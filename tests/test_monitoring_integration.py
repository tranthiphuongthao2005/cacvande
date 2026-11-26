import asyncio
import json
from datetime import datetime

import httpx
import pytest

from app.context_store import ContextStore
from app.detection_api import create_app
from app.monitoring_client import DetectionClient, ElasticsearchPoller, iso
from app.monitoring_config import Settings
from app.monitoring_store import MonitoringStore
from app.monitoring_worker import Worker
from test_monitoring_store import NOW, query
from test_rule_detection import TRACE, completion


def test_entire_pipeline_restart_replay_and_late_evidence(tmp_path):
    async def exercise():
        now = NOW
        settings = Settings(enabled=True, es_url="http://mock-es", es_api_key="test",
                            detection_url="http://mock-hybrid", storage_path=str(tmp_path / "worker.sqlite"),
                            quiet_period_seconds=0, batch_size=1)
        first = {**completion(status=503), "@timestamp": iso(NOW + 1)}
        late = {**completion(6), "@timestamp": iso(NOW + .5)}
        old = {**completion(7), "@timestamp": iso(NOW - 1)}
        docs = [old, first]
        hybrid_docs = [first]
        poll_calls, hybrid_calls, requests = [], [], []

        def handler(request, documents, calls, polling):
            calls.append((request.method, request.url.path))
            if request.method == "DELETE":
                assert json.loads(request.content)["id"] in {"new", "original"}
                return httpx.Response(200, json={})
            if request.url.path.endswith("/_pit"):
                return httpx.Response(200, json={"id": "original"})
            payload = json.loads(request.content)
            selected = documents
            if polling:
                range_ = payload["query"]["range"]["@timestamp"]
                assert datetime.fromisoformat(range_["gte"]).timestamp() >= NOW
                selected = [row for row in documents if range_["gte"] <= row["@timestamp"] < range_["lt"]]
                selected.sort(key=lambda row: row["@timestamp"])
            offset = payload.get("search_after", ["", "", 0])[2]
            if offset:
                assert payload["pit"]["id"] == "new"
            hits = [{"_source": row, "_id": row["event_id"], "_index": "thesis-logs-test",
                     "sort": [row["@timestamp"], row["event_id"], i + 1]}
                    for i, row in enumerate(selected) if offset <= i < offset + payload["size"]]
            return httpx.Response(200, json={"pit_id": "new", "hits": {"hits": hits}})

        def poll_es(request):
            assert request.url.host == "mock-es"
            return handler(request, docs, poll_calls, True)

        def hybrid_es(request):
            return handler(request, hybrid_docs, hybrid_calls, False)

        with httpx.Client(base_url="http://mock-es", transport=httpx.MockTransport(hybrid_es)) as es:
            api = create_app(rule_store=ContextStore(es))

            @api.middleware("http")
            async def capture(request, call_next):
                requests.append(await request.json())
                return await call_next(request)

            async with (api.router.lifespan_context(api),
                        httpx.AsyncClient(base_url="http://mock-es", transport=httpx.MockTransport(poll_es)) as poll,
                        httpx.AsyncClient(base_url="http://mock-hybrid",
                                          transport=httpx.ASGITransport(app=api)) as detection):
                store = MonitoringStore(settings)
                store.open(now)
                worker = Worker(settings, store, ElasticsearchPoller(poll, settings),
                                DetectionClient(detection, 10), clock=lambda: now)
                now += 2
                assert await worker.poll_once()
                # Restart before dispatch. The pending trace and checkpoint must survive.
                store = MonitoringStore(settings)
                store.open(now)
                worker = Worker(settings, store, ElasticsearchPoller(poll, settings),
                                DetectionClient(detection, 10), clock=lambda: now)
                await worker.dispatch()
                now += 1
                await worker.poll_once()
                await worker.dispatch()
                assert len(requests) == 1
                assert query(store, "SELECT last_event FROM checkpoint") == [(first["event_id"],)]
                docs.append(late)
                hybrid_docs.append(late)
                now += 1
                await worker.poll_once()
                await worker.dispatch()
                assert requests == [{"trace_id": TRACE, "mode": "AUTO"}] * 2
                history = [json.loads(doc) for (doc,) in query(store, "SELECT document FROM detection_events "
                                                            "ORDER BY trace_version")]
                assert [entry["trace_version"] for entry in history] == [1, 2]
                assert history[0]["worker_observed_event_ids"] == [first["event_id"]]
                assert history[1]["worker_observed_event_ids"] == [first["event_id"], late["event_id"]]
                for entry in history:
                    assert entry["evidence_event_ids"] == [first["event_id"]]
                    assert entry["model_score"] is None and entry["detection_source"] == "rule_based"
                    assert entry["fallback_reason"] == "DOMAIN_NOT_VALIDATED"
                    assert entry["context_completeness"] == "partial"
                assert query(store, "SELECT cursor FROM checkpoint") == [(float(now),)]
                assert poll_calls.count(("DELETE", "/_pit")) == 3
                assert hybrid_calls.count(("DELETE", "/_pit")) == 2

    asyncio.run(exercise())


@pytest.fixture(autouse=True)
def prohibit_live_http(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("integration uses in-process HTTP or MockTransport only")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
