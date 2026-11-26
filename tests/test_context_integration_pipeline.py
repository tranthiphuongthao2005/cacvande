import asyncio
import json

import httpx
import pytest

from app.context_api import create_app as context_app
from app.context_integration import Settings, Worker
from app.context_integration_client import ContextClient, ContextFailure
from app.context_integration_store import ContextPackageStore
from app.context_store import ContextStore
from app.detection_api import create_app as detection_app
from app.monitoring_client import DetectionClient, ElasticsearchPoller, iso
from app.monitoring_config import Settings as MonitoringSettings
from app.monitoring_store import MonitoringStore
from app.monitoring_worker import Worker as Monitor
from test_monitoring_store import NOW, query
from test_rule_detection import TRACE, completion, dependency


@pytest.mark.parametrize("scenario", ["normal", "503", "recovered", "missing", "late", "unavailable", "restart",
                                     "forbidden", "conflict"])
def test_elasticsearch_monitoring_hybrid_context_sqlite(scenario, tmp_path):
    async def exercise():
        now = NOW
        path = str(tmp_path / "monitoring.sqlite")
        monitor_settings = MonitoringSettings(
            enabled=True, es_url="http://fixture-es", es_api_key="test", detection_url="http://fixture-hybrid",
            storage_path=path, quiet_period_seconds=0,
        )
        settings = Settings(enabled=True, url="http://fixture-context", storage_path=path)
        monitor_store = MonitoringStore(monitor_settings)
        monitor_store.open(now)
        packages = ContextPackageStore(settings)
        packages.install()
        monitor_store.open(now)
        historical = {**completion(8), "@timestamp": iso(NOW - 1)}
        success = {**completion(), "@timestamp": iso(NOW + 1)}
        anomaly = {**success, "status_code": 503, "level": "ERROR"}
        timeout = {**dependency(1, code="dependency_timeout"), "@timestamp": iso(NOW + .5)}
        recent = [success] if scenario == "normal" else [timeout, success] if scenario == "recovered" else [anomaly]
        monitoring_rows = [historical, *recent]
        detection_rows = list(recent)
        context_rows = [dict(anomaly, status_code=502)] if scenario == "conflict" else (
            [{**completion(6), "@timestamp": iso(NOW + 1)}] if scenario == "missing" else list(recent)
        )
        requests = []

        def elastic(rows, request):
            assert request.url.host == "fixture-es"
            if request.method == "DELETE":
                return httpx.Response(200, json={})
            if request.url.path.endswith("/_pit"):
                return httpx.Response(200, json={"id": "fixture"})
            if rows is monitoring_rows:
                time_range = json.loads(request.content)["query"]["range"]["@timestamp"]
                rows = [row for row in rows if time_range["gte"] <= row["@timestamp"] < time_range["lt"]]
            return httpx.Response(200, json={"hits": {"hits": [{"_source": row, "sort": [
                row["@timestamp"], row["event_id"], i
            ]} for i, row in enumerate(rows)]}})

        es = lambda rows: httpx.MockTransport(lambda request: elastic(rows, request))
        with (httpx.Client(base_url="http://fixture-es", transport=es(detection_rows)) as detection_es,
              httpx.Client(base_url="http://fixture-es", transport=es(context_rows)) as context_es):
            detection = detection_app(rule_store=ContextStore(detection_es))
            context = context_app(store=ContextStore(context_es))

            @context.middleware("http")
            async def observe(request, call_next):
                requests.append((request.url.path, dict(request.query_params)))
                if scenario == "unavailable":
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"error": {"code": "TRACE_STORE_UNAVAILABLE"}}, status_code=503)
                response = await call_next(request)
                if scenario == "forbidden":
                    from fastapi.responses import JSONResponse
                    body = b"".join([part async for part in response.body_iterator])
                    payload = json.loads(body)
                    payload["data_quality"]["ground_truth"] = 1
                    return JSONResponse(payload)
                return response

            async with (detection.router.lifespan_context(detection), context.router.lifespan_context(context),
                        httpx.AsyncClient(base_url="http://fixture-es", transport=es(monitoring_rows)) as poll,
                        httpx.AsyncClient(base_url="http://fixture-hybrid",
                                          transport=httpx.ASGITransport(app=detection)) as hybrid,
                        httpx.AsyncClient(base_url="http://fixture-context",
                                          transport=httpx.ASGITransport(app=context)) as context_http):
                monitor = Monitor(monitor_settings, monitor_store, ElasticsearchPoller(poll, monitor_settings),
                                  DetectionClient(hybrid, 10), clock=lambda: now)
                now += 2
                assert await monitor.poll_once()
                await monitor.dispatch()
                assert query(monitor_store, "SELECT count(*) FROM results") == [(1,)]
                if scenario == "restart":
                    pending, = packages.claims(now)
                    assert pending.attempt == 1
                    packages = ContextPackageStore(settings)
                    packages.install()
                    now += 42
                    assert packages.claims(now) == []
                    now += 10
                worker = Worker(settings, packages, ContextClient(context_http, settings), clock=lambda: now)
                await worker.tick()
                if scenario == "unavailable":
                    for delay in (10, 20):
                        now += delay
                        await worker.tick()
                if scenario == "late":
                    late = {**completion(6), "@timestamp": iso(NOW + .75)}
                    for rows in (monitoring_rows, detection_rows, context_rows):
                        rows.append(late)
                    now += 1
                    assert await monitor.poll_once()
                    await monitor.dispatch()
                    await worker.tick()
                    await worker.tick()

        outcomes = {
            "normal": ["SKIPPED_NOT_ELIGIBLE"], "recovered": ["SKIPPED_NOT_ELIGIBLE"],
            "503": ["READY_FOR_ANALYSIS"], "missing": ["NEEDS_MORE_EVIDENCE"],
            "late": ["SUPERSEDED", "READY_FOR_ANALYSIS"], "unavailable": ["CONTEXT_FAILED"],
            "restart": ["READY_FOR_ANALYSIS"], "forbidden": ["CONTEXT_FAILED"], "conflict": ["NEEDS_REVIEW"],
        }
        assert [state for (state,) in query(monitor_store, "SELECT state FROM context_jobs ORDER BY trace_version")] == (
            outcomes[scenario]
        )
        if scenario == "normal":
            assert query(monitor_store, "SELECT count(*) FROM detection_events") == [(0,)]
        else:
            assert query(monitor_store, "SELECT count(*) FROM detection_events") == [(2 if scenario == "late" else 1,)]
        expected_requests = {"normal": 0, "recovered": 0, "late": 2, "unavailable": 3}.get(scenario, 1)
        assert requests == [(f"/context/trace/{TRACE}", {"mode": "cross_service", "wait_ms": "0"})] * expected_requests
        all_packages = [packages.read_package(key) for (key,) in
                        query(monitor_store, "SELECT package_id FROM context_packages ORDER BY trace_version")]
        if scenario in {"normal", "recovered", "unavailable", "forbidden"}:
            assert not all_packages
        else:
            assert all_packages[0].detection_evidence_ids == [anomaly["event_id"]]
            assert all_packages[0].context_completeness == "PARTIAL"
        if scenario == "late":
            first, second = all_packages
            assert first.trace_version == 1 and second.trace_version == 2
            assert second.supersedes_package_id == first.context_package_id
            assert second.incident_correlation_key == first.incident_correlation_key
            assert second.additional_context_event_ids == [late["event_id"]]
        if scenario == "conflict":
            assert all_packages[0].conflicting_evidence_ids == [anomaly["event_id"]]
        if scenario == "missing":
            assert all_packages[0].missing_evidence_ids == [anomaly["event_id"]]

    asyncio.run(exercise())


@pytest.fixture(autouse=True)
def prohibit_real_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Only ASGI or mocked HTTP can be used")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
