"""Read the bounded, evidence-only cross-service Context API response."""

import asyncio
import json
from datetime import datetime

import httpx
from pydantic import ValidationError

from app.context_integration_models import ContextValidationError, context_payload

TRANSIENT = {408, 429, 500, 502, 503, 504}


class ContextFailure(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.retryable = retryable


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ContextValidationError("DUPLICATE_CONTEXT_FIELD")
    return result


class ContextClient:
    def __init__(self, client, settings):
        self.client = client
        self.settings = settings

    async def ready(self):
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                async with self.client.stream("GET", "/ready") as response:
                    return response.status_code == 200
        except (TimeoutError, httpx.HTTPError):
            return False

    async def retrieve(self, trace_id):
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                async with self.client.stream("GET", f"/context/trace/{trace_id}",
                                              params={"mode": "cross_service", "wait_ms": 0}) as response:
                    status = response.status_code
                    if status != 200:
                        code = "CONTEXT_TRACE_NOT_FOUND" if status == 404 else f"CONTEXT_HTTP_{status}"
                        raise ContextFailure(code, status in TRANSIENT)
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        if len(buffer) + len(chunk) > self.settings.max_payload_bytes:
                            raise ContextFailure("CONTEXT_PAYLOAD_TOO_LARGE")
                        buffer.extend(chunk)
        except (TimeoutError, httpx.TimeoutException):
            raise ContextFailure("CONTEXT_TIMEOUT", True) from None
        except httpx.TransportError:
            raise ContextFailure("CONTEXT_UNAVAILABLE", True) from None
        except httpx.HTTPError:
            raise ContextFailure("INVALID_CONTEXT_RESPONSE") from None

        try:
            return context_payload(json.loads(buffer, object_pairs_hook=unique_object), trace_id)
        except ContextValidationError as exc:
            raise ContextFailure(exc.code) from None
        except (ValueError, ValidationError, RecursionError):
            raise ContextFailure("INVALID_CONTEXT_RESPONSE") from None
