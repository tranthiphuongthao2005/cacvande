"""Controlled development-only diagnostics of the frozen 100-episode checkpoint."""

import csv
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from support_stability import (
    BASE, FEATURES, HERE, META, NAMES, WINDOW, correlation, digest, metrics,
    peak_working_set_mib, read_json, readonly_hashes, require, save, sha,
    summary, validate_arrays, verified_inputs, write_csv,
)

PRIOR = HERE / "support_stability_1000_1019"


def pool(name, manifest, protocol, vocab, metadata):
    require(name in ("development_support", "development_query"), "Development only")
    rows = manifest["pools"][name]
    locked = protocol["pools"][name]
    require([(r["sequence_id"], r["raw_line_ids"], r["true_length"], r["label"]) for r in rows] ==
            [(r["block_id"], r["raw_line_ids"], len(r["raw_line_ids"]), int(r["label"] == "Anomaly"))
             for r in locked], "Pool lineage changed")
    path = FEATURES / (NAMES[name] + ".npz")
    require(digest(path) == manifest["statistics"][name]["npz_sha256"], "NPZ checksum mismatch")
    lengths = np.array([r["true_length"] for r in rows])
    with np.load(path, allow_pickle=False) as data:
        a = {key: data[key] for key in data.files}
    validate_arrays(a, WINDOW, vocab, lengths.tolist())
    require({k: int(a[k]) for k in META} == metadata, "Input/ checkpoint metadata differs")
    y = a["y"].argmax(1)
    require(y.tolist() == [r["label"] for r in rows], "Changed 0/1 label mapping")
    return [r["sequence_id"] for r in rows], y, lengths, tuple(
        torch.from_numpy(a[k]) for k in ("x", "p_key", "p_type", "p_val", "p_num")
    )


@torch.inference_mode()
def encode(model, pool_data, width, stress=None):
    _, _, lengths, values = pool_data
    require(width >= max(lengths), "Diagnostic would truncate real events")
    data = []
    for feature, original in enumerate(values):
        t = original[:, :width].clone()
        if width > WINDOW:
            t = torch.cat((t, t.new_zeros((len(t), width - WINDOW, *t.shape[2:]))), dim=1)
        for i, n in enumerate(lengths):
            original_events = original[i, :n]
            if stress == "reverse":
                t[i, :n] = original_events.flip((0,))
            elif stress == "zero_template" and feature == 0:
                t[i, :n].zero_()
            else:
                require(torch.equal(t[i, :n], original_events), "Real events changed")
            require(not torch.count_nonzero(t[i, n:]).item(), "Padding changed content")
        data.append(t)
    z = torch.cat([model(data[0][i:i+8], tuple(p[i:i+8] for p in data[1:]))
                   for i in range(0, len(lengths), 8)])
    require(torch.isfinite(z).all().item(), "Nonfinite embeddings")
    return z, F.normalize(z, dim=1)


def difference(support, query, groups):
    proto = F.normalize(torch.stack([support[g].mean(0) for g in groups]), dim=1)
    normal = (query @ proto[0:1].T).flatten().numpy()
    anomaly = (query @ proto[1:2].T).flatten().numpy()
    return anomaly - normal, float(proto[0] @ proto[1])


def embedding_delta(baseline, other):
    raw, unit = baseline
    altered_raw, altered_unit = other
    return {"cosine": summary((unit * altered_unit).sum(1).numpy()),
            "raw_l2": summary((raw - altered_raw).norm(dim=1).numpy())}


def changes(y, length, masks, base, score, proto_cosine):
    result = metrics(y, score)
    flips = (base > 0) != (score > 0)
    result.update({
        "score_shift": summary(score - base),
        "abs_score_shift": summary(abs(score - base)),
        "sign_flips": int(flips.sum()),
        "prototype_cosine": proto_cosine,
        "length_score_spearman": correlation(length, score, np.ones(len(y), bool)),
    })
    result["by_length"] = {}
    for name, mask in masks.items():
        m = metrics(y[mask], score[mask])
        tn, fp, fn, tp = np.asarray(m["confusion_matrix"]).ravel().tolist()
        m["recall_anomaly"] = tp / (tp + fn) if tp + fn else None
        m["fpr_normal"] = fp / (fp + tn) if fp + tn else None
        m["sign_flips"] = int(flips[mask].sum())
        m["abs_score_shift"] = summary(abs(score[mask] - base[mask]))
        result["by_length"][name] = m
    return result


