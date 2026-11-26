"""Independent Stage 9.1 telemetry fixtures and offline API integration tests."""

import json
from time import perf_counter

import httpx
import pytest
from fastapi.testclient import TestClient

from app.context_store import ContextStore, Snapshot
from app.detection_api import create_app
from app.rule_detection import detect

TRACE = "a" * 32
REQUEST = "b" * 16


def event(number, message="request_completed", **fields):
    return {
        "event_id": f"{number:032x}", "trace_id": TRACE,
        "@timestamp": f"2026-11-22T17:00:{number:02d}Z", "request_id": REQUEST,
        "service_name": "order", "message": message, "level": "INFO",
        **fields,
    }


def completion(number=5, status=201, **fields):
    return event(number, status_code=status, endpoint="/orders", http_method="POST", **fields)


def dependency(number, message="dependency_attempt_failed", code="dependency_unavailable"):
    return event(number, message, error_type=code, dependency_service="product",
                 status_code=504 if code == "dependency_timeout" else 502,
                 level="WARNING" if message == "dependency_attempt_failed" else "ERROR")


def cascade():
    return [
        event(1, service_name="product", request_id="c" * 16, status_code=503,
              http_method="GET", endpoint="/products/{key}", level="ERROR"),
        dependency(2), dependency(3, "dependency_exhausted"), completion(status=502),
    ]


def decisions(rows, **flags):
    return detect(TRACE, Snapshot(rows, **flags), perf_counter())


@pytest.mark.parametrize(("rows", "expected"), [
    ([completion()], []),
    ([completion(status=500)], ["R01"]),
    ([completion(status=503)], ["R01"]),
    ([completion(status=422)], []),
    ([dependency(2, code="dependency_timeout"), completion()], ["R02"]),
    ([event(1, "database_connection_failed"), completion(status=503)], ["R01", "R03"]),
    ([event(1, "order_processing_failed"), completion(status=500)], ["R01", "R04"]),
    ([event(1, "request_failed", error_type="internal_error")], ["R04"]),
    ([dependency(1), completion()], []),
    ([dependency(3, "dependency_exhausted")], ["R05", "R06"]),
    ([dependency(3, "dependency_exhausted", "dependency_timeout")], ["R02", "R06"]),
    (cascade(), ["R01", "R05", "R06", "R07"]),
    ([cascade()[0], cascade()[-1]], ["R01"]),
    ([*cascade()[:-1], {**cascade()[-1], "request_id": "d" * 16}], ["R01", "R05", "R06"]),
    ([event(1, "request_failed", level="CRITICAL")], ["R08"]),
    ([event(1, "database_connection_failed", level="ERROR"),
      event(2, "request_failed", level="ERROR")], ["R03", "R08"]),
    ([{**completion(status=503), "service_name": "product"}, completion(6, 502),
      dependency(3, "dependency_exhausted"), dependency(2)], ["R01", "R05", "R06"]),
])
def test_rules(rows, expected):
    output = decisions(rows)
    assert [match.rule_id for match in output.matched_rules] == expected
    assert output.is_anomaly is bool(expected)
    assert output.detection_status == ("ANOMALY" if expected else "NO_ANOMALY_DETECTED")
    assert output.model_score is None
    assert set(output.evidence_event_ids) <= {row["event_id"] for row in rows}
    assert all(match.evidence_event_ids for match in output.matched_rules)
    assert set(output.evidence_event_ids) == {
        event_id for match in output.matched_rules for event_id in match.evidence_event_ids
    }


@pytest.mark.parametrize(("rows", "flags", "diagnostic"), [
    ([], {}, "MISSING_OUTCOME_EVIDENCE"),
    ([{}], {}, "INVALID_EVENT"),
    (["corrupted log"], {}, "INVALID_EVENT"),
    ([event(1)], {}, "MISSING_OUTCOME_EVIDENCE"),
    ([dependency(2)], {}, "MISSING_OUTCOME_EVIDENCE"),
    ([completion()], {"truncated": True}, "SNAPSHOT_TRUNCATED"),
    ([completion(), completion(status=500)], {}, "CONFLICTING_EVENT_ID"),
    ([completion(), {**completion(), "status_code": "500"}], {}, "INVALID_EVENT"),
    ([{**completion(status=500), "event_id": "0" * 32}], {}, "INVALID_EVENT"),
    ([{**completion(status=500), "trace_id": "d" * 32}], {}, "INVALID_EVENT"),
])
def test_insufficient_data(rows, flags, diagnostic):
    output = decisions(rows, **flags)
    assert output.detection_status == "INSUFFICIENT_DATA"
    assert output.is_anomaly is None and output.evidence_event_ids == []
    assert diagnostic in output.diagnostics


