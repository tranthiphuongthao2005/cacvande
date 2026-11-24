"""OpenAI and Gemini adapters and deterministic test provider."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.llm_analysis import ModelAnalysis, PROMPT


GEMINI_DIAGNOSTICS = logging.getLogger("uvicorn.error").getChild("gemini")
GOOGLE_ERROR_STATUS = frozenset({
    "INVALID_ARGUMENT", "FAILED_PRECONDITION", "UNAUTHENTICATED", "PERMISSION_DENIED",
    "NOT_FOUND", "RESOURCE_EXHAUSTED", "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED",
})


class ProviderFailure(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status


@dataclass(frozen=True)
class ProviderResult:
    body: object
    model: str
    usage: dict | None
    status: str = "completed"


class OpenAIProvider:
    name = "openai"

    def __init__(self, key, model, max_output_tokens):
        from openai import OpenAI

        self.model = model
        self.max_output_tokens = max_output_tokens
        self.client = OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=20.0, max_retries=0)

    def generate(self, prepared):
        from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
        from pydantic import ValidationError

        try:
            response = self.client.responses.parse(
                model=self.model, instructions=PROMPT, input=prepared.payload,
                text_format=ModelAnalysis, max_output_tokens=self.max_output_tokens, store=False,
            )
        except APITimeoutError:
            raise ProviderFailure("PROVIDER_TIMEOUT", 504) from None
        except RateLimitError:
            raise ProviderFailure("PROVIDER_RATE_LIMITED", 503) from None
        except (APIConnectionError, APIStatusError):
            raise ProviderFailure("PROVIDER_ERROR") from None
        except ValidationError:
            raise ProviderFailure("INVALID_MODEL_OUTPUT") from None
        usage = response.usage
        tokens = None if usage is None else {
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
        if response.status != "completed" or response.output_parsed is None:
            raise ProviderFailure("PROVIDER_NO_STRUCTURED_RESULT")
        return ProviderResult(response.output_parsed, response.model, tokens)

    def close(self):
        self.client.close()


class GeminiProvider:
    name = "gemini"
    free_tier_model = "gemini-3.1-flash-lite"

    def __init__(self, key, model, max_output_tokens, trace_id):
        from google import genai
        from google.genai import types

        self.model = model
        self.trace_id = trace_id
        self.max_output_tokens = max_output_tokens
        self.config = types.GenerateContentConfig(
            system_instruction=PROMPT, response_mime_type="application/json",
            response_json_schema=ModelAnalysis.model_json_schema(),
            max_output_tokens=max_output_tokens, candidate_count=1,
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.client = genai.Client(
            api_key=key, vertexai=False,
            http_options=types.HttpOptions(
                base_url="https://generativelanguage.googleapis.com", api_version="v1beta",
                timeout=20000, retry_options=types.HttpRetryOptions(attempts=1),
                client_args={"trust_env": False, "follow_redirects": False},
            ),
        )

    def generate(self, prepared):
        import httpx
        from google.genai.errors import APIError
        from pydantic import ValidationError

        attempt_id = uuid4().hex
        started = perf_counter()

        def failure(exc, category, stage, message, *, upstream=None, provider_code=None,
                    receipt="UNKNOWN", retryable=None, public_code="PROVIDER_ERROR", public_status=502):
            # SDK exception messages may include URLs, provider bodies or input data.
            # Emit only curated text and typed/allowlisted metadata.
            GEMINI_DIAGNOSTICS.warning("gemini_provider_failure %s", json.dumps({
                "attempt_id": attempt_id,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                "requested_model": self.model,
                "category": category,
                "failure_stage": stage,
                "exception_class": type(exc).__name__ if exc is not None else None,
                "sanitized_error_message": message,
                "upstream_http_status": upstream,
                "provider_error_code": provider_code,
                "receipt_status": receipt,
                "retryable": retryable,
            }))
            return ProviderFailure(public_code, public_status)

        try:
            response = self.client.models.generate_content(
                model=self.model, contents=prepared.payload, config=self.config,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise failure(exc, "PROVIDER_TIMEOUT", "transport", "Transport timed out",
                          retryable=True, public_code="PROVIDER_TIMEOUT", public_status=504) from None
        except APIError as exc:
            category, message, retryable = classify_gemini_api_error(exc, self.model)
            public_code, public_status = {
                429: ("PROVIDER_RATE_LIMITED", 503),
                408: ("PROVIDER_TIMEOUT", 504),
                504: ("PROVIDER_TIMEOUT", 504),
            }.get(exc.code, ("PROVIDER_ERROR", 502))
            upstream = exc.response.status_code if isinstance(exc.response, httpx.Response) else None
            provider_code = exc.status if isinstance(exc.status, str) and exc.status in GOOGLE_ERROR_STATUS else None
            raise failure(exc, category, "upstream_response", message, upstream=upstream,
                          provider_code=provider_code, receipt="CONFIRMED" if upstream else "UNKNOWN",
                          retryable=retryable, public_code=public_code, public_status=public_status) from None
        except (json.JSONDecodeError, ValidationError) as exc:
            raise failure(exc, "PROVIDER_RESPONSE_PARSE_ERROR", "sdk", "SDK could not decode or validate data") from None
        except httpx.NetworkError as exc:
            raise failure(exc, "PROVIDER_NETWORK_ERROR", "transport", "Network connection or I/O failed") from None
        except httpx.HTTPError as exc:
            raise failure(exc, "PROVIDER_NETWORK_ERROR", "transport", "HTTP transport failed") from None
        except (ValueError, TypeError) as exc:
            raise failure(exc, "PROVIDER_UNKNOWN_ERROR", "sdk", "SDK rejected a value or type") from None

        if (not response.candidates or response.candidates[0].finish_reason != "STOP"
                or not response.text):
            raise failure(None, "PROVIDER_RESPONSE_PARSE_ERROR", "structured_response",
                          "No complete structured candidate", receipt="CONFIRMED",
                          public_code="PROVIDER_NO_STRUCTURED_RESULT")
        try:
            body = ModelAnalysis.model_validate_json(response.text)
        except ValidationError as exc:
            raise failure(exc, "PROVIDER_RESPONSE_PARSE_ERROR", "canonical_validation",
                          "Candidate failed canonical JSON validation", receipt="CONFIRMED",
                          public_code="INVALID_MODEL_OUTPUT") from None

        usage = response.usage_metadata
        tokens = None if usage is None else {
            k: v for k, v in {
                "input_tokens": usage.prompt_token_count,
                "output_tokens": usage.candidates_token_count,
                "thinking_tokens": usage.thoughts_token_count,
                "total_tokens": usage.total_token_count,
            }.items() if v is not None
        }
        return ProviderResult(body, response.model_version or self.model, tokens)

    def close(self):
        self.client.close()


def classify_gemini_api_error(exc, model):
    code = exc.code
    message = exc.message.casefold() if isinstance(exc.message, str) else ""
    if code == 400 and exc.status == "INVALID_ARGUMENT":
        if any(field in message for field in ("response_json_schema", "responsejsonschema",
                                              "response_schema", "responseschema")):
            return "PROVIDER_SCHEMA_ERROR", "Upstream identified the response schema", False
    if code == 404 and exc.status == "NOT_FOUND" and f"models/{model.casefold()}" in message:
        if "not found" in message:
            return "PROVIDER_MODEL_NOT_FOUND", "Upstream reported the requested model was not found", False
    if isinstance(code, int) and 500 <= code <= 599 and code != 504:
        return "PROVIDER_UPSTREAM_ERROR", "Upstream reported a server error", True
    return {
        400: ("PROVIDER_INVALID_REQUEST", "Upstream rejected the request", False),
        401: ("PROVIDER_AUTH_ERROR", "Upstream rejected authentication", False),
        403: ("PROVIDER_PERMISSION_ERROR", "Upstream denied permission", False),
        408: ("PROVIDER_TIMEOUT", "Upstream reported a timeout", True),
        429: ("PROVIDER_RATE_LIMIT", "Upstream reported a rate or quota limit", None),
        504: ("PROVIDER_TIMEOUT", "Upstream reported a timeout", True),
    }.get(code, ("PROVIDER_UNKNOWN_ERROR", "Upstream error could not be classified", None))


class MockProvider:
    name = "mock"
    model = "mock-rca-v1"

    def generate(self, prepared):
        observations = [
            {"event_id": event["event_id"], "service_name": event["service_name"],
             "kind": "status", "value": str(event["status_code"])}
            for event in prepared.events.values() if event["status_code"] is not None
        ]
        return ProviderResult({
            "analysis_status": "INSUFFICIENT_EVIDENCE",
            "suspected_root_cause": None,
            "suspected_root_cause_service": None,
            "affected_services": [],
            "observations": observations,
            "hypotheses": [],
            "evidence": [{"event_id": item["event_id"], "service_name": item["service_name"],
                          "observation": item, "supports_claim": "Observed HTTP status"} for item in observations],
            "missing_information": ["Validated parent span links and upstream diagnostics"],
            "recommended_checks": ["Inspect the referenced request completions and upstream spans"],
            "suggested_remediations": [],
            "limitations": ["Deterministic mock output for contract verification"],
        }, self.model, None)
