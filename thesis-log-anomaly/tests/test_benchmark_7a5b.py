import asyncio
import hashlib
import io
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.api import Settings, create_app
from app.context_store import Snapshot
from app.incident_context import build_context
from app.telemetry import logger, provider
from test_api import MemoryRepository
from tools.collect_benchmark_7a5b import collect_fixture, dry_run
from tools.consolidate_7a4 import verify_hashes
from tools.validate_7a5 import PLAN, read


@pytest.mark.parametrize("mode,expected,attempts", [
    ("healthy", 201, 1), ("unavailable", 502, 1), ("retry", 502, 3),
    ("transport", 502, 3), ("processing", 500, 1), ("processing_before_lookup", 500, 0),
])
def test_order_fault_evidence(mode, expected, attempts, monkeypatch):
    sink = io.StringIO()
    monkeypatch.setattr(logger().handlers[0], "stream", sink)
    repo = MemoryRepository()
    exporter = InMemorySpanExporter()
    tp = provider("order", False)
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    calls = []
    def lookup(request):
        calls.append(request.url.host)
        if request.url.host == "product-service":
            if mode == "transport":
                raise httpx.ConnectError("fixture refusal", request=request)
            if mode in {"unavailable", "retry"}:
                return httpx.Response(503)
        return httpx.Response(200)
    fault = mode if mode.startswith("processing") else ""
    app = create_app(Settings("order", "unused", attempts=max(1, attempts), fault=fault, lab_enabled=bool(fault)),
                     repository=repo, tracer_provider=tp, transport=httpx.MockTransport(lookup))
    payload = {"product_id": str(uuid4()), "user_id": str(uuid4()), "quantity": 1}
    try:
        with TestClient(app) as client:
            response = client.post("/orders", json=payload)
        assert response.status_code == expected
        assert len(repo.rows) == int(expected == 201)
        assert calls.count("product-service") == attempts
        spans = [s for s in exporter.get_finished_spans() if s.attributes.get("peer.service") == "product"]
        assert [s.attributes["retry.attempt"] for s in spans] == list(range(1, attempts + 1))
        assert all(a.end_time <= b.start_time for a, b in zip(spans, spans[1:]))
        assert any(s.kind.name == "SERVER" for s in exporter.get_finished_spans())
        logs = [json.loads(line) for line in sink.getvalue().splitlines()]
        logs = [row for row in logs if row.get("trace_id") == response.headers["x-trace-id"]]
        if mode in {"unavailable", "retry", "transport"}:
            assert response.json()["error"]["code"] == "dependency_unavailable"
            assert [s.attributes.get("http.response.status_code") for s in spans] == [
                None if mode == "transport" else 503] * attempts
            assert [row["attempt"] for row in logs if row["event"] == "dependency_attempt_failed"] == list(
                range(1, attempts + 1))
            assert sum(row["event"] == "dependency_exhausted" for row in logs) == 1
        if fault:
            failure, = [row for row in logs if row["event"] == "order_processing_failed"]
            if mode == "processing_before_lookup":
                assert failure["stage"] == "before_dependency_lookup"
            recovered = create_app(Settings("order", "unused"), repository=repo,
                                   transport=httpx.MockTransport(lookup))
            with TestClient(recovered) as client:
                assert client.post("/orders", json=payload).status_code == 201
    finally:
        tp.shutdown()


class Adapter:
    def __init__(self, failure):
        self.failure = failure
        self.calls = []

    async def preflight(self):
        self.calls.append("preflight")
        return {"ok": self.failure != "preflight"}

    async def activate(self, campaign):
        self.calls.append("activate")
        return self.failure != "activation"

    async def post_once(self):
        self.calls.append("post")
        if self.failure == "timeout":
            await asyncio.sleep(1)
        if self.failure == "post":
            raise OSError()
        return uuid4().hex

    async def capture(self, trace):
        rows = [{"trace_id": trace, "event_id": uuid4().hex, "service_name": service,
                 "level": "INFO", "message": "request_completed", "status_code": 200,
                 "@timestamp": "2026-11-22T17:00:00Z"} for service in ("order", "product")]
        single = build_context(trace, "single_service", "order", Snapshot(rows[:1])).model_dump(mode="json")
        cross = build_context(trace, "cross_service", None, Snapshot(rows)).model_dump(mode="json")
        evidence = [{"event_id": row["event_id"],
                     "payload_sha256": hashlib.sha256(json.dumps(row).encode()).hexdigest()} for row in rows]
        if self.failure == "leak":
            cross["ground_truth"] = "private"
        if self.failure == "pair":
            single["events"][0]["status_code"] = 500
        return {"trace_id": trace, "single": single, "cross": cross, "producer": evidence, "docker": evidence,
                "es": evidence[:-1] if self.failure == "missing" else evidence,
                "seal_closed": True, "handoff_confirmed": False, "activation_verified": True,
                "dossier": {"ground_truth": "private"}}

    async def rollback(self):
        self.calls.append("rollback")
        return self.failure != "rollback"

    async def postflight(self):
        self.calls.append("postflight")
        return {"ok": True}


@pytest.mark.parametrize("failure,status,count", [
    ("", "FIXTURE_VALID", 2), ("post", "FAILED", 1), ("timeout", "TIMEOUT", 1),
    ("preflight", "PREFLIGHT_FAILED", 0), ("activation", "FAILED", 0),
    ("rollback", "CLEANUP_FAILED", 2), ("leak", "FAILED", 1), ("pair", "FAILED", 1),
    ("missing", "FAILED", 1),
])
def test_bounded_collection(tmp_path, failure, status, count):
    adapter = Adapter(failure)
    output = tmp_path / "fixture"
    record = asyncio.run(collect_fixture("normal-a", adapter, output, seconds=.05 if failure == "timeout" else 5))
    assert record["status"] == status and record["target_requests"] == adapter.calls.count("post") == count
    assert ("postflight" in adapter.calls) == (failure not in {"preflight", "rollback"})
    assert not record["blind_eligible"]
    assert verify_hashes(output, "bundle_sha256.json") >= 1
    if not failure:
        assert "ground_truth" not in (output / "run-1.cross.json").read_text()
        assert json.loads((output / "labels/run-1.json").read_text())["status"] == "NEEDS_REVIEW"


def test_dry_run_limits():
    assert dry_run("normal-a")["target_requests"] == 0
    with pytest.raises(ValueError):
        dry_run("normal-a", requests=3)
    with pytest.raises(ValueError):
        dry_run("unknown")


def test_configuration_matrix_preserves_slots_and_pending_independence():
    plan = read(PLAN / "cohort_plan.json")
    matrix = read(PLAN / "configuration_matrix.json")
    slots = matrix["slots"]
    assert {row["id"] for row in slots} == {row["id"] for row in plan["configs"]}
    assert len(slots) == 14 and sum(row["status"] == "FIXTURE_VERIFIED" for row in slots) == 10
    assert all(not row["live_verified"] for row in slots)
    assert matrix["independence_verified"] == 0 and not matrix["protocol_changed"]
