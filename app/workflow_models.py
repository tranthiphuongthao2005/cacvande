"""Snapshot-preserving HTTP contract for the mock workflow."""

import re
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.context_integration_models import ContextPayload, context_payload, digest
from app.contracts import StrictRecord, TraceId
from app.incident_context import Service
from app.trace_store import valid_trace

VERSION = "1.0"
PURPOSE = "incident-analysis-mock"
HexDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Binding(StrictRecord):
    schema_version: Literal["1.0"]
    analysis_job_id: HexDigest
    context_package_id: HexDigest
    trace_id: TraceId
    trace_version: int = Field(ge=1, strict=True)
    context_payload_sha256: HexDigest
    idempotency_key: HexDigest


class AnalysisRequest(Binding):
    context_mode: Literal["cross_service"] = "cross_service"
    context_payload: ContextPayload


class Observation(StrictRecord):
    event_id: TraceId
    service_name: Service
    kind: Literal["http_server_error", "dependency_failure"]
    status_code: int | None = Field(strict=True, ge=100, le=599)


class AnalysisResult(Binding):
    analysis_provider: Literal["mock"]
    analysis_mode: Literal["MOCK"]
    is_mock: bool = Field(strict=True)
    analysis_status: Literal["SIMULATED_OBSERVATIONS", "INSUFFICIENT_EVIDENCE"]
    evidence_validation_scope: Literal["CONTEXT_ID_AND_OBSERVABLE_FIELDS"]
    observations: list[Observation] = Field(max_length=8)


def identity(namespace, package_id, trace_version):
    return digest([namespace, package_id, trace_version, VERSION, PURPOSE])


def verify_request(request, raw_payload=None):
    raw = raw_payload if raw_payload is not None else request.context_payload.model_dump(mode="json")
    context_payload(raw, request.trace_id)
    payload = request.context_payload.model_dump(mode="json")
    if (not valid_trace(request.trace_id) or request.idempotency_key != request.analysis_job_id
            or digest(raw) != request.context_payload_sha256
            or digest(payload) != request.context_payload_sha256):
        raise ValueError("CONTEXT_HASH_OR_IDENTITY_MISMATCH")


def build_request(package, namespace):
    job_id = identity(namespace, package.context_package_id, package.trace_version)
    return AnalysisRequest(
        schema_version=VERSION, analysis_job_id=job_id, idempotency_key=job_id,
        context_package_id=package.context_package_id,
        trace_id=package.trace_id, trace_version=package.trace_version,
        context_payload_sha256=package.context_payload_sha256, context_payload=package.context_payload,
    )


def observable(event):
    if event.message == "request_completed" and 500 <= (event.status_code or 0) <= 599:
        return "http_server_error"
    if event.message == "dependency_attempt_failed" and event.dependency_service:
        return "dependency_failure"
    return None


def simulate(request):
    observations = [
        Observation(event_id=event.event_id, service_name=event.service_name, kind=kind,
                    status_code=event.status_code)
        for event in request.context_payload.events if (kind := observable(event))
    ][:8]
    return AnalysisResult(
        **request.model_dump(include=set(Binding.model_fields)),
        analysis_provider="mock", analysis_mode="MOCK", is_mock=True,
        evidence_validation_scope="CONTEXT_ID_AND_OBSERVABLE_FIELDS",
        analysis_status="SIMULATED_OBSERVATIONS" if observations else "INSUFFICIENT_EVIDENCE",
        observations=observations,
    )


def validate_result(request, result):
    binding = set(Binding.model_fields)
    if not result.is_mock or result.model_dump(include=binding) != request.model_dump(include=binding):
        raise ValueError("ANALYSIS_IDENTITY_MISMATCH")
    if (result.analysis_status == "SIMULATED_OBSERVATIONS") != bool(result.observations):
        raise ValueError("INVALID_ABSTENTION")
    events = {e.event_id: e for e in request.context_payload.events}
    seen = set()
    for item in result.observations:
        event = events.get(item.event_id)
        if (not event or item.event_id in seen
                or (item.service_name, item.kind, item.status_code) !=
                (event.service_name, observable(event), event.status_code)):
            raise ValueError("ANALYSIS_EVIDENCE_MISMATCH")
        seen.add(item.event_id)


def execution_id(header):
    return header if header and re.fullmatch(r"[0-9]{1,32}", header) else None
