import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from app.context_store import Snapshot
from app.hybrid_detection import HybridRouter
from app.monitoring_client import DetectionClient, DetectionFailure, ElasticsearchPoller, PollFailure
from app.monitoring_config import Settings
from app.monitoring_store import MonitoringStore
from app.monitoring_worker import Worker
from test_monitoring_store import NOW, add, query
from test_rule_detection import TRACE, completion


@pytest.mark.parametrize(("mode", "expected"), [
    ("empty", None),
    ("es_unavailable", "ELASTICSEARCH_UNAVAILABLE"),
    ("es_timeout", "ELASTICSEARCH_TIMEOUT"),
    ("malformed", "INVALID_SEARCH_RESPONSE"),
    ("partial_search", "INCOMPLETE_SEARCH"),
    ("page_limit", "POLL_PAGE_LIMIT"),
])
def test_poll_outcomes_and_pit_cleanup(mode, expected):
    async def exercise():
        calls = []
        def handler(request):
            calls.append(request.method)
            if request.method == "DELETE":
                return httpx.Response(200, json={})
            if request.url.path.endswith("/_pit"):
                return httpx.Response(200, json={"id": "open"})
            if mode == "es_unavailable":
                return httpx.Response(503, json={})
            if mode == "es_timeout":
                raise httpx.ReadTimeout("sensitive")
            if mode == "malformed":
                return httpx.Response(200, json={"hits": {"hits": {}}})
            if mode == "partial_search":
                return httpx.Response(200, json={"timed_out": True})
            hits = [{"sort": ["timestamp", "id", 1], "_source": completion()}] if mode == "page_limit" else []
            return httpx.Response(200, json={"hits": {"hits": hits}})
        async with httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler)) as client:
            poller = ElasticsearchPoller(client, Settings(batch_size=1, max_pages=1))
            persist = Mock()
            if expected:
                with pytest.raises(PollFailure, match=expected):
                    await poller.poll(NOW, NOW + 1, persist, asyncio.Event())
            else:
                assert await poller.poll(NOW, NOW + 1, persist, asyncio.Event())
                persist.assert_called_once_with([])
            assert calls[-1] == "DELETE"
    asyncio.run(exercise())


@pytest.mark.parametrize(("mode", "code", "retryable", "cooldown"), [
    ("deadline", "DETECTION_TIMEOUT", True, True),
    ("transport", "DETECTION_TRANSPORT_ERROR", True, True),
    ("unavailable", "DETECTION_HTTP_503", True, False),
    ("gateway_timeout", "DETECTION_HTTP_504", True, True),
    ("malformed", "INVALID_DETECTION_RESPONSE", False, False),
    ("mismatch", "INVALID_DETECTION_RESPONSE", False, False),
    ("backend_result", "DETECTION_HTTP_503", True, False),
])
def test_detection_client_validates_and_classifies(mode, code, retryable, cooldown):
    async def exercise():
        async def handler(request):
            assert request.url.path == "/detect/hybrid"
            assert json.loads(request.content) == {"trace_id": TRACE, "mode": "AUTO"}
            if mode == "deadline":
                await asyncio.Event().wait()
            if mode == "transport":
                raise httpx.ConnectError("sensitive")
            if mode in {"unavailable", "gateway_timeout", "malformed"}:
                return httpx.Response({"unavailable": 503, "gateway_timeout": 504, "malformed": 200}[mode],
                                      json={})
            if mode == "backend_result":
                from app.hybrid_detection import SnapshotFailure

                def unavailable(_):
                    raise SnapshotFailure(503, "TRACE_STORE_UNAVAILABLE")
                status, output = HybridRouter().route(TRACE, "AUTO", unavailable)
            else:
                status, output = HybridRouter().route("b" * 32, "AUTO", lambda _: Snapshot([]))
            return httpx.Response(status, content=output.model_dump_json())
        async with httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(DetectionFailure, match=code) as caught:
                await DetectionClient(client, .05).detect(TRACE)
            assert (caught.value.retryable, caught.value.cooldown) == (retryable, cooldown)
            assert (caught.value.result is not None) is (mode == "backend_result")
    asyncio.run(exercise())


