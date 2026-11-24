"""One approved, bounded 7A.4 campaign; no evaluation is run."""

import argparse
import csv
import json
import subprocess
import shutil
from pathlib import Path
from time import monotonic, sleep

import httpx

from app.benchmark import isolate, validate_context
from app.micro_dataset import checksum
from experiments.run_scenario import ROOT, SETUPS, URLS
from tools.audit_research import audit
from tools.collect_benchmark_7a1 import digest, write
from tools.smoke_producer_accounting import run
from tools.verify_ground_truth_7a2 import read
from tools.smoke_telemetry_7a3 import now
from app.context_store import ContextStore

FAMILY = {"normal": "negative-control", "timeout": "dependency-delay", "database": "database-disconnection",
          "processing": "order-processing", "unavailable": "product-unavailability",
          "retry": "product-unavailability", "cascade": "product-unavailability"}
MEASUREMENT_WINDOW = 420


def exclusion(technical, reviewed, historical):
    out = []
    if not technical:
        out.append("TECHNICAL_GATE_FAILED")
    if not reviewed:
        out.append("LABEL_PENDING_REVIEW")
    if historical:
        out.append("HISTORICAL_SIGNATURE_OVERLAP")
    out.append("NO_APPROVED_LOCKED_EVALUATION")
    return out


