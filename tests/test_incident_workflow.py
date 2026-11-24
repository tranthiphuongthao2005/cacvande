from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.context_store import Snapshot
from app.incident_context import build_context
from app.incident_workflow import Ledger, create_app
from app.llm_api import create_app as llm_app
from app.llm_provider import MockProvider

TRACE = "a" * 32
TOKEN = "fixture-token-" * 3
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PAYLOAD = {"trace_id": TRACE, "analysis_mode": "cross_service", "request_id": "fixture-one"}


def context(query):
    return build_context(query.trace_id, query.mode, query.service_name, Snapshot([{
        "event_id": "b" * 32, "trace_id": query.trace_id, "@timestamp": "2026-11-22T17:00:00Z",
        "service_name": "order", "span_id": "b" * 16, "level": "ERROR",
        "message": "request_completed", "status_code": 502, "endpoint": "/orders", "http_method": "POST",
    }])).model_dump(mode="json")


def test_authenticated_workflow_idempotency_and_persistence(tmp_path):
    db = tmp_path / "incidents.db"
    calls = []
    with TestClient(llm_app(SimpleNamespace(fetch=context), MockProvider())) as llm:
        def route(request):
            calls.append(request.method)
            if request.method == "GET":
                value = context(SimpleNamespace(trace_id=TRACE, mode="cross_service", service_name=None))
                return httpx.Response(200, json=value)
            assert request.headers["X-Required-Provider"] == "mock"
            response = llm.post("/analyze/trace", content=request.content,
                                headers={"X-Required-Provider": "mock", "content-type": "application/json"})
            return httpx.Response(response.status_code, json=response.json())

        with httpx.Client(transport=httpx.MockTransport(route)) as outbound:
            with TestClient(create_app(db, TOKEN, outbound)) as api:
                assert api.post("/trigger", json=PAYLOAD).status_code == 401
                assert api.post("/trigger", json=PAYLOAD, headers={"Authorization": "Bearer wrong"}).status_code == 401
                invalid = api.post("/trigger", json={**PAYLOAD, "ground_truth": "hidden"}, headers=AUTH)
                assert invalid.status_code == 422 and "hidden" not in invalid.text
                original = api.post("/trigger", json=PAYLOAD, headers=AUTH).json()
                assert original["analysis_status"] == "INSUFFICIENT_EVIDENCE"
                assert original["notification_status"] == "SUPPRESSED" and original["review_required"]
                assert original["context_calls"] == original["llm_calls"] == 1
                assert api.post("/trigger", json={**PAYLOAD, "trace_id": "c" * 32}, headers=AUTH).status_code == 409
            with TestClient(create_app(db, TOKEN, outbound)) as api:
                replay = api.post("/trigger", json=PAYLOAD, headers=AUTH).json()
                assert replay == {**original, "replayed": True}
                assert api.get("/incidents/" + original["incident_id"], headers=AUTH).status_code == 200
    assert calls == ["GET", "POST"]


@pytest.mark.parametrize(("phase", "status", "code", "expected"), [
    ("context", 404, "TRACE_NOT_FOUND", "CONTEXT_UNAVAILABLE"),
    ("llm", 503, "PROVIDER_NOT_CONFIGURED", "PROVIDER_UNAVAILABLE"),
    ("llm", 502, "INVALID_MODEL_OUTPUT", "VALIDATION_FAILED"),
    ("llm", 504, "PROVIDER_TIMEOUT", "TIMEOUT"),
])
def test_failure_classification_suppresses_notifications(tmp_path, phase, status, code, expected):
    def route(request):
        if phase == "llm" and request.method == "GET":
            return httpx.Response(200, json=context(SimpleNamespace(
                trace_id=TRACE, mode="cross_service", service_name=None)))
        return httpx.Response(status, json={"error": {"code": code}})

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        with TestClient(create_app(tmp_path / "incidents.db", TOKEN, client)) as api:
            result = api.post("/trigger", json=PAYLOAD, headers=AUTH).json()
            assert result["analysis_status"] == expected
            assert result["notification_status"] == "SUPPRESSED" and result["report"] is None


def test_openai_configuration_is_rejected_before_execution_by_scope_header():
    class Other(MockProvider):
        name = "openai"

        def generate(self, _):
            pytest.fail("Provider scope guard must precede generation")

    with TestClient(llm_app(SimpleNamespace(fetch=context), Other())) as llm:
        response = llm.post("/analyze/trace", json={"trace_id": TRACE}, headers={"X-Required-Provider": "mock"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "PROVIDER_SCOPE_MISMATCH"


def test_pending_claim_and_local_notification_cooldown(tmp_path):
    ledger = Ledger(tmp_path / "incidents.db")
    signature = "same-trace-scope"
    state, identity = ledger.claim("first", signature)
    assert state == "new"
    assert ledger.claim("first", signature) == ("pending", identity)
    report = {"observations": [], "suspected_root_cause": None, "evidence_event_ids": [],
              "limitations": ["Fixture"], "recommended_checks": ["Inspect"]}
    first = {"analysis_status": "COMPLETED", "scope_signature": signature,
             "incident_id": identity, "report": report}
    ledger.finish("first", first)
    _, second_id = ledger.claim("second", signature)
    second = {"analysis_status": "COMPLETED", "scope_signature": signature,
              "incident_id": second_id, "report": report}
    ledger.finish("second", second)
    assert ledger.read(identity)["notification_status"] == "LOCAL_STORED"
    assert ledger.read(second_id)["notification_status"] == "SUPPRESSED"
