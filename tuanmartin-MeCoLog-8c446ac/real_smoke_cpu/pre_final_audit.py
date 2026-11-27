"""Freeze the two pre-final scoring rules and audit them on development only."""

import csv
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from controlled_diagnostics import encode, pool
from support_stability import (
    BASE, FEATURES, HERE, NAMES, digest, metrics, peak_working_set_mib, read_json,
    readonly_hashes, require, save, sha, verified_inputs, write_csv,
)

EXPERIMENTS = HERE / "prototype_experiments_seed123"
SEEDS = range(1000, 1020)
SHOTS = 10
BOUNDARY = 4
MIN_CLUSTER = 2
METHODS = ("single", "length_two")


def seed_support(labels, seed):
    rng = np.random.default_rng(seed)
    groups = [rng.permutation(np.flatnonzero(labels == c))[:SHOTS].tolist() for c in (0, 1)]
    require(all(len(g) == SHOTS for g in groups), "Insufficient support")
    return groups


def anomaly_partition(selected, support_lengths):
    short = [i for i in selected if support_lengths[i] <= BOUNDARY]
    long = [i for i in selected if support_lengths[i] > BOUNDARY]
    return [short, long] if min(len(short), len(long)) >= MIN_CLUSTER else [selected]


def unit_mean(embeddings, group):
    require(bool(group), "Empty prototype")
    v = embeddings[group].mean(dim=0, keepdim=True)
    require(torch.isfinite(v).all().item() and v.norm().item() > 1e-12, "Invalid prototype norm")
    return F.normalize(v, dim=1)


def score(queries, normal, anomaly_prototypes):
    # The only query input is its embedding. No length, index or label routing.
    require(bool(anomaly_prototypes), "No anomaly prototypes")
    similarities = [(queries @ p.T).flatten() for p in anomaly_prototypes]
    result = torch.stack(similarities, dim=0).amax(dim=0) - (queries @ normal.T).flatten()
    require(torch.isfinite(result).all().item(), "Nonfinite score")
    return result.numpy()


def final_metadata(protocol, manifest):
    def lineage(name):
        rows = [(r["block_id"], r["raw_line_ids"]) for r in protocol["pools"][name]]
        features = [(r["sequence_id"], r["raw_line_ids"]) for r in manifest["pools"][name]]
        require(rows == features, f"Feature lineage mismatch: {name}")
        ids = {key for key, _ in rows}
        lines = [line for _, lines in rows for line in lines]
        require(len(ids) == len(rows) and len(set(lines)) == len(lines), f"Duplicate lineage: {name}")
        return rows, ids, set(lines)

    used_ids, used_lines = set(), set()
    result = {}
    for name in ("development_support", "development_query", "final_support", "final_query"):
        rows, ids, lines = lineage(name)
        require(not ids & used_ids and not lines & used_lines, "Overlapping pools")
        used_ids.update(ids)
        used_lines.update(lines)
        if name.startswith("final_"):
            require(len(rows) == (40 if name.endswith("support") else 200), "Unexpected final pool size")
            path = FEATURES / (NAMES[name] + ".npz")
            actual = digest(path)  # Opaque bytes. NumPy never opens final NPZs in this audit.
            require(actual == manifest["statistics"][name]["npz_sha256"], "Final NPZ hash mismatch")
            result[name] = dict(count=len(rows), raw_lines=len(lines), lineage_sha256=sha(rows),
                                feature_path=str(path.relative_to(HERE)), feature_sha256=actual)
    counts = protocol["summary"]["final_support"]["counts"]
    require(counts == {"Normal": 20, "Anomaly": 20}, "Unexpected final support capacity")
    result["final_support"]["locked_label_counts"] = counts
    result["integrity"] = "all four pools disjoint; final archive bytes hashed only"
    return result


def matching_rows(filename):
    with (EXPERIMENTS / filename).open(newline="", encoding="utf-8") as stream:
        return [r for r in csv.DictReader(stream) if r["selection"] == "random" and
                r["shots"] == "10" and r.get("method", "single") in METHODS]


