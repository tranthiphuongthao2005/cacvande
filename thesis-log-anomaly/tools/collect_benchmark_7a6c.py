"""One explicitly approved development acceptance run for a priority adapter."""
import argparse
import json
import subprocess
from pathlib import Path
from time import monotonic

import httpx

from tools.collect_benchmark_7a1 import digest, write
from tools.collect_benchmark_7a4 import preflight
from tools.collect_benchmark_7a5c import postflight, remaining, runtime, save_pair
from tools.collect_benchmark_7a5e import Deadlines
from tools.collection_gate_7a6b import CollectionBlocked, PostGate
from tools.fault_adapters_7a6c import ADAPTERS, verify_observed
from tools.smoke_producer_accounting import run
from tools.validate_7a5 import PLAN, read


def dry_run(adapter):
    return {"mode": "DRY_RUN", "cohort": "DEVELOPMENT_ACCEPTANCE", "blind_eligible": False,
            "campaign_id": adapter.campaign, "configuration_id": adapter.configuration,
            "maximum_business_posts": 1, "actual_business_posts": 0, "retries": 0}


def execute(adapter, output, gate, *, metadata=None):
    gate.check(reserved=False)
    output.mkdir(exist_ok=False)
    deadlines = Deadlines(monotonic())
    deadlines.campaign = gate.campaign
    status = {**dry_run(adapter), "mode": "LIVE", "status": "INCOMPLETE"}
    if metadata is not None:
        status.update(metadata)
    refs = ("preflight.json", "activation.json", "request_attempt.json", "http_response.json", "accounting.json",
            "reconciliation.json", "telemetry.json", "context-single_service.json", "context-cross_service.json",
            "snapshot_manifest.json", "postflight.json")
    try:
        with httpx.Client(timeout=4, trust_env=False) as api:
            checks = preflight(api)
        checks.update(runtime=runtime(deadlines.preflight), approval_sha256=gate.governance_hash, target_post_cap=1)
        remaining(deadlines.preflight)
        run(output, scenario=adapter.scenario, deadline=deadlines.activation, preflight_record=checks,
            normal_smoke=adapter.scenario is None, postflight=postflight,
            reserved_output=True, pilot=deadlines, post_gate=gate)
        activation = read(output / "activation.json")
        if not activation["behavior_confirmed"] or (adapter.scenario == "database"
                and activation["order_db_health_during_fault"] != "healthy"):
            raise ValueError("Adapter did not meet its expected evidence")
        verify_observed(adapter, read(output / "telemetry.json"))
        save_pair(output, deadlines.settle())
        identity = read(output / "reconciliation.json")
        (output / "labels").mkdir()
        write(output / "labels" / "dossier.json", {
            "run_id": identity["run_id"], "trace_id": identity["trace_id"],
            "configuration": adapter.configuration, "candidate_mechanism": adapter.mechanism,
            "candidate_handling": adapter.handling, "cohort": status["cohort"],
            "candidate_service": {"timeout": "product", "cascade": "product", "processing": "order",
                                  "database": "order"}.get(adapter.scenario),
            "blind_eligible": False, "reviewer_status": "NEEDS_REVIEW", "verification_status": "UNVERIFIED",
            "references": {name: digest(output / name) for name in refs},
        })
        status["status"] = "PASS"
    except (TimeoutError, subprocess.TimeoutExpired, httpx.TimeoutException):
        status["status"] = "TIMEOUT"
    except Exception as exc:
        status["error_type"] = type(exc).__name__
    finally:
        attempt = output / "request_attempt.json"
        if attempt.exists():
            status["actual_business_posts"] = read(attempt)["post_attempts"]
        write(output / "acceptance_result.json", status)
        manifest = output / "bundle_sha256.json"
        write(manifest, {p.relative_to(output).as_posix(): digest(p)
                         for p in sorted(output.rglob("*.json")) if p != manifest})
    print(json.dumps(status))
    return status["status"] == "PASS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", required=True, choices=ADAPTERS)
    parser.add_argument("--governance", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    adapter = ADAPTERS[args.configuration]
    if not args.live:
        print(json.dumps(dry_run(adapter)))
        return
    if args.governance is None or args.output is None:
        parser.error("Live acceptance requires governance and a new output")
    output = args.output.resolve()
    if output.parent != PLAN.resolve() or output.exists():
        parser.error("Use a new immediate child of experiments/benchmark_7a5")
    try:
        gate = PostGate(args.governance, adapter.campaign, output)
        if read(args.governance)["collection_batches"][adapter.configuration]["overall_seconds"] != 792:
            raise CollectionBlocked("Acceptance needs the approved 792-second envelope")
    except (CollectionBlocked, OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    if not execute(adapter, output, gate):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
