"""One-shot final evaluation under the pre-final protocol lock."""

import argparse
import csv
import math
import time
from pathlib import Path
from traceback import format_exc

import numpy as np
import torch

import pre_final_audit as frozen
from controlled_diagnostics import encode
from support_stability import (
    BASE, FEATURES, HERE, META, NAMES, digest, metrics, peak_working_set_mib, read_json,
    readonly_hashes, require, save, sha, summary, validate_arrays, verified_inputs, write_csv,
)

LOCK = "308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b"
DEST = HERE / "final_evaluation_locked_seed123"
METHODS = ("single", "length_two")
FIELDS = ("binary_precision", "binary_recall", "binary_f1", "macro_precision", "macro_recall",
          "macro_f1", "roc_auc", "average_precision", "fpr", "tn", "fp", "fn", "tp")
PAIRED = ("binary_f1", "macro_f1", "roc_auc", "average_precision", "fpr", "binary_recall")


def preflight():
    require(not DEST.exists(), "Final output already exists; one-shot guard")
    folder = HERE / "pre_final_audit_seed123"
    lock = read_json(folder / "frozen_protocol.json")
    doc = (folder / "PROTOCOL.md").read_text(encoding="utf-8")
    require(lock["lock_sha256"] == LOCK == sha({k: v for k, v in lock.items() if k != "lock_sha256"}),
            "Protocol checksum failed")
    require(all(v in doc for v in ("1000", "1019", "PCG64", "≤ 4", "> 4", "score > 0", "window 50")),
            "Protocol text does not agree")
    require(digest(Path(frozen.__file__)) == lock["frozen_scorer_sha256"], "Audited scorer changed")
    require(lock["methods"] == list(METHODS) and lock["support_seeds"] == list(frozen.SEEDS) and
            lock["shots_per_class"] == frozen.SHOTS == 10 and lock["window"] == 50 and
            lock["threshold"] == 0 and lock["anomaly_if"] == "score > 0" and
            lock["boundary"] == frozen.BOUNDARY == 4 and
            lock["minimum_anomaly_cluster_size"] == frozen.MIN_CLUSTER == 2 and
            lock["rng"] == "numpy.default_rng(PCG64); Normal then Anomaly permutations" and
            not lock["query_length_used_for_prototype_selection"] and not lock["clustering"],
            "Scorer constants disagree with lock")
    _, protocol, train, vocab = verified_inputs()
    fm_path = FEATURES / "feature_manifest.json"
    require(digest(fm_path) == lock["feature_manifest_sha256"], "Feature manifest changed")
    fm = read_json(fm_path)
    ckpt = HERE / lock["checkpoint"]
    require(ckpt == BASE / train["checkpoint"] and
            digest(ckpt) == lock["checkpoint_sha256"] == train["checkpoint_sha256"], "Checkpoint hash mismatch")
    protected = readonly_hashes(ckpt)
    require(protected == fm["protected_sha256"] and len([k for k in protected if k.endswith(".py")]) == 9 and
            protected["model.py"] == lock["model_source_sha256"], "Original sources or protected input changed")
    require(protocol["split_sha256"] == lock["protocol_sha256"] and
            fm["vocabulary_sha256"] == lock["vocabulary_sha256"] == train["vocabulary_sha256"] and
            fm["sbert_revision"] == lock["sbert_revision"], "Feature provenance differs")
    final = frozen.final_metadata(protocol, fm)
    require(final == lock["final_metadata"], "Final lineage or NPZ hashes differ")
    audit = read_json(folder / "audit_summary.json")
    require(audit["lock_sha256"] == LOCK and audit["runs"] == 40 and
            audit["prediction_or_metric_mismatches"] == 0 and audit["weights_unchanged"],
            "Development implementation audit failed")
    require(torch.__version__ == lock["runtime"]["torch"] and np.__version__ == lock["runtime"]["numpy"],
            "Numerical runtime differs from lock")
    torch.set_num_threads(2)
    from model import Model

    cfg = dict(lock["architecture"])
    layers, heads = cfg.pop("layers"), cfg.pop("heads")
    require(layers == 1 and heads == 8 and cfg.pop("dim") == 768 and cfg == train["metadata"],
            "Invalid architecture")
    state = torch.load(ckpt, weights_only=True, map_location="cpu")["net"]
    require(len(state) == lock["checkpoint_tensors"] == 32 and
            all(torch.isfinite(t).all().item() for t in state.values()), "Invalid checkpoint")
    model = Model(num_layers=layers, nhead=heads, window_size=50, **cfg).eval()
    strict = model.load_state_dict(state, strict=True)
    require(str(strict) == lock["strict_load"], "Strict load differs")
    verification = {
        "status": "preflight_passed_before_final_npz_load", "lock_sha256": LOCK,
        "lock_file_sha256": digest(folder / "frozen_protocol.json"),
        "protocol_document_sha256": digest(folder / "PROTOCOL.md"),
        "checkpoint_sha256": digest(ckpt), "frozen_scorer_sha256": digest(Path(frozen.__file__)),
        "runner_sha256": digest(Path(__file__)), "original_and_protected_files_sha256": protected,
        "final_metadata": final, "strict_load": str(strict), "tensor_count": len(state),
        "runtime": lock["runtime"], "output_existed_at_preflight": False,
    }
    return verification, fm, vocab, cfg, model, state, ckpt


