"""SQLite checkpoint, durable trace queue, and idempotent detection history."""

import hashlib
import json
import math
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.monitoring_config import VERSION
from app.rule_detection import normalize
from app.trace_store import valid_trace


SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoint (
    id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL, fingerprint TEXT NOT NULL,
    worker_version TEXT NOT NULL, floor REAL NOT NULL, cursor REAL NOT NULL,
    tiebreaker TEXT, last_event TEXT, last_poll REAL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
    window_start REAL NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
    token TEXT, claimed_version INTEGER, lease_until REAL, last_detection_at REAL
);
CREATE TABLE IF NOT EXISTS observed (
    event_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL REFERENCES traces ON DELETE CASCADE,
    payload TEXT NOT NULL, event_time REAL NOT NULL, conflicted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS observed_trace ON observed(trace_id);
CREATE TABLE IF NOT EXISTS results (
    idempotency_key TEXT PRIMARY KEY, trace_id TEXT NOT NULL REFERENCES traces ON DELETE CASCADE,
    trace_version INTEGER NOT NULL, detected_at REAL NOT NULL, document TEXT NOT NULL,
    UNIQUE(trace_id, trace_version)
);
CREATE TABLE IF NOT EXISTS failures (
    id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL REFERENCES traces ON DELETE CASCADE,
    trace_version INTEGER NOT NULL, occurred_at REAL NOT NULL, error_code TEXT NOT NULL, document TEXT
);
CREATE TABLE IF NOT EXISTS metrics (name TEXT PRIMARY KEY, value REAL NOT NULL);
CREATE TABLE IF NOT EXISTS worker_status (
    id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, updated_at REAL NOT NULL, error_code TEXT
);
CREATE VIEW IF NOT EXISTS detection_events AS
SELECT idempotency_key, trace_id, trace_version, detected_at, document FROM results
WHERE json_extract(document, '$.detection_status') = 'ANOMALY';
"""
TABLES = {"checkpoint", "traces", "observed", "results", "failures", "metrics", "worker_status"}


class CheckpointError(Exception):
    pass


@dataclass(frozen=True)
class Claim:
    trace_id: str
    version: int
    token: str
    attempt: int
    observed: dict


class MonitoringStore:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.storage_path

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db

    def open(self, now):
        required = self.settings.start_policy == "RESUME_CHECKPOINT"
        if required:
            if not Path(self.path).is_file():
                raise CheckpointError("CHECKPOINT_REQUIRED")
            with closing(sqlite3.connect(self.uri("ro"), uri=True)) as db:
                if db.execute("SELECT count(*) FROM checkpoint").fetchone()[0] != 1:
                    raise CheckpointError("CHECKPOINT_REQUIRED")
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and not TABLES <= tables:
                raise CheckpointError("INVALID_STORAGE_SCHEMA")
            db.execute("PRAGMA journal_mode=WAL")
            if tables:
                db.execute("BEGIN IMMEDIATE")
            else:
                db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
            row = db.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
            if row is None:
                if required or tables:
                    raise CheckpointError("CHECKPOINT_REQUIRED")
                floor = now - self.settings.lookback_seconds
                db.execute("INSERT INTO checkpoint VALUES (1,?,?,?,?,?,NULL,NULL,NULL,?)",
                           (self.settings.es_index, self.settings.fingerprint(), VERSION, floor, floor, now))
            else:
                self.validate_checkpoint(row, now)

    def uri(self, mode):
        return Path(self.path).absolute().as_uri() + f"?mode={mode}"

    def validate_checkpoint(self, row, now):
        if (row["source"], row["fingerprint"], row["worker_version"]) != (
            self.settings.es_index, self.settings.fingerprint(), VERSION
        ):
            raise CheckpointError("CHECKPOINT_CONFIGURATION_MISMATCH")
        values = (row["floor"], row["cursor"], row["updated_at"])
        if (not all(isinstance(x, (float, int)) and math.isfinite(x) for x in values)
                or not 0 <= row["floor"] <= row["cursor"] <= now or row["updated_at"] > now
                or row["updated_at"] < row["cursor"]
                or (row["last_event"] is not None and
                    (not isinstance(row["last_event"], str) or not valid_trace(row["last_event"])))
                or (row["tiebreaker"] is not None and not isinstance(row["tiebreaker"], str))
                or (row["last_poll"] is not None and
                    (not isinstance(row["last_poll"], (float, int))
                     or not row["cursor"] <= row["last_poll"] <= row["updated_at"]))):
            raise CheckpointError("INVALID_CHECKPOINT")

    def window(self, now):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
            if row is None:
                raise CheckpointError("CHECKPOINT_REQUIRED")
            self.validate_checkpoint(row, now)
            return max(row["floor"], row["cursor"] - self.settings.overlap_seconds), row["cursor"]

    @staticmethod
    def count(db, name, amount=1):
        db.execute("INSERT INTO metrics VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value",
                   (name, amount))

    @staticmethod
    def gauge(db, name, value):
        db.execute("INSERT INTO metrics VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                   (name, value))

    def mark(self, state, now, error=None, latency=None):
        with self.transaction() as db:
            db.execute("INSERT INTO worker_status VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "state=excluded.state,updated_at=excluded.updated_at,error_code=excluded.error_code",
                       (state, now, error))
            if latency is not None:
                self.count(db, "poll_latency_ms_total", latency)
                self.count(db, "poll_attempts")

    def accept_page(self, hits, now):
        last_id = None
        with self.transaction() as db:
            self.count(db, "events_fetched", len(hits))
            for hit in hits:
                source = hit.get("_source") if isinstance(hit, dict) else None
                if not isinstance(source, dict):
                    self.count(db, "invalid_events")
                    continue
                trace_id = source.get("trace_id")
                if not isinstance(trace_id, str) or not valid_trace(trace_id):
                    self.count(db, "uncorrelated_events")
                    continue
                if not source.get("event_id"):
                    self.count(db, "missing_event_ids")
                events, _, _ = normalize([source], trace_id)
                if not events:
                    self.count(db, "invalid_events")
                    continue
                event = events[0]
                last_id = event.event_id
                value = event.model_dump_json()
                previous = db.execute("SELECT * FROM observed WHERE event_id=?", (event.event_id,)).fetchone()
                if previous:
                    if previous["payload"] == value:
                        self.count(db, "duplicate_events")
                    else:
                        self.count(db, "conflicting_event_ids")
                        if not previous["conflicted"]:
                            db.execute("UPDATE observed SET conflicted=1 WHERE event_id=?", (event.event_id,))
                            self.touch_trace(db, previous["trace_id"], now)
                    continue
                self.touch_trace(db, trace_id, now)
                db.execute("INSERT INTO observed VALUES (?,?,?,?,0)",
                           (event.event_id, trace_id, value, event.timestamp.timestamp()))
                self.count(db, "events_accepted")
        return last_id

    def touch_trace(self, db, trace_id, now):
        row = db.execute("SELECT * FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
        if row is None:
            db.execute("INSERT INTO traces(trace_id,first_seen,last_seen,window_start,version,status) "
                       "VALUES (?,?,?,?,1,'PENDING')", (trace_id, now, now, now))
            return
        new_window = row["status"] in {"DETECTED", "PROCESSING_FAILED", "RETRY_PENDING"} or (
            row["status"] == "DETECTING" and row["claimed_version"] == row["version"]
        )
        if row["last_detection_at"] is not None or row["token"] is not None:
            self.count(db, "late_events")
        db.execute("UPDATE traces SET version=version+1,last_seen=?,window_start=?,"
                   "status=CASE WHEN token IS NULL THEN 'UPDATED' ELSE status END,attempts=0 WHERE trace_id=?",
                   (now, now if new_window else row["window_start"], trace_id))

    def advance(self, expected, upper, tiebreaker, last_id, now):
        with self.transaction() as db:
            updated = db.execute("UPDATE checkpoint SET cursor=?,tiebreaker=?,last_event=COALESCE(?,last_event),"
                                 "last_poll=?,updated_at=? WHERE id=1 AND cursor=?",
                                 (upper, tiebreaker, last_id, now, now, expected))
            if updated.rowcount != 1:
                raise CheckpointError("CHECKPOINT_CHANGED_DURING_POLL")
            self.count(db, "successful_polls")
            expiry = now - self.settings.retention_seconds
            db.execute("DELETE FROM traces WHERE token IS NULL AND status IN ('DETECTED','PROCESSING_FAILED') "
                       "AND last_seen < ? AND COALESCE(last_detection_at,0) < ? AND NOT EXISTS "
                       "(SELECT 1 FROM observed WHERE observed.trace_id=traces.trace_id AND event_time >= ?)",
                       (expiry, expiry, upper - self.settings.overlap_seconds))

    def claims(self, now):
        settings = self.settings
        with self.transaction() as db:
            expired = db.execute("SELECT * FROM traces WHERE token IS NOT NULL AND lease_until<=?", (now,)).fetchall()
            for row in expired:
                db.execute("INSERT INTO failures(trace_id,trace_version,occurred_at,error_code) VALUES (?,?,?,?)",
                           (row["trace_id"], row["claimed_version"], now, "INTERRUPTED_DETECTION"))
                state = "PROCESSING_FAILED" if row["attempts"] > settings.max_retries else "RETRY_PENDING"
                db.execute("UPDATE traces SET token=NULL,claimed_version=NULL,lease_until=NULL,status=?,next_at=? "
                           "WHERE trace_id=?",
                           (state, now, row["trace_id"]))
            in_flight = db.execute("SELECT count(*) FROM traces WHERE token IS NOT NULL").fetchone()[0]
            due = db.execute(
                "SELECT * FROM traces WHERE token IS NULL AND status IN ('PENDING','UPDATED','RETRY_PENDING') "
                "AND next_at<=? AND (status='RETRY_PENDING' OR last_seen<=? OR window_start<=?) "
                "ORDER BY window_start,trace_id LIMIT ?",
                (now, now - settings.quiet_period_seconds, now - settings.max_trace_wait_seconds,
                 max(0, settings.max_concurrent_traces - in_flight)),
            ).fetchall()
            claimed = []
            for row in due:
                token, attempt = uuid4().hex, row["attempts"] + 1
                lease = now + settings.detection_timeout_seconds + settings.timeout_cooldown_seconds
                db.execute("UPDATE traces SET token=?,claimed_version=version,lease_until=?,attempts=?,"
                           "status='DETECTING' WHERE trace_id=?", (token, lease, attempt, row["trace_id"]))
                observed = {r["event_id"]: None if r["conflicted"] else json.loads(r["payload"]) for r in
                            db.execute("SELECT * FROM observed WHERE trace_id=?", (row["trace_id"],))}
                claimed.append(Claim(row["trace_id"], row["version"], token, attempt, observed))
                self.count(db, "detection_requests")
                if attempt > 1:
                    self.count(db, "retry_count")
        return claimed

    def finish(self, claim, now, *, document=None, failure=None, latency_ms=0):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM traces WHERE trace_id=? AND token=?",
                             (claim.trace_id, claim.token)).fetchone()
            if row is None:
                return False
            updated = row["version"] != claim.version
            if failure is None:
                inserted = db.execute("INSERT INTO results VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                                      (document.idempotency_key, claim.trace_id, claim.version,
                                       document.detected_at.timestamp(), document.model_dump_json())).rowcount
                if inserted:
                    self.count(db, "detection_successes")
                    if document.is_anomaly:
                        self.count(db, "anomalies_detected")
                self.gauge(db, "last_detection_success_at", now)
                state, next_at = ("UPDATED" if updated else "DETECTED"), now
            else:
                preserved = failure.result.model_dump_json() if failure.result is not None else None
                db.execute("INSERT INTO failures(trace_id,trace_version,occurred_at,error_code,document) VALUES (?,?,?,?,?)",
                           (claim.trace_id, claim.version, now, failure.code, preserved))
                self.count(db, "detection_errors")
                self.gauge(db, "last_detection_error_at", now)
                delay = self.settings.retry_backoff_seconds * (2 ** min(claim.attempt - 1, 6))
                if failure.cooldown:
                    delay = max(delay, self.settings.timeout_cooldown_seconds)
                if updated:
                    state = "UPDATED"
                elif failure.retryable and claim.attempt <= self.settings.max_retries:
                    state = "RETRY_PENDING"
                else:
                    state = "PROCESSING_FAILED"
                next_at = now + delay
            self.count(db, "detection_latency_ms_total", latency_ms)
            db.execute("UPDATE traces SET status=?,next_at=?,token=NULL,claimed_version=NULL,"
                       "lease_until=NULL,last_detection_at=? "
                       "WHERE trace_id=?", (state, next_at, now, claim.trace_id))
        return True

    def read_status(self, now):
        with closing(sqlite3.connect(self.uri("ro"), uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            status = db.execute("SELECT state,updated_at,error_code FROM worker_status").fetchone()
            checkpoint = db.execute("SELECT * FROM checkpoint").fetchone()
            counts = dict(db.execute("SELECT name,value FROM metrics"))
            states = dict(db.execute("SELECT status,count(*) FROM traces GROUP BY status"))
        if checkpoint is None:
            raise CheckpointError("CHECKPOINT_REQUIRED")
        self.validate_checkpoint(checkpoint, now)
        state = status["state"] if status else "STARTING"
        last_error = counts.get("last_detection_error_at", 0)
        detector_degraded = last_error > counts.get("last_detection_success_at", 0)
        stale = status and now - status["updated_at"] > (
            self.settings.poll_interval_seconds + self.settings.poll_timeout_seconds
            + self.settings.detection_timeout_seconds + 5)
        if state == "RUNNING" and (stale or detector_degraded):
            state = "DEGRADED"
        reason = status["error_code"] if status else None
        if state == "DEGRADED" and reason is None:
            reason = "WORKER_HEARTBEAT_STALE" if stale else "DETECTION_BACKEND_DEGRADED"
        return {"enabled": self.settings.enabled, "state": state, "ready": state == "RUNNING",
                "error_code": reason,
                "last_successful_poll": checkpoint["last_poll"], "last_checkpoint_update": checkpoint["updated_at"],
                "pending_traces": sum(states.get(s, 0) for s in ("PENDING", "UPDATED", "RETRY_PENDING")),
                "in_flight": states.get("DETECTING", 0), "metrics": counts}
