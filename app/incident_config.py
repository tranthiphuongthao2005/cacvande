"""Configuration for the internal incident API and replay-safe handoff."""

import os

from pydantic import ConfigDict, Field, SecretStr, model_validator

from app.contracts import StrictRecord


class Settings(StrictRecord):
    model_config = ConfigDict(hide_input_in_errors=True)

    management_enabled: bool = False
    handoff_enabled: bool = False
    storage_path: str = Field(default="incidents.sqlite", min_length=1)
    source_storage_path: str | None = None
    api_token: SecretStr | None = None
    read_token: SecretStr | None = None
    operator_id: str = Field(default="internal-operator", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    poll_interval_seconds: float = Field(default=5, ge=.1, le=600)
    batch_size: int = Field(default=32, ge=1, le=256)
    max_retries: int = Field(default=3, ge=0, le=8)
    retry_backoff_seconds: float = Field(default=5, ge=.1, le=600)
    max_page_size: int = Field(default=100, ge=1, le=200)
    max_payload_bytes: int = Field(default=4096, ge=512, le=65536)

    @model_validator(mode="after")
    def validate_scope(self):
        tokens = [value.get_secret_value() for value in (self.api_token, self.read_token) if value is not None]
        if any(not (32 <= len(t) <= 256 and t.isascii() and t.isprintable() and not any(
            c.isspace() for c in t
        )) for t in tokens) or len(set(tokens)) != len(tokens):
            raise ValueError("Use separate, strong internal tokens")
        if self.management_enabled and self.api_token is None:
            raise ValueError("Internal operator token required")
        if self.handoff_enabled and (not self.management_enabled or not self.source_storage_path):
            raise ValueError("Enabled handoff requires management and an upstream SQLite file")
        if any(path is not None and (not path.strip() or path == ":memory:") for path in
               (self.storage_path, self.source_storage_path)):
            raise ValueError("Persistent SQLite paths required")
        return self

    @classmethod
    def from_env(cls):
        values = {name: os.environ[key] for name in cls.model_fields
                  if (key := f"INCIDENT_{name.upper()}") in os.environ}
        for optional in ("api_token", "read_token"):
            if values.get(optional) == "":
                del values[optional]
        return cls.model_validate(values)
