"""Audit support selection on frozen development embeddings."""

import csv
import sys
import time
from pathlib import Path

import numpy as np
import torch
from scipy.stats import spearmanr
from torch.nn import functional as F

from hdfs_development import (
    BASE, HERE, META, NAMES, WINDOW, digest, metrics, peak_working_set_mib,
    read_json, readonly_hashes, require, save, sha, validate_arrays, verified_inputs,
)

FEATURES = HERE / "hdfs_locked_features_seed123"
SEEDS = tuple(range(1000, 1020))
SHOTS = (2, 5, 10)
CLASSES = ("Normal", "Anomaly")


def summary(values):
    a = np.asarray([v for v in values if v is not None], dtype=float)
    if not len(a):
        return None
    q5, median, q95 = np.quantile(a, [.05, .5, .95])
    return dict(n=len(a), mean=float(a.mean()), std=float(a.std(ddof=1)) if len(a) > 1 else None,
                median=float(median), min=float(a.min()), max=float(a.max()),
                p05=float(q5), p95=float(q95))


def correlation(length, score, mask):
    length, score = length[mask], score[mask]
    if len(np.unique(length)) < 2 or len(np.unique(score)) < 2:
        return None
    return float(spearmanr(length, score).statistic)


def score_stats(y, score):
    return {name: summary(score[y == cls]) for cls, name in enumerate(CLASSES)}


