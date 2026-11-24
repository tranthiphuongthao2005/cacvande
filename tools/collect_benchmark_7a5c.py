"""Single approved Normal A integration smoke on the existing local stack."""
import argparse
import json
import subprocess
from pathlib import Path
from time import monotonic, sleep

import httpx

from app.benchmark import validate_context
from app.telemetry_receipts import classify, decode
from experiments.run_scenario import ROOT, URLS
from tools.collect_benchmark_7a1 import digest, write
from tools.collect_benchmark_7a4 import preflight
from tools.collect_benchmark_7a5b import dry_run
from tools.smoke_producer_accounting import run
from tools.validate_7a5 import read, validate

CONTEXT = "http://127.0.0.1:8015"
OUT_ROOT = ROOT / "experiments" / "benchmark_7a5"


def remaining(deadline, cap=10):
    seconds = min(cap, deadline - monotonic())
    if seconds <= 0:
        raise TimeoutError("Smoke time budget exhausted")
    return seconds


def runtime(deadline):
    rows = {}
    for service in URLS:
        result = subprocess.run(["docker", "exec", f"thesis-log-anomaly-{service}-service-1", "python", "-c",
            "import json,os; from app.producer_accounting import VERSION; "
            "print(json.dumps([VERSION,*[os.getenv(k) for k in "
            "('LAB_ENABLED','LAB_FAULT','ACCOUNTING_TRACE_ID','ACCOUNTING_RUN_ID')]]))"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=remaining(deadline))
        rows[service] = json.loads(result.stdout)
        version, enabled, *flags = rows[service]
        if version != "producer-accounting-v1" or enabled not in (None, "", "0") or any(flags):
            raise ValueError("Fault or accounting scope already active, or producer module unavailable")
    return rows


def postflight(deadline):
    settings = runtime(deadline)
    with httpx.Client(trust_env=False) as client:
        while True:
            checks = {**URLS, "context": CONTEXT}
            statuses = {}
            for name, base in checks.items():
                try:
                    statuses[name] = client.get(base + "/ready", timeout=remaining(deadline, 3)).status_code
                except httpx.RequestError:
                    statuses[name] = None
            if all(status == 200 for status in statuses.values()):
                break
            sleep(min(.5, remaining(deadline)))
    # Context /ready queries Elasticsearch; each app /ready queries its PostgreSQL.
    return {"status": "PASS", "runtime": settings, "readiness_http": statuses,
            "elasticsearch_verified_via_context": True, "postgresql_verified_via_app": True}


def save_pair(output, deadline):
    identity = read(output / "reconciliation.json")
    trace = identity["trace_id"]
    receipt_path = output / "receipts" / f"{trace}.json"
    seal, receipt = decode(read(receipt_path))
    snapshots = {}
    manifest = {}
    with httpx.Client(trust_env=False) as client:
        for mode, service in (("single_service", "order"), ("cross_service", None)):
            params = {"mode": mode}
            if service:
                params["service_name"] = service
            raw = client.get(f"{CONTEXT}/context/v2/trace/{trace}", params=params,
                             timeout=remaining(deadline)).raise_for_status().json()
            snapshot = validate_context(raw["context"], trace, mode, service)
            snapshots[mode] = snapshot
            report = classify(snapshot, seal, receipt)
            if not report["ingestion_reconciled"] or report["trace_complete"]:
                raise ValueError("Context snapshot failed bounded receipt reconciliation")
            path = output / f"context-{mode}.json"
            write(path, raw["context"])
            manifest[mode] = {"path": path.name, "sha256": digest(path), "event_ids": snapshot.evidence_event_ids,
                              "completeness": snapshot.completeness_status, "provenance": report,
                              "api_provenance": raw["completeness_provenance"]}
    single, cross = snapshots["single_service"], snapshots["cross_service"]
    if single.events != [event for event in cross.events if event.service_name == "order"]:
        raise ValueError("Single snapshot differs from Order projection of Cross")
    write(output / "snapshot_manifest.json", manifest)


def live(output, post_gate):
    output.mkdir(exist_ok=False)
    deadline = monotonic() + 420
    status = {"cohort": "INTEGRATION_SMOKE", "campaign_id": "normal-a", "blind_eligible": False,
              "status": "PREFLIGHT_FAILED", "post_attempts": 0}
    try:
        protected = validate()
        with httpx.Client(timeout=4, trust_env=False) as client:
            checks = preflight(client)
        checks.update(runtime=runtime(deadline), historical_audit=protected, target_post_cap=1)
        remaining(deadline)
        status["status"] = "FAILED"
        run(output, deadline=deadline, preflight_record=checks, normal_smoke=True, postflight=postflight,
            reserved_output=True, post_gate=post_gate)
        if not read(output / "activation.json")["behavior_confirmed"]:
            raise ValueError("Normal A did not match the success contract")
        save_pair(output, deadline)
        status["status"] = "PASS"
    except Exception as exc:
        status["error_type"] = type(exc).__name__
        # Avoid saving SDK/subprocess exceptions that can contain environment or credentials.
    finally:
        attempt = output / "request_attempt.json"
        if attempt.exists():
            status["post_attempts"] = read(attempt)["post_attempts"]
        write(output / "smoke_result.json", status)
        path = output / "bundle_sha256.json"
        write(path, {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob("*.json")) if p != path})
    print(json.dumps(status))
    return status["status"] == "PASS"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--campaign", required=True, choices=["normal-a"])
    cli.add_argument("--max-requests", type=int, default=1, choices=[1])
    cli.add_argument("--live", action="store_true")
    cli.add_argument("--operator-confirmed", action="store_true")
    cli.add_argument("--output", type=Path)
    cli.add_argument("--governance", type=Path)
    args = cli.parse_args()
    if not args.live:
        print(json.dumps(dry_run(args.campaign, args.max_requests)))
        return
    if not args.operator_confirmed or args.output is None:
        cli.error("Live requires operator confirmation and a new output directory")
    output = args.output.resolve()
    if output.parent != OUT_ROOT.resolve() or output.exists():
        cli.error("Use a new immediate child directory of experiments/benchmark_7a5")
    from tools.collection_gate_7a6b import CollectionBlocked, PostGate
    try:
        post_gate = PostGate(args.governance, "normal-a", output)
    except (CollectionBlocked, OSError) as exc:
        cli.error(str(exc))
    if not live(output, post_gate):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
