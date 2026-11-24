"""Offline audit, manifest validation, aggregation and report."""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from itertools import groupby
from pathlib import Path

from app.benchmark import GroundTruth, Review, load, paired, validate_manifest, validate_reviews
from app.micro_dataset import checksum
from tools.audit_research import audit as research_audit

ROOT = Path(__file__).resolve().parents[1]


def audit_runs(experiments):
    verified = load(experiments / "context_verification.json")
    context = {row["trace_id"]: row for row in verified["scenarios"] + verified["pilot"]}
    rows = []
    for path in sorted((experiments / "runs").glob("*.json")):
        item = load(path)
        trace = item["observed"]["trace_id"]
        telemetry = experiments / "telemetry" / f"{trace}.jsonl"
        raw = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()] if telemetry.exists() else []
        events = [{"event_id": e.get("event_id"), "service_name": e["service"], "message": e["event"],
                   "timestamp": e["timestamp"], "status_code": e.get("status")}
                  for e in raw if e.get("trace_id") == trace and {"timestamp", "service", "event"} <= e.keys()]
        valid = all(item["observed"].get(k) == item["expected_behavior"].get(k) for k in ("status", "error"))
        rows.append(("development" if trace in context else "engineering_history", path.stem, trace,
                     item["scenario_id"], events if telemetry.exists() else None,
                     "ENGINEERING_ORACLE_MATCH" if valid else "ENGINEERING_ORACLE_MISMATCH"))
    pilot = experiments / "micro_pilot_seed123"
    receipts = {row["run_id"]: row for row in load(pilot / "collection.json")["runs"]}
    for path in sorted((pilot / "observations").glob("*.json")):
        obs, label = load(path), load(pilot / "labels" / path.name)
        received = receipts.pop(path.stem)
        if (checksum(obs) != received["observation_sha256"] or checksum(label) != received["label_sha256"]
                or label["trace_id"] != obs["trace_id"]):
            raise ValueError("Pilot lineage or checksum mismatch")
        rows.append(("pilot", path.stem, obs["trace_id"], label["scenario_id"], obs["events"], "LAB_ORACLE_ONLY"))
    if receipts:
        raise ValueError("Pilot receipt is missing observations")
    family = {"cascade": "product-unavailable", "retry": "product-unavailable", "unavailable": "product-unavailable"}
    owner, parent, audited = {}, {}, []
    signatures, trace_ids, event_ids, times = Counter(), Counter(), Counter(), []

    def root(run):
        while parent[run] != run:
            run = parent[run]
        return run

    for split, run, trace, scenario, events, label_status in sorted(rows):
        retained = events is not None
        parent[run] = run
        trace_ids[trace] += 1
        event_ids.update(e["event_id"] for e in (events or ()) if e["event_id"])
        events = sorted(events or (), key=lambda e: (datetime.fromisoformat(e["timestamp"]), e["event_id"] or ""))
        templates = [(e["service_name"], e["message"]) for e in events]
        sequence = checksum([key for key, _ in groupby(templates)]) if events else None
        signature = checksum([(e["service_name"], e["message"], e.get("status_code")) for e in events]) if events else None
        keys = ["trace:" + trace, "family:" + family.get(scenario, scenario)]
        if events:
            signatures[signature] += 1
            keys.extend(("bag:" + checksum(sorted(set(templates))), "sequence:" + sequence))
            times.extend((events[0]["timestamp"], events[-1]["timestamp"]))
        keys.extend("event:" + event["event_id"] for event in events if event["event_id"])
        for key in keys:
            a, b = sorted((root(run), root(owner.setdefault(key, run))))
            parent[b] = a
        audited.append({"scenario": scenario, "run_id": run, "trace_id": trace, "source_class": split,
                        "event_count": len(events) if retained else None,
                        "events_without_id": sum(e["event_id"] is None for e in events) if retained else None,
                        "service_count": len({e["service_name"] for e in events}) if retained else None,
                        "telemetry_retained": retained,
                        "first_event": events[0]["timestamp"] if events else None,
                        "last_event": events[-1]["timestamp"] if events else None,
                        "completeness": context.get(trace, {}).get("status", "UNKNOWN"),
                        "ground_truth_availability": label_status, "normalized_template_sha256": sequence,
                        "observable_status_signature_sha256": signature, "eligible_for_evaluation": False})
    groups = {key: f"group-{i + 1:02d}" for i, key in enumerate(sorted({root(row["run_id"]) for row in audited}))}
    for row in audited:
        row["independence_group"] = groups[root(row["run_id"])]
    return {
        "rows": audited, "runs": len(audited), "unique_traces": len(trace_ids), "unique_events": len(event_ids),
        "duplicate_trace_ids": sum(x > 1 for x in trace_ids.values()),
        "duplicate_event_ids": sum(x > 1 for x in event_ids.values()),
        "runs_without_telemetry": sum(not row["telemetry_retained"] for row in audited),
        "events_without_id": sum(row["events_without_id"] or 0 for row in audited),
        "observed_events": sum(row["event_count"] or 0 for row in audited),
        "observable_signature_duplicate_clusters": sum(x > 1 for x in signatures.values()),
        "runs_in_observable_signature_duplicate_clusters": sum(x for x in signatures.values() if x > 1),
        "class_counts": dict(Counter(row["source_class"] for row in audited)),
        "completeness": dict(Counter(row["completeness"] for row in audited)),
        "group_sizes": dict(Counter(row["independence_group"] for row in audited)),
        "timestamp_range": [min(times, key=datetime.fromisoformat), max(times, key=datetime.fromisoformat)] if times else None,
        "payload_overlap": "UNMEASURABLE_REQUEST_PAYLOAD_NOT_RETAINED",
        "eligible_for_evaluation": 0, "locked_evaluation_manifest": False,
        "research_audit": research_audit(),
    }