def aggregate(rows):
    out = {k: summary(r[k] for r in rows) for k in (
        "roc_auc", "average_precision", "sign_flips", "prototype_cosine", "length_score_spearman")}
    out["binary"] = {k: summary(r["binary"][k] for r in rows) for k in ("precision", "recall", "f1")}
    out["macro_f1"] = summary(r["macro"]["f1"] for r in rows)
    out["mean_abs_score_shift"] = summary(r["abs_score_shift"]["mean"] for r in rows)
    out["max_abs_score_shift"] = max(r["abs_score_shift"]["max"] for r in rows)
    out["by_length"] = {name: {
        key: summary(r["by_length"][name][key] for r in rows)
        for key in ("recall_anomaly", "fpr_normal", "roc_auc", "sign_flips")
    } for name in rows[0]["by_length"]}
    return out


def main(output):
    start = time.perf_counter()
    require(not output.exists(), "Choose a new diagnosis output")
    torch.set_num_threads(2)
    from model import Model

    _, protocol, train, vocab = verified_inputs()
    feature_manifest = read_json(FEATURES / "feature_manifest.json")
    checkpoint = BASE / train["checkpoint"]
    protected = readonly_hashes(checkpoint)
    require(protected == feature_manifest["protected_sha256"], "Protected inputs changed")
    previous = read_json(PRIOR / "summary.json")
    require(digest(checkpoint) == train["checkpoint_sha256"] == previous["checkpoint_sha256"]
            and protocol["split_sha256"] == previous["protocol_sha256"] ==
            feature_manifest["protocol_sha256"], "Checkpoint/protocol mismatch")
    require(previous["threshold"] == 0 and previous["seeds"] == list(range(1000, 1020)) and
            previous["shots"] == [2, 5, 10], "Unexpected prior protocol")
    for name, kind in (("development_support", "support"), ("development_query", "query")):
        require(feature_manifest["statistics"][name]["npz_sha256"] ==
                previous[f"development_{kind}_npz_sha256"], "Prior NPZ checksum differs")
    support = pool("development_support", feature_manifest, protocol, vocab, train["metadata"])
    query = pool("development_query", feature_manifest, protocol, vocab, train["metadata"])
    sid, ys, slen, _ = support
    ids, y, length, _ = query
    require(len(sid) == len(set(sid)) == 40 and len(ids) == len(set(ids)) == 200 and
            not set(sid).intersection(ids) and sha(ids) == previous["query_ids_sha256"], "Pool IDs differ")
    require(np.bincount(ys).tolist() == [20, 20] and np.bincount(y).tolist() == [100, 100], "Wrong classes")
    maximum = max(int(slen.max()), int(length.max()))
    require(maximum <= 44, "Window 44 is unsafe")
    weights = torch.load(checkpoint, map_location="cpu", weights_only=True)["net"]
    model = Model(num_layers=1, window_size=64, nhead=8, **train["metadata"]).eval()
    load = model.load_state_dict(weights, strict=True)
    require(all(layer.rope.max_len >= 65 for layer in model.layers), "RoPE cache too short for window 64 + CLS")
    base_s = encode(model, support, 50)
    base_q = encode(model, query, 50)
    prior_runs = read_json(PRIOR / "runs.json")
    with (PRIOR / "query_scores.csv").open(newline="", encoding="utf-8") as stream:
        prior_predictions = list(csv.DictReader(stream))
    require(len(prior_runs) == 60 and len(prior_predictions) == 12000, "Prior rows missing")
    index = {name: i for i, name in enumerate(sid)}
    cases = []
    replay_error = 0.0
    for i, run in enumerate(prior_runs):
        seed, k = run["seed"], run["shots_per_class"]
        require((seed, k) == (1000 + i // 3, (2, 5, 10)[i % 3]), "Seed grid changed")
        chosen = run["support_ids"]
        require(sha(chosen) == run["support_sha256"], "Support checksum mismatch")
        groups = [[index[name] for name in chosen[cls]] for cls in ("Normal", "Anomaly")]
        require(all(len(group) == len(set(group)) == k and all(ys[j] == c for j in group)
                    for c, group in enumerate(groups)), "Wrong support labels")
        original = prior_predictions[i*200:(i+1)*200]
        require([(int(row["seed"]), int(row["shots_per_class"]), row["block_id"], int(row["label"]),
                  int(row["length"])) for row in original] ==
                list(zip([seed]*200, [k]*200, ids, y, length)), "Saved query order or labels differ")
        score, proto = difference(base_s[1], base_q[1], groups)
        error = max(abs(score - np.array([float(row["score"]) for row in original])))
        replay_error = max(replay_error, float(error))
        require(error <= 2e-6 and (score > 0).tolist() == [bool(int(row["prediction"])) for row in original]
                and abs(proto - run["prototype_cosine"]) <= 2e-6, "Baseline replay failed")
        cases.append((seed, k, groups, score))
    require(all(torch.equal(t, weights[key]) for key, t in model.state_dict().items()), "Replay modified weights")
    print(f"Baseline replay passed: 60 runs, max error {replay_error:.3g}; true max length {maximum}.", flush=True)

    masks = {"2-4": length <= 4, "5-19": (length >= 5) & (length <= 19),
             "20-29": (length >= 20) & (length <= 29), "30-50": length >= 30}
    variants = {
        "window_44": (encode(model, support, 44), encode(model, query, 44)),
        "window_64": (encode(model, support, 64), encode(model, query, 64)),
        "reverse_query": (base_s, encode(model, query, 50, "reverse")),
        "zero_template_query": (base_s, encode(model, query, 50, "zero_template")),
    }
    detail, score_rows = {}, []
    for name, (s, q) in variants.items():
        rows = []
        for seed, k, groups, base in cases:
            score, proto = difference(s[1], q[1], groups)
            require(np.isfinite(score).all(), f"Nonfinite scores: {name}")
            rows.append({"seed": seed, "shots": k, **changes(y, length, masks, base, score, proto)})
            score_rows.extend(dict(variant=name, seed=seed, shots=k, block_id=bid, label=int(label),
                                   length=int(n), baseline_score=float(b), score=float(v),
                                   baseline_pred=int(b > 0), pred=int(v > 0))
                              for bid, label, n, b, v in zip(ids, y, length, base, score))
        detail[name] = {"support_embedding_delta": embedding_delta(base_s, s),
                        "query_embedding_delta": embedding_delta(base_q, q), "runs": rows}

    short = np.flatnonzero((ys == 1) & (slen <= 4))
    long = np.flatnonzero((ys == 1) & (slen >= 20))
    normal = np.flatnonzero(ys == 0)
    require(min(len(short), len(long)) >= 5, "Insufficient anomaly support for paired composition")
    composition = {"short_support": [], "long_support": []}
    for seed in range(1000, 1020):
        rng = np.random.default_rng(seed)
        ns = rng.permutation(normal)[:5]
        level = {"short_support": rng.permutation(short)[:5], "long_support": rng.permutation(long)[:5]}
        short_score, _ = difference(base_s[1], base_q[1], (ns, level["short_support"]))
        for name, selected in level.items():
            score, proto = difference(base_s[1], base_q[1], (ns, selected))
            require(np.isfinite(score).all(), "Nonfinite composition scores")
            composition[name].append({"seed": seed, "shots": 5,
                                      "normal_support_ids": [sid[j] for j in ns],
                                      "anomaly_support_ids": [sid[j] for j in selected],
                                      **changes(y, length, masks, short_score, score, proto)})
    require(all(torch.equal(t, weights[key]) for key, t in model.state_dict().items()) and
            protected == readonly_hashes(checkpoint), "Protected weights or files changed")
    output.mkdir()
    write_csv(output / "query_diagnostics.csv", score_rows)
    save(output / "runs.json", {"variants": detail, "support_composition": composition})
    save(output / "summary.json", {
        "checkpoint_sha256": train["checkpoint_sha256"], "strict_load": str(load),
        "protocol_sha256": protocol["split_sha256"], "query_ids_sha256": sha(ids),
        "threshold": 0, "maximum_true_length": maximum, "windows": [44, 50, 64],
        "replay_runs": 60, "replay_predictions": 12000, "max_replay_score_error": replay_error,
        "query_counts_by_length": {name: np.bincount(y[mask], minlength=2).tolist()
                                   for name, mask in masks.items()},
        "variants": {name: {
            "support_embedding_delta": part["support_embedding_delta"],
            "query_embedding_delta": part["query_embedding_delta"],
            "by_shots": {k: aggregate([r for r in part["runs"] if r["shots"] == k]) for k in (2, 5, 10)}
        } for name, part in detail.items()},
        "composition_candidate_counts": {"short_anomaly": len(short), "long_anomaly": len(long)},
        "support_composition": {name: aggregate(rows) for name, rows in composition.items()},
        "seconds": time.perf_counter() - start, "peak_working_set_mib": peak_working_set_mib(),
    })
    print(f"Wrote development-only diagnostics to {output}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