def write_csv(path, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@torch.inference_mode()
def encode_dev(name, model, manifest, protocol, vocab, metadata):
    require(name in ("development_support", "development_query"), "Development only")
    rows = manifest["pools"][name]
    locked = protocol["pools"][name]
    require([(r["sequence_id"], r["raw_line_ids"], r["true_length"]) for r in rows] ==
            [(r["block_id"], r["raw_line_ids"], len(r["raw_line_ids"])) for r in locked],
            "Locked lineage mismatch")
    path = FEATURES / (NAMES[name] + ".npz")
    expected_sha = manifest["statistics"][name]["npz_sha256"]
    require(digest(path) == expected_sha, "Feature checksum mismatch")
    with np.load(path, allow_pickle=False) as source:
        a = {k: source[k] for k in source.files}
    validate_arrays(a, WINDOW, vocab, [r["true_length"] for r in rows])
    require({k: int(a[k]) for k in META} == metadata, "Model metadata differs")
    y = a["y"].argmax(1)
    require(y.tolist() == [r["label"] for r in rows] ==
            [int(r["label"] == "Anomaly") for r in locked], "Labels differ")
    x, *params = [torch.from_numpy(a[k]) for k in ("x", "p_key", "p_type", "p_val", "p_num")]
    embeddings = torch.cat([model(x[i:i+8], tuple(p[i:i+8] for p in params))
                            for i in range(0, len(x), 8)])
    require(torch.isfinite(embeddings).all().item(), "Nonfinite embeddings")
    return rows, y, F.normalize(embeddings, dim=1), expected_sha


def main(output):
    start = time.perf_counter()
    require(not output.exists(), "Use a new output directory")
    torch.set_num_threads(2)
    _, protocol, train, vocab = verified_inputs()
    manifest = read_json(FEATURES / "feature_manifest.json")
    checkpoint = BASE / train["checkpoint"]
    protected = readonly_hashes(checkpoint)
    require(protected == manifest["protected_sha256"] and digest(checkpoint) == train["checkpoint_sha256"],
            "Protected data or checkpoint changed")
    require(manifest["vocabulary_sha256"] == train["vocabulary_sha256"] and
            manifest["protocol_sha256"] == protocol["split_sha256"], "Provenance differs")
    from model import Model
    state = torch.load(checkpoint, weights_only=True, map_location="cpu")["net"]
    model = Model(num_layers=1, window_size=WINDOW, nhead=8, **train["metadata"]).eval()
    loaded = model.load_state_dict(state, strict=True)
    support, ys, zs, support_hash = encode_dev("development_support", model, manifest, protocol, vocab, train["metadata"])
    query, y, zq, query_hash = encode_dev("development_query", model, manifest, protocol, vocab, train["metadata"])
    support_ids = [s["sequence_id"] for s in support]
    ids = [s["sequence_id"] for s in query]
    require(len(set(support_ids)) == 40 and len(set(ids)) == 200 and not set(ids) & set(support_ids) and
            np.bincount(ys).tolist() == [20, 20] and np.bincount(y).tolist() == [100, 100], "Invalid pools")
    prior = read_json(FEATURES / "development_metrics.json")
    require(sha(ids) == prior["query_ids_sha256"], "Query changed from previous evaluation")
    length = np.array([r["true_length"] for r in query])
    masks = {"2-4": length <= 4, "5-19": (length >= 5) & (length <= 19),
             "20-29": (length >= 20) & (length <= 29), "30-50": length >= 30}
    bin_name = np.empty(len(y), dtype=object)
    for name, mask in masks.items():
        bin_name[mask] = name
    diagnostic = {}
    for name, score in (("length", length), ("negative_length", -length)):
        report = metrics(y, score)
        # Only ranking metrics are meaningful for these uncalibrated integer scores.
        diagnostic[name] = {k: report[k] for k in ("roc_auc", "average_precision")}
        diagnostic[name]["by_length"] = {
            b: {k: m[k] for k in ("roc_auc", "average_precision")}
            for b, mask in masks.items() for m in [metrics(y[mask], score[mask])]
        }
    detail, flat, predictions = [], [], []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        permutations = [rng.permutation(np.flatnonzero(ys == c)) for c in (0, 1)]
        for k in SHOTS:
            groups = [g[:k] for g in permutations]
            proto = F.normalize(torch.stack([zs[g].mean(0) for g in groups]), dim=1)
            normal = (zq @ proto[0:1].T).flatten().numpy()
            anomaly = (zq @ proto[1:2].T).flatten().numpy()
            score = anomaly - normal
            require(np.isfinite(score).all(), "Nonfinite scores")
            pred = (score > 0).astype(int)
            metric = metrics(y, score)
            tn, fp, fn, tp = np.asarray(metric["confusion_matrix"]).ravel().tolist()
            correlations = {"all": correlation(length, score, np.ones(len(y), bool)),
                            "normal": correlation(length, score, y == 0),
                            "anomaly": correlation(length, score, y == 1)}
            bins = {}
            for name, mask in masks.items():
                m = metrics(y[mask], score[mask])
                b_tn, b_fp, b_fn, b_tp = np.asarray(m["confusion_matrix"]).ravel().tolist()
                bins[name] = {
                    **m, "recall_anomaly": b_tp / (b_tp + b_fn) if b_tp + b_fn else None,
                    "fpr_normal": b_fp / (b_fp + b_tn) if b_fp + b_tn else None,
                    "score_by_class": score_stats(y[mask], score[mask]),
                }
            row = {"seed": seed, "shots_per_class": k, **metric["binary"], "macro_f1": metric["macro"]["f1"],
                   "roc_auc": metric["roc_auc"], "average_precision": metric["average_precision"],
                   "tn": tn, "fp": fp, "fn": fn, "tp": tp, "prototype_cosine": float(proto[0] @ proto[1]),
                   "short_anomaly_tp_2_4": int(((y == 1) & (pred == 1) & (length <= 4)).sum()),
                   "long_anomaly_tp_20_50": int(((y == 1) & (pred == 1) & (length >= 20)).sum()),
                   **{f"spearman_{name}": value for name, value in correlations.items()}}
            selected = {name: [support_ids[i] for i in g] for name, g in zip(CLASSES, groups)}
            flat.append(row)
            detail.append({**row, "support_ids": selected, "support_sha256": sha(selected),
                           "confusion_matrix": metric["confusion_matrix"],
                           "score_by_class": score_stats(y, score), "by_length": bins})
            predictions.extend({"seed": seed, "shots_per_class": k, "block_id": bid, "label": label,
                                "length": n, "length_bin": b, "cos_normal": cn, "cos_anomaly": ca,
                                "score": sa, "prediction": p}
                               for bid, label, n, b, cn, ca, sa, p in
                               zip(ids, y, length, bin_name, normal, anomaly, score, pred))
    require(len(detail) == len(SEEDS) * len(SHOTS), "Validation runs missing")
    aggregated = {}
    for k in SHOTS:
        selected = [r for r in detail if r["shots_per_class"] == k]
        aggregated[k] = {
            "metrics": {name: summary([r[name] for r in selected])
                        for name in flat[0] if name not in ("seed", "shots_per_class")},
            "by_length": {name: {
                "class_counts": selected[0]["by_length"][name]["class_counts"],
                **{key: summary([r["by_length"][name][key] for r in selected])
                   for key in ("recall_anomaly", "fpr_normal", "roc_auc", "average_precision")},
                "median_score_by_class_across_seeds": {
                    cls: summary([r["by_length"][name]["score_by_class"][cls]["median"] for r in selected])
                    if selected[0]["by_length"][name]["score_by_class"][cls] else None
                    for cls in CLASSES
                }
            } for name in masks},
            "median_score_by_class_across_seeds": {
                cls: summary([r["score_by_class"][cls]["median"] for r in selected]) for cls in CLASSES
            },
        }
    require(all(torch.equal(v, state[k]) for k, v in model.state_dict().items()) and
            protected == readonly_hashes(checkpoint), "Protected weights or files changed")
    output.mkdir()
    write_csv(output / "runs.csv", flat)
    write_csv(output / "query_scores.csv", predictions)
    save(output / "runs.json", detail)
    save(output / "summary.json", {
        "seeds": list(SEEDS), "rng": "numpy.default_rng (PCG64), separate class permutations from each seed",
        "shots": list(SHOTS), "threshold": 0, "checkpoint_tensors": len(state), "strict_load": str(loaded),
        "checkpoint_sha256": train["checkpoint_sha256"], "query_ids_sha256": sha(ids),
        "protocol_sha256": protocol["split_sha256"], "vocabulary_sha256": train["vocabulary_sha256"],
        "development_support_npz_sha256": support_hash, "development_query_npz_sha256": query_hash,
        "length_only_diagnostic": diagnostic, "by_shots": aggregated,
        "seconds": time.perf_counter() - start, "peak_working_set_mib": peak_working_set_mib(),
    })
    print(f"Completed {len(detail)} resamples; {len(ids)} fixed development queries.")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
