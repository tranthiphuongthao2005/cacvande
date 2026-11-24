import copy
from pathlib import Path

import pytest

from app.benchmark import isolate
from app.micro_dataset import checksum
from tools.verify_ground_truth_7a2 import assess, dossier, read, run, validate_review

PILOT = Path(__file__).resolve().parents[1] / "experiments/benchmark_7a1_pilot_seed124"


@pytest.fixture
def source():
    row = next(r for r in read(PILOT / "run_manifest.json")["runs"] if r["scenario_variant"] == "cascade")
    return (row, read(PILOT / row["telemetry_reference"]),
            read(PILOT / row["snapshots"]["cross_service"]["path"]), read(PILOT / row["ground_truth_reference"]))


def test_dossier_links_order_product_and_preserves_blank_review(source):
    evidence = dossier(*source)
    assert evidence["candidate_root_cause_service"] == "product"
    assert evidence["evidence_sufficient_for_candidate_review"]
    assert evidence["reviewer_status"] == "NEEDS_REVIEW"
    assert evidence["verification_status"] == "UNVERIFIED"
    assert {edge["callee"] for edge in evidence["supporting_evidence"]["linked_calls"]} == {"user", "product"}
    form = {"run_id": evidence["run_id"], "dossier_sha256": checksum(evidence), "status": "NEEDS_REVIEW",
            "reviewer_id": None, "reviewed_at": None, "reason": None}
    validate_review(form, evidence)
    with pytest.raises(ValueError, match="Reviewer identity"):
        validate_review({**form, "status": "VERIFIED"}, evidence)
    for state in ("VERIFIED", "REJECTED", "INCONCLUSIVE"):
        validate_review({**form, "status": state, "reviewer_id": "fixture-reviewer",
                         "reviewed_at": "2026-11-22T22:01:00Z", "reason": "Fixture only"}, evidence)


def test_sealed_trace_and_delayed_ack(source):
    row, telemetry, cross, _ = source
    trace = row["trace_id"]
    root, = [s for s in telemetry["spans"] if s["parent_id"] is None]
    ids = cross["evidence_event_ids"]
    receipt = {"trace_id": trace, "capture_cutoff": "2026-11-22T20:01:00Z", "source_closed": True,
               "snapshot_observed_at": "2026-11-22T20:02:00Z", "expected_event_ids": ids,
               "expected_span_ids": [s["span_id"] for s in telemetry["spans"]],
               "root_span_id": root["span_id"], "indexed_ack_at": {eid: "2026-11-22T20:01:30Z" for eid in ids}}
    old = assess(trace, telemetry, cross)
    assert old["request_completed"] and old["docker_es_reconciled"] and old["classification"] == "PARTIAL"
    assert assess(trace, telemetry, cross, receipt)["classification"] == "COMPLETE"
    early = assess(trace, telemetry, cross, {**receipt, "snapshot_observed_at": "2026-11-22T20:01:20Z"})
    assert not early["ingestion_settled"] and early["classification"] == "PARTIAL"
    late = {**cross, "events": cross["events"][:-1]}
    assert not assess(trace, telemetry, late, receipt)["trace_complete"]
    degraded = {**cross, "retrieval_warnings": ["TRUNCATED_RESULT"]}
    assert not assess(trace, telemetry, degraded, receipt)["trace_complete"]
    child_missing = {**telemetry, "spans": [s for s in telemetry["spans"] if s["service"] != "product"]}
    result = assess(trace, child_missing, cross, receipt)
    assert not result["parent_graph_valid"] and not result["trace_complete"]
    no_marker = copy.deepcopy(telemetry)
    completion = next(e for e in no_marker["docker_events"] if e["service"] == "order"
                      and e["event"] == "request_completed")
    completion["event"] = "request_failed"
    result = assess(trace, no_marker, cross, receipt)
    assert not result["request_completed"] and not result["trace_complete"]


def test_repeat_audit_preserves_pilot_and_isolates_ground_truth(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    run(PILOT, first)
    run(PILOT, second)
    assert read(first / "checksum_manifest.json") == read(second / "checksum_manifest.json")
    records = read(first / "audit.json")["runs"]
    assert len(records) == 4 and all(r["review_status"] == "NEEDS_REVIEW" for r in records)
    assert sum(r["candidate_label"] == "NORMAL_CONTROL_OBSERVED" for r in records) == 2
    for record in records:
        assert not record["completeness"]["trace_complete"]
        for snapshot in record["original_snapshots"].values():
            isolate(read(PILOT / snapshot["path"]))
