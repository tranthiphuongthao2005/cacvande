import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.context_integration import Settings as ContextSettings
from app.context_integration_store import ContextPackageStore
from app.incident_api import create_app
from app.incident_config import Settings
from app.incident_handoff import Source, Worker
from app.incident_models import StatusChange
from app.incident_store import IncidentStore
from app.monitoring_config import Settings as MonitorSettings
from app.monitoring_store import MonitoringStore
from app.scenario_incident_store import Ledger
from app.workflow_config import Settings as WorkflowSettings
from app.workflow_store import Store
from test_context_integration import detection
from test_context_integration_store import insert, package
from test_monitoring_store import NOW
from test_rule_detection import TRACE


OPERATOR = "isolated-operator-credential-123456"
READER = "isolated-reader-credential-1234567"
AUTH = {"Authorization": f"Bearer {OPERATOR}"}
READ = {"Authorization": f"Bearer {READER}"}


@pytest.fixture
def setup(tmp_path):
    db = str(tmp_path / "monitor.sqlite")
    Monitor = MonitoringStore(MonitorSettings(storage_path=db))
    Monitor.open(NOW)
    context = ContextPackageStore(ContextSettings(storage_path=db, namespace="fixture"))
    context.install()
    workflow = Store(WorkflowSettings(storage_path=db))
    workflow.install()
    settings = Settings(management_enabled=True, handoff_enabled=True, source_storage_path=db,
                        storage_path=str(tmp_path / "incidents.sqlite"), api_token=OPERATOR, read_token=READER,
                        operator_id="operator-a")
    source = Source(settings)
    source.install()
    store = IncidentStore(settings.storage_path)
    store.install()
    return context, workflow, settings, source, store


def managed(store):
    return store.list({}, 50, 0)[0]


def transfer(setup, now=NOW):
    _, _, settings, source, store = setup
    return Worker(settings, source, store, clock=lambda: now).tick()


@pytest.mark.parametrize(("status", "eligible", "expected"), [
    ("ANOMALY", "ELIGIBLE", 1), ("ANOMALY", "RECOVERED_SIGNAL", 0),
    ("ANOMALY", "NEEDS_MORE_EVIDENCE", 0), ("ANOMALY", "NOT_ELIGIBLE", 0),
    ("NO_ANOMALY_DETECTED", "NOT_ELIGIBLE", 0), ("INSUFFICIENT_DATA", "NEEDS_MORE_EVIDENCE", 0),
    ("DETECTION_ERROR", "NOT_ELIGIBLE", 0),
])
def test_early_detection_eligibility_before_context(setup, status, eligible, expected):
    context, _, _, _, store = setup
    event = detection().model_copy(update={"detection_status": status, "incident_eligibility": eligible,
                                           "is_anomaly": True if status == "ANOMALY" else None})
    insert(context, event)
    assert transfer(setup) == expected
    incidents = managed(store)
    assert len(incidents) == expected
    if incidents:
        assert incidents[0].incident_status == "OPEN" and incidents[0].analysis_status == "PENDING"
        assert incidents[0].proposed_root_cause is None and incidents[0].is_mock is None
        labels = {row["event"] for row in store.history(incidents[0].incident_id, "timeline", 30, 0)}
        assert labels == {"INCIDENT_CREATED", "ANOMALY_DETECTED", "DETECTION_PERSISTED"}


def test_no_historical_backfill_and_idempotent_migration(setup):
    context, _, _, source, store = setup
    with source.connect() as db:
        db.execute("DROP TRIGGER incident_enqueue_detection")
        db.execute("DROP TRIGGER incident_enqueue_context")
        db.execute("DROP TRIGGER incident_enqueue_workflow")
        db.execute("DROP TABLE incident_outbox")
        db.execute("DROP TABLE incident_outbox_source")
    insert(context, detection())
    source.install()
    source.install()
    store.install()
    assert transfer(setup) == 0
    insert(context, detection(version=2))
    assert transfer(setup) == 1 and len(managed(store)) == 1


