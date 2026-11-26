"""Version-one collector-to-detection contract, independent of model runtime."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

TraceId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
SpanId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceMetadata(StrictRecord):
    collector: Text
    environment: Text
    sessionization_version: Literal["trace-v1"] = "trace-v1"
    completeness: Literal["complete", "partial"]
    dropped_events: int = Field(default=0, ge=0)


class LogEvent(StrictRecord):
    event_id: Text
    timestamp: AwareDatetime
    service_name: Text
    span_id: SpanId | None = None
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    event_name: Text
    message: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    http_status: int | None = Field(default=None, ge=100, le=599)


class DetectionSession(StrictRecord):
    session_id: Text
    trace_id: TraceId
    service_name: Text
    start_time: AwareDatetime
    end_time: AwareDatetime
    events: list[LogEvent] = Field(min_length=1, max_length=2048)
    source_metadata: SourceMetadata

    @model_validator(mode="after")
    def check_time_and_identity(self):
        if self.trace_id == "0" * 32:
            raise ValueError("zero trace ID")
        times = [event.timestamp for event in self.events]
        if times != sorted(times) or times[0] < self.start_time or times[-1] > self.end_time:
            raise ValueError("events must be ordered and lie within the session")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("event IDs must be unique within the session")
        return self
