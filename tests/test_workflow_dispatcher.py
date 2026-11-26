import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.context_integration import Settings as ContextSettings
from app.context_integration_store import ContextPackageStore
from app.mock_analysis_api import create_app
from app.monitoring_config import Settings as MonitorSettings
from app.monitoring_store import MonitoringStore
from app.workflow_config import Settings, WEBHOOK_PATH
from app.workflow_dispatcher import Client, Dispatcher
from app.workflow_models import simulate
from app.workflow_store import Store
from test_context_integration import detection
from test_context_integration_store import insert, package
from test_monitoring_store import NOW

TOKEN = "isolated-fixture-token-123456"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def setup(tmp_path):
    path = str(tmp_path / "monitoring.sqlite")
    MonitoringStore(MonitorSettings(storage_path=path)).open(NOW)
    context = ContextPackageStore(ContextSettings(storage_path=path))
    context.install()
    settings = Settings(storage_path=path, n8n_url="http://workflow-n8n:5678", webhook_token=TOKEN,
                        max_concurrency=1, timeout_seconds=.1)
    store = Store(settings)
    store.install()
    return settings, context, store


def seed(context, version=1, readiness=None):
    event = detection(version=version)
    insert(context, event)
    claim, = context.claims(NOW)
    doc = package(event, claim)
    if readiness:
        doc = doc.model_copy(update={"analysis_readiness": readiness})
    context.finish(claim, NOW, package=doc)
    return doc


def state(store):
    with store.connect() as db:
        return db.execute("SELECT state FROM workflow_jobs ORDER BY trace_version").fetchall()


def start(setup):
    settings, context, store = setup
    doc = seed(context)
    claim, = store.claims(NOW)
    return doc, claim, store.before_dispatch(claim, context.read_ready(doc.context_package_id), NOW)


@pytest.mark.parametrize("readiness", ["NEEDS_MORE_EVIDENCE", "NEEDS_REVIEW"])
def test_only_ready_enters_outbox(setup, readiness):
    _, context, store = setup
    seed(context, readiness=readiness)
    assert store.claims(NOW) == []


@pytest.mark.parametrize("damaged", ["hash", "trace", "version", "missing", "superseded", "forbidden"])
def test_package_changes_before_dispatch_are_blocked(setup, damaged):
    _, context, store = setup
    doc = seed(context)
    claim, = store.claims(NOW)
    previous = context.read_ready(doc.context_package_id)
    with store.connect(write=True) as db:
        if damaged == "superseded":
            db.execute("UPDATE context_jobs SET state='SUPERSEDED'")
        elif damaged == "missing":
            db.execute("DELETE FROM context_packages")
        else:
            path, value = {
                "hash": ("$.context_payload_sha256", "f" * 64),
                "trace": ("$.trace_id", "b" * 32),
                "version": ("$.trace_version", 2),
                "forbidden": ("$.context_payload.data_quality.ground_truth", 1),
            }[damaged]
            db.execute("UPDATE context_packages SET document=json_set(document,?,?)", (path, value))
    assert store.before_dispatch(claim, previous, NOW) is None
    assert state(store)[0][0] in {"NEEDS_REVIEW", "SUPERSEDED"}


def test_no_backfill_and_concurrent_claim_restart(tmp_path, setup):
    settings, context, store = setup
    with store.connect(write=True) as db:
        db.execute("DROP TRIGGER enqueue_workflow_package")
        for name in ("workflow_attempts", "workflow_results", "workflow_jobs", "workflow_status"):
            db.execute("DROP TABLE " + name)
        db.execute("DROP VIEW workflow_incident_handoff")
    seed(context)
    store.install()
    assert store.claims(NOW) == []
    seed(context, version=2)
    with ThreadPoolExecutor(2) as pool:
        result = sum(pool.map(store.claims, [NOW, NOW]), [])
    assert len(result) == 1
    restarted = Store(settings)
    assert restarted.claims(NOW + 1) == []
    recovered, = restarted.claims(NOW + 31)
    assert recovered.package_id == result[0].package_id and recovered.token != result[0].token


def test_accepted_and_ambiguous_dispatch_never_replays(setup):
    _, _, store = setup
    _, claim, _ = start(setup)
    assert store.dispatch_outcome(claim, NOW, "WORKFLOW_ACCEPTED", "WEBHOOK_HTTP_202", 3) == "WORKFLOW_ACCEPTED"
    assert store.claims(NOW + 60) == []
    assert state(store)[0][0] == "OUTCOME_UNKNOWN"


