"""Additive SQLite outbox, context claims, and immutable package history."""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.context_integration_models import VERSION, verified_package

SCHEMA = """
CREATE TABLE IF NOT EXISTS context_settings (
    id INTEGER PRIMARY KEY CHECK(id=1), namespace TEXT NOT NULL, version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS context_jobs (
    event_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, trace_version INTEGER NOT NULL,
    document TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING_CONTEXT',
    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
    token TEXT, lease_until REAL, last_error TEXT, updated_at REAL NOT NULL,
    UNIQUE(trace_id, trace_version)
);
CREATE INDEX IF NOT EXISTS context_jobs_due ON context_jobs(state, next_at);
CREATE TABLE IF NOT EXISTS context_packages (
    package_id TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL REFERENCES context_jobs ON DELETE CASCADE,
    trace_id TEXT NOT NULL, trace_version INTEGER NOT NULL, document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS context_attempts (
    id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES context_jobs ON DELETE CASCADE,
    attempted_at REAL NOT NULL, attempt INTEGER NOT NULL, code TEXT NOT NULL,
    retrieval_ms REAL NOT NULL, processing_ms REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS context_status (
    id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, heartbeat REAL NOT NULL, last_success REAL,
    error_code TEXT
);
CREATE TABLE IF NOT EXISTS context_counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE VIEW IF NOT EXISTS analysis_readiness_queue AS
SELECT p.package_id,p.event_id,p.trace_id,p.trace_version,p.document FROM context_packages p
JOIN context_jobs j ON p.event_id=j.event_id WHERE j.state='READY_FOR_ANALYSIS';
CREATE TRIGGER IF NOT EXISTS enqueue_context_result AFTER INSERT ON results
BEGIN
    INSERT INTO context_jobs(event_id,trace_id,trace_version,document,updated_at)
    VALUES(NEW.idempotency_key,NEW.trace_id,NEW.trace_version,NEW.document,
           unixepoch('now')) ON CONFLICT DO NOTHING;
    INSERT INTO context_counters(name,value) SELECT 'duplicate_jobs_prevented',1 WHERE changes()=0
    ON CONFLICT(name) DO UPDATE SET value=value+1;
    UPDATE context_jobs SET state='SUPERSEDED',updated_at=unixepoch('now')
    WHERE trace_id=NEW.trace_id AND trace_version<(SELECT max(trace_version) FROM context_jobs WHERE trace_id=NEW.trace_id)
      AND state IN ('PENDING_CONTEXT','CONTEXT_RETRY_PENDING','READY_FOR_ANALYSIS',
                    'NEEDS_MORE_EVIDENCE','NEEDS_REVIEW');
END;
"""
SCHEMA_OBJECTS = {
    "context_settings", "context_jobs", "context_jobs_due", "context_packages", "context_attempts",
    "context_status", "context_counters", "analysis_readiness_queue", "enqueue_context_result",
}


class StorageFailure(Exception):
    pass


@dataclass(frozen=True)
class Claim:
    event_id: str
    trace_id: str
    trace_version: int
    document: str
    token: str
    attempt: int
    last_error: str | None


