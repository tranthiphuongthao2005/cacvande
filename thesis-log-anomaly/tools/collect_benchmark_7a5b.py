"""Offline campaign planning and bounded collection against an injected fixture adapter."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from app.benchmark import validate_context
from app.telemetry_receipts import differences
from tools.validate_7a5 import PLAN, read


def select(campaign):
    return next((row for row in read(PLAN / "collection_batches.json")["batches"]
                 if campaign in row["config_ids"]), None)


def dry_run(campaign, requests=2, seconds=420, cleanup_seconds=30):
    batch = select(campaign)
    if (batch is None or not 1 <= requests <= 2 or not 0 < seconds <= 420
            or not 0 < cleanup_seconds <= 30):
        raise ValueError("Select one configuration and valid request/runtime limits")
    return {"mode": "DRY_RUN", "campaign": campaign, "target_request_cap": requests,
            "setup_requests": 0, "work_seconds": seconds, "cleanup_seconds": cleanup_seconds,
            "maximum_seconds": seconds + cleanup_seconds, "target_requests": 0}


def verify_run(sample, seen_traces, seen_events):
    trace = sample["trace_id"]
    single = validate_context(sample["single"], trace, "single_service", "order")
    cross = validate_context(sample["cross"], trace, "cross_service", None)
    ids = [event.event_id for event in cross.events]
    if (single.events != [event for event in cross.events if event.service_name == "order"]
            or ids != cross.evidence_event_ids
            or single.evidence_event_ids != [event.event_id for event in single.events]
            or trace in seen_traces or set(ids) & seen_events):
        raise ValueError("Pairing or execution independence failed")
    producer, docker, es = (sample[name] for name in ("producer", "docker", "es"))
    if (not sample["seal_closed"] or not sample["activation_verified"]
            or any(differences(ids, [row["event_id"] for row in source]) != ([], [], [])
                   for source in (producer, docker, es))
            or any({row["event_id"]: row["payload_sha256"] for row in source} !=
                   {row["event_id"]: row["payload_sha256"] for row in producer} for source in (docker, es))
            or not sample["handoff_confirmed"] and
                "COMPLETE" in {single.completeness_status, cross.completeness_status}):
        raise ValueError("Activation, telemetry or completeness mismatch")
    seen_traces.add(trace)
    seen_events.update(ids)


def write_bundle(directory, record, samples):
    directory.mkdir()
    artifacts = {"collection.json": record}
    for number, sample in enumerate(samples, 1):
        artifacts[f"run-{number}.single.json"] = sample["single"]
        artifacts[f"run-{number}.cross.json"] = sample["cross"]
        artifacts[f"run-{number}.telemetry.json"] = {
            key: value for key, value in sample.items() if key not in {"single", "cross", "dossier"}}
        artifacts[f"labels/run-{number}.json"] = {**sample["dossier"], "trace_id": sample["trace_id"],
                                                 "status": "NEEDS_REVIEW"}
    hashes = {}
    for name, value in artifacts.items():
        path = directory / name
        path.parent.mkdir(exist_ok=True)
        payload = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
        path.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    (directory / "bundle_sha256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")


async def collect_fixture(campaign, adapter, output, *, requests=2, seconds=420, cleanup_seconds=30):
    """Fixture adapter operations must be cancellable and perform zero hidden POSTs."""
    record = dry_run(campaign, requests, seconds, cleanup_seconds)
    matrix = read(PLAN / "configuration_matrix.json")
    if not any(slot["id"] == campaign and slot["status"] == "FIXTURE_VERIFIED" for slot in matrix["slots"]):
        raise ValueError("Configuration is not available for fixture collection")
    if output.exists():
        raise FileExistsError(output)
    record.update(mode="FIXTURE_ONLY", cohort="engineering_fixture", blind_eligible=False,
                  rollback="NOT_REQUIRED", postflight="NOT_RUN")
    samples, seen_traces, seen_events = [], set(), set()
    preflight = False
    activation_started = False
    try:
        async with asyncio.timeout(seconds):
            record["preflight"] = await adapter.preflight()
            if record["preflight"].get("ok") is not True:
                raise ValueError("Preflight rejected")
            preflight = True
            activation_started = True
            if await adapter.activate(campaign) is not True:
                raise ValueError("Fault activation was not verified")
            for _ in range(requests):
                record["target_requests"] += 1
                response = await adapter.post_once()
                sample = await adapter.capture(response)
                verify_run(sample, seen_traces, seen_events)
                samples.append(sample)
        record["status"] = "FIXTURE_VALID"
    except Exception as exc:
        record["status"] = ("TIMEOUT" if isinstance(exc, TimeoutError) else
                            "FAILED" if preflight else "PREFLIGHT_FAILED")
        record["error_type"] = type(exc).__name__
    finally:
        if activation_started:
            try:
                async with asyncio.timeout(cleanup_seconds):
                    if await adapter.rollback() is not True:
                        raise RuntimeError("Rollback could not be verified")
                    record["rollback"] = "VERIFIED"
                    record["postflight"] = await adapter.postflight()
                    if record["postflight"].get("ok") is not True:
                        raise RuntimeError("Postflight rejected")
            except Exception:
                if record["rollback"] != "VERIFIED":
                    record["rollback"] = "FAILED"
                record["status"] = "CLEANUP_FAILED"
        write_bundle(output, record, samples)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--max-requests", type=int, default=2)
    parser.add_argument("--max-runtime", type=int, default=420)
    parser.add_argument("--cleanup-timeout", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(dry_run(args.campaign, args.max_requests, args.max_runtime, args.cleanup_timeout)))
