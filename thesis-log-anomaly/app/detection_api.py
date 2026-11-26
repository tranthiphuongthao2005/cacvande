"""Loopback service for trace materialization and explicit scoring readiness."""

import os
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.contracts import DetectionSession, StrictRecord, TraceId
from app.trace_store import TraceStore, valid_trace


class TraceRequest(StrictRecord):
    trace_id: TraceId


def failure(status, code, **context):
    return JSONResponse(status_code=status, content={"error": {"code": code, **context}})


def create_app(trace_store=None, approved_runtime=None):
    @asynccontextmanager
    async def lifespan(app):
        key = os.getenv("DETECTION_ES_API_KEY")
        if trace_store is not None:
            app.state.store = trace_store
            yield
        elif key:
            with httpx.Client(
                base_url=os.getenv("DETECTION_ES_URL", "http://127.0.0.1:9200"),
                headers={"Authorization": f"ApiKey {key}"},
                timeout=10, trust_env=False,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            ) as client:
                app.state.store = TraceStore(client, os.getenv("DETECTION_ENVIRONMENT", "local"))
                yield
        else:
            app.state.store = None
            yield

    app = FastAPI(title="Thesis Detection API", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        return failure(422, "INVALID_REQUEST")

    @app.get("/health")
    def health():
        return {"status": "alive"}

    @app.get("/ready")
    def readiness():
        if approved_runtime is not None:
            return {"status": "ready_for_scoring", "trace_store_configured": app.state.store is not None}
        return failure(503, "NOT_READY_FOR_SCORING", trace_store_configured=app.state.store is not None,
                       blockers=["MICROSERVICES_PREPROCESSING_NOT_VALIDATED", "SUPPORT_PROTOCOL_UNAVAILABLE"])

    def assess(session, started):
        evidence = {"trace_id": session.trace_id, "session_id": session.session_id,
                    "event_count": len(session.events),
                    "evidence_event_ids": [event.event_id for event in session.events]}
        if approved_runtime is not None:
            try:
                result = approved_runtime.detect(session)
            except ValueError:
                return failure(422, "SESSION_NOT_ELIGIBLE_FOR_SCORING")
            except (OSError, ImportError, RuntimeError):
                return failure(503, "SCORING_DEPENDENCY_UNAVAILABLE")
            return {**result, **evidence, "processing_time_ms": round((perf_counter() - started) * 1000, 3)}
        return failure(503, "NOT_READY_FOR_SCORING", **evidence,
                       preprocessing_warnings=["TRACE_PARTIAL"] if
                       session.source_metadata.completeness == "partial" else [],
                       processing_time_ms=round((perf_counter() - started) * 1000, 3),
                       blockers=["MICROSERVICES_PREPROCESSING_NOT_VALIDATED", "SUPPORT_PROTOCOL_UNAVAILABLE"])

    @app.post("/detect/session")
    def detect_session(session: DetectionSession):
        return assess(session, perf_counter())

    @app.post("/detect/trace")
    def detect_trace(query: TraceRequest):
        started = perf_counter()
        if not valid_trace(query.trace_id):
            return failure(422, "INVALID_TRACE_ID")
        if app.state.store is None:
            return failure(503, "TRACE_STORE_NOT_CONFIGURED")
        try:
            session = app.state.store.fetch(query.trace_id)
        except httpx.HTTPError:
            return failure(503, "TRACE_STORE_UNAVAILABLE")
        except (KeyError, TypeError, ValueError):
            return failure(502, "INVALID_TRACE_DATA")
        if session is None:
            return failure(404, "TRACE_NOT_FOUND")
        return assess(session, started)

    return app


app = create_app()