def read_pool(name, fm, vocab, cfg):
    require(name in ("final_support", "final_query"), "Unexpected pool")
    rows = fm["pools"][name]
    path = FEATURES / (NAMES[name] + ".npz")
    with np.load(path, allow_pickle=False) as d:
        data = {key: d[key] for key in d.files}
    length = np.array([row["true_length"] for row in rows])
    validate_arrays(data, 50, vocab, length.tolist())
    require({k: int(data[k]) for k in META} == cfg, "Final feature metadata differs")
    y = data["y"].argmax(1)
    require(y.tolist() == [r["label"] for r in rows] and
            np.bincount(y).tolist() == ([20, 20] if name == "final_support" else [100, 100]),
            "Final labels differ from locked feature rows")
    tensors = tuple(torch.from_numpy(data[k]) for k in ("x", "p_key", "p_type", "p_val", "p_num"))
    return [r["sequence_id"] for r in rows], y, length, tensors


def main_metrics(y, scores):
    m = metrics(y, scores)
    tn, fp, fn, tp = map(int, np.array(m["confusion_matrix"]).ravel())
    return {**{f"{avg}_{k}": v for avg in ("binary", "macro") for k, v in m[avg].items()},
            "roc_auc": m["roc_auc"], "average_precision": m["average_precision"],
            "fpr": fp/(tn+fp), "tn": tn, "fp": fp, "fn": fn, "tp": tp}


