"""Authenticated mock-only analysis of a bound, immutable Context Package."""

import asyncio
import json
import os
import sqlite3
from hmac import compare_digest
from time import perf_counter, time

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.context_integration_client import unique_object
from app.workflow_config import Settings
from app.workflow_models import AnalysisRequest, AnalysisResult, execution_id, simulate, validate_result, verify_request
from app.workflow_store import Store


async def simulated_analysis(envelope):
    return simulate(envelope)


def error(status, code):
    return JSONResponse(status_code=status, content={
        "error": {"code": code}, "analysis_provider": "mock", "analysis_mode": "MOCK", "is_mock": True,
    })


def create_app(settings=None, *, analyze=simulated_analysis, clock=time):
    app = FastAPI(title="Isolated mock analysis")
    settings = settings or Settings.from_env()
    store = Store(settings)
    token = settings.secret()

    @app.get("/health")
    def health():
        return {"status": "alive", "analysis_provider": "mock", "analysis_mode": "MOCK", "is_mock": True}

    @app.post("/analyze/package", response_model=AnalysisResult)
    async def execute(request: Request):
        auth = request.headers.get("Authorization", "").encode("utf-8")
        if token is None:
            return error(503, "MOCK_AUTH_NOT_CONFIGURED")
        if not compare_digest(auth, f"Bearer {token}".encode()):
            return error(401, "WORKFLOW_UNAUTHORIZED")
        try:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > settings.max_payload_bytes:
                    return error(413, "WORKFLOW_PAYLOAD_TOO_LARGE")
                body.extend(chunk)
            raw = json.loads(body, object_pairs_hook=unique_object)
            envelope = AnalysisRequest.model_validate(raw)
            verify_request(envelope, raw["context_payload"])
        except (ValueError, TypeError, RecursionError):
            return error(422, "INVALID_WORKFLOW_REQUEST")

        try:
            status, claim = store.accept(envelope, execution_id(request.headers.get("X-Workflow-Execution-Id")), clock())
            if status == 200:
                return Response(claim, media_type="application/json")
            if status != 201:
                return error(status, claim)
            started = perf_counter()
            try:
                async with asyncio.timeout(min(10, settings.timeout_seconds)):
                    output = AnalysisResult.model_validate(await analyze(envelope))
                validate_result(envelope, output)
            except TimeoutError:
                store.finish_analysis(envelope, claim, clock(), (perf_counter() - started) * 1000,
                                      code="MOCK_ANALYSIS_TIMEOUT")
                return error(504, "MOCK_ANALYSIS_TIMEOUT")
            except ValueError:
                store.finish_analysis(envelope, claim, clock(), (perf_counter() - started) * 1000,
                                      code="ANALYSIS_VALIDATION_FAILED", review=True)
                return error(422, "ANALYSIS_VALIDATION_FAILED")
            except Exception:
                store.finish_analysis(envelope, claim, clock(), (perf_counter() - started) * 1000,
                                      code="MOCK_ANALYSIS_UNAVAILABLE")
                return error(503, "MOCK_ANALYSIS_UNAVAILABLE")
            store.finish_analysis(envelope, claim, clock(), (perf_counter() - started) * 1000, output=output)
            return output
        except (sqlite3.Error, OSError):
            return error(503, "WORKFLOW_STORAGE_UNAVAILABLE")
        except ValueError:
            return error(409, "WORKFLOW_STATE_CONFLICT")

    return app


app = create_app()
