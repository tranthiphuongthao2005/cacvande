import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.context_api import create_app as context_app
from app.context_integration import Settings as ContextSettings, Worker as ContextWorker
from app.context_integration_client import ContextClient
from app.context_integration_models import digest
from app.context_integration_store import ContextPackageStore
from app.context_store import ContextStore
from app.detection_api import create_app as hybrid_app
from app.mock_analysis_api import create_app as analysis_app
from app.monitoring_client import DetectionClient, ElasticsearchPoller, iso
from app.monitoring_config import Settings as MonitorSettings
from app.monitoring_store import MonitoringStore
from app.monitoring_worker import Worker as Monitor
from app.workflow_config import Settings, WEBHOOK_PATH
from app.workflow_dispatcher import Client, Dispatcher
from app.workflow_models import simulate
from app.workflow_store import Store
from test_monitoring_store import NOW, query
from test_rule_detection import TRACE, cascade, completion, dependency
from test_workflow_dispatcher import TOKEN

ROOT = Path(__file__).resolve().parents[1]


def test_export_uses_known_nodes_fixed_destination_and_distinct_routes():
    directory = ROOT / "workflows"
    original = json.loads((directory / "scenario-incident.json").read_text())
    new = json.loads((directory / "detection-incident.json").read_text())
    assert original["nodes"][0]["parameters"]["path"] == "scenario-incident"
    assert original["nodes"][1]["parameters"]["url"] == "http://incident-adapter:8000/trigger"
    assert new["active"] is False and new["nodes"][0]["parameters"]["path"] == WEBHOOK_PATH.split("/")[-1]
    approved = {node["type"]: node["typeVersion"] for node in original["nodes"]}
    nodes = {node["name"]: node for node in new["nodes"]}
    assert all(approved[node["type"]] == node["typeVersion"] for node in nodes.values())
    for start, outputs in new["connections"].items():
        assert start in nodes
        assert all(link["node"] in nodes for branch in outputs["main"] for link in branch)
    outgoing = new["nodes"][1]
    assert outgoing["parameters"]["url"] == "http://mock-analysis:8000/analyze/package"
    assert outgoing["retryOnFail"] is False and outgoing["onError"] == "continueErrorOutput"
    assert outgoing["parameters"]["options"]["redirect"]["redirect"]["followRedirects"] is False
    assert "credentials" not in json.dumps(new) and "MOCK_ANALYSIS_TRANSPORT_FAILURE" in json.dumps(new)
    assert len(new["connections"][outgoing["name"]]["main"]) == 2