def test_cascade_evidence_order_duplicates_and_determinism():
    rows = cascade()
    ignored = {"detection_id", "detection_timestamp", "latency_ms"}
    baseline = decisions(rows)
    shuffled = decisions([rows[3], rows[1], rows[0], rows[2], rows[0]])
    assert baseline.model_dump(exclude=ignored) == shuffled.model_dump(exclude=ignored)
    cascade_match = next(match for match in baseline.matched_rules if match.rule_id == "R07")
    assert cascade_match.evidence_event_ids == [row["event_id"] for row in rows]
    assert baseline.affected_services == ["order", "product"]
    assert baseline.context_completeness == "partial"


def test_positive_evidence_survives_truncation_and_excludes_conflicting_ids():
    output = decisions([completion(1, 500), completion(1, 201), completion(2, 503)], truncated=True)
    assert output.is_anomaly is True
    assert output.evidence_event_ids == [completion(2)["event_id"]]
    assert output.diagnostics == ["SNAPSHOT_TRUNCATED", "CONFLICTING_EVENT_ID"]


def test_cascade_correlates_final_attempt_and_requires_unambiguous_snapshot():
    rows = cascade()
    first_failure = rows[0]
    second_failure = {**first_failure, **{key: event(3)[key] for key in ("event_id", "@timestamp")}}
    retry = dependency(4)
    exhausted = dependency(5, "dependency_exhausted")
    rows = [first_failure, rows[1], second_failure, retry, exhausted, completion(6, 502)]
    match = next(match for match in decisions(rows).matched_rules if match.rule_id == "R07")
    assert match.evidence_event_ids == [row["event_id"] for row in rows[2:]]
    assert "R07" not in {match.rule_id for match in decisions(rows, truncated=True).matched_rules}


def test_ground_truth_and_activation_fields_have_no_effect():
    row = {**completion(), "ground_truth": {"is_anomaly": True},
           "scenario": "database_connection_failed", "activation": "dependency_exhausted",
           "app": {"code": "dependency_timeout"}}
    ignored = {"detection_id", "detection_timestamp", "latency_ms"}
    assert decisions([row]).model_dump(exclude=ignored) == decisions([completion()]).model_dump(exclude=ignored)