def test_crash_after_marking_dispatch_is_unknown(setup):
    settings, _, store = setup
    start(setup)
    assert Store(settings).claims(NOW + 60) == []
    assert state(store)[0][0] == "OUTCOME_UNKNOWN"


def test_backoff_only_for_definite_connection_failure(setup):
    _, context, store = setup
    doc, claim, envelope = start(setup)
    now = NOW
    for wait in (10, 20, 0):
        outcome = store.dispatch_outcome(claim, now, "DISPATCH_FAILED", "WEBHOOK_CONNECTION_FAILED", 1,
                                         safe_retry=True)
        if wait:
            assert outcome == "RETRY_PENDING" and store.claims(now + wait - 1) == []
            now += wait
            claim, = store.claims(now)
            assert store.before_dispatch(claim, context.read_ready(doc.context_package_id), now) == envelope
    assert state(store)[0][0] == "DISPATCH_FAILED"


@pytest.mark.parametrize(("response", "expected", "retry"), [
    ("timeout", "OUTCOME_UNKNOWN", False), ("connect", "DISPATCH_FAILED", True),
    ("503", "OUTCOME_UNKNOWN", False), ("401", "DISPATCH_FAILED", False),
    ("202", "WORKFLOW_ACCEPTED", False), ("200", "OUTCOME_UNKNOWN", False),
])
def test_client_classifies_delivery(setup, response, expected, retry):
    settings, _, _ = setup
    _, _, envelope = start(setup)
    async def exercise():
        async def webhook(request):
            assert request.url.path == WEBHOOK_PATH and request.headers["Authorization"] == HEADERS["Authorization"]
            if response == "timeout":
                raise httpx.ReadTimeout("sensitive")
            if response == "connect":
                raise httpx.ConnectError("sensitive")
            return httpx.Response(int(response), json=simulate(envelope).model_dump(mode="json"))
        async with httpx.AsyncClient(base_url=settings.n8n_url, transport=httpx.MockTransport(webhook)) as http:
            outcome = await Client(http, settings).dispatch(envelope)
        assert outcome.state == expected and outcome.safe_retry == retry and "sensitive" not in outcome.code
    asyncio.run(exercise())


@pytest.mark.parametrize(("case", "expected"), [
    ("no_auth", 401), ("wrong_auth", 401), ("normal", 200), ("forbidden", 422),
    ("oversize", 413), ("conflict", 409), ("bad_hash", 422), ("unavailable", 503),
    ("timeout", 504), ("bad_response", 422), ("bad_evidence", 422), ("bad_content", 422),
    ("abstain", 200),
])
def test_mock_api_auth_lineage_validation_and_replay(setup, case, expected):
    settings, _, store = setup
    _, _, envelope = start(setup)
    if case == "oversize":
        settings = settings.model_copy(update={"max_payload_bytes": 1024})
    calls = []

    async def analysis(request):
        calls.append(request)
        result = simulate(request)
        if case == "unavailable":
            raise RuntimeError("sensitive")
        if case == "timeout":
            await asyncio.Event().wait()
        if case == "bad_response":
            return {"unexpected": 1}
        if case in {"bad_evidence", "bad_content"}:
            field = {"event_id": "b" * 32} if case == "bad_evidence" else {"status_code": 501}
            return result.model_copy(update={"observations": [result.observations[0].model_copy(update=field)]})
        if case == "abstain":
            return result.model_copy(update={"analysis_status": "INSUFFICIENT_EVIDENCE", "observations": []})
        return result

    payload = envelope.model_dump(mode="json")
    if case == "forbidden":
        payload["context_payload"]["data_quality"]["ground_truth"] = 1
    if case == "conflict":
        payload["trace_version"] += 1
    if case == "bad_hash":
        payload["context_payload_sha256"] = "f" * 64
    headers = {} if case == "no_auth" else {"Authorization": "Bearer wrong"} if case == "wrong_auth" else HEADERS
    with TestClient(create_app(settings, analyze=analysis, clock=lambda: NOW)) as http:
        reply = http.post("/analyze/package", headers=headers, json=payload)
        assert reply.status_code == expected and "sensitive" not in reply.text
        assert reply.json()["analysis_provider"] == "mock" and reply.json()["is_mock"] is True
        if expected == 200:
            replay = http.post("/analyze/package", headers=headers, json=payload)
            assert replay.json() == reply.json() and len(calls) == 1
            result = reply.json()
            assert result["analysis_mode"] == "MOCK" and result["is_mock"] is True
            assert result["analysis_provider"] == "mock"
            assert result["evidence_validation_scope"] == "CONTEXT_ID_AND_OBSERVABLE_FIELDS"
            assert result["context_payload_sha256"] == envelope.context_payload_sha256
            assert result["analysis_status"] == ("INSUFFICIENT_EVIDENCE" if case == "abstain"
                                                 else "SIMULATED_OBSERVATIONS")
        if expected in {401, 409, 413} or case in {"forbidden", "bad_hash"}:
            assert calls == []
    if case in {"bad_response", "bad_evidence", "bad_content"}:
        assert state(store)[0][0] == "NEEDS_REVIEW"
    elif case in {"unavailable", "timeout"}:
        assert state(store)[0][0] == "ANALYSIS_FAILED"


