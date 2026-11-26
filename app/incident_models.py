"""Validate upstream lineage and define the internal incident API contract."""

import hashlib
import json
import re
from typing import Literal

from pydantic import AwareDatetime, Field, FiniteFloat

from app.context_integration_models import VERSION as CONTEXT_VERSION, digest, validate_detection, verified_package
from app.contracts import StrictRecord, TraceId
from app.monitoring_models import DetectionEvent
from app.workflow_models import AnalysisResult, HexDigest, build_request, validate_result

Lifecycle = Literal["OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"]
AnalysisState = Literal["PENDING", "ANALYZING", "ANALYZED", "NEEDS_REVIEW", "ANALYSIS_FAILED",
                        "INSUFFICIENT_EVIDENCE", "OUTCOME_UNKNOWN"]
TRANSITIONS = {"OPEN": {"INVESTIGATING", "RESOLVED"}, "INVESTIGATING": {"RESOLVED"},
               "RESOLVED": {"CLOSED", "OPEN"}, "CLOSED": set()}
WORKFLOW_STATES = {
    "CLAIMED": "PENDING", "PENDING_DISPATCH": "PENDING", "RETRY_PENDING": "PENDING",
    "DISPATCHING": "ANALYZING", "WORKFLOW_ACCEPTED": "ANALYZING", "ANALYZING": "ANALYZING",
    "NEEDS_REVIEW": "NEEDS_REVIEW", "ANALYSIS_FAILED": "ANALYSIS_FAILED", "DISPATCH_FAILED": "ANALYSIS_FAILED",
    "OUTCOME_UNKNOWN": "OUTCOME_UNKNOWN", "SUPERSEDED": "PENDING", "COMPLETED": "ANALYZED",
}
CONTEXT_STATES = {
    "FETCHING_CONTEXT": "PENDING", "CONTEXT_RETRY_PENDING": "PENDING", "READY_FOR_ANALYSIS": "PENDING",
    "NEEDS_MORE_EVIDENCE": "NEEDS_REVIEW", "NEEDS_REVIEW": "NEEDS_REVIEW",
    "CONTEXT_FAILED": "ANALYSIS_FAILED", "SUPERSEDED": "PENDING",
    "PENDING_CONTEXT": "PENDING", "SKIPPED_NOT_ELIGIBLE": "PENDING",
}


class StatusChange(StrictRecord):
    status: Lifecycle
    reason: str = Field(min_length=3, max_length=500, pattern=r"^\S(?:.*\S)?$")
    expected_version: int = Field(ge=1, strict=True)


class Incident(StrictRecord):
    incident_id: str
    incident_correlation_key: HexDigest
    source_namespace: str
    trace_id: TraceId
    current_trace_version: int
    incident_status: Lifecycle
    analysis_status: AnalysisState
    severity: Literal["medium", "high", "critical"] | None
    detection_source: Literal["rule_based"]
    anomaly_types: list[str]
    matched_rules: list[dict]
    observed_services: list[str]
    affected_services: list[str]
    context_completeness: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    proposed_root_cause: str | None = None
    root_cause_verification_status: Literal["NOT_ANALYZED", "NOT_PROPOSED", "INSUFFICIENT_EVIDENCE", "NEEDS_REVIEW"]
    analysis_provider: Literal["mock"] | None
    is_mock: bool | None
    evidence_validation_status: str
    latest_detection_event_id: HexDigest
    latest_context_package_id: HexDigest | None
    latest_analysis_job_id: HexDigest | None
    last_error_code: str | None
    first_detected_at: AwareDatetime
    last_detected_at: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime
    resolved_at: AwareDatetime | None
    closed_at: AwareDatetime | None
    record_version: int


class IncidentPage(StrictRecord):
    items: list[Incident]
    total: int
    limit: int
    offset: int


