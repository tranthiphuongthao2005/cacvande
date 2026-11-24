import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from uuid import uuid4

from app.producer_accounting import enabled

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

propagator = TraceContextTextMapPropagator()
request_id = ContextVar("request_id", default=None)


class EventIdentity(logging.Filter):
    def __init__(self, accounting=None):
        super().__init__()
        self.accounting = accounting

    def filter(self, record):
        record.event_id = uuid4().hex
        ctx = trace.get_current_span().get_span_context()
        if (self.accounting and ctx.is_valid and f"{ctx.trace_id:032x}" == self.accounting.trace_id
                and getattr(record, "service", record.name) == self.accounting.service):
            self.accounting.create(record.event_id, datetime.fromtimestamp(record.created, timezone.utc).isoformat())
            record.accounting = self.accounting
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        ctx = trace.get_current_span().get_span_context()
        return json.dumps({
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "event_id": record.event_id,
            "level": record.levelname,
            "service": getattr(record, "service", record.name),
            "event": record.getMessage(),
            "trace_id": f"{ctx.trace_id:032x}" if ctx.is_valid else None,
            "span_id": f"{ctx.span_id:016x}" if ctx.is_valid else None,
            "request_id": request_id.get(),
            **getattr(record, "fields", {}),
        })


class AccountedWrite:
    def emit(self, record):
        tracker = getattr(record, "accounting", None)
        if tracker is None:
            return super().emit(record)
        state, payload = "WRITE_FAILED", None
        try:
            if self.sink == "file":
                if self.shouldRollover(record):
                    self.doRollover()
                if self.stream is None:
                    self.stream = self._open()
            payload = self.format(record)
            self.stream.write(payload + self.terminator)
            state = "FLUSH_FAILED"
            self.flush()
            state = "LOG_FLUSHED"
        except Exception:
            self.handleError(record)
        finally:
            tracker.outcome(record.event_id, self.sink, state, payload)


class AccountedStream(AccountedWrite, logging.StreamHandler):
    sink = "stderr"


class AccountedFile(AccountedWrite, RotatingFileHandler):
    sink = "file"


def logger():
    log = logging.getLogger("thesis")
    if not log.handlers:
        accounting = enabled()
        stream = AccountedStream() if accounting else logging.StreamHandler()
        stream.setFormatter(JsonFormatter())
        log.addHandler(stream)
        log.addFilter(EventIdentity(accounting))
        if path := os.getenv("APP_LOG_PATH"):
            handler = AccountedFile if accounting else RotatingFileHandler
            file = handler(path, maxBytes=5 * 2**20, backupCount=3, encoding="utf-8")
            file.setFormatter(JsonFormatter())
            log.addHandler(file)
        log.propagate = False
        log.setLevel(logging.INFO)
    return log


def provider(service, export_stdout):
    result = TracerProvider(resource=Resource.create({"service.name": service}))
    if export_stdout:
        exporter = ConsoleSpanExporter(formatter=lambda span: span.to_json(indent=None) + "\n")
        result.add_span_processor(SimpleSpanProcessor(exporter))
    return result
