"""Offline pilot dossiers and source-seal completeness verification."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.benchmark import isolate
from app.micro_dataset import checksum
from app.trace_store import valid_trace
from tools.audit_research import audit
from tools.collect_benchmark_7a1 import digest, validate_run_manifest, write

DEFAULT = Path("experiments/benchmark_7a1_pilot_seed124")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def moment(value):
    t = datetime.fromisoformat(value)
    if t.utcoffset() is None:
        raise ValueError("Timestamp requires timezone")
    return t


def assess(trace, telemetry, cross, receipt=None):
    """Assess a trace against an optional receipt from a separately trusted, closed capture."""
    spans = telemetry["spans"]
    events = telemetry["docker_events"]
    by_id = {s["span_id"]: s for s in spans}
    roots = [s for s in spans if s["kind"] == "SpanKind.SERVER" and s["parent_id"] is None]

    def reaches_root(span):
        visited = set()
        while span["parent_id"] is not None:
            key = span["parent_id"]
            if key in visited or key not in by_id:
                return False
            visited.add(key)
            span = by_id[key]
        return bool(len(roots) == 1 and span == roots[0])

    root = roots[0] if len(roots) == 1 else None
    completed = bool(root and root["end_time"] and any(
        e["trace_id"] == trace and e["event"] == "request_completed" and
        "0x" + e["span_id"] == root["span_id"] and e["service"] == root["service"]
        and moment(e["timestamp"]) <= moment(root["end_time"]) for e in events))
    graph_ok = bool(root and len(by_id) == len(spans) and
                    all(s["end_time"] and reaches_root(s) for s in spans) and
                    all(e["trace_id"] == trace and "0x" + e["span_id"] in by_id for e in events))
    docker_ids = {e["event_id"] for e in events}
    indexed = {e["event_id"]: e for e in cross["events"]}
    indexed_ids = set(indexed)
    concordant = all(
        (e["trace_id"], e["service"], e["span_id"], moment(e["timestamp"]), e["level"],
         e["event"], e.get("status"), e.get("dependency"), e.get("code")) ==
        (d["trace_id"], d["service_name"], d["span_id"], moment(d["timestamp"]), d["level"],
         d["message"], d.get("status_code"), d.get("dependency_service"), d.get("error_type"))
        for e in events if (d := indexed.get(e["event_id"])) is not None)
    matched = bool(docker_ids and docker_ids == indexed_ids and len(events) == len(docker_ids)
                   and len(cross["events"]) == len(indexed_ids)
                   and concordant
                   and all(valid_trace(eid) for eid in docker_ids)
                   and cross["trace_id"] == trace and all(e["trace_id"] == trace for e in cross["events"])
                   and not any(telemetry[key] for key in ("missing_from_es", "extra_in_es", "field_mismatches")))
    settled, source_agrees = False, False
    if receipt is not None:
        cutoff = moment(receipt["capture_cutoff"])
        snapshot_at = moment(receipt["snapshot_observed_at"])
        source_events, source_spans = set(receipt["expected_event_ids"]), set(receipt["expected_span_ids"])
        acks = receipt["indexed_ack_at"]
        settled = bool(receipt["trace_id"] == trace and receipt["source_closed"] is True
                       and source_events and set(acks) == indexed_ids == source_events
                       and len(source_events) == len(receipt["expected_event_ids"])
                       and snapshot_at >= cutoff and all(moment(stamp) <= snapshot_at for stamp in acks.values()))
        source_agrees = bool(completed and graph_ok and source_events == docker_ids
                             and source_spans == set(by_id) and receipt["root_span_id"] == root["span_id"]
                             and len(source_spans) == len(receipt["expected_span_ids"])
                             and all(moment(s["end_time"]) <= cutoff for s in spans)
                             and all(moment(e["timestamp"]) <= cutoff and
                                     moment(e["timestamp"]) <= moment(acks[e["event_id"]])
                                     for e in events if e["event_id"] in acks))
    damage = {"TRUNCATED_RESULT", "ELASTICSEARCH_TIMEOUT_OR_INCOMPLETE_SEARCH", "INVALID_DOCUMENTS",
              "CONFLICTING_EVENT_IDS", "MISSING_SPAN_ID"}
    complete = bool(completed and settled and source_agrees and matched
                    and not damage.intersection(cross.get("retrieval_warnings", [])))
    return {"request_completed": completed, "parent_graph_valid": graph_ok, "docker_es_reconciled": matched,
            "ingestion_settled": settled, "trace_complete": complete,
            "classification": "COMPLETE" if complete else "PARTIAL" if completed or docker_ids else "UNKNOWN",
            "watermark_receipt_present": receipt is not None}


def dossier(row, telemetry, cross, label):
    trace = row["trace_id"]
    result = assess(trace, telemetry, cross)
    events, spans = telemetry["docker_events"], telemetry["spans"]
    by_id = {s["span_id"]: s for s in spans}
    statuses = sorted((e["service"], e["status"]) for e in events if e["event"] == "request_completed")
    expected = [("order", 201), ("product", 200), ("user", 200)]
    cascade = row["scenario_variant"] == "cascade"
    fault = label["injected_fault_configuration"]
    edges = []
    for e in events:
        if e["event"] == "request_completed" and e["service"] in {"product", "user"}:
            server = by_id.get("0x" + e["span_id"], {})
            client = by_id.get(server.get("parent_id"), {})
            parent = by_id.get(client.get("parent_id"), {})
            if (server.get("kind") == "SpanKind.SERVER" and server.get("service") == e["service"]
                    and client.get("kind") == "SpanKind.CLIENT" and client.get("service") == "order"
                    and parent.get("kind") == "SpanKind.SERVER" and parent.get("service") == "order"
                    and parent.get("parent_id") is None):
                edges.append({"caller": "order", "callee": e["service"], "server_event_id": e["event_id"],
                              "caller_span_id": client["span_id"], "root_span_id": parent["span_id"]})
    app_failure = [e for e in events if e["event"] == "dependency_attempt_failed"
                   and e.get("dependency") == "product" and e.get("code") == "dependency_unavailable"
                   and any(edge["callee"] == "product" and edge["caller_span_id"] == "0x" + e["span_id"]
                           for edge in edges)]
    if cascade:
        expected = [("order", 502), ("product", 503), ("user", 200)]
        behavior = bool(fault["product_fault"] == "unavailable" and row["http_status"] == 502
                        and row["http_error_code"] == "dependency_unavailable" and app_failure)
    else:
        behavior = bool(not fault["product_fault"] and not fault["order_fault"] and row["http_status"] == 201
                        and not any(e["level"] == "ERROR" or e["event"] == "dependency_attempt_failed" for e in events))
    expectation_matches = bool(behavior and statuses == expected and {e["callee"] for e in edges} == {"user", "product"}
                               and result["request_completed"] and result["parent_graph_valid"]
                               and result["docker_es_reconciled"])
    return {
        "run_id": row["run_id"], "trace_id": trace, "scenario_family": row["scenario_family"],
        "injected_fault": fault, "fault_configuration_matches_hash": checksum(fault) == row["fault_configuration_hash"],
        "injection_execution_status": ("OBSERVED_BEHAVIOR_CONSISTENT" if cascade and expectation_matches else
                                      "NO_INJECTION_CONTROL" if not cascade and expectation_matches else "UNCONFIRMED"),
        "observed_behavior": {"http_status": row["http_status"], "http_error_code": row["http_error_code"],
                              "request_completions": statuses},
        "candidate_root_cause": "Product lookup unavailable; Order reported dependency failure" if cascade and expectation_matches else None,
        "candidate_root_cause_service": "product" if cascade and expectation_matches else None,
        "candidate_label": "CAUSE_HYPOTHESIS" if cascade and expectation_matches else
                           "NORMAL_CONTROL_OBSERVED" if expectation_matches else "UNDETERMINED",
        "supporting_evidence": {"expected_causal_chain": label["causal_chain_expected"], "linked_calls": edges,
                                "event_ids": [e["event_id"] for e in events],
                                "telemetry_reference": row["telemetry_reference"]},
        "contradictory_evidence": [] if expectation_matches else ["Expected behavior or lineage was not confirmed"],
        "missing_evidence": ["INDEPENDENT_REVIEW", "SOURCE_SEAL_AND_INGEST_ACK"]
                            + (["INDEPENDENT_FAULT_ACTIVATION_RECORD"] if cascade else []),
        "evidence_sufficient_for_candidate_review": expectation_matches,
        "verification_status": "UNVERIFIED", "reviewer_status": "NEEDS_REVIEW", "completeness": result,
    }


def validate_review(form, evidence):
    if set(form) != {"run_id", "dossier_sha256", "status", "reviewer_id", "reviewed_at", "reason"}:
        raise ValueError("Unexpected review fields")
    if form["run_id"] != evidence["run_id"] or form["dossier_sha256"] != checksum(evidence):
        raise ValueError("Review refers to another dossier")
    fields = ("reviewer_id", "reviewed_at", "reason")
    if form["status"] == "NEEDS_REVIEW":
        if any(form[key] is not None for key in fields):
            raise ValueError("Blank review cannot contain a decision")
    elif form["status"] in {"VERIFIED", "REJECTED", "INCONCLUSIVE"}:
        if not all(isinstance(form[key], str) and form[key].strip() for key in fields):
            raise ValueError("Reviewer identity, timestamp and reason required")
        moment(form["reviewed_at"])
        if form["status"] == "VERIFIED" and not evidence["evidence_sufficient_for_candidate_review"]:
            raise ValueError("Dossier needs supplementary evidence before verification")
    else:
        raise ValueError("Invalid reviewer state")


def run(pilot, output):
    checks = read(pilot / "checksum_manifest.json")
    for name, expected in checks.items():
        path = (pilot / name).resolve(strict=True)
        if not path.is_relative_to(pilot.resolve()) or digest(path) != expected:
            raise ValueError("Pilot checksum mismatch")
    manifest = validate_run_manifest(pilot / "run_manifest.json")
    indexed_snapshots = read(pilot / "snapshot_manifest.json")
    if indexed_snapshots != {row["run_id"]: row["snapshots"] for row in manifest["runs"]}:
        raise ValueError("Snapshot manifests disagree")
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("dossiers", "review_forms"):
        (output / folder).mkdir()
    rows = []
    for row in manifest["runs"]:
        raw = read(pilot / row["telemetry_reference"])
        cross = read(pilot / row["snapshots"]["cross_service"]["path"])
        isolate(raw)
        label = read(pilot / row["ground_truth_reference"])
        evidence = dossier(row, raw, cross, label)
        name = row["run_id"]
        write(output / "dossiers" / f"{name}.json", evidence)
        form = {"run_id": name, "dossier_sha256": checksum(evidence), "status": "NEEDS_REVIEW",
                "reviewer_id": None, "reviewed_at": None, "reason": None}
        validate_review(form, evidence)
        write(output / "review_forms" / f"{name}.json", form)
        rows.append({"run_id": name, "trace_id": row["trace_id"], "candidate_label": evidence["candidate_label"],
                     "candidate_review_evidence": evidence["evidence_sufficient_for_candidate_review"],
                     "completeness": evidence["completeness"], "review_status": form["status"],
                     "original_snapshots": row["snapshots"]})
    write(output / "audit.json", {"runs": rows, "verified_pilot_files": len(checks),
                                  "verified_research_files": audit()["verified_unique_files"],
                                  "blind_evaluation_eligible": 0, "live_watermark": False})
    write(output / "checksum_manifest.json", {p.relative_to(output).as_posix(): digest(p)
                                               for p in sorted(output.rglob("*.json"))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, default=DEFAULT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--dossier", type=Path)
    args = parser.parse_args()
    if args.review and args.dossier:
        validate_review(read(args.review), read(args.dossier))
        print("Review record structurally valid; no labels changed.")
    elif args.output and not (args.review or args.dossier):
        run(args.pilot, args.output)
        print(f"Offline dossier audit saved to {args.output}")
    else:
        parser.error("Specify --output, or --review with --dossier")


if __name__ == "__main__":
    main()
