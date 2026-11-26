import json

import httpx
from fastapi.testclient import TestClient

from app.context_api import create_app
from app.context_store import ContextStore, Snapshot
from app.incident_context import TraceProof, build_context

TRACE = "a" * 32
STAMP = "2026-11-22T17:00:00.123456Z"


def event(i, service="order", message="request_completed", **extra):
    return {"event_id": f"{i:032x}", "trace_id": TRACE, "@timestamp": STAMP,
            "service_name": service, "span_id": "b" * 16, "level": "INFO",
            "message": message, "status_code": 200, **extra}


def test_single_scope_is_pushed_down_and_pit_closed():
    calls = []

    def handler(request):
        payload = json.loads(request.content) if request.content else {}
        calls.append((request.method, payload))
        if request.method == "DELETE":
            return httpx.Response(200, json={"succeeded": True})
        if request.url.path.endswith("_pit"):
            return httpx.Response(200, json={"id": "open"})
        filters = payload["query"]["bool"]["filter"]
        assert {"term": {"trace_id": TRACE}} in filters
        assert {"term": {"service_name": "user"}} in filters
        assert "app" not in payload["_source"]
        return httpx.Response(200, json={"pit_id": "updated", "hits": {
            "hits": [{"_source": event(1, "user")}]}})

    with httpx.Client(base_url="http://es", transport=httpx.MockTransport(handler)) as client:
        output = ContextStore(client).snapshot(TRACE, "user")
    assert output.rows[0]["service_name"] == "user"
    assert calls[-1] == ("DELETE", {"id": "updated"})


def test_duplicate_conflict_ties_and_invalid_fields():
    first, second, third = [event(i) for i in (1, 2, 3)]
    invalid = {k: v for k, v in event(4).items() if k != "service_name"}
    other = event(5, span_id=None, error_type="injected_fault_type=secret")
    data = build_context(TRACE, "cross_service", None, Snapshot(
        [third, third, first, second, {**second, "status_code": 503}, invalid, other]))
    assert data.evidence_event_ids == [first["event_id"], third["event_id"], other["event_id"]]
    assert data.data_quality["conflicting_event_ids"] == 1
    assert data.data_quality["duplicate_documents"] == 2
    assert data.data_quality["timestamp_ties"] == 2
    assert {"MISSING_SPAN_ID", "MISSING_SERVICE_NAME", "UNRECOGNIZED_ERROR_TYPE"} <= set(data.retrieval_warnings)
    assert "secret" not in data.model_dump_json()
    assert data.completeness_status == "PARTIAL"


def test_cross_service_timeline_preserves_only_linked_evidence():
    rows = [event(1, "user"), event(2, "product", status_code=503),
            event(3, message="dependency_attempt_failed", dependency_service="product", status_code=502),
            event(4, endpoint="/orders", http_method="POST", status_code=502, expected_root_cause="secret")]
    ctx = build_context(TRACE, "cross_service", None, Snapshot(rows))
    assert {e.service_name for e in ctx.events} == {"user", "product", "order"}
    assert [line["status_code"] for line in ctx.timeline] == [200, 503, 502, 502]
    assert [(e["source_service"], e["target_service"]) for e in ctx.dependencies] == [("order", "product")]
    assert ctx.dependencies[0]["evidence_event_ids"] == [rows[2]["event_id"]]
    assert ctx.completeness_status == "PARTIAL"
    assert "secret" not in ctx.model_dump_json()


def test_complete_requires_trusted_closed_manifest():
    row = event(1, "user")
    expected = frozenset({row["event_id"]})
    proof = TraceProof(row["event_id"], expected, frozenset(), True)
    assert build_context(TRACE, "cross_service", None, Snapshot([row])).completeness_status == "UNKNOWN"
    assert build_context(TRACE, "cross_service", None, Snapshot([row]), proof).completeness_status == "COMPLETE"
    assert build_context(TRACE, "cross_service", None, Snapshot([row], truncated=True), proof).completeness_status == "PARTIAL"
    assert build_context(TRACE, "single_service", "user", Snapshot([row]), proof).completeness_status == "UNKNOWN"


def test_polling_opens_a_new_snapshot_and_records_change(monkeypatch):
    store = ContextStore(None)
    values = iter([Snapshot(), Snapshot([event(1)])])
    monkeypatch.setattr(store, "snapshot", lambda *args: next(values))
    times = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr("app.context_store.monotonic", lambda: next(times))
    monkeypatch.setattr("app.context_store.sleep", lambda _: None)
    result = store.fetch(TRACE, wait_ms=500)
    assert result.polls == 2 and result.late_documents


def test_context_http_contract_and_timeout():
    class Store:
        def ready(self):
            return None

        def fetch(self, trace_id, service, *, wait_ms):
            if trace_id == "f" * 32:
                raise httpx.ReadTimeout("trace timed out")
            if trace_id == "e" * 32:
                return Snapshot()
            return Snapshot([event(1, "user")])

    with TestClient(create_app(Store())) as client:
        path = f"/context/trace/{TRACE}"
        assert client.get("/health").status_code == client.get("/ready").status_code == 200
        assert client.get(path, params={"mode": "single_service"}).status_code == 422
        assert client.get(path, params={"service_name": "user"}).status_code == 422
        assert client.get(path, params={"wait_ms": 3001}).status_code == 422
        assert client.get(path, params={"mode": "single_service", "service_name": "user"}).json()["services"] == ["user"]
        assert client.get(f"/context/trace/{'f' * 32}").status_code == 504
        assert client.get(f"/context/trace/{'e' * 32}").status_code == 404