def preflight(client):
    compose_version = subprocess.run(["docker", "compose", "version", "--short"], capture_output=True,
                                    text=True, timeout=15, check=True).stdout.strip()
    memory = int(subprocess.run(["docker", "info", "--format", "{{.MemTotal}}"], capture_output=True,
                                text=True, timeout=20, check=True).stdout.strip())
    stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
                           capture_output=True, text=True, timeout=25, check=True).stdout.splitlines()
    if memory < 4 * 2**30:
        raise ValueError("Docker VM below the 4 GiB lab operating floor")
    for addr in [*URLS.values(), "http://127.0.0.1:8015"]:
        client.get(addr + "/ready").raise_for_status()
    free = shutil.disk_usage(ROOT).free
    if free < 2 * 2**30:
        raise ValueError("Workspace disk below the 2 GiB lab operating floor")
    elasticsearch_ready()
    databases = {}
    for service in URLS:
        name = f"thesis-log-anomaly-{service}-db-1"
        status = subprocess.run(["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
                                capture_output=True, text=True, timeout=15, check=True).stdout.strip()
        databases[service] = status
    if set(databases.values()) != {"healthy"}:
        raise ValueError("PostgreSQL readiness gate failed")
    return {"timestamp": now().isoformat(), "compose_version": compose_version, "workspace_disk_free_bytes": free,
            "docker_vm_bytes": memory, "elasticsearch_readable": True, "postgresql_health": databases,
            "docker_memory_snapshot": [s for s in stats if s.startswith("thesis-log-anomaly-")]}


def elasticsearch_ready():
    key = dict(row.split("=", 1) for row in (ROOT / ".env.context").read_text().splitlines())["CONTEXT_ES_API_KEY"]
    with httpx.Client(base_url="http://127.0.0.1:9200", timeout=8, trust_env=False,
                      headers={"Authorization": f"ApiKey {key}"}) as client:
        ContextStore(client).ready()


def rollback_settings():
    settings = {}
    for service in URLS:
        result = subprocess.run(["docker", "exec", f"thesis-log-anomaly-{service}-service-1", "python", "-c",
            "import json,os; print(json.dumps({k:os.getenv(k) for k in "
            "('LAB_FAULT','LAB_ENABLED','ACCOUNTING_TRACE_ID')}))"], capture_output=True, text=True,
            timeout=15, check=True)
        settings[service] = json.loads(result.stdout)
    return settings


def rollback_readiness(client):
    until = monotonic() + 35
    while True:
        statuses = {}
        for service, addr in URLS.items():
            try:
                statuses[service] = client.get(addr + "/ready").status_code
            except httpx.HTTPError:
                statuses[service] = None
        if all(code == 200 for code in statuses.values()) or monotonic() >= until:
            return statuses
        sleep(1)


def finalize(output, scenario, before, elapsed, *, collector_error=None):
    after = audit()
    check_paths = ("benchmark_7a1_pilot_seed124", "benchmark_7a2_verification",
                   "benchmark_7a3_smoke", "benchmark_7a3b_smoke")
    historic = {}
    for name in check_paths:
        src = ROOT / "experiments" / name
        hashes = read(src / "checksum_manifest.json")
        if any(digest(src / rel) != value for rel, value in hashes.items()):
            raise ValueError("Historical bundle changed")
        historic[name] = len(hashes)
    with httpx.Client(timeout=8, trust_env=False) as client:
        statuses = rollback_readiness(client)
        runtime = rollback_settings()
        elasticsearch_ready()
        rollback_ok = all(code == 200 for code in statuses.values()) and all(
            not s["LAB_FAULT"] and s["LAB_ENABLED"] not in {"1", "true"} and not s["ACCOUNTING_TRACE_ID"]
            for s in runtime.values())
        postflight = {"timestamp": now().isoformat()}
        if rollback_ok:
            try:
                postflight = preflight(client)
            except (OSError, ValueError, httpx.HTTPError, subprocess.SubprocessError) as exc:
                postflight["failure_type"] = type(exc).__name__
                rollback_ok = False
        write(output / "postflight.json", {**postflight, "ready": statuses, "runtime": runtime, "rollback_ok": rollback_ok})
        detection = client.get("http://127.0.0.1:8014/ready")
        if detection.status_code != 503 or detection.json()["error"]["code"] != "NOT_READY_FOR_SCORING":
            raise ValueError("Detection configuration changed")
        can_process = all((output / name).exists() for name in ("activation.json", "snapshot.json", "reconciliation.json"))
        row, snapshots, candidate = {}, {}, {}
        if can_process:
            rec, activation = read(output / "reconciliation.json"), read(output / "activation.json")
            trace, run_id = rec["trace_id"], rec["run_id"]
            cross = validate_context(read(output / "snapshot.json"), trace, "cross_service", None)
            if any(e.service_name == "order" for e in cross.events):
                result = client.get(f"http://127.0.0.1:8015/context/trace/{trace}",
                                    params={"mode": "single_service", "service_name": "order"})
                single = validate_context(result.raise_for_status().json(), trace, "single_service", "order")
                if single.events != [e for e in cross.events if e.service_name == "order"]:
                    raise ValueError("Single/Cross pairing mismatch")
                for context in (single, cross):
                    value = context.model_dump(mode="json")
                    isolate(value)
                    path = output / f"context-{context.mode}.json"
                    write(path, value)
                    snapshots[context.mode] = {"path": path.name, "sha256": digest(path),
                        "event_ids": context.evidence_event_ids, "completeness": context.completeness_status,
                        "snapshot_version": "incident-context-v1", "provenance": "local-es-context"}
            sig = checksum([(e.service_name, e.message, e.status_code) for e in cross.events])
            templates = {(e.service_name, e.message) for e in cross.events}
            anchor = ROOT / "experiments/benchmark_7a1_pilot_seed124"
            comparisons = []
            prior_trace, prior_ids = set(), set()
            for old in read(anchor / "run_manifest.json")["runs"]:
                old_events = read(anchor / old["snapshots"]["cross_service"]["path"])["events"]
                prior_trace.add(old["trace_id"])
                prior_ids.update(e["event_id"] for e in old_events)
                other = {(e["service_name"], e["message"]) for e in old_events}
                comparisons.append({"pilot_run_id": old["run_id"], "template_jaccard": len(templates & other) / len(templates | other),
                                    "exact_signature_match": old["exact_log_signature"] == sig,
                                    "same_fault_family": (old["scenario_variant"] == "normal" and scenario == "normal")
                                    or (old["scenario_variant"] == "cascade" and FAMILY[scenario] == "product-unavailability")})
            with (ROOT / "experiments/benchmark_7a_audit.csv").open(encoding="utf-8-sig", newline="") as stream:
                history = list(csv.DictReader(stream))
            overlap = any(entry["exact_signature_match"] for entry in comparisons) or any(
                entry["observable_status_signature_sha256"] == sig for entry in history)
            duplicate = trace in prior_trace or any(entry["trace_id"] == trace for entry in history) or bool(
                prior_ids.intersection(cross.evidence_event_ids))
            for batch in (("01", "02") if scenario == "database" else ("01",) if scenario == "timeout" else ()):
                previous = ROOT / f"experiments/benchmark_7a4_batch{batch}"
                old_rows = read(previous / "run_manifest.json")["runs"]
                old = read(previous / "snapshot.json")
                old_sig = checksum([(e["service_name"], e["message"], e["status_code"]) for e in old["events"]])
                old_templates = {(e["service_name"], e["message"]) for e in old["events"]}
                comparisons.append({"batch": batch, "historical_run_id": old_rows[0]["run_id"], "same_fault_family": False,
                    "template_jaccard": len(templates & old_templates) / len(templates | old_templates),
                    "exact_signature_match": old_sig == sig, "shared_workload_family": True,
                    "shared_campaign": False, "historical_batch": True})
                overlap |= old_sig == sig
                duplicate |= old["trace_id"] == trace or bool(set(old["evidence_event_ids"]) & set(cross.evidence_event_ids))
            technical = bool(activation["behavior_confirmed"] and not rec["comparison"]["warnings"] and
                             len(snapshots) == 2 and not duplicate and not collector_error and
                             rollback_ok)
            causes = exclusion(technical, False, overlap)
            write(output / "independence_report.json", {"group": "campaign-" + run_id, "executions": 1,
                "configuration_independence_verified": False, "new_fault_mechanism": False,
                "historical_overlap": overlap, "duplicate_identity": duplicate, "comparisons": comparisons,
                "workload": "serial Order lookup with references reused from latest lab order"})
            (output / "labels").mkdir()
            dossier = {"run_id": run_id, "trace_id": trace, "scenario_family": FAMILY[scenario],
                       "fault_configuration": activation["runtime"], "expected_behavior": activation["expected_behavior"],
                       "observed_http": activation["http_status"], "fault_behavior_confirmed": activation["behavior_confirmed"],
                       "telemetry_reference": "telemetry.json", "producer_reference": "accounting.json",
                       "candidate_root_cause": ({"timeout": "Product lookup exceeded Order timeout",
                         "database": "Order request repository could not connect using the lab request DSN"}.
                         get(scenario) if activation["behavior_confirmed"] else None),
                       "candidate_root_cause_service": ({"timeout": "product", "database": "order"}.get(scenario)
                                                        if activation["behavior_confirmed"] else None),
                       "contradictory_evidence": [] if activation["behavior_confirmed"] else ["FAULT_NOT_CONFIRMED"],
                       "missing_evidence": ["INDEPENDENT_REVIEW", "FILEBEAT_PER_EVENT_ACK"],
                       "verification_status": "UNVERIFIED",
                       "reviewer_status": "NEEDS_REVIEW",
                       "supporting_evidence": {"event_ids": cross.evidence_event_ids}}
            write(output / "labels/dossier.json", dossier)
            write(output / "labels/reviewer_form.json", {"run_id": run_id, "dossier_sha256": checksum(dossier),
                  "status": "NEEDS_REVIEW", "reviewer_id": None, "reviewed_at": None, "reason": None})
            candidate = {"run_id": run_id, "fault_family": FAMILY[scenario], "independence_group": "campaign-" + run_id,
                "ground_truth_status": "LABEL_PENDING_REVIEW", "telemetry_quality": "TECHNICALLY_VALID" if technical else "FAILED",
                "completeness": cross.completeness_status, "pairing_status": "PAIRED" if snapshots else "UNPAIRED",
                "leakage_check": "HISTORICAL_OVERLAP" if overlap else "NO_KNOWN_SIGNATURE_OVERLAP",
                "eligibility_decision": "EXCLUDED", "exclusion_reasons": causes}
            row = {"run_id": run_id, "trace_id": trace, "scenario": scenario, "http_status": activation["http_status"],
                "transport_handoff": "UNCONFIRMED", "events": rec["producer_events"], "docker_events": rec["docker_events"],
                "es_events": rec["es_events"], "fault_activation_observed": activation["behavior_confirmed"],
                "status": candidate["telemetry_quality"]}
    write(output / "campaign_manifest.json", {"variant": scenario, "limits": {"measured_requests": 1, "application_requests": 2,
          "measurement_window_seconds": MEASUREMENT_WINDOW},
          "preflight": before, "post_rollback_readiness": statuses, "elapsed_seconds": elapsed,
          "collection_error": collector_error, "locked_evaluation": False, "historical_checks": historic, "research_audit": after})
    write(output / "run_manifest.json", {"runs": [row] if row else []})
    write(output / "snapshot_manifest.json", {"pair_id": "pair-" + row["run_id"],
          "run_id": row["run_id"], "trace_id": row["trace_id"], "snapshots": snapshots} if row else {})
    write(output / "telemetry_audit.json", {**row, "reconciliation": read(output / "reconciliation.json") if row else None})
    write(output / "evaluation_candidates.json", [candidate] if candidate else [])
    with (output / "telemetry_audit.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        csv_writer = csv.DictWriter(stream, fieldnames=list(row) or ["status"])
        csv_writer.writeheader()
        csv_writer.writerow(row or {"status": "COLLECTION_FAILED"})
    checks = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob("*"))
              if p.is_file() and p.name != "bundle_sha256.json"}
    write(output / "bundle_sha256.json", checks)
    print(json.dumps({"record": row, "candidate": candidate, "verified_hashes": len(checks)}))
    if not rollback_ok:
        raise RuntimeError("Rollback verification failed; evidence preserved")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scenario", choices=SETUPS, default="cascade")
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--execute-lab", action="store_true")
    args = cli.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "experiments"):
        cli.error("Use a new output directory in experiments/")
    if not args.execute_lab:
        print(json.dumps({"dry_run": True, "variant": args.scenario, "request_budget": 2}))
        return
    try:
        with httpx.Client(timeout=8, trust_env=False) as client:
            before = preflight(client)
        for batch in (("01", "02") if args.scenario == "database" else ("01",)):
            prior = ROOT / f"experiments/benchmark_7a4_batch{batch}"
            locked = read(prior / "bundle_sha256.json")
            if any(digest(prior / name) != value for name, value in locked.items()):
                raise ValueError(f"Batch {batch} checksum mismatch")
            before[f"batch{batch}_hashes_verified"] = len(locked)
    except (OSError, ValueError, httpx.HTTPError, subprocess.SubprocessError) as exc:
        output.mkdir()
        write(output / "preflight_blocker.json", {"timestamp": now().isoformat(), "failure_type": type(exc).__name__,
                                                 "status": "PREFLIGHT_FAILED", "measured_requests": 0})
        raise SystemExit("Preflight failed; see blocker artifact") from None
    start = monotonic()
    failure = None
    try:
        run(output, scenario=args.scenario, deadline=start + MEASUREMENT_WINDOW, preflight_record=before)
    except (ValueError, RuntimeError, TimeoutError, httpx.HTTPError, subprocess.SubprocessError) as exc:
        failure = type(exc).__name__
    finalize(output, args.scenario, before, round(monotonic() - start, 3), collector_error=failure)
    if failure:
        raise SystemExit("Collection failed; see audit artifact")


if __name__ == "__main__":
    main()
