"""Read-only collection readiness gate for the 7A.6A proposal."""
import argparse
import json
from collections import Counter
from pathlib import Path

from tools.benchmark_readiness_7a5i import CANDIDATES, HANDOFF, confirmed, reviewer_packet
from tools.collect_benchmark_7a1 import digest
from tools.consolidate_7a4 import verify_hashes
from tools.validate_7a5d import PLAN, ROOT, read, validate

PROPOSAL = PLAN / "collection_proposal_7a6a.json"


def check(governance=None, batch_id=None, *, reserved_output=None, output_parent=PLAN):
    proposal = read(PROPOSAL)
    slots = {s["id"]: s for s in proposal["slots"]}
    previous = read(PLAN / "configuration_matrix.json")["slots"]
    batches = {b["configuration_id"]: b for b in proposal["batches"]}
    if (proposal["collection_authorized"] or len(slots) != len(proposal["slots"])
            or set(slots) != {s["id"] for s in previous}
            or any(s["independence_status"] != "UNVERIFIED" for s in slots.values())
            or any(slots[old["id"]]["fixture_verified"] != (old["status"] == "FIXTURE_VERIFIED") for old in previous)
            or any(b["approval_status"] != "PENDING" or b["maximum_business_posts"] != 1 or b["retries"] != 0
                   for b in batches.values())):
        raise ValueError("Proposal drift from approved offline scope")
    unknown = set(batches) - slots.keys()
    if unknown or batch_id is not None and batch_id not in batches:
        raise ValueError("Unknown proposed batch")
    office = read(governance) if governance else {}
    base = governance.resolve().parent if governance else ROOT
    approvals = office.get("approvals", {})
    gates = {key: confirmed(approvals.get(key, {}), base, {
        "candidate_sha256": digest(CANDIDATES / f"{key}_candidate.json")}) for key in ("taxonomy", "protocol")}

    scope = {"configuration_id": batch_id, "proposal_sha256": digest(PROPOSAL), "maximum_business_posts": 1,
             "retries": 0}
    batch_record = office.get("collection_batches", {}).get(batch_id, {})
    output = batch_record.get("output_directory")
    destination = (ROOT / output).resolve() if isinstance(output, str) and output else None
    budget = batch_record.get("overall_seconds")
    gates["batch_scope_and_budget"] = (
        batch_id is not None and destination is not None and destination.parent == output_parent.resolve()
        and (not destination.exists() if reserved_output is None else destination == reserved_output.resolve())
        and type(budget) is int and 0 < budget <= 792
        and confirmed(batch_record, base, {**scope, "rollback": batches[batch_id]["rollback"]}))
    gates["fault_adapter_verified"] = batch_id is not None and confirmed(
        office.get("fault_adapters", {}).get(batch_id, {}), base, scope)
    gates["grouping_and_capture_policy"] = batch_id is not None and confirmed(
        office.get("grouping_and_capture_policy", {}), base, scope)
    return {"mode": "DRY_RUN_READ_ONLY", "gates": gates, "all_checks_met": all(gates.values()),
            "execution_authorized_by_tool": False,
            "collection_status": "AWAITING_RUNTIME_AUTHORIZATION" if all(gates.values()) else "BLOCKED",
            "fixture_verified": sum(s["fixture_verified"] for s in slots.values()),
            "independently_verified": 0, "slots": dict(sorted(Counter(s["status"] for s in slots.values()).items())),
            "proposed_batches": len(batches), "business_posts": 0, "provider_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--governance", type=Path)
    parser.add_argument("--batch")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--require-ready", action="store_true", help="Exit nonzero if collection prechecks fail")
    args = parser.parse_args()
    result = check(args.governance, args.batch)
    if args.audit:
        result["history"] = validate()
        result["processing_hashes"] = verify_hashes(PLAN / "processing_a_development_pilot", "bundle_sha256.json")
        result["reviewer"] = reviewer_packet(HANDOFF)
    print(json.dumps(result, indent=2))
    if args.require_ready and not result["all_checks_met"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
