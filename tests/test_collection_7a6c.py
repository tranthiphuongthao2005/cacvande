from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import collection_gate_7a6b as gates
from tools import smoke_producer_accounting as collector
from tools.collect_benchmark_7a6c import dry_run
from tools.consolidate_7a4 import pairing
from tools.fault_adapters_7a6c import ADAPTERS, await_timeout_trace, verify_observed, verify_timeouts
from tools.validate_7a5d import ROOT, read


def test_supported_adapters_and_dry_run():
    assert set(ADAPTERS) == {"normal-a", "processing-a", "timeout-a", "database-a", "cascade-a"}
    for adapter in ADAPTERS.values():
        assert gates.SCOPES[adapter.campaign][0] == adapter.configuration
        result = dry_run(adapter)
        assert result["cohort"] == "DEVELOPMENT_ACCEPTANCE" and not result["blind_eligible"]
        assert result["actual_business_posts"] == result["retries"] == 0


@pytest.mark.parametrize("config,batch,status", [
    ("timeout-a", "02", 504), ("database-a", "03", 503), ("cascade-a", "01", 502),
])
def test_adapter_contract_on_historical_evidence(config, batch, status):
    directory = ROOT / "experiments" / ("benchmark_7a4_batch" + batch)
    activation = read(directory / "activation.json")
    assert activation["http_status"] == status
    detail = read(directory / "telemetry.json")
    verify_observed(ADAPTERS[config], detail)
    manifest = read(directory / "snapshot_manifest.json")
    trace = detail["docker_events"][0]["trace_id"]
    single, cross = pairing(directory, trace, manifest.get("snapshots", manifest))
    assert single.completeness_status != "COMPLETE" and cross.completeness_status != "COMPLETE"
    if config == "timeout-a":
        verify_timeouts(activation["runtime"])
        with pytest.raises(ValueError):
            verify_timeouts({**activation["runtime"], "order": [None, None, None, "1.0"]})


def test_timeout_capture_waits_for_late_closed_product_span():
    order = {"event": "request_completed", "service": "order", "status": 504,
             "timestamp": "2026-11-24T00:00:02+00:00"}
    late = {**order, "service": "product", "status": 200, "timestamp": "2026-11-24T00:00:02.250+00:00"}
    span = {"kind": "SpanKind.SERVER", "end_time": late["timestamp"],
            "resource": {"attributes": {"service.name": "product"}}}
    fetch = Mock(side_effect=[[order], [order, late], [order, late, span]])
    time = [0]
    def wait(seconds):
        time[0] += seconds
    assert await_timeout_trace(fetch, 2, clock=lambda: time[0], wait=wait) == [order, late, span]
    assert fetch.call_count == 3
    with pytest.raises(TimeoutError):
        await_timeout_trace(lambda _: [order], 1, clock=lambda: time[0], wait=wait)


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_activation_failure_attempts_rollback_and_retains_failed_stop_marker(tmp_path, monkeypatch, rollback_fails):
    monkeypatch.setattr(gates, "PLAN", tmp_path)
    monkeypatch.setattr(collector, "ROOT", tmp_path)
    monkeypatch.setattr(collector, "read", lambda _: [
        {"scenario_id": "timeout", "expected_behavior": {"request_service": "order"}}])
    (tmp_path / ".env.context").write_text("CONTEXT_ES_API_KEY=fixture")
    api = Mock()
    api.get.return_value.raise_for_status.return_value.json.return_value = [
        {"user_id": "fixture", "product_id": "fixture", "quantity": 1}]
    client_cm = Mock()
    client_cm.__enter__ = Mock(return_value=api)
    client_cm.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(collector.httpx, "Client", lambda **_: client_cm)
    calls = []
    def compose(command, **kwargs):
        calls.append(command)
        if len(calls) == 1 or rollback_fails:
            raise RuntimeError("fixture")
        return SimpleNamespace()
    monkeypatch.setattr(collector.subprocess, "run", compose)
    output = tmp_path / "run"
    campaign = ADAPTERS["timeout-a"].campaign
    permit = SimpleNamespace(campaign=campaign, output=output, check=Mock())
    pilot = SimpleNamespace(campaign=campaign, cleanup_deadline=lambda t: t + 30)
    with pytest.raises(RuntimeError, match="fixture"):
        collector.run(output, scenario="timeout", postflight=lambda _: {"status": "PASS"},
                      pilot=pilot, post_gate=permit)
    assert len(calls) == 2 and "compose.timeout-a.yaml" in calls[0] and "compose.timeout-a.yaml" not in calls[1]
    api.post.assert_not_called()
    marker = tmp_path / "collection_runtime_lock"
    assert marker.exists() == rollback_fails
    if rollback_fails:
        with pytest.raises(gates.CollectionBlocked):
            gates.RuntimeLease(tmp_path / "next").acquire()
