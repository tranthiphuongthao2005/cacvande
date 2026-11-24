"""Bounded local collection and offline audit for benchmark readiness."""

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import file_digest
from itertools import groupby
from itertools import combinations
from pathlib import Path
from uuid import uuid4

import httpx

from app.benchmark import isolate, validate_context
from app.micro_dataset import checksum
from app.trace_store import valid_trace
from tools.audit_research import audit
from tools.collect_micro_dataset import ROOT, SETUPS, collect, write

MECHANISMS = {"normal": "baseline", "timeout": "dependency-delay", "unavailable": "product-unavailable",
              "database": "order-db-disconnected", "processing": "order-processing",
              "retry": "product-unavailable", "cascade": "product-unavailable"}
APP_FIELDS = {"event_id", "trace_id", "timestamp", "service", "span_id", "level", "event",
              "status", "dependency", "code"}
CONTEXT = "http://127.0.0.1:8015"


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def reconcile(telemetry, context, trace):
    app = [{k: v for k, v in row.items() if k in APP_FIELDS} for row in telemetry if "event_id" in row]
    docker = {row["event_id"]: row for row in app}
    indexed = {e.event_id: e for e in context.events}
    if len(docker) != len(app) or any(not valid_trace(key) for key in docker):
        raise ValueError("Duplicate or invalid Docker event ID")
    missing, extra = sorted(docker.keys() - indexed.keys()), sorted(indexed.keys() - docker.keys())
    mismatched = []
    for eid in docker.keys() & indexed.keys():
        d, e = docker[eid], indexed[eid]
        if (d["trace_id"] != e.trace_id or e.trace_id != trace or d["span_id"] != e.span_id or
                datetime.fromisoformat(d["timestamp"]) != e.timestamp or d["service"] != e.service_name or
                d["level"] != e.level or d["event"] != e.message or d.get("status") != e.status_code or
                d.get("dependency") != e.dependency_service or d.get("code") != e.error_type):
            mismatched.append(eid)
    spans = []
    for row in telemetry:
        ctx = row.get("context", {})
        if ctx.get("trace_id") == "0x" + trace:
            span_id = ctx["span_id"]
            spans.append({"span_id": span_id, "parent_id": row.get("parent_id"), "kind": row.get("kind"),
                          "end_time": row.get("end_time"),
                          "service": row.get("resource", {}).get("attributes", {}).get("service.name")})
    by_span = {span["span_id"]: span for span in spans}
    roots = [s["span_id"] for s in spans if s["kind"] == "SpanKind.SERVER" and not s["parent_id"] and s["end_time"]]
    return {"docker_events": app, "spans": spans, "missing_from_es": missing,
            "extra_in_es": extra, "field_mismatches": sorted(mismatched), "closed_root_spans": len(roots),
            "parent_links_observed": sum(s["parent_id"] in by_span for s in spans),
            "event_spans_missing": sum(e.span_id is None or "0x" + e.span_id not in by_span for e in context.events)}


def executed(scenario, valid_http, context):
    """Check scenario behavior only. Causal annotation requires a human."""
    events = context.events
    completions = {(e.service_name, e.status_code) for e in events if e.message == "request_completed"}
    failures = [e for e in events if e.message == "dependency_attempt_failed"]
    observed = {
        "normal": {("user", 200), ("product", 200), ("order", 201)} <= completions and not failures,
        "timeout": ("order", 504) in completions and len(failures) == 1 and any(
            e.service_name == "order" and e.error_type == "dependency_timeout" and e.dependency_service == "product"
            for e in failures),
        "unavailable": ("product", 503) in completions,
        "database": any(e.service_name == "order" and e.message == "database_connection_failed" for e in events),
        "processing": any(e.service_name == "order" and e.message == "order_processing_failed" for e in events),
        "retry": len(failures) == 3 and all(e.dependency_service == "product" for e in failures),
        "cascade": {("user", 200), ("product", 503), ("order", 502)} <= completions
        and any(e.service_name == "order" and e.dependency_service == "product" for e in failures),
    }
    return bool(valid_http and observed[scenario])


def groups(rows):
    owners, parents = {}, {}

    def root(key):
        while parents[key] != key:
            key = parents[key]
        return key

    for row in sorted(rows, key=lambda row: row["run_id"]):
        run = row["run_id"]
        if run in parents:
            raise ValueError("Duplicate run ID")
        parents[run] = run
        config = (row["fault_configuration_hash"], row["workload_family"])
        for item in [("campaign", row["campaign_id"]), ("signature", row["template_signature"]),
                     ("bag", row["template_bag"]), ("configuration", config)]:
            representative = owners.setdefault(item, run)
            a, b = sorted((root(run), root(representative)))
            parents[b] = a
    return {run: root(run) for run in parents}