@pytest.mark.parametrize("scenario", [
    "normal", "503", "cascade", "recovered", "missing", "invalid_hash", "n8n_unavailable",
    "mock_unavailable", "invalid_evidence", "restart", "late", "timeout", "ack_lost",
])
def test_pipeline_through_mock_n8n_boundary(scenario, tmp_path):
    async def exercise():
        now = NOW
        path = str(tmp_path / "monitor.sqlite")
        config = MonitorSettings(enabled=True, es_url="http://fixture-es", es_api_key="fixture",
                                 detection_url="http://fixture-hybrid", storage_path=path, quiet_period_seconds=0)
        context_config = ContextSettings(enabled=True, url="http://fixture-context", storage_path=path)
        workflow = Settings(n8n_url="http://workflow-n8n:5678", webhook_token=TOKEN, storage_path=path,
                            timeout_seconds=.2)
        monitor_store = MonitoringStore(config)
        monitor_store.open(now)
        packages = ContextPackageStore(context_config)
        packages.install()
        store = Store(workflow)
        store.install()
        rows = [completion(status=503)]
        if scenario == "normal":
            rows = [completion()]
        elif scenario == "recovered":
            rows = [dependency(1, code="dependency_timeout"), completion()]
        elif scenario == "cascade":
            rows = cascade()
        rows = [{**row, "@timestamp": iso(NOW + .2 + index * .1)} for index, row in enumerate(rows)]
        context_rows = [dict(rows[0], event_id="c" * 32)] if scenario == "missing" else list(rows)
        http_calls, analyses = [], []

        def es(rows, request):
            assert request.url.host == "fixture-es"
            if request.method == "DELETE":
                return httpx.Response(200, json={})
            if request.url.path.endswith("/_pit"):
                return httpx.Response(200, json={"id": "fixture"})
            return httpx.Response(200, json={"hits": {"hits": [{"_source": row,
                "sort": [row["@timestamp"], row["event_id"], index]} for index, row in enumerate(rows)]}})

        async def analyze(envelope):
            doc = packages.read_package(envelope.context_package_id)
            assert doc.context_payload_sha256 == envelope.context_payload_sha256
            assert doc.context_payload == envelope.context_payload
            analyses.append(envelope)
            result = simulate(envelope)
            if scenario == "mock_unavailable":
                raise RuntimeError("fixture only")
            if scenario == "invalid_evidence":
                return result.model_copy(update={
                    "observations": [result.observations[0].model_copy(update={"event_id": "e" * 32})],
                })
            return result

        with (httpx.Client(base_url="http://fixture-es", transport=httpx.MockTransport(lambda r: es(rows, r))) as he,
              httpx.Client(base_url="http://fixture-es", transport=httpx.MockTransport(lambda r: es(context_rows, r))) as ce):
            hybrid = hybrid_app(rule_store=ContextStore(he))
            context = context_app(store=ContextStore(ce))
            mock = analysis_app(workflow, analyze=analyze, clock=lambda: now)
            async with (
                hybrid.router.lifespan_context(hybrid), context.router.lifespan_context(context),
                httpx.AsyncClient(base_url="http://fixture-es", transport=httpx.MockTransport(lambda r: es(rows, r))) as pe,
                httpx.AsyncClient(base_url="http://fixture-hybrid", transport=httpx.ASGITransport(app=hybrid)) as hd,
                httpx.AsyncClient(base_url="http://fixture-context", transport=httpx.ASGITransport(app=context)) as cc,
                httpx.AsyncClient(base_url="http://mock-analysis:8000", transport=httpx.ASGITransport(app=mock)) as ma,
            ):
                export = json.loads((ROOT / "workflows/detection-incident.json").read_text())
                target = export["nodes"][1]["parameters"]["url"]

                async def n8n(request):
                    assert request.url.path == WEBHOOK_PATH and request.url.host == "workflow-n8n"
                    http_calls.append(json.loads(request.content))
                    if scenario == "n8n_unavailable":
                        raise httpx.ConnectError("fixture")
                    if scenario == "timeout":
                        raise httpx.ReadTimeout("fixture")
                    headers = {"Authorization": request.headers["Authorization"], "X-Workflow-Execution-Id": "123"}
                    result = await ma.post(target, headers=headers, content=request.content)
                    if scenario in {"503", "late"}:
                        assert (await ma.post(target, headers=headers, content=request.content)).json() == result.json()
                    if scenario == "ack_lost":
                        raise httpx.ReadTimeout("fixture result committed before lost acknowledgement")
                    return result

                async with httpx.AsyncClient(base_url=workflow.n8n_url, transport=httpx.MockTransport(n8n)) as nh:
                    monitor = Monitor(config, monitor_store, ElasticsearchPoller(pe, config),
                                      DetectionClient(hd, 10), clock=lambda: now)
                    cw = ContextWorker(context_config, packages, ContextClient(cc, context_config), clock=lambda: now)
                    now += 2
                    await monitor.poll_once()
                    await monitor.dispatch()
                    await cw.tick()
                    if scenario == "invalid_hash":
                        with store.connect(write=True) as db:
                            db.execute("UPDATE context_packages SET document=json_set("
                                       "document,'$.context_payload_sha256',?)", ("f" * 64,))
                    if scenario == "restart":
                        assert len(store.claims(now)) == 1
                        now += 32
                        store = Store(workflow)
                        store.install()
                    dispatcher = Dispatcher(workflow, store, packages, Client(nh, workflow), clock=lambda: now)
                    await dispatcher.tick()
                    if scenario == "n8n_unavailable":
                        for offset in (10, 20):
                            now += offset
                            await dispatcher.tick()
                    if scenario == "late":
                        late = {**completion(8), "@timestamp": iso(NOW + 1)}
                        rows.append(late)
                        context_rows.append(late)
                        now += 1
                        await monitor.poll_once()
                        await monitor.dispatch()
                        await cw.tick()
                        await dispatcher.tick()
                    now += 60
                    await dispatcher.tick()

        statuses = {
            "normal": [], "recovered": [], "missing": [], "invalid_hash": ["NEEDS_REVIEW"],
            "n8n_unavailable": ["DISPATCH_FAILED"], "mock_unavailable": ["ANALYSIS_FAILED"],
            "invalid_evidence": ["NEEDS_REVIEW"], "timeout": ["OUTCOME_UNKNOWN"],
            "late": ["COMPLETED", "COMPLETED"],
        }.get(scenario, ["COMPLETED"])
        assert [row[0] for row in query(monitor_store, "SELECT state FROM workflow_jobs ORDER BY trace_version")] == statuses
        if scenario == "n8n_unavailable":
            assert len(http_calls) == 3 and len({item["idempotency_key"] for item in http_calls}) == 1
        elif not statuses or scenario == "invalid_hash":
            assert not http_calls
        else:
            assert len(http_calls) == (2 if scenario == "late" else 1)
        with store.connect() as db:
            history = db.execute("SELECT * FROM workflow_incident_handoff ORDER BY trace_version").fetchall()
        assert len(history) == statuses.count("COMPLETED")
        for row in history:
            output = json.loads(row["document"])
            assert digest(output) == row["response_sha256"]
            assert output["is_mock"] is True and "root_cause" not in output
            assert output["trace_id"] == TRACE
        if scenario == "cascade":
            assert len(json.loads(history[0]["evidence_event_ids"])) >= 2
        if scenario == "late":
            assert [row["superseded"] for row in history] == [1, 0]
            assert history[0]["incident_correlation_key"] == history[1]["incident_correlation_key"]
            assert history[0]["job_id"] != history[1]["job_id"]

    asyncio.run(exercise())


@pytest.fixture(autouse=True)
def disallow_live_http(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("offline integration only")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fail)
