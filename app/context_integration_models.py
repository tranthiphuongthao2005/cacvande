"""Context validation, reconciliation, and a versioned package for analysis handoff."""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from app.contracts import StrictRecord, TraceId
from app.incident_context import ERROR_CODES, IncidentContext, Service
from app.monitoring_models import DetectionEvent
from app.rule_detection import RULES, RuleMatch
from app.trace_store import EVENTS, valid_trace

VERSION = "1.0.0"
QUALITY = {
    "documents_read", "polls", "conflicting_event_ids", "missing_span_id", "timestamp_ties",
    "missing_service_name", "out_of_scope", "unrecognized_error_type", "invalid_documents", "duplicate_documents",
}
WARNINGS = {key.upper() for key in QUALITY} | {
    "TRUNCATED_RESULT", "ELASTICSEARCH_TIMEOUT_OR_INCOMPLETE_SEARCH", "INGESTION_CHANGED_DURING_POLLING",
    "ROOT_SPAN_OR_INGESTION_WATERMARK_UNVERIFIED", "ORDER_COMPLETION_OBSERVED", "DEPENDENCY_LINKS_UNVERIFIED",
}
Readiness = Literal["READY_FOR_ANALYSIS", "NEEDS_MORE_EVIDENCE", "NEEDS_REVIEW"]


class TimelineEntry(StrictRecord):
    timestamp: AwareDatetime
    service_name: Service
    observation: str
    status_code: int | None = Field(strict=True, ge=100, le=599)
    evidence_event_ids: list[TraceId]


class Dependency(StrictRecord):
    source_service: Service
    target_service: Service
    outcome: Literal["failure_reported"]
    caller_status_code: int | None = Field(strict=True, ge=100, le=599)
    evidence_event_ids: list[TraceId]


class ContextPayload(IncidentContext):
    event_count: int = Field(strict=True, ge=0)
    timeline: list[TimelineEntry]
    dependencies: list[Dependency]


class ContextValidationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(payload):
    return hashlib.sha256(canonical(payload)).hexdigest()


def context_payload(raw, trace_id):
    context = ContextPayload.model_validate(raw, strict=False)
    if context.trace_id != trace_id or context.mode != "cross_service" or context.selected_service is not None:
        raise ContextValidationError("CONTEXT_SCOPE_MISMATCH")
    if not set(context.retrieval_warnings) <= WARNINGS or not set(context.data_quality) <= QUALITY:
        raise ContextValidationError("UNEXPECTED_CONTEXT_METADATA")
    if any(type(value) is not int or value < 0 for value in context.data_quality.values()):
        raise ContextValidationError("INVALID_CONTEXT_QUALITY")
    if (any(not isinstance(item.get("timestamp"), str) for item in raw["events"] + raw["timeline"])
            or any(raw[key] is not None and not isinstance(raw[key], str) for key in ("start_time", "end_time"))):
        raise ContextValidationError("INVALID_CONTEXT_TIMESTAMP")
    events = {}
    for event in context.events:
        if not valid_trace(event.event_id) or event.trace_id != trace_id:
            raise ContextValidationError("INVALID_CONTEXT_EVENT_IDENTITY")
        if event.message not in EVENTS or (event.error_type is not None and event.error_type not in ERROR_CODES):
            raise ContextValidationError("UNEXPECTED_EVENT_CONTENT")
        if event.event_id in events:
            code = "DUPLICATE_CONTEXT_EVENT" if event == events[event.event_id] else "CONFLICTING_CONTEXT_EVENT"
            raise ContextValidationError(code)
        events[event.event_id] = event
    timestamps = [event.timestamp for event in context.events]
    if (context.event_count != len(events) or len(context.evidence_event_ids) != len(events)
            or set(context.evidence_event_ids) != events.keys()
            or sorted(context.services) != sorted({event.service_name for event in events.values()})
            or context.start_time != min(timestamps, default=None) or context.end_time != max(timestamps, default=None)):
        raise ContextValidationError("INVALID_CONTEXT_SUMMARY")
    projected = {}
    for entry in context.timeline:
        if len(entry.evidence_event_ids) != 1:
            raise ContextValidationError("INVALID_TIMELINE_REFERENCE")
        key, = entry.evidence_event_ids
        event = events.get(key)
        if event is None or key in projected or (
            entry.timestamp, entry.service_name, entry.observation, entry.status_code
        ) != (event.timestamp, event.service_name, event.message, event.status_code):
            raise ContextValidationError("INVALID_TIMELINE_REFERENCE")
        projected[key] = entry
    if projected.keys() != events.keys():
        raise ContextValidationError("INVALID_TIMELINE_REFERENCE")
    dependencies = {
        event.event_id: (event.service_name, event.dependency_service, event.status_code)
        for event in events.values() if event.dependency_service and event.message == "dependency_attempt_failed"
    }
    if len(context.dependencies) != len(dependencies):
        raise ContextValidationError("INVALID_DEPENDENCY_REFERENCE")
    for edge in context.dependencies:
        if len(edge.evidence_event_ids) != 1 or dependencies.pop(edge.evidence_event_ids[0], None) != (
            edge.source_service, edge.target_service, edge.caller_status_code
        ):
            raise ContextValidationError("INVALID_DEPENDENCY_REFERENCE")
    return context


