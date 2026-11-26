import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.context_integration import Settings, Worker, utc
from app.context_integration_client import ContextClient, ContextFailure
from app.context_integration_models import build_package, context_payload, gate, verified_package
from app.context_store import Snapshot
from app.incident_context import build_context
from app.monitoring_models import make_event
from app.monitoring_store import Claim
from test_monitoring_store import NOW, output
from test_rule_detection import TRACE, completion


def context(rows):
    return build_context(TRACE, "cross_service", None, Snapshot(rows)).model_dump(mode="json")


def detection(rows=None, eligibility="ELIGIBLE", version=1):
    rows = rows if rows is not None else [completion(status=503)]
    claim = Claim(TRACE, version, "token", 1, {})
    return make_event(output(rows), claim, NOW).model_copy(update={
        "incident_eligibility": eligibility, "eligibility_reason": "OBSERVED_HTTP_5XX_COMPLETION",
    })


@pytest.mark.parametrize(("status", "eligibility", "expected"), [
    ("ANOMALY", "ELIGIBLE", None), ("ANOMALY", "NEEDS_MORE_EVIDENCE", None),
    ("ANOMALY", "RECOVERED_SIGNAL", "RECOVERED_SIGNAL"), ("ANOMALY", "NOT_ELIGIBLE", "NOT_ELIGIBLE"),
    ("NO_ANOMALY_DETECTED", "NOT_ELIGIBLE", "DETECTION_NO_ANOMALY_DETECTED"),
    ("INSUFFICIENT_DATA", "NEEDS_MORE_EVIDENCE", "DETECTION_INSUFFICIENT_DATA"),
    ("DETECTION_ERROR", "NOT_ELIGIBLE", "DETECTION_DETECTION_ERROR"),
])
def test_eligibility_gate(status, eligibility, expected):
    event = detection(eligibility=eligibility).model_copy(update={
        "detection_status": status, "is_anomaly": True if status == "ANOMALY" else None,
    })
    assert gate(event) == expected


@pytest.mark.parametrize(("case", "expected", "reconciliation"), [
    ("partial", "READY_FOR_ANALYSIS", "MATCHED"),
    ("unknown", "READY_FOR_ANALYSIS", "MATCHED"),
    ("complete", "READY_FOR_ANALYSIS", "MATCHED"),
    ("missing", "NEEDS_MORE_EVIDENCE", "MISSING_EVIDENCE"),
    ("partial_match", "NEEDS_MORE_EVIDENCE", "PARTIAL_MATCH"),
    ("conflict_count", "NEEDS_REVIEW", "CONFLICTING_EVIDENCE"),
    ("conflict_id", "NEEDS_REVIEW", "CONFLICTING_EVIDENCE"),
    ("needs_evidence", "NEEDS_MORE_EVIDENCE", "MATCHED"),
    ("truncated", "NEEDS_REVIEW", "MATCHED"),
])
def test_package_preserves_evidence_and_completeness(case, expected, reconciliation):
    anomaly = completion(status=503)
    other = completion(6)
    events = [other] if case == "missing" else [anomaly, other]
    raw = context(events)
    event = detection([anomaly, completion(7, status=502)] if case == "partial_match" else [anomaly],
                      "NEEDS_MORE_EVIDENCE" if case == "needs_evidence" else "ELIGIBLE")
    if case in {"partial", "unknown", "complete"}:
        raw["completeness_status"] = case.upper()
    if case == "conflict_count":
        raw["data_quality"]["conflicting_event_ids"] = 2
    if case == "conflict_id":
        event = event.model_copy(update={"conflicting_evidence_event_ids": [anomaly["event_id"]]})
    if case == "truncated":
        raw["retrieval_warnings"].append("TRUNCATED_RESULT")
    package = build_package(event, context_payload(raw, TRACE), SimpleNamespace(attempt=2, last_error="CONTEXT_HTTP_503"),
                            {}, "test", utc(NOW), utc(NOW + 1))
    assert package.analysis_readiness == expected and package.evidence_reconciliation_status == reconciliation
    assert package.context_completeness == raw["completeness_status"]
    assert other["event_id"] in package.additional_context_event_ids
    assert package.detection_evidence_ids == event.evidence_event_ids
    assert package.retry_count == 1 and package.last_error_code == "CONTEXT_HTTP_503"
    assert verified_package(package.model_dump_json()) == package
    corrupted = package.model_dump(mode="json")
    corrupted["context_payload"]["completeness_status"] = "COMPLETE" if case != "complete" else "PARTIAL"
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        verified_package(json.dumps(corrupted))


