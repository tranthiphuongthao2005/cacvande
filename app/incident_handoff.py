"""Capture new upstream state changes and deliver them across the SQLite boundary."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from time import perf_counter, time
from uuid import uuid4

FILTER = """
json_extract({doc},'$.detection_status')='ANOMALY'
AND json_extract({doc},'$.is_anomaly')=1
AND json_extract({doc},'$.incident_eligibility')='ELIGIBLE'
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS incident_outbox_source (
    id INTEGER PRIMARY KEY CHECK(id=1), source_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT, namespace TEXT NOT NULL, trace_id TEXT NOT NULL,
    trace_version INTEGER NOT NULL, detection_event_id TEXT NOT NULL, phase TEXT NOT NULL,
    source_state TEXT NOT NULL, occurred_at REAL NOT NULL, detection TEXT NOT NULL,
    context_package TEXT, workflow TEXT, source_error TEXT, outcome TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
    claim_token TEXT, lease_until REAL, error_code TEXT
);
CREATE INDEX IF NOT EXISTS incident_outbox_pending ON incident_outbox(outcome,id);
CREATE TRIGGER IF NOT EXISTS incident_enqueue_detection AFTER INSERT ON results
WHEN {detection_filter}
BEGIN
    INSERT INTO incident_outbox(namespace,trace_id,trace_version,detection_event_id,phase,source_state,occurred_at,detection)
    SELECT namespace,NEW.trace_id,NEW.trace_version,NEW.idempotency_key,'DETECTION','ANOMALY',
           unixepoch('now'),NEW.document FROM context_settings WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS incident_enqueue_context AFTER UPDATE OF state ON context_jobs
WHEN OLD.state<>NEW.state AND {context_filter}
BEGIN
    INSERT INTO incident_outbox(namespace,trace_id,trace_version,detection_event_id,phase,source_state,occurred_at,
                                detection,context_package,source_error)
    SELECT s.namespace,NEW.trace_id,NEW.trace_version,NEW.event_id,'CONTEXT',NEW.state,NEW.updated_at,
           NEW.document,p.document,NEW.last_error FROM context_settings s
    LEFT JOIN context_packages p ON p.event_id=NEW.event_id WHERE s.id=1 AND EXISTS (
        SELECT 1 FROM incident_outbox i WHERE i.detection_event_id=NEW.event_id AND i.phase='DETECTION');
END;
CREATE TRIGGER IF NOT EXISTS incident_enqueue_workflow AFTER UPDATE OF state ON workflow_jobs
WHEN OLD.state<>NEW.state
BEGIN
    INSERT INTO incident_outbox(namespace,trace_id,trace_version,detection_event_id,phase,source_state,occurred_at,
                                detection,context_package,workflow)
    SELECT s.namespace,c.trace_id,c.trace_version,c.event_id,'WORKFLOW',NEW.state,
           unixepoch('now'),c.document,p.document,
           json_object('job_id',NEW.job_id,'package_id',NEW.package_id,'detection_event_id',c.event_id,
             'trace_id',NEW.trace_id,'trace_version',NEW.trace_version,'state',NEW.state,
             'execution_id',NEW.execution_id,'dispatched_at',NEW.dispatched_at,'accepted_at',NEW.accepted_at,
             'analysis_started_at',NEW.analysis_started_at,'analysis_completed_at',NEW.analysis_completed_at,
             'persisted_at',NEW.persisted_at,'error_code',NEW.error_code,'superseded',NEW.superseded,
             'response_sha256',h.response_sha256,'response',h.document,'correlation',h.incident_correlation_key,
             'context_sha256',h.context_payload_sha256,'validation_status',h.validation_status,
             'evidence_event_ids',h.evidence_event_ids,'result_detection_event_id',h.detection_event_id)
    FROM context_packages p JOIN context_jobs c ON c.event_id=p.event_id JOIN context_settings s ON s.id=1
    LEFT JOIN workflow_incident_handoff h ON h.job_id=NEW.job_id
    WHERE p.package_id=NEW.package_id AND {workflow_filter} AND EXISTS (
        SELECT 1 FROM incident_outbox i WHERE i.detection_event_id=c.event_id AND i.phase='DETECTION');
