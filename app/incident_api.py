"""Authenticated REST API and independent incident handoff runner."""

import asyncio
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from hmac import compare_digest
from time import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, Field, ValidationError, model_validator

from app.context_integration_client import unique_object
from app.contracts import StrictRecord, TraceId
from app.incident_config import Settings
from app.incident_handoff import Source, Worker
from app.incident_models import AnalysisState, Incident, IncidentPage, Lifecycle, StatusChange
from app.incident_store import IncidentStore

Identity = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100000)]
api_bearer = HTTPBearer(auto_error=False)


class Filters(StrictRecord):
    incident_status: Lifecycle | None = None
    analysis_status: AnalysisState | None = None
    severity: Literal["medium", "high", "critical"] | None = None
    service: Literal["user", "product", "order"] | None = None
    anomaly_type: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    detection_source: Literal["rule_based"] | None = None
    analysis_provider: Literal["mock", "gemini", "openai"] | None = None
    is_mock: bool | None = None
    context_completeness: Literal["COMPLETE", "PARTIAL", "UNKNOWN"] | None = None
    trace_id: TraceId | None = None
    source_namespace: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    from_time: AwareDatetime | None = None
    to_time: AwareDatetime | None = None

    @model_validator(mode="after")
    def range_order(self):
        if self.from_time and self.to_time and self.from_time >= self.to_time:
            raise ValueError("Invalid time interval")
        return self


class ListQuery(Filters):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=100000)


def error(status, code):
    return JSONResponse(status_code=status, content={"error": {"code": code}})


def require(condition, status, code):
    if not condition:
        raise HTTPException(status, code)


