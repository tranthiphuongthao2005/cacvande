"""One authorized recovery, changing only the final runner's artifact boundary."""

import csv
import difflib
import json
import math
import tempfile
import time
from pathlib import Path
from traceback import format_exc
from unittest.mock import patch

import numpy as np

import final_evaluation as runner

INCIDENT = runner.HERE / "final_evaluation_locked_seed123"
OUTPUT = runner.HERE / "final_recovery_seed123"
REASON = "NumPy JSON serialization failure"


def python_value(value):
    if isinstance(value, np.ndarray):
        return python_value(value.tolist())
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return python_value(value.item())
    if isinstance(value, dict):
        return {python_value(key): python_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [python_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(python_value(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite artifact number")
    return value


def save_json(path, value):
    content = json.dumps(python_value(value), indent=2, allow_nan=False)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def save_csv(path, rows):
    clean = python_value(rows)
    fields = list(clean[0])
    runner.require(all(set(row) == set(fields) for row in clean), "CSV fields differ")
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(clean)


def fixture_test():
    f32, f64 = np.float32(0.12345679), np.float64(-0.012345678901234567)
    fixture = {"seed": np.int32(1000), "id": "fixture_001",
               "nested": {"int64": np.int64(2**54 + 1), "float32": f32, "float64": f64,
                          "bool": np.bool_(True), "array": np.array([[1, 2], [3, 4]], dtype=np.int32)},
               "list": [np.int32(3), f32, np.bool_(False)]}
    expected = {"seed": 1000, "id": "fixture_001",
                "nested": {"int64": 2**54 + 1, "float32": float(f32), "float64": float(f64),
                           "bool": True, "array": [[1, 2], [3, 4]]},
                "list": [3, float(f32), False]}
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        out = base / "fixture.json"
        save_json(out, fixture)
        restored = runner.read_json(out)
        runner.require(restored == expected and type(restored["nested"]["bool"]) is bool and
                       type(restored["nested"]["int64"]) is int, "JSON fixture mismatch")
        csv_path = base / "fixture.csv"
        save_csv(csv_path, [{"seed": np.int32(1000 + i), "id": f"fixture_{i:03}",
                             "score": value, "flag": np.bool_(i == 0)}
                            for i, value in enumerate((f32, f64))])
        with csv_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            runner.require(reader.fieldnames == ["seed", "id", "score", "flag"] and len(rows) == 2,
                           "CSV dimensions or fields differ")
        runner.require([(r["seed"], r["id"], float(r["score"]), r["flag"]) for r in rows] ==
                       [("1000", "fixture_000", float(f32), "True"),
                        ("1001", "fixture_001", float(f64), "False")], "CSV fixture mismatch")
        for i, value in enumerate((np.float32(np.nan), np.float64(np.inf), np.float64(-np.inf))):
            for kind, writer, payload in (
                ("json", save_json, {"value": [value]}), ("csv", save_csv, [{"value": value}])
            ):
                invalid = base / f"invalid-{i}.{kind}"
                try:
                    writer(invalid, payload)
                except ValueError:
                    runner.require(not invalid.exists(), "Invalid values created an artifact")
                else:
                    raise ValueError("Nonfinite fixture was accepted")
    return {"passed": True, "uses_final_data": False, "csv_rows": 2, "csv_columns": 4,
            "types": ["int32", "int64", "float32", "float64", "bool_", "ndarray", "dict", "list"],
            "json_fields_preserved": True, "seed_and_id_preserved": True,
            "float_policy": "lossless widening to Python float for float32; float64 unchanged",
            "nonfinite_json_and_csv_rejected_before_file_creation": True}


def validate(prepared):
    audit, fm, _, _, model, state, ckpt = prepared
    summary = runner.read_json(OUTPUT / "final_summary.json")
    plan = runner.read_json(OUTPUT / "final_support_seeds.json")
    seeds = list(range(1000, 1020))
    query = fm["pools"]["final_query"]
    support = {r["sequence_id"]: r for r in fm["pools"]["final_support"]}
    ids = [r["sequence_id"] for r in query]
    labels = np.array([r["label"] for r in query])
    expected_pairs = [(seed, method) for seed in seeds for method in runner.METHODS]
    with (OUTPUT / "final_runs.csv").open(newline="", encoding="utf-8") as stream:
        runs = list(csv.DictReader(stream))
    with (OUTPUT / "final_predictions.csv").open(newline="", encoding="utf-8") as stream:
        predictions = list(csv.DictReader(stream))
    runner.require(len(predictions) == 8000 and [(int(r["seed"]), r["method"]) for r in runs] == expected_pairs
                   and [p["seed"] for p in plan] == seeds and summary["threshold"] == 0 and
                   summary["lock_sha256"] == runner.LOCK, "Seed grid, counts, or lock differ")
    support_by_seed = {p["seed"]: p for p in plan}
    for i, run in enumerate(runs):
        seed = int(run["seed"])
        p = support_by_seed[seed]
        chosen = p["support_ids"]
        combined = chosen["Normal"] + chosen["Anomaly"]
        runner.require(len(chosen["Normal"]) == len(chosen["Anomaly"]) == 10 and len(set(combined)) == 20
                       and not set(combined).intersection(ids) and
                       all(support[x]["label"] == c for c, name in enumerate(("Normal", "Anomaly"))
                           for x in chosen[name]) and run["support_sha256"] == runner.sha(chosen)
                       and run["query_sha256"] == runner.sha(ids), "Support/query IDs invalid")
        short = sum(support[x]["true_length"] <= 4 for x in chosen["Anomaly"])
        fallback = min(short, 10-short) < 2
        runner.require(p["short"] == short and p["long"] == 10-short and p["fallback"] is fallback and
                       (run["fallback"] == "True") == (fallback and run["method"] == "length_two"),
                       "Fallback differs")
        block = predictions[200*i:200*(i+1)]
        runner.require([(int(r["seed"]), r["method"], r["block_id"], int(r["label"])) for r in block] ==
                       list(zip([seed]*200, [run["method"]]*200, ids, labels)), "Query order differs")
        scores = np.array([float(r["score"]) for r in block])
        pred = [int(r["prediction"]) for r in block]
        m = runner.main_metrics(labels, scores)
        runner.require(np.isfinite(scores).all() and pred == (scores > 0).astype(int).tolist() and
                       sum(m[k] for k in ("tn", "fp", "fn", "tp")) == 200 and
                       all(math.isclose(v, float(run[k]), rel_tol=0, abs_tol=1e-12) for k, v in m.items()),
                       "Score, confusion matrix, or metrics differ")
    runner.require(runner.readonly_hashes(ckpt) == audit["original_and_protected_files_sha256"] and
                   all(runner.digest(runner.HERE / audit["final_metadata"][name]["feature_path"]) ==
                       audit["final_metadata"][name]["feature_sha256"] for name in ("final_support", "final_query"))
                   and all(runner.torch.equal(t, state[k]) for k, t in model.state_dict().items()),
                   "Weights or input hash drift")
    return {"passed": True, "runs": len(runs), "scores": len(predictions), "predictions": len(predictions),
            "seeds": seeds, "fallback_seeds": [p["seed"] for p in plan if p["fallback"]]}


def main():
    started = time.perf_counter()
    runner.require(not OUTPUT.exists(), "Recovery already reserved; no retry")
    incident = runner.read_json(INCIDENT / "incident.json")
    previous = runner.read_json(INCIDENT / "final_protocol_verification.json")
    original_runner_hash = runner.digest(Path(runner.__file__))
    runner.require(incident["phase"] == "predictions_integrity" and incident["no_automatic_retry"] and
                   'save(DEST / "final_support_seeds.json", support_plan)' in incident["traceback"] and
                   "int32 is not JSON serializable" in incident["traceback"] and
                   original_runner_hash == previous["runner_sha256"] and previous["lock_sha256"] == runner.LOCK,
                   "Incident or original runner fingerprint differs")
    incident_hash = {p.name: runner.digest(p) for p in INCIDENT.iterdir() if p.is_file()}
    fixture = fixture_test()
    substitutions = "".join(difflib.unified_diff(
        ["DEST = final_evaluation_locked_seed123\n", "save = original JSON writer\n",
         "write_csv = original CSV writer\n"],
        ["DEST = final_recovery_seed123\n", "save = recovery bootstrap + save_json(python_value(value))\n",
         "write_csv = save_csv(python_value(rows))\n"],
        fromfile="original runtime bindings", tofile="authorized recovery runtime bindings"))
    diff = ("Original final_evaluation.py remains byte-identical to the incident runner.\n"
            f"Original SHA-256: {original_runner_hash}\n"
            f"Recovery wrapper SHA-256: {runner.digest(Path(__file__))}\n"
            "The runtime binding diff below is exhaustive for the original module.\n"
            "Recovery adds preflight artifacts and read-only postvalidation.\n\n" + substitutions)
    recovery = {"recovery_of": INCIDENT.name, "reason": REASON, "independent_final_test": False,
                "original_runner_sha256": original_runner_hash, "incident_artifacts_sha256": incident_hash,
                "recovery_wrapper_sha256": runner.digest(Path(__file__)), "automatic_retry": False}

    def save_with_preflight(path, value):
        if path.name == "final_protocol_verification.json":
            save_json(OUTPUT / "recovery_preflight.json",
                      {**value, **recovery, "serialization_fixture_passed": True})
            save_json(OUTPUT / "serialization_fixture_test.json", fixture)
            with (OUTPUT / "serialization_patch_diff.txt").open("x", encoding="utf-8") as stream:
                stream.write(diff)
        save_json(path, value)

    with patch.object(runner, "DEST", OUTPUT):
        prepared = runner.preflight()
        print("Fixture and locked preflight passed; starting the authorized recovery.", flush=True)
        try:
            with patch.object(runner, "save", save_with_preflight), patch.object(runner, "write_csv", save_csv):
                runner.evaluate(prepared, started)
            checked = validate(prepared)
            runner.require(incident_hash == {p.name: runner.digest(p) for p in INCIDENT.iterdir() if p.is_file()},
                           "Incident artifacts changed")
            save_json(OUTPUT / "recovery_manifest.json", {**recovery, "validation": checked})
        except BaseException:
            if OUTPUT.exists() and not (OUTPUT / "incident.json").exists():
                save_json(OUTPUT / "incident.json", {"phase": "recovery_artifacts_or_validation",
                          "traceback": format_exc(), "no_automatic_retry": True})
            raise
    print("Recovery complete and independently validated; no retry.", flush=True)


if __name__ == "__main__":
    main()
