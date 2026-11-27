"""Isolated scenario-triggered analysis with fail-closed evidence handling."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from collections import OrderedDict
from contextlib import asynccontextmanager
from threading import BoundedSemaphore, Lock
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.llm_analysis import (AnalysisRequest, IncidentAnalysis, ObservationMismatch,
                              PROMPT_VERSION, prepare, validate_model)
from app.llm_provider import (GeminiProvider, MockProvider, OpenAIProvider, ProviderFailure,
                              capture_raw_gemini_response)
from app.trace_store import EVENTS, valid_trace


VALIDATION_DIAGNOSTICS = logging.getLogger("uvicorn.error").getChild("llm_validation")
VALIDATION_REASON_CODES = {
    "Output contains disallowed content": "DISALLOWED_CONTENT",
    "Unknown or out-of-scope evidence": "OUT_OF_SCOPE_EVIDENCE",
    "Observation contradicts indexed event fields": "OBSERVATION_MISMATCH",
    "Evidence fields disagree": "EVIDENCE_MISMATCH",
    "Affected service lacks a grounded observation": "AFFECTED_SERVICE_UNGROUNDED",
    "Invalid suspected cause for analysis status": "INVALID_SUSPECTED_CAUSE",
    "Hypothesis lacks grounded references": "HYPOTHESIS_UNGROUNDED",
    "Suspected service lacks an in-scope cited event": "SUSPECTED_SERVICE_UNGROUNDED",
    "Analysis lacks grounded observations": "MISSING_OBSERVATIONS",
}


def validation_diagnostic(exc):
    details = {"reason": VALIDATION_REASON_CODES.get(str(exc), "UNCLASSIFIED")}
    if isinstance(exc, ObservationMismatch):
        actual = exc.actual
        safe_actual = (actual in EVENTS or actual in {"user", "product", "order"}
                       or re.fullmatch(r"(?:HTTP )?[1-5][0-9]{2}", actual) is not None)
        details.update({
            "location": exc.location,
            "index": exc.index,
            "event_id": exc.event_id,
            "kind": exc.kind,
            "expected": exc.expected,
            "actual_safe": actual if safe_actual else None,
            "actual_length": len(actual),
        })
    return details


def error(status, code):
    return JSONResponse(status_code=status, content={"error": {"code": code}})


class ContextClient:
    def __init__(self, client):
        self.client = client

    def fetch(self, query):
        params = {"mode": query.mode}
        if query.service_name is not None:
            params["service_name"] = query.service_name
        return self.client.get(f"/context/trace/{query.trace_id}", params=params).raise_for_status().json()


def configured_provider():
    mode = os.getenv("LLM_PROVIDER", "openai")
    if mode == "mock":
        return MockProvider()
    if mode == "gemini":
        key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", "").strip()
        trace_id = os.getenv("LLM_GEMINI_SMOKE_TRACE_ID", "")
        if (os.getenv("LLM_ALLOW_EXTERNAL") != "1" or not key
                or model != GeminiProvider.free_tier_model or not valid_trace(trace_id)
                or not gemini_smoke_authorized()):
            return None
        return GeminiProvider(key, model, 1200, trace_id)
    key, model = os.getenv("OPENAI_API_KEY", "").strip(), os.getenv("LLM_MODEL", "").strip()
    if mode != "openai" or not key or not model or os.getenv("LLM_ALLOW_EXTERNAL") != "1":
        return None
    return OpenAIProvider(key, model, 1200)


def gemini_smoke_authorized():
    """Require an operator attestation and short-lived smoke authorization."""
    if (os.getenv("LLM_GEMINI_FREE_TIER_CONFIRMED") != "1"
            or not os.getenv("LLM_GEMINI_SMOKE_APPROVAL_ID", "").strip()):
        return False
    try:
        expires = datetime.fromisoformat(os.getenv("LLM_GEMINI_SMOKE_EXPIRES_UTC", ""))
        now = datetime.now(timezone.utc)
        return 0 < (expires - now).total_seconds() <= 3600
    except (ValueError, TypeError):
        return False


def provider_limits(runtime, call_cap, validation_retries):
    if runtime.name == "gemini":
        return min(call_cap, 2), 0
    if runtime.name == "openai":
        return call_cap, validation_retries
    return None, validation_retries


def create_app(context=None, provider=None, *, input_budget=7000, call_cap=1, validation_retries=0):
    if not 256 <= input_budget <= 16000 or not 0 <= call_cap <= 50 or validation_retries not in (0, 1):
        raise ValueError("Invalid LLM budget configuration")
    slots = BoundedSemaphore(2)
    lock = Lock()
    saved = OrderedDict()
    calls = 0

    @asynccontextmanager
    async def lifespan(app):
        app.state.provider = provider if provider is not None else configured_provider()
        try:
            with httpx.Client(base_url=os.getenv("CONTEXT_API_URL", "http://127.0.0.1:8015"),
                              timeout=6.0, trust_env=False) as client:
                app.state.context = context if context is not None else ContextClient(client)
                yield
        finally:
            if isinstance(app.state.provider, (OpenAIProvider, GeminiProvider)):
                app.state.provider.close()

    app = FastAPI(title="Thesis LLM Analysis Service", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _exc):
        return error(422, "INVALID_ANALYSIS_REQUEST")

    @app.get("/health")
    def health():
        return {"status": "alive"}

    @app.get("/ready")
    def ready():
        runtime = app.state.provider
        if runtime is None:
            return error(503, "PROVIDER_NOT_CONFIGURED")
        if runtime.name == "gemini" and not gemini_smoke_authorized():
            return error(503, "GEMINI_SMOKE_APPROVAL_REQUIRED")
        cap, retries = provider_limits(runtime, call_cap, validation_retries)
        with lock:
            remaining = None if cap is None else cap - calls
            if remaining is not None and remaining <= 0:
                return error(503, "PROVIDER_CALL_BUDGET_EXHAUSTED")
        return {"status": "configured", "provider": runtime.name, "model": runtime.model,
                "prompt_version": PROMPT_VERSION, "input_budget": input_budget,
                "max_output_tokens": getattr(runtime, "max_output_tokens", None),
                "decoding": "model_defaults", "validation_retries": retries,
                "call_cap": cap,
                "calls_remaining": remaining}

    @app.get("/analysis/{analysis_id}", response_model=IncidentAnalysis)
    def get_analysis(analysis_id: str):
        with lock:
            report = saved.get(analysis_id)
        return report if report is not None else error(404, "ANALYSIS_NOT_FOUND")

    @app.post("/analyze/trace", response_model=IncidentAnalysis)
    def analyze(query: AnalysisRequest, x_required_provider: str | None = Header(default=None)):
        nonlocal calls
        if not valid_trace(query.trace_id) or (query.mode == "single_service") != (query.service_name is not None):
            return error(422, "INVALID_TRACE_OR_SCOPE")
        runtime = app.state.provider
        if runtime is None:
            return error(503, "PROVIDER_NOT_CONFIGURED")
        if x_required_provider is not None and runtime.name != x_required_provider:
            return error(503, "PROVIDER_SCOPE_MISMATCH")
        cap, retries = provider_limits(runtime, call_cap, validation_retries)
        if runtime.name == "gemini" and query.trace_id != runtime.trace_id:
            return error(403, "GEMINI_SMOKE_TRACE_NOT_AUTHORIZED")
        if not slots.acquire(blocking=False):
            return error(429, "ANALYSIS_CONCURRENCY_LIMIT")
        try:
            started = perf_counter()
            try:
                evidence = prepare(app.state.context.fetch(query), query, input_budget)
            except httpx.TimeoutException:
                return error(504, "CONTEXT_TIMEOUT")
            except httpx.HTTPStatusError as exc:
                return error(404, "CONTEXT_NOT_FOUND") if exc.response.status_code == 404 else error(502, "CONTEXT_ERROR")
            except httpx.HTTPError:
                return error(502, "CONTEXT_ERROR")
            except (ValueError, TypeError, KeyError):
                return error(502, "INVALID_CONTEXT")
            if not evidence.events:
                return error(422, "NO_EVIDENCE_FOR_ANALYSIS")
            usage = None
            for attempt in range(retries + 1):
                if cap is not None:
                    with lock:
                        if runtime.name == "gemini" and not gemini_smoke_authorized():
                            return error(503, "GEMINI_SMOKE_APPROVAL_REQUIRED")
                        if calls >= cap:
                            return error(429, "PROVIDER_CALL_BUDGET_EXHAUSTED")
                        calls += 1
                try:
                    result = runtime.generate(evidence)
                except ProviderFailure as exc:
                    return error(exc.status, exc.code)
                if result.usage is not None:
                    usage = {k: (usage or {}).get(k, 0) + v for k, v in result.usage.items()}
                try:
                    report, warnings = validate_model(result.body, evidence)
                    break
                except (ValueError, TypeError) as exc:
                    if attempt == retries:
                        if runtime.name == "gemini":
                            capture_status = capture_raw_gemini_response(result.raw_text, query.trace_id)
                            if capture_status != "DISABLED":
                                VALIDATION_DIAGNOSTICS.warning(
                                    "gemini_raw_capture status=%s", capture_status)
                        VALIDATION_DIAGNOSTICS.warning(
                            "llm_validation_failure %s",
                            json.dumps(validation_diagnostic(exc), separators=(",", ":")),
                        )
                        return error(502, "INVALID_MODEL_OUTPUT")
            if attempt:
                warnings.append("MODEL_VALIDATION_RETRIED")
            full = IncidentAnalysis(
                **report.model_dump(), analysis_id=uuid4().hex, trace_id=query.trace_id,
                analysis_mode=query.mode, selected_service=query.service_name, model_name=result.model,
                configured_model=runtime.model, provider=runtime.name, prompt_version=PROMPT_VERSION,
                provider_response_status=result.status if cap is not None else "mock",
                analysis_config_id=query.analysis_config_id, context_completeness=evidence.completeness,
                input_event_ids=list(evidence.events), omitted_event_ids=evidence.omitted,
                omitted_event_count=len(evidence.omitted), redacted_event_count=evidence.redacted,
                validation_status=("FACTS_CHECKED_HYPOTHESES_UNVERIFIED" if report.hypotheses or
                                   report.suspected_root_cause or report.evidence else "FACTS_CHECKED"),
                validation_warnings=warnings, token_usage=usage,
                processing_time_ms=round((perf_counter() - started) * 1000, 3),
            )
            with lock:
                saved[full.analysis_id] = full
                if len(saved) > 128:
                    saved.popitem(last=False)
            return full
        finally:
            slots.release()

    return app


app = create_app(input_budget=int(os.getenv("LLM_INPUT_BUDGET", "7000")),
                 call_cap=int(os.getenv("LLM_CALL_CAP", "1")),
                 validation_retries=int(os.getenv("LLM_VALIDATION_RETRIES", "0")))
