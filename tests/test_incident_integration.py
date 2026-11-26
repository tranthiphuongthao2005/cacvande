import asyncio
import json

import httpx
import pytest

from app.context_api import create_app as context_app
from app.context_integration import Settings as ContextSettings, Worker as ContextWorker
from app.context_integration_client import ContextClient, ContextFailure
from app.context_integration_store import ContextPackageStore
from app.context_store import ContextStore
from app.detection_api import create_app as hybrid_app
from app.incident_api import create_app as incident_app
from app.incident_config import Settings as IncidentSettings
from app.incident_handoff import Source, Worker as IncidentWorker
from app.incident_store import IncidentStore
from app.mock_analysis_api import create_app as mock_app
from app.monitoring_client import DetectionClient, ElasticsearchPoller, iso
from app.monitoring_config import Settings as MonitoringSettings
from app.monitoring_store import MonitoringStore
from app.monitoring_worker import Worker as Monitor
from app.workflow_config import Settings as WorkflowSettings, WEBHOOK_PATH
from app.workflow_dispatcher import Client, Dispatcher
from app.workflow_models import simulate
from app.workflow_store import Store
from test_incident_management import AUTH, OPERATOR
from test_monitoring_store import NOW
from test_rule_detection import TRACE, cascade, completion, dependency
from test_workflow_dispatcher import TOKEN


@pytest.mark.parametrize("scenario", ["normal", "503", "cascade", "recovered", "analysis_failed", "missing_evidence",
                                     "context_failed", "bad_hash", "invalid_evidence", "late", "late_old_result"])
