from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.benchmark import isolate
from app.context_api import create_app
from app.context_store import Snapshot
from app.incident_context import build_context
from app.micro_dataset import checksum
from app.telemetry_receipts import Receipt, Seal, classify, decode, differences, envelope, fingerprint, resolve
from tools.collect_benchmark_7a1 import write
from tools.import_review_7a3 import signature, verify
from tools.verify_ground_truth_7a2 import read

TRACE = "a" * 32
EVENT = "b" * 32
NOW = "2026-11-22T20:00:00Z"


def row(event=EVENT):
    return {"trace_id": TRACE, "event_id": event, "@timestamp": NOW, "span_id": "c" * 16,
            "service_name": "order", "level": "INFO", "message": "request_completed",
            "status_code": 201, "endpoint": "/orders", "http_method": "POST"}


def reports():
    context = build_context(TRACE, "cross_service", None, Snapshot([row()]))
    seal = Seal(seal_version="source-seal-v1", run_id="d" * 32, trace_id=TRACE, source_service="order",
                source_completion_timestamp=NOW, root_span_completion_status=True, source_event_ids=[EVENT],
                expected_event_count=1, source_coverage="AUTHORITATIVE_CLOSED_CAPTURE", parent_graph_valid=True)
    receipt = Receipt(receipt_version="es-receipt-v1", run_id=seal.run_id, trace_id=TRACE,
                      expected_event_ids=[EVENT], observed_event_ids=[EVENT], missing_event_ids=[],
                      unexpected_event_ids=[], duplicate_event_ids=[], reconciliation_timestamp=NOW,
                      ingestion_settled_status="MATCHED_CAPTURE", event_content_matches=True,
                      event_sha256={EVENT: fingerprint(context.events[0].model_dump(mode="json"))})
    return context, seal, receipt


def test_completeness_guards_missing_and_scope():
    ctx, seal, receipt = reports()
    assert classify(ctx)["warnings"] == ["SOURCE_SEAL_MISSING", "INGESTION_RECEIPT_MISSING"]
    assert "INGESTION_RECEIPT_MISSING" in classify(ctx, seal)["warnings"]
    assert classify(ctx, seal, receipt)["trace_complete"]
    assert not classify(ctx, seal.model_copy(update={"parent_graph_valid": False}), receipt)["trace_complete"]
    observational = seal.model_copy(update={"source_coverage": "OBSERVED_CAPTURE_ONLY", "expected_event_count": None})
    result = classify(ctx, observational, receipt)
    assert result["ingestion_reconciled"] and not result["trace_complete"]
    single = build_context(TRACE, "single_service", "order", Snapshot([row()]))
    assert classify(single, seal, receipt)["classification"] == "UNKNOWN"


def test_delayed_missing_duplicate_and_content_mismatch():
    ctx, seal, receipt = reports()
    assert differences([EVENT], [EVENT, EVENT]) == ([], [], [EVENT])
    for update in [{"observed_event_ids": [], "missing_event_ids": [EVENT], "event_sha256": {}},
                   {"observed_event_ids": [EVENT, EVENT], "duplicate_event_ids": [EVENT]}]:
        mismatch = receipt.model_copy(update={**update, "ingestion_settled_status": "MISMATCH"})
        _, parsed = decode(envelope(seal, mismatch))
        assert not classify(ctx, seal, parsed)["trace_complete"]
    late = build_context(TRACE, "cross_service", None, Snapshot([row(), row("e" * 32)]))
    assert not classify(late, seal, receipt)["trace_complete"]
    changed = build_context(TRACE, "cross_service", None, Snapshot([{**row(), "status_code": 500}]))
    assert not classify(changed, seal, receipt)["trace_complete"]


def test_integrity_and_invalid_version(tmp_path):
    context, seal, receipt = reports()
    invalid = seal.model_copy(update={"seal_version": "other"})
    with pytest.raises(ValueError):
        decode(envelope(invalid, receipt))
    raw = envelope(seal, receipt)
    raw["seal"]["source_service"] = "user"
    write(tmp_path / f"{TRACE}.json", raw)
    result, provenance = resolve(context, tmp_path)
    assert "RECEIPT_UNTRUSTED_OR_INVALID" in result["warnings"] and provenance is None
    with pytest.raises(ValueError):
        isolate({"receipt": {"ground_truth": "hidden"}})


def test_context_version_keeps_old_schema_and_late_detection(tmp_path, monkeypatch):
    _, seal, receipt = reports()
    write(tmp_path / f"{TRACE}.json", envelope(seal, receipt))
    monkeypatch.setenv("CONTEXT_RECEIPT_DIR", str(tmp_path))
    rows = [row()]
    store = SimpleNamespace(fetch=lambda *_, **__: Snapshot(rows.copy()))
    with TestClient(create_app(store)) as api:
        old = api.get(f"/context/trace/{TRACE}").json()
        new = api.get(f"/context/v2/trace/{TRACE}").json()
        assert old == new["context"] and old["completeness_status"] == "PARTIAL"
        assert new["completeness"]["classification"] == "COMPLETE"
        rows.append(row("e" * 32))
        assert not api.get(f"/context/v2/trace/{TRACE}").json()["completeness"]["trace_complete"]


def test_reviewer_requires_authorization_and_bound_signature():
    files = Path(__file__).resolve().parents[1] / "experiments/benchmark_7a2_verification/dossiers"
    dossier = read(next(files.glob("*.json")))
    body = {"run_id": dossier["run_id"], "reviewer_id": "fixture", "reviewed_at": NOW,
            "decision": "INCONCLUSIVE", "reviewed_evidence_references": ["dossier:" + checksum(dossier)],
            "justification": "Fixture only"}
    key = "a1" * 32
    signed = {"decision": body, "signature": signature(body, key)}
    with pytest.raises(ValueError, match="signature"):
        verify({"decision": body}, dossier, {})
    with pytest.raises(ValueError, match="Unauthorized"):
        verify(signed, dossier, {})
    with pytest.raises(ValueError, match="not authorized"):
        verify(signed, dossier, {"fixture": {"key_hex": key, "run_ids": []}})
    allowlist = {"fixture": {"key_hex": key, "run_ids": [dossier["run_id"]]}}
    assert verify(signed, dossier, allowlist)["status"] == "INCONCLUSIVE"
    with pytest.raises(ValueError, match="Invalid reviewer signature"):
        verify({**signed, "decision": {**body, "decision": "VERIFIED"}}, dossier, allowlist)
