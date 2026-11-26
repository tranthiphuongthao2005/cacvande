import copy
import json

import pytest

from app.benchmark import isolate, load, paired, validate_manifest, validate_reviews
from app.context_store import Snapshot
from app.incident_context import build_context
from app.micro_dataset import checksum
from tools.benchmark import main, report


@pytest.fixture
def bundle(tmp_path):
    for folder in ("labels", "contexts"):
        (tmp_path / folder).mkdir()
    protocol = {"protocol_id": "fixture-only", "model": "fixture-model", "prompt_version": "fixture",
                "decoding": {"strategy": "fixture"}, "rubric_version": "v1", "output_schema": "v1",
                "single_service": "order", "reviewer_roles": ["reviewer"], "bootstrap_seed": 42,
                "bootstrap_min_groups": 2, "input_budget": 7000, "data_kind": "FIXTURE_ONLY"}

    def asset(path, obj):
        (tmp_path / path).write_text(json.dumps(obj), encoding="utf-8")
        return {"path": path, "sha256": checksum(obj)}

    rows, records = [], []
    for i in (1, 2, 3):
        trace, primary, secondary = [f"{i * 100 + n:032x}" for n in range(3)]
        raw = [{"trace_id": trace, "event_id": eid, "service_name": service,
                "level": "INFO", "message": event, "status_code": 200,
                "@timestamp": "2026-11-22T17:00:00Z"}
               for eid, service, event in [(primary, "order", "request_completed"),
                                           (secondary, "product", ("request_completed", "request_failed",
                                                                    "database_connection_failed")[i - 1])]]
        row = {"run_id": f"run-{i}", "trace_id": trace, "group": f"group-{i}", "campaign_id": f"campaign-{i}",
               "previously_exposed": False, "split": "evaluation", "contexts": {}}
        truth = {"run_id": row["run_id"], "trace_id": trace, "scenario_family": "test",
                 "injected_fault": "fixture", "injection_provenance": "fixture", "root_cause_service": "product",
                 "root_cause_category": "fixture", "expected_causal_chain": [], "affected_services": ["order"],
                 "supporting_event_ids": [secondary], "expected_observations": [],
                 "acceptable_root_cause_variants": ["fixture"], "annotation_status": "VERIFIED",
                 "reviewer_role": "fixture"}
        row["ground_truth"] = asset(f"labels/{i}.json", truth)
        for mode, service, events in [("single_service", "order", raw[:1]), ("cross_service", None, raw)]:
            context = build_context(trace, mode, service, Snapshot(events)).model_dump(mode="json")
            row["contexts"][mode] = asset(f"contexts/{i}-{mode}.json", context)
            key = "OK" if i != 3 or service is None else "PROVIDER_FAILURE"
            abstains = i == 3 and service is None
            records.append({"trace_id": trace, "mode": mode, "provider_status": key, "reviewer_id": "fixture",
                            "analysis_status": (("INSUFFICIENT_EVIDENCE" if abstains else "ANALYZED") if key == "OK" else None),
                            "adjudicated": True, "model_name": protocol["model"] if key == "OK" else None,
                            "config_sha256": checksum(protocol) if key == "OK" else None,
                            "input_event_ids": context["evidence_event_ids"] if key == "OK" else [],
                            "cause_correct": (service is None) if key == "OK" and not abstains else None,
                            "service_correct": None, "recommendations": [True, None] if key == "OK" else [],
                            "claims": [{"claim_id": "test", "event_ids": [primary], "judgement": "SUPPORTED"}]
                            if key == "OK" and not abstains else []})
        rows.append(row)
    manifest = {"protocol": protocol, "runs": rows}
    path = tmp_path / "manifest.json"

    def write(data):
        path.write_text(json.dumps({**data, "lock_sha256": checksum(data)}), encoding="utf-8")
        return path

    return manifest, write, records


def test_validate_manifest_detects_exposure_hash_overlap_and_campaign(bundle):
    manifest, write, _ = bundle
    assert len(validate_manifest(write(manifest))[1]) == 3
    for change, match in [
        ({"previously_exposed": True}, "exposed"),
        ({"trace_id": manifest["runs"][0]["trace_id"]}, "exposed"),
        ({"campaign_id": manifest["runs"][0]["campaign_id"]}, "Campaign"),
    ]:
        bad = copy.deepcopy(manifest)
        bad["runs"][1].update(change)
        with pytest.raises(ValueError, match=match):
            validate_manifest(write(bad))
    path = write(manifest)
    data = load(path)
    data["protocol"]["model"] = "tampered"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        validate_manifest(path)


def test_label_isolation_rejects_nested_fields_and_markers():
    for item in ({"timeline": [{"ground_truth": "hidden"}]}, {"message": "expected_root_cause: hidden"},
                 {"message": "Bearer fakefakefake"}):
        with pytest.raises(ValueError):
            isolate(item)


def test_pairing_evidence_and_missing_data(bundle):
    manifest, write, rows = bundle
    protocol, cases = validate_manifest(write(manifest))
    with pytest.raises(ValueError, match="Pair missing"):
        validate_reviews(rows[:-1], cases, protocol)
    bad = copy.deepcopy(rows)
    bad[0]["claims"][0]["event_ids"] = ["f" * 32]
    with pytest.raises(ValueError, match="Supported claim"):
        validate_reviews(bad, cases, protocol)
    bad[0]["claims"][0]["judgement"] = "HALLUCINATED"
    reviews = validate_reviews(bad, cases, protocol)
    result = paired(protocol, cases, reviews)
    assert result["modes"]["single_service"]["hallucination_rate"]["value"] == .5
    assert result["modes"]["single_service"]["provider_coverage"]["denominator"] == 3
    assert result["modes"]["cross_service"]["abstention_rate"]["numerator"] == 1
    assert result["paired_cause_accuracy_delta"]["value"] == 1
    assert result == paired(protocol, cases, reviews)
    assert result["paired_cause_accuracy_delta"]["cluster_bootstrap_95"] == [1, 1]
    assert paired({**protocol, "bootstrap_min_groups": 10}, cases, reviews)["paired_cause_accuracy_delta"]["cluster_bootstrap_95"] is None


def test_offline_cli_roundtrip(bundle, tmp_path, monkeypatch):
    manifest, write, rows = bundle
    path = write(manifest)
    reviews, result, markdown = (tmp_path / name for name in ("reviews.json", "result.json", "report.md"))
    reviews.write_text(json.dumps(rows))
    monkeypatch.setattr("sys.argv", ["benchmark", "validate", "--manifest", str(path)])
    main()
    monkeypatch.setattr("sys.argv", ["benchmark", "aggregate", "--manifest", str(path), "--reviews", str(reviews),
                                     "--fixture", "--output", str(result)])
    main()
    monkeypatch.setattr("sys.argv", ["benchmark", "report", "--input", str(result), "--output", str(markdown)])
    main()
    assert markdown.read_text(encoding="utf-8") == report(load(result))
    assert "FIXTURE_ONLY" in markdown.read_text(encoding="utf-8")
