import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm_analysis import AnalysisRequest, prepare
from app.llm_api import create_app
from app.llm_provider import GEMINI_DIAGNOSTICS, GeminiProvider, MockProvider, OpenAIProvider
from test_llm import TRACE, context


@pytest.fixture
def authorized(monkeypatch):
    configuration = {
        "LLM_PROVIDER": "gemini",
        "LLM_MODEL": GeminiProvider.free_tier_model,
        "GEMINI_API_KEY": "fixture-only",
        "LLM_ALLOW_EXTERNAL": "1",
        "LLM_GEMINI_FREE_TIER_CONFIRMED": "1",
        "LLM_GEMINI_SMOKE_APPROVAL_ID": "fixture-only",
        "LLM_GEMINI_SMOKE_EXPIRES_UTC": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "LLM_GEMINI_SMOKE_TRACE_ID": TRACE,
    }
    for field, value in configuration.items():
        monkeypatch.setenv(field, value)


@pytest.mark.parametrize("missing", [
    "GEMINI_API_KEY", "LLM_ALLOW_EXTERNAL", "LLM_GEMINI_FREE_TIER_CONFIRMED",
    "LLM_GEMINI_SMOKE_APPROVAL_ID", "LLM_GEMINI_SMOKE_EXPIRES_UTC",
    "LLM_GEMINI_SMOKE_TRACE_ID",
])
def test_missing_configuration_blocks_provider(authorized, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with TestClient(create_app()) as client:
        assert client.get("/ready").status_code == 503


@pytest.fixture
def offline_sdk(monkeypatch):
    from google import genai

    sdk_client = genai.Client

    def install(handler):
        requests = []

        def send(request):
            requests.append(request)
            return handler(request)

        def init(**kwargs):
            options = kwargs["http_options"]
            assert options.retry_options.attempts == 1
            options.httpx_client = httpx.Client(transport=httpx.MockTransport(send))
            return sdk_client(**kwargs)

        monkeypatch.setattr(genai, "Client", init)
        return requests

    return install


def test_sdk_structured_request_scope_and_two_call_cap(authorized, offline_sdk):
    def succeeded(request):
        body = json.loads(request.content)
        config = body["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert config["responseJsonSchema"]["type"] == "object"
        assert config["maxOutputTokens"] == 1200
        assert config["thinkingConfig"]["thinking_level"] == "MINIMAL"
        assert body["systemInstruction"]["parts"][0]["text"]
        assert request.url.path.endswith("/models/gemini-3.1-flash-lite:generateContent")
        assert "tools" not in body
        payload = json.loads(body["contents"][0]["parts"][0]["text"])
        scope = len(payload["events"])
        query = AnalysisRequest(trace_id=TRACE) if scope > 1 else AnalysisRequest(
            trace_id=TRACE, mode="single_service", service_name="order")
        result = MockProvider().generate(prepare(context(query), query, 7000))
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {"role": "model",
                            "parts": [{"text": json.dumps(result.body)}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3,
                              "thoughtsTokenCount": 2, "totalTokenCount": 17},
            "modelVersion": GeminiProvider.free_tier_model,
        })

    requests = offline_sdk(succeeded)
    with TestClient(create_app(SimpleNamespace(fetch=context), call_cap=50, validation_retries=1)) as client:
        ready = client.get("/ready").json()
        assert (ready["call_cap"], ready["validation_retries"]) == (2, 0)
        assert client.post("/analyze/trace", json={"trace_id": "c" * 32}).status_code == 403
        for params, count in [({"mode": "single_service", "service_name": "order"}, 1), ({}, 3)]:
            response = client.post("/analyze/trace", json={"trace_id": TRACE, **params})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["provider"] == "gemini" and len(result["input_event_ids"]) == count
            assert result["token_usage"]["thinking_tokens"] == 2
        assert client.post("/analyze/trace", json={"trace_id": TRACE}).status_code == 429
    assert len(requests) == 2
    assert all(r.url.host == "generativelanguage.googleapis.com" for r in requests)


@pytest.mark.parametrize(("failure", "code"), [
    ("quota", "PROVIDER_RATE_LIMITED"), ("timeout", "PROVIDER_TIMEOUT"),
    ("invalid_json", "INVALID_MODEL_OUTPUT"),
])
def test_sdk_does_not_retry_or_disclose_errors(authorized, offline_sdk, failure, code):
    def failed(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private fixture", request=request)
        if failure == "quota":
            return httpx.Response(429, json={"error": {"code": 429, "message": "private fixture"}})
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": "{}"}]},
        }]})

    requests = offline_sdk(failed)
    with TestClient(create_app(SimpleNamespace(fetch=context), call_cap=2, validation_retries=1)) as client:
        response = client.post("/analyze/trace", json={"trace_id": TRACE})
        assert response.json() == {"error": {"code": code}}
    assert len(requests) == 1


