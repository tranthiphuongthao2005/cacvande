import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.context_integration import Settings, Worker, utc
from app.context_integration_client import ContextFailure
from app.context_integration_models import build_package, context_payload
from app.context_integration_store import ContextPackageStore, StorageFailure
from app.monitoring_config import Settings as MonitoringSettings
from app.monitoring_store import MonitoringStore
from test_context_integration import context, detection
from test_monitoring_store import NOW, query
from test_rule_detection import TRACE, completion


def insert(store, event):
    with store.connection(write=True) as db:
        db.execute("INSERT OR IGNORE INTO traces(trace_id,first_seen,last_seen,window_start,version,status) "
                   "VALUES(?,?,?,?,?,'DETECTED')", (event.trace_id, NOW, NOW, NOW, event.trace_version))
        db.execute("INSERT INTO results VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                   (event.idempotency_key, event.trace_id, event.trace_version, NOW, event.model_dump_json()))


@pytest.fixture
def store(tmp_path):
    path = str(tmp_path / "monitoring.sqlite")
    MonitoringStore(MonitoringSettings(storage_path=path)).open(NOW)
    store = ContextPackageStore(Settings(storage_path=path, max_concurrency=1))
    store.install()
    return store


def states(store):
    with store.connection() as db:
        return [row[0] for row in db.execute("SELECT state FROM context_jobs ORDER BY trace_version")]


def package(event, claim):
    return build_package(event, context_payload(context([completion(status=503)]), TRACE), claim, {}, "local",
                         utc(NOW), utc(NOW))


def test_migration_has_no_backfill_and_is_idempotent(tmp_path):
    path = str(tmp_path / "monitoring.sqlite")
    MonitoringStore(MonitoringSettings(storage_path=path)).open(NOW)
    store = ContextPackageStore(Settings(storage_path=path))
    insert(store, detection())
    store.install()
    assert not store.claims(NOW)
    store.install()
    insert(store, detection(version=2))
    insert(store, detection(version=2))
    assert states(store) == ["PENDING_CONTEXT"]


def test_retry_limit_and_exponential_backoff(store):
    async def exercise():
        now = NOW
        insert(store, detection())
        async def unavailable(_):
            raise ContextFailure("CONTEXT_HTTP_503", True)
        worker = Worker(store.settings, store, SimpleNamespace(retrieve=unavailable), clock=lambda: now)
        for wait in (10, 20, 0):
            assert await worker.tick() == ["CONTEXT_HTTP_503"]
            if wait:
                now += wait - 1
                assert await worker.tick() == []
                now += 1
        assert states(store) == ["CONTEXT_FAILED"]
        assert await worker.tick() == []
        assert store.inspect(now)["retry_count"] == 2
    asyncio.run(exercise())


def test_concurrency_and_expired_claim_fencing(store):
    event = detection()
    insert(store, event)
    with ThreadPoolExecutor(2) as pool:
        claims = sum(pool.map(store.claims, [NOW, NOW]), [])
    assert len(claims) == 1
    restarted = ContextPackageStore(store.settings)
    restarted.install()
    assert restarted.claims(NOW + 1) == []
    assert restarted.claims(NOW + 42) == []
    retry, = restarted.claims(NOW + 52)
    assert retry.last_error == "INTERRUPTED_CONTEXT"
    assert not restarted.finish(claims[0], NOW + 52, package=package(event, claims[0]))
    assert restarted.finish(retry, NOW + 52, package=package(event, retry))
    assert not restarted.finish(retry, NOW + 53, package=package(event, retry))
    assert restarted.read_package(package(event, retry).context_package_id) is not None


def test_concurrency_limit_applies_to_different_traces(store):
    insert(store, detection())
    insert(store, detection().model_copy(update={
        "trace_id": "b" * 32, "idempotency_key": "f" * 64, "detection_event_id": "f" * 64,
    }))
    with ThreadPoolExecutor(2) as pool:
        claims = sum(pool.map(store.claims, [NOW, NOW]), [])
    assert len(claims) == 1 and store.claims(NOW + 1) == []


def test_atomic_commit_if_worker_crashes_before_acknowledgement(store):
    event = detection()
    insert(store, event)
    claim, = store.claims(NOW)
    doc = package(event, claim)
    with store.connection(write=True) as db:
        db.execute("CREATE TRIGGER fail_context_commit BEFORE UPDATE ON context_jobs "
                   "WHEN NEW.state='READY_FOR_ANALYSIS' BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.finish(claim, NOW, package=doc)
    assert store.read_package(doc.context_package_id) is None
    assert states(store) == ["FETCHING_CONTEXT"]
    with store.connection(write=True) as db:
        db.execute("DROP TRIGGER fail_context_commit")
    assert store.finish(claim, NOW, package=doc)
    reopened = ContextPackageStore(store.settings)
    assert reopened.claims(NOW + 60) == []
    assert reopened.read_package(doc.context_package_id) == doc
    assert not reopened.finish(claim, NOW + 60, package=doc)


def test_newer_trace_supersedes_analysis_queue_preserving_history(store):
    old = detection()
    insert(store, old)
    claim, = store.claims(NOW)
    prior = package(old, claim)
    store.finish(claim, NOW, package=prior)
    insert(store, detection(version=2))
    assert states(store) == ["SUPERSEDED", "PENDING_CONTEXT"]
    observed, predecessor = store.context_inputs(store.claims(NOW)[0])
    assert predecessor == prior.context_package_id
    assert store.read_package(prior.context_package_id) == prior
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM analysis_readiness_queue").fetchone()[0] == 0


def test_storage_missing_and_namespace_mismatch_fail_closed(tmp_path, store):
    missing = ContextPackageStore(Settings(storage_path=str(tmp_path / "missing.sqlite")))
    with pytest.raises(sqlite3.Error):
        missing.install()
    assert not (tmp_path / "missing.sqlite").exists()
    with pytest.raises(StorageFailure, match="CONFIGURATION_MISMATCH"):
        ContextPackageStore(store.settings.model_copy(update={"namespace": "other"})).install()


def test_hash_corruption_blocks_handoff(store):
    event = detection()
    insert(store, event)
    claim, = store.claims(NOW)
    doc = package(event, claim)
    store.finish(claim, NOW, package=doc)
    assert store.read_ready(doc.context_package_id) == doc
    with store.connection(write=True) as db:
        db.execute("UPDATE context_packages SET document=json_set(document,'$.context_payload_sha256','bad')")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        store.read_ready(doc.context_package_id)


def test_worker_run_processes_job_and_dry_run_is_read_only(store):
    event = detection()
    insert(store, event)
    dry = store.settings.model_copy(update={"enabled": True, "dry_run": True})
    asyncio.run(Worker(dry, store, None, clock=lambda: NOW).run())
    assert states(store) == ["PENDING_CONTEXT"]
    assert not store.inspect(NOW)["ready"]

    async def retrieve(_):
        return context_payload(context([completion(status=503)]), TRACE)

    enabled = store.settings.model_copy(update={"enabled": True, "url": "http://fixture"})
    asyncio.run(Worker(enabled, store, SimpleNamespace(retrieve=retrieve), clock=lambda: NOW).run(once=True))
    assert states(store) == ["READY_FOR_ANALYSIS"]
    status = store.inspect(NOW)
    assert status["state"] == "STOPPED" and status["last_success"] == NOW
    assert status["retrieval_successes"] == status["context_requests"] == 1