@pytest.mark.parametrize("dry", [False, True])
def test_disabled_and_dry_run_have_no_local_or_detection_side_effects(tmp_path, dry):
    async def exercise():
        settings = Settings(enabled=dry, dry_run=dry, es_url="http://mock" if dry else None,
                            es_api_key="fixture" if dry else None, storage_path=str(tmp_path / "worker.sqlite"))
        called = []
        async def poll(lower, upper, persist, stop):
            called.append((lower, upper))
            persist([{}])
            return True
        store = MonitoringStore(settings)
        await Worker(settings, store, SimpleNamespace(poll=poll), None, clock=lambda: NOW).run()
        assert called == ([(NOW - settings.overlap_seconds, NOW)] if dry else [])
        assert not list(tmp_path.iterdir())
    asyncio.run(exercise())


def test_graceful_shutdown_drains_inflight_and_stops_scheduling(tmp_path):
    async def exercise():
        settings = Settings(enabled=True, es_url="http://mock", es_api_key="test", detection_url="http://mock",
                            storage_path=str(tmp_path / "worker.sqlite"), quiet_period_seconds=0,
                            max_concurrent_traces=1)
        store = MonitoringStore(settings)
        store.open(NOW)
        add(store, completion(), {**completion(6), "trace_id": "e" * 32})
        called = []
        async def detect(trace_id):
            called.append(trace_id)
            worker.stopping.set()
            return HybridRouter().route(trace_id, "AUTO", lambda _: Snapshot([completion()]))[1]

        async def poll(lower, upper, persist, stop):
            persist([])
            return True

        worker = Worker(settings, store, SimpleNamespace(poll=poll), SimpleNamespace(detect=detect),
                        clock=lambda: NOW + 1)
        await worker.run()
        await worker.dispatch()
        assert len(called) == 1
        assert query(store, "SELECT count(*) FROM results") == [(1,)]
        state = store.read_status(NOW + 1)
        assert state["state"] == "STOPPED" and not state["ready"]
        assert state["in_flight"] == 0 and state["pending_traces"] == 1
    asyncio.run(exercise())


def test_poll_failure_after_page_persistence_keeps_watermark(tmp_path):
    async def exercise():
        settings = Settings(storage_path=str(tmp_path / "worker.sqlite"), batch_size=1)
        def handler(request):
            if request.method == "DELETE":
                return httpx.Response(200, json={})
            if request.url.path.endswith("/_pit"):
                return httpx.Response(200, json={"id": "open"})
            if "search_after" in json.loads(request.content):
                return httpx.Response(503, json={})
            return httpx.Response(200, json={"hits": {"hits": [
                {"sort": ["timestamp", "id", 1], "_source": completion()}
            ]}})
        store = MonitoringStore(settings)
        store.open(NOW)
        async with httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler)) as client:
            worker = Worker(settings, store, ElasticsearchPoller(client, settings), None, clock=lambda: NOW + 1)
            with pytest.raises(PollFailure):
                await worker.poll_once()
            assert query(store, "SELECT cursor FROM checkpoint") == [(float(NOW),)]
            assert query(store, "SELECT version FROM traces") == [(1,)]
    asyncio.run(exercise())


@pytest.mark.parametrize("settings", [
    {"enabled": True},
    {"enabled": True, "es_url": "http://mock", "es_api_key": "", "detection_url": "http://mock"},
    {"es_url": "http://name:secret@mock"},
    {"start_policy": "EXPLICIT_LOOKBACK"},
    {"quiet_period_seconds": 60},
    {"retention_seconds": 30},
    {"storage_path": ":memory:"},
])
def test_invalid_configuration_fails_closed(settings):
    with pytest.raises(ValidationError):
        Settings(**settings)


def test_detector_failure_degrades_status_without_claiming_readiness(tmp_path):
    store = MonitoringStore(Settings(storage_path=str(tmp_path / "worker.sqlite"),
                                     quiet_period_seconds=0))
    store.open(NOW)
    add(store, completion())
    store.mark("RUNNING", NOW)
    assert store.read_status(NOW)["ready"]
    claim, = store.claims(NOW)
    store.finish(claim, NOW + 1, failure=DetectionFailure("DETECTION_HTTP_503", retryable=True))
    status = store.read_status(NOW + 1)
    assert status["state"] == "DEGRADED" and not status["ready"]
    assert status["error_code"] == "DETECTION_BACKEND_DEGRADED"
