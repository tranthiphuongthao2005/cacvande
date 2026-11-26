"""Consume committed monitoring results and build durable context packages."""

import argparse
import asyncio
import os
import signal
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from pydantic import Field, ValidationError, model_validator

from app.context_integration_client import ContextClient, ContextFailure
from app.context_integration_models import build_package, canonical, gate, validate_detection
from app.context_integration_store import ContextPackageStore, StorageFailure
from app.contracts import StrictRecord
from app.monitoring_models import DetectionEvent
from app.monitoring_worker import report


class Settings(StrictRecord):
    enabled: bool = False
    dry_run: bool = False
    url: str | None = None
    storage_path: str = Field(default="monitoring.sqlite", min_length=1)
    namespace: str = Field(default="local", pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    poll_interval_seconds: float = Field(default=5, ge=.1, le=3600)
    batch_size: int = Field(default=16, ge=1, le=500)
    timeout_seconds: float = Field(default=12, ge=.1, le=120)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=10, ge=.1, le=600)
    max_concurrency: int = Field(default=2, ge=1, le=32)
    retention_seconds: int = Field(default=604800, ge=300)
    max_payload_bytes: int = Field(default=1048576, ge=256, le=8388608)

    @model_validator(mode="after")
    def scope(self):
        if self.enabled and not self.dry_run and not self.url:
            raise ValueError("Enabled context integration requires a Context API URL")
        if not self.storage_path.strip() or self.storage_path == ":memory:":
            raise ValueError("Use a persistent monitoring database")
        if self.url is not None:
            origin = urlsplit(self.url)
            if (origin.scheme not in {"http", "https"} or not origin.hostname or origin.username is not None
                    or origin.password is not None or origin.query or origin.fragment or origin.path not in {"", "/"}):
                raise ValueError("Use a service origin without credentials or a path")
            _ = origin.port
        return self

    @classmethod
    def from_env(cls):
        return cls.model_validate({name: os.environ[key] for name in cls.model_fields
                                   if (key := f"CONTEXT_INTEGRATION_{name.upper()}") in os.environ})


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc)


class Worker:
    def __init__(self, settings, store, client, *, clock=time.time):
        self.settings, self.store, self.client = settings, store, client
        self.clock = clock
        self.stopping = asyncio.Event()

    async def process(self, claim):
        started = time.perf_counter()
        retrieval = 0

        def finish(**fields):
            return self.store.finish(claim, self.clock(), retrieval_ms=retrieval,
                                     processing_ms=(time.perf_counter() - started) * 1000, **fields)

        try:
            event = DetectionEvent.model_validate_json(claim.document)
            validate_detection(event)
            if (event.detection_event_id, event.trace_id, event.trace_version) != (
                claim.event_id, claim.trace_id, claim.trace_version
            ):
                raise ValueError("Detection job identity mismatch")
        except ValueError:
            finish(error="INVALID_DETECTION_EVENT")
            return "INVALID_DETECTION_EVENT"
        reason = gate(event)
        if reason:
            finish(error=reason, skipped=True)
            return None

        read_started = time.perf_counter()
        try:
            context = await self.client.retrieve(event.trace_id)
        except ContextFailure as failure:
            retrieval = (time.perf_counter() - read_started) * 1000
            finish(error=str(failure), retry=failure.retryable)
            report("context_retrieval_failure", trace_id=claim.trace_id, code=str(failure), attempt=claim.attempt)
            return str(failure)
        retrieval = (time.perf_counter() - read_started) * 1000
        retrieved_at = utc(self.clock())
        observed, prior = self.store.context_inputs(claim)
        package = build_package(event, context, claim, observed, self.settings.namespace, retrieved_at,
                                utc(self.clock()), prior)
        if len(canonical(package.context_payload.model_dump(mode="json"))) > self.settings.max_payload_bytes:
            finish(error="CONTEXT_PAYLOAD_TOO_LARGE")
            return "CONTEXT_PAYLOAD_TOO_LARGE"
        saved = finish(package=package)
        report("context_package_processed", trace_id=event.trace_id, trace_version=event.trace_version,
               readiness=package.analysis_readiness, persisted=saved)
        return "CONTEXT_STORED" if saved else None

    async def tick(self):
        if self.stopping.is_set():
            return []
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(self.process(claim)) for claim in self.store.claims(self.clock())]
        return [task.result() for task in tasks]

    async def run(self, *, once=False):
        if not self.settings.enabled:
            report("context_integration_status", state="DISABLED", ready=False)
            return
        if self.settings.dry_run:
            with self.store.connection() as db:
                installed = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_jobs'").fetchone()
                count = db.execute("SELECT count(*) FROM context_jobs WHERE state IN "
                                   "('PENDING_CONTEXT','CONTEXT_RETRY_PENDING')").fetchone()[0] if installed else 0
            report("context_integration_status", state="DRY_RUN", ready=False, queued=count)
            return

        self.store.install()
        self.store.mark("STARTING", self.clock())
        last_error = None
        try:
            while not self.stopping.is_set():
                outcomes = await self.tick()
                success = "CONTEXT_STORED" in outcomes
                errors = [code for code in outcomes if code and code != "CONTEXT_STORED"]
                if errors:
                    last_error = errors[0]
                elif success:
                    last_error = None
                elif not self.stopping.is_set():
                    # A successful probe clears transport health, not response validation failures.
                    if not await self.client.ready():
                        last_error = last_error or "CONTEXT_NOT_READY"
                    elif last_error == "CONTEXT_NOT_READY" or (last_error and last_error.startswith("CONTEXT_HTTP_5")):
                        last_error = None
                self.store.mark("DEGRADED" if last_error else "RUNNING", self.clock(), last_error, success)
                if once:
                    break
                try:
                    await asyncio.wait_for(self.stopping.wait(), self.settings.poll_interval_seconds)
                except TimeoutError:
                    pass
        except Exception:
            self.store.mark("FAILED", self.clock(), "CONTEXT_WORKER_FAILURE")
            raise
        self.store.mark("STOPPED", self.clock())
        report("context_integration_shutdown", state="STOPPED")


async def run(settings, once):
    store = ContextPackageStore(settings)
    if not settings.enabled or settings.dry_run:
        await Worker(settings, store, None).run(once=once)
        return
    timeout = httpx.Timeout(settings.timeout_seconds, connect=min(3, settings.timeout_seconds))
    limits = httpx.Limits(max_connections=settings.max_concurrency)
    async with httpx.AsyncClient(base_url=settings.url, timeout=timeout, limits=limits, trust_env=False) as client:
        worker = Worker(settings, store, ContextClient(client, settings))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(worker.stopping.set))
        await worker.run(once=once)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--once", action="store_true")
    flags.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.status and settings.enabled and not settings.dry_run:
            report("context_integration_status", **ContextPackageStore(settings).inspect(time.time()))
        elif args.status:
            report("context_integration_status", state="DRY_RUN" if settings.enabled else "DISABLED", ready=False)
        else:
            asyncio.run(run(settings, args.once))
        return 0
    except ValidationError:
        code = "INVALID_CONTEXT_CONFIGURATION"
    except StorageFailure as exc:
        code = str(exc)
    except (sqlite3.Error, OSError):
        code = "CONTEXT_STORAGE_UNAVAILABLE"
    except Exception:
        code = "CONTEXT_WORKER_FAILURE"
    report("context_integration_error", state="FAILED", ready=False, code=code)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