def main(output):
    start = time.perf_counter()
    require(not output.exists(), "Use a new output directory")
    torch.set_num_threads(2)
    from model import Model

    _, protocol, train, vocab = verified_inputs()
    fm = read_json(FEATURES / "feature_manifest.json")
    ckpt = BASE / train["checkpoint"]
    protected = readonly_hashes(ckpt)
    reference_replay = read_json(EXPERIMENTS / "baseline_replay.json")
    require(protected == fm["protected_sha256"] and
            digest(ckpt) == train["checkpoint_sha256"] == reference_replay["checkpoint_sha256"] and
            protocol["split_sha256"] == fm["protocol_sha256"] == reference_replay["protocol_sha256"] and
            fm["vocabulary_sha256"] == train["vocabulary_sha256"] == reference_replay["vocabulary_sha256"],
            "Checkpoint/provenance mismatch")
    final = final_metadata(protocol, fm)
    sd = pool("development_support", fm, protocol, vocab, train["metadata"])
    qd = pool("development_query", fm, protocol, vocab, train["metadata"])
    sid, ys, slen, _ = sd
    qid, yq, _, _ = qd
    require(sha(qid) == reference_replay["query_sha256"] and not set(sid) & set(qid) and
            len(set(sid)) == 40 and len(set(qid)) == 200, "Development IDs differ")

    state = torch.load(ckpt, weights_only=True, map_location="cpu")["net"]
    model = Model(num_layers=1, nhead=8, window_size=50, **train["metadata"]).eval()
    load = model.load_state_dict(state, strict=True)
    _, zs = encode(model, sd, 50)
    _, zq = encode(model, qd, 50)
    for z in (zs, zq):
        require(torch.allclose(z.norm(dim=1), torch.ones(len(z)), atol=2e-6, rtol=0), "Nonunit embedding")

    old_predictions, old_support, old_prototypes = defaultdict(list), defaultdict(list), defaultdict(list)
    old_runs = {(int(r["seed"]), r["method"]): r for r in matching_rows("experiment_runs.csv")}
    for row in matching_rows("query_predictions.csv"):
        old_predictions[int(row["seed"]), row["method"]].append(row)
    for row in matching_rows("support_selection.csv"):
        old_support[int(row["seed"])].append(row)
    for row in matching_rows("prototype_assignments.csv"):
        old_prototypes[int(row["seed"]), row["method"]].append(row)
    require(len(old_runs) == 40 and sum(map(len, old_predictions.values())) == 8000, "Saved runs incomplete")

    # Edge-case checks exercise only the selection rule, with no scoring or benchmark data.
    indices = list(range(10))
    expected = (([20]*10, 1), ([2]*10, 1), ([2]+[20]*9, 1), ([2]*9+[20], 1),
                ([2]*2+[20]*8, 2), ([2]*8+[20]*2, 2))
    require(all(len(anomaly_partition(indices, lengths)) == n for lengths, n in expected),
            "Fallback rule failed")

    rows = []
    for seed in SEEDS:
        normal, anomaly = seed_support(ys, seed)
        chosen = {"Normal": [sid[i] for i in normal], "Anomaly": [sid[i] for i in anomaly]}
        support_hash = sha(chosen)
        require([(r["block_id"], int(r["label"]), int(r["length"])) for r in old_support[seed]] ==
                [(sid[i], cls, int(slen[i])) for cls, group in enumerate((normal, anomaly)) for i in group],
                "Support IDs, labels or lengths changed")
        normal_proto = unit_mean(zs, normal)
        for method in METHODS:
            groups = [anomaly] if method == "single" else anomaly_partition(anomaly, slen)
            ordered = [("Normal", normal), *((f"Anomaly_{i}", g) for i, g in enumerate(groups))]
            require([(r["prototype"], r["block_id"], int(r["length"]))
                     for r in old_prototypes[seed, method]] ==
                    [(name, sid[i], int(slen[i])) for name, group in ordered for i in group],
                    "Prototype memberships changed")
            scores = score(zq, normal_proto, [unit_mean(zs, group) for group in groups])
            reference = old_predictions[seed, method]
            require([(r["block_id"], int(r["label"])) for r in reference] == list(zip(qid, yq)),
                    "Saved development query order/labels differ")
            error = float(max(abs(scores - [float(r["score"]) for r in reference])))
            require(error <= 2e-6 and (scores > 0).tolist() == [bool(int(r["prediction"])) for r in reference],
                    "Score/prediction replay failed")
            m = metrics(yq, scores)
            tn, fp, fn, tp = np.asarray(m["confusion_matrix"]).ravel().tolist()
            result = dict(**m["binary"], macro_f1=m["macro"]["f1"], roc_auc=m["roc_auc"],
                          average_precision=m["average_precision"], fpr=fp / (tn + fp),
                          tn=tn, fp=fp, fn=fn, tp=tp)
            prior = old_runs[seed, method]
            require(prior["support_sha256"] == support_hash and prior["query_sha256"] == sha(qid),
                    "ID checksum differs")
            require(all(math.isclose(value, float(prior[key]), abs_tol=2e-9, rel_tol=0)
                        for key, value in result.items()), "Metrics replay failed")
            rows.append(dict(seed=seed, method=method, support_sha256=support_hash,
                             anomaly_prototypes=len(groups), max_score_difference=error, **result))

    require(all(torch.equal(t, state[k]) for k, t in model.state_dict().items()) and
            protected == readonly_hashes(ckpt), "Protected inputs or weights changed")
    output.mkdir()
    write_csv(output / "development_replay.csv", rows)
    frozen = {
        "status": "locked_before_final_inference", "methods": list(METHODS),
        "support_seeds": list(SEEDS), "rng": "numpy.default_rng(PCG64); Normal then Anomaly permutations",
        "support_pool_order": "locked NPZ/manifest order; first 10 of each permuted class",
        "shots_per_class": SHOTS, "window": 50, "threshold": 0, "anomaly_if": "score > 0",
        "checkpoint": str(ckpt.relative_to(HERE)), "checkpoint_sha256": train["checkpoint_sha256"],
        "architecture": {"layers": 1, "heads": 8, "dim": 768, **train["metadata"]},
        "checkpoint_tensors": len(state), "strict_load": str(load),
        "runtime": {"torch": torch.__version__, "numpy": np.__version__, "device": "cpu", "threads": 2},
        "boundary": BOUNDARY, "boundary_origin": "development diagnostics; adopted before final evaluation",
        "minimum_anomaly_cluster_size": MIN_CLUSTER, "fallback": "one prototype from all anomaly support",
        "formula": "normalize each embedding; normalize each support mean; max anomaly cosine minus normal cosine",
        "query_length_used_for_prototype_selection": False, "clustering": False,
        "protocol_sha256": protocol["split_sha256"], "vocabulary_sha256": train["vocabulary_sha256"],
        "sbert_revision": fm["sbert_revision"],
        "feature_manifest_sha256": digest(FEATURES / "feature_manifest.json"),
        "model_source_sha256": protected["model.py"],
        "frozen_scorer_sha256": digest(Path(__file__)), "final_metadata": final,
        "final_reporting": {"paired": True, "all_seeds": True, "query_fixed": True,
                            "metrics": ["binary_precision", "binary_recall", "binary_f1", "macro_f1",
                                        "roc_auc", "average_precision", "fpr", "confusion_matrix"],
                            "report_fallback": True, "select_best_seed": False},
    }
    frozen["lock_sha256"] = sha(frozen)
    save(output / "frozen_protocol.json", frozen)
    simulation = {}
    for method in METHODS:
        r = [row for row in rows if row["method"] == method]
        tpr, fpr = (sum(row[key] for row in r)/len(r) for key in ("recall", "fpr"))
        simulation[method] = {"mean_tpr": tpr, "mean_fpr": fpr, "fallbacks": sum(
            row["anomaly_prototypes"] == 1 for row in r) if method == "length_two" else None,
            "expected_precision_by_prevalence": {
                str(p): tpr*p/(tpr*p+fpr*(1-p)) for p in (.5, .1, .01, .001)},
            "expected_false_positives_per_10000_normal": fpr*10000}
    report = {"runs": len(rows), "queries_scored": len(rows)*200,
              "max_score_difference": max(r["max_score_difference"] for r in rows),
              "score_replay_tolerance": 2e-6, "prediction_or_metric_mismatches": 0,
              "weights_unchanged": True, "final_query_labels_accessed": False,
              "final_npz_arrays_loaded": False,
              "simulation_assumption": "conditional TPR/FPR fixed at development seed means",
              "prevalence_simulation": simulation, "seconds": time.perf_counter()-start,
              "peak_working_set_mib": peak_working_set_mib(), "lock_sha256": frozen["lock_sha256"]}
    save(output / "audit_summary.json", report)
    print(f"Passed {len(rows)} development replays; final feature hashes verified as opaque files.")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
