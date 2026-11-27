"""Approval-gated one-request Processing A development pilot."""
import argparse
import json
import subprocess
from pathlib import Path
from time import monotonic, sleep

import httpx

from tools.collect_benchmark_7a1 import digest, write
from tools.collect_benchmark_7a4 import preflight
from tools.collect_benchmark_7a5c import postflight, remaining, runtime, save_pair
from tools.smoke_producer_accounting import run
from tools.validate_7a5 import PLAN, ROOT, read

CAMPAIGN = "processing-a-development-pilot"
CONFIG = "processing-a"
SCOPE = {"service": "order", "fault": "processing"}
ROLLBACK = "restore-baseline-compose-without-fault-or-accounting-overlays-and-verify-readiness"


class Deadlines:
    campaign = CAMPAIGN

    def __init__(self, started):
        self.preflight = started + 120
        self.activation = self.preflight + 180
        self.overall = self.activation + 12 + 420 + 30 + 30
        self.cutoff = None

    def request_deadline(self, now):
        if now >= self.activation:
            raise TimeoutError("Activation deadline reached")
        return min(now + 12, self.activation)

    def response_received(self, now):
        self.cutoff = now + 420
        return min(now + 120, self.overall - 30)

    def cleanup_deadline(self, now):
        return min(now + 30, self.overall)

    def settle(self, clock=monotonic, wait=sleep):
        if self.cutoff is None:
            raise ValueError("A measured response is required")
        deadline = min(self.cutoff + 30, self.overall)
        if clock() >= deadline:
            raise TimeoutError("Snapshot deadline reached")
        while clock() < self.cutoff:
            wait(min(1, self.cutoff - clock()))
        if clock() >= deadline:
            raise TimeoutError("Snapshot deadline reached")
        return deadline


def approval_matches(record, output):
    return (
        record.get("schema_version") == "7A.5E-pilot-approval-v1"
        and record.get("status") == "APPROVED"
        and isinstance(record.get("operator"), str) and bool(record["operator"].strip())
        and record.get("campaign_id") == CAMPAIGN
        and record.get("configuration_id") == CONFIG
        and type(record.get("maximum_business_posts")) is int and record["maximum_business_posts"] == 1
        and record.get("output_directory") == output.relative_to(ROOT).as_posix()
        and record.get("fault_scope") == SCOPE and record.get("rollback_plan") == ROLLBACK
    )


def dry_run():
    return {"mode": "DRY_RUN", "live_status": "LIVE_NOT_AUTHORIZED", "campaign_id": CAMPAIGN,
            "configuration_id": CONFIG, "maximum_business_posts": 1, "actual_business_posts": 0,
            "snapshot_offset_seconds": 420, "overall_seconds": 792}


def execute(output, approval, approval_path, post_gate):
    output.mkdir(exist_ok=False)
    deadlines = Deadlines(monotonic())
    status = {"cohort": "DEVELOPMENT_PILOT", "blind_eligible": False, "post_attempts": 0,
              "status": "INCOMPLETE", "campaign_id": CAMPAIGN}
    try:
        with httpx.Client(timeout=4, trust_env=False) as client:
            checks = preflight(client)
        checks.update(runtime=runtime(deadlines.preflight), approved_scope=SCOPE,
                      approval_sha256=digest(approval_path), target_post_cap=approval["maximum_business_posts"])
        remaining(deadlines.preflight)
        run(output, scenario="processing", deadline=deadlines.activation,
            preflight_record=checks, postflight=postflight, reserved_output=True, pilot=deadlines, post_gate=post_gate)
        activation = read(output / "activation.json")
        detail = read(output / "telemetry.json")
        spans = detail["spans"]
        if (not activation["behavior_confirmed"] or detail["closed_root_spans"] != 1
                or sum(s["kind"] == "SpanKind.CLIENT" and s["service"] == "order" for s in spans) != 2
                or not {"user", "product"} <= {
                    s["service"] for s in spans if s["kind"] == "SpanKind.SERVER"}):
            raise ValueError("Processing failure evidence contract not met")
        save_pair(output, deadlines.settle())
        reconciliation = read(output / "reconciliation.json")
        (output / "labels").mkdir()
        write(output / "labels" / "dossier.json", {
            "run_id": reconciliation["run_id"], "trace_id": reconciliation["trace_id"],
            "configuration": CONFIG, "candidate_mechanism": "processing_failure",
            "candidate_service": "order", "reviewer_status": "NEEDS_REVIEW",
            "verification_status": "UNVERIFIED",
            "references": {name: digest(output / name) for name in ("activation.json", "telemetry.json",
                                                                     "snapshot_manifest.json", "postflight.json")},
        })
        status["status"] = "PASS"
    except (TimeoutError, subprocess.TimeoutExpired, httpx.TimeoutException):
        status["status"] = "TIMEOUT"
    except Exception as exc:
        status["error_type"] = type(exc).__name__
    finally:
        attempt = output / "request_attempt.json"
        if attempt.exists():
            status["post_attempts"] = read(attempt)["post_attempts"]
        write(output / "pilot_result.json", status)
        manifest = output / "bundle_sha256.json"
        write(manifest, {p.relative_to(output).as_posix(): digest(p)
                         for p in sorted(output.rglob("*.json")) if p != manifest})
    print(json.dumps(status))
    return status["status"] == "PASS"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--campaign", choices=[CAMPAIGN], required=True)
    cli.add_argument("--live", action="store_true")
    cli.add_argument("--approval-file", type=Path)
    cli.add_argument("--governance", type=Path)
    cli.add_argument("--output", type=Path)
    cli.add_argument("--max-requests", type=int, choices=[1], default=1)
    args = cli.parse_args()
    if not args.live:
        print(json.dumps(dry_run()))
        return
    if args.approval_file is None or args.output is None:
        cli.error("LIVE_NOT_AUTHORIZED: separate approval and output are required")
    output = args.output.resolve()
    if output.parent != PLAN.resolve() or output.exists():
        cli.error("Use a new immediate child of experiments/benchmark_7a5")
    try:
        approval = read(args.approval_file)
        authorized = approval_matches(approval, output)
    except (OSError, ValueError, AttributeError):
        authorized = False
    if not authorized:
        cli.error("LIVE_NOT_AUTHORIZED: scope or approval mismatch")
    from tools.collection_gate_7a6b import CollectionBlocked, PostGate
    try:
        post_gate = PostGate(args.governance, CAMPAIGN, output)
    except (CollectionBlocked, OSError) as exc:
        cli.error(str(exc))
    if not execute(output, approval, args.approval_file, post_gate):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