def test_pipeline_to_incident_rest_api(scenario, tmp_path):
    async def exercise():
        now = NOW
        db = str(tmp_path / "monitoring.sqlite")
        monitor_settings = MonitoringSettings(enabled=True, es_url="http://fixture-es", es_api_key="fixture",
                                              detection_url="http://fixture-hybrid", storage_path=db,
                                              quiet_period_seconds=0)
        monitoring = MonitoringStore(monitor_settings)
        monitoring.open(now)
        context_settings = ContextSettings(enabled=True, url="http://fixture-context", storage_path=db,
                                           namespace="isolated-stage96")
        packages = ContextPackageStore(context_settings)
        packages.install()
        workflow_settings = WorkflowSettings(n8n_url="http://workflow-n8n:5678", webhook_token=TOKEN, storage_path=db)
        workflows = Store(workflow_settings)
        workflows.install()
        incident_settings = IncidentSettings(management_enabled=True, handoff_enabled=True,
                                             storage_path=str(tmp_path / "incidents.sqlite"), source_storage_path=db,
                                             api_token=OPERATOR, batch_size=2)
        source = Source(incident_settings)
        source.install()
        incidents = IncidentStore(incident_settings.storage_path)
        incidents.install()
        worker = IncidentWorker(incident_settings, source, incidents, clock=lambda: now)

        def transfer():
            while worker.tick():
                pass

        rows = cascade() if scenario == "cascade" else [completion(status=503)]
        if scenario == "normal":
            rows = [completion()]
        if scenario == "recovered":
            rows = [dependency(1, code="dependency_timeout"), completion()]
        rows = [{**row, "@timestamp": iso(now + .1 + i * .1)} for i, row in enumerate(rows)]
        context_rows = [dict(rows[0], event_id="b" * 32)] if scenario == "missing_evidence" else list(rows)

        def transport(events):
            def elastic(request):
                assert request.url.host == "fixture-es"
                if request.method == "DELETE":
                    return httpx.Response(200, json={})
                if request.url.path.endswith("/_pit"):
                    return httpx.Response(200, json={"id": "fixture"})
                return httpx.Response(200, json={"hits": {"hits": [
                    {"_source": row, "sort": [row["@timestamp"], row["event_id"], i]}
                    for i, row in enumerate(events)
                ]}})
            return httpx.MockTransport(elastic)

        analysis_started = asyncio.Event()
        release_analysis = asyncio.Event()

        async def analyze(envelope):
            response = simulate(envelope)
            if scenario == "late_old_result" and len(envelope.context_payload.events) == 1:
                analysis_started.set()
                await release_analysis.wait()
            if scenario == "analysis_failed":
                raise RuntimeError("fixture")
            if scenario == "invalid_evidence":
                response.observations[0].event_id = "f" * 32
            return response

        with (httpx.Client(base_url="http://fixture-es", transport=transport(rows)) as he,
              httpx.Client(base_url="http://fixture-es", transport=transport(context_rows)) as ce):
            hybrid = hybrid_app(rule_store=ContextStore(he))
            retrieval = context_app(store=ContextStore(ce))
            mock = mock_app(workflow_settings, analyze=analyze, clock=lambda: now)
            api = incident_app(incident_settings.model_copy(update={"handoff_enabled": False}), clock=lambda: now + 10)
            async with (hybrid.router.lifespan_context(hybrid), retrieval.router.lifespan_context(retrieval),
                        api.router.lifespan_context(api),
                        httpx.AsyncClient(base_url="http://fixture-es", transport=transport(rows)) as poll,
                        httpx.AsyncClient(base_url="http://fixture-hybrid", transport=httpx.ASGITransport(app=hybrid)) as hd,
                        httpx.AsyncClient(base_url="http://fixture-context",
                                          transport=httpx.ASGITransport(app=retrieval)) as cc,
                        httpx.AsyncClient(base_url="http://mock-analysis:8000",
                                          transport=httpx.ASGITransport(app=mock)) as ma,
                        httpx.AsyncClient(base_url="http://fixture-incident",
                                          transport=httpx.ASGITransport(app=api)) as ir):
                async def webhook(request):
                    assert request.url.path == WEBHOOK_PATH
                    return await ma.post("/analyze/package", content=request.content, headers={
                        "Authorization": request.headers["Authorization"], "X-Workflow-Execution-Id": "42",
                    })

                async with httpx.AsyncClient(base_url=workflow_settings.n8n_url,
                                             transport=httpx.MockTransport(webhook)) as n8n:
                    monitor = Monitor(monitor_settings, monitoring, ElasticsearchPoller(poll, monitor_settings),
                                      DetectionClient(hd, 10), clock=lambda: now)
                    class Unavailable:
                        async def retrieve(self, _):
                            raise ContextFailure("CONTEXT_HTTP_404")
                    context_worker = ContextWorker(
                        context_settings, packages, Unavailable() if scenario == "context_failed" else (
                            ContextClient(cc, context_settings)
                        ), clock=lambda: now,
                    )
                    dispatcher = Dispatcher(workflow_settings, workflows, packages, Client(n8n, workflow_settings),
                                            clock=lambda: now)

                    async def revision():
                        await monitor.poll_once()
                        await monitor.dispatch()
                        transfer()

                    now += 2
                    await revision()
                    listing = (await ir.get("/incidents", headers=AUTH)).json()
                    if scenario in {"normal", "recovered"}:
                        assert listing["total"] == 0
                        await context_worker.tick()
                        assert not await dispatcher.tick()
                        return
                    early, = listing["items"]
                    identity = early["incident_id"]
                    assert early["analysis_status"] == "PENDING" and early["incident_status"] == "OPEN"
                    await context_worker.tick()
                    if scenario == "late_old_result":
                        in_progress = asyncio.create_task(dispatcher.tick())
                        await asyncio.wait_for(analysis_started.wait(), 2)
                    else:
                        await dispatcher.tick()

                    if scenario == "bad_hash":
                        with source.connect() as db_source:
                            db_source.execute("UPDATE incident_outbox SET workflow=json_set(workflow,"
                                              "'$.response_sha256',?) WHERE source_state='COMPLETED'", ("f" * 64,))
                    transfer()
                    if scenario in {"late", "late_old_result"}:
                        rows.append({**completion(8), "@timestamp": iso(NOW + .8)})
                        context_rows.append(rows[-1])
                        now += 1
                        await revision()
                        await context_worker.tick()
                        await dispatcher.tick()
                        transfer()
                        if scenario == "late_old_result":
                            release_analysis.set()
                            await in_progress
                            transfer()

                    view = (await ir.get(f"/incidents/{identity}", headers=AUTH)).json()
                    body = (await ir.get(f"/incidents/{identity}/revisions", headers=AUTH)).json()
                    states = {"analysis_failed": "ANALYSIS_FAILED", "invalid_evidence": "NEEDS_REVIEW",
                              "missing_evidence": "NEEDS_REVIEW", "context_failed": "ANALYSIS_FAILED",
                              "bad_hash": "NEEDS_REVIEW"}
                    assert view["analysis_status"] == states.get(scenario, "ANALYZED")
                    assert view["incident_status"] == "OPEN" and view["proposed_root_cause"] is None
                    assert view["root_cause_verification_status"] in {"NOT_ANALYZED", "NOT_PROPOSED", "NEEDS_REVIEW"}
                    assert view["incident_correlation_key"] == early["incident_correlation_key"]
                    if scenario != "context_failed":
                        assert view["latest_context_package_id"] is not None
                    expected_versions = 2 if scenario in {"late", "late_old_result"} else 1
                    current_version = early["current_trace_version"] + expected_versions - 1
                    assert view["current_trace_version"] == current_version
                    assert sum(item["kind"] == "DETECTION" for item in body["items"]) == expected_versions
                    evidence = (await ir.get(f"/incidents/{identity}/evidence", headers=AUTH)).json()["items"]
                    assert any(item["role"] == "DETECTION" for item in evidence)
                    if view["analysis_status"] == "ANALYZED":
                        assert view["is_mock"] is True and view["context_completeness"] == "PARTIAL"
                        assert any(item["role"] == "ANALYSIS" for item in evidence)
                        assert view["latest_analysis_job_id"] == [
                            item["source_id"] for item in body["items"]
                            if item["kind"] == "ANALYSIS" and item["trace_version"] == current_version
                        ][-1]
                    stats = (await ir.get("/incidents/statistics", headers=AUTH)).json()
                    assert stats["total_incidents"] == 1 and stats["detection_revision_count"] == expected_versions
                    assert stats["mock_count"] == int(view["analysis_status"] == "ANALYZED") and stats["real_count"] == 0
                    if scenario == "bad_hash":
                        assert stats["metrics"]["artifact_validation_failures"] == 1
                        assert stats["metrics"]["hash_validation_failures"] == 1
                    timeline = (await ir.get(f"/incidents/{identity}/timeline", headers=AUTH)).json()["items"]
                    times = [item["occurred_at"] for item in timeline]
                    assert times == sorted(times)
                    assert "INCIDENT_RESOLVED" not in {item["event"] for item in timeline}

    asyncio.run(exercise())


@pytest.fixture(autouse=True)
def forbid_real_http(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Only ASGI and HTTP mock transports are allowed")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
