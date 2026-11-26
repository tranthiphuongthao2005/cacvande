"""Persisted detection contract and incident triage metadata."""

import hashlib
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime

from app.contracts import TraceId
from app.hybrid_detection import HybridResult


class DetectionEvent(HybridResult):
    detection_event_id: str
    idempotency_key: str
    trace_version: int
    worker_observed_event_ids: list[TraceId]
    worker_observed_services: list[str]
    unobserved_evidence_event_ids: list[TraceId]
    conflicting_evidence_event_ids: list[TraceId]
    incident_eligibility: Literal["ELIGIBLE", "RECOVERED_SIGNAL", "NEEDS_MORE_EVIDENCE", "NOT_ELIGIBLE"]
    eligibility_reason: str
    detected_at: AwareDatetime
    persisted_at: AwareDatetime


def eligibility(result, observed, unobserved, conflicts):
    if result.detection_status == "INSUFFICIENT_DATA":
        return "NEEDS_MORE_EVIDENCE", "INSUFFICIENT_DATA"
    if result.detection_status != "ANOMALY":
        return "NOT_ELIGIBLE", result.detection_status
    if unobserved or conflicts:
        return "NEEDS_MORE_EVIDENCE", "EVIDENCE_NOT_RECONCILED"
    ids_by_rule = {row.rule_id: row.evidence_event_ids for row in result.matched_rules}
    if "R01" in ids_by_rule and any(
        observed[key]["message"] == "request_completed" and 500 <= (observed[key]["status_code"] or 0) <= 599
        for key in ids_by_rule["R01"]
    ):
        return "ELIGIBLE", "OBSERVED_HTTP_5XX_COMPLETION"
    if set(ids_by_rule) == {"R02"}:
        completed = [event for event in observed.values() if event and event["message"] == "request_completed"
                     and 200 <= (event["status_code"] or 0) < 300 and event["request_id"]]
        timeouts = [observed[key] for key in ids_by_rule["R02"]]
        if all(event["message"] == "dependency_attempt_failed" and any(
            terminal["service_name"] == event["service_name"] and terminal["request_id"] == event["request_id"]
            and datetime.fromisoformat(terminal["timestamp"]) > datetime.fromisoformat(event["timestamp"])
            for terminal in completed
        ) for event in timeouts):
            return "RECOVERED_SIGNAL", "SAME_REQUEST_LATER_SUCCEEDED"
    return "NEEDS_MORE_EVIDENCE", "REQUEST_IMPACT_NOT_CONFIRMED"


def make_event(result: HybridResult, claim, now):
    evidence = set(result.evidence_event_ids)
    unobserved = sorted(evidence - claim.observed.keys())
    conflicts = sorted(key for key in evidence & claim.observed.keys() if claim.observed[key] is None)
    eligible, reason = eligibility(result, claim.observed, unobserved, conflicts)
    identity = hashlib.sha256(f"monitoring:v1:{claim.trace_id}:{claim.version}".encode()).hexdigest()
    return DetectionEvent(
        **result.model_dump(), detection_event_id=identity, idempotency_key=identity, trace_version=claim.version,
        worker_observed_event_ids=sorted(claim.observed),
        worker_observed_services=sorted({e["service_name"] for e in claim.observed.values() if e}),
        unobserved_evidence_event_ids=unobserved, conflicting_evidence_event_ids=conflicts,
        incident_eligibility=eligible, eligibility_reason=reason, detected_at=result.detection_timestamp,
        persisted_at=datetime.fromtimestamp(now, timezone.utc),
    )
