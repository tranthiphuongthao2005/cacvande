import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from app.hybrid_detection import HybridRouter
from app.context_store import Snapshot
from app.monitoring_client import DetectionFailure
from app.monitoring_config import Settings
from app.monitoring_models import make_event
from app.monitoring_store import CheckpointError, MonitoringStore
from test_rule_detection import TRACE, completion, dependency, cascade

NOW = 1795366900
OTHER = "c" * 32


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_path=str(tmp_path / "monitoring.sqlite"), quiet_period_seconds=5,
                    max_trace_wait_seconds=15, max_concurrent_traces=1)


@pytest.fixture
def store(settings):
    result = MonitoringStore(settings)
    result.open(NOW)
    return result


def query(store, sql):
    with closing(sqlite3.connect(store.path)) as db:
        return db.execute(sql).fetchall()


def hit(row):
    return {"_source": row}


def add(store, *rows, now=NOW):
    store.accept_page([hit(row) for row in rows], now)


def output(rows):
    return HybridRouter().route(TRACE, "AUTO", lambda _: Snapshot(rows))[1]


@pytest.mark.parametrize("same_batch", [True, False])
def test_duplicates_persist_across_batches_and_restart(settings, store, same_batch):
    row = completion()
    add(store, row, row) if same_batch else add(store, row)
    reopened = MonitoringStore(settings)
    reopened.open(NOW + 1)
    if not same_batch:
        add(reopened, row)
    assert query(reopened, "SELECT version FROM traces") == [(1,)]
    assert dict(query(reopened, "SELECT * FROM metrics"))["duplicate_events"] == 1


def test_conflict_missing_identifiers_and_trace_grouping(store):
    row = completion(status=503)
    add(store, row, {**row, "status_code": 200}, {**completion(6), "trace_id": OTHER},
        {**completion(7), "trace_id": None}, {**completion(8), "event_id": None})
    metrics = dict(query(store, "SELECT * FROM metrics"))
    assert metrics["conflicting_event_ids"] == metrics["missing_event_ids"] == metrics["uncorrelated_events"] == 1
    assert query(store, "SELECT version FROM traces ORDER BY trace_id") == [(2,), (1,)]
    claim, = store.claims(NOW + 5)
    assert claim.trace_id == TRACE and claim.observed == {row["event_id"]: None}


def test_quiet_and_max_wait_with_new_events(store):
    add(store, completion(1))
    for number, when in enumerate((4, 8, 12, 14), 2):
        assert store.claims(NOW + when) == []
        add(store, completion(number), now=NOW + when)
    claim, = store.claims(NOW + 15)
    assert claim.version == 5


def test_concurrent_claims_limited_and_same_trace_fenced(store):
    add(store, completion(), {**completion(6), "trace_id": OTHER})
    with ThreadPoolExecutor(2) as threads:
        claims = sum(threads.map(store.claims, [NOW + 5] * 2), [])
    assert len(claims) == 1
    assert store.claims(NOW + 6) == []


def test_late_event_during_detection_retains_prior_version(store):
    row = completion(status=503)
    add(store, row)
    first, = store.claims(NOW + 5)
    other = completion(6)
    add(store, other, now=NOW + 6)
    assert store.claims(NOW + 7) == []
    assert store.finish(first, NOW + 7, document=make_event(output([row]), first, NOW + 7))
    assert not store.finish(first, NOW + 8, document=make_event(output([row]), first, NOW + 8))
    second, = store.claims(NOW + 11)
    assert second.version == first.version + 1
    assert query(store, "SELECT trace_version FROM detection_events") == [(1,)]


def test_max_retries_and_timeout_cooldown(store):
    add(store, completion())
    now = NOW + 5
    for attempt in (1, 2, 3):
        claim, = store.claims(now)
        assert claim.attempt == attempt
        error = DetectionFailure("DETECTION_TIMEOUT", retryable=True, cooldown=True)
        assert store.finish(claim, now, failure=error)
        assert store.claims(now + 89) == []
        now += 90
    assert store.claims(now) == []
    assert query(store, "SELECT status FROM traces") == [("PROCESSING_FAILED",)]
    assert len(query(store, "SELECT * FROM failures")) == 3


def test_regular_backoff_exponent(store):
    add(store, completion())
    for offset, backoff in ((5, 10), (15, 20)):
        claim, = store.claims(NOW + offset)
        store.finish(claim, NOW + offset, failure=DetectionFailure("DETECTION_HTTP_503", retryable=True))
        assert store.claims(NOW + offset + backoff - 1) == []
    assert store.claims(NOW + 35)[0].attempt == 3


def test_checkpoint_scope_and_initial_policy(settings, store):
    assert store.window(NOW + 10) == (NOW, NOW)
    store.advance(NOW, NOW + 10, None, None, NOW + 11)
    assert MonitoringStore(settings).window(NOW + 12) == (NOW, NOW + 10)
    settings = settings.model_copy(update={"overlap_seconds": 301})
    with pytest.raises(CheckpointError, match="MISMATCH"):
        MonitoringStore(settings).open(NOW + 12)


