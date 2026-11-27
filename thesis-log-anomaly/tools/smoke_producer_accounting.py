"""Bounded two-request lab exercise for producer accounting."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import httpx
from opentelemetry.sdk.trace import TracerProvider

from app.context_store import ContextStore
from app.incident_context import build_context
from app.producer_accounting import VERSION, digest as producer_digest
from app.telemetry_receipts import Receipt, Seal, differences, envelope, fingerprint
from experiments.run_scenario import ROOT, SETUPS, URLS, compose_command, read_trace
from tools.collect_benchmark_7a1 import digest, executed, reconcile, write
from tools.verify_ground_truth_7a2 import read
from tools.smoke_telemetry_7a3 import now
from tools.verify_ground_truth_7a2 import assess

OUTPUT = ROOT / "experiments/benchmark_7a3b_smoke"
SERVICES = ("user", "product", "order")


def compare(seals, inspections, docker, es_ids, services=SERVICES):
    expected, warnings = [], []
    scopes = set()
    docker_by_id = {e["event_id"]: e for e in docker}
    for service in services:
        saved = seals[service]["seal"]
        if not saved or saved["sha256"] != producer_digest({k: v for k, v in saved.items() if k != "sha256"}):
            warnings.append("INVALID_PRODUCER_SEAL")
            continue
        data = saved["summary"]
        scopes.add((data["run_id"], data["trace_id"]))
        live = inspections[service]
        events = data["events"]
        ids = [e["event_id"] for e in events]
        expected.extend(ids)
        if [e["event_sequence"] for e in events] != list(range(1, len(ids) + 1)):
            warnings.append("PRODUCER_SEQUENCE_GAP")
        if (len(ids) != data["expected_event_count"] or ids != data["expected_event_ids"]
                or data["accounting_version"] != VERSION or data["service_name"] != service
                or live["seal"] != saved or data["emitted_event_count"] != len(ids)
                or data["failed_emission_count"] or live["summary"]["expected_event_count"] < len(ids)):
            warnings.append("PRODUCER_ACCOUNTING_MISMATCH")
        if live["late_event_ids"] or live["summary"]["expected_event_ids"] != ids:
            warnings.append("EVENT_AFTER_SEAL")
        for event in events:
            doc = docker_by_id.get(event["event_id"])
            if (doc and (doc["service"] != service or event["payload_sha256"] !=
                        hashlib.sha256(json.dumps(doc).encode()).hexdigest())):
                warnings.append("DOCKER_PAYLOAD_MISMATCH")
    docker_diff = differences(expected, [e["event_id"] for e in docker])
    es_diff = differences(expected, es_ids)
    if len(expected) != len(set(expected)):
        warnings.append("DUPLICATE_PRODUCER_EVENT_ID")
    if len(scopes) != 1:
        warnings.append("PRODUCER_SCOPE_MISMATCH")
    if any(docker_diff):
        warnings.append("DOCKER_EVENT_SET_MISMATCH")
    if any(es_diff):
        warnings.append("ES_EVENT_SET_MISMATCH")
    return {"expected": sorted(expected), "docker": dict(zip(("missing", "unexpected", "duplicate"), docker_diff)),
            "elasticsearch": dict(zip(("missing", "unexpected", "duplicate"), es_diff)),
            "warnings": sorted(set(warnings))}


def run(output=OUTPUT, *, scenario=None, deadline=None, preflight_record=None, normal_smoke=False,
        postflight=None, reserved_output=False, pilot=None, post_gate=None):
    from tools.collection_gate_7a6b import CollectionBlocked, RuntimeLease, business_post
    from tools.fault_adapters_7a6c import ADAPTERS, await_timeout_trace, runtime_fault_db_health, verify_timeouts
    if post_gate is None:
        raise CollectionBlocked("A scoped runtime gate is required before collection")
    expected_campaign = pilot.campaign if pilot else "normal-a"
    if post_gate.campaign != expected_campaign or post_gate.output != output.resolve() or not (normal_smoke or pilot):
        raise CollectionBlocked("Gate does not match collector campaign or output")
    adapter = (ADAPTERS.get(post_gate.scope()[0]) if hasattr(post_gate, "scope") else
               next((item for item in ADAPTERS.values() if item.campaign == expected_campaign), None))
    if adapter is None or scenario != adapter.scenario or postflight is None:
        raise CollectionBlocked("Configuration or postflight does not match the scoped campaign")
    if not reserved_output:
        output.mkdir(exist_ok=False)
    if preflight_record is not None:
        write(output / "preflight.json", preflight_record)
    receipt_dir = output / "receipts"
    receipt_dir.mkdir()
    run_id = uuid4().hex
    tracer = TracerProvider().get_tracer("lab.accounting.smoke")
    with tracer.start_as_current_span("lab measured Order") as upstream:
        ctx = upstream.get_span_context()
        trace_id, parent_id = f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
        env = {**os.environ, "LAB_WITH_ELK": "1", "ACCOUNTING_RUN_ID": run_id, "ACCOUNTING_TRACE_ID": trace_id}
        product, order, attempts = SETUPS[scenario or "normal"]
        target = next(r["expected_behavior"] for r in read(ROOT / "experiments/ground_truth.json")
                      if r["scenario_id"] == (scenario or "normal"))
        env.update(PRODUCT_LAB_FAULT=product, ORDER_LAB_FAULT=order, LAB_ATTEMPTS=str(attempts))
        scoped_services = ("product",) if target["request_service"] == "product" else SERVICES
        cmd = compose_command(env)

        def budget(maximum, until=deadline):
            if until is None:
                return maximum
            remaining = min(maximum, until - monotonic())
            if remaining <= 0:
                raise TimeoutError("Accounting smoke deadline reached")
            return remaining

        def compose(args, *, overlay=True, stdout=False, until=deadline):
            files = (["-f", "compose.accounting.yaml"] +
                     (["-f", "compose.faults.yaml"] if scenario else [])) if overlay else []
            if overlay and scenario == "timeout":
                files += ["-f", "compose.timeout-a.yaml"]
            result = subprocess.run(cmd + files + args, cwd=ROOT, env=env, check=True, timeout=budget(200, until),
                                    capture_output=stdout, encoding="utf-8")
            return json.loads(result.stdout) if stdout else None

        names = [s + "-service" for s in SERVICES]
        key = dict(row.split("=", 1) for row in (ROOT / ".env.context").read_text().splitlines())["CONTEXT_ES_API_KEY"]
        with httpx.Client(timeout=12, trust_env=False) as api, httpx.Client(
            base_url="http://127.0.0.1:9200", timeout=5, trust_env=False,
            headers={"Authorization": f"ApiKey {key}"},
        ) as es:
            # Reuse existing lab references without issuing setup POSTs.
            rows = api.get(URLS["order"] + "/orders", params={"limit": 1}, timeout=budget(12)).raise_for_status().json()
            if not rows:
                raise ValueError("No existing lab order to reuse for the two-request budget")
            payload = {name: rows[0][name] for name in ("user_id", "product_id", "quantity")}
            cleanup_failed = False
            post_gate.check(reserved=True)
            lease = RuntimeLease(output)
            lease.acquire()
            try:
                compose(["up", "-d", *(["--no-build"] if normal_smoke or pilot else ["--build"]), "--no-deps", *names])
                # Probe listening sockets without spending application requests.
                for service in names:
                    listener_deadline = min(monotonic() + 45, deadline) if deadline is not None else monotonic() + 45
                    while monotonic() < listener_deadline:
                        probe = subprocess.run(cmd + ["exec", "-T", service, "python", "-c",
                            "import socket; socket.create_connection(('127.0.0.1', 8000), 2).close()"],
                            cwd=ROOT, env=env, capture_output=True, timeout=budget(12, listener_deadline))
                        if probe.returncode == 0:
                            break
                        sleep(1)
                    else:
                        raise RuntimeError("Service listener not ready")
                applied = {}
                if normal_smoke or pilot:
                    for service in SERVICES:
                        applied[service] = compose(["exec", "-T", service + "-service", "python", "-c",
                            "import json,os; print(json.dumps([os.getenv(k) for k in "
                            "('LAB_ENABLED','LAB_FAULT','ACCOUNTING_TRACE_ID','ACCOUNTING_RUN_ID')]))"], stdout=True)
                        enabled, fault, armed_trace, armed_run = applied[service]
                        expected_fault = {"order": order, "product": product}.get(service, "")
                        expected_enabled = bool(scenario and service in {"order", "product"})
                        allowed_enabled = ("1",) if expected_enabled else (None, "", "0")
                        if (enabled not in allowed_enabled or (fault or "") != expected_fault
                                or (armed_trace, armed_run) != (trace_id, run_id)):
                            raise RuntimeError("Scoped runtime configuration mismatch")
                if scenario:
                    for service in ("product", "order"):
                        applied[service] = compose(["exec", "-T", service + "-service", "python", "-c",
                            "import json,os; print(json.dumps([os.getenv(k) for k in "
                            "('LAB_ENABLED','LAB_FAULT','UPSTREAM_ATTEMPTS','UPSTREAM_TIMEOUT')]))"], stdout=True)
                    if (applied["product"][:2] != ["1", product]
                            or applied["order"][:3] != ["1", order, str(attempts)]):
                        raise RuntimeError("Runtime fault configuration mismatch")
                    if scenario == "timeout":
                        verify_timeouts(applied)
                db_health = runtime_fault_db_health(budget(10)) if scenario == "database" else None
                if deadline is not None and monotonic() >= deadline:
                    raise TimeoutError("Batch reached the deadline before measured request")
                headers = {"traceparent": f"00-{trace_id}-{parent_id}-01"}
                activation_checked_at = now().isoformat()
                write(output / "activation_readback.json", {"runtime": applied, "checked_at": activation_checked_at,
                      "order_db_health_during_fault": db_health})
                request_started = monotonic()
                request_timeout = budget(12, pilot.request_deadline(request_started)) if pilot else budget(12)
                def record_attempt():
                    write(output / "request_attempt.json", {"campaign_id": pilot.campaign if pilot else "normal-a", "run_id": run_id,
                          "trace_id": trace_id, "post_attempts": 1, "runtime": applied})
                response = business_post(post_gate, api, URLS["order"] + "/orders",
                                         before_send=record_attempt, json=payload, headers=headers,
                                         timeout=request_timeout)
                capture_until = pilot.response_received(monotonic()) if pilot else deadline
                if normal_smoke or pilot:
                    write(output / "http_response.json", {"status": response.status_code, "body": response.json(),
                          "trace_id": response.headers.get("x-trace-id"), "quantity": payload["quantity"]})
                http_error = response.json().get("error", {}).get("code")
                request_ms = round((monotonic() - request_started) * 1000, 3)
                http_matches = response.status_code == target["status"] and http_error == target.get("error")
                if response.headers.get("x-trace-id") != trace_id:
                    raise RuntimeError("Measured request missing expected trace")
                if scenario == "timeout":
                    telemetry = await_timeout_trace(lambda cap: read_trace(env, trace_id, timeout=cap), capture_until)
                else:
                    sleep(.75)
                    telemetry = read_trace(env, trace_id, timeout=budget(20, capture_until))
                # Close only the armed local capture. An external caller span is outside this scope.
                docker = [e for e in telemetry if "event_id" in e]
                scoped = [{**e, "parent_id": None} if e.get("parent_id") == "0x" + parent_id and
                          e.get("kind") == "SpanKind.SERVER" else e for e in telemetry]
                store = ContextStore(es)
                probe = store.snapshot(trace_id)
                ctx = build_context(trace_id, "cross_service", None, probe)
                detail = reconcile(scoped, ctx, trace_id)
                if pilot:
                    write(output / "capture_observed.json", detail)
                source = assess(trace_id, detail, ctx.model_dump(mode="json"))
                if not source["request_completed"] or not source["parent_graph_valid"]:
                    raise ValueError("Local SERVER boundary is not closed")
                seals = {s: compose(["exec", "-T", f"{s}-service", "python", "-m",
                                     "app.producer_accounting", "seal"], stdout=True, until=capture_until) for s in scoped_services}
                expected = sorted(e for item in seals.values() for e in item["seal"]["summary"]["expected_event_ids"])
                poll_deadline = min(monotonic() + 20, capture_until) if capture_until is not None else monotonic() + 20
                while True:
                    if pilot:
                        budget(5, capture_until)
                    snap = store.snapshot(trace_id)
                    es_ids = sorted(e["event_id"] for e in snap.rows)
                    if not any(differences(expected, es_ids)) or monotonic() >= poll_deadline:
                        break
                    sleep(.5)
                inspected = {s: compose(["exec", "-T", f"{s}-service", "python", "-m",
                                         "app.producer_accounting", "inspect"], stdout=True, until=capture_until) for s in scoped_services}
                if pilot:
                    write(output / "capture_accounting.json", {"seals": seals, "inspection": inspected})
            finally:
                cleanup_until = pilot.cleanup_deadline(monotonic()) if pilot else monotonic() + 30 if normal_smoke else None
                try:
                    compose(["up", "-d", "--no-deps", *names], overlay=False, until=cleanup_until)
                    if postflight is not None:
                        restored = postflight(cleanup_until)
                        write(output / "postflight.json", restored)
                        if restored.get("status") != "PASS":
                            raise RuntimeError("Postflight did not verify restoration")
                        lease.release()
                except Exception as exc:
                    if not (normal_smoke or pilot):
                        raise
                    cleanup_failed = True
                    write(output / "postflight.json", {"status": "FAILED", "error_type": type(exc).__name__})
    comparison = compare(seals, inspected, docker, es_ids, scoped_services)
    ctx = build_context(trace_id, "cross_service", None, snap)
    detail = reconcile(scoped, ctx, trace_id)
    assessed = assess(trace_id, detail, ctx.model_dump(mode="json"))
    hashes = {e.event_id: fingerprint(e.model_dump(mode="json")) for e in ctx.events}
    observed_match = not comparison["warnings"] and assessed["docker_es_reconciled"] and not snap.truncated and not snap.timed_out
    seal = Seal(seal_version="source-seal-v1", run_id=run_id, trace_id=trace_id, source_service=target["request_service"],
                source_completion_timestamp=max(
                    datetime.fromisoformat(item["seal"]["closed_at"]) for item in seals.values()),
                root_span_completion_status=assessed["request_completed"], source_event_ids=expected,
                expected_event_count=len(expected), source_coverage="OBSERVED_CAPTURE_ONLY",
                parent_graph_valid=assessed["parent_graph_valid"], producer_accounting_version=VERSION,
                producer_evidence_sha256=fingerprint(seals), producer_services=list(scoped_services),
                transport_handoff_confirmed=False)
    missing, unexpected, duplicate = differences(expected, es_ids)
    receipt = Receipt(receipt_version="es-receipt-v1", run_id=run_id, trace_id=trace_id,
                      expected_event_ids=expected, observed_event_ids=es_ids, missing_event_ids=missing,
                      unexpected_event_ids=unexpected, duplicate_event_ids=duplicate, reconciliation_timestamp=now(),
                      ingestion_settled_status="MATCHED_CAPTURE" if observed_match else "MISMATCH",
                      event_content_matches=observed_match, event_sha256=hashes)
    write(receipt_dir / f"{trace_id}.json", envelope(seal, receipt))
    write(output / "accounting.json", {"seals": seals, "inspection": inspected})
    write(output / "reconciliation.json", {"trace_id": trace_id, "run_id": run_id,
          "requests": 2, "measured_requests": 1, "producer_events": len(expected),
          "docker_events": len(docker), "es_events": len(es_ids), "comparison": comparison,
          "deployment_only": True, "trace_complete": False})
    write(output / "snapshot.json", ctx.model_dump(mode="json"))
    if normal_smoke:
        write(output / "telemetry.json", detail)
        write(output / "activation.json", {"variant": "normal-a", "runtime": applied,
              "http_status": response.status_code, "http_error_code": http_error,
              "request_duration_ms": request_ms, "behavior_confirmed": executed("normal", http_matches, ctx)})
    if scenario:
        write(output / "telemetry.json", detail)
        write(output / "activation.json", {"variant": scenario, "runtime": applied, "expected_behavior": target,
              "http_status": response.status_code, "http_error_code": http_error,
              "activation_checked_at": activation_checked_at, "request_duration_ms": request_ms,
              "workload": {"entry_service": target["request_service"], "fixture": "existing Lab Order",
                           "quantity": payload["quantity"], "concurrency": 1},
              "configured_delay_seconds": float(applied["product"][3]) + .25 if scenario == "timeout" else None,
              "order_timeout_seconds": float(applied["order"][3]),
              "order_db_health_during_fault": db_health,
              "behavior_confirmed": executed(scenario, http_matches, ctx)})
    write(output / "checksum_manifest.json", {p.relative_to(output).as_posix(): digest(p)
                                               for p in sorted(output.rglob("*.json"))})
    if not observed_match:
        raise RuntimeError("Reconciliation did not pass; evidence preserved")
    if cleanup_failed:
        raise RuntimeError("Cleanup failed; evidence preserved")
    print(f"Verified producer scope for {trace_id}")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--execute-local", action="store_true")
    cli.add_argument("--output", type=Path, default=OUTPUT)
    args = cli.parse_args()
    if args.execute_local:
        output = args.output.resolve()
        if not output.is_relative_to((ROOT / "experiments").resolve()):
            cli.error("Output must be a new directory under experiments/")
        run(output)
    else:
        print("Dry run: GET one existing order, then one measured Order POST.")
