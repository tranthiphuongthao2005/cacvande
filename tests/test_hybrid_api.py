import json
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient

from app.context_store import ContextStore
from app.detection_api import create_app
from test_rule_detection import TRACE, completion


@pytest.fixture(autouse=True)
def disallow_live_http(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Hybrid API integration must use an in-process or mocked HTTP transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fail)


@pytest.mark.parametrize("mode", [None, "AUTO", "RULE_BASED"])
def test_hybrid_pit_isolation_and_evidence(monkeypatch, mode):
    monkeypatch.setattr("app.context_store.PAGE", 1)
    calls = []
    row = completion(status=503)
    raw = {**row, "ground_truth": True, "activation": "never used"}

    def elastic(request):
        assert request.url.host == "fixture-es"
        calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            assert json.loads(request.content) == {"id": "updated"}
            return httpx.Response(200, json={})
        if request.url.path.endswith("/_pit"):
            return httpx.Response(200, json={"id": "initial"})
        query = json.loads(request.content)
        assert {"term": {"trace_id": TRACE}} in query["query"]["bool"]["filter"]
        assert {"ground_truth", "activation", "app"}.isdisjoint(query["_source"])
        if "search_after" not in query:
            return httpx.Response(200, json={"pit_id": "updated", "hits": {"hits": [{"sort": [1], "_source": raw}]}})
        assert query["pit"]["id"] == "updated" and query["search_after"] == [1]
        return httpx.Response(200, json={"hits": {"hits": []}})

    with httpx.Client(base_url="http://fixture-es", transport=httpx.MockTransport(elastic)) as es:
        with TestClient(create_app(rule_store=ContextStore(es))) as client:
            payload = {"trace_id": TRACE}
            if mode:
                payload["mode"] = mode
            response = client.post("/detect/hybrid", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["requested_mode"] == (mode or "AUTO") and data["executed_mode"] == "RULE_BASED"
    assert data["detection_source"] == "rule_based" and data["detection_status"] == "ANOMALY"
    assert data["fallback_used"] is (mode != "RULE_BASED")
    assert data["fallback_reason"] == (None if mode == "RULE_BASED" else "DOMAIN_NOT_VALIDATED")
    assert data["model_score"] is None and data["evidence_event_ids"] == [row["event_id"]]
    assert data["matched_rules"][0]["evidence_event_ids"] == data["evidence_event_ids"]
    assert calls == [("POST", "/thesis-logs-*/_pit"), ("POST", "/_search"), ("POST", "/_search"), ("DELETE", "/_pit")]


@pytest.mark.parametrize(("failure", "status", "code"), [
    ("unavailable", 503, "TRACE_STORE_UNAVAILABLE"),
    ("timeout", 504, "ELASTICSEARCH_TIMEOUT"),
    ("invalid", 502, "INVALID_SEARCH_RESPONSE"),
    ("partial", 504, "INCOMPLETE_SEARCH"),
])
def test_backend_errors_remain_errors(failure, status, code, caplog):
    calls = []

    def elastic(request):
        calls.append(request.method)
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        if request.url.path.endswith("/_pit"):
            return httpx.Response(200, json={"id": "initial"})
        if failure == "unavailable":
            return httpx.Response(503, json={"detail": "secret"})
        if failure == "timeout":
            raise httpx.ReadTimeout("secret", request=request)
        if failure == "invalid":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"timed_out": True, "hits": {"hits": []}})

    caplog.set_level("INFO", logger="uvicorn.error")
    with httpx.Client(base_url="http://fixture-es", transport=httpx.MockTransport(elastic)) as es:
        with TestClient(create_app(rule_store=ContextStore(es))) as client:
            response = client.post("/detect/hybrid", json={"trace_id": TRACE})
    body = response.json()
    assert response.status_code == status and body["error"]["code"] == code
    assert body["detection_status"] == "DETECTION_ERROR" and body["is_anomaly"] is None
    assert body["executed_mode"] is None and body["model_score"] is None
    assert calls[-1] == "DELETE"
    assert "secret" not in response.text and "secret" not in caplog.text


def test_contract_validation_capabilities_and_legacy(monkeypatch):
    monkeypatch.delenv("DETECTION_ES_API_KEY", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "alive"}
        assert client.get("/ready").status_code == 503
        assert client.get("/ready").json()["error"]["code"] == "NOT_READY_FOR_SCORING"
        for payload in ({"trace_id": TRACE, "mode": "hybrid"}, {"trace_id": "0" * 32},
                        {"trace_id": "invalid"}, {"trace_id": TRACE, "ground_truth": True}):
            assert client.post("/detect/hybrid", json=payload).status_code == 422
        paths = client.get("/openapi.json").json()["paths"]
        assert {"200", "422", "500", "502", "503", "504"} <= paths["/detect/hybrid"]["post"]["responses"].keys()
        assert {"/detect/trace", "/detect/session", "/detect/rule-based", "/detect/capabilities"} <= paths.keys()
        capabilities = client.get("/detect/capabilities").json()
        assert not capabilities["rule_based_available"] and not capabilities["auto_available"]
        assert not capabilities["mecolog_available"]
        assert capabilities["mecolog_block_reason"] == "DOMAIN_NOT_VALIDATED"
        assert capabilities["supported_modes"] == ["AUTO", "RULE_BASED", "MECOLOG_ONLY"]
        assert client.post("/detect/trace", json={"trace_id": TRACE}).json()["error"]["code"] == "TRACE_STORE_NOT_CONFIGURED"


def test_model_only_no_query_and_capabilities_even_with_legacy_runtime():
    class Never:
        def snapshot(self, _):
            pytest.fail("MECOLOG_ONLY must not fetch a blocked model snapshot")

        def detect(self, _):
            pytest.fail("Hybrid must not call the legacy scorer")

    with TestClient(create_app(approved_runtime=Never(), rule_store=Never())) as client:
        response = client.post("/detect/hybrid", json={"trace_id": TRACE, "mode": "MECOLOG_ONLY"})
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "NOT_READY_FOR_SCORING"
        assert not body["fallback_used"] and body["model_score"] is None
        assert body["executed_mode"] is None
        caps = client.get("/detect/capabilities").json()
        assert caps["rule_based_available"] and caps["auto_available"] and not caps["mecolog_available"]
        assert client.get("/ready").json()["status"] == "ready_for_scoring"


def test_request_deadline_returns_early_and_worker_cleans_up_pit(monkeypatch):
    monkeypatch.setattr("app.detection_api.HYBRID_TIMEOUT_SECONDS", .3)
    release, cleaned = Event(), Event()

    def elastic(request):
        if request.method == "DELETE":
            cleaned.set()
            return httpx.Response(200, json={})
        if request.url.path.endswith("/_pit"):
            return httpx.Response(200, json={"id": "initial"})
        assert release.wait(4)
        return httpx.Response(200, json={"hits": {"hits": []}})

    with httpx.Client(base_url="http://fixture-es", transport=httpx.MockTransport(elastic)) as es:
        with TestClient(create_app(rule_store=ContextStore(es))) as client:
            try:
                response = client.post("/detect/hybrid", json={"trace_id": TRACE})
                assert response.status_code == 504
                assert response.json()["error"]["code"] == "DETECTION_TIMEOUT"
                assert not cleaned.is_set()
            finally:
                release.set()
            assert cleaned.wait(4)