def dump(path, result):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)


def report(result):
    lines = ["# Báo cáo đánh giá theo cặp", "",
             f"Nguồn kết quả: {result['data_kind']}. Hiệu số tính Cross trừ Single.", "",
             "| Chỉ số | Single | Cross |", "|---|---:|---:|"]
    single, cross = (result["modes"][x] for x in ("single_service", "cross_service"))
    for key, value in single.items():
        if isinstance(value, dict) and "denominator" in value:
            a, b = value, cross[key]
            lines.append(f"| {key} | {a['numerator']}/{a['denominator']} | {b['numerator']}/{b['denominator']} |")
    effect = result["paired_cause_accuracy_delta"]
    lines.extend(["", f"Cặp chấm được: {effect['scorable_pairs']}, nhóm: {effect['independent_groups']}.",
                  f"Hiệu số accuracy: {effect['value']}, CI bootstrap nhóm 95%: {effect['cluster_bootstrap_95']}.", ""])
    return "\n".join(lines)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="action", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--csv", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    aggr = commands.add_parser("aggregate")
    aggr.add_argument("--manifest", type=Path, required=True)
    aggr.add_argument("--reviews", type=Path, required=True)
    aggr.add_argument("--fixture", action="store_true")
    aggr.add_argument("--output", type=Path, required=True)
    render = commands.add_parser("report")
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    schema = commands.add_parser("schema")
    schema.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.action == "audit":
        if args.output.exists() or args.csv.exists():
            raise FileExistsError("Audit outputs already exist")
        result = audit_runs(ROOT / "experiments")
        dump(args.output, result)
        with args.csv.open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(result["rows"][0]))
            writer.writeheader()
            writer.writerows(result["rows"])
        print(f"Audited {result['runs']} runs. Evaluation eligible: 0.")
    elif args.action == "report":
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(report(load(args.input)))
    elif args.action == "schema":
        dump(args.output, {"ground_truth": GroundTruth.model_json_schema(),
                           "adjudicated_review": Review.model_json_schema()})
    else:
        protocol, cases = validate_manifest(args.manifest)
        if args.action == "validate":
            print(f"Validated locked manifest with {len(cases)} cases.")
        else:
            kind = "FIXTURE_ONLY" if args.fixture else "HUMAN_REVIEW_INPUT"
            if protocol["data_kind"] != kind:
                raise ValueError("CLI data kind does not match frozen protocol")
            reviews = validate_reviews(load(args.reviews), cases, protocol)
            dump(args.output, {**paired(protocol, cases, reviews),
                               "manifest_lock_sha256": load(args.manifest)["lock_sha256"],
                               "data_kind": kind})


if __name__ == "__main__":
    main()
