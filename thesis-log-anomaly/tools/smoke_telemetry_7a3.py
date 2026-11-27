"""Collect one measured local Order trace and reconcile it with real Elasticsearch."""

import argparse
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import httpx

from app.benchmark import isolate
from app.context_store import ContextStore
from app.incident_context import build_context
from app.telemetry_receipts import Receipt, Seal, differences, envelope, fingerprint
from app.trace_store import valid_trace
from experiments.run_scenario import ROOT, URLS, read_trace
from tools.collect_benchmark_7a1 import digest, reconcile, write
from tools.verify_ground_truth_7a2 import assess

OUTPUT = ROOT / "experiments/benchmark_7a3_smoke"


def now():
    return datetime.now(timezone.utc)


def run(output):
    output.mkdir(exist_ok=False)
    (output / "receipts").mkdir()
    env = {**os.environ, "LAB_WITH_ELK": "1"}
    key = dict(row.split("=", 1) for row in (ROOT / ".env.context").read_text().splitlines())["CONTEXT_ES_API_KEY"]
    with httpx.Client(timeout=12, trust_env=False) as api, httpx.Client(
        base_url="http://127.0.0.1:9200", timeout=5, trust_env=False,
        headers={"Authorization": f"ApiKey {key}"},
    ) as es:
        for url in URLS.values():
            api.get(url + "/ready").raise_for_status()
        user = api.post(URLS["user"] + "/users", json={
            "name": "Telemetry Smoke", "email": secrets.token_hex(10) + "@example.com",
        }).raise_for_status().json()
        product = api.post(URLS["product"] + "/products", json={
            "name": "Telemetry Smoke", "price": "5.25",
        }).raise_for_status().json()
        response = api.post(URLS["order"] + "/orders", json={
            "user_id": user["id"], "product_id": product["id"], "quantity": 1,
        })
        trace = response.headers.get("x-trace-id", "")
        if response.status_code != 201 or not valid_trace(trace):
            raise RuntimeError("Smoke Order did not complete as expected")
        # Producer capture is a bounded read of Docker telemetry, and has no exporter drain/ack.
        sleep(.75)
        telemetry = read_trace(env, trace)
        captured_at = now()
        event_ids = sorted(row["event_id"] for row in telemetry if "event_id" in row)
        if not event_ids or len(event_ids) != len(set(event_ids)):
            raise ValueError("Source capture has missing or duplicate identities")
        store, deadline = ContextStore(es), monotonic() + 25
        while True:
            snapshot = store.snapshot(trace)
            observed = sorted(row["event_id"] for row in snapshot.rows if row.get("event_id"))
            diffs = differences(event_ids, observed)
            if not any(diffs) or diffs[1] or diffs[2] or monotonic() >= deadline:
                break
            sleep(.5)
        context = build_context(trace, "cross_service", None, snapshot)
        raw_context = context.model_dump(mode="json")
        detail = reconcile(telemetry, context, trace)
        assessment = assess(trace, detail, raw_context)
        isolate(detail)
        isolate(raw_context)
        rid = uuid4().hex
        seal = Seal(seal_version="source-seal-v1", trace_id=trace, run_id=rid, source_service="order",
                    source_completion_timestamp=captured_at,
                    root_span_completion_status=assessment["request_completed"], source_event_ids=event_ids,
                    expected_event_count=None, source_coverage="OBSERVED_CAPTURE_ONLY",
                    parent_graph_valid=assessment["parent_graph_valid"])
        receipt = Receipt(receipt_version="es-receipt-v1", run_id=rid, trace_id=trace,
                          expected_event_ids=event_ids, observed_event_ids=observed, missing_event_ids=diffs[0],
                          unexpected_event_ids=diffs[1], duplicate_event_ids=diffs[2], reconciliation_timestamp=now(),
                          ingestion_settled_status="INCOMPLETE_QUERY" if snapshot.timed_out or snapshot.truncated
                          else "MISMATCH" if any(diffs) else "MATCHED_CAPTURE",
                          event_content_matches=assessment["docker_es_reconciled"],
                          event_sha256={e.event_id: fingerprint(e.model_dump(mode="json")) for e in context.events})
        bundle = envelope(seal, receipt)
        isolate(bundle)
        write(output / "receipts" / f"{trace}.json", bundle)
        write(output / "source_telemetry.json", detail)
        write(output / "snapshot.json", raw_context)
        write(output / "smoke.json", {"trace_id": trace, "run_id": rid, "http_status": response.status_code,
                                      "scope": "engineering_smoke_only", "fixture_posts": 2, "measured_posts": 1,
                                      "blind_eligible": False, "source_event_count": len(event_ids),
                                      "es_event_count": len(observed), "reconciliation": receipt.ingestion_settled_status,
                                      "trace_complete": False})
    write(output / "checksum_manifest.json", {p.relative_to(output).as_posix(): digest(p)
                                               for p in sorted(output.rglob("*.json"))})
    print(f"Saved one local smoke trace: {trace}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-local", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if not args.execute_local:
        print("Dry run: two fixture POSTs and one measured Order POST, localhost only.")
        return
    path = args.output.resolve()
    if not path.is_relative_to((ROOT / "experiments").resolve()):
        parser.error("Output must be under experiments/")
    run(path)


if __name__ == "__main__":
    main()