END;
""".format(detection_filter=FILTER.format(doc="NEW.document"), context_filter=FILTER.format(doc="NEW.document"),
           workflow_filter=FILTER.format(doc="c.document"))


class Source:
    def __init__(self, settings):
        self.settings = settings
        self.uri = Path(settings.source_storage_path).absolute().as_uri()

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.uri + "?mode=rw", uri=True, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            yield db

    def install(self):
        with closing(sqlite3.connect(self.uri + "?mode=rw", uri=True, timeout=2)) as db, db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            if not {"results", "context_jobs", "context_settings", "context_packages",
                    "workflow_jobs", "workflow_incident_handoff"} <= names:
                raise ValueError("UPSTREAM_SCHEMA_REQUIRED")
            expected = {"incident_outbox", "incident_outbox_source", "incident_outbox_pending",
                        "incident_enqueue_detection", "incident_enqueue_context", "incident_enqueue_workflow"}
            if names & expected and not expected <= names:
                raise ValueError("INCOMPLETE_INCIDENT_OUTBOX")
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
            db.execute("INSERT OR IGNORE INTO incident_outbox_source VALUES (1,?)", (uuid4().hex,))

    def claim(self, now):
        with self.connect() as db:
            row = db.execute("SELECT * FROM incident_outbox WHERE outcome IN ('PENDING','CLAIMED') "
                             "ORDER BY id LIMIT 1").fetchone()
            if not row or row["next_at"] > now or (row["lease_until"] or 0) > now:
                return None
            token = uuid4().hex
            db.execute("UPDATE incident_outbox SET outcome='CLAIMED',claim_token=?,lease_until=? WHERE id=?",
                       (token, now + 30, row["id"]))
            source_id = db.execute("SELECT source_id FROM incident_outbox_source WHERE id=1").fetchone()[0]
            return {**dict(row), "claim_token": token, "source_id": source_id}

    def finish(self, row, now, *, retry=False):
        attempts = row["attempts"] + int(retry)
        exhausted = retry and attempts > self.settings.max_retries
        next_at = now + self.settings.retry_backoff_seconds * (2 ** max(0, attempts - 1)) if retry else 0
        with self.connect() as db:
            db.execute("UPDATE incident_outbox SET outcome=?,attempts=?,next_at=?,claim_token=NULL,lease_until=NULL,"
                       "error_code=? WHERE id=? AND claim_token=?",
                       ("FAILED" if exhausted else "PENDING" if retry else "DELIVERED", attempts, next_at,
                        "INCIDENT_STORAGE_UNAVAILABLE" if retry else None, row["id"], row["claim_token"]))

    def counts(self):
        with self.connect() as db:
            states = dict(db.execute("SELECT outcome,count(*) FROM incident_outbox GROUP BY outcome"))
            retries = db.execute("SELECT COALESCE(sum(attempts),0) FROM incident_outbox").fetchone()[0]
        return {"states": states, "pending_handoffs": states.get("PENDING", 0) + states.get("CLAIMED", 0),
                "destination_database_errors": retries}


class Worker:
    def __init__(self, settings, source, store, *, clock=time):
        self.settings, self.source, self.store, self.clock = settings, source, store, clock
        self.last_error = None

    def tick(self):
        completed = 0
        if not self.settings.handoff_enabled:
            return completed
        for _ in range(self.settings.batch_size):
            started = perf_counter()
            row = self.source.claim(self.clock())
            if row is None:
                break
            try:
                self.store.ingest(row, self.clock(), started)
            except sqlite3.Error:
                self.last_error = "INCIDENT_STORAGE_UNAVAILABLE"
                self.source.finish(row, self.clock(), retry=True)
                break
            self.last_error = None
            self.source.finish(row, self.clock())
            completed += 1
        return completed
