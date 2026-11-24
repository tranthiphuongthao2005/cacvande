"""Read-only readiness checks for the 7A.5I benchmark candidate."""
import argparse
import json
from collections import Counter
from pathlib import Path

from app.benchmark import validate_manifest
from app.micro_dataset import checksum
from tools.collect_benchmark_7a1 import digest
from tools.consolidate_7a4 import consolidate, pairing, verify_hashes
from tools.import_review_7a3 import Decision, verify
from tools.validate_7a5d import PLAN, ROOT, descriptor, read
from tools.verify_ground_truth_7a2 import validate_review

CANDIDATES = PLAN / "benchmark_candidates_7a5i"
HANDOFF = PLAN / "processing_a_reviewer_handoff_7a5h"


def check_reference(root, ref):
    path = (root / ref["path"]).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or digest(path) != ref["sha256"]:
        raise ValueError("Artifact integrity check failed")
    return path


def reviewer_packet(folder):
    dossier = read(folder / "dossier.json")
    validate_review(read(folder / "review_form.json"), dossier)
    template = Decision.model_validate(read(folder / "reviewer_decision_template.json"))
    if (template.run_id != dossier["run_id"] or template.reviewed_evidence_references != ["dossier:" + checksum(dossier)]
            or any((template.reviewer_id, template.reviewed_at, template.decision, template.justification))
            or dossier["verification_status"] != "UNVERIFIED" or dossier["reviewer_status"] != "NEEDS_REVIEW"):
        raise ValueError("Reviewer packet is not blank or is improperly bound")
    supporting = dossier["supporting_evidence"]
    refs = [dossier["source_dossier"], dossier["source_bundle_manifest"], *supporting["artifacts"].values()]
    paths = [check_reference(ROOT, ref) for ref in refs]
    original = read(paths[0])
    bundle = paths[1].parent
    verify_hashes(bundle, paths[1].name)
    _, cross = pairing(bundle, dossier["trace_id"], read(bundle / "snapshot_manifest.json"))
    if (original["run_id"] != dossier["run_id"] or original["trace_id"] != dossier["trace_id"]
            or original["candidate_mechanism"] != dossier["candidate_mechanism"]
            or original["candidate_service"] != dossier["candidate_service"]
            or supporting["event_ids"] != cross.evidence_event_ids):
        raise ValueError("Reviewer packet evidence scope mismatch")
    return {"references_checked": len(paths), "event_count": len(cross.events), "status": "NEEDS_REVIEW"}


def actual_review(base, records, row, truth, allowlist):
    """Verify human-supplied material; fixture labels and status strings alone do not count."""
    entry = records.get(row["run_id"])
    if allowlist is None or not entry:
        return False
    dossier = read(check_reference(base, entry["dossier"]))
    signed = read(check_reference(base, entry["decision"]))
    receipt = verify(signed, dossier, allowlist)
    if (receipt["status"] != "VERIFIED" or receipt["run_id"] != row["run_id"]
            or receipt["reviewer_id"] != truth.reviewer_id or dossier["trace_id"] != truth.trace_id
            or not set(truth.supporting_event_ids) <= set(dossier["supporting_evidence"]["event_ids"])
            or dossier.get("ground_truth_sha256") != row["ground_truth"]["sha256"]
            or receipt["reviewer_id"] in entry["campaign_creator_and_approver_ids"]
            or not entry["campaign_creator_and_approver_ids"]):
        raise ValueError("Reviewer, campaign or ground-truth binding failed")
    return True


def confirmed(record, base, required):
    if (record.get("actual_approval_status") != "APPROVED"
            or record.get("decision_source") == "ADVISOR_SIMULATION"
            or record.get("authority") != "OPERATOR" or not isinstance(record.get("operator_id"), str)
            or not record["operator_id"].strip()
            or any(record.get(key) != value for key, value in required.items())):
        return False
    check_reference(base, record["evidence"])
    return True