@pytest.mark.parametrize(("case", "code", "retry"), [
    ("ok", None, False), ("trace", "CONTEXT_SCOPE_MISMATCH", False),
    ("event_trace", "INVALID_CONTEXT_EVENT_IDENTITY", False),
    ("bad_schema", "INVALID_CONTEXT_RESPONSE", False),
    ("invalid_time", "INVALID_CONTEXT_RESPONSE", False),
    ("duplicate", "DUPLICATE_CONTEXT_EVENT", False),
    ("conflicting", "CONFLICTING_CONTEXT_EVENT", False),
    ("ground_truth", "UNEXPECTED_CONTEXT_METADATA", False),
    ("fault_metadata", "INVALID_CONTEXT_RESPONSE", False),
    ("credential", "UNEXPECTED_EVENT_CONTENT", False),
    ("timeline_leak", "INVALID_CONTEXT_RESPONSE", False),
    ("missing", "CONTEXT_TRACE_NOT_FOUND", False), ("unavailable", "CONTEXT_HTTP_503", True),
    ("bad_request", "CONTEXT_HTTP_422", False), ("timeout", "CONTEXT_TIMEOUT", True),
    ("too_large", "CONTEXT_PAYLOAD_TOO_LARGE", False),
])
def test_context_client_validation(case, code, retry):
    async def exercise():
        raw = context([completion(status=503)])
        if case == "trace":
            raw["trace_id"] = "c" * 32
        if case == "event_trace":
            raw["events"][0]["trace_id"] = "c" * 32
        if case == "bad_schema":
            del raw["services"]
        if case == "invalid_time":
            raw["events"][0]["timestamp"] = "broken"
        if case in {"duplicate", "conflicting"}:
            raw["events"].append({**raw["events"][0],
                                  "status_code": 200 if case == "conflicting" else raw["events"][0]["status_code"]})
        if case == "ground_truth":
            raw["data_quality"]["ground_truth"] = 1
        if case == "fault_metadata":
            raw["events"][0]["activation"] = "never retain"
        if case == "credential":
            raw["events"][0]["error_type"] = "postgresql://user:secret@database"
        if case == "timeline_leak":
            raw["timeline"][0]["authorization"] = "Bearer secret"

        async def mock(request):
            assert request.url.path == f"/context/trace/{TRACE}"
            assert dict(request.url.params) == {"mode": "cross_service", "wait_ms": "0"}
            assert "Authorization" not in request.headers
            if case == "timeout":
                await asyncio.Event().wait()
            if case in {"missing", "unavailable", "bad_request"}:
                return httpx.Response({"missing": 404, "unavailable": 503, "bad_request": 422}[case],
                                      content=b"super secret raw response")
            return httpx.Response(200, json=raw)

        settings = Settings(timeout_seconds=.1, max_payload_bytes=256 if case == "too_large" else 1048576)
        async with httpx.AsyncClient(base_url="http://fixture-context", transport=httpx.MockTransport(mock)) as http:
            client = ContextClient(http, settings)
            if code:
                with pytest.raises(ContextFailure, match=code) as caught:
                    await client.retrieve(TRACE)
                assert caught.value.retryable == retry
                assert "secret" not in str(caught.value)
            else:
                assert (await client.retrieve(TRACE)).evidence_event_ids == raw["evidence_event_ids"]
    asyncio.run(exercise())


def test_disabled_has_no_storage_or_http_side_effect():
    asyncio.run(Worker(Settings(), None, None).run())
