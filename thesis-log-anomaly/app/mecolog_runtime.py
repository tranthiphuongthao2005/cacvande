"""Offline diagnostics and read-only access to the original MeCoLog components."""

import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from app.trace_store import EVENTS, SERVICES

WINDOW = 50
DIM = 768
PARAMS = 8
CHARS = 16
CHECKPOINT_SHA = "713d1ec5a4c34d9a091abea9dc2430c0e9500a9255e0bbc7307a6edfa053c5f0"
VOCAB_SHA = "087874c66d0fabaeb2ab52cd36d05d6720389f3dc033834f90dac50e1c928e3d"
SBERT_REVISION = "b404353e5a0ef9cdf6a4500baa81aaec875d4db0"
CHECKPOINT = "baseline100_seed123/checkpoints/meta_11222247_BGL_1_8_1e-05_baseline100-latest.pt"


def digest(path, algorithm="sha256", prefix=b""):
    output = hashlib.new(algorithm, prefix)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            output.update(block)
    return output.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def bind_research(root):
    root = Path(root).resolve(strict=True)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from importlib.util import find_spec
    for name in ("model", "Drain", "preprocess.parsing", "preprocess.parameters",
                 "preprocess.embeddings", "preprocess.npz_io"):
        spec = find_spec(name)
        if not spec or not spec.origin or not Path(spec.origin).resolve().is_relative_to(root):
            raise ValueError(f"Unexpected research module origin: {name}")
    return root / "real_smoke_cpu"


def load_encoder(root):
    run = bind_research(root)
    import torch
    from model import Model

    checkpoint = run / CHECKPOINT
    if digest(checkpoint) != CHECKPOINT_SHA:
        raise ValueError("Checkpoint checksum mismatch")
    state = torch.load(checkpoint, weights_only=True, map_location="cpu")["net"]
    if len(state) != 32 or not all(isinstance(value, torch.Tensor) for value in state.values()):
        raise ValueError("Unexpected checkpoint tensor count/types")
    model = Model(num_layers=1, nhead=8, window_size=WINDOW, dim=DIM, max_params=PARAMS,
                  max_chars=CHARS, key_vocab_size=12, char_vocab_size=42)
    model.load_state_dict(state, strict=True)
    model.eval().requires_grad_(False)
    if digest(checkpoint) != CHECKPOINT_SHA:
        raise ValueError("Checkpoint changed during loading")
    return FrozenEncoder(model)


class FrozenEncoder:
    def __init__(self, model):
        self.model = model

    def encode(self, arrays):
        import torch
        with torch.inference_mode():
            x, *params = (torch.from_numpy(array) for array in validate_arrays(arrays))
            embedding = self.model.encode(x, tuple(params))
            if embedding.shape != (len(x), DIM) or not torch.isfinite(embedding).all():
                raise ValueError("Invalid MeCoLog embedding")
        return embedding


def validate_arrays(arrays):
    import numpy as np
    n = len(arrays["x"])
    schema = {
        "x": ((n, WINDOW, DIM), np.float32, None),
        "p_key": ((n, WINDOW, PARAMS), np.int64, 12),
        "p_type": ((n, WINDOW, PARAMS), np.int64, 5),
        "p_val": ((n, WINDOW, PARAMS, CHARS), np.int64, 42),
        "p_num": ((n, WINDOW, PARAMS), np.float32, None),
    }
    if not 0 < n <= 8 or set(arrays) != set(schema):
        raise ValueError("Invalid inference batch")
    for name, (shape, dtype, upper) in schema.items():
        arr = arrays[name]
        if arr.shape != shape or arr.dtype != dtype or not np.isfinite(arr).all():
            raise ValueError(f"Invalid tensor: {name}")
        if upper is not None and (np.any(arr < 0) or np.any(arr >= upper)):
            raise ValueError(f"Invalid tensor IDs: {name}")
    return tuple(arrays[name] for name in schema)


def source_drain(run, manifest):
    from preprocess.parsing import DrainAdapter

    train = manifest["splits"]["HDFS"]["training"]
    if len(train) != 204:
        raise ValueError("Unexpected historical Drain training session count")
    ids = {line for row in train for line in row["line_ids"]}
    archive = run / "archives/HDFS_v1.zip"
    if digest(archive, "md5") != "76a24b4d9a6164d543fb275f89773260":
        raise ValueError("HDFS archive mismatch")
    lines = []
    with ZipFile(archive) as zipped:
        [name] = [name for name in zipped.namelist() if name.rsplit("/", 1)[-1] == "HDFS.log"]
        with zipped.open(name) as raw, io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as stream:
            last = max(ids)
            for number, content in enumerate(stream, 1):
                if number in ids:
                    lines.append(SimpleNamespace(id=number, text=content.strip()))
                if number == last:
                    break
    if len(lines) != len(ids):
        raise ValueError("Historical Drain training lines missing")
    drain = DrainAdapter("HDFS")
    sequence = [SimpleNamespace(lines=lines)]
    drain.fit(sequence)
    with (run / "preprocessed_data/HDFS_events.jsonl").open(encoding="utf-8") as stream:
        reference = {row["line_id"]: (row["event_id"], row["template"]) for row in map(json.loads, stream)
                     if row["line_id"] in ids}
    observed = {key: (event.event_id, event.template) for key, event in drain.transform(sequence).items()}
    if observed != reference:
        raise ValueError("Frozen Drain replay mismatch")
    return drain, len(observed)


