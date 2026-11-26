"""Validated configuration for the independent monitoring process."""

import hashlib
import json
import os
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator

from app.contracts import StrictRecord

VERSION = "1.0.0"


class Settings(StrictRecord):
    enabled: bool = False
    dry_run: bool = False
    es_url: str | None = None
    es_api_key: SecretStr | None = None
    es_index: str = Field(default="thesis-logs-*", pattern=r"^[a-z0-9][a-z0-9_.-]*\*?$")
    detection_url: str | None = None
    storage_path: str = Field(default="monitoring.sqlite", min_length=1)
    start_policy: Literal["START_FROM_NOW", "RESUME_CHECKPOINT", "EXPLICIT_LOOKBACK"] = "START_FROM_NOW"
    lookback_seconds: int = Field(default=0, ge=0, le=86400)
    overlap_seconds: int = Field(default=300, ge=1, le=86400)
    poll_interval_seconds: float = Field(default=5, ge=.1, le=3600)
    batch_size: int = Field(default=128, ge=1, le=1000)
    max_pages: int = Field(default=32, ge=1, le=500)
    poll_timeout_seconds: float = Field(default=15, ge=.1, le=120)
    quiet_period_seconds: float = Field(default=5, ge=0, le=3600)
    max_trace_wait_seconds: float = Field(default=30, ge=1, le=7200)
    max_concurrent_traces: int = Field(default=2, ge=1, le=32)
    detection_timeout_seconds: float = Field(default=12, ge=.1, le=120)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=10, ge=.1, le=600)
    timeout_cooldown_seconds: float = Field(default=90, ge=60, le=3600)
    retention_seconds: int = Field(default=604800, ge=1)

    @model_validator(mode="after")
    def validate_operating_scope(self):
        has_key = self.es_api_key is not None and bool(self.es_api_key.get_secret_value().strip())
        if self.enabled and not all((self.es_url, has_key, self.detection_url or self.dry_run)):
            raise ValueError("Enabled monitoring needs explicit Elasticsearch and detection configuration")
        if self.storage_path == ":memory:" or not self.storage_path.strip():
            raise ValueError("Monitoring requires a persistent SQLite path")
        for url in (self.es_url, self.detection_url):
            if url is not None:
                parts = urlsplit(url)
                if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
                        or parts.password is not None or parts.path not in {"", "/"} or parts.query or parts.fragment):
                    raise ValueError("Use an HTTP(S) service origin without credentials or a path")
                _ = parts.port
        if (self.start_policy == "EXPLICIT_LOOKBACK") != (self.lookback_seconds > 0):
            raise ValueError("A bounded lookback is only valid for EXPLICIT_LOOKBACK")
        if self.quiet_period_seconds > self.max_trace_wait_seconds:
            raise ValueError("Quiet period exceeds maximum trace wait")
        if self.retention_seconds <= max(self.overlap_seconds, self.detection_timeout_seconds
                                         + self.timeout_cooldown_seconds, self.max_trace_wait_seconds):
            raise ValueError("Retention must exceed overlap, trace wait and detection cooldown")
        return self

    @classmethod
    def from_env(cls):
        return cls.model_validate({name: os.environ[key] for name in cls.model_fields
                                   if (key := f"MONITORING_{name.upper()}") in os.environ})

    def fingerprint(self):
        # Bind cursor identity to the source and time semantics, not operational tuning or credentials.
        source = [VERSION, (self.es_url or "").rstrip("/"), self.es_index, self.overlap_seconds,
                  (self.detection_url or "").rstrip("/")]
        return hashlib.sha256(json.dumps(source).encode()).hexdigest()