def create_app(settings=None, *, clock=time):
    settings = settings or Settings.from_env()
    store = IncidentStore(settings.storage_path)

    @asynccontextmanager
    async def lifespan(app):
        app.state.storage_ready = False
        app.state.handoff_ready = not settings.handoff_enabled
        app.state.handoff_error = None
        stop = asyncio.Event()
        task = None
        if settings.management_enabled:
            try:
                await asyncio.to_thread(store.install)
                app.state.storage_ready = True
                if settings.handoff_enabled:
                    source = Source(settings)
                    await asyncio.to_thread(source.install)
                    app.state.source = source
                    worker = Worker(settings, source, store, clock=clock)

                    async def pump():
                        while not stop.is_set():
                            try:
                                await asyncio.to_thread(worker.tick)
                                app.state.handoff_ready = worker.last_error is None
                                app.state.handoff_error = worker.last_error
                            except sqlite3.Error:
                                app.state.handoff_ready = False
                                app.state.handoff_error = "HANDOFF_STORAGE_UNAVAILABLE"
                            try:
                                await asyncio.wait_for(stop.wait(), settings.poll_interval_seconds)
                            except TimeoutError:
                                pass

                    task = asyncio.create_task(pump())
            except (sqlite3.Error, OSError, ValueError):
                app.state.handoff_error = "INCIDENT_STARTUP_STORAGE_FAILURE"
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                await task

    app = FastAPI(title="Internal Incident Management", lifespan=lifespan, redoc_url=None)

    @app.exception_handler(HTTPException)
    async def rejected(_request, exc):
        return error(exc.status_code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _exc):
        return error(422, "INVALID_INCIDENT_REQUEST")

    @app.exception_handler(sqlite3.Error)
    async def db_error(_request, _exc):
        return error(503, "INCIDENT_STORAGE_UNAVAILABLE")

    @app.exception_handler(ValidationError)
    async def stored_error(_request, _exc):
        return error(503, "INVALID_STORED_INCIDENT")

    def token_matches(token, actual):
        return token is not None and compare_digest(token.get_secret_value().encode(), actual)

    def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(api_bearer)]):
        require(settings.management_enabled, 503, "INCIDENT_MANAGEMENT_DISABLED")
        value = credentials.credentials.encode("utf-8") if credentials else b""
        role = "operator" if token_matches(settings.api_token, value) else "reader" if (
            token_matches(settings.read_token, value)
        ) else None
        require(role is not None, 401, "INCIDENT_UNAUTHORIZED")
        require(app.state.storage_ready, 503, "INCIDENT_STORAGE_UNAVAILABLE")
        return role

    def operator(role: Annotated[str, Depends(authorize)]):
        require(role == "operator", 403, "INCIDENT_OPERATOR_REQUIRED")
        return settings.operator_id

    def paging(limit):
        require(limit <= settings.max_page_size, 422, "INCIDENT_PAGE_LIMIT")

    def existing(identity):
        value = store.get(identity)
        require(value is not None, 404, "INCIDENT_NOT_FOUND")
        return value

    @app.get("/health")
    def health():
        return {"status": "alive"}

    @app.get("/ready")
    def ready():
        if not settings.management_enabled:
            return error(503, "INCIDENT_MANAGEMENT_DISABLED")
        if not app.state.storage_ready or not app.state.handoff_ready:
            return error(503, app.state.handoff_error or "INCIDENT_NOT_READY")
        with store.connect() as db:
            db.execute("SELECT id FROM managed_incidents LIMIT 1").fetchone()
        return {"status": "ready", "handoff_enabled": settings.handoff_enabled}

    @app.get("/incidents/statistics", dependencies=[Depends(authorize)])
    def statistics(filters: Annotated[Filters, Query()]):
        output = store.statistics(filters.model_dump())
        if settings.handoff_enabled and hasattr(app.state, "source"):
            output["handoff_queue"] = app.state.source.counts()
        return output

    @app.get("/incidents", response_model=IncidentPage, dependencies=[Depends(authorize)])
    def incidents(query: Annotated[ListQuery, Query()]):
        paging(query.limit)
        items, total = store.list(query.model_dump(exclude={"limit", "offset"}), query.limit, query.offset)
        return IncidentPage(items=items, total=total, limit=query.limit, offset=query.offset)

    @app.get("/incidents/{incident_id}", response_model=Incident | dict, dependencies=[Depends(authorize)])
    def detail(incident_id: Identity):
        value = store.get(incident_id)
        if value is not None:
            return value
        legacy = store.legacy.read(incident_id)
        require(legacy is not None, 404, "INCIDENT_NOT_FOUND")
        return JSONResponse(legacy)

    @app.get("/incidents/{incident_id}/timeline", dependencies=[Depends(authorize)])
    def timeline(incident_id: Identity, limit: Limit = 50, offset: Offset = 0):
        paging(limit)
        existing(incident_id)
        return {"items": store.history(incident_id, "timeline", limit, offset), "limit": limit, "offset": offset}

    @app.get("/incidents/{incident_id}/history", dependencies=[Depends(authorize)])
    def status_history(incident_id: Identity, limit: Limit = 50, offset: Offset = 0):
        paging(limit)
        existing(incident_id)
        return {"items": store.history(incident_id, "history", limit, offset), "limit": limit, "offset": offset}

    @app.get("/incidents/{incident_id}/revisions", dependencies=[Depends(authorize)])
    def revisions(incident_id: Identity, limit: Limit = 50, offset: Offset = 0):
        paging(limit)
        existing(incident_id)
        return {"items": store.history(incident_id, "revisions", limit, offset), "limit": limit, "offset": offset}

    @app.get("/incidents/{incident_id}/evidence", dependencies=[Depends(authorize)])
    def evidence(incident_id: Identity, limit: Limit = 50, offset: Offset = 0):
        paging(limit)
        existing(incident_id)
        return {"items": store.evidence(incident_id, limit, offset), "limit": limit, "offset": offset}

    @app.patch("/incidents/{incident_id}/status", response_model=Incident,
               openapi_extra={"requestBody": {"required": True, "content": {
                   "application/json": {"schema": StatusChange.model_json_schema()}
               }}})
    async def update_status(incident_id: Identity, request: Request, actor: Annotated[str, Depends(operator)]):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > settings.max_payload_bytes:
                return error(413, "INCIDENT_PAYLOAD_TOO_LARGE")
            body.extend(chunk)
        try:
            change = StatusChange.model_validate(json.loads(body, object_pairs_hook=unique_object))
            if re.search(r"(?i)(?:bearer\s+|[a-z]+://[^\s]+:[^\s]+@|(?:api[_ -]?key|password|token)\s*[:=])",
                         change.reason):
                raise ValueError("Secret-shaped status reason")
        except (ValueError, RecursionError):
            return error(422, "INVALID_INCIDENT_REQUEST")
        code, value = await asyncio.to_thread(store.change, incident_id, change, actor, clock())
        if code:
            return error(404 if code == "INCIDENT_NOT_FOUND" else 409, code)
        return value

    return app


app = create_app()
