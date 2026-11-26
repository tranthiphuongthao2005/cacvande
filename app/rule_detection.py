"""Versioned detection over allowlisted application telemetry."""

from datetime import datetime, timezone
from time import perf_counter
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, ValidationError

from app.contracts import SpanId, StrictRecord, TraceId
from app.context_store import Snapshot
from app.trace_store import SERVICES

RULE_VERSION = "1.0.0"
RULES = {
    "R01": "HTTP_SERVER_ERROR",
    "R02": "REQUEST_TIMEOUT",
    "R03": "DATABASE_FAILURE",
    "R04": "PROCESSING_FAILURE",
    "R05": "DEPENDENCY_UNAVAILABLE",
    "R06": "RETRY_EXHAUSTED",
    "R07": "CASCADE_FAILURE",
    "R08": "ERROR_EVENT",
}
DEPENDENCY_EVENTS = {"dependency_attempt_failed", "dependency_exhausted"}


class TelemetryEvent(StrictRecord):
    event_id: TraceId
    trace_id: TraceId
    timestamp: AwareDatetime = Field(alias="@timestamp")
    service_name: Literal["user", "product", "order"]
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    message: str = Field(min_length=1, max_length=256)
    status_code: int | None = Field(default=None, strict=True, ge=100, le=599)
    span_id: SpanId | None = None
    request_id: SpanId | None = None
    dependency_service: str | None = None
    error_type: str | None = None
    endpoint: str | None = None
    http_method: str | None = None


class RuleMatch(StrictRecord):
    rule_id: str
    anomaly_type: str
    evidence_event_ids: list[TraceId]


class DetectionResult(StrictRecord):
    detection_id: str
    trace_id: TraceId
    detection_source: Literal["rule_based"] = "rule_based"
    detection_status: Literal["ANOMALY", "NO_ANOMALY_DETECTED", "INSUFFICIENT_DATA", "DETECTION_ERROR"]
    is_anomaly: bool | None
    matched_rules: list[RuleMatch] = Field(default_factory=list)
    anomaly_types: list[str] = Field(default_factory=list)
    severity: Literal["medium", "high", "critical"] | None = None
    observed_services: list[str] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    evidence_event_ids: list[TraceId] = Field(default_factory=list)
    context_completeness: Literal["partial", "unknown"] = "unknown"
    detection_timestamp: AwareDatetime
    latency_ms: float
    rule_version: str = RULE_VERSION
    model_score: None = None
    diagnostics: list[str] = Field(default_factory=list)


def result(trace_id, started, status, **fields):
    decision = {"ANOMALY": True, "NO_ANOMALY_DETECTED": False}.get(status)
    return DetectionResult(
        detection_id=uuid4().hex, trace_id=trace_id, detection_status=status,
        is_anomaly=decision, detection_timestamp=datetime.now(timezone.utc),
        latency_ms=round((perf_counter() - started) * 1000, 3), **fields,
    )


def normalize(rows, trace_id):
    by_id, conflicts = {}, set()
    invalid = False
    for row in rows:
        if not isinstance(row, dict):
            invalid = True
            continue
        try:
            fields = {key: row[key] for key in TelemetryEvent.model_fields if key in row and key != "timestamp"}
            fields["@timestamp"] = row.get("@timestamp")
            event = TelemetryEvent.model_validate(fields)
            if event.trace_id != trace_id or event.event_id == "0" * 32:
                raise ValueError("Invalid evidence identity")
        except (ValidationError, ValueError):
            invalid = True
            # A malformed copy makes this ID unsafe even if another copy validates.
            event_id = row.get("event_id")
            if isinstance(event_id, str):
                conflicts.add(event_id)
            continue
        previous = by_id.setdefault(event.event_id, event)
        if previous != event:
            conflicts.add(event.event_id)
    events = sorted((event for key, event in by_id.items() if key not in conflicts),
                    key=lambda event: (event.timestamp, event.event_id))
    return events, invalid, bool(conflicts & by_id.keys())


def event_rules(event):
    codes = []
    if event.message == "request_completed" and event.status_code and event.status_code >= 500:
        codes.append("R01")
    if event.message in DEPENDENCY_EVENTS and event.error_type == "dependency_timeout":
        codes.append("R02")
    if event.message == "database_connection_failed":
        codes.append("R03")
    if event.message == "order_processing_failed" or (
        event.message == "request_failed" and event.error_type == "internal_error"
    ):
        codes.append("R04")
    if event.message == "dependency_exhausted":
        if event.error_type == "dependency_unavailable" and event.dependency_service in SERVICES:
            codes.append("R05")
        codes.append("R06")
    return codes


