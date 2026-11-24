import json
import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import Settings, create_app
from app.telemetry import logger


class MemoryRepository:
    def __init__(self):
        self.rows = {}

    async def initialize(self):
        pass

    async def ready(self):
        pass

    async def create(self, data):
        key = uuid4()
        self.rows[key] = {"id": key, **data}
        return self.rows[key]

    async def get(self, key):
        return self.rows.get(key)

    async def list(self, limit, offset):
        return list(self.rows.values())[offset:offset+limit]

    async def update(self, key, data):
        if key in self.rows:
            self.rows[key] = {"id": key, **data}
        return self.rows.get(key)

    async def delete(self, key):
        return self.rows.pop(key, None) is not None


@pytest.mark.parametrize("kind,path,good,bad", [
    ("user", "/users", {"name": "A", "email": "a@example.com"}, {"name": "A", "email": "no"}),
    ("product", "/products", {"name": "Item", "price": "10.00"}, {"name": "Item", "price": -1}),
])
def test_crud_and_validation(kind, path, good, bad):
    app = create_app(Settings(kind, "unused"), repository=MemoryRepository())
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "service": kind}
        assert client.get("/ready").status_code == 200
        assert client.post(path, json=bad).status_code == 422
        created = client.post(path, json=good)
        assert created.status_code == 201
        resource = f"{path}/{created.json()['id']}"
        assert client.get(resource).json() == created.json()
        assert client.get(path, params={"limit": 1, "offset": 0}).json() == [created.json()]
        assert client.put(resource, json={**good, "name": "Updated"}).json()["name"] == "Updated"
        assert client.delete(resource).status_code == 204
        assert client.get(resource).json() == {"error": {"code": "not_found"}}


def test_order_rejects_invalid_input_before_http():
    with TestClient(create_app(Settings("order", "unused"), repository=MemoryRepository())) as client:
        r = client.post("/orders", json={"user_id": str(uuid4()), "product_id": str(uuid4()), "quantity": True})
    assert r.status_code == 422
    assert "body.quantity" in r.json()["error"]["fields"]


def test_fault_disabled_by_default():
    with pytest.raises(ValueError):
        create_app(Settings("product", "unused", fault="delay"), repository=MemoryRepository())


def test_structured_log_not_echoing_body(monkeypatch):
    sink = io.StringIO()
    monkeypatch.setattr(logger().handlers[0], "stream", sink)
    with TestClient(create_app(Settings("user", "unused"), repository=MemoryRepository())) as client:
        r = client.post("/users", json={"name": "Lab", "email": "private@example.com"})
    rows = [json.loads(line) for line in sink.getvalue().splitlines()]
    request = next(row for row in rows if row["event"] == "request_completed")
    assert request["trace_id"] == r.headers["x-trace-id"]
    assert request["route"] == "/users" and request["service"] == "user"
    assert "private@example.com" not in json.dumps(rows)
