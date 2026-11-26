"""Independent polling and scheduling process for Microservices telemetry."""

import argparse
import asyncio
import json
import signal
import sqlite3
import time

import httpx
from pydantic import ValidationError

from app.monitoring_client import DetectionClient, DetectionFailure, ElasticsearchPoller, PollFailure
from app.monitoring_config import Settings
from app.monitoring_models import make_event
from app.monitoring_store import CheckpointError, MonitoringStore


def report(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


class Worker:
    def __init__(self, settings, store, poller, detector, *, clock=time.time):
        self.settings, self.store = settings, store
        self.poller, self.detector = poller, detector
        self.clock = clock
        self.stopping = asyncio.Event()

    async def poll_once(self):
        upper = self.clock()
        lower, cursor = self.store.window(upper)
        if lower >= upper:
            return False
        last_id = None
        tie = None

        def persist(hits):
            nonlocal last_id, tie
            last_id = self.store.accept_page(hits, self.clock()) or last_id
            if hits and isinstance(hits[-1], dict):
                last_sort = hits[-1].get("sort")
                # Only the stable producer ID is kept as diagnostic metadata.
                if isinstance(last_sort, list) and len(last_sort) == 3 and isinstance(last_sort[1], str):
                    tie = last_sort[1]

        if await self.poller.poll(lower, upper, persist, self.stopping):
            self.store.advance(cursor, upper, tie, last_id, self.clock())
            return True
        return False

    async def detect_one(self, claim):
        started = time.perf_counter()
        try:
            output = await self.detector.detect(claim.trace_id)
            now = self.clock()
            document = make_event(output, claim, now)
            saved = self.store.finish(claim, now, document=document,
                                      latency_ms=(time.perf_counter() - started) * 1000)
            report("monitoring_detection", trace_id=claim.trace_id, trace_version=claim.version,
                   detection_status=output.detection_status, persisted=saved)
        except DetectionFailure as failure:
            self.store.finish(claim, self.clock(), failure=failure, latency_ms=(time.perf_counter() - started) * 1000)
            report("monitoring_detection_error", trace_id=claim.trace_id, trace_version=claim.version,
                   code=failure.code)

    async def dispatch(self):
        if not self.stopping.is_set():
            async with asyncio.TaskGroup() as group:
                for claim in self.store.claims(self.clock()):
                    group.create_task(self.detect_one(claim))

    async def run(self, *, once=False):
        if not self.settings.enabled:
            report("monitoring_status", state="DISABLED", ready=False)
            return
        if self.settings.dry_run:
            # One bounded query, with no checkpoint, Detection API call or local writes.
            now = self.clock()
            seen = 0

            def count(hits):
                nonlocal seen
                seen += len(hits)

            interval = self.settings.lookback_seconds or self.settings.overlap_seconds
            completed = await self.poller.poll(now - interval, now, count, self.stopping)
            report("monitoring_dry_run", events_fetched=seen, completed=completed, ready=False)
            return

        self.store.open(self.clock())
        self.store.mark("STARTING", self.clock())
        try:
            while not self.stopping.is_set():
                started = time.perf_counter()
                try:
                    if await self.poll_once():
                        self.store.mark("RUNNING", self.clock(), latency=(time.perf_counter() - started) * 1000)
                except PollFailure as failure:
                    self.store.mark("DEGRADED", self.clock(), str(failure),
                                    latency=(time.perf_counter() - started) * 1000)
                    report("monitoring_poll_error", code=str(failure))
                await self.dispatch()
                if once:
                    break
                try:
                    await asyncio.wait_for(self.stopping.wait(), self.settings.poll_interval_seconds)
                except TimeoutError:
                    pass
        except Exception:
            self.store.mark("FAILED", self.clock(), "WORKER_FAILURE")
            raise
        self.store.mark("STOPPED", self.clock())
        report("monitoring_shutdown", state="STOPPED")


async def run(settings, once):
    if not settings.enabled:
        await Worker(settings, None, None, None).run()
        return
    def timeout(seconds):
        return httpx.Timeout(seconds, connect=min(3, seconds))

    async with (
        httpx.AsyncClient(base_url=settings.es_url, trust_env=False, timeout=timeout(settings.poll_timeout_seconds),
                          headers={"Authorization": f"ApiKey {settings.es_api_key.get_secret_value()}"}) as elastic,
        httpx.AsyncClient(base_url=settings.detection_url or "", trust_env=False,
                          timeout=timeout(settings.detection_timeout_seconds),
                          limits=httpx.Limits(max_connections=settings.max_concurrent_traces)) as detection,
    ):
        worker = Worker(settings, MonitoringStore(settings), ElasticsearchPoller(elastic, settings),
                        DetectionClient(detection, settings.detection_timeout_seconds))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(worker.stopping.set))
        await worker.run(once=once)


def main():
    args = argparse.ArgumentParser(description=__doc__)
    mode = args.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--status", action="store_true")
    flags = args.parse_args()
    try:
        settings = Settings.from_env()
        if flags.status:
            if not settings.enabled or settings.dry_run:
                report("monitoring_status", state="DRY_RUN" if settings.enabled else "DISABLED", ready=False)
            else:
                report("monitoring_status", **MonitoringStore(settings).read_status(time.time()))
        else:
            asyncio.run(run(settings, flags.once))
        return 0
    except ValidationError:
        code = "INVALID_CONFIGURATION"
    except (CheckpointError, PollFailure) as exc:
        code = str(exc)
    except (sqlite3.Error, OSError):
        code = "STORAGE_OR_IO_FAILURE"
    except Exception:
        code = "WORKER_FAILURE"
    report("monitoring_error", state="FAILED", ready=False, code=code)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