def validate_split(rows, assignment, target):
    assigned = {r["run_id"] for r in rows}
    if set(assignment) != assigned or set(assignment.values()) != {"development", "evaluation"}:
        raise ValueError("Group-aware split must partition all runs into two nonempty folds")
    grouped = groups(rows)
    memberships, mechanisms = {}, {}
    for row in rows:
        run = row["run_id"]
        split = assignment[run]
        if memberships.setdefault(grouped[run], split) != split:
            raise ValueError("Execution group crosses split")
        if split == "evaluation" and (row["previously_exposed"] or row["annotation_status"] != "VERIFIED"
                                       or row.get("overlaps_history") or row.get("collection_status") != "VALID"):
            raise ValueError("Unverified or contaminated evaluation candidate")
        mechanisms.setdefault(row["scenario_family"], set()).add(split)
    evaluation = {r["scenario_family"] for r in rows if assignment[r["run_id"]] == "evaluation"}
    if target == "known" and any("development" not in mechanisms[family] for family in evaluation):
        raise ValueError("Known-fault evaluation requires family in development")
    if target == "unseen" and any("development" in mechanisms[family] for family in evaluation):
        raise ValueError("Unseen-fault evaluation requires unseen mechanisms")
    if target not in {"known", "unseen"}:
        raise ValueError("Unknown evaluation target")


def similarity(output, valid):
    templates = {}
    for row in valid:
        path = output / row["snapshots"]["cross_service"]["path"]
        value = json.loads(path.read_text(encoding="utf-8"))
        templates[row["run_id"]] = {(e["service_name"], e["message"]) for e in value["events"]}
    comparisons = []
    for left, right in combinations(valid, 2):
        a, b = (templates[row["run_id"]] for row in (left, right))
        comparisons.append({"runs": [left["run_id"], right["run_id"]],
                            "template_jaccard": len(a & b) / len(a | b),
                            "same_fault_configuration": left["fault_configuration_hash"] == right["fault_configuration_hash"],
                            "same_workload_family": left["workload_family"] == right["workload_family"],
                            "same_workload_configuration": left["workload_configuration_hash"] == right["workload_configuration_hash"],
                            "same_campaign": left["campaign_id"] == right["campaign_id"]})
    return comparisons