def test_crash_before_and_after_persistence_replay_by_receipt(setup):
    context, _, settings, source, store = setup
    insert(context, detection())
    row = source.claim(NOW)
    assert row is not None and source.claim(NOW + 29) is None
    recovered = Source(settings).claim(NOW + 30)
    assert recovered["id"] == row["id"]
    store.ingest(recovered, NOW + 30)
    # The destination committed, but the worker did not acknowledge the source.
    assert transfer(setup, NOW + 61) == 1
    items = managed(IncidentStore(settings.storage_path))
    assert len(items) == 1
    assert store.statistics({})["metrics"]["duplicate_handoffs"] == 1
    assert store.statistics({})["detection_revision_count"] == 1


def test_status_conflicts_history_and_reopen(setup):
    context, _, _, _, store = setup
    insert(context, detection())
    transfer(setup)
    initial = managed(store)[0]
    identity = initial.incident_id
    assert store.change(identity, StatusChange(status="CLOSED", reason="Invalid transition", expected_version=1),
                        "operator-a", NOW)[0] == "INVALID_INCIDENT_TRANSITION"

    def advance(_):
        return store.change(identity, StatusChange(status="INVESTIGATING", reason="Started investigation",
                                                    expected_version=1), "operator-a", NOW + 1)[0]

    with ThreadPoolExecutor(2) as executor:
        assert set(executor.map(advance, range(2))) == {None, "INCIDENT_VERSION_CONFLICT"}
    _, resolved = store.change(identity, StatusChange(status="RESOLVED", reason="Verified request recovery",
                                                       expected_version=2), "operator-a", NOW + 2)
    _, reopened = store.change(identity, StatusChange(status="OPEN", reason="Operator requested reopen",
                                                       expected_version=resolved.record_version), "operator-a", NOW + 3)
    assert reopened.resolved_at is None
    _, resolved = store.change(identity, StatusChange(status="RESOLVED", reason="Recovery confirmed",
                                                       expected_version=reopened.record_version), "operator-a", NOW + 4)
    _, closed = store.change(identity, StatusChange(status="CLOSED", reason="Review completed",
                                                     expected_version=resolved.record_version), "operator-a", NOW + 5)
    assert closed.closed_at is not None
    assert store.change(identity, StatusChange(status="OPEN", reason="Reopen is blocked",
                                               expected_version=closed.record_version),
                        "operator-a", NOW + 6)[0] == "INVALID_INCIDENT_TRANSITION"
    assert len(store.history(identity, "history", 20, 0)) == 5
    assert len({row["actor_id"] for row in store.history(identity, "history", 20, 0)}) == 1


def test_api_filters_paging_auth_history_and_legacy_preservation(setup):
    context, _, settings, _, store = setup
    insert(context, detection())
    transfer(setup)
    doc = managed(store)[0]
    identity = doc.incident_id
    extra = detection().model_copy(update={"trace_id": "b" * 32, "idempotency_key": "f" * 64,
                                           "detection_event_id": "f" * 64})
    insert(context, extra)
    transfer(setup)
    legacy = Ledger(settings.storage_path)
    _, old = legacy.claim("fixture", "fixture-signature")
    legacy.finish("fixture", {"incident_id": old, "analysis_status": "INSUFFICIENT_EVIDENCE",
                              "scope_signature": "fixture-signature",
                              "report": {"suspected_root_cause": {"summary": "legacy proposed claim"}}})
    config = settings.model_copy(update={"handoff_enabled": False})
    with TestClient(create_app(config, clock=lambda: NOW + 10)) as http:
        assert http.get("/health").status_code == http.get("/ready").status_code == 200
        assert http.get("/incidents").status_code == 401
        assert http.get("/incidents", headers={"Authorization": "Bearer bad"}).status_code == 401
        assert http.get("/incidents/statistics", headers=READ).json()["total_incidents"] == 2
        assert http.get("/incidents/statistics", headers=AUTH).json()["real_count"] == 0
        first = http.get("/incidents?limit=1", headers=READ).json()
        second = http.get("/incidents?limit=1&offset=1", headers=READ).json()
        assert first["total"] == second["total"] == 2 and first["items"][0] != second["items"][0]
        for params in ({"service": "order"}, {"severity": "high"}, {"incident_status": "OPEN"},
                       {"detection_source": "rule_based"}, {"anomaly_type": "HTTP_SERVER_ERROR"},
                       {"from_time": "2020-01-01T00:00:00Z", "to_time": "2040-01-01T00:00:00Z"}):
            assert http.get("/incidents", params=params, headers=READ).json()["total"] == 2
        for params in ({"analysis_provider": "mock"}, {"is_mock": False},
                       {"from_time": "2040-01-01T00:00:00Z"}):
            assert http.get("/incidents", params=params, headers=READ).json()["total"] == 0
        for params in ({"source_namespace": "' OR 1=1 --"}, {"limit": 201}, {"from_time": "2020-01-01"},
                       {"arbitrary_sort": "DROP TABLE"}):
            assert http.get("/incidents", params=params, headers=READ).status_code == 422
        assert http.get("/incidents/" + "a" * 32, headers=READ).status_code == 404
        old_result = http.get(f"/incidents/{old}", headers=READ).json()
        assert old_result["report"]["suspected_root_cause"]["summary"] == "legacy proposed claim"
        assert http.get(f"/incidents/{identity}/evidence", headers=READ).json()["items"][0][
            "validation_status"] == "CONTEXT_UNAVAILABLE"
        url = f"/incidents/{identity}/status"
        body = {"status": "INVESTIGATING", "reason": "Operator started investigation", "expected_version": 1}
        assert http.patch(url, headers=READ, json=body).status_code == 403
        assert http.patch(url, headers=AUTH, json={**body, "actor_id": "forged"}).status_code == 422
        assert http.patch(url, headers=AUTH, content=b"x" * 4100).status_code == 413
        assert http.patch(url, headers=AUTH, json=body).status_code == 200
        assert http.patch(url, headers=AUTH, json=body).status_code == 409
        assert http.get(f"/incidents/{identity}/history", headers=READ).json()["items"][0]["actor_id"] == "operator-a"
        assert "/incidents/statistics" in http.get("/openapi.json").json()["paths"]


