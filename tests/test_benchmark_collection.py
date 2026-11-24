import json

import pytest

from app.context_store import Snapshot
from app.incident_context import build_context
from tools.collect_benchmark_7a1 import executed, groups, reconcile, validate_run_manifest, validate_split

TRACE = "a" * 32


def app_event(i, service, status, **fields):
    return {"event_id": f"{i:032x}", "trace_id": TRACE, "service": service, "status": status,
            "event": "request_completed", "level": "INFO", "span_id": "b" * 16,
            "timestamp": "2026-11-22T17:00:00+00:00", **fields}


def context(rows):
    return build_context(TRACE, "cross_service", None, Snapshot([
        {"event_id": e["event_id"], "trace_id": TRACE, "service_name": e["service"], "status_code": e["status"],
         "message": e["event"], "level": e["level"], "span_id": e["span_id"], "@timestamp": e["timestamp"],
         "dependency_service": e.get("dependency")} for e in rows]))


def test_reconcile_preserves_partial_and_detects_corruption():
    normal = [app_event(1, "user", 200), app_event(2, "product", 200), app_event(3, "order", 201)]
    snapshot = context(normal)
    result = reconcile(normal, snapshot, TRACE)
    assert result["field_mismatches"] == result["missing_from_es"] == []
    assert snapshot.completeness_status != "COMPLETE" and result["closed_root_spans"] == 0
    assert result["event_spans_missing"] == 3
    assert reconcile(normal, context(normal[:-1]), TRACE)["missing_from_es"] == [normal[-1]["event_id"]]
    assert reconcile([{**normal[0], "status": 404}, *normal[1:]], snapshot, TRACE)["field_mismatches"]
    with pytest.raises(ValueError, match="Duplicate"):
        reconcile(normal + [normal[0]], snapshot, TRACE)


def test_fault_needs_causal_observation_beyond_http():
    events = [app_event(1, "user", 200), app_event(2, "product", 503), app_event(3, "order", 502)]
    assert not executed("cascade", True, context(events))
    failure = {**app_event(4, "order", 502), "event": "dependency_attempt_failed", "dependency": "product"}
    assert executed("cascade", True, context(events + [failure]))
    assert not executed("cascade", False, context(events + [failure]))


def test_group_aware_known_and_unseen_are_distinct():
    def row(run, campaign, template, family):
        return {"run_id": run, "campaign_id": campaign, "template_signature": template,
                "template_bag": template, "fault_configuration_hash": run, "workload_family": "order",
                "scenario_family": family, "previously_exposed": False, "annotation_status": "VERIFIED",
                "collection_status": "VALID"}

    a, b = row("a", "one", "1", "known"), row("b", "two", "2", "known")
    assert groups([b, a]) == groups([a, b])
    assignment = {"a": "development", "b": "evaluation"}
    validate_split([a, b], assignment, "known")
    with pytest.raises(ValueError, match="unseen mechanisms"):
        validate_split([a, b], assignment, "unseen")
    with pytest.raises(ValueError, match="crosses split"):
        validate_split([a, {**b, "template_bag": "1"}], assignment, "known")
    with pytest.raises(ValueError, match="contaminated"):
        validate_split([a, {**b, "annotation_status": "UNVERIFIED"}], assignment, "known")


def test_manifest_leakage_duplicates_and_snapshot_hash(tmp_path):
    from tools.collect_benchmark_7a1 import digest

    for folder in ("telemetry", "labels", "snapshots"):
        (tmp_path / folder).mkdir()
    raw = [app_event(1, "order", 201)]
    cross = context(raw).model_dump(mode="json")
    single = {**cross, "mode": "single_service", "selected_service": "order"}
    for name, value in {
        "telemetry/one.json": {"docker_events": raw},
        "labels/one.json": {"run_id": "one", "trace_id": TRACE},
        "snapshots/cross.json": cross, "snapshots/single.json": single,
    }.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    snapshots = {}
    for mode, file, value in [("cross_service", "cross", cross), ("single_service", "single", single)]:
        path = f"snapshots/{file}.json"
        snapshots[mode] = {"path": path, "event_ids": value["evidence_event_ids"], "sha256": digest(tmp_path / path),
                           "completeness": value["completeness_status"], "warnings": value["retrieval_warnings"]}
    row = {"run_id": "one", "trace_id": TRACE, "source_environment": "fixture", "application_version": "fixture",
           "telemetry_reference": "telemetry/one.json", "ground_truth_reference": "labels/one.json",
           "snapshots": snapshots}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"runs": [row]}))
    assert validate_run_manifest(manifest) == validate_run_manifest(manifest)
    manifest.write_text(json.dumps({"runs": [row, row]}))
    with pytest.raises(ValueError, match="duplicate"):
        validate_run_manifest(manifest)
    manifest.write_text(json.dumps({"runs": [row]}))
    (tmp_path / "telemetry/one.json").write_text(json.dumps({"docker_events": raw, "injected_fault": "secret"}))
    with pytest.raises(ValueError, match="Label fields"):
        validate_run_manifest(manifest)
    (tmp_path / "telemetry/one.json").write_text(json.dumps({"docker_events": raw}))
    (tmp_path / "snapshots/cross.json").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        validate_run_manifest(manifest)