class WorkflowSnapshot(StrictRecord):
    job_id: HexDigest | None
    package_id: HexDigest
    detection_event_id: HexDigest
    trace_id: TraceId
    trace_version: int
    state: str
    execution_id: str | None
    dispatched_at: FiniteFloat | None
    accepted_at: FiniteFloat | None
    analysis_started_at: FiniteFloat | None
    analysis_completed_at: FiniteFloat | None
    persisted_at: FiniteFloat | None
    error_code: str | None
    superseded: Literal[0, 1]
    response_sha256: HexDigest | None
    response: str | None
    correlation: HexDigest | None
    context_sha256: HexDigest | None
    validation_status: str | None
    evidence_event_ids: str | None
    result_detection_event_id: HexDigest | None


def detection_from(row):
    event = DetectionEvent.model_validate_json(row["detection"])
    validate_detection(event)
    if (event.detection_status != "ANOMALY" or event.is_anomaly is not True or event.incident_eligibility != "ELIGIBLE"
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", row["namespace"])
            or (event.trace_id, event.trace_version, event.detection_event_id)
            != (row["trace_id"], row["trace_version"], row["detection_event_id"])):
        raise ValueError("INVALID_DETECTION_HANDOFF")
    return event


def package_from(row, event, correlation):
    if row["context_package"] is None:
        return None
    package = verified_package(row["context_package"])
    ids = {item.event_id for item in package.context_payload.events}
    evidence = set(event.evidence_event_ids)
    expected_id = hashlib.sha256(f"context:{CONTEXT_VERSION}:{event.detection_event_id}".encode()).hexdigest()
    if ((package.trace_id, package.trace_version, package.detection_event_id, package.detection_id,
         package.incident_correlation_key, package.incident_eligibility, set(package.detection_evidence_ids)) !=
        (event.trace_id, event.trace_version, event.detection_event_id, event.detection_id,
         correlation, "ELIGIBLE", evidence)
        or set(package.context_event_ids) != ids
        or set(package.missing_evidence_ids) != evidence - ids
        or set(package.additional_context_event_ids) != ids - evidence
        or set(package.matched_evidence_ids) != (evidence & ids) - set(package.conflicting_evidence_ids)
        or package.context_package_id != expected_id or package.idempotency_key != expected_id
        or package.context_completeness != package.context_payload.completeness_status):
        raise ValueError("CONTEXT_BINDING_MISMATCH")
    return package


def workflow_from(row, event, package, correlation):
    item = WorkflowSnapshot.model_validate_json(row["workflow"])
    if (package is None or (item.trace_id, item.trace_version, item.detection_event_id, item.package_id)
            != (event.trace_id, event.trace_version, event.detection_event_id, package.context_package_id)
            or item.state != row["source_state"] or item.state not in WORKFLOW_STATES
            or (item.execution_id is not None and not re.fullmatch(r"[0-9]{1,32}", item.execution_id))
            or (item.error_code is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]{1,70}", item.error_code))):
        raise ValueError("WORKFLOW_BINDING_MISMATCH")
    envelope = build_request(package, row["namespace"])
    if item.job_id is not None and item.job_id != envelope.analysis_job_id:
        raise ValueError("ANALYSIS_JOB_MISMATCH")
    if item.state != "COMPLETED":
        if item.response is not None:
            raise ValueError("WORKFLOW_RESULT_NOT_COMMITTED")
        return item, None
    if (not item.response or item.job_id is None or item.persisted_at is None or item.analysis_completed_at is None
            or item.context_sha256 != envelope.context_payload_sha256 or item.correlation != correlation
            or item.validation_status != "CONTEXT_ID_AND_OBSERVABLE_FIELDS"
            or item.result_detection_event_id != event.detection_event_id):
        raise ValueError("INVALID_COMMITTED_HANDOFF")
    output = AnalysisResult.model_validate_json(item.response)
    if (digest(output.model_dump(mode="json")) != item.response_sha256
            or digest(json.loads(item.response)) != item.response_sha256):
        raise ValueError("ANALYSIS_RESPONSE_HASH_MISMATCH")
    validate_result(envelope, output)
    if json.loads(item.evidence_event_ids or "null") != [obs.event_id for obs in output.observations]:
        raise ValueError("ANALYSIS_EVIDENCE_MISMATCH")
    return item, output
