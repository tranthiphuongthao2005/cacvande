"""Additive incident projection in the existing scenario SQLite database."""

import json
import re
import sqlite3
from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.context_integration_models import digest
from app.incident_models import (
    CONTEXT_STATES, TRANSITIONS, WORKFLOW_STATES, Incident, detection_from, package_from, workflow_from,
)
from app.scenario_incident_store import Ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS managed_incidents (
    id TEXT PRIMARY KEY, correlation TEXT UNIQUE NOT NULL, namespace TEXT NOT NULL, trace_id TEXT NOT NULL,
    trace_version INTEGER NOT NULL, phase_rank INTEGER NOT NULL, created_at REAL NOT NULL,
    last_detected REAL NOT NULL, document TEXT NOT NULL, UNIQUE(namespace,trace_id)
);
CREATE INDEX IF NOT EXISTS managed_incidents_order ON managed_incidents(last_detected DESC,id);
CREATE TABLE IF NOT EXISTS incident_revisions (
    incident_id TEXT NOT NULL REFERENCES managed_incidents, kind TEXT NOT NULL, source_id TEXT NOT NULL,
    trace_version INTEGER NOT NULL, payload_sha256 TEXT NOT NULL, document TEXT NOT NULL,
    PRIMARY KEY(incident_id,kind,source_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS incident_detection_version ON incident_revisions(incident_id,trace_version)
WHERE kind='DETECTION';
CREATE TABLE IF NOT EXISTS incident_timeline (
    id INTEGER PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES managed_incidents, event_key TEXT NOT NULL,
    event TEXT NOT NULL, occurred_at REAL NOT NULL, source TEXT NOT NULL, trace_version INTEGER NOT NULL,
    UNIQUE(incident_id,event_key)
);
CREATE INDEX IF NOT EXISTS incident_timeline_order ON incident_timeline(incident_id,occurred_at,id);
CREATE TABLE IF NOT EXISTS incident_status_history (
    id INTEGER PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES managed_incidents, previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL, actor_id TEXT NOT NULL, reason TEXT NOT NULL, changed_at REAL NOT NULL,
    record_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_receipts (
    source_id TEXT NOT NULL, outbox_id INTEGER NOT NULL, incident_id TEXT, outcome TEXT NOT NULL,
    processed_at REAL NOT NULL, latency_ms REAL NOT NULL, PRIMARY KEY(source_id,outbox_id)
);
CREATE TABLE IF NOT EXISTS incident_metrics (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""

FILTERS = {name: "$." + name for name in (
    "incident_status", "analysis_status", "severity", "detection_source", "analysis_provider", "is_mock",
    "context_completeness", "trace_id", "source_namespace",
)}
MULTI_FILTERS = {"service": ("affected_services", "observed_services"), "anomaly_type": ("anomaly_types",)}


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


def count(db, key):
    db.execute("INSERT INTO incident_metrics VALUES (?,1) ON CONFLICT(name) DO UPDATE SET value=value+1", (key,))


class IncidentStore:
    def __init__(self, path):
        self.path = path
        self.uri = Path(path).absolute().as_uri()

    @contextmanager
    def connect(self, write=False):
        mode = "rw" if write else "ro"
        with closing(sqlite3.connect(f"{self.uri}?mode={mode}", uri=True, timeout=2)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db

    def install(self):
        self.legacy = Ledger(self.path)
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            if not {"request_digest", "signature", "incident_id", "created", "result", "notification"} <= {
                row[1] for row in db.execute("PRAGMA table_info(incidents)")
            }:
                raise ValueError("LEGACY_INCIDENT_SCHEMA_MISMATCH")
            expected = {"managed_incidents", "managed_incidents_order", "incident_revisions",
                        "incident_detection_version", "incident_timeline", "incident_timeline_order",
                        "incident_status_history", "incident_receipts", "incident_metrics"}
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            if names & expected and not expected <= names:
                raise ValueError("INCOMPLETE_INCIDENT_SCHEMA")
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)

    @staticmethod
    def timeline(db, incident, key, label, when, source, version):
        if when is not None:
            db.execute("INSERT INTO incident_timeline(incident_id,event_key,event,occurred_at,source,trace_version) "
                       "VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                       (incident, key + ":" + label, label, when, source, version))

    @staticmethod
    def revision(db, incident, kind, key, version, document):
        signature = digest(document)
        existing = db.execute("SELECT payload_sha256 FROM incident_revisions WHERE incident_id=? AND kind=? "
                              "AND source_id=?", (incident, kind, key)).fetchone()
        if existing:
            if existing["payload_sha256"] != signature:
                raise ValueError("REVISION_CONTENT_CONFLICT")
            return
        db.execute("INSERT INTO incident_revisions VALUES (?,?,?,?,?,?)",
                   (incident, kind, key, version, signature, json.dumps(document)))
        count(db, kind.lower() + "_revisions")

    def initial(self, db, event, namespace, correlation, now):
        identity = uuid4().hex
        data = Incident(
            incident_id=identity, incident_correlation_key=correlation, source_namespace=namespace,
            trace_id=event.trace_id, current_trace_version=event.trace_version,
            incident_status="OPEN", analysis_status="PENDING", severity=event.severity,
            detection_source=event.detection_source, anomaly_types=event.anomaly_types,
            matched_rules=[rule.model_dump(mode="json") for rule in event.matched_rules],
            observed_services=event.observed_services, affected_services=event.affected_services,
            context_completeness=event.context_completeness.upper(), root_cause_verification_status="NOT_ANALYZED",
            analysis_provider=None, is_mock=None, evidence_validation_status="NOT_RUN",
            latest_detection_event_id=event.detection_event_id, latest_context_package_id=None,
            latest_analysis_job_id=None, last_error_code=None, first_detected_at=event.detected_at,
            last_detected_at=event.detected_at, created_at=utc(now), updated_at=utc(now),
            resolved_at=None, closed_at=None, record_version=1,
        )
        db.execute("INSERT INTO managed_incidents VALUES (?,?,?,?,?,?,?,?,?)",
                   (identity, correlation, namespace, event.trace_id, event.trace_version, 0, now,
                    event.detected_at.timestamp(), data.model_dump_json()))
        self.timeline(db, identity, identity, "INCIDENT_CREATED", now, "INCIDENT_PERSISTENCE", event.trace_version)
        count(db, "incidents_created")
        return data

    def ingest(self, row, now, started=None):
        with self.connect(write=True) as db:
            key = (row["source_id"], row["id"])
            if db.execute("SELECT 1 FROM incident_receipts WHERE source_id=? AND outbox_id=?", key).fetchone():
                count(db, "duplicate_handoffs")
                return
            identity, outcome = None, "APPLIED"
            db.execute("SAVEPOINT incident_projection")
            try:
                identity, outcome = self.project(db, row, now)
            except (ValueError, OverflowError, TypeError, KeyError, RecursionError):
                db.execute("ROLLBACK TO incident_projection")
                outcome = "INVALID_HANDOFF"
                count(db, "handoff_failures")
            db.execute("RELEASE incident_projection")
            latency = (perf_counter() - started) * 1000 if started is not None else 0
            db.execute("INSERT INTO incident_receipts VALUES (?,?,?,?,?,?)", (*key, identity, outcome, now, latency))

    def project(self, db, row, now):
        event = detection_from(row)
        namespace = row["namespace"]
        correlation = digest([namespace, event.trace_id])
        stored = db.execute("SELECT * FROM managed_incidents WHERE correlation=? OR (namespace=? AND trace_id=?)",
                            (correlation, namespace, event.trace_id)).fetchone()
        if stored and (stored["namespace"], stored["trace_id"], stored["correlation"]) != (
            namespace, event.trace_id, correlation
        ):
            raise ValueError("CORRELATION_CONFLICT")
        if stored is None and row["phase"] != "DETECTION":
            raise ValueError("MISSING_DETECTION_HANDOFF")
        previous = Incident.model_validate_json(stored["document"]) if stored else self.initial(
            db, event, namespace, correlation, now
        )
        incident = previous.incident_id
        version, detection_id = event.trace_version, event.detection_event_id
        rank = {"DETECTION": 0, "CONTEXT": 1, "WORKFLOW": 2}[row["phase"]]
        prior_rank = stored["phase_rank"] if stored else 0
        anchor = db.execute("SELECT source_id FROM incident_revisions WHERE incident_id=? "
                            "AND kind='DETECTION' AND trace_version=?", (incident, version)).fetchone()
        if row["phase"] == "DETECTION":
            if anchor and anchor["source_id"] != detection_id:
                raise ValueError("DETECTION_VERSION_CONFLICT")
            self.revision(db, incident, "DETECTION", detection_id, version, {
                "detection_event_id": detection_id, "detection_id": event.detection_id,
                "source_payload_sha256": digest(event.model_dump(mode="json")),
                "detected_at": event.detected_at.isoformat(), "persisted_at": event.persisted_at.isoformat(),
                "evidence_event_ids": event.evidence_event_ids, "anomaly_types": event.anomaly_types,
                "matched_rules": [rule.model_dump(mode="json") for rule in event.matched_rules],
                "severity": event.severity, "incident_eligibility": event.incident_eligibility,
                "detection_source": event.detection_source, "context_completeness": event.context_completeness,
            })
            self.timeline(db, incident, detection_id, "ANOMALY_DETECTED", event.detected_at.timestamp(),
                          "DETECTION", version)
            self.timeline(db, incident, detection_id, "DETECTION_PERSISTED", event.persisted_at.timestamp(),
                          "DETECTION_PERSISTENCE", version)
        else:
            if anchor is None or anchor["source_id"] != detection_id:
                raise ValueError("DETECTION_REVISION_MISSING")
        changes = {}
        outcome = "APPLIED"
        handoff_key = f"{row['source_id']}:{row['id']}"
        if version > previous.current_trace_version:
            changes.update(
                current_trace_version=version, severity=event.severity, anomaly_types=event.anomaly_types,
                matched_rules=[rule.model_dump(mode="json") for rule in event.matched_rules],
                observed_services=event.observed_services, affected_services=event.affected_services,
                latest_detection_event_id=detection_id, latest_context_package_id=None, latest_analysis_job_id=None,
                analysis_status="PENDING", context_completeness=event.context_completeness.upper(),
                analysis_provider=None, is_mock=None, evidence_validation_status="NOT_RUN",
                last_error_code=None, proposed_root_cause=None, root_cause_verification_status="NOT_ANALYZED",
            )
            self.timeline(db, incident, detection_id, "DETECTION_REVISION_RECEIVED", now,
                          "INCIDENT_PERSISTENCE", version)
        stage = {}
        try:
            package = package_from(row, event, correlation)
            if package is not None:
                self.context(db, incident, package)
                stage.update(latest_context_package_id=package.context_package_id,
                             context_completeness=package.context_completeness)
            if row["phase"] == "CONTEXT":
                state = row["source_state"]
                stage["analysis_status"] = CONTEXT_STATES[state]
                if state == "FETCHING_CONTEXT":
                    self.timeline(db, incident, handoff_key, "CONTEXT_RETRIEVAL_STARTED",
                                  row["occurred_at"], "CONTEXT", version)
                elif state == "CONTEXT_FAILED":
                    self.timeline(db, incident, detection_id, "CONTEXT_FAILED", row["occurred_at"], "CONTEXT", version)
                    code = row.get("source_error")
                    stage["last_error_code"] = code if code and re.fullmatch(r"[A-Z][A-Z0-9_]{1,70}", code) else (
                        "CONTEXT_FAILED"
                    )
            if row["phase"] == "WORKFLOW":
                workflow, output = workflow_from(row, event, package, correlation)
                stage.update(self.workflow(db, incident, event, workflow, output))
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            outcome = "VALIDATION_FAILED"
            count(db, "handoff_failures")
            count(db, "artifact_validation_failures")
            error = str(exc)
            if error in {"ANALYSIS_RESPONSE_HASH_MISMATCH", "CONTEXT_PAYLOAD_HASH_MISMATCH"}:
                count(db, "hash_validation_failures")
            else:
                error = outcome
            stage.update(analysis_status="NEEDS_REVIEW", evidence_validation_status="FAILED",
                         last_error_code=error, root_cause_verification_status="NEEDS_REVIEW")
            self.timeline(db, incident, handoff_key, "HANDOFF_VALIDATION_FAILED", now,
                          "INCIDENT_VALIDATION", version)
        current = version > previous.current_trace_version or (
            version == previous.current_trace_version and rank >= prior_rank
        )
        if current:
            changes.update(stage)
        changes["first_detected_at"] = min(previous.first_detected_at, event.detected_at)
        changes["last_detected_at"] = max(previous.last_detected_at, event.detected_at)
        updated = previous.model_copy(update=changes)
        if updated != previous:
            updated = updated.model_copy(update={"updated_at": utc(now), "record_version": previous.record_version + 1})
            self.save(db, updated, rank if current else prior_rank)
            count(db, "incidents_updated")
        elif current and rank > prior_rank:
            self.save(db, previous, rank)
        return incident, outcome

    def context(self, db, incident, package):
        key, version = package.context_package_id, package.trace_version
        self.revision(db, incident, "CONTEXT", key, version, {
            "context_package_id": key, "context_payload_sha256": package.context_payload_sha256,
            "context_retrieved_at": package.context_retrieved_at.isoformat(),
            "persisted_at": package.persisted_at.isoformat(), "analysis_readiness": package.analysis_readiness,
            "context_completeness": package.context_completeness,
            "evidence_reconciliation_status": package.evidence_reconciliation_status,
            "missing_evidence_ids": package.missing_evidence_ids, "conflicting_evidence_ids": package.conflicting_evidence_ids,
            "events": [item.model_dump(mode="json") for item in package.context_payload.events],
        })
        self.timeline(db, incident, key, "CONTEXT_PACKAGE_PERSISTED", package.persisted_at.timestamp(),
                      "CONTEXT_PERSISTENCE", version)

    def workflow(self, db, incident, event, item, result):
        key = item.job_id or item.package_id
        version = event.trace_version
        state = WORKFLOW_STATES[item.state]
        changes = {"analysis_status": state, "latest_analysis_job_id": item.job_id, "last_error_code": item.error_code}
        for label, timestamp in (
            ("WORKFLOW_DISPATCHED", item.dispatched_at), ("WORKFLOW_ACCEPTED", item.accepted_at),
            ("ANALYSIS_STARTED", item.analysis_started_at), ("ANALYSIS_COMPLETED", item.analysis_completed_at),
        ):
            self.timeline(db, incident, key, label, timestamp, "WORKFLOW", version)
        if result:
            self.revision(db, incident, "ANALYSIS", key, version, {
                "analysis_job_id": item.job_id, "workflow_execution_id": item.execution_id,
                "analysis_response_sha256": item.response_sha256, "context_payload_sha256": item.context_sha256,
                "workflow_status": item.state, "analysis_completed_at": item.analysis_completed_at,
                "validation_status": item.validation_status, "result": result.model_dump(mode="json"),
            })
            self.timeline(db, incident, key, "EVIDENCE_VALIDATION_COMPLETED", item.persisted_at,
                          "WORKFLOW_PERSISTENCE", version)
            abstained = result.analysis_status == "INSUFFICIENT_EVIDENCE"
            changes.update(analysis_status="INSUFFICIENT_EVIDENCE" if abstained else "ANALYZED",
                           analysis_provider=result.analysis_provider, is_mock=result.is_mock,
                           evidence_validation_status=result.evidence_validation_scope,
                           root_cause_verification_status="INSUFFICIENT_EVIDENCE" if abstained else "NOT_PROPOSED")
        elif state in {"ANALYSIS_FAILED", "NEEDS_REVIEW", "OUTCOME_UNKNOWN"}:
            self.revision(db, incident, "ANALYSIS", key + ":" + item.state, version, {
                "analysis_job_id": item.job_id, "workflow_execution_id": item.execution_id,
                "workflow_status": item.state, "error_code": item.error_code,
                "analysis_completed_at": item.analysis_completed_at,
            })
            self.timeline(db, incident, key, state, item.analysis_completed_at, "WORKFLOW", version)
            if state == "NEEDS_REVIEW":
                changes.update(evidence_validation_status="FAILED", root_cause_verification_status="NEEDS_REVIEW")
        return changes

    @staticmethod
    def save(db, incident, rank):
        db.execute("UPDATE managed_incidents SET trace_version=?,phase_rank=?,last_detected=?,document=? WHERE id=?",
                   (incident.current_trace_version, rank, incident.last_detected_at.timestamp(),
                    incident.model_dump_json(), incident.incident_id))

    def get(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT document FROM managed_incidents WHERE id=?", (identity,)).fetchone()
        return Incident.model_validate_json(row["document"]) if row else None

    def change(self, identity, change, actor, now):
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM managed_incidents WHERE id=?", (identity,)).fetchone()
            if row is None:
                return "INCIDENT_NOT_FOUND", None
            incident = Incident.model_validate_json(row["document"])
            error = None
            if change.expected_version != incident.record_version:
                error = "INCIDENT_VERSION_CONFLICT"
            elif change.status not in TRANSITIONS[incident.incident_status]:
                error = "INVALID_INCIDENT_TRANSITION"
            if error:
                count(db, "status_transition_conflicts")
                return error, None
            values = {"incident_status": change.status, "updated_at": utc(now),
                      "record_version": incident.record_version + 1}
            if change.status == "RESOLVED":
                values["resolved_at"] = utc(now)
            if change.status == "OPEN":
                values["resolved_at"] = None
            if change.status == "CLOSED":
                values["closed_at"] = utc(now)
            updated = incident.model_copy(update=values)
            self.save(db, updated, row["phase_rank"])
            db.execute("INSERT INTO incident_status_history(incident_id,previous_status,new_status,actor_id,reason,"
                       "changed_at,record_version) VALUES(?,?,?,?,?,?,?)",
                       (identity, incident.incident_status, change.status, actor, change.reason, now,
                        updated.record_version))
            self.timeline(db, identity, str(updated.record_version), "INCIDENT_STATUS_UPDATED", now,
                          "OPERATOR", updated.current_trace_version)
            if change.status in {"RESOLVED", "CLOSED"}:
                self.timeline(db, identity, str(updated.record_version), "INCIDENT_" + change.status, now,
                              "OPERATOR", updated.current_trace_version)
            count(db, "incident_status_updates")
            return None, updated

    def list(self, filters, limit, offset):
        condition, values = self.filters(filters)
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM managed_incidents" + condition, values).fetchone()[0]
            rows = db.execute("SELECT document FROM managed_incidents" + condition +
                              " ORDER BY last_detected DESC,id LIMIT ? OFFSET ?", (*values, limit, offset)).fetchall()
        return [Incident.model_validate_json(row[0]) for row in rows], total

    @staticmethod
    def filters(filters):
        clauses, values = [], []
        for name, value in filters.items():
            if value is None:
                continue
            if name in FILTERS:
                clauses.append("json_extract(document,?)=?")
                values.extend((FILTERS[name], value))
            elif name in MULTI_FILTERS:
                options = ["EXISTS (SELECT 1 FROM json_each(document,?) WHERE value=?)" for _ in MULTI_FILTERS[name]]
                clauses.append("(" + " OR ".join(options) + ")")
                for path in MULTI_FILTERS[name]:
                    values.extend(("$." + path, value))
            elif name in {"from_time", "to_time"}:
                clauses.append("created_at>=?" if name == "from_time" else "created_at<?")
                values.append(value.timestamp())
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), values

    def history(self, identity, kind, limit, offset):
        tables = {"timeline": ("incident_timeline", "occurred_at,id"),
                  "history": ("incident_status_history", "changed_at,id"),
                  "revisions": ("incident_revisions", "trace_version,kind,source_id")}
        table, order = tables[kind]
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM {table} WHERE incident_id=? ORDER BY {order} LIMIT ? OFFSET ?",
                              (identity, limit, offset)).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item.pop("event_key", None)
            if "document" in item:
                item["document"] = json.loads(item["document"])
            for field in ("occurred_at", "changed_at"):
                if field in item:
                    item[field] = utc(item[field]).isoformat()
        return result

    def evidence(self, identity, limit, offset):
        with self.connect() as db:
            rows = db.execute("""
                WITH revisions AS (SELECT * FROM incident_revisions WHERE incident_id=?),
                evidence AS (
                    SELECT r.trace_version,r.source_id,'DETECTION' AS role,e.value AS event_id,NULL AS observed,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM revisions c,json_each(c.document,'$.events') ce
                        WHERE c.kind='CONTEXT' AND c.trace_version=r.trace_version
                          AND json_extract(ce.value,'$.event_id')=e.value
                    ) THEN 'AVAILABLE_IN_CONTEXT' ELSE 'CONTEXT_UNAVAILABLE' END AS validation_status
                    FROM revisions r,json_each(r.document,'$.evidence_event_ids') e WHERE r.kind='DETECTION'
                    UNION ALL
                    SELECT r.trace_version,r.source_id,'CONTEXT',json_extract(e.value,'$.event_id'),e.value,
                           CASE WHEN EXISTS (SELECT 1 FROM json_each(r.document,'$.conflicting_evidence_ids') x
                               WHERE x.value=json_extract(e.value,'$.event_id')) THEN 'CONFLICTING' ELSE 'OBSERVED' END
                    FROM revisions r,json_each(r.document,'$.events') e WHERE r.kind='CONTEXT'
                    UNION ALL
                    SELECT r.trace_version,r.source_id,'ANALYSIS',json_extract(e.value,'$.event_id'),e.value,
                           'CONTEXT_ID_AND_OBSERVABLE_FIELDS'
                    FROM revisions r,json_each(r.document,'$.result.observations') e WHERE r.kind='ANALYSIS'
                )
                SELECT * FROM evidence ORDER BY trace_version,role,source_id,event_id LIMIT ? OFFSET ?
            """, (identity, limit, offset)).fetchall()
        return [{**dict(row), "observed": json.loads(row["observed"]) if row["observed"] else None} for row in rows]

    def statistics(self, filters):
        where, args = self.filters(filters)
        with self.connect() as db:
            rows = db.execute("SELECT document FROM managed_incidents" + where, args).fetchall()
            metrics = dict(db.execute("SELECT name,value FROM incident_metrics"))
            receipts = db.execute("SELECT max(CASE WHEN outcome='APPLIED' THEN processed_at END),coalesce(sum(latency_ms),0) "
                                  "FROM incident_receipts").fetchone()
            detection_count = db.execute("SELECT count(*) FROM incident_revisions WHERE kind='DETECTION' AND incident_id IN "
                                         "(SELECT id FROM managed_incidents" + where + ")", args).fetchone()[0]
        documents = [Incident.model_validate_json(row[0]) for row in rows]
        groups = {field: Counter(getattr(i, field) for i in documents if getattr(i, field) is not None)
                  for field in ("incident_status", "analysis_status", "severity", "detection_source", "analysis_provider")}
        durations = [(i.resolved_at - i.created_at).total_seconds() for i in documents
                     if i.resolved_at and i.resolved_at >= i.created_at]
        return {
            "timezone": "UTC", "total_incidents": len(documents), "detection_revision_count": detection_count,
            "groups": groups, "anomaly_types": Counter(a for i in documents for a in set(i.anomaly_types)),
            "affected_services": Counter(s for i in documents for s in set(i.affected_services)),
            "creation_trend": Counter(i.created_at.date().isoformat() for i in documents),
            "mock_count": sum(i.is_mock is True for i in documents), "real_count": sum(i.is_mock is False for i in documents),
            "analysis_failure_count": groups["analysis_status"].get("ANALYSIS_FAILED", 0),
            "needs_review_count": groups["analysis_status"].get("NEEDS_REVIEW", 0),
            "mean_resolution_seconds": sum(durations) / len(durations) if durations else None,
            "metrics": metrics, "last_successful_handoff_at": utc(receipts[0]).isoformat() if receipts[0] else None,
            "processing_latency_ms_total": receipts[1],
        }
