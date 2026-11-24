"""Verify saved real Docker events against Elasticsearch and provision the Kibana data view."""

import argparse
import base64
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments/runs"
TELEMETRY = ROOT / "experiments/telemetry"
ES = "http://127.0.0.1:9200"
KIBANA = "http://127.0.0.1:5601"
TRUTH_FIELDS = {"scenario_id", "root_cause_service", "root_cause_type", "affected_services", "expected_behavior"}


def client():
    credentials = dict(line.split("=", 1) for line in (ROOT / ".env.elk").read_text().splitlines())
    token = base64.b64encode(f"elastic:{credentials['ELASTIC_PASSWORD']}".encode()).decode()

    def request(host, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        req = Request(host + path, data=body, headers={"Authorization": f"Basic {token}",
                      "Content-Type": "application/json", "kbn-xsrf": "thesis-verification"})
        with urlopen(req, timeout=60 if host == KIBANA else 15) as response:
            return json.load(response)

    return request


def wait(request, host, path, predicate, payload=None, seconds=60):
    until = time.monotonic() + seconds
    last = None
    while time.monotonic() < until:
        try:
            last = request(host, path, payload)
            if predicate(last):
                return last
        except (OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {path}: {last}")


def create_view(request):
    path = "/api/data_views/data_view/thesis-logs"
    try:
        view = request(KIBANA, path)["data_view"]
    except HTTPError as exc:
        if exc.code != 404:
            raise
        view = request(KIBANA, "/api/data_views/data_view",
                       {"data_view": {"id": "thesis-logs", "name": "Thesis application logs",
                                      "title": "thesis-logs-*", "timeFieldName": "@timestamp"}})["data_view"]
    assert view["title"] == "thesis-logs-*" and view["timeFieldName"] == "@timestamp"
    return view["id"]


def count(request, query):
    return request(ES, "/thesis-logs-*/_count", {"query": query})["count"]


def trace_search(request, trace_id, expected_count):
    query = {"size": 300, "track_total_hits": True, "query": {"term": {"trace_id": trace_id}},
             "sort": [{"@timestamp": "asc"}, {"event_id": "asc"}]}
    response = wait(request, ES, "/thesis-logs-*/_search",
                    lambda r: r["hits"]["total"]["value"] >= expected_count, query)
    result = response["hits"]["hits"]
    assert len(result) == expected_count, f"Count mismatch or duplicates: {trace_id}"
    return result


def check_trace(request, receipt):
    observation = receipt["observed"]
    target = receipt["expected_behavior"]
    assert observation["status"] == target["status"] and observation["error"] == target.get("error")
    trace_id = observation["trace_id"]
    telemetry = [json.loads(line) for line in (TELEMETRY / f"{trace_id}.jsonl").read_text().splitlines()]
    app = {item["event_id"]: item for item in telemetry if "event_id" in item}
    assert app and len(app) == sum("event_id" in item for item in telemetry)
    hits = trace_search(request, trace_id, len(app))
    assert len({(hit["_index"], hit["_id"]) for hit in hits}) == len(app)
    observed = {hit["_source"]["event_id"]: hit["_source"] for hit in hits}
    assert set(app) == set(observed), "Missing or duplicated source event"
    timestamps = []
    for hit in hits:
        doc = hit["_source"]
        raw = app[doc["event_id"]]
        assert hit["_id"] == doc["event_id"] and raw == doc["app"], "Source JSON changed"
        assert doc["trace_id"] == trace_id and doc["span_id"] == raw["span_id"]
        assert doc["request_id"] == raw["request_id"] and doc["service_name"] == raw["service"]
        assert not (TRUTH_FIELDS & doc.keys() or TRUTH_FIELDS & raw.keys())
        timestamp = datetime.fromisoformat(doc["@timestamp"].replace("Z", "+00:00"))
        assert timestamp == datetime.fromisoformat(raw["timestamp"])
        timestamps.append(timestamp)
        for name, source in (("status_code", "status"), ("duration_ms", "duration_ms")):
            if source in raw:
                assert isinstance(doc[name], (int, float)) and doc[name] == raw[source]
    assert timestamps == sorted(timestamps)
    statuses = {d["service_name"]: d["status_code"] for d in observed.values() if d["message"] == "request_completed"}
    if receipt["scenario_id"] == "cascade":
        assert statuses == {"user": 200, "product": 503, "order": 502}
    if receipt["scenario_id"] == "timeout":
        assert any(d.get("error_type") == "dependency_timeout" for d in observed.values())
    if "attempts" in target:
        assert sum(d["message"] == "dependency_attempt_failed" for d in observed.values()) == target["attempts"]
    return {"scenario": receipt["scenario_id"], "trace_id": trace_id, "observed_http": observation["status"],
            "docker_app_events": len(app), "docker_other_records": len(telemetry) - len(app),
            "indexed_events": len(hits), "statuses_by_service": statuses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    request = client()
    health = wait(request, ES, "/_cluster/health", lambda r: r["status"] in ("green", "yellow"),
                  seconds=240)
    kb = wait(request, KIBANA, "/api/status", lambda r: r["status"]["overall"]["level"] == "available",
              seconds=240)
    view = create_view(request)
    truth = json.loads((ROOT / "experiments/ground_truth.json").read_text())
    verifications = []
    for item in truth:
        before = set(RUNS.glob("*.json"))
        subprocess.run([sys.executable, "-B", "-m", "experiments.run_scenario", item["scenario_id"], "--elk"],
                       cwd=ROOT, check=True)
        [receipt] = set(RUNS.glob("*.json")) - before
        verifications.append(check_trace(request, json.loads(receipt.read_text())))
    services = {name: count(request, {"term": {"service_name": name}}) for name in ("user", "product", "order")}
    errors = count(request, {"bool": {"filter": [{"term": {"level": "ERROR"}},
                   {"range": {"status_code": {"gte": 500}}}]}})
    assert min(services.values()) > 0 and errors > 0
    assert count(request, {"bool": {"must_not": [{"exists": {"field": "event_id"}}]}}) == 0
    for row in verifications:
        assert count(request, {"term": {"trace_id": row["trace_id"]}}) == row["indexed_events"]
    try:
        urlopen(ES + "/_cluster/health", timeout=5)
    except HTTPError as exc:
        assert exc.code == 401, "Unexpected response without credentials"
    else:
        raise AssertionError("Elasticsearch allowed access without credentials")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"elasticsearch_status": health["status"], "kibana_status": kb["status"]["overall"]["level"],
                   "data_view": view, "service_counts": services, "error_5xx_count": errors,
                   "unauthenticated_elasticsearch_status": 401,
                   "scenarios": verifications}, stream, indent=2)
    print(f"Verified {len(verifications)} real traces; report: {args.output}")


if __name__ == "__main__":
    main()