def plan(governance_path=None, manifest_path=None, allowlist_path=None):
    register = read(CANDIDATES / "decision_register.json")
    budget = read(CANDIDATES / "protocol_candidate.json")["capacity"]
    if (len(register["decisions"]) != 6 or any(
        (d["decision_source"], d["authority"], d["actual_approval_status"]) !=
        ("ADVISOR_SIMULATION", "NON_BINDING", "PENDING") for d in register["decisions"]
    )):
        raise ValueError("Simulation register must remain non-binding")
    office = read(governance_path) if governance_path else {}
    base = governance_path.resolve().parent if governance_path else ROOT
    allowlist = read(allowlist_path) if allowlist_path else None
    approvals = office.get("approvals", {})
    candidate_refs = {key: descriptor(CANDIDATES / file)["sha256"] for key, file in (
        ("taxonomy", "taxonomy_candidate.json"), ("protocol", "protocol_candidate.json"))}
    gates = {key: confirmed(approvals.get(key, {}), base, {"candidate_sha256": value})
             for key, value in candidate_refs.items()}
    gates.update(credentials_model_cost=False, fault_adapter_readiness=False, snapshot_integrity=False)
    rows = []
    pairs = []
    groups = set()
    excluded = Counter()
    completeness = Counter()
    coverage = Counter()
    if manifest_path:
        protocol, cases = validate_manifest(manifest_path)
        model_scope = {"model_snapshot": protocol["model"], "manifest_sha256": digest(manifest_path),
                       "call_cap": budget["call_cap"], "retries": 0}
        provider = approvals.get("provider", {})
        limit = provider.get("cost_ceiling_usd")
        gates["credentials_model_cost"] = (
            provider.get("credentials_attested") is True and type(limit) in (int, float) and 0 < limit < float("inf")
            and confirmed(provider, base, model_scope))
        gates["snapshot_integrity"] = protocol["data_kind"] == "HUMAN_REVIEW_INPUT"
        history, *_ = consolidate()
        known_runs = {entry["run_id"] for entry in history}
        known_traces = {entry["trace_id"] for entry in history}
        for name in ("normal_a_integration_smoke", "processing_a_development_pilot"):
            prior = read(PLAN / name / "reconciliation.json")
            known_runs.add(prior["run_id"])
            known_traces.add(prior["trace_id"])
        eligible_adapters = set()
        configurations = office.get("configurations", {})
        manifest_hash = model_scope["manifest_sha256"]
        for trace, (row, truth, contexts) in cases.items():
            if row["split"] != "evaluation":
                excluded["non_evaluation"] += 1
                continue
            if row["run_id"] in known_runs or trace in known_traces:
                excluded["historical_in_evaluation"] += 1
                continue
            if not gates["snapshot_integrity"] or truth.annotation_status != "VERIFIED" or not actual_review(
                    base, office.get("reviews", {}), row, truth, allowlist):
                excluded["missing_authenticated_ground_truth"] += 1
                continue
            scope = {"group": row["group"], "manifest_sha256": manifest_hash}
            config = configurations.get(row["group"], {})
            adapter_ok = confirmed(config.get("fault_adapter", {}), base, scope)
            if adapter_ok:
                eligible_adapters.add(row["group"])
            normal = truth.root_cause_category == "normal"
            if not normal and confirmed(config.get("independence", {}), base, scope):
                groups.add(row["group"])
            rows.append((row["group"], normal))
            coverage["normal" if normal else truth.root_cause_category] += 1
            statuses = {mode: contexts[mode].completeness_status for mode in ("single_service", "cross_service")}
            completeness["/".join(statuses.values())] += 1
            pairs.append({"run_id": row["run_id"], "group": row["group"], "completeness": statuses,
                          "event_counts": {mode: contexts[mode].event_count for mode in statuses}})
        gates["fault_adapter_readiness"] = bool(rows) and {group for group, _ in rows} <= eligible_adapters
    fault = sum(not is_normal for _, is_normal in rows)
    normal = len(rows) - fault
    gates.update(verified_independent_configurations=len(groups) >= budget["min_independent_fault_groups"],
                 verified_ground_truth=fault >= budget["min_fault_pairs"] and normal >= budget["min_normal_pairs"],
                 blind_cohort_eligibility=bool(rows) and not (
                     excluded["missing_authenticated_ground_truth"] or excluded["historical_in_evaluation"]),
                 call_budget=len(rows) <= budget["pair_cap"] and 2 * len(rows) <= budget["call_cap"])
    return {"mode": "DRY_RUN_READ_ONLY", "gates": gates, "all_checks_met": all(gates.values()),
            "execution_authorized_by_tool": False, "fault_pairs": fault, "normal_pairs": normal,
            "verified_independent_fault_groups": len(groups), "coverage": dict(coverage),
            "completeness_single_cross": dict(completeness), "pairs": pairs, "excluded": dict(excluded),
            "forecast_model_calls": 2 * len(rows), "design_call_cap": budget["call_cap"], "actual_api_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-packet", type=Path)
    parser.add_argument("--governance", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--allowlist", type=Path)
    args = parser.parse_args()
    result = (reviewer_packet(args.reviewer_packet) if args.reviewer_packet else
              plan(args.governance, args.manifest, args.allowlist))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