def test_lookback_and_resume(settings):
    resume = settings.model_copy(update={"start_policy": "RESUME_CHECKPOINT"})
    with pytest.raises(CheckpointError, match="REQUIRED"):
        MonitoringStore(resume).open(NOW)
    assert not Path(settings.storage_path).exists()
    explicit = settings.model_copy(update={"start_policy": "EXPLICIT_LOOKBACK", "lookback_seconds": 30})
    seed = MonitoringStore(explicit)
    seed.open(NOW)
    MonitoringStore(resume).open(NOW)
    assert seed.window(NOW) == (NOW - 30, NOW - 30)


@pytest.mark.parametrize("corrupt", ["sqlite_file", "cursor", "missing_checkpoint"])
def test_corrupt_checkpoint_fails_closed(settings, store, corrupt):
    if corrupt == "sqlite_file":
        Path(store.path).write_bytes(b"corrupt")
        with pytest.raises(sqlite3.DatabaseError):
            MonitoringStore(settings).open(NOW)
        return
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE checkpoint SET cursor='invalid'" if corrupt == "cursor" else "DELETE FROM checkpoint")
    with pytest.raises(CheckpointError):
        MonitoringStore(settings).open(NOW)


@pytest.mark.parametrize("crash", ["before_commit", "after_page_commit", "after_detection_response"])
def test_restart_recovers_durable_state(settings, store, crash):
    row = completion(status=503)
    if crash == "before_commit":
        original = store.touch_trace
        def interrupted(*args):
            original(*args)
            raise RuntimeError("interrupted")
        store.touch_trace = interrupted
        with pytest.raises(RuntimeError):
            add(store, row)
        assert query(store, "SELECT * FROM traces") == []
    else:
        add(store, row)
    if crash == "after_detection_response":
        lost, = store.claims(NOW + 5)
        assert make_event(output([row]), lost, NOW + 6).is_anomaly
        assert query(store, "SELECT * FROM results") == []
    restarted = MonitoringStore(settings)
    restarted.open(NOW + 7)
    assert restarted.window(NOW + 7) == (NOW, NOW)
    add(restarted, row, now=NOW + 7)
    due = NOW + 12
    if crash == "after_detection_response":
        assert restarted.claims(due) == []
        due = NOW + 5 + settings.detection_timeout_seconds + settings.timeout_cooldown_seconds
    claim, = restarted.claims(due)
    document = make_event(output([row]), claim, due)
    assert restarted.finish(claim, due, document=document)
    assert not restarted.finish(claim, due, document=document)
    assert len(query(restarted, "SELECT * FROM detection_events")) == 1


def test_result_and_trace_transition_roll_back_together(store):
    row = completion(status=503)
    add(store, row)
    claim, = store.claims(NOW + 5)
    document = make_event(output([row]), claim, NOW + 5)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("CREATE TRIGGER fail_transition BEFORE UPDATE ON traces WHEN NEW.status='DETECTED' "
                   "BEGIN SELECT RAISE(ABORT, 'simulated crash'); END")
    with pytest.raises(sqlite3.IntegrityError, match="simulated crash"):
        store.finish(claim, NOW + 5, document=document)
    assert query(store, "SELECT status FROM traces") == [("DETECTING",)]
    assert query(store, "SELECT * FROM results") == []


@pytest.mark.parametrize(("rows", "state", "eligibility", "completeness"), [
    ([completion()], "NO_ANOMALY_DETECTED", "NOT_ELIGIBLE", "partial"),
    ([completion(status=503)], "ANOMALY", "ELIGIBLE", "partial"),
    ([], "INSUFFICIENT_DATA", "NEEDS_MORE_EVIDENCE", "unknown"),
    ([dependency(1, code="dependency_timeout"), completion()], "ANOMALY", "RECOVERED_SIGNAL", "partial"),
    (cascade(), "ANOMALY", "ELIGIBLE", "partial"),
])
def test_processing_results_and_eligibility(store, rows, state, eligibility, completeness):
    add(store, *(rows or [completion()]))
    claim, = store.claims(NOW + 5)
    event = make_event(output(rows), claim, NOW + 5)
    store.finish(claim, NOW + 5, document=event)
    document = json.loads(query(store, "SELECT document FROM results")[0][0])
    assert document["detection_status"] == state and document["incident_eligibility"] == eligibility
    assert document["context_completeness"] == completeness and document["model_score"] is None
    assert document["is_anomaly"] is (True if state == "ANOMALY" else None if not rows else False)


def test_unpolled_evidence_is_preserved_without_assuming_consistency(store):
    add(store, completion(1))
    claim, = store.claims(NOW + 5)
    row = completion(status=503)
    doc = make_event(output([row]), claim, NOW + 5)
    assert doc.unobserved_evidence_event_ids == doc.evidence_event_ids == [row["event_id"]]
    assert doc.worker_observed_event_ids == [completion(1)["event_id"]]
    assert doc.incident_eligibility == "NEEDS_MORE_EVIDENCE"
