"""Consume ready Context Packages and dispatch the isolated n8n workflow."""

import argparse
import asyncio
import signal
import sqlite3
import time
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from app.context_integration_models import canonical
from app.context_integration_store import ContextPackageStore
from app.monitoring_worker import report
from app.workflow_config import WEBHOOK_PATH, Settings
from app.workflow_models import AnalysisResult, validate_result, verify_request
from app.workflow_store import Store


@dataclass(frozen=True)
class Outcome:
    state: str
    code: str
    safe_retry: bool = False


class Client:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    async def ready(self):
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                async with self.client.stream("GET", "/healthz/readiness") as response:
                    return response.status_code == 200
        except (TimeoutError, httpx.HTTPError):
            return False

    async def dispatch(self, envelope):
        verify_request(envelope)
        payload = canonical(envelope.model_dump(mode="json"))
        if len(payload) > self.settings.max_payload_bytes:
            return Outcome("DISPATCH_FAILED", "WORKFLOW_PAYLOAD_TOO_LARGE")
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                async with self.client.stream(
                    "POST", WEBHOOK_PATH, content=payload,
                    headers={"Authorization": f"Bearer {self.settings.secret()}", "Content-Type": "application/json"},
                ) as response:
                    status = response.status_code
                    if status == 202:
                        return Outcome("WORKFLOW_ACCEPTED", "WEBHOOK_HTTP_202")
                    if status in {401, 403, 404, 409, 413, 422}:
                        return Outcome("DISPATCH_FAILED", f"WEBHOOK_HTTP_{status}")
                    if status != 200:
                        return Outcome("OUTCOME_UNKNOWN", f"WEBHOOK_HTTP_{status}")
                    received = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        if len(received) + len(chunk) > self.settings.max_payload_bytes:
                            return Outcome("OUTCOME_UNKNOWN", "WEBHOOK_RESPONSE_TOO_LARGE")
                        received.extend(chunk)
            result = AnalysisResult.model_validate_json(received)
            validate_result(envelope, result)
            # Only the adapter transaction can commit COMPLETED.
            return Outcome("OUTCOME_UNKNOWN", "WEBHOOK_RESULT_NOT_COMMITTED")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return Outcome("DISPATCH_FAILED", "WEBHOOK_CONNECTION_FAILED", True)
        except (TimeoutError, httpx.TimeoutException):
            return Outcome("OUTCOME_UNKNOWN", "WEBHOOK_TIMEOUT")
        except httpx.HTTPError:
            return Outcome("OUTCOME_UNKNOWN", "WEBHOOK_TRANSPORT_ERROR")
        except (ValueError, RecursionError):
            return Outcome("OUTCOME_UNKNOWN", "INVALID_WEBHOOK_RESULT")


class Dispatcher:
    def __init__(self, settings, store, context, client, *, clock=time.time):
        self.settings, self.store, self.context, self.client = settings, store, context, client
        self.clock = clock
        self.stopping = asyncio.Event()

    async def process(self, claim):
        started = time.perf_counter()
        try:
            package = self.context.read_ready(claim.package_id)
        except (ValueError, RecursionError):
            package = None
        envelope = self.store.before_dispatch(claim, package, self.clock())
        if envelope is None:
            return
        outcome = await self.client.dispatch(envelope)
        state = self.store.dispatch_outcome(claim, self.clock(), outcome.state, outcome.code,
                                            (time.perf_counter() - started) * 1000,
                                            safe_retry=outcome.safe_retry)
        report("workflow_dispatch", package_id=claim.package_id, state=state, webhook_outcome=outcome.code)
        return state

    async def tick(self):
        if self.stopping.is_set():
            return []
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(self.process(claim)) for claim in self.store.claims(self.clock())]
        return [task.result() for task in tasks]

    async def run(self, *, once=False):
        if not self.settings.dispatch_enabled:
            report("workflow_status", state="DISABLED", ready=False)
            return
        if self.settings.dispatch_dry_run:
            with self.store.connect() as db:
                count = db.execute("SELECT count(*) FROM analysis_readiness_queue").fetchone()[0]
            report("workflow_status", state="DRY_RUN", ready=False, ready_packages=count)
            return
        self.store.install()
        self.store.mark("STARTING", self.clock())
        state = "STARTING"
        try:
            while not self.stopping.is_set():
                outcomes = await self.tick()
                if any(item in {"DISPATCH_FAILED", "OUTCOME_UNKNOWN", "RETRY_PENDING", "ANALYSIS_FAILED"}
                       for item in outcomes):
                    state = "DEGRADED"
                elif "COMPLETED" in outcomes:
                    state = "RUNNING"
                if state == "STARTING" and not self.stopping.is_set():
                    state = "RUNNING" if await self.client.ready() else "DEGRADED"
                self.store.mark(state, self.clock())
                if once:
                    break
                try:
                    await asyncio.wait_for(self.stopping.wait(), self.settings.poll_interval_seconds)
                except TimeoutError:
                    pass
        except Exception:
            self.store.mark("FAILED", self.clock())
            raise
        self.store.mark("STOPPED", self.clock())
        report("workflow_shutdown", state="STOPPED")


async def run(settings, once):
    store = Store(settings)
    if not settings.dispatch_enabled or settings.dispatch_dry_run:
        await Dispatcher(settings, store, None, None).run(once=once)
        return
    timeout = httpx.Timeout(settings.timeout_seconds, connect=min(3, settings.timeout_seconds))
    limits = httpx.Limits(max_connections=settings.max_concurrency)
    async with httpx.AsyncClient(base_url=settings.n8n_url, trust_env=False, follow_redirects=False,
                                 timeout=timeout, limits=limits) as http:
        dispatcher = Dispatcher(settings, store, ContextPackageStore(settings), Client(http, settings))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(dispatcher.stopping.set))
        await dispatcher.run(once=once)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.status and settings.dispatch_enabled and not settings.dispatch_dry_run:
            report("workflow_status", **Store(settings).inspect(time.time()))
        elif args.status:
            report("workflow_status", state="DRY_RUN" if settings.dispatch_enabled else "DISABLED", ready=False)
        else:
            asyncio.run(run(settings, args.once))
        return 0
    except ValidationError:
        code = "INVALID_WORKFLOW_CONFIGURATION"
    except (sqlite3.Error, OSError):
        code = "WORKFLOW_STORAGE_UNAVAILABLE"
    except Exception:
        code = "WORKFLOW_WORKER_FAILURE"
    report("workflow_error", state="FAILED", ready=False, code=code)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