def gate(event):
    if event.detection_status != "ANOMALY" or event.is_anomaly is not True:
        return "DETECTION_" + event.detection_status
    if event.incident_eligibility not in {"ELIGIBLE", "NEEDS_MORE_EVIDENCE"}:
        return event.incident_eligibility
    return None


class ContextPackage(StrictRecord):
    context_package_id: str
    idempotency_key: str
    detection_event_id: str
    detection_id: str
    trace_id: TraceId
    trace_version: int
    incident_correlation_key: str
    context_mode: Literal["cross_service"] = "cross_service"
    context_schema_version: Literal["incident-context-v1"] = "incident-context-v1"
    processing_version: Literal["1.0.0"] = VERSION
    detection_source: Literal["rule_based"]
    detection_status: Literal["ANOMALY"]
    anomaly_types: list[str]
    matched_rules: list[RuleMatch]
    severity: Literal["medium", "high", "critical"] | None
    incident_eligibility: Literal["ELIGIBLE", "NEEDS_MORE_EVIDENCE"]
    eligibility_reason: str
    observed_services: list[Service]
    affected_services: list[Service]
    monitoring_observed_event_ids: list[TraceId]
    detection_evidence_ids: list[TraceId]
    context_event_ids: list[TraceId]
    matched_evidence_ids: list[TraceId]
    missing_evidence_ids: list[TraceId]
    conflicting_evidence_ids: list[TraceId]
    context_reported_conflict_count: int = Field(ge=0)
    additional_context_event_ids: list[TraceId]
    evidence_reconciliation_status: Literal["MATCHED", "PARTIAL_MATCH", "MISSING_EVIDENCE", "CONFLICTING_EVIDENCE"]
    context_completeness: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    context_payload: ContextPayload
    context_payload_sha256: str
    detection_timestamp: AwareDatetime
    context_retrieved_at: AwareDatetime
    persisted_at: AwareDatetime
    analysis_readiness: Readiness
    readiness_reason: str
    retry_count: int
    last_error_code: str | None = None
    supersedes_package_id: str | None = None


def validate_detection(event: DetectionEvent):
    keys = (event.detection_event_id, event.idempotency_key)
    if (any(len(key) != 64 or any(c not in "0123456789abcdef" for c in key) for key in keys)
            or keys[0] != keys[1] or not valid_trace(event.trace_id) or event.trace_version < 1):
        raise ValueError("Invalid detection event identity")
    if gate(event):
        return
    evidence = set(event.evidence_event_ids)
    if (event.detection_source != "rule_based" or event.model_score is not None or not valid_trace(event.detection_id)
            or not evidence or any(not valid_trace(key) for key in evidence)
            or evidence != {key for rule in event.matched_rules for key in rule.evidence_event_ids}
            or any(RULES.get(rule.rule_id) != rule.anomaly_type for rule in event.matched_rules)
            or event.anomaly_types != [rule.anomaly_type for rule in event.matched_rules]
            or any(not valid_trace(key) for key in event.worker_observed_event_ids)
            or not set(event.observed_services + event.affected_services) <= {"user", "product", "order"}
            or event.eligibility_reason not in {
                "OBSERVED_HTTP_5XX_COMPLETION", "EVIDENCE_NOT_RECONCILED", "REQUEST_IMPACT_NOT_CONFIRMED"
            }):
        raise ValueError("Invalid detection evidence")