def test_database_failure_and_disabled_worker_are_safe(tmp_path, setup):
    context, _, settings, source, store = setup
    insert(context, detection())
    disabled = settings.model_copy(update={"management_enabled": False, "handoff_enabled": False})
    assert Worker(disabled, None, None).tick() == 0
    with TestClient(create_app(disabled)) as http:
        assert http.get("/ready").status_code == 503
    config = settings.model_copy(update={"handoff_enabled": False, "storage_path": str(tmp_path / "missing" / "db")})
    with TestClient(create_app(config)) as http:
        assert http.get("/ready").status_code == 503
        assert http.get("/incidents", headers=AUTH).status_code == 503
    with sqlite3.connect(store.path) as locked:
        locked.execute("BEGIN IMMEDIATE")
        worker = Worker(settings, source, store, clock=lambda: NOW)
        assert worker.tick() == 0 and worker.last_error == "INCIDENT_STORAGE_UNAVAILABLE"
        locked.rollback()
    assert transfer(setup, NOW + 1) == 0
    assert transfer(setup, NOW + 5) == 1


def test_forbidden_source_metadata_is_quarantined(setup):
    context, _, _, source, store = setup
    insert(context, detection())
    with source.connect() as sql:
        sql.execute("UPDATE incident_outbox SET detection=json_set(detection,'$.ground_truth','hidden')")
    assert transfer(setup) == 1
    assert managed(store) == [] and store.statistics({})["metrics"]["handoff_failures"] == 1


def test_namespace_distinguishes_same_trace_and_replay_keeps_identity(setup):
    context, _, _, source, store = setup
    insert(context, detection())
    row = source.claim(NOW)
    store.ingest(row, NOW)
    store.ingest(row, NOW)
    store.ingest({**row, "source_id": "second-stream", "namespace": "different-source"}, NOW)
    records = managed(store)
    assert len(records) == 2 and all(item.trace_id == TRACE for item in records)
    assert len({item.incident_correlation_key for item in records}) == 2
    assert store.statistics({})["metrics"]["duplicate_handoffs"] == 1


def test_late_detection_does_not_auto_reopen_resolved_incident(setup):
    context, _, _, _, store = setup
    insert(context, detection())
    transfer(setup)
    before = managed(store)[0]
    store.change(before.incident_id, StatusChange(status="RESOLVED", reason="Operator confirmed recovery",
                                                  expected_version=1), "operator-a", NOW + 1)
    insert(context, detection(version=2))
    transfer(setup, NOW + 2)
    after = managed(store)[0]
    assert after.incident_id == before.incident_id and after.current_trace_version == 2
    assert after.incident_status == "RESOLVED" and after.resolved_at is not None
    assert store.statistics({})["detection_revision_count"] == 2
