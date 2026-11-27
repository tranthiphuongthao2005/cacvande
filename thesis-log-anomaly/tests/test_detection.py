import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.detection_api import create_app
from app.mecolog_runtime import FrozenEncoder, bind_research, build_candidates, load_encoder, validate_arrays
from app.prototypes import Lineage, PrototypeScorer, reject_support_query_overlap, validate_pools
from app.trace_store import TraceStore

TRACE = "a" * 32
STAMP = "2026-11-22T17:00:00.123456Z"


def row(event_id, *, timestamp=STAMP, trace=TRACE):
    return {"trace_id": trace, "event_id": event_id, "@timestamp": timestamp, "service_name": "order",
            "message": "request_completed", "span_id": "b" * 16, "status_code": 201, "level": "INFO",
            "endpoint": "/orders", "http_method": "POST"}


def test_es_pagination_dedup_and_order(monkeypatch):
    monkeypatch.setattr("app.trace_store.PAGE_SIZE", 2)
    rows = [row("b"), row("b"), row("a")]
    calls = []

    def handler(request):
        data = json.loads(request.content) if request.content else {}
        calls.append((request.method, request.url.path, data))
        if request.url.path.endswith("/_pit"):
            return httpx.Response(200, json={"id": "original"})
        if "search_after" in data:
            assert data["pit"]["id"] == "new"
            assert data["search_after"] == [1]
            hits = rows[2:]
        else:
            assert data["query"]["bool"]["filter"][0] == {"term": {"trace_id": TRACE}}
            assert "app" not in data["_source"] and "scenario_id" not in data["_source"]
            hits = rows[:2]
        return httpx.Response(200, json={"pit_id": "new", "hits": {
            "hits": [{"_source": r, "sort": [i]} for i, r in enumerate(hits)]}})

    with httpx.Client(base_url="http://es", transport=httpx.MockTransport(handler)) as client:
        session = TraceStore(client).fetch(TRACE)
    assert [event.event_id for event in session.events] == ["a", "b"]
    assert session.events[0].timestamp.microsecond == 123456
    assert session.source_metadata.completeness == "partial"
    assert calls[-1] == ("DELETE", "/_pit", {"id": "new"})


def test_conflicting_duplicate_rejected():
    responses = iter([{"id": "x"}, {"hits": {"hits": [
        {"_source": row("a")}, {"_source": {**row("a"), "status_code": 500}},
    ]}}, {}])
    with httpx.Client(base_url="http://es", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=next(responses))
    )) as client:
        with pytest.raises(ValueError, match="Conflicting"):
            TraceStore(client).fetch(TRACE)


def test_api_not_ready_and_no_label_echo():
    session = TraceStore(None).session(TRACE, [row("example")])
    store = SimpleNamespace(fetch=lambda trace: session if trace == TRACE else None)
    with TestClient(create_app(store)) as api:
        assert api.get("/health").status_code == 200
        assert api.get("/ready").status_code == 503
        trace = api.post("/detect/trace", json={"trace_id": TRACE})
        assert trace.status_code == 503
        body = trace.json()["error"]
        assert body["code"] == "NOT_READY_FOR_SCORING"
        assert body["event_count"] == 1 and body["evidence_event_ids"] == ["example"]
        assert "anomaly_score" not in body and "predicted_label" not in body
        assert api.post("/detect/trace", json={"trace_id": "c" * 32}).status_code == 404
        assert api.post("/detect/trace", json={"trace_id": "0" * 32}).status_code == 422
        payload = session.model_dump(mode="json")
        assert api.post("/detect/session", json=payload).status_code == 503
        invalid = api.post("/detect/session", json={**payload, "ground_truth": "not-for-response"})
        assert invalid.status_code == 422 and "not-for-response" not in invalid.text
    with TestClient(create_app()) as api:
        assert api.post("/detect/trace", json={"trace_id": TRACE}).json()["error"]["code"] == "TRACE_STORE_NOT_CONFIGURED"


