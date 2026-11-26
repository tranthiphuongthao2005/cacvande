"""SQLite workflow outbox and durable dispatch/analysis idempotency."""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.context_integration_models import ContextPackage, digest, verified_package
from app.workflow_models import AnalysisResult, build_request, validate_result

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_jobs (
    package_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, trace_version INTEGER NOT NULL,
    job_id TEXT UNIQUE, signature TEXT, state TEXT NOT NULL DEFAULT 'PENDING_DISPATCH',
    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
    claim_token TEXT, lease_until REAL, execution_token TEXT, execution_id TEXT,
    error_code TEXT, created_at REAL NOT NULL, dispatched_at REAL, analysis_started_at REAL,
    analysis_completed_at REAL, persisted_at REAL, accepted_at REAL, superseded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS workflow_jobs_due ON workflow_jobs(state,next_at);
CREATE TABLE IF NOT EXISTS workflow_attempts (
    id INTEGER PRIMARY KEY, package_id TEXT NOT NULL REFERENCES workflow_jobs,
    occurred_at REAL NOT NULL, phase TEXT NOT NULL, code TEXT NOT NULL, latency_ms REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_results (
    job_id TEXT PRIMARY KEY REFERENCES workflow_jobs(job_id), package_id TEXT UNIQUE NOT NULL,
    detection_event_id TEXT NOT NULL, trace_id TEXT NOT NULL, trace_version INTEGER NOT NULL,
    incident_correlation_key TEXT NOT NULL, context_payload_sha256 TEXT NOT NULL,
    response_sha256 TEXT NOT NULL, evidence_event_ids TEXT NOT NULL, validation_status TEXT NOT NULL,
    document TEXT NOT NULL, persisted_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_status (
    id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, heartbeat REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS enqueue_workflow_package AFTER UPDATE OF state ON context_jobs
WHEN NEW.state='READY_FOR_ANALYSIS' AND OLD.state<>NEW.state
BEGIN
    INSERT INTO workflow_jobs(package_id,trace_id,trace_version,created_at)
    SELECT package_id,trace_id,trace_version,unixepoch('now') FROM context_packages WHERE event_id=NEW.event_id
    ON CONFLICT DO NOTHING;
END;
CREATE VIEW IF NOT EXISTS workflow_incident_handoff AS
SELECT r.*, j.execution_id AS workflow_execution_id, j.accepted_at, j.dispatched_at,
       j.analysis_started_at,j.analysis_completed_at,j.attempts AS attempt_count,
       CASE WHEN j.superseded=1 OR q.package_id IS NULL THEN 1 ELSE 0 END AS superseded
FROM workflow_results r JOIN workflow_jobs j ON j.job_id=r.job_id
LEFT JOIN analysis_readiness_queue q ON q.package_id=r.package_id;
"""
OBJECTS = {"workflow_jobs", "workflow_jobs_due", "workflow_attempts", "workflow_results", "workflow_status",
           "enqueue_workflow_package", "workflow_incident_handoff"}


@dataclass(frozen=True)
class Claim:
    package_id: str
    token: str


@dataclass(frozen=True)
class AnalysisClaim:
    token: str
    package: ContextPackage


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.uri = Path(settings.storage_path).absolute().as_uri()

    @contextmanager
    def connect(self, write=False):
        mode = "rw" if write else "ro"
        with closing(sqlite3.connect(f"{self.uri}?mode={mode}", uri=True, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def install(self):
        with closing(sqlite3.connect(f"{self.uri}?mode=rw", uri=True, timeout=2)) as db, db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            if not {"analysis_readiness_queue", "context_settings"} <= names:
                raise ValueError("CONTEXT_STORAGE_REQUIRED")
            if names & OBJECTS and not OBJECTS <= names:
                raise ValueError("INCOMPLETE_WORKFLOW_SCHEMA")
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)

    @staticmethod
    def attempt(db, package, now, phase, code, latency=0):
        db.execute("INSERT INTO workflow_attempts(package_id,occurred_at,phase,code,latency_ms) VALUES(?,?,?,?,?)",
                   (package, now, phase, code, latency))

    @staticmethod
    def ready_row(db, package_id):
        return db.execute("SELECT * FROM analysis_readiness_queue WHERE package_id=?", (package_id,)).fetchone()

    @staticmethod
    def current_request(db, ready):
        package = verified_package(ready["document"])
        if (package.context_package_id, package.trace_id, package.trace_version) != (
            ready["package_id"], ready["trace_id"], ready["trace_version"]
        ) or package.analysis_readiness != "READY_FOR_ANALYSIS" or package.incident_eligibility != "ELIGIBLE" or (
            package.evidence_reconciliation_status != "MATCHED" or package.missing_evidence_ids
            or package.conflicting_evidence_ids or package.context_reported_conflict_count
            or not package.detection_evidence_ids
            or set(package.detection_evidence_ids) != set(package.matched_evidence_ids)
            or not set(package.matched_evidence_ids) <= {event.event_id for event in package.context_payload.events}
        ):
            raise ValueError("INVALID_CONTEXT_PACKAGE_BINDING")
        namespace = db.execute("SELECT namespace FROM context_settings WHERE id=1").fetchone()[0]
        return package, build_request(package, namespace)

    def claims(self, now):
        with self.connect(write=True) as db:
            for row in db.execute("SELECT package_id,state FROM workflow_jobs WHERE lease_until<=? AND "
                                  "state IN ('CLAIMED','DISPATCHING','ANALYZING','WORKFLOW_ACCEPTED')", (now,)).fetchall():
                state = "PENDING_DISPATCH" if row["state"] == "CLAIMED" else "OUTCOME_UNKNOWN"
                db.execute("UPDATE workflow_jobs SET state=?,claim_token=NULL,lease_until=NULL,"
                           "error_code=? WHERE package_id=?", (state, state, row["package_id"]))
                self.attempt(db, row["package_id"], now, "RECOVERY", state)
            db.execute("UPDATE workflow_jobs SET state='SUPERSEDED',superseded=1,claim_token=NULL WHERE "
                       "state IN ('PENDING_DISPATCH','RETRY_PENDING','CLAIMED') AND NOT EXISTS "
                       "(SELECT 1 FROM analysis_readiness_queue q WHERE q.package_id=workflow_jobs.package_id)")
            active = db.execute("SELECT count(*) FROM workflow_jobs WHERE state IN "
                                "('CLAIMED','DISPATCHING','ANALYZING','WORKFLOW_ACCEPTED')").fetchone()[0]
            slots = min(self.settings.batch_size, max(0, self.settings.max_concurrency - active))
            claims = []
            for row in db.execute("SELECT package_id FROM workflow_jobs WHERE state IN "
                                  "('PENDING_DISPATCH','RETRY_PENDING') AND next_at<=? ORDER BY rowid LIMIT ?",
                                  (now, slots)).fetchall():
                token = uuid4().hex
                db.execute("UPDATE workflow_jobs SET state='CLAIMED',claim_token=?,lease_until=? WHERE package_id=?",
                           (token, now + self.settings.timeout_seconds + 30, row["package_id"]))
                claims.append(Claim(row["package_id"], token))
            return claims

    def before_dispatch(self, claim, ready_package, now):
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM workflow_jobs WHERE package_id=? AND state='CLAIMED' AND claim_token=?",
                             (claim.package_id, claim.token)).fetchone()
            if row is None:
                return None
            ready = self.ready_row(db, claim.package_id)
            if ready is None:
                self.reject_claim(db, claim, now, "SUPERSEDED", "PACKAGE_NOT_READY")
                return None
            try:
                package, request = self.current_request(db, ready)
                if ready_package is None or package != ready_package or (
                    package.trace_id, package.trace_version
                ) != (row["trace_id"], row["trace_version"]):
                    raise ValueError("PACKAGE_CHANGED")
                signature = digest(request.model_dump(mode="json"))
                if row["signature"] is not None and row["signature"] != signature:
                    raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
            except ValueError:
                self.reject_claim(db, claim, now, "NEEDS_REVIEW", "CONTEXT_VERIFICATION_FAILED")
                return None
            db.execute("UPDATE workflow_jobs SET job_id=?,signature=?,state='DISPATCHING',attempts=attempts+1,"
                       "dispatched_at=?,lease_until=?,error_code=NULL WHERE package_id=?",
                       (request.analysis_job_id, signature, now, now + self.settings.timeout_seconds + 30,
                        claim.package_id))
            self.attempt(db, claim.package_id, now, "DISPATCH", "STARTED")
            return request

    def reject_claim(self, db, claim, now, state, code):
        db.execute("UPDATE workflow_jobs SET state=?,claim_token=NULL,lease_until=NULL,error_code=?,superseded=? "
                   "WHERE package_id=?", (state, code, int(state == "SUPERSEDED"), claim.package_id))
        self.attempt(db, claim.package_id, now, "VERIFY", code)

    def dispatch_outcome(self, claim, now, status, code, latency, *, safe_retry=False):
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM workflow_jobs WHERE package_id=?",
                             (claim.package_id,)).fetchone()
            self.attempt(db, claim.package_id, now, "WEBHOOK", code, latency)
            if row["state"] != "DISPATCHING" or row["claim_token"] != claim.token:
                return row["state"]
            next_at = 0
            if safe_retry:
                if row["attempts"] <= self.settings.max_retries:
                    status = "RETRY_PENDING"
                    next_at = now + self.settings.retry_backoff_seconds * (2 ** (row["attempts"] - 1))
                else:
                    status = "DISPATCH_FAILED"
            db.execute("UPDATE workflow_jobs SET state=?,next_at=?,error_code=?,claim_token=NULL,lease_until=?,"
                       "accepted_at=CASE WHEN ?='WORKFLOW_ACCEPTED' THEN COALESCE(accepted_at,?) ELSE accepted_at END "
                       "WHERE package_id=?", (status, next_at, code,
                                              now + self.settings.timeout_seconds if status == "WORKFLOW_ACCEPTED" else None,
                                              status, now, claim.package_id))
            return status

    def accept(self, request, execution_id, now):
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM workflow_jobs WHERE job_id=?", (request.analysis_job_id,)).fetchone()
            if row is None or row["signature"] != digest(request.model_dump(mode="json")):
                return 409, "IDEMPOTENCY_KEY_CONFLICT"
            result = db.execute("SELECT document,response_sha256 FROM workflow_results WHERE job_id=?",
                                (row["job_id"],)).fetchone()
            if result is not None:
                value = AnalysisResult.model_validate_json(result["document"])
                validate_result(request, value)
                if digest(value.model_dump(mode="json")) != result["response_sha256"]:
                    raise ValueError("ANALYSIS_RESULT_HASH_MISMATCH")
                self.attempt(db, row["package_id"], now, "DUPLICATE", "REPLAY_RESULT")
                return 200, result["document"]
            if row["state"] in {"NEEDS_REVIEW", "ANALYSIS_FAILED", "SUPERSEDED", "DISPATCH_FAILED"}:
                return 409, row["error_code"] or row["state"]
            if row["analysis_started_at"] is not None:
                self.attempt(db, row["package_id"], now, "DUPLICATE", "ANALYSIS_ALREADY_STARTED")
                return 202, "ANALYSIS_ALREADY_STARTED"
            if row["state"] not in {"DISPATCHING", "OUTCOME_UNKNOWN", "WORKFLOW_ACCEPTED"}:
                return 409, "DISPATCH_NOT_AUTHORIZED"
            ready = self.ready_row(db, request.context_package_id)
            if ready is None:
                db.execute("UPDATE workflow_jobs SET state='SUPERSEDED',superseded=1,error_code='PACKAGE_NOT_READY',"
                           "lease_until=NULL WHERE package_id=?", (row["package_id"],))
                return 409, "PACKAGE_NOT_READY"
            try:
                package, expected = self.current_request(db, ready)
                if expected != request:
                    raise ValueError("PACKAGE_CHANGED")
            except ValueError:
                db.execute("UPDATE workflow_jobs SET state='NEEDS_REVIEW',error_code='CONTEXT_VERIFICATION_FAILED',"
                           "lease_until=NULL WHERE package_id=?", (row["package_id"],))
                return 409, "CONTEXT_VERIFICATION_FAILED"
            token = uuid4().hex
            db.execute("UPDATE workflow_jobs SET state='ANALYZING',execution_token=?,execution_id=?,"
                       "accepted_at=COALESCE(accepted_at,?),analysis_started_at=?,lease_until=? WHERE job_id=?",
                       (token, execution_id, now, now, now + self.settings.timeout_seconds + 30, row["job_id"]))
            self.attempt(db, row["package_id"], now, "ANALYSIS", "STARTED")
            return 201, AnalysisClaim(token, package)

    def finish_analysis(self, request, claim, now, latency, *, output=None, code=None, review=False):
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM workflow_jobs WHERE job_id=? AND execution_token=?",
                             (request.analysis_job_id, claim.token)).fetchone()
            if row is None:
                raise ValueError("STALE_ANALYSIS_CLAIM")
            result = db.execute("SELECT document FROM workflow_results WHERE job_id=?", (row["job_id"],)).fetchone()
            if result is not None:
                return
            if output is not None:
                validate_result(request, output)
                db.execute("INSERT INTO workflow_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    row["job_id"], row["package_id"], claim.package.detection_event_id, row["trace_id"],
                    row["trace_version"], claim.package.incident_correlation_key, request.context_payload_sha256,
                    digest(output.model_dump(mode="json")),
                    json.dumps([item.event_id for item in output.observations]),
                    output.evidence_validation_scope, output.model_dump_json(), now,
                ))
                state = "COMPLETED"
            else:
                state = "NEEDS_REVIEW" if review else "ANALYSIS_FAILED"
            superseded = self.ready_row(db, row["package_id"]) is None
            db.execute("UPDATE workflow_jobs SET state=?,error_code=?,analysis_completed_at=?,persisted_at=?,"
                       "lease_until=NULL,claim_token=NULL,execution_token=NULL,superseded=? WHERE job_id=?",
                       (state, code, now, now, int(superseded), row["job_id"]))
            self.attempt(db, row["package_id"], now, "ANALYSIS", code or "VALIDATED_RESULT", latency)

    def mark(self, state, now):
        with self.connect(write=True) as db:
            db.execute("INSERT INTO workflow_status VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "state=excluded.state, heartbeat=excluded.heartbeat", (state, now))

    def inspect(self, now):
        with self.connect() as db:
            row = db.execute("SELECT state, heartbeat FROM workflow_status WHERE id=1").fetchone()
            states = dict(db.execute("SELECT state,count(*) FROM workflow_jobs GROUP BY state"))
            phases = dict(db.execute("SELECT phase || ':' || code,count(*) FROM workflow_attempts GROUP BY phase,code"))
            latency = dict(db.execute("SELECT phase,sum(latency_ms) FROM workflow_attempts GROUP BY phase"))
            ready = db.execute("SELECT count(*) FROM analysis_readiness_queue").fetchone()[0]
            completed = db.execute("SELECT max(CASE WHEN state='COMPLETED' THEN persisted_at END),"
                                   "sum(CASE WHEN state='COMPLETED' THEN persisted_at-dispatched_at END),"
                                   "count(accepted_at) FROM workflow_jobs").fetchone()
        state = row["state"] if row else "STARTING"
        if state == "RUNNING" and now - row["heartbeat"] > (
            self.settings.poll_interval_seconds + self.settings.timeout_seconds + 5
        ):
            state = "DEGRADED"
        return {"state": state, "ready": state == "RUNNING", "ready_packages": ready, "jobs": states,
                "queue_size": sum(states.get(s, 0) for s in ("PENDING_DISPATCH", "RETRY_PENDING", "CLAIMED")),
                "in_flight": sum(states.get(s, 0) for s in ("DISPATCHING", "WORKFLOW_ACCEPTED", "ANALYZING")),
                "attempts": phases, "latency_ms_total": latency, "last_success": completed[0],
                "end_to_end_seconds_total": completed[1] or 0, "accepted_workflows": completed[2]}
