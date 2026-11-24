import asyncio
import json
import os
import socket
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import pytest
import uvicorn
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from psycopg import sql
from psycopg.conninfo import make_conninfo
from opentelemetry.trace import SpanKind

from app.api import Settings, create_app
from app.telemetry import provider

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def db_configs():
    admin = os.getenv("TEST_PG_ADMIN_URL")
    if not admin:
        pytest.skip("Set TEST_PG_ADMIN_URL to an isolated PostgreSQL instance")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    names = {s: f"test_{s}_{uuid4().hex[:8]}" for s in ("user", "product", "order")}
    with psycopg.connect(admin, autocommit=True) as conn:
        created = []
        try:
            for name in names.values():
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)
            yield {s: make_conninfo(admin, dbname=n) for s, n in names.items()}
        finally:
            for name in created:
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@contextmanager
def serve(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, ws="none"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            until = time.monotonic() + 8
            while not server.started and thread.is_alive() and time.monotonic() < until:
                time.sleep(.02)
            assert server.started
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(8)
            assert not thread.is_alive()


@contextmanager
def stack(db, product_fault="", order_fault="", attempts=2, user_fault=""):
    with ExitStack() as cleanup:
        exporter = InMemorySpanExporter()
        def launch(name, **kwargs):
            tp = provider(name, False)
            tp.add_span_processor(SimpleSpanProcessor(exporter))
            cleanup.callback(tp.shutdown)
            app = create_app(Settings(name, db[name], timeout=.25, lab_enabled=True, **kwargs),
                             tracer_provider=tp)
            return cleanup.enter_context(serve(app))
        user = launch("user", fault=user_fault)
        product = launch("product", fault=product_fault)
        order = launch("order", user_url=user, product_url=product, fault=order_fault, attempts=attempts)
        yield user, product, order, exporter


def populate(client, user, product):
    u = client.post(user + "/users", json={"name": "User", "email": f"{uuid4().hex}@example.com"})
    p = client.post(product + "/products", json={"name": "Book", "price": "12.50"})
    assert u.status_code == p.status_code == 201
    return {"user_id": u.json()["id"], "product_id": p.json()["id"], "quantity": 1}


def test_live_services_postgresql_crud_and_w3c_trace(db_configs):
    with stack(db_configs) as (user, product, order, exporter), httpx.Client(timeout=5, trust_env=False) as c:
        assert all(c.get(url + "/ready").status_code == 200 for url in (user, product, order))
        payload = populate(c, user, product)
        email = c.get(user + "/users/" + payload["user_id"]).json()["email"]
        assert c.post(user + "/users", json={"name": "Duplicate", "email": email.upper()}).status_code == 409
        trace_id = "1234567890abcdef1234567890abcdef"
        parent = "1234567890abcdef"
        response = c.post(order + "/orders", json=payload, headers={"traceparent": f"00-{trace_id}-{parent}-01"})
        assert response.status_code == 201 and response.headers["x-trace-id"] == trace_id
        path = order + "/orders/" + response.json()["id"]
        assert c.get(path).json()["quantity"] == 1
        assert c.put(path, json={**payload, "quantity": 2}).json()["quantity"] == 2
        assert c.delete(path).status_code == 204
        assert c.get(path).status_code == 404
        assert c.post(order + "/orders", json={**payload, "user_id": str(uuid4())}).status_code == 422
        spans = [s for s in exporter.get_finished_spans() if s.context.trace_id == int(trace_id, 16)]
        servers = {s.resource.attributes["service.name"]: s for s in spans if s.kind is SpanKind.SERVER}
        clients = {s.attributes["peer.service"]: s for s in spans if s.kind is SpanKind.CLIENT}
        assert set(servers) == {"user", "product", "order"} and set(clients) == {"user", "product"}
        assert servers["order"].parent.span_id == int(parent, 16)
        for name in clients:
            assert servers[name].parent.span_id == clients[name].context.span_id
            assert clients[name].parent.span_id == servers["order"].context.span_id
        with psycopg.connect(db_configs["order"]) as db:
            assert db.execute("SELECT count(*) FROM records WHERE id=%s", (response.json()["id"],)).fetchone() == (0,)
        with psycopg.connect(db_configs["user"]) as db:
            assert db.execute("SELECT count(*) FROM records WHERE id=%s", (payload["user_id"],)).fetchone() == (1,)


TRUTH = json.loads((Path(__file__).parents[1]/"experiments/ground_truth.json").read_text())
FAULTS = {"normal": ("", "", 2), "timeout": ("delay", "", 1), "unavailable": ("unavailable", "", 1),
          "database": ("", "database", 1), "processing": ("", "processing", 1),
          "retry": ("unavailable", "", 3), "cascade": ("unavailable", "", 1)}


@pytest.mark.parametrize("scenario", TRUTH, ids=lambda r: r["scenario_id"])
def test_fault_scenarios(db_configs, scenario):
    product_fault, order_fault, attempts = FAULTS[scenario["scenario_id"]]
    expected = scenario["expected_behavior"]
    with stack(db_configs, product_fault, order_fault, attempts) as (user, product, order, exporter), \
            httpx.Client(timeout=5, trust_env=False) as c:
        data = populate(c, user, product)
        if expected["request_service"] == "product":
            r = c.get(product + "/products/" + data["product_id"])
        else:
            r = c.post(order + "/orders", json=data)
        assert r.status_code == expected["status"]
        assert r.json().get("error", {}).get("code") == expected.get("error")
        spans = [s for s in exporter.get_finished_spans()
                 if s.context.trace_id == int(r.headers["x-trace-id"], 16)]
        assert all("scenario_id" not in s.attributes and "root_cause_type" not in s.attributes for s in spans)
        if "attempts" in expected:
            attempts_seen = [s.attributes["retry.attempt"] for s in spans
                             if s.kind is SpanKind.CLIENT and s.attributes["peer.service"] == "product"]
            assert attempts_seen == list(range(1, expected["attempts"]+1))
        if scenario["scenario_id"] == "cascade":
            statuses = {s.resource.attributes["service.name"]: s.attributes["http.response.status_code"]
                        for s in spans if s.kind is SpanKind.SERVER}
            assert statuses == {"user": 200, "product": 503, "order": 502}


@pytest.mark.parametrize("fault,status,error", [
    ("delay", 504, "dependency_timeout"), ("unavailable", 502, "dependency_unavailable"),
])
def test_user_originated_order_failures(db_configs, fault, status, error):
    with stack(db_configs, attempts=1, user_fault=fault) as (user, product, order, exporter), \
            httpx.Client(timeout=5, trust_env=False) as client:
        data = populate(client, user, product)
        response = client.post(order + "/orders", json=data)
        assert response.status_code == status and response.json()["error"]["code"] == error
        spans = [s for s in exporter.get_finished_spans()
                 if s.context.trace_id == int(response.headers["x-trace-id"], 16)]
        assert [s.attributes["peer.service"] for s in spans if s.kind is SpanKind.CLIENT] == ["user"]
        assert any(s.kind is SpanKind.SERVER and s.attributes["http.route"] == "/orders" for s in spans)
        if fault == "unavailable":
            assert any(s.kind is SpanKind.SERVER and s.attributes["http.response.status_code"] == 503 for s in spans)