def compare_event(event, observed):
    if observed is None:
        return True
    expected = event.model_dump(exclude={"timestamp", "error_type"})
    return (datetime.fromisoformat(observed["timestamp"]) != event.timestamp
            or any(observed[key] != value for key, value in expected.items())
            or (observed["error_type"] if observed["error_type"] in ERROR_CODES else None) != event.error_type)


def build_package(event, context, claim, observed, namespace, retrieved_at, persisted_at, predecessor=None):
    evidence = set(event.evidence_event_ids)
    by_id = {item.event_id: item for item in context.events}
    matched, missing = evidence & by_id.keys(), evidence - by_id.keys()
    conflicts = set(event.conflicting_evidence_event_ids) & evidence
    conflicts.update(key for key in matched & observed.keys() if compare_event(by_id[key], observed[key]))
    count = context.data_quality.get("conflicting_event_ids", 0)
    if "CONFLICTING_EVENT_IDS" in context.retrieval_warnings:
        count = max(1, count)
    matched -= conflicts
    reconciliation = ("CONFLICTING_EVIDENCE" if conflicts or count else
                      ("PARTIAL_MATCH" if matched else "MISSING_EVIDENCE") if missing else "MATCHED")
    if conflicts or count:
        readiness, reason = "NEEDS_REVIEW", "EVIDENCE_CONFLICT"
    elif missing:
        readiness, reason = "NEEDS_MORE_EVIDENCE", "DETECTION_EVIDENCE_MISSING"
    elif event.incident_eligibility != "ELIGIBLE":
        readiness, reason = "NEEDS_MORE_EVIDENCE", "ELIGIBILITY_REQUIRES_REVIEW"
    elif ({"TRUNCATED_RESULT", "ELASTICSEARCH_TIMEOUT_OR_INCOMPLETE_SEARCH", "INVALID_DOCUMENTS"}
          & set(context.retrieval_warnings) or context.data_quality.get("invalid_documents", 0)):
        readiness, reason = "NEEDS_REVIEW", "CONTEXT_QUALITY_DEGRADED"
    else:
        readiness = "READY_FOR_ANALYSIS"
        reason = ("EVIDENCE_RECONCILED" if context.completeness_status == "COMPLETE"
                  else "EVIDENCE_RECONCILED_LIMITED_CONTEXT")
    identity = hashlib.sha256(f"context:{VERSION}:{event.detection_event_id}".encode()).hexdigest()
    correlation = hashlib.sha256(canonical([namespace, event.trace_id])).hexdigest()
    return ContextPackage(
        context_package_id=identity, idempotency_key=identity, detection_event_id=event.detection_event_id,
        detection_id=event.detection_id, trace_id=event.trace_id, trace_version=event.trace_version,
        incident_correlation_key=correlation, detection_source=event.detection_source, detection_status="ANOMALY",
        anomaly_types=event.anomaly_types, matched_rules=event.matched_rules, severity=event.severity,
        incident_eligibility=event.incident_eligibility, eligibility_reason=event.eligibility_reason,
        observed_services=event.observed_services, affected_services=event.affected_services,
        monitoring_observed_event_ids=event.worker_observed_event_ids,
        detection_evidence_ids=sorted(evidence), context_event_ids=sorted(by_id), matched_evidence_ids=sorted(matched),
        missing_evidence_ids=sorted(missing), conflicting_evidence_ids=sorted(conflicts),
        context_reported_conflict_count=count, additional_context_event_ids=sorted(by_id.keys() - evidence),
        evidence_reconciliation_status=reconciliation, context_completeness=context.completeness_status,
        context_payload=context, context_payload_sha256=digest(context.model_dump(mode="json")),
        detection_timestamp=event.detected_at, context_retrieved_at=retrieved_at, persisted_at=persisted_at,
        analysis_readiness=readiness, readiness_reason=reason, retry_count=claim.attempt - 1,
        last_error_code=claim.last_error, supersedes_package_id=predecessor,
    )


def verified_package(raw):
    package = ContextPackage.model_validate_json(raw)
    payload = package.context_payload.model_dump(mode="json")
    if digest(payload) != package.context_payload_sha256:
        raise ContextValidationError("CONTEXT_PAYLOAD_HASH_MISMATCH")
    context_payload(payload, package.trace_id)
    return package