def validate_run_manifest(path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent.resolve()
    rows = manifest["runs"]
    if not rows or len({r["trace_id"] for r in rows}) != len(rows) or len({r["run_id"] for r in rows}) != len(rows):
        raise ValueError("Empty manifest or duplicate trace/run ID")
    seen_ids = set()
    for row in rows:
        if not valid_trace(row["trace_id"]) or not row["application_version"] or not row["source_environment"]:
            raise ValueError("Invalid provenance")
        for field, folder in (("telemetry_reference", "telemetry"), ("ground_truth_reference", "labels")):
            local = (root / row[field]).resolve(strict=True)
            if not local.is_relative_to(root / folder):
                raise ValueError("Ground truth/telemetry isolation violation")
            data = json.loads(local.read_text(encoding="utf-8"))
            if field == "telemetry_reference":
                isolate(data)
                ids = [e["event_id"] for e in data["docker_events"]]
                if len(ids) != len(set(ids)) or seen_ids.intersection(ids):
                    raise ValueError("Shared event ID")
                seen_ids.update(ids)
            elif data["trace_id"] != row["trace_id"] or data["run_id"] != row["run_id"]:
                raise ValueError("Label lineage mismatch")
            elif ("fault_configuration_hash" in row and
                    checksum(data["injected_fault_configuration"]) != row["fault_configuration_hash"]):
                raise ValueError("Fault configuration fingerprint mismatch")
        if ("workload_configuration_hash" in row and
                checksum(row["workload_configuration"]) != row["workload_configuration_hash"]):
            raise ValueError("Workload configuration fingerprint mismatch")
        contexts = {}
        for mode, descriptor in row["snapshots"].items():
            local = (root / descriptor["path"]).resolve(strict=True)
            if not local.is_relative_to(root / "snapshots") or digest(local) != descriptor["sha256"]:
                raise ValueError("Snapshot checksum or scope failure")
            address = "order" if mode == "single_service" else None
            context = validate_context(json.loads(local.read_text(encoding="utf-8")), row["trace_id"], mode, address)
            if descriptor["event_ids"] != context.evidence_event_ids:
                raise ValueError("Snapshot event IDs changed")
            if (descriptor["completeness"] != context.completeness_status or
                    descriptor["warnings"] != context.retrieval_warnings):
                raise ValueError("Snapshot quality metadata changed")
            contexts[mode] = context
        if "cross_service" not in contexts:
            raise ValueError("Missing Cross snapshot")
        expected = [event for event in contexts["cross_service"].events if event.service_name == "order"]
        if expected and ("single_service" not in contexts or contexts["single_service"].events != expected):
            raise ValueError("Invalid Single/Cross pairing")
    return manifest


def run(output, scenarios, repetitions, seed, seconds):
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("telemetry", "labels", "snapshots", "runs"):
        (output / folder).mkdir()
    campaign = uuid4().hex
    version = checksum({p: digest(ROOT / p) for p in (
        "app/api.py", "app/telemetry.py", "app/storage.py", "compose.yaml", "compose.logging.yaml",
        "compose.faults.yaml", "compose.dataset-latency.yaml")})
    history = set()
    with (ROOT / "experiments/benchmark_7a_audit.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            history.update((row["trace_id"], row["normalized_template_sha256"], row["observable_status_signature_sha256"]))
    rows = []
    with httpx.Client(timeout=8, trust_env=False) as client:
        def observe(record, telemetry, valid, target, fault, workload):
            run_id, trace, scenario = record["run_id"], record["trace_id"], record["scenario_id"]
            expected_count = sum("event_id" in row for row in telemetry)
            deadline = time.monotonic() + 27
            while True:
                response = client.get(f"{CONTEXT}/context/trace/{trace}")
                if response.status_code == 200:
                    raw = response.json()
                    if raw["event_count"] >= expected_count or time.monotonic() >= deadline:
                        break
                if time.monotonic() >= deadline:
                    response.raise_for_status()
                    raise ValueError("No retained Context snapshot")
                time.sleep(.5)
            cross = validate_context(raw, trace, "cross_service", None)
            quality = reconcile(telemetry, cross, trace)
            isolate(quality)
            telemetry_path = f"telemetry/{run_id}.json"
            write(output / telemetry_path, quality)
            behavior = executed(scenario, valid, cross)
            match = not any(quality[key] for key in ("missing_from_es", "extra_in_es", "field_mismatches"))
            snapshots = {}
            contexts = {"cross_service": cross}
            order_events = [e for e in cross.events if e.service_name == "order"]
            if order_events:
                single = client.get(f"{CONTEXT}/context/trace/{trace}", params={
                    "mode": "single_service", "service_name": "order",
                }).raise_for_status().json()
                s = validate_context(single, trace, "single_service", "order")
                if s.events != order_events:
                    raise ValueError("Single/Cross snapshot mismatch")
                contexts["single_service"] = s
            for mode, context in contexts.items():
                ref = f"snapshots/{run_id}-{mode}.json"
                write(output / ref, context.model_dump(mode="json"))
                snapshots[mode] = {"path": ref, "sha256": digest(output / ref), "event_ids": context.evidence_event_ids,
                                   "completeness": context.completeness_status, "warnings": context.retrieval_warnings}
            label_path = f"labels/{run_id}.json"
            label = {"run_id": run_id, "trace_id": trace, "annotation_status": "UNVERIFIED",
                     "expected_behavior": target, "injected_fault_configuration": fault,
                     "causal_chain_expected": ["Order calls Product", "Product unavailable", "Order propagates 502"]
                     if scenario in {"cascade", "retry"} else [],
                     "behavior_check": behavior, "root_cause_service": None, "root_cause_category": None,
                     "supporting_event_ids": [], "reviewer_role": None}
            write(output / label_path, label)
            signatures = [(e.service_name, e.message) for e in cross.events]
            sequence = checksum([key for key, _ in groupby(signatures)])
            exact = checksum([(e.service_name, e.message, e.status_code) for e in cross.events])
            warnings = list(cross.retrieval_warnings)
            if quality["event_spans_missing"]:
                warnings.append("EVENT_SPANS_MISSING_FROM_DOCKER")
            row = {"run_id": run_id, "trace_id": trace, "scenario_family": MECHANISMS[scenario],
                   "scenario_variant": scenario, "campaign_id": campaign,
                   "fault_configuration_id": f"lab-{scenario}", "fault_configuration_hash": checksum(fault),
                   "workload_configuration_id": f"serial-{workload['entry_service']}-lookup-v1",
                   "workload_configuration_hash": checksum(workload), "workload_family": workload["entry_service"],
                   "workload_configuration": workload, "collection_timestamp": record["timestamp"],
                   "source_environment": "compose-local-lab", "application_version": version,
                   "telemetry_reference": telemetry_path, "ground_truth_reference": label_path,
                   "http_status": record["observed_status"], "http_error_code": record["observed_error"],
                   "event_count": len(cross.events), "telemetry_reconciled": match, "behavior_confirmed": behavior,
                   "collection_status": "VALID" if behavior and match else "INVALID",
                   "annotation_status": "UNVERIFIED", "completeness": cross.completeness_status,
                   "warnings": warnings, "snapshots": snapshots, "evaluation_eligible": False,
                   "previously_exposed": True, "template_signature": sequence,
                   "template_bag": checksum(sorted(set(signatures))), "template_categories": sorted(set(signatures)),
                   "exact_log_signature": exact,
                   "overlaps_history": trace in history or sequence in history or exact in history}
            rows.append(row)
            write(output / "runs" / f"{run_id}.json", row)

        collect(output / "collector_receipts", repetitions, seed, scenarios, on_run=observe,
                deadline=time.monotonic() + seconds)
    group_ids = groups(rows)
    for row in rows:
        row["independence_group"] = group_ids[row["run_id"]]
    manifest = {"campaign_id": campaign, "seed": seed, "purpose": "pilot_known_fault",
                "evaluation_locked": False, "runs": rows}
    write(output / "run_manifest.json", manifest)
    validate_run_manifest(output / "run_manifest.json")
    write(output / "snapshot_manifest.json", {r["run_id"]: r["snapshots"] for r in rows})
    valid = [r for r in rows if r["collection_status"] == "VALID"]
    summary = {"runs": len(rows), "valid_runs": len(valid), "events": sum(r["event_count"] for r in valid),
               "unique_traces": len({r["trace_id"] for r in valid}),
               "execution_ids": len({r["run_id"] for r in valid}),
               "distinct_fault_configurations": len({r["fault_configuration_hash"] for r in valid}),
               "distinct_workload_configurations": len({r["workload_configuration_hash"] for r in valid}),
               "fault_mechanism_groups": sorted({r["scenario_family"] for r in valid if r["scenario_family"] != "baseline"}),
               "conservative_independence_groups": dict(Counter(group_ids.values())),
               "configuration_independence_verified": False,
               "pairwise_similarity": similarity(output, valid),
               "exact_signature_clusters": dict(Counter(r["exact_log_signature"] for r in valid)),
               "completeness": dict(Counter(r["completeness"] for r in valid)),
               "pair_count": sum(len(r["snapshots"]) == 2 for r in valid),
               "matches_history": sum(r["overlaps_history"] for r in valid),
               "ground_truth": dict(Counter(r["annotation_status"] for r in valid)),
               "eligible_for_evaluation": 0, "research_audit": audit()}
    write(output / "independence_report.json", summary)
    fields = ("run_id", "trace_id", "scenario_variant", "collection_status", "event_count", "telemetry_reconciled",
              "behavior_confirmed", "completeness", "warnings", "annotation_status", "independence_group",
              "overlaps_history", "evaluation_eligible")
    with (output / "quality_audit.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    write(output / "checksum_manifest.json", {p.relative_to(output).as_posix(): digest(p)
                                               for p in sorted(output.rglob("*")) if p.is_file()})


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--scenario", action="append", choices=SETUPS)
    cli.add_argument("--repetitions", type=int, choices=(2, 3), default=2)
    cli.add_argument("--seed", type=int, default=124)
    cli.add_argument("--seconds", type=int, choices=range(60, 601), default=420)
    cli.add_argument("--execute-lab", action="store_true")
    cli.add_argument("--validate", type=Path)
    cli.add_argument("--similarity-output", type=Path)
    cli.add_argument("--split", type=Path)
    cli.add_argument("--target", choices=("known", "unseen"), default="known")
    args = cli.parse_args()
    if args.validate:
        manifest = validate_run_manifest(args.validate)
        if args.similarity_output:
            write(args.similarity_output, similarity(args.validate.parent, [
                row for row in manifest["runs"] if row["collection_status"] == "VALID"
            ]))
        if args.split:
            assignment = json.loads(args.split.read_text(encoding="utf-8"))
            validate_split(manifest["runs"], assignment, args.target)
        print(f"Validated {len(manifest['runs'])} pilot runs")
        return
    scenarios = list(dict.fromkeys(args.scenario or ["normal", "cascade"]))
    if len(scenarios) * args.repetitions > 8:
        cli.error("Maximum eight requests per batch")
    if not args.execute_lab:
        print(json.dumps({"mode": "dry-run", "target": "compose-local-lab", "scenarios": scenarios,
                          "requests": len(scenarios) * args.repetitions, "scheduling_deadline_seconds": args.seconds}))
        return
    if args.output is None or not args.output.resolve().is_relative_to((ROOT / "experiments").resolve()):
        cli.error("Output must be a new directory within experiments/")
    run(args.output.resolve(), scenarios, args.repetitions, args.seed, args.seconds)


if __name__ == "__main__":
    main()
