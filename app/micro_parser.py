"""Deterministic event catalog for diagnostics with the frozen encoder."""

from dataclasses import dataclass

from app.trace_store import EVENTS, SERVICES

CATALOG_VERSION = "micro-observed-v1"
CATALOG = {event: event.replace("_", " ") for event in EVENTS}
@dataclass(frozen=True)
class ParsedEvent:
    trace_id: str
    event_id: str
    template: str
    status: int | None
    unknown_template: bool


def parse_event(trace_id, event):
    """Use the observed message; event_name alone cannot override an unknown message."""
    message = " ".join(event.message.split())
    known = event.service_name in SERVICES and message in CATALOG and message == event.event_name
    template = f"{event.service_name} {CATALOG[message]}" if known else "unknown application event"
    return ParsedEvent(trace_id, event.event_id, template, event.http_status, not known)


def typed_features(parsed, *, positional=False):
    from preprocess.parameters import Parameter, NUM

    if parsed.status is None:
        return ()
    return (Parameter("pos:1" if positional else "key:status", str(parsed.status), NUM),)