def test_pool_and_online_overlap_guards():
    support = [Lineage(TRACE, frozenset({"a"}), "family-a")]
    dev = [Lineage("b", frozenset({"b"}), "family-b")]
    evaluation = [Lineage("c", frozenset({"c"}), "family-c")]
    validate_pools(support, dev, evaluation)
    for invalid in [Lineage(TRACE, frozenset({"c"}), "family-c"),
                    Lineage("c", frozenset({"a"}), "family-c"),
                    Lineage("c", frozenset({"c"}), "family-a")]:
        with pytest.raises(ValueError, match="leakage"):
            validate_pools(support, dev, [invalid])
    with pytest.raises(ValueError, match="overlap"):
        reject_support_query_overlap(TraceStore(None).session(TRACE, [row("z")]), support)


def research_root():
    root = Path(__file__).resolve().parents[2] / "tuanmartin-MeCoLog-8c446ac"
    path = root / ".venv/Lib/site-packages"
    if path.exists() and str(path) not in sys.path:
        sys.path.append(str(path))
    return root


def test_candidate_shapes_oov_padding_truncation():
    root = research_root()
    np = pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    bind_research(root)
    from preprocess.parameters import Vocabulary
    from preprocess.parsing import DrainAdapter

    store = TraceStore(None)
    short = store.session(TRACE, [row("a")])
    long = store.session(TRACE, [row(f"long{i:02}") for i in range(51)])
    arrays, stats = build_candidates([short, long], DrainAdapter("HDFS"), Vocabulary({}, {}),
                                     lambda templates: {t: np.ones(768, np.float32) for t in templates})
    assert arrays["x"].shape == (2, 50, 768)
    assert arrays["p_val"].shape == (2, 50, 8, 16)
    assert not arrays["x"][0, 1:].any()
    assert stats[0]["key_oov"] == 1 and stats[0]["unseen_templates_events"] == 1
    assert stats[0]["padding_events"] == 49 and stats[1]["truncated_events"] == 1
    with pytest.raises(ValueError, match="Invalid tensor"):
        validate_arrays({**arrays, "p_key": arrays["p_key"].astype(np.int32)})


def test_checkpoint_digest_mismatch_stops_before_load(tmp_path, monkeypatch):
    research_root()
    torch = pytest.importorskip("torch")
    from app import mecolog_runtime as runtime
    bind_research(research_root())
    path = tmp_path / runtime.CHECKPOINT
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unexpected contents")
    monkeypatch.setattr(runtime, "bind_research", lambda _: tmp_path)
    monkeypatch.setattr(torch, "load", lambda *a, **k: pytest.fail("Deserialized unverified checkpoint"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_encoder(tmp_path)


def test_prototype_scoring_and_fallback():
    research_root()
    torch = pytest.importorskip("torch")
    support = torch.tensor([[1., 0.], [0., 1.], [0., 1.], [-1., 0.], [-1., 0.]])
    labels = [0, 1, 1, 1, 1]
    query = torch.tensor([[0., 1.], [1., 0.]])
    single = PrototypeScorer(support, labels, [3, 2, 4, 5, 9], "single")
    multi = PrototypeScorer(support, labels, [3, 2, 4, 5, 9], "length_aware_multi")
    fallback = PrototypeScorer(support, labels, [3, 2, 3, 4, 9], "length_aware_multi")
    torch.testing.assert_close(multi.scores(query), torch.tensor([1., -1.]))
    assert not multi.fallback and fallback.fallback
    torch.testing.assert_close(fallback.scores(query), single.scores(query))


def test_wrapper_uses_inference_context_on_fixture():
    research_root()
    np = pytest.importorskip("numpy")
    torch = pytest.importorskip("torch")

    def inspect_fixture(x, params):
        assert torch.is_inference_mode_enabled() and not torch.is_grad_enabled()
        assert x.shape == (1, 50, 768) and len(params) == 4
        return x[:, 0, :]

    encoder = FrozenEncoder(SimpleNamespace(encode=inspect_fixture))
    arrays = {"x": np.zeros((1, 50, 768), np.float32),
              "p_key": np.zeros((1, 50, 8), np.int64), "p_type": np.zeros((1, 50, 8), np.int64),
              "p_val": np.zeros((1, 50, 8, 16), np.int64), "p_num": np.zeros((1, 50, 8), np.float32)}
    assert encoder.encode(arrays).shape == (1, 768)