@pytest.mark.parametrize(("mode", "status", "decision"), [
    ("normal", 200, "NO_ANOMALY_DETECTED"),
    ("anomaly", 200, "ANOMALY"),
    ("empty", 200, "INSUFFICIENT_DATA"),
    ("unavailable", 503, "DETECTION_ERROR"),
    ("timeout", 504, "DETECTION_ERROR"),
    ("partial_search", 504, "DETECTION_ERROR"),
    ("malformed_response", 502, "DETECTION_ERROR"),
])
def test_api_through_elasticsearch_transport(mode, status, decision, caplog):
    calls = []

    def elastic(request):
        calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(200, json={"succeeded": True})
        if request.url.path.endswith("/_pit"):
            if mode == "unavailable":
                return httpx.Response(503, json={})
            if mode == "timeout":
                raise httpx.ReadTimeout("fixture error", request=request)
            return httpx.Response(200, json={"id": "snapshot"})
        payload = json.loads(request.content)
        assert {"term": {"trace_id": TRACE}} in payload["query"]["bool"]["filter"]
        assert {"error_type", "dependency_service", "request_id"} <= set(payload["_source"])
        assert {"ground_truth", "activation", "app"}.isdisjoint(payload["_source"])
        if mode == "malformed_response":
            return httpx.Response(200, json={})
        rows = [] if mode == "empty" else [completion(status=500 if mode == "anomaly" else 201)]
        return httpx.Response(200, json={"timed_out": mode == "partial_search",
                                        "hits": {"hits": [{"_source": row} for row in rows]}})

    caplog.set_level("INFO", logger="uvicorn.error")
    with httpx.Client(base_url="http://es", transport=httpx.MockTransport(elastic)) as es:
        with TestClient(create_app(rule_store=ContextStore(es))) as client:
            response = client.post("/detect/rule-based", json={"trace_id": TRACE})
    assert response.status_code == status
    body = response.json()
    assert body["detection_status"] == decision and body["model_score"] is None
    assert body["detection_source"] == "rule_based"
    assert body["trace_id"] == TRACE and body["latency_ms"] >= 0
    if status != 200:
        assert body["is_anomaly"] is None and body["diagnostics"]
    if mode == "anomaly":
        assert body["matched_rules"][0]["evidence_event_ids"] == [completion()["event_id"]]
    if mode not in {"unavailable", "timeout"}:
        assert calls[-1] == ("DELETE", "/_pit")
    log = next(json.loads(r.message) for r in caplog.records if r.name == "uvicorn.error")
    assert log["detection_id"] == body["detection_id"]
    assert "fixture error" not in caplog.text


def test_validation_openapi_unconfigured_and_mecolog_guard(monkeypatch):
    monkeypatch.delenv("DETECTION_ES_API_KEY", raising=False)
    with TestClient(create_app(rule_store=ContextStore(None))) as client:
        for payload in ({}, {"trace_id": "0" * 32}, {"trace_id": TRACE, "ground_truth": True}):
            assert client.post("/detect/rule-based", json=payload).status_code == 422
        assert client.get("/ready").json()["error"]["code"] == "NOT_READY_FOR_SCORING"
        route = client.get("/openapi.json").json()["paths"]["/detect/rule-based"]["post"]
        assert {"200", "422", "502", "503", "504"} <= route["responses"].keys()
    with TestClient(create_app()) as client:
        body = client.post("/detect/rule-based", json={"trace_id": TRACE}).json()
        assert body["diagnostics"] == ["TRACE_STORE_NOT_CONFIGURED"]


def test_default_app_wires_existing_elasticsearch_client(monkeypatch):
    monkeypatch.setenv("DETECTION_ES_API_KEY", "fixture-only")
    real_client = httpx.Client

    def transport(request):
        assert request.url.path == "/thesis-logs-*/_pit"
        return httpx.Response(404, json={})

    monkeypatch.setattr("app.detection_api.httpx.Client", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(transport)
    ))
    with TestClient(create_app()) as client:
        assert client.post("/detect/rule-based", json={"trace_id": TRACE}).json()[
            "detection_status"] == "INSUFFICIENT_DATA"
        assert client.get("/ready").json()["error"]["code"] == "NOT_READY_FOR_SCORING"


def test_api_reads_multiple_pit_pages(monkeypatch):
    monkeypatch.setattr("app.context_store.PAGE", 1)
    rows = [completion(1, 500), completion(2, 503)]
    cursor = iter([None, [1], [2]])

    def elastic(request):
        if request.method == "DELETE":
            assert json.loads(request.content) == {"id": "last"}
            return httpx.Response(200, json={"succeeded": True})
        if request.url.path.endswith("/_pit"):
            return httpx.Response(200, json={"id": "first"})
        payload = json.loads(request.content)
        expected = next(cursor)
        assert payload.get("search_after") == expected
        offset = expected[0] if expected else 0
        hits = [{"_source": row, "sort": [offset + 1]} for row in rows[offset:offset + 1]]
        return httpx.Response(200, json={"pit_id": "last", "hits": {"hits": hits}})

    with httpx.Client(base_url="http://es", transport=httpx.MockTransport(elastic)) as es:
        with TestClient(create_app(rule_store=ContextStore(es))) as client:
            body = client.post("/detect/rule-based", json={"trace_id": TRACE}).json()
    assert body["evidence_event_ids"] == [row["event_id"] for row in rows]
