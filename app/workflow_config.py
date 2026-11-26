"""Fail-closed configuration for the isolated mock workflow."""

import os

from pydantic import Field, SecretStr, model_validator

from app.contracts import StrictRecord

ORIGINS = {"http://workflow-n8n:5678", "http://127.0.0.1:15678"}
WEBHOOK_PATH = "/webhook/detection-incident"


class Settings(StrictRecord):
    dispatch_enabled: bool = False
    dispatch_dry_run: bool = False
    n8n_url: str | None = None
    webhook_token: SecretStr | None = None
    storage_path: str = Field(default="monitoring.sqlite", min_length=1)
    poll_interval_seconds: float = Field(default=5, ge=.1, le=600)
    batch_size: int = Field(default=16, ge=1, le=256)
    max_concurrency: int = Field(default=2, ge=1, le=8)
    timeout_seconds: float = Field(default=25, ge=.1, le=60)
    max_retries: int = Field(default=2, ge=0, le=6)
    retry_backoff_seconds: float = Field(default=10, ge=.1, le=600)
    max_payload_bytes: int = Field(default=524288, ge=1024, le=900000)
    analysis_provider: str = "mock"
    external_allowed: bool = False

    @model_validator(mode="after")
    def scope(self):
        if self.external_allowed or self.analysis_provider != "mock":
            raise ValueError("Only isolated mock execution is permitted")
        if self.n8n_url is not None and self.n8n_url not in ORIGINS:
            raise ValueError("Unapproved n8n origin")
        if self.dispatch_enabled and not self.dispatch_dry_run and (not self.n8n_url or not self.secret()):
            raise ValueError("Explicit isolated n8n origin and token required")
        if not self.storage_path.strip() or self.storage_path == ":memory:":
            raise ValueError("Persistent SQLite path required")
        return self

    def secret(self):
        if self.webhook_token is None:
            return None
        token = self.webhook_token.get_secret_value()
        return token if 24 <= len(token) <= 256 and token.isascii() and token.isprintable() and not any(
            c.isspace() for c in token
        ) else None

    @classmethod
    def from_env(cls):
        return cls.model_validate({name: os.environ[key] for name in cls.model_fields
                                   if (key := f"WORKFLOW_{name.upper()}") in os.environ})
