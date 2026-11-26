import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np
import torch
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from model import Model
from preprocess import parameters
from preprocess.datasets import Line
from preprocess.parsing import DrainAdapter
from run import ZipText

DATA = HERE / "preprocessed_data"
SMOKE = HERE / "meta_smoke_seed123"


def stats(x):
    return dict(zip(("min", "q25", "median", "q75", "max"), np.quantile(x, [0, .25, .5, .75, 1]).tolist()))


def correlate(a, b):
    return float(spearmanr(a, b).statistic)


def main(output):
    output.mkdir()
    manifest = json.loads((DATA / "manifest.json").read_text())
    audit = json.loads((SMOKE / "testing_audit.json").read_text())
    train = json.loads((SMOKE / "training_audit.json").read_text())
    validation = json.loads((DATA / "validation.json").read_text())
    ckpt = SMOKE / train["checkpoint"]
    with ckpt.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == train["checkpoint_sha256"]
    assert manifest["vocabulary"]["sha256"] == train["vocabulary_sha256"] == validation["vocabulary_sha256"]
    with (SMOKE / "query_predictions.csv").open(newline="") as stream:
        records = list(csv.DictReader(stream))
    ids = [r["sequence_id"] for r in records]
    assert ids == audit["query_ids"] and len(set(ids)) == 48 and not set(ids) & set(audit["support_ids"])
    truth = np.array([int(r["label"]) for r in records])
    pred = np.array([int(r["prediction"]) for r in records])
    saved = np.array([float(r["anomaly_score"]) for r in records])
    assert np.isfinite(saved).all() and np.array_equal(saved > 0, pred)
    fn, tp = (truth == 1) & (pred == 0), (truth == 1) & (pred == 1)
    groups = {"normal": truth == 0, "anomaly": truth == 1, "fn": fn, "tp": tp}
    report = {"query_count": len(ids), "metrics": {}, "scores": {k: stats(saved[v]) for k, v in groups.items()}}
    for avg in ("binary", "macro"):
        p, r, f, _ = precision_recall_fscore_support(truth, pred, labels=[0, 1], average=avg, zero_division=0)
        vals = dict(precision=p, recall=r, f1=f)
        assert all(np.isclose(v, audit["metrics"][avg][k]) for k, v in vals.items())
        report["metrics"][avg] = vals
    report.update(roc_auc=roc_auc_score(truth, saved), average_precision=average_precision_score(truth, saved),
                  confusion=confusion_matrix(truth, pred, labels=[0, 1]).tolist(),
                  fn_vs_normal_auc=roc_auc_score(np.r_[np.zeros(sum(truth == 0)), np.ones(sum(fn))],
                                                 np.r_[saved[truth == 0], saved[fn]]))
    assert np.isclose(report["roc_auc"], audit["roc_auc"])
    assert np.isclose(report["average_precision"], audit["average_precision"])
    assert report["confusion"] == audit["confusion_matrix"]

    sequences = manifest["splits"]["HDFS"]["testing"]
    pos = {s["id"]: i for i, s in enumerate(sequences)}
    all_ids = audit["support_ids"] + ids
    indices = [pos[i] for i in all_ids]
    lengths = np.array([len(sequences[i]["line_ids"]) for i in indices])
    assert np.array_equal(truth, [sequences[i]["label"] for i in indices[4:]])
    with np.load(DATA / "HDFS_testing.npz", allow_pickle=False) as a:
        y = a["y"].argmax(axis=1)[indices]
        x, *params = [torch.from_numpy(a[k][indices]) for k in ("x", "p_key", "p_type", "p_val", "p_num")]
        metadata = {k: int(a[k]) for k in ("key_vocab_size", "char_vocab_size", "max_params", "max_chars")}
    assert np.array_equal(y[4:], truth) and np.array_equal(np.bincount(y[:4]), [2, 2])
    assert lengths.max() <= 50
    torch.set_num_threads(2)
    model = Model(num_layers=1, window_size=64, nhead=8, **metadata).eval()
    state = torch.load(ckpt, weights_only=True, map_location="cpu")["net"]
    model.load_state_dict(state, strict=True)

    def resize(t, width):
        if width <= 50:
            return t[:, :width].contiguous()
        return torch.cat((t, t.new_zeros((len(t), width - 50, *t.shape[2:]))), dim=1)

    def encode(width):
        rows = []
        for start, end in [(0, 4), *((i, min(i + 8, len(all_ids))) for i in range(4, len(all_ids), 8))]:
            inputs = [resize(t[start:end], width) for t in (x, *params)]
            rows.append(torch.nn.functional.normalize(model(inputs[0], tuple(inputs[1:])), dim=1))
        z = torch.cat(rows)
        prototypes = torch.nn.functional.normalize(torch.stack([z[:4][y[:4] == c].mean(0) for c in (0, 1)]), dim=1)
        similarities = z[4:] @ prototypes.T
        scores = similarities[:, 1] - similarities[:, 0]
        assert torch.isfinite(z).all() and torch.isfinite(scores).all()
        return z, prototypes, similarities.numpy(), scores.numpy()

    with torch.inference_mode():
        z, prototypes, sim, base = encode(50)
        assert np.allclose(saved, base, rtol=0, atol=2e-6)
        assert np.array_equal(base > 0, pred)
        report["max_score_replay_difference"] = float(abs(saved - base).max())
        report["prototype_cosine"] = float(prototypes[0] @ prototypes[1])
        report["embedding_pair_cosine"] = {}
        for key, a, b in (("normal_within", 0, 0), ("anomaly_within", 1, 1), ("between", 0, 1)):
            left, right = z[4:][truth == a], z[4:][truth == b]
            pairs = left @ right.T
            report["embedding_pair_cosine"][key] = stats(pairs[torch.triu_indices(len(left), len(right), 1).unbind()]
                                                          if a == b else pairs.flatten())
        report["prototype_similarities"] = {k: {"normal": stats(sim[v, 0]), "anomaly": stats(sim[v, 1])}
                                            for k, v in groups.items()}
        report["padding_probe"] = {}
        for width in sorted({int(lengths.max()), 64} - {50}):
            alt_z, _, _, alt = encode(width)
            delta = abs(alt - base)
            report["padding_probe"][width] = {
                "max_abs_score_change": float(delta.max()), "mean_abs_score_change": float(delta.mean()),
                "score_rank_spearman": correlate(base, alt),
                "sign_flips": int(sum((alt > 0) != (base > 0))),
                "embedding_cosine_to_baseline": stats((alt_z[4:] * z[4:]).sum(1).numpy()),
                "diagnostic_roc_auc": roc_auc_score(truth, alt),
            }
    assert all(torch.equal(t, state[k]) for k, t in model.state_dict().items())
    qlen = lengths[4:]
    report["length_padding"] = {k: {"length": stats(qlen[v]), "padding": stats(1 - qlen[v] / 50)}
                                for k, v in groups.items()}
    report["length_score_spearman"] = {k: correlate(qlen[v], saved[v]) for k, v in {
        "all": np.ones(len(ids), bool), "normal": truth == 0, "anomaly": truth == 1}.items()}
    details = [{"id": i, "label": int(t), "prediction": int(p), "score": float(s), "length": int(l),
                "padding": 1 - int(l) / 50, "cos_normal": float(cs[0]), "cos_anomaly": float(cs[1])}
               for i, t, p, s, l, cs in zip(ids, truth, pred, saved, qlen, sim)]
    report["nearest_boundary"] = sorted(details, key=lambda r: abs(r["score"]))[:5]
    report["lowest_fn"] = sorted((r for r in details if r["label"] and not r["prediction"]),
                                 key=lambda r: r["score"])[:5]
    with (output / "query_cosines.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=details[0])
        writer.writeheader()
        writer.writerows(details)
    report["preprocessing"] = audit_features(manifest)
    (output / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))


