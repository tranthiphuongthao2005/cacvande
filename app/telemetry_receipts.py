"""Versioned, fail-closed completeness proofs for the read-only Context API."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field

from app.contracts import StrictRecord, TraceId
from app.incident_context import IncidentContext, Service


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class Seal(StrictRecord):
    seal_version: Literal["source-seal-v1"]
    run_id: TraceId
    trace_id: TraceId
    source_service: Service
    source_completion_timestamp: AwareDatetime
    root_span_completion_status: bool
    source_event_ids: list[TraceId] = Field(max_length=512)
    expected_event_count: int | None = Field(ge=0, le=512)
    source_coverage: Literal["OBSERVED_CAPTURE_ONLY", "AUTHORITATIVE_CLOSED_CAPTURE"]
    parent_graph_valid: bool
    producer_accounting_version: Literal["producer-accounting-v1"] | None = None
    producer_evidence_sha256: str | None = None
    producer_services: list[Service] | None = None
    transport_handoff_confirmed: bool | None = None


class Receipt(StrictRecord):
    receipt_version: Literal["es-receipt-v1"]
    run_id: TraceId
    trace_id: TraceId
    expected_event_ids: list[TraceId] = Field(max_length=512)
    observed_event_ids: list[TraceId] = Field(max_length=512)
    missing_event_ids: list[TraceId]
    unexpected_event_ids: list[TraceId]
    duplicate_event_ids: list[TraceId]
    reconciliation_timestamp: AwareDatetime
    ingestion_settled_status: Literal["MATCHED_CAPTURE", "MISMATCH", "INCOMPLETE_QUERY"]
    event_content_matches: bool
    event_sha256: dict[TraceId, str]


def differences(expected, observed):
    a, b = set(expected), set(observed)
    return sorted(a - b), sorted(b - a), sorted(k for k, v in Counter(observed).items() if v > 1)


def envelope(seal, receipt):
    body = {"seal": seal.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json")}
    return {**body, "sha256": fingerprint(body)}


def decode(raw):
    if set(raw) != {"seal", "receipt", "sha256"} or raw["sha256"] != fingerprint({
        "seal": raw["seal"], "receipt": raw["receipt"],
    }):
        raise ValueError("Receipt bundle digest mismatch")
    seal, receipt = Seal.model_validate(raw["seal"]), Receipt.model_validate(raw["receipt"])
    if seal.trace_id != receipt.trace_id or seal.run_id != receipt.run_id:
        raise ValueError("Receipt provenance mismatch")
    missing, extra, duplicate = differences(receipt.expected_event_ids, receipt.observed_event_ids)
    if (seal.source_event_ids != receipt.expected_event_ids
            or len(seal.source_event_ids) != len(set(seal.source_event_ids))
            or set(receipt.event_sha256) != set(receipt.observed_event_ids)
            or receipt.reconciliation_timestamp < seal.source_completion_timestamp
            or (missing, extra, duplicate) != (receipt.missing_event_ids, receipt.unexpected_event_ids,
                                               receipt.duplicate_event_ids)
            or seal.expected_event_count is not None and seal.expected_event_count != len(seal.source_event_ids)
            or receipt.ingestion_settled_status == "MATCHED_CAPTURE" and (missing or extra or duplicate)):
        raise ValueError("Inconsistent reconciliation receipt")
    return seal, receipt


def classify(context: IncidentContext, seal=None, receipt=None):
    reasons = []
    match = False
    if seal is None:
        reasons.append("SOURCE_SEAL_MISSING")
    if receipt is None:
        reasons.append("INGESTION_RECEIPT_MISSING")
    authoritative = bool(seal and seal.source_coverage == "AUTHORITATIVE_CLOSED_CAPTURE"
                         and seal.expected_event_count is not None)
    if seal is not None:
        if not authoritative:
            reasons.append("SOURCE_CAPTURE_COVERAGE_UNPROVEN")
        if not seal.parent_graph_valid:
            reasons.append("SPAN_GRAPH_UNVERIFIED")
        if seal.producer_accounting_version and not seal.transport_handoff_confirmed:
            reasons.append("TRANSPORT_HANDOFF_UNCONFIRMED")
    if seal and receipt:
        ids = context.evidence_event_ids
        expected = set(seal.source_event_ids)
        current_match = set(ids) == expected if context.mode == "cross_service" else bool(ids) and set(ids) <= expected
        match = bool(seal.trace_id == context.trace_id == receipt.trace_id and current_match and expected
                     and all(receipt.event_sha256.get(e.event_id) == fingerprint(e.model_dump(mode="json"))
                             for e in context.events)
                     and receipt.ingestion_settled_status == "MATCHED_CAPTURE" and receipt.event_content_matches)
        if not match:
            reasons.append("RECEIPT_OR_CURRENT_SNAPSHOT_MISMATCH")
    if context.mode == "single_service":
        reasons.append("SINGLE_SERVICE_SCOPE")
    damage = {"TRUNCATED_RESULT", "ELASTICSEARCH_TIMEOUT_OR_INCOMPLETE_SEARCH", "INVALID_DOCUMENTS",
              "CONFLICTING_EVENT_IDS", "MISSING_SPAN_ID"}
    clean = not damage.intersection(context.retrieval_warnings)
    if not clean:
        reasons.append("CURRENT_SNAPSHOT_DEGRADED")
    receipt_scoped = bool(seal and seal.trace_id == context.trace_id)
    completed = bool(receipt_scoped and seal.root_span_completion_status and
                     (context.selected_service is None or context.selected_service == seal.source_service))
    complete = bool(completed and authoritative and seal.parent_graph_valid and match
                    and (not seal.producer_accounting_version or seal.transport_handoff_confirmed is True)
                    and clean and context.mode == "cross_service")
    return {"classification": "COMPLETE" if complete else context.completeness_status,
            "scope": context.mode, "request_completed": completed,
            "source_sealed": receipt_scoped, "authoritative_source_coverage": authoritative and receipt_scoped,
            "ingestion_reconciled": match and clean,
            "trace_complete": complete, "warnings": reasons}


def resolve(context, directory):
    if not directory:
        return classify(context), None
    file = Path(directory) / f"{context.trace_id}.json"
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
        seal, receipt = decode(raw)
        if seal.trace_id != context.trace_id:
            raise ValueError("Receipt trace mismatch")
    except FileNotFoundError:
        return classify(context), None
    except (OSError, ValueError, KeyError, TypeError):
        result = classify(context)
        result["warnings"].append("RECEIPT_UNTRUSTED_OR_INVALID")
        return result, None
    provenance = {"run_id": seal.run_id, "seal_version": seal.seal_version,
                  "receipt_version": receipt.receipt_version, "bundle_sha256": raw["sha256"]}
    if seal.producer_accounting_version:
        provenance.update(accounting_version=seal.producer_accounting_version,
                          producer_evidence_sha256=seal.producer_evidence_sha256,
                          producer_services=seal.producer_services,
                          transport_handoff_confirmed=seal.transport_handoff_confirmed)
    return classify(context, seal, receipt), provenance