class ContextPackageStore:
    def __init__(self, settings):
        self.settings = settings
        self.uri = Path(settings.storage_path).absolute().as_uri()

    @contextmanager
    def connection(self, write=False):
        mode = "rw" if write else "ro"
        with closing(sqlite3.connect(f"{self.uri}?mode={mode}", uri=True, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def install(self):
        # Run DDL and namespace binding as one transaction; no INSERT SELECT backfill.
        with closing(sqlite3.connect(f"{self.uri}?mode=rw", uri=True, timeout=2)) as db, db:
            objects = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            if "detection_events" not in objects:
                raise StorageFailure("MONITORING_SCHEMA_REQUIRED")
            if objects & SCHEMA_OBJECTS and not SCHEMA_OBJECTS <= objects:
                raise StorageFailure("INCOMPLETE_CONTEXT_STORAGE_SCHEMA")
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
            db.execute("INSERT OR IGNORE INTO context_settings VALUES (1,?,?)", (self.settings.namespace, VERSION))
            row = db.execute("SELECT namespace,version FROM context_settings WHERE id=1").fetchone()
            if row != (self.settings.namespace, VERSION):
                raise StorageFailure("CONTEXT_STORAGE_CONFIGURATION_MISMATCH")

    def claims(self, now):
        with self.connection(write=True) as db:
            expired = db.execute("SELECT * FROM context_jobs WHERE state='FETCHING_CONTEXT' AND lease_until<=?",
                                 (now,)).fetchall()
            for job in expired:
                claim = Claim(job["event_id"], job["trace_id"], job["trace_version"], job["document"], job["token"],
                              job["attempts"], job["last_error"])
                self.transition(db, claim, now, "INTERRUPTED_CONTEXT", True, 0, 0)
            inflight = db.execute("SELECT count(*) FROM context_jobs WHERE state='FETCHING_CONTEXT'").fetchone()[0]
            slots = min(self.settings.batch_size, max(0, self.settings.max_concurrency - inflight))
            rows = db.execute(
                "SELECT j.* FROM context_jobs j WHERE j.state IN ('PENDING_CONTEXT','CONTEXT_RETRY_PENDING') "
                "AND j.next_at<=? AND NOT EXISTS(SELECT 1 FROM context_jobs other WHERE other.trace_id=j.trace_id "
                "AND (other.state='FETCHING_CONTEXT' OR other.trace_version>j.trace_version)) "
                "ORDER BY j.next_at,j.rowid LIMIT ?", (now, slots),
            ).fetchall()
            claims = []
            for row in rows:
                token = uuid4().hex
                db.execute("UPDATE context_jobs SET state='FETCHING_CONTEXT',attempts=attempts+1,token=?,"
                           "lease_until=?,updated_at=? WHERE event_id=?",
                           (token, now + self.settings.timeout_seconds + 30, now, row["event_id"]))
                claims.append(Claim(row["event_id"], row["trace_id"], row["trace_version"], row["document"],
                                    token, row["attempts"] + 1, row["last_error"]))
            return claims

    def context_inputs(self, claim):
        with self.connection() as db:
            observed = {row["event_id"]: None if row["conflicted"] else json.loads(row["payload"]) for row in
                        db.execute("SELECT event_id,payload,conflicted FROM observed WHERE trace_id=?", (claim.trace_id,))}
            prior = db.execute("SELECT package_id FROM context_packages WHERE trace_id=? AND trace_version<? "
                               "ORDER BY trace_version DESC LIMIT 1", (claim.trace_id, claim.trace_version)).fetchone()
        return observed, prior["package_id"] if prior else None

    def finish(self, claim, now, *, package=None, error=None, retry=False, skipped=False,
               retrieval_ms=0, processing_ms=0):
        with self.connection(write=True) as db:
            if not db.execute("SELECT 1 FROM context_jobs WHERE event_id=? AND token=?",
                              (claim.event_id, claim.token)).fetchone():
                return False
            self.transition(db, claim, now, error, retry, retrieval_ms, processing_ms, package, skipped)
            return True

    def transition(self, db, claim, now, error, retry, retrieval_ms, processing_ms, package=None, skipped=False):
        next_at = 0
        if package:
            db.execute("INSERT INTO context_packages VALUES (?,?,?,?,?)",
                       (package.context_package_id, claim.event_id, claim.trace_id, claim.trace_version,
                        package.model_dump_json()))
            state = package.analysis_readiness
        elif skipped:
            state = "SKIPPED_NOT_ELIGIBLE"
        elif retry and claim.attempt <= self.settings.max_retries:
            state = "CONTEXT_RETRY_PENDING"
            next_at = now + self.settings.retry_backoff_seconds * (2 ** (claim.attempt - 1))
        else:
            state = "CONTEXT_FAILED"
        if db.execute("SELECT 1 FROM context_jobs WHERE trace_id=? AND trace_version>?",
                      (claim.trace_id, claim.trace_version)).fetchone():
            state = "SUPERSEDED"
        db.execute("INSERT INTO context_attempts(event_id,attempted_at,attempt,code,retrieval_ms,processing_ms) "
                   "VALUES(?,?,?,?,?,?)", (claim.event_id, now, claim.attempt, error or "CONTEXT_STORED",
                                          retrieval_ms, processing_ms))
        db.execute("UPDATE context_jobs SET state=?,next_at=?,token=NULL,lease_until=NULL,"
                   "last_error=?,updated_at=? WHERE event_id=?", (state, next_at, error, now, claim.event_id))

    def read_package(self, package_id):
        with self.connection() as db:
            row = db.execute("SELECT document FROM context_packages WHERE package_id=?", (package_id,)).fetchone()
        return verified_package(row["document"]) if row else None

    def read_ready(self, package_id):
        """Read and verify a currently queued package, without claiming downstream analysis."""
        with self.connection() as db:
            row = db.execute("SELECT document FROM analysis_readiness_queue WHERE package_id=?",
                             (package_id,)).fetchone()
        return verified_package(row["document"]) if row else None

    def mark(self, state, now, error=None, success=False):
        with self.connection(write=True) as db:
            db.execute("INSERT INTO context_status VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "state=excluded.state,heartbeat=excluded.heartbeat,error_code=excluded.error_code,"
                       "last_success=COALESCE(excluded.last_success,context_status.last_success)",
                       (state, now, now if success else None, error))
            db.execute("DELETE FROM context_jobs WHERE state NOT IN "
                       "('PENDING_CONTEXT','FETCHING_CONTEXT','CONTEXT_RETRY_PENDING') "
                       "AND updated_at<? AND NOT EXISTS "
                       "(SELECT 1 FROM results WHERE idempotency_key=context_jobs.event_id)",
                       (now - self.settings.retention_seconds,))

    def inspect(self, now):
        with self.connection() as db:
            row = db.execute("SELECT * FROM context_status").fetchone()
            states = dict(db.execute("SELECT state,count(*) FROM context_jobs GROUP BY state"))
            counts = dict(db.execute("SELECT code,count(*) FROM context_attempts GROUP BY code"))
            requests, succeeded, retried, retrieval, processing = db.execute(
                "SELECT count(CASE WHEN retrieval_ms>0 THEN 1 END),"
                "count(CASE WHEN retrieval_ms>0 AND code='CONTEXT_STORED' THEN 1 END),"
                "count(CASE WHEN attempt>1 THEN 1 END),coalesce(sum(retrieval_ms),0),"
                "coalesce(sum(processing_ms),0) FROM context_attempts").fetchone()
            missing, conflicts = db.execute(
                "SELECT coalesce(sum(json_array_length(document,'$.missing_evidence_ids')),0),"
                "coalesce(sum(json_array_length(document,'$.conflicting_evidence_ids')+"
                "json_extract(document,'$.context_reported_conflict_count')),0) FROM context_packages").fetchone()
            duplicate = db.execute("SELECT value FROM context_counters WHERE name='duplicate_jobs_prevented'").fetchone()
        state = row["state"] if row else "STARTING"
        if state == "RUNNING" and now - row["heartbeat"] > (
            self.settings.poll_interval_seconds + self.settings.timeout_seconds + 5
        ):
            state = "DEGRADED"
        return {
            "enabled": True, "state": state, "ready": state == "RUNNING",
            "error_code": row["error_code"] if row else None, "last_success": row["last_success"] if row else None,
            "jobs": states, "queue_size": sum(states.get(key, 0) for key in
                                             ("PENDING_CONTEXT", "CONTEXT_RETRY_PENDING", "FETCHING_CONTEXT")),
            "context_requests": requests, "retry_count": retried, "retrieval_latency_ms_total": retrieval,
            "processing_latency_ms_total": processing, "attempt_codes": counts,
            "missing_evidence_count": missing, "evidence_conflict_count": conflicts,
            "duplicate_jobs_prevented": duplicate[0] if duplicate else 0,
            "retrieval_successes": succeeded, "retrieval_failures": requests - succeeded,
        }
