"""Authenticated scenario orchestration, durable idempotency and local notifications."""

import hashlib
import json
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from hmac import compare_digest
from threading import BoundedSemaphore
from time import perf_counter, time
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from app.contracts import StrictRecord, TraceId
from app.incident_context import Mode, Service
from app.llm_analysis import AnalysisRequest, IncidentAnalysis, ModelAnalysis, prepare, validate_model
from app.trace_store import valid_trace

RETENTION = 7 * 24 * 3600
KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$"
STATUS_CODES = {"COMPLETED": 200, "INSUFFICIENT_EVIDENCE": 200, "VALIDATION_FAILED": 502,
                "CONTEXT_UNAVAILABLE": 503, "PROVIDER_UNAVAILABLE": 503, "TIMEOUT": 504,
                "INTERNAL_ERROR": 500}


class Trigger(StrictRecord):
    trace_id: TraceId
    analysis_mode: Mode
    service_name: Service | None = None
    request_id: str | None = Field(default=None, pattern=KEY_PATTERN)
    idempotency_key: str | None = Field(default=None, pattern=KEY_PATTERN)


def error(status, code):
    return JSONResponse(status_code=status, content={"error": {"code": code}})


class Ledger:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS incidents (
                request_digest TEXT PRIMARY KEY, signature TEXT NOT NULL, incident_id TEXT UNIQUE NOT NULL,
                created REAL NOT NULL, result TEXT, notification TEXT)""")

    def claim(self, key, signature):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM incidents WHERE created < ?", (time() - RETENTION,))
            row = db.execute("SELECT signature, incident_id, result FROM incidents WHERE request_digest=?",
                             (key,)).fetchone()
            if row:
                stored, identity, result = row
                return ("conflict", None) if stored != signature else ("replay", json.loads(result)) if result else (
                    "pending", identity)
            identity = uuid4().hex
            db.execute("INSERT INTO incidents VALUES (?, ?, ?, ?, NULL, NULL)", (key, signature, identity, time()))
            return "new", identity

    def finish(self, key, result):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            notification = None
            if result["analysis_status"] == "COMPLETED":
                recent = db.execute(
                    "SELECT 1 FROM incidents WHERE signature=? AND created>=? AND notification IS NOT NULL",
                    (result["scope_signature"], time() - 3600),
                ).fetchone()
                if not recent:
                    notification = {"type": "local_analysis_review", "incident_id": result["incident_id"],
                                    "observations": result["report"]["observations"],
                                    "suspected_cause": result["report"]["suspected_root_cause"],
                                    "evidence_event_ids": result["report"]["evidence_event_ids"],
                                    "limitations": result["report"]["limitations"],
                                    "recommended_checks": result["report"]["recommended_checks"]}
            result["notification_status"] = "LOCAL_STORED" if notification else "SUPPRESSED"
            result.pop("scope_signature")
            db.execute("UPDATE incidents SET result=?, notification=? WHERE request_digest=?",
                       (json.dumps(result), json.dumps(notification) if notification else None, key))

    def read(self, identity):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT result FROM incidents WHERE incident_id=? AND created>=?",
                             (identity, time() - RETENTION)).fetchone()
        return json.loads(row[0]) if row and row[0] else None


def classify(response, phase):
    try:
        code = response.json().get("error", {}).get("code")
    except (ValueError, AttributeError):
        code = None
    if response.status_code == 504:
        return "TIMEOUT"
    if phase == "context" or code in {"CONTEXT_ERROR", "CONTEXT_NOT_FOUND"}:
        return "CONTEXT_UNAVAILABLE"
    if code in {"INVALID_CONTEXT", "INVALID_MODEL_OUTPUT", "PROVIDER_NO_STRUCTURED_RESULT", "NO_EVIDENCE_FOR_ANALYSIS"}:
        return "VALIDATION_FAILED"
    if response.status_code == 429 or response.status_code == 503 or code in {"PROVIDER_ERROR", "PROVIDER_RATE_LIMITED"}:
        return "PROVIDER_UNAVAILABLE"
    return "INTERNAL_ERROR"


def execute(client, context_base, llm_base, item, result):
    query = AnalysisRequest(trace_id=item.trace_id, mode=item.analysis_mode, service_name=item.service_name)
    params = {"mode": query.mode}
    if query.service_name:
        params["service_name"] = query.service_name
    phase = "context"
    try:
        result["context_calls"] += 1
        reply = client.get(f"{context_base}/context/trace/{query.trace_id}", params=params)
        if reply.status_code != 200:
            return classify(reply, phase)
        source = prepare(reply.json(), query, 16000)
        if not source.events:
            return "VALIDATION_FAILED"
        result["context_completeness"] = source.completeness
        phase = "llm"
        result["llm_calls"] += 1
        reply = client.post(f"{llm_base}/analyze/trace", json=query.model_dump(mode="json"),
                            headers={"X-Required-Provider": "mock"})
        if reply.status_code != 200:
            return classify(reply, phase)
        analysis = IncidentAnalysis.model_validate(reply.json())
        if (analysis.provider != "mock" or analysis.trace_id != query.trace_id or analysis.analysis_mode != query.mode
                or analysis.selected_service != query.service_name or analysis.context_completeness != source.completeness
                or set(analysis.input_event_ids) | set(analysis.omitted_event_ids) != set(source.events) | set(source.omitted)
                or not set(analysis.input_event_ids) <= set(source.events)
                or not analysis.input_event_ids
                or len(set(analysis.input_event_ids)) != len(analysis.input_event_ids)
                or set(analysis.input_event_ids) & set(analysis.omitted_event_ids)):
            return "VALIDATION_FAILED"
        source.events = {eid: source.events[eid] for eid in analysis.input_event_ids}
        source.omitted = analysis.omitted_event_ids
        _, warnings = validate_model(analysis.model_dump(include=set(ModelAnalysis.model_fields)), source)
        if not set(warnings) <= set(analysis.validation_warnings):
            return "VALIDATION_FAILED"
        result.update(provider_type=analysis.provider, model_name=analysis.model_name,
                      evidence_validation_status=analysis.validation_status,
                      report={"analysis_id": analysis.analysis_id,
                              "observations": [fact.model_dump() for fact in analysis.observations],
                              "suspected_root_cause": analysis.suspected_root_cause.model_dump()
                              if analysis.suspected_root_cause else None,
                              "evidence_event_ids": analysis.input_event_ids,
                              "limitations": analysis.limitations, "recommended_checks": analysis.recommended_checks,
                              "validation_warnings": analysis.validation_warnings})
        return "COMPLETED" if analysis.analysis_status == "ANALYZED" else "INSUFFICIENT_EVIDENCE"
    except httpx.TimeoutException:
        return "TIMEOUT"
    except httpx.HTTPError:
        return "CONTEXT_UNAVAILABLE" if phase == "context" else "PROVIDER_UNAVAILABLE"
    except (ValueError, TypeError, KeyError):
        return "VALIDATION_FAILED"


def create_app(path=None, token=None, client=None):
    slots = BoundedSemaphore(2)

    @asynccontextmanager
    async def lifespan(app):
        app.state.ledger = Ledger(path or os.getenv("INCIDENT_DB_PATH", "/data/incidents.sqlite"))
        app.state.token = token or os.environ["WORKFLOW_TRIGGER_TOKEN"]
        if len(app.state.token) < 32:
            raise ValueError("Workflow trigger token must contain at least 32 characters")
        with httpx.Client(timeout=25, trust_env=False) as downstream:
            app.state.client = client or downstream
            yield

    api = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    def authorized(auth):
        reference = ("Bearer " + api.state.token).encode()
        return bool(auth and compare_digest(auth.encode(), reference))

    @api.exception_handler(RequestValidationError)
    async def invalid(_req, _exc):
        return error(422, "INVALID_TRIGGER")

    @api.get("/health")
    def health():
        return {"status": "alive"}

    @api.get("/incidents/{identity}")
    def read(identity: str, authorization: str | None = Header(default=None)):
        if not authorized(authorization):
            return error(401, "UNAUTHORIZED_TRIGGER")
        result = api.state.ledger.read(identity)
        return result or error(404, "INCIDENT_NOT_FOUND")

    @api.post("/trigger")
    def trigger(item: Trigger, authorization: str | None = Header(default=None)):
        if not authorized(authorization):
            return error(401, "UNAUTHORIZED_TRIGGER")
        if (not valid_trace(item.trace_id) or (item.analysis_mode == "single_service") != bool(item.service_name)
                or bool(item.request_id) == bool(item.idempotency_key)):
            return error(422, "INVALID_TRIGGER")
        if not slots.acquire(blocking=False):
            return error(429, "WORKFLOW_BUSY")
        try:
            key = hashlib.sha256((item.idempotency_key or item.request_id).encode()).hexdigest()
            signature = hashlib.sha256(json.dumps((item.trace_id, item.analysis_mode, item.service_name)).encode()).hexdigest()
            state, value = api.state.ledger.claim(key, signature)
            if state == "conflict":
                return error(409, "IDEMPOTENCY_CONFLICT")
            if state == "pending":
                return JSONResponse(status_code=202, content={"status": "IN_PROGRESS", "incident_id": value})
            if state == "replay":
                return JSONResponse(status_code=STATUS_CODES[value["analysis_status"]],
                                    content={**value, "replayed": True})
            started = perf_counter()
            result = {"incident_id": value, "trace_id": item.trace_id, "trigger_type": "scenario",
                      "analysis_mode": item.analysis_mode, "selected_service": item.service_name,
                      "provider_type": None, "model_name": None, "context_completeness": None,
                      "evidence_validation_status": "NOT_RUN", "report": None, "scope_signature": signature,
                      "created_at": datetime.now(timezone.utc).isoformat(),
                      "report_reference": f"incident-store:{value}", "context_calls": 0, "llm_calls": 0}
            status = execute(api.state.client, os.getenv("WORKFLOW_CONTEXT_URL", "http://context-service:8000"),
                             os.getenv("WORKFLOW_LLM_URL", "http://llm-service:8000"), item, result)
            result.update(analysis_status=status, review_required=True,
                          processing_time_ms=round((perf_counter() - started) * 1000, 3))
            if status == "VALIDATION_FAILED":
                result["evidence_validation_status"] = "FAILED"
            api.state.ledger.finish(key, result)
            return JSONResponse(status_code=STATUS_CODES[status], content={**result, "replayed": False})
        finally:
            slots.release()

    return api


app = create_app()
