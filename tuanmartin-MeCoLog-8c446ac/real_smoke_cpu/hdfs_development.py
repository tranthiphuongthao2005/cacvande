"""Export frozen HDFS pools and evaluate only the development pools."""

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from hdfs_protocol import sha
from run import ZipText
from preprocess import parameters
from preprocess.__main__ import peak_working_set_mib
from preprocess.datasets import BLOCK, LABELS, Line, Sequence
from preprocess.embeddings import embed_templates
from preprocess.npz_io import validate_arrays, vocabulary_manifest, write_split
from preprocess.parsing import DrainAdapter

NAMES = {
    "development_support": "hdfs_dev_support",
    "development_query": "hdfs_dev_query",
    "final_support": "hdfs_final_support",
    "final_query": "hdfs_final_query",
}
WINDOW = 50
META = ("key_vocab_size", "char_vocab_size", "max_params", "max_chars")
OLD = HERE / "preprocessed_data"
BASE = HERE / "baseline100_seed123"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, obj):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, indent=2, allow_nan=False)


def digest(path, algorithm="sha256"):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verified_inputs():
    old = read_json(OLD / "manifest.json")
    protocol = read_json(HERE / "hdfs_protocol_seed123.json")
    train = read_json(BASE / "training_audit.json")
    vocab_info = old["vocabulary"]
    vocab = parameters.Vocabulary(vocab_info["keys"], vocab_info["chars"])
    require(vocabulary_manifest(vocab) == vocab_info and
            vocab_info["sha256"] == train["vocabulary_sha256"], "Vocabulary checksum mismatch")
    require(sha(protocol["pools"]) == protocol["split_sha256"] == train["hdfs_protocol_sha256"],
            "HDFS protocol checksum mismatch")
    require(digest(OLD / "BGL_training.npz") == train["bgl_training_sha256"], "Source NPZ changed")
    return old, protocol, train, vocab


