from app.context_store import Snapshot
import httpx
from app.incident_context import build_context
from experiments.run_scenario import SETUPS
from tools.collect_benchmark_7a1 import executed
from tools.collect_benchmark_7a4 import FAMILY, exclusion, rollback_readiness


def test_campaigns_share_mechanism_without_inventing_faults():
    assert set(FAMILY) == set(SETUPS)
    assert FAMILY["cascade"] == FAMILY["retry"] == FAMILY["unavailable"]
    assert SETUPS["retry"][2] == 3 and SETUPS["cascade"][2] == 1


def test_technical_gate_and_review_are_distinct():
    assert exclusion(True, False, True) == [
        "LABEL_PENDING_REVIEW", "HISTORICAL_SIGNATURE_OVERLAP", "NO_APPROVED_LOCKED_EVALUATION",
    ]
    assert "TECHNICAL_GATE_FAILED" in exclusion(False, True, False)
    assert exclusion(True, True, False) == ["NO_APPROVED_LOCKED_EVALUATION"]


def test_cascade_activation_requires_caller_event():
    trace = "b" * 32
    rows = [{"trace_id": trace, "event_id": f"{i:032x}", "message": "request_completed",
             "@timestamp": "2026-11-22T16:00:00Z", "service_name": service, "level": "INFO",
             "status_code": status} for i, (service, status) in enumerate(
                 [("user", 200), ("product", 503), ("order", 502)], start=1)]
    assert not executed("cascade", True, build_context(trace, "cross_service", None, Snapshot(rows)))
    rows.append({**rows[-1], "event_id": "d" * 32, "message": "dependency_attempt_failed",
                 "dependency_service": "product"})
    context = build_context(trace, "cross_service", None, Snapshot(rows))
    assert executed("cascade", True, context) and not executed("cascade", False, context)


def test_timeout_requires_product_caller_evidence():
    trace = "b" * 32
    completion = {"trace_id": trace, "event_id": "c" * 32, "message": "request_completed",
                  "@timestamp": "2026-11-22T16:00:00Z", "service_name": "order", "level": "INFO",
                  "status_code": 504}
    failure = {**completion, "event_id": "d" * 32, "message": "dependency_attempt_failed",
               "error_type": "dependency_timeout", "dependency_service": "product"}
    assert not executed("timeout", True, build_context(trace, "cross_service", None, Snapshot([completion])))
    assert executed("timeout", True, build_context(trace, "cross_service", None, Snapshot([completion, failure])))
    assert not executed("timeout", True, build_context(trace, "cross_service", None, Snapshot([
        completion, {**failure, "dependency_service": "user"}])))


def test_rollback_retries_only_readiness(monkeypatch):
    from tools import collect_benchmark_7a4

    monkeypatch.setattr(collect_benchmark_7a4, "sleep", lambda _: None)
    calls = []

    def route(request):
        calls.append((request.method, request.url.path))
        if len(calls) == 1:
            raise httpx.ConnectError("warming up")
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        assert rollback_readiness(client) == {"user": 200, "product": 200, "order": 200}
    assert calls == [("GET", "/ready")] * 6


def test_database_status_requires_repository_failure_event():
    trace = "b" * 32
    completion = {"trace_id": trace, "event_id": "c" * 32, "message": "request_completed",
                  "@timestamp": "2026-11-22T16:00:00Z", "service_name": "order", "level": "ERROR",
                  "status_code": 503}
    failure = {**completion, "event_id": "d" * 32, "message": "database_connection_failed",
               "error_type": "database_unavailable"}
    assert not executed("database", True, build_context(trace, "cross_service", None, Snapshot([completion])))
    assert executed("database", True, build_context(trace, "cross_service", None, Snapshot([completion, failure])))
    assert not executed("database", True, build_context(trace, "cross_service", None, Snapshot([
        completion, {**failure, "service_name": "product"}])))
