"""Development-only factorial comparison of support selection and prototypes."""

import csv
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np
import torch
from sklearn.cluster import KMeans
from threadpoolctl import threadpool_limits
from torch.nn import functional as F

from controlled_diagnostics import PRIOR, difference, encode, pool
from support_stability import (
    BASE, FEATURES, NAMES, digest, metrics, peak_working_set_mib, read_json,
    readonly_hashes, require, save, sha, summary, verified_inputs, write_csv,
)

SEEDS = range(1000, 1020)
SHOTS = (5, 10)
CLASSES = ("Normal", "Anomaly")
METHODS = ("single", "length_two", "kmeans_two")
FIELDS = ("precision", "recall", "f1", "macro_f1", "roc_auc", "average_precision",
          "fpr", "fp", "fn", "recall_2_4", "recall_20_29", "recall_30_50")


def diverse_groups(seed, k, labels, lengths):
    rng = np.random.default_rng(seed)
    normal = sorted(np.flatnonzero(labels == 0), key=lambda i: (lengths[i], i))
    normal = [int(rng.choice(b)) for b in np.array_split(normal, k)]
    short = np.flatnonzero((labels == 1) & (lengths <= 4))
    longer = np.flatnonzero((labels == 1) & (lengths > 4))
    require(len(short) >= k // 2 and len(longer) >= k - k // 2, "Insufficient support strata")
    anomaly = np.r_[rng.permutation(short)[:k//2], rng.permutation(longer)[:k-k//2]].tolist()
    return normal, anomaly


def anomaly_groups(method, zs, selected, lengths):
    if method == "single":
        return [selected], ""
    if method == "length_two":
        group_labels = (lengths[selected] > 4).astype(int)
    else:
        vectors = zs[selected].numpy()
        if len(np.unique(vectors, axis=0)) < 2:
            return [selected], "fewer_than_two_distinct_embeddings"
        group_labels = KMeans(n_clusters=2, random_state=123, n_init=10).fit_predict(vectors)
    groups = [np.asarray(selected)[group_labels == i].tolist() for i in (0, 1)]
    if min(map(len, groups)) < 2:
        return [selected], "cluster_size_below_two:" + "/".join(map(str, map(len, groups)))
    return groups, ""


def scores(zs, zq, normal, anomalies):
    centroids = F.normalize(torch.stack([zs[g].mean(0) for g in [normal, *anomalies]]), dim=1)
    norm_score = (zq @ centroids[0:1].T).flatten()
    # Score each centroid separately to preserve the original single-prototype arithmetic.
    anom_score = torch.stack([(zq @ centroids[i:i+1].T).flatten()
                              for i in range(1, len(centroids))]).amax(dim=0)
    return (anom_score - norm_score).numpy()


def main(output):
    start = time.perf_counter()
    require(not output.exists(), "Use a new output directory")
    torch.set_num_threads(2)
    from model import Model

    _, protocol, train, vocab = verified_inputs()
    manifests = read_json(FEATURES / "feature_manifest.json")
    prior = read_json(PRIOR / "summary.json")
    ckpt = BASE / train["checkpoint"]
    protected = readonly_hashes(ckpt)
    require(protected == manifests["protected_sha256"] and
            digest(ckpt) == train["checkpoint_sha256"] == prior["checkpoint_sha256"] and
            protocol["split_sha256"] == manifests["protocol_sha256"] == prior["protocol_sha256"] and
            manifests["vocabulary_sha256"] == train["vocabulary_sha256"] == prior["vocabulary_sha256"],
            "Checkpoint or provenance differs")
    require(prior["threshold"] == 0 and prior["seeds"] == list(SEEDS), "Prior protocol changed")
    for name, kind in (("development_support", "support"), ("development_query", "query")):
        require(manifests["statistics"][name]["npz_sha256"] == prior[f"development_{kind}_npz_sha256"],
                "Prior NPZ checksum differs")
    support = pool("development_support", manifests, protocol, vocab, train["metadata"])
    query = pool("development_query", manifests, protocol, vocab, train["metadata"])
    sid, ys, slen, _ = support
    qid, yq, qlen, _ = query
    require(len(set(sid)) == 40 and len(set(qid)) == 200 and not set(sid) & set(qid) and
            sha(qid) == prior["query_ids_sha256"] and np.bincount(ys).tolist() == [20, 20] and
            np.bincount(yq).tolist() == [100, 100], "Development pools differ")
    state = torch.load(ckpt, map_location="cpu", weights_only=True)["net"]
    model = Model(num_layers=1, window_size=50, nhead=8, **train["metadata"]).eval()
    load = model.load_state_dict(state, strict=True)
    tick = time.perf_counter()
    zs = encode(model, support, 50)[1]
    zq = encode(model, query, 50)[1]
    encoding_seconds = time.perf_counter() - tick
    index = {i: j for j, i in enumerate(sid)}
    with (PRIOR / "query_scores.csv").open(newline="", encoding="utf-8") as f:
        saved = list(csv.DictReader(f))
    require(len(saved) == 12000, "Prior query rows missing")
    random_cases = {}
    max_error = 0.0
    prior_runs = read_json(PRIOR / "runs.json")
    require(len(prior_runs) == 60, "Prior runs missing")
    for i, run in enumerate(prior_runs):
        seed, k = run["seed"], run["shots_per_class"]
        require((seed, k) == (1000 + i // 3, (2, 5, 10)[i % 3]), "Prior seed grid changed")
        selected = run["support_ids"]
        require(sha(selected) == run["support_sha256"], "Support checksum mismatch")
        groups = [[index[name] for name in selected[cls]] for cls in CLASSES]
        require(all(len(set(g)) == len(g) == k and all(ys[j] == c for j in g)
                    for c, g in enumerate(groups)), "Support labels differ")
        rows = saved[i*200:(i+1)*200]
        require([(int(r["seed"]), int(r["shots_per_class"]), r["block_id"], int(r["label"]), int(r["length"]))
                 for r in rows] == list(zip([seed]*200, [k]*200, qid, yq, qlen)), "Query rows differ")
        actual = scores(zs, zq, groups[0], [groups[1]])
        original, _ = difference(zs, zq, groups)
        err = float(max(abs(actual - [float(r["score"]) for r in rows])))
        max_error = max(max_error, err)
        require(err <= 2e-6 and np.allclose(actual, original, rtol=0, atol=2e-6) and
                (actual > 0).tolist() == [bool(int(r["prediction"])) for r in rows], "Replay failed")
        random_cases[seed, k] = (groups, actual)
    print(f"Replay verified: 60 runs, 12000 predictions, max score error {max_error:.3g}.", flush=True)

    results, selections, assignments, preds = [], [], [], []
    for seed, k, selection in product(SEEDS, SHOTS, ("random", "length_diverse")):
        rand, baseline = random_cases[seed, k]
        groups = rand if selection == "random" else diverse_groups(seed, k, ys, slen)
        require(all(len(set(g)) == len(g) == k and all(ys[j] == c for j in g)
                    for c, g in enumerate(groups)), "Invalid chosen support")
        support_hash = sha({cls: [sid[j] for j in g] for cls, g in zip(CLASSES, groups)})
        for c, g in enumerate(groups):
            selections.extend(dict(seed=seed, shots=k, selection=selection, label=c, block_id=sid[i],
                                   length=int(slen[i]), support_sha256=support_hash) for i in g)
        single = scores(zs, zq, groups[0], [groups[1]])
        for method in METHODS:
            tick = time.perf_counter_ns()
            prototypes, fallback = anomaly_groups(method, zs, groups[1], slen)
            build_ms = (time.perf_counter_ns() - tick) / 1e6
            tick = time.perf_counter_ns()
            score = scores(zs, zq, groups[0], prototypes)
            score_ms = (time.perf_counter_ns() - tick) / 1e6
            require(np.isfinite(score).all(), "Nonfinite score")
            pred = score > 0
            m = metrics(yq, score)
            tn, fp, fn, tp = np.asarray(m["confusion_matrix"]).ravel().tolist()
            row = dict(seed=seed, shots=k, selection=selection, method=method,
                       support_sha256=support_hash, query_sha256=sha(qid), fallback=fallback,
                       anomaly_prototypes=len(prototypes), **m["binary"], macro_f1=m["macro"]["f1"],
                       roc_auc=m["roc_auc"], average_precision=m["average_precision"],
                       tn=tn, fp=fp, fn=fn, tp=tp, fpr=fp/(tn+fp),
                       flips_vs_random_single=int(((baseline > 0) != pred).sum()),
                       flips_vs_same_support_single=int(((single > 0) != pred).sum()),
                       grouping_ms=build_ms, scoring_with_centroids_ms=score_ms)
            for a, b in ((2, 4), (20, 29), (30, 50)):
                mask = (yq == 1) & (qlen >= a) & (qlen <= b)
                row[f"recall_{a}_{b}"] = float(pred[mask].mean())
            minority = sum(min(sum(slen[g] <= 4), sum(slen[g] > 4)) for g in prototypes)
            row["length_split_purity"] = float(1 - minority / k) if len(prototypes) == 2 else None
            results.append(row)
            proto_members = [("Normal", groups[0]), *((f"Anomaly_{i}", g) for i, g in enumerate(prototypes))]
            for proto_id, g in proto_members:
                assignments.extend(dict(seed=seed, shots=k, selection=selection, method=method,
                    prototype=proto_id, cluster_size=len(g), block_id=sid[i], label=int(ys[i]),
                    length=int(slen[i]), fallback=fallback, support_sha256=support_hash) for i in g)
            preds.extend(dict(seed=seed, shots=k, selection=selection, method=method,
                              block_id=name, length=int(n), label=int(y), prediction=int(p),
                              score=float(s)) for name, n, y, p, s in zip(qid, qlen, yq, pred, score))

    lookup = {(r["seed"], r["shots"], r["selection"], r["method"]): r for r in results}
    pairs = []
    for seed, k in product(SEEDS, SHOTS):
        comparisons = [("selection_only", "random", "single", "length_diverse", "single")]
        comparisons.extend(("prototype_only", choice, "single", choice, method)
                           for choice, method in product(("random", "length_diverse"), METHODS[1:]))
        for effect, initial, before, changed, after in comparisons:
            a, b = lookup[seed, k, initial, before], lookup[seed, k, changed, after]
            require(effect != "prototype_only" or a["support_sha256"] == b["support_sha256"],
                    "Unpaired support IDs")
            pairs.append(dict(seed=seed, shots=k, effect=effect, before_selection=initial,
                              before_method=before, after_selection=changed, after_method=after,
                              **{f"delta_{field}": b[field] - a[field] for field in FIELDS}))
    cells, paired = {}, {}
    for k, choice, method in product(SHOTS, ("random", "length_diverse"), METHODS):
        rows = [lookup[s, k, choice, method] for s in SEEDS]
        fields = (*FIELDS, "flips_vs_random_single", "flips_vs_same_support_single",
                  "grouping_ms", "scoring_with_centroids_ms", "length_split_purity")
        cells[f"{k}/{choice}/{method}"] = {**{f: summary(r[f] for r in rows) for f in fields},
                                          "fallback_runs": sum(bool(r["fallback"]) for r in rows)}
    for row in pairs:
        key = (row["shots"], row["effect"], row["after_selection"], row["after_method"])
        paired.setdefault("/".join(map(str, key)), []).append(row)
    paired = {key: {f: summary(r[f"delta_{f}"] for r in rows) for f in FIELDS} for key, rows in paired.items()}
    require(len(results) == 240 and len(pairs) == 200 and len(preds) == 48000, "Incomplete experiment")
    require(protected == readonly_hashes(ckpt) and all(torch.equal(t, state[k]) for k, t in model.state_dict().items())
            and all(digest(FEATURES / (NAMES[name] + ".npz")) == manifests["statistics"][name]["npz_sha256"]
                    for name in ("development_support", "development_query")), "Weights or data changed")
    output.mkdir()
    save(output / "baseline_replay.json", dict(runs=60, predictions=12000, max_score_error=max_error,
         strict_load=str(load), tensors=len(state), checkpoint_sha256=train["checkpoint_sha256"],
         query_sha256=sha(qid), vocabulary_sha256=train["vocabulary_sha256"],
         protocol_sha256=protocol["split_sha256"], prediction_mismatches=0))
    write_csv(output / "support_selection.csv", selections)
    write_csv(output / "prototype_assignments.csv", assignments)
    write_csv(output / "experiment_runs.csv", results)
    write_csv(output / "paired_comparisons.csv", pairs)
    write_csv(output / "query_predictions.csv", preds)
    save(output / "experiment_summary.json", dict(
        seeds=list(SEEDS), shots=list(SHOTS), threshold=0, query_n=200,
        seconds=time.perf_counter()-start, encoding_seconds=encoding_seconds,
        peak_working_set_mib=peak_working_set_mib(), results=cells, paired=paired))
    print(f"Wrote {len(results)} runs and {len(pairs)} paired comparisons to {output}")


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main(Path(sys.argv[1]).resolve())