def test_supersession_during_analysis_keeps_old_result(setup):
    settings, context, store = setup
    doc, _, envelope = start(setup)
    status, claim = store.accept(envelope, "123", NOW)
    assert status == 201
    successor = seed(context, version=2)
    store.finish_analysis(envelope, claim, NOW, 1, output=simulate(envelope))
    with store.connect() as db:
        row = db.execute("SELECT * FROM workflow_incident_handoff").fetchone()
        assert row["superseded"] == 1 and row["workflow_execution_id"] == "123"
        assert row["incident_correlation_key"] == doc.incident_correlation_key == successor.incident_correlation_key
    assert store.claims(NOW)[0].package_id == successor.context_package_id


def test_concurrent_webhook_and_late_delivery_reconcile_same_key(setup):
    settings, _, store = setup
    _, dispatcher_claim, envelope = start(setup)
    store.dispatch_outcome(dispatcher_claim, NOW, "OUTCOME_UNKNOWN", "WEBHOOK_TIMEOUT", 1)

    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def analysis(request):
            calls.append(request)
            started.set()
            await release.wait()
            return simulate(request)

        api = create_app(settings.model_copy(update={"timeout_seconds": 2}), analyze=analysis, clock=lambda: NOW)
        async with httpx.AsyncClient(base_url="http://mock-analysis:8000",
                                     transport=httpx.ASGITransport(app=api)) as http:
            async def post():
                return await http.post("/analyze/package", headers=HEADERS, json=envelope.model_dump(mode="json"))
            first = asyncio.create_task(post())
            await asyncio.wait_for(started.wait(), 1)
            try:
                assert (await post()).status_code == 202
            finally:
                release.set()
            assert (await first).status_code == 200
            assert len(calls) == 1

    asyncio.run(exercise())
    assert state(store)[0][0] == "COMPLETED"


def test_crash_after_analysis_before_persistence_keeps_unknown(setup):
    _, _, store = setup
    _, _, envelope = start(setup)
    status, claim = store.accept(envelope, None, NOW)
    assert status == 201
    with store.connect(write=True) as db:
        db.execute("CREATE TRIGGER fail_result BEFORE UPDATE ON workflow_jobs WHEN NEW.state='COMPLETED' "
                   "BEGIN SELECT RAISE(ABORT,'fixture crash'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.finish_analysis(envelope, claim, NOW, 1, output=simulate(envelope))
    assert store.claims(NOW + 60) == []
    assert store.accept(envelope, None, NOW + 60)[0] == 202
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM workflow_results").fetchone()[0] == 0


@pytest.mark.parametrize("config", [{"n8n_url": "https://api.openai.com"}, {"n8n_url": "http://localhost:5678"},
                                   {"external_allowed": True}, {"analysis_provider": "gemini"},
                                   {"dispatch_enabled": True}])
def test_external_and_shared_runtime_configuration_is_rejected(config):
    with pytest.raises(ValidationError):
        Settings(**config)


def test_disabled_never_reads_storage_and_no_auth_by_default():
    asyncio.run(Dispatcher(Settings(), None, None, None).run())
    with TestClient(create_app(Settings())) as client:
        assert client.post("/analyze/package", json={}).status_code == 503