def audit_features(manifest):
    results = {}
    vocab = parameters.Vocabulary(manifest["vocabulary"]["keys"], manifest["vocabulary"]["chars"])
    for domain, width, filename in (("BGL", 20, "BGL.zip"), ("HDFS", 50, "HDFS_v1.zip")):
        splits = manifest["splits"][domain]
        mapped = {r["line_id"]: r["template"] for r in map(json.loads, (DATA / f"{domain}_events.jsonl").read_text().splitlines())}
        retained = {line for seqs in splits.values() for seq in seqs for line in seq["line_ids"][:width]}
        adapter = DrainAdapter(domain)
        extracted = {}
        with ZipFile(HERE / "archives" / filename) as archive:
            with ZipText(archive, domain + ".log").open(encoding="utf-8", errors="replace") as stream, patch.object(
                parameters, "P", sys.maxsize
            ):
                last = max(retained)
                for line, raw in enumerate(stream, 1):
                    if line in retained:
                        content = adapter.content(Line(line, raw.strip()))
                        extracted[line] = parameters.extract_parameters(content, mapped[line])
                    if line == last:
                        break
        assert retained == extracted.keys()
        for split, seqs in splits.items():
            counts = Counter()
            types = Counter()
            keys_oov = Counter()
            signatures = defaultdict(Counter)
            with np.load(DATA / f"{domain}_{split}.npz", allow_pickle=False) as a:
                keys, kinds, chars, nums = [a[k] for k in ("p_key", "p_type", "p_val", "p_num")]
                embeds = a["x"]
            for j, seq in enumerate(seqs):
                length = min(len(seq["line_ids"]), width)
                signature = hashlib.sha256()
                for item in (embeds, keys, kinds, chars, nums):
                    signature.update(item[j, :length].tobytes())
                signatures[signature.hexdigest()][seq["label"]] += 1
                for k, line in enumerate(seq["line_ids"][:width]):
                    raw = extracted[line]
                    counts["events"] += 1
                    counts["events_exceed_P"] += len(raw) > 8
                    counts["parameters_dropped"] += max(len(raw) - 8, 0)
                    counts["parameters"] += len(raw[:8])
                    encoded = parameters.encode_parameters(raw, vocab)
                    assert all(np.array_equal(x, a[j, k]) for x, a in zip(encoded, (keys, kinds, chars, nums)))
                    counts["unk_keys"] += int(sum(keys[j, k] == 1))
                    counts["char_ids"] += int((chars[j, k] != 0).sum())
                    counts["unk_chars"] += int((chars[j, k] == 1).sum())
                    for p in raw[:8]:
                        types[p.kind] += 1
                        if p.key not in vocab.keys:
                            keys_oov[p.key] += 1
                        if p.kind in (parameters.PATH, parameters.STR):
                            length = len(parameters.character_value(p))
                            counts["string_path_values"] += 1
                            counts["values_exceed_C"] += length > 16
                            counts["characters_dropped"] += max(length - 16, 0)
            counts["distinct_full_inputs"] = len(signatures)
            counts["mixed_label_identical_input_groups"] = sum(len(group) > 1 for group in signatures.values())
            counts["samples_in_mixed_label_identical_groups"] = sum(sum(g.values()) for g in signatures.values() if len(g) > 1)
            results[domain + "_" + split] = {"counts": dict(counts), "types": dict(types), "unk_keys_top": keys_oov.most_common(5)}
    return results


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