@pytest.mark.parametrize(("upstream", "provider_status", "message", "category", "public_status", "public_code"), [
    (400, "INVALID_ARGUMENT", "invalid argument", "PROVIDER_INVALID_REQUEST", 502, "PROVIDER_ERROR"),
    (400, "INVALID_ARGUMENT", "generationConfig.responseJsonSchema", "PROVIDER_SCHEMA_ERROR", 502, "PROVIDER_ERROR"),
    (401, "UNAUTHENTICATED", "invalid credential", "PROVIDER_AUTH_ERROR", 502, "PROVIDER_ERROR"),
    (403, "PERMISSION_DENIED", "permission denied", "PROVIDER_PERMISSION_ERROR", 502, "PROVIDER_ERROR"),
    (404, "NOT_FOUND", "models/gemini-3.1-flash-lite not found", "PROVIDER_MODEL_NOT_FOUND", 502, "PROVIDER_ERROR"),
    (404, "NOT_FOUND", "other resource not found", "PROVIDER_UNKNOWN_ERROR", 502, "PROVIDER_ERROR"),
    (429, "RESOURCE_EXHAUSTED", "quota limit", "PROVIDER_RATE_LIMIT", 503, "PROVIDER_RATE_LIMITED"),
    (500, "INTERNAL", "internal error", "PROVIDER_UPSTREAM_ERROR", 502, "PROVIDER_ERROR"),
    (503, "UNAVAILABLE", "service unavailable", "PROVIDER_UPSTREAM_ERROR", 502, "PROVIDER_ERROR"),
    (504, "DEADLINE_EXCEEDED", "timed out", "PROVIDER_TIMEOUT", 504, "PROVIDER_TIMEOUT"),
])
def test_upstream_diagnostics_preserve_public_contract(
        authorized, offline_sdk, caplog, monkeypatch, upstream, provider_status, message,
        category, public_status, public_code):
    def unexpected_fallback(*args, **kwargs):
        pytest.fail("Provider fallback")

    monkeypatch.setattr(MockProvider, "generate", unexpected_fallback)
    monkeypatch.setattr(OpenAIProvider, "__init__", unexpected_fallback)
    secret = "https://example.invalid/?key=private-fixture; Authorization: Bearer hidden-token; student@example.invalid"
    requests = offline_sdk(lambda _: httpx.Response(upstream, json={"error": {
        "code": upstream, "status": provider_status, "message": f"{message} {secret}",
        "details": [{"ground_truth": "raw-private-label"}],
    }}))
    with TestClient(create_app(SimpleNamespace(fetch=context), call_cap=2, validation_retries=1)) as client:
        response = client.post("/analyze/trace", json={"trace_id": TRACE},
                               headers={"X-Required-Provider": "gemini"})
        assert response.status_code == public_status
        assert response.json() == {"error": {"code": public_code}}
        assert client.get("/ready").json()["calls_remaining"] == 1
    assert len(requests) == 1
    record, = [rec for rec in caplog.records if rec.name == GEMINI_DIAGNOSTICS.name]
    details = json.loads(record.getMessage().split(" ", 1)[1])
    assert (details["category"], details["upstream_http_status"], details["provider_error_code"],
            details["receipt_status"]) == (category, upstream, provider_status, "CONFIRMED")
    assert details["exception_class"] in {"ClientError", "ServerError"}
    assert details["attempt_id"] and details["timestamp_utc"] and details["duration_ms"] >= 0
    assert all(value not in caplog.text + response.text for value in (
        "private-fixture", "hidden-token", "student@example.invalid", "raw-private-label", "fixture-only",
    ))


@pytest.mark.parametrize(("case", "category", "receipt"), [
    ("connect", "PROVIDER_NETWORK_ERROR", "UNKNOWN"),
    ("timeout", "PROVIDER_TIMEOUT", "UNKNOWN"),
    ("invalid_envelope", "PROVIDER_RESPONSE_PARSE_ERROR", "UNKNOWN"),
    ("invalid_candidate", "PROVIDER_RESPONSE_PARSE_ERROR", "CONFIRMED"),
])
def test_network_and_malformed_diagnostics(authorized, offline_sdk, caplog, case, category, receipt):
    def fail(request):
        if case == "connect":
            raise httpx.ConnectError("private DNS detail", request=request)
        if case == "timeout":
            raise httpx.ReadTimeout("private timeout detail", request=request)
        if case == "invalid_envelope":
            return httpx.Response(200, content=b"private non-JSON detail")
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": "private candidate detail"}]},
        }]})

    requests = offline_sdk(fail)
    with TestClient(create_app(SimpleNamespace(fetch=context), call_cap=2, validation_retries=1)) as client:
        assert client.post("/analyze/trace", json={"trace_id": TRACE}).status_code in {502, 504}
    assert len(requests) == 1
    record, = [rec for rec in caplog.records if rec.name == GEMINI_DIAGNOSTICS.name]
    details = json.loads(record.getMessage().split(" ", 1)[1])
    assert (details["category"], details["receipt_status"]) == (category, receipt)
    assert "private" not in caplog.text