def verified_sbert(run):
    provenance = read(run / "provenance.json")
    if provenance["sbert_revision"] != SBERT_REVISION:
        raise ValueError("Unexpected SBERT revision")
    verified = set()
    for item in provenance["files"]:
        path = Path(item["path"].replace("\\", "/"))
        if not path.is_relative_to("sbert"):
            continue
        algorithm, expected = item["checksum"].split(":")
        file = run / path
        size = file.stat().st_size
        if algorithm == "git-sha1":
            actual = digest(file, "sha1", f"blob {size}\0".encode())
        else:
            actual = digest(file, algorithm)
        if size != item["bytes"] or actual != expected:
            raise ValueError(f"SBERT fingerprint mismatch: {path}")
        verified.add(file.resolve())
    local = run / "sbert"
    if (local / "model.safetensors").resolve() not in verified or verified != {
        path.resolve() for path in local.rglob("*") if path.is_file()
    }:
        raise ValueError("Unexpected SBERT snapshot files")
    return local


def normalized_event(event):
    if event.service_name not in SERVICES or event.event_name not in EVENTS:
        raise ValueError("Unsupported application event")
    core = f"{event.service_name} {event.event_name} {event.level}"
    return core if event.http_status is None else f"{core} status={event.http_status}"


def build_candidates(sessions, drain, vocab, embed, parse=None):
    """Produce diagnostic candidates. JSON-to-Content lineage is not yet approved."""
    import numpy as np
    from preprocess.parameters import UNK, encode_parameters, extract_parameters
    from preprocess.npz_io import DIM as source_dim
    from preprocess.parameters import C, P

    if not 0 < len(sessions) <= 8 or (source_dim, P, C) != (DIM, PARAMS, CHARS):
        raise ValueError("Unsupported candidate batch/schema")
    parsed = []
    for session in sessions:
        rows = []
        for event in session.events[:WINDOW]:
            if parse is not None:
                rows.append(parse(session.trace_id, event))
                continue
            content = normalized_event(event)
            tokens = drain.tokens(content)
            cluster = drain.parser.treeSearch(drain.root, tokens)
            template = " ".join(tokens if cluster is None else cluster.logTemplate)
            parameters = extract_parameters(content, template)
            rows.append((template, cluster is None, parameters))
        parsed.append(rows)
    vectors = embed([template for rows in parsed for template, _, _ in rows])
    n = len(sessions)
    arrays = {
        "x": np.zeros((n, WINDOW, DIM), np.float32),
        "p_key": np.zeros((n, WINDOW, P), np.int64),
        "p_type": np.zeros((n, WINDOW, P), np.int64),
        "p_val": np.zeros((n, WINDOW, P, C), np.int64),
        "p_num": np.zeros((n, WINDOW, P), np.float32),
    }
    reports = []
    for i, (session, rows) in enumerate(zip(sessions, parsed)):
        for j, (template, _, parameters) in enumerate(rows):
            arrays["x"][i, j] = vectors[template]
            for key, value in zip(("p_key", "p_type", "p_val", "p_num"), encode_parameters(parameters, vocab)):
                arrays[key][i, j] = value
        keys, chars = arrays["p_key"][i], arrays["p_val"][i]
        reports.append({"trace_id": session.trace_id, "true_length": len(session.events),
                        "encoded_events": len(rows), "padding_events": WINDOW - len(rows),
                        "truncated_events": len(session.events) - len(rows),
                        "unseen_templates_events": sum(miss for _, miss, _ in rows),
                        "key_oov": int((keys == UNK).sum()), "key_total": int(np.count_nonzero(keys)),
                        "char_oov": int((chars == UNK).sum()), "char_total": int(np.count_nonzero(chars))})
    validate_arrays(arrays)
    return arrays, reports


def candidate_resources(root):
    run = bind_research(root)
    from preprocess.embeddings import embed_templates
    from preprocess.npz_io import vocabulary_manifest
    from preprocess.parameters import Vocabulary

    manifest = read(run / "preprocessed_data/manifest.json")
    mapping = manifest["vocabulary"]
    vocab = Vocabulary(mapping["keys"], mapping["chars"])
    if vocabulary_manifest(vocab) != mapping or mapping["sha256"] != VOCAB_SHA:
        raise ValueError("Frozen vocabulary mismatch")
    snapshot = verified_sbert(run)
    drain, count = source_drain(run, manifest)
    return drain, vocab, lambda templates: embed_templates(templates, snapshot, 4), count
