"""Offline reviewer intake and configuration comparison for 7A.6B."""
import argparse
import json
from itertools import combinations
from pathlib import Path

from tools.benchmark_readiness_7a5i import reviewer_packet
from tools.collection_readiness_7a6a import PROPOSAL
from tools.import_review_7a3 import verify
from tools.validate_7a5d import read

FIELDS = ("mechanism", "position", "edge", "retry")


def compare(left, right):
    changed = [field for field in FIELDS if left[field] != right[field]]
    related = left["group_hint"] == right["group_hint"]
    return {"left": left["id"], "right": right["id"], "different_fields": changed,
            "handling_changed": left["handling"] != right["handling"],
            "classification": ("REPEATED_OR_EQUIVALENT" if not changed else
                               "RELATED_VARIANT" if related else "DISTINCT_CANDIDATE"),
            "independence": "UNVERIFIED"}


def cohort():
    proposal = read(PROPOSAL)
    slots = {row["id"]: row for row in proposal["slots"]}
    families = {
        "normal": ["normal-a", "normal-a"],
        "dependency_timeout": ["timeout-a", "timeout-a"],
        "database_connection_failure": ["database-a", "database-a"],
        "processing_failure": ["processing-a", "processing-a"],
        "dependency_unavailable": ["cascade-a", "cascade-a"],
    }
    return {"proposed_executions_by_family": families, "fault_family_candidates": 4,
            "potential_fault_pairs": 8, "potential_normal_pairs": 2, "verified_independent_groups": 0,
            "blind_eligible": 0, "runtime_eligible_fault_pairs": 0,
            "adapter_status": {key: slots[key]["status"] for key in {ids[0] for ids in families.values()}},
            "comparisons": [compare(a, b) for a, b in combinations(slots.values(), 2)]}


def import_review(packet, signed, allowlist, output, *, campaign_actors=None):
    reviewer_packet(packet)
    dossier = read(packet / "dossier.json")
    receipt = verify(read(signed), dossier, read(allowlist))
    actors = read(campaign_actors) if campaign_actors else {}
    identities = actors.get("creator_and_approver_ids")
    if (actors.get("run_id") != dossier["run_id"] or not isinstance(identities, list) or not identities
            or any(not isinstance(identity, str) or not identity.strip() for identity in identities)
            or receipt["reviewer_id"] in identities):
        raise ValueError("Reviewer independence requires a matching campaign actor record")
    # The receipt records the authenticated human decision outside the source packet.
    if output.resolve().is_relative_to(packet.resolve()):
        raise ValueError("Review receipts must go to a separate reviewer-controlled directory")
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    return {"status": "IMPORTED_RECEIPT", "run_id": receipt["run_id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("cohort")
    packet = sub.add_parser("reviewer-check")
    packet.add_argument("--packet", type=Path, required=True)
    intake = sub.add_parser("reviewer-import")
    for name in ("packet", "signed", "allowlist", "output", "campaign-actors"):
        intake.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.action == "cohort":
        result = cohort()
    elif args.action == "reviewer-check":
        result = reviewer_packet(args.packet)
    else:
        result = import_review(args.packet, args.signed, args.allowlist, args.output,
                               campaign_actors=args.campaign_actors)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
