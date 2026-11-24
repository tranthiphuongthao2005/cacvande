"""Validate the 7A.5A planning artifacts without operational requests."""
import argparse
import csv
import json
from pathlib import Path

from tools.audit_research import audit
from tools.consolidate_7a4 import consolidate, write_csv

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "experiments/benchmark_7a5"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reviewer_rows(queue):
    for row in queue:
        dossier_path = ROOT / row["evidence_dossier_path"]
        dossier = read(dossier_path)
        batch_root = dossier_path.parent.parent
        activation = batch_root / "activation.json"
        telemetry = batch_root / "telemetry.json"
        supporting = dossier["supporting_evidence"]
        referenced_telemetry = batch_root / supporting.get("telemetry_reference", "") if supporting.get("telemetry_reference") else None
        if not telemetry.is_file() and referenced_telemetry and not referenced_telemetry.is_file():
            referenced_telemetry = ROOT / "experiments" / supporting["telemetry_reference"]
        telemetry = telemetry if telemetry.is_file() else referenced_telemetry
        yield {
            **row,
            "review_status": dossier["reviewer_status"],
            "candidate_label": dossier.get("candidate_label") or dossier.get("candidate_root_cause") or "UNSPECIFIED",
            "activation_evidence": activation.relative_to(ROOT).as_posix() if activation.is_file() else "See dossier; no independent activation record asserted",
            "http_behavior": json.dumps(dossier.get("observed_behavior", dossier.get("observed_http")), ensure_ascii=False),
            "log_span_evidence": telemetry.relative_to(ROOT).as_posix() if telemetry and telemetry.is_file() else "See event/span references in dossier",
            "supporting_event_ids": " ".join(supporting["event_ids"]),
            "contradictory_evidence": json.dumps(dossier.get("contradictory_evidence"), ensure_ascii=False),
            "access_scope": "GROUND_TRUTH_REVIEW_ONLY",
        }


def validate(*, write_queue=False):
    plan = read(PLAN / "cohort_plan.json")
    protocol = read(PLAN / "evaluation_protocol.json")
    batches = read(PLAN / "collection_batches.json")
    configs = plan["configs"]
    ids = {c["id"] for c in configs}
    require(len(ids) == len(configs) == 14, "Expected 14 planning slots")
    require({c["family"] for c in configs} == {b["family"] for b in batches["batches"]}
            and len(batches["batches"]) == 7, "Batch coverage mismatch")
    for priority, batch in enumerate(batches["batches"], 1):
        group = [c for c in configs if c["family"] == batch["family"]]
        require(len(group) == 2 and [c["id"] for c in group] == batch["config_ids"]
                and group[0]["mechanism"] != group[1]["mechanism"] and batch["priority"] == priority,
                "Configuration slots must describe different proposed mechanisms or workflows")
        require(batch["cap_target_requests"] == 2 * plan["traces_per_configuration"]
                and batch["cap_setup_requests"] == 8 and batch["extra_target_retries"] == 0, "Request cap changed")
    require(plan["configuration_independence_verified"] == 0
            and all(c["status"] in {"DESIGN_BLOCKED", "IMPLEMENTED_PATH_UNVERIFIED"}
                    and bool(c["blocked_reason"]) == (c["status"] == "DESIGN_BLOCKED") for c in configs),
            "Unsubstantiated configuration status")
    require(protocol["modes"] == {"single": "order", "cross": "same trace"} and protocol["snapshot_cutoff_seconds"] == 420
            and set(protocol["completeness"]) == {"COMPLETE", "PARTIAL", "UNKNOWN"}, "Snapshot protocol changed")
    require(protocol["cohorts"] == {"historical": "excluded", "development_pilot": "excluded",
                                     "integration_smoke": "excluded", "batches_01_03": "excluded",
                                     "new_candidates": "pending independent review"}, "Cohort exposure rule changed")
    cost = protocol["cost"]
    pairs = len(configs) * plan["traces_per_configuration"]
    calls = pairs * cost["calls_per_pair"]
    require(pairs == plan["planned_pairs_ceiling"] == cost["pairs"] == 28
            and calls == cost["call_cap"] == 56 and cost["extra_calls"] == 0
            and cost["input_token_cap_plan"] == calls * cost["input_tokens_per_call_planning"]
            and cost["output_token_cap_plan"] == calls * protocol["model"]["output_tokens"], "Cost cap mismatch")
    require(protocol["lock_sha256"] is None and protocol["provider_calls_authorized"] is False
            and batches["status"] == "NOT_AUTHORIZED", "Planning artifacts cannot authorize execution")
    # Existing consolidation validates hashes, context pairing, eligibility and blank forms.
    inventory, queue, summaries, historical = consolidate()
    require(len(inventory) == 43 and len(queue) == 7 and len(summaries) == 3, "Historical inventory changed")
    rows = list(reviewer_rows(queue))
    require(all(row["review_status"] == "NEEDS_REVIEW" for row in rows), "Unexpected reviewer decision")
    queue_path = PLAN / "reviewer_queue.csv"
    if write_queue:
        write_csv(queue_path, rows)
    with queue_path.open(encoding="utf-8-sig", newline="") as stream:
        require(list(csv.DictReader(stream)) == rows, "Reviewer packet index mismatch")
    return {
        "families": 7, "slots": len(configs), "blocked": sum(c["status"] == "DESIGN_BLOCKED" for c in configs),
        "independent_configurations_verified": 0, "planned_pairs_ceiling": pairs, "review_packets": len(rows),
        "batch_hashes": [row["batch_verified_hashes"] for row in summaries],
        "historical_hashes": historical, "research_hashes": audit()["verified_unique_files"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-queue", action="store_true", help="Create reviewer packet index once")
    print(json.dumps(validate(write_queue=parser.parse_args().write_queue), ensure_ascii=True))
