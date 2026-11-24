"""Compare standalone Context API with Elasticsearch and existing observation receipts."""

import argparse
import json
from pathlib import Path

import httpx

from tools.audit_research import audit
from tools.verify_elk import ES, client as admin_client

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"ground_truth", "expected_root_cause", "injected_fault_type", "scenario_id", "root_cause"}


def check_no_labels(value):
    if isinstance(value, dict):
        assert not FORBIDDEN & set(value)
        for child in value.values():
            check_no_labels(child)
    elif isinstance(value, list):
        for child in value:
            check_no_labels(child)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pilot", type=Path, default=ROOT / "experiments/micro_pilot_seed123/observations")
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    expected = json.loads((ROOT / "experiments/elk_verification.json").read_text())["scenarios"]
    cascade = next(row["trace_id"] for row in expected if row["scenario"] == "cascade")
    key = dict(row.split("=", 1) for row in (ROOT / ".env.context").read_text().splitlines())["CONTEXT_ES_API_KEY"]
    mapping_response = admin_client()(ES, "/thesis-logs-*/_mapping")
    required = {"trace_id": "keyword", "event_id": "keyword", "span_id": "keyword",
                "service_name": "keyword", "dependency_service": "keyword", "error_type": "keyword",
                "request_id": "keyword", "endpoint": "keyword", "http_method": "keyword",
                "status_code": "integer", "@timestamp": "date_nanos", "message": "text"}
    for index in mapping_response.values():
        props = index["mappings"]["properties"]
        assert {key: props[key]["type"] for key in required} == required
        assert "parent_span_id" not in props and "event.ingested" not in props

    with httpx.Client(timeout=25, trust_env=False) as http:
        base = "http://127.0.0.1:8015"
        for endpoint in ("/health", "/ready"):
            http.get(base + endpoint).raise_for_status()
        results, pilot = [], []
        cross, single = None, {}
        for row in expected:
            trace = row["trace_id"]
            path = f"{base}/context/trace/{trace}"
            response = http.get(path, params={"wait_ms": 550 if trace == cascade else 0}).raise_for_status().json()
            check_no_labels(response)
            raw = http.post(ES + "/thesis-logs-*/_search", headers={"Authorization": f"ApiKey {key}"},
                            json={"query": {"term": {"trace_id": trace}}, "size": 64,
                                  "_source": ["event_id", "service_name", "status_code", "span_id"]})
            records = raw.raise_for_status().json()["hits"]["hits"]
            raw_ids = {item["_source"]["event_id"] for item in records}
            assert set(response["evidence_event_ids"]) == raw_ids
            assert response["event_count"] == len(raw_ids) == row["indexed_events"]
            assert all(set(item["evidence_event_ids"]) <= raw_ids for item in response["timeline"])
            results.append({"trace_id": trace, "scenario": row["scenario"], "event_count": len(raw_ids),
                            "status": response["completeness_status"],
                            "warnings": response["retrieval_warnings"]})
            if trace != cascade:
                continue
            cross = response
            assert set(cross["services"]) == {"user", "product", "order"}
            completed = {e["service_name"]: e["status_code"] for e in cross["events"]
                         if e["message"] == "request_completed"}
            assert completed == {"user": 200, "product": 503, "order": 502}
            assert any(e["source_service"] == "order" and e["target_service"] == "product"
                       for e in cross["dependencies"])
            for service in completed:
                scoped = http.get(path, params={"mode": "single_service", "service_name": service})
                single[service] = scoped.raise_for_status().json()
                check_no_labels(single[service])
                assert single[service]["services"] == [service]
                assert {e["event_id"] for e in single[service]["events"]} == {
                    r["_source"]["event_id"] for r in records if r["_source"]["service_name"] == service}
        for path in sorted(args.pilot.glob("*.json")):
            obs = json.loads(path.read_text())
            response = http.get(f"{base}/context/trace/{obs['trace_id']}").raise_for_status().json()
            check_no_labels(response)
            assert response["evidence_event_ids"] == [e["event_id"] for e in obs["events"]]
            pilot.append({"trace_id": obs["trace_id"], "event_count": response["event_count"],
                          "status": response["completeness_status"], "warnings": response["retrieval_warnings"]})
        detection = http.get("http://127.0.0.1:8014/ready")
        assert detection.status_code == 503 and detection.json()["error"]["code"] == "NOT_READY_FOR_SCORING"
    assert cross and len(pilot) == 14
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"scenarios": results, "pilot": pilot, "cascade_cross_service": cross,
                   "cascade_single_service": single, "verified_mappings": required,
                   "detection_status": detection.json(), "research_audit": audit()}, stream, indent=2)
    print(f"Verified {len(results)} ELK scenarios and {len(pilot)} pilot traces. Report: {args.output}")


if __name__ == "__main__":
    main()