def cascade_evidence(events):
    """Find a directed sequence consistent with propagation across a known Order lookup."""
    for exhausted in events:
        if (exhausted.service_name != "order" or "R05" not in event_rules(exhausted)
                or not exhausted.request_id or exhausted.status_code != 502):
            continue
        dependency = exhausted.dependency_service
        if dependency not in {"user", "product"}:
            continue
        attempts = [e for e in events if e.message == "dependency_attempt_failed"
                    and e.service_name == "order" and e.request_id == exhausted.request_id
                    and e.dependency_service == dependency and e.timestamp < exhausted.timestamp]
        if not attempts:
            continue
        attempt = attempts[-1]
        if attempt.error_type != exhausted.error_type or attempt.status_code != 502:
            continue
        previous_attempt = attempts[-2].timestamp if len(attempts) > 1 else None
        downstream = [e for e in events if e.service_name == dependency and "R01" in event_rules(e)
                      and e.status_code in {502, 503} and e.http_method == "GET"
                      and e.endpoint == f"/{dependency}s/{{key}}" and e.timestamp < attempt.timestamp
                      and (previous_attempt is None or previous_attempt < e.timestamp)]
        terminal = [e for e in events if e.service_name == "order" and e.request_id == exhausted.request_id
                    and e.message == "request_completed" and e.status_code == 502
                    and e.http_method == "POST" and e.endpoint == "/orders"
                    and e.timestamp > exhausted.timestamp]
        if len(downstream) == 1 and len(terminal) == 1:
            yield (downstream[0], attempt, exhausted, terminal[0])


def detect(trace_id: str, snapshot: Snapshot, started: float) -> DetectionResult:
    events, invalid, conflicts = normalize(snapshot.rows, trace_id)
    diagnostics = []
    if snapshot.truncated:
        diagnostics.append("SNAPSHOT_TRUNCATED")
    if invalid:
        diagnostics.append("INVALID_EVENT")
    if conflicts:
        diagnostics.append("CONFLICTING_EVENT_ID")
    completions = {(event.service_name, event.request_id) for event in events
                   if event.message == "request_completed" and event.status_code is not None}
    successful = {(event.service_name, event.request_id): event.timestamp for event in events
                  if event.message == "request_completed" and event.status_code is not None
                  and 200 <= event.status_code < 300 and event.request_id}
    if not completions or any(
        event.message == "request_completed" and event.status_code is None
        or event.message == "dependency_attempt_failed"
        and successful.get((event.service_name, event.request_id), event.timestamp) <= event.timestamp
        for event in events
    ):
        diagnostics.append("MISSING_OUTCOME_EVIDENCE")

    evidence = {rule: set() for rule in RULES}
    for event in events:
        for rule in event_rules(event):
            evidence[rule].add(event.event_id)
    if not (snapshot.truncated or invalid or conflicts):
        for chain in cascade_evidence(events):
            evidence["R07"].update(event.event_id for event in chain)
    specific_ids = set().union(*evidence.values())
    evidence["R08"] = {event.event_id for event in events
                       if event.level in {"ERROR", "CRITICAL"} and event.event_id not in specific_ids}
    matches = [RuleMatch(rule_id=rule, anomaly_type=RULES[rule], evidence_event_ids=sorted(ids))
               for rule, ids in evidence.items() if ids]
    ids = set().union(*evidence.values())
    severity = None
    if matches:
        severity = "critical" if any(e.level == "CRITICAL" and e.event_id in ids for e in events) else (
            "high" if any(evidence[rule] for rule in ("R01", "R03", "R04", "R05", "R06", "R07")) else "medium"
        )
    status = "ANOMALY" if matches else "INSUFFICIENT_DATA" if diagnostics else "NO_ANOMALY_DETECTED"
    return result(
        trace_id, started, status, matched_rules=matches, anomaly_types=[m.anomaly_type for m in matches],
        severity=severity, observed_services=sorted({e.service_name for e in events}),
        affected_services=sorted({e.service_name for e in events if e.event_id in ids}),
        evidence_event_ids=sorted(ids), context_completeness="partial" if events else "unknown",
        diagnostics=diagnostics,
    )