def readonly_hashes(checkpoint):
    paths = [*ROOT.glob("*.py"), *OLD.glob("*.npz"), checkpoint]
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def source_sequences(old, protocol, archive_path):
    fit = old["splits"]["HDFS"]["training"]
    require(len(fit) == 204, "Expected exactly 204 old HDFS training sessions")
    expected = {row["id"]: (row["label"], row["line_ids"]) for row in fit}
    used_ids = {row["id"] for split in old["splits"]["HDFS"].values() for row in split}
    used_lines = {line for split in old["splits"]["HDFS"].values() for row in split for line in row["line_ids"]}
    for name, pool in protocol["pools"].items():
        require(sha(pool) == protocol["summary"][name]["sha256"], f"Pool checksum mismatch: {name}")
        counts = Counter(row["label"] for row in pool)
        expected_class_size = 20 if name.endswith("support") else 100
        require(counts == {"Normal": expected_class_size, "Anomaly": expected_class_size},
                f"Wrong classes: {name}")
        for row in pool:
            block, lines = row["block_id"], row["raw_line_ids"]
            require(block not in used_ids and len(lines) <= WINDOW and bool(lines)
                    and lines == sorted(set(lines)) and not used_lines.intersection(lines),
                    f"Invalid or shared pool lineage for {block}")
            used_ids.add(block)
            used_lines.update(lines)
            expected[block] = (LABELS[row["label"]], lines)

    found = defaultdict(list)
    records = {}
    with ZipFile(archive_path) as archive:
        official = {}
        with ZipText(archive, "anomaly_label.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                block = row["BlockId"]
                if block in expected:
                    require(block not in official and row["Label"] in LABELS,
                            f"Invalid or duplicate label for {block}")
                    official[block] = LABELS[row["Label"]]
        fitted = {row["id"] for row in fit}
        with ZipText(archive, "HDFS.log").open(encoding="utf-8", errors="replace") as stream:
            for number, raw in enumerate(stream, 1):
                blocks = {match.group() for match in BLOCK.finditer(raw)}
                selected = blocks & expected.keys()
                if selected:
                    require(len(blocks) == 1 or selected <= fitted,
                            f"New pool includes shared raw line {number}")
                    for block in selected:
                        found[block].append(number)
                    records[number] = Line(number, raw.strip())
    for block, (label, lines) in expected.items():
        require(official.get(block) == label and found[block] == lines, f"Raw lineage/label mismatch: {block}")

    def sequence(block):
        label, lines = expected[block]
        return Sequence(block, label, tuple(records[i] for i in lines))

    return [sequence(row["id"]) for row in fit], {
        name: [sequence(row["block_id"]) for row in pool] for name, pool in protocol["pools"].items()
    }, number


def feature_stats(path, sequences, events, uncapped, misses, known_templates, vocab):
    counts = Counter()
    with np.load(path, allow_pickle=False) as arrays:
        validate_arrays(arrays, WINDOW, vocab, [len(s.lines) for s in sequences])
        require(arrays["y"].argmax(1).tolist() == [s.label for s in sequences], "Export labels differ")
        keys, chars = arrays["p_key"], arrays["p_val"]
        counts.update(key_ids=int(np.count_nonzero(keys)), key_unk=int((keys == 1).sum()),
                      char_ids=int(np.count_nonzero(chars)), char_unk=int((chars == 1).sum()))
        shape = {name: {"shape": list(arrays[name].shape), "dtype": str(arrays[name].dtype)}
                 for name in arrays.files}
    templates = set()
    for seq in sequences:
        counts["padding_slots"] += WINDOW - len(seq.lines)
        for line in seq.lines:
            counts["events"] += 1
            raw = uncapped[line.id]
            counts["parameters_dropped_P"] += max(len(raw) - parameters.P, 0)
            counts["events_over_P"] += len(raw) > parameters.P
            counts["fallback_events"] += line.id in misses
            templates.add(events[line.id].template)
            for param in raw[:parameters.P]:
                if param.kind in (parameters.PATH, parameters.STR):
                    length = len(parameters.character_value(param))
                    counts["string_path_values"] += 1
                    counts["values_truncated_C"] += length > parameters.C
                    counts["characters_dropped_C"] += max(length - parameters.C, 0)
    return {**counts, "padding_ratio": counts["padding_slots"] / (len(sequences) * WINDOW),
            "template_count": len(templates), "unseen_template_count": len(templates - known_templates),
            "unseen_templates": sorted(templates - known_templates),
            "shapes_dtypes": shape, "npz_sha256": digest(path)}


def features(output):
    started = time.perf_counter()
    require(not output.exists(), "Choose a new feature directory")
    old, protocol, train, vocab = verified_inputs()
    checkpoint = BASE / train["checkpoint"]
    protected = readonly_hashes(checkpoint)
    require(digest(checkpoint) == train["checkpoint_sha256"], "Checkpoint SHA256 mismatch")
    archive = HERE / "archives/HDFS_v1.zip"
    archive_md5 = digest(archive, "md5")
    require(archive_md5 == protocol["archive_md5"] == "76a24b4d9a6164d543fb275f89773260",
            "Official HDFS archive checksum mismatch")
    prov = read_json(HERE / "provenance.json")
    revision = prov["sbert_revision"]
    require(revision == "b404353e5a0ef9cdf6a4500baa81aaec875d4db0", "Unexpected SBERT revision")
    sbert_files = {}
    for item in prov["files"]:
        path = HERE / item["path"]
        if not path.is_relative_to(HERE / "sbert"):
            continue
        algorithm, expected = item["checksum"].split(":")
        require(path.stat().st_size == item["bytes"], f"Snapshot size changed: {path}")
        actual = (hashlib.sha1(f"blob {item['bytes']}\0".encode() + path.read_bytes()).hexdigest()
                  if algorithm == "git-sha1" else digest(path, algorithm))
        require(actual == expected, f"Snapshot checksum changed: {path}")
        sbert_files[item["path"]] = item["checksum"]
    require("sbert\\model.safetensors" in sbert_files or "sbert/model.safetensors" in sbert_files,
            "Missing model checksum")
    fit, pools, scanned = source_sequences(old, protocol, archive)
    drain = DrainAdapter("HDFS")
    drain.fit(fit)
    reference = {r["line_id"]: (r["event_id"], r["template"]) for r in map(
        json.loads, (OLD / "HDFS_events.jsonl").read_text(encoding="utf-8").splitlines())}
    observed = {i: (event.event_id, event.template) for i, event in drain.transform(fit).items()}
    require(observed == {i: reference[i] for i in {line.id for seq in fit for line in seq.lines}},
            "Old Drain template/EventId replay did not match")
    known = {template for _, template in observed.values()}
    frozen = {i: tuple(cluster.logTemplate) for i, cluster in drain.training_clusters.items()}
    events, misses, uncapped = {}, set(), {}
    for sequences in pools.values():
        lines = list(drain.unique_lines(sequences))
        for line in lines:
            if drain.parser.treeSearch(drain.root, drain.tokens(drain.content(line))) is None:
                misses.add(line.id)
        parsed = drain.transform(sequences)
        events.update((line.id, parsed[line.id]) for line in lines)
        with patch.object(parameters, "P", sys.maxsize):
            for line in lines:
                uncapped[line.id] = parameters.extract_parameters(drain.content(line), parsed[line.id].template)
    require(frozen == {i: tuple(c.logTemplate) for i, c in drain.training_clusters.items()},
            "Frozen Drain templates changed")
    templates = {event.template for event in events.values()}
    vectors = embed_templates(templates, HERE / "sbert", 4)
    output.mkdir()
    statistics = {}
    for name, sequences in pools.items():
        path = output / (NAMES[name] + ".npz")
        write_split(path, sequences, events, vectors, vocab, WINDOW)
        statistics[name] = feature_stats(path, sequences, events, uncapped, misses, known, vocab)
    with (output / "events.jsonl").open("x", encoding="utf-8") as stream:
        for event in events.values():
            stream.write(json.dumps({"line_id": event.line_id, "event_id": event.event_id,
                                     "template": event.template}) + "\n")
    require(protected == readonly_hashes(checkpoint), "Protected inputs changed")
    save(output / "feature_manifest.json", {
        "protocol_sha256": protocol["split_sha256"], "protocol_seed": protocol["seed"],
        "archive_md5": archive_md5, "raw_lines_scanned": scanned, "sbert_revision": revision,
        "sbert_files": sbert_files, "sbert_batch_size": 4, "vocabulary_sha256": old["vocabulary"]["sha256"],
        "window": WINDOW, "drain_threshold": 0.5, "drain_depth": 4,
        "drain_fit_sessions": len(fit), "drain_fit_replayed_lines": len(observed),
        "drain_fit_template_count": len(known), "drain_fit_event_mapping_sha256": sha(observed),
        "drain_fit_block_ids": [seq.id for seq in fit], "unique_new_pool_templates": len(templates),
        "unique_unseen_templates": len(templates - known),
        "statistics": statistics, "protected_sha256": protected,
        "pools": {name: [{"sequence_id": seq.id, "label": seq.label, "true_length": len(seq.lines),
                         "raw_line_ids": [line.id for line in seq.lines]} for seq in seqs]
                  for name, seqs in pools.items()},
        "seconds": time.perf_counter() - started, "peak_working_set_mib": peak_working_set_mib(),
    })
    print(f"Replayed {len(observed)} old lines. Exported four pools with {len(templates)} templates.", flush=True)


def metrics(y, score):
    from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
    pred = score > 0
    output = {"class_counts": np.bincount(y, minlength=2).tolist(),
              "confusion_matrix": confusion_matrix(y, pred, labels=[0, 1]).tolist()}
    for average in ("binary", "macro"):
        p, r, f, _ = precision_recall_fscore_support(y, pred, labels=[0, 1], average=average, zero_division=0)
        output[average] = dict(precision=p, recall=r, f1=f)
    both = len(np.unique(y)) == 2
    output["roc_auc"] = roc_auc_score(y, score) if both else None
    output["average_precision"] = average_precision_score(y, score) if both else None
    return output


def evaluate(output):
    start = time.perf_counter()
    import torch
    from model import Model

    torch.set_num_threads(2)
    _, protocol, train, vocab = verified_inputs()
    manifest = read_json(output / "feature_manifest.json")
    checkpoint = BASE / train["checkpoint"]
    require(manifest["protected_sha256"] == readonly_hashes(checkpoint), "Protected input checksum mismatch")
    require(manifest["protocol_sha256"] == protocol["split_sha256"] and
            manifest["vocabulary_sha256"] == train["vocabulary_sha256"], "Feature provenance mismatch")
    require(digest(checkpoint) == train["checkpoint_sha256"], "Checkpoint checksum mismatch")
    require(not (output / "development_metrics.json").exists() and
            not (output / "development_predictions.csv").exists(), "Development output already exists")
    state = torch.load(checkpoint, weights_only=True, map_location="cpu")["net"]
    model = Model(num_layers=1, window_size=WINDOW, nhead=8, **train["metadata"]).eval()
    loaded = model.load_state_dict(state, strict=True)

    @torch.inference_mode()
    def read_dev(name):
        require(name in ("development_support", "development_query"), "Development only")
        rows = manifest["pools"][name]
        original = protocol["pools"][name]
        require([r["sequence_id"] for r in rows] == [r["block_id"] for r in original],
                "ID order differs from locked protocol")
        path = output / (NAMES[name] + ".npz")
        require(digest(path) == manifest["statistics"][name]["npz_sha256"], "Development NPZ changed")
        with np.load(path, allow_pickle=False) as d:
            arrays = {key: d[key] for key in d.files}
        validate_arrays(arrays, WINDOW, vocab, [r["true_length"] for r in rows])
        require({k: int(arrays[k]) for k in META} == train["metadata"], "Checkpoint metadata mismatch")
        values = [torch.from_numpy(arrays[k]) for k in ("x", "p_key", "p_type", "p_val", "p_num")]
        chunks = [model(values[0][i:i + 8], tuple(x[i:i + 8] for x in values[1:]))
                  for i in range(0, len(rows), 8)]
        z = torch.nn.functional.normalize(torch.cat(chunks), dim=1)
        y = arrays["y"].argmax(1)
        require(torch.isfinite(z).all().item() and y.tolist() == [r["label"] for r in rows] ==
                [LABELS[r["label"]] for r in original], "Invalid labels or embeddings")
        return rows, z, y

    support, zs, ys = read_dev("development_support")
    query, zq, yq = read_dev("development_query")
    qids = [r["sequence_id"] for r in query]
    require(not set(qids).intersection(r["sequence_id"] for r in support)
            and len(set(qids)) == 200 and np.bincount(yq).tolist() == [100, 100],
            "Invalid development pool")
    lengths = np.array([r["true_length"] for r in query])
    results, predictions = {}, []
    masks = {"2-4": lengths <= 4, "5-19": (lengths >= 5) & (lengths < 20),
             "20-29": (lengths >= 20) & (lengths < 30), "30-50": lengths >= 30}
    for k in (2, 5, 10):
        groups = [np.flatnonzero(ys == c)[:k] for c in (0, 1)]
        prototypes = torch.nn.functional.normalize(torch.stack([zs[g].mean(0) for g in groups]), dim=1)
        normal = (zq @ prototypes[0:1].T).flatten().numpy()
        anomaly = (zq @ prototypes[1:2].T).flatten().numpy()
        score = anomaly - normal
        require(np.isfinite(score).all(), "Nonfinite prototype scores")
        pred = (score > 0).astype(int)
        matrix = metrics(yq, score)
        matrix["prototype_cosine"] = (prototypes[0] @ prototypes[1]).item()
        matrix["support_ids"] = [[support[i]["sequence_id"] for i in group] for group in groups]
        matrix["by_length"] = {name: metrics(yq[mask], score[mask]) for name, mask in masks.items() if mask.any()}
        matrix["score_quantiles_min_q25_median_q75_max"] = {
            label: np.quantile(score[yq == c], [0, .25, .5, .75, 1]).tolist()
            for c, label in ((0, "Normal"), (1, "Anomaly"))}
        matrix["fn_length_counts"] = {n: int(((yq == 1) & (pred == 0) & m).sum()) for n, m in masks.items()}
        matrix["fp_length_counts"] = {n: int(((yq == 0) & (pred == 1) & m).sum()) for n, m in masks.items()}
        results[k] = matrix
        predictions.extend(zip([k] * len(qids), qids, lengths, yq, pred, normal, anomaly, score))
    require(all(torch.equal(value, state[key]) for key, value in model.state_dict().items()),
            "Checkpoint tensors changed during evaluation")
    with (output / "development_predictions.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("shots_per_class", "block_id", "length", "label", "prediction",
                         "cos_normal", "cos_anomaly", "score"))
        writer.writerows(predictions)
    save(output / "development_metrics.json", {
        "checkpoint_sha256": train["checkpoint_sha256"], "checkpoint_tensors": len(state),
        "strict_load": str(loaded), "threshold": 0, "device": "cpu",
        "query_ids_sha256": sha(qids), "query_count": len(qids), "results": results,
        "seconds": time.perf_counter() - start, "peak_working_set_mib": peak_working_set_mib(),
    })
    print(f"Development only: {len(qids)} fixed queries, support 2/5/10 per class.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("features", "evaluate"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    (features if args.stage == "features" else evaluate)(args.output.resolve())
