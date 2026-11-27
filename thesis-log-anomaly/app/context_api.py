"""Standalone read-only context API."""

import os
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.context_store import ContextStore
from app.incident_context import IncidentContext, Mode, Service, build_context
from app.telemetry_receipts import resolve
from app.trace_store import valid_trace


def error(status, code):
    return JSONResponse(status_code=status, content={"error": {"code": code}})


def create_app(store=None):
    @asynccontextmanager
    async def lifespan(app):
        key = os.getenv("CONTEXT_ES_API_KEY")
        if store is not None:
            app.state.store = store
            yield
        elif key:
            with httpx.Client(base_url=os.getenv("CONTEXT_ES_URL", "http://127.0.0.1:9200"),
                              headers={"Authorization": f"ApiKey {key}"}, trust_env=False, timeout=2.5,
                              limits=httpx.Limits(max_connections=8, max_keepalive_connections=4)) as client:
                app.state.store = ContextStore(client)
                yield
        else:
            app.state.store = None
            yield

    app = FastAPI(title="Thesis Context Retrieval API", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _exc):
        return error(422, "INVALID_REQUEST")

    @app.get("/health")
    def health():
        return {"status": "alive"}

    @app.get("/ready")
    def ready():
        if app.state.store is None:
            return error(503, "TRACE_STORE_NOT_CONFIGURED")
        try:
            app.state.store.ready()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return error(503, "TRACE_STORE_UNAVAILABLE")
        return {"status": "ready"}

    @app.get("/context/trace/{trace_id}", response_model=IncidentContext)
    def get_context(trace_id: str, mode: Mode = "cross_service", service_name: Service | None = None,
                    wait_ms: Annotated[int, Query(ge=0, le=3000)] = 0):
        if not valid_trace(trace_id) or (mode == "single_service") != (service_name is not None):
            return error(422, "INVALID_TRACE_OR_SCOPE")
        if app.state.store is None:
            return error(503, "TRACE_STORE_NOT_CONFIGURED")
        try:
            result = app.state.store.fetch(trace_id, service_name, wait_ms=wait_ms)
        except httpx.TimeoutException:
            return error(504, "ELASTICSEARCH_TIMEOUT")
        except httpx.HTTPError:
            return error(503, "TRACE_STORE_UNAVAILABLE")
        except (ValueError, KeyError, TypeError):
            return error(502, "INVALID_SEARCH_RESPONSE")
        if not result.rows:
            return error(504, "INCOMPLETE_SEARCH") if result.timed_out else error(404, "TRACE_NOT_FOUND")
        return build_context(trace_id, mode, service_name, result)

    @app.get("/context/v2/trace/{trace_id}")
    def get_context_v2(trace_id: str, mode: Mode = "cross_service", service_name: Service | None = None,
                       wait_ms: Annotated[int, Query(ge=0, le=3000)] = 0):
        base = get_context(trace_id, mode, service_name, wait_ms)
        if not isinstance(base, IncidentContext):
            return base
        completeness, provenance = resolve(base, os.getenv("CONTEXT_PRODUCER_RECEIPT_DIR"))
        if provenance is None and "RECEIPT_UNTRUSTED_OR_INVALID" not in completeness["warnings"]:
            completeness, provenance = resolve(base, os.getenv("CONTEXT_RECEIPT_DIR"))
        return {"schema_version": "context-receipts-v2", "context": base.model_dump(mode="json"),
                "completeness": completeness, "completeness_provenance": provenance}

    return app


app = create_app()
