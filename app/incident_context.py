"""Incident context schema and evidence-only projection."""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from pydantic import AwareDatetime, Field, ValidationError

from app.contracts import SpanId, StrictRecord, TraceId
from app.trace_store import EVENTS, SERVICES

Mode = Literal["single_service", "cross_service"]
Service = Literal["user", "product", "order"]


class IncidentEvent(StrictRecord):
    event_id: str
    timestamp: AwareDatetime
    service_name: Service
    trace_id: TraceId
    span_id: SpanId | None = None
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    message: str
    status_code: int | None = Field(default=None, strict=True, ge=100, le=599)
    dependency_service: Service | None = None
    error_type: str | None = None


class IncidentContext(StrictRecord):
    trace_id: TraceId
    mode: Mode
    selected_service: Service | None
    services: list[Service]
    start_time: AwareDatetime | None
    end_time: AwareDatetime | None
    event_count: int
    events: list[IncidentEvent]
    timeline: list[dict]
    dependencies: list[dict]
    evidence_event_ids: list[str]
    completeness_status: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    retrieval_warnings: list[str]
    data_quality: dict


@dataclass(frozen=True)
class TraceProof:
    """Trusted collector evidence, never inferred from log count or supplied by API clients."""
    root_completion_id: str
    expected_event_ids: frozenset[str]
    dependency_event_ids: frozenset[str]
    watermark_closed: bool


ERROR_CODES = {
    "internal_error", "database_unavailable", "dependency_timeout", "dependency_unavailable",
    "dependency_connection_error", "dependency_not_found", "order_processing_error",
    "service_unavailable",
}


def build_context(trace_id, mode, selected, snapshot, proof=None):
    warnings = set()
    counts = Counter()
    parsed = {}
    conflicts = set()
    for row in snapshot.rows:
        try:
            if (row.get("trace_id") != trace_id or row.get("message") not in EVENTS
                    or not re.fullmatch(r"[0-9a-f]{32}", row.get("event_id", ""))):
                raise ValueError
            if "service_name" not in row:
                counts["missing_service_name"] += 1
                raise ValueError
            if selected is not None and row["service_name"] != selected:
                counts["out_of_scope"] += 1
                raise ValueError
            code = row.get("error_type")
            if code is not None and code not in ERROR_CODES:
                counts["unrecognized_error_type"] += 1
                code = None
            event = IncidentEvent(
                event_id=row["event_id"], trace_id=trace_id, timestamp=row["@timestamp"],
                service_name=row["service_name"], span_id=row.get("span_id"), level=row["level"],
                message=row["message"], status_code=row.get("status_code"),
                dependency_service=row.get("dependency_service"), error_type=code,
            )
        except (TypeError, KeyError, ValueError, ValidationError):
            counts["invalid_documents"] += 1
            continue
        previous = parsed.get(event.event_id)
        if previous is not None:
            counts["duplicate_documents"] += 1
            if row != previous[1]:
                conflicts.add(event.event_id)
            continue
        parsed[event.event_id] = (event, row)
    events = sorted((event for key, (event, _) in parsed.items() if key not in conflicts),
                    key=lambda event: (event.timestamp, event.event_id))
    ids = [event.event_id for event in events]
    counts["conflicting_event_ids"] = len(conflicts)
    counts["missing_span_id"] = sum(e.span_id is None for e in events)
    counts["timestamp_ties"] = len(events) - len({e.timestamp for e in events})
    warnings.update(key.upper() for key, value in counts.items() if value)
    if snapshot.truncated:
        warnings.add("TRUNCATED_RESULT")
    if snapshot.timed_out:
        warnings.add("ELASTICSEARCH_TIMEOUT_OR_INCOMPLETE_SEARCH")
    if snapshot.late_documents:
        warnings.add("INGESTION_CHANGED_DURING_POLLING")

    timeline = [{"timestamp": event.timestamp.isoformat(), "service_name": event.service_name,
                 "observation": event.message, "status_code": event.status_code,
                 "evidence_event_ids": [event.event_id]} for event in events]
    dependencies = [{
        "source_service": event.service_name, "target_service": event.dependency_service,
        "outcome": "failure_reported", "caller_status_code": event.status_code,
        "evidence_event_ids": [event.event_id],
    } for event in events if event.dependency_service and event.message == "dependency_attempt_failed"]
    order_ends = [e for e in events if e.service_name == "order" and e.message == "request_completed"
                  and parsed[e.event_id][1].get("endpoint") == "/orders"
                  and parsed[e.event_id][1].get("http_method") == "POST"]
    required = ({"user"} if any(edge["target_service"] == "user" for edge in dependencies)
                and not any(e.service_name == "product" for e in events) else {"user", "product"})
    examined = {edge["target_service"] for edge in dependencies if edge["source_service"] == "order"}
    dependency_events = {event.event_id for event in events if event.message == "request_completed"}
    verified_proof = bool(
        proof and proof.watermark_closed and proof.root_completion_id in dependency_events
        and proof.expected_event_ids and proof.root_completion_id in proof.expected_event_ids
        and proof.expected_event_ids <= set(ids) and proof.dependency_event_ids <= set(ids)
    )
    damaged = bool(snapshot.truncated or snapshot.timed_out or conflicts or counts["invalid_documents"]
                   or counts["missing_span_id"])
    if selected is not None:
        warnings.add("SINGLE_SERVICE_SCOPE")
    if not verified_proof:
        warnings.add("ROOT_SPAN_OR_INGESTION_WATERMARK_UNVERIFIED")
        if selected is None and len(order_ends) == 1:
            warnings.add("ORDER_COMPLETION_OBSERVED")
            if required - examined:
                warnings.add("DEPENDENCY_LINKS_UNVERIFIED")
    status = ("COMPLETE" if selected is None and verified_proof and not damaged else
              "PARTIAL" if damaged or (selected is None and len(order_ends) == 1) else "UNKNOWN")
    return IncidentContext(
        trace_id=trace_id, mode=mode, selected_service=selected, services=sorted({e.service_name for e in events}),
        start_time=events[0].timestamp if events else None, end_time=events[-1].timestamp if events else None,
        event_count=len(events), events=events, timeline=timeline, dependencies=dependencies,
        evidence_event_ids=ids, completeness_status=status, retrieval_warnings=sorted(warnings),
        data_quality={"documents_read": len(snapshot.rows), "polls": snapshot.polls, **counts},
    )