def evaluate(prepared, started):
    audit, fm, vocab, cfg, model, state, ckpt = prepared
    DEST.mkdir()  # Reserve once, before opening arrays.
    save(DEST / "final_protocol_verification.json", audit)
    phase = "final_data_open"
    try:
        support = read_pool("final_support", fm, vocab, cfg)
        query = read_pool("final_query", fm, vocab, cfg)
        sid, ys, slen, _ = support
        ids, y, qlen, _ = query
        require(len(set(sid)) == 40 and len(set(ids)) == 200 and not set(ids) & set(sid), "Pool overlap")
        phase = "final_inference"
        tick = time.perf_counter()
        zs = encode(model, support, 50)[1]
        zq = encode(model, query, 50)[1]
        encode_time = time.perf_counter()-tick
        runs, preds, support_plan = [], [], []
        for seed in frozen.SEEDS:
            normal, anomaly = frozen.seed_support(ys, seed)
            require(len(set(normal + anomaly)) == 20, "Support sampling repeated a row")
            groups = frozen.anomaly_partition(anomaly, slen)
            short = sum(slen[i] <= 4 for i in anomaly)
            long = 10 - short
            fallback = min(short, long) < 2
            require(len(groups) == (1 if fallback else 2) and
                    set(i for group in groups for i in group) == set(anomaly), "Invalid fallback")
            chosen = {"Normal": [sid[i] for i in normal], "Anomaly": [sid[i] for i in anomaly]}
            support_plan.append(dict(seed=seed, support_ids=chosen, support_sha256=sha(chosen),
                                     short=short, long=long, fallback=fallback,
                                     anomaly_groups=[[sid[i] for i in group] for group in groups]))
            normal_proto = frozen.unit_mean(zs, normal)
            baseline = frozen.unit_mean(zs, anomaly)
            for method in METHODS:
                prototypes = ([baseline] if method == "single" or fallback else
                              [frozen.unit_mean(zs, g) for g in groups])
                scores = frozen.score(zq, normal_proto, prototypes)
                predicted = scores > 0
                runs.append(dict(seed=seed, method=method, support_sha256=sha(chosen), query_sha256=sha(ids),
                                 short_anomaly_support=short, long_anomaly_support=long,
                                 fallback=method == "length_two" and fallback,
                                 **main_metrics(y, scores)))
                preds.extend(dict(seed=seed, method=method, block_id=bid, length=int(n), label=int(label),
                                  score=float(s), prediction=int(p))
                             for bid, n, label, s, p in zip(ids, qlen, y, scores, predicted))
        require(len(runs) == 40 and len(preds) == 8000, "Final output is incomplete")
        require(all(torch.equal(t, state[k]) for k, t in model.state_dict().items()), "Weights changed")
        require(audit["original_and_protected_files_sha256"] == readonly_hashes(ckpt), "Protected inputs changed")
        for name in ("final_support", "final_query"):
            locked = audit["final_metadata"][name]
            require(digest(HERE / locked["feature_path"]) == locked["feature_sha256"], "Final feature mutated")
        phase = "predictions_integrity"
        save(DEST / "final_support_seeds.json", support_plan)
        write_csv(DEST / "final_runs.csv", runs)
        write_csv(DEST / "final_predictions.csv", preds)
        with (DEST / "final_predictions.csv").open(newline="", encoding="utf-8") as stream:
            reloaded = list(csv.DictReader(stream))
        require(len(reloaded) == len(preds), "Saved predictions truncated")
        scores_by_run = {}
        for i, run in enumerate(runs):
            rows = reloaded[i*200:(i+1)*200]
            require([(int(r["seed"]), r["method"], r["block_id"], int(r["label"]), int(r["length"])) for r in rows]
                    == list(zip([run["seed"]]*200, [run["method"]]*200, ids, y, qlen)), "Saved query rows differ")
            s = np.array([float(r["score"]) for r in rows])
            require(np.isfinite(s).all() and (s > 0).tolist() == [bool(int(r["prediction"])) for r in rows],
                    "Saved predictions do not match threshold")
            require(all(math.isclose(v, run[k], rel_tol=0, abs_tol=1e-12)
                        for k, v in main_metrics(y, s).items()), "Saved metrics differ")
            scores_by_run[run["seed"], run["method"]] = s

        phase = "paired_and_posthoc_reporting"
        by_seed = {(r["seed"], r["method"]): r for r in runs}
        pairs = [dict(seed=seed, fallback=by_seed[seed, "length_two"]["fallback"],
                      **{f"delta_{k}": by_seed[seed, "length_two"][k]-by_seed[seed, "single"][k]
                         for k in PAIRED}) for seed in frozen.SEEDS]
        for row in pairs:
            if row["fallback"]:
                require(all(row[f"delta_{k}"] == 0 for k in PAIRED) and np.array_equal(
                    scores_by_run[row["seed"], "single"], scores_by_run[row["seed"], "length_two"]),
                    "Fallback predictions diverged")
        write_csv(DEST / "paired_final_comparison.csv", pairs)
        paired = {}
        for k in PAIRED:
            delta = np.array([row[f"delta_{k}"] for row in pairs])
            paired[k] = {**summary(delta), "positive": int((delta > 1e-12).sum()),
                         "negative": int((delta < -1e-12).sum()), "equal": int((abs(delta) <= 1e-12).sum())}
        length_report = {}
        for a, b in ((2, 4), (5, 19), (20, 29), (30, 50)):
            mask = (qlen >= a) & (qlen <= b)
            counts = np.bincount(y[mask], minlength=2).tolist()
            results = {}
            for method in METHODS:
                bins = []
                for seed in frozen.SEEDS:
                    scores = scores_by_run[seed, method][mask]
                    if not len(scores):
                        continue
                    actual = y[mask]
                    pred = scores > 0
                    bins.append(dict(seed=seed,
                        anomaly_recall=float(pred[actual == 1].mean()) if counts[1] else None,
                        normal_fpr=float(pred[actual == 0].mean()) if counts[0] else None,
                        roc_auc=metrics(actual, scores)["roc_auc"],
                        score_normal=summary(scores[actual == 0]), score_anomaly=summary(scores[actual == 1])))
                keys = ("anomaly_recall", "normal_fpr", "roc_auc")
                results[method] = {"runs": bins, **{k: summary(r[k] for r in bins) for k in keys},
                    "seed_median_score_normal": summary(r["score_normal"]["median"] for r in bins) if counts[0] else None,
                    "seed_median_score_anomaly": summary(r["score_anomaly"]["median"] for r in bins) if counts[1] else None}
            length_report[f"{a}-{b}"] = {"counts_normal_anomaly": counts, "methods": results}
        save(DEST / "final_length_analysis.json", length_report)
        save(DEST / "final_summary.json", {
            "status": "completed_one_locked_final_evaluation", "lock_sha256": LOCK,
            "query_sha256": sha(ids), "seeds": list(frozen.SEEDS), "threshold": 0, "query_count": 200,
            "fallback_seeds": [r["seed"] for r in support_plan if r["fallback"]],
            "metrics": {method: {k: summary(r[k] for r in runs if r["method"] == method) for k in FIELDS}
                        for method in METHODS},
            "paired": paired, "paired_sign_tolerance": 1e-12,
            "encoded_seconds": encode_time, "seconds_including_preflight": time.perf_counter()-started,
            "peak_working_set_mib": peak_working_set_mib(),
            "checked_saved_predictions": len(reloaded), "weights_and_inputs_unchanged": True,
        })
    except BaseException:
        save(DEST / "incident.json", {"phase": phase, "traceback": format_exc(), "no_automatic_retry": True})
        raise
    print("Completed one locked final evaluation: 40 runs, 8000 verified predictions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    start = time.perf_counter()
    prepared = preflight()
    print("Preflight passed; final NPZs have been hashed but not loaded.", flush=True)
    if not args.preflight_only:
        evaluate(prepared, start)
