"""Audit frozen collection evidence and prepare non-executable 7A.8 candidates."""
import argparse
import json
import re
from datetime import datetime

from app.benchmark import isolate
from app.micro_dataset import checksum
from app.telemetry_receipts import classify, decode
from tools.collect_benchmark_7a1 import digest, executed, write
from tools.collect_benchmark_7a7 import COHORT, CohortGate, ROOT, expose, locked_plan
from tools.consolidate_7a4 import pairing, verify_hashes
from tools.fault_adapters_7a6c import ADAPTERS, verify_observed, verify_timeouts
from tools.import_review_7a3 import Decision
from tools.validate_7a5d import PLAN, read, validate

OUT = ROOT / "experiments/benchmark_7a8"
GROUPS = {"normal-a": "NC", "processing-a": "G1", "timeout-a": "G2",
          "database-a": "G3", "cascade-a": "G4"}
GROUP_EVIDENCE = {
    "NC": ("normal", "none", "Order→User/Product", "Healthy dependencies and no activation"),
    "G1": ("processing_failure", "Order before create", "Order→User/Product", "200 lookups precede processing hook"),
    "G2": ("dependency_timeout", "Product delay", "Order→Product", "Deadline, late Product 200 and closed span"),
    "G3": ("database_connection_failure", "Order request DSN", "Order→PostgreSQL", "Order 503 with healthy DB"),
    "G4": ("dependency_unavailable", "Product unavailable", "Order→Product", "Linked Product 503 and Order 502"),
}


def describe_group(label):
    mechanism, injection, edge, evidence = GROUP_EVIDENCE[label]
    return {"mechanism": mechanism, "injection_position": injection, "dependency_edge": edge,
            "distinguishing_evidence": evidence, "configuration_fingerprints": ref(COHORT / "collection_plan.json")}


def ref(p):
    return {"path": p.relative_to(ROOT).as_posix(), "sha256": digest(p)}


def signature(rows):
    return checksum(sorted({(e["service_name"], e["message"], e.get("status_code")) for e in rows},
                           key=lambda row: (row[0], row[1], str(row[2]))))


def historical_signatures():
    inventory = {}
    for p in (ROOT / "experiments").rglob("*.json"):
        if p.is_relative_to(COHORT) or p.is_relative_to(OUT):
            continue
        if not ("cross" in p.name or p.name == "snapshot.json"):
            continue
        obj = read(p)
        if isinstance(obj, dict) and obj.get("mode") == "cross_service" and obj.get("events"):
            inventory.setdefault(signature(obj["events"]), []).append(ref(p))
    return inventory


def audit():
    plan, sha = locked_plan()
    lock = datetime.fromisoformat(plan["locked_at"])
    previous = lock
    collected = read(COHORT / "cohort_manifest.json")
    eligibility = read(COHORT / "eligibility_audit.json")
    configurations = read(COHORT / "configuration_groups.json")
    assert collected["plan_sha256"] == sha and not eligibility["benchmark_locked"]
    assert len(configurations["groups"]) == 5
    historical_runs, historical_traces = expose()
    signatures = historical_signatures()
    records, inference, findings, packets, overlaps = [], [], [], [], []
    ids = {k: set() for k in ("campaign", "run", "trace", "approval", "event", "snapshot")}
    fingerprints = 0
    candidates = PLAN / "benchmark_candidates_7a5i"
    for index, (slot, row) in enumerate(zip(plan["slots"], collected["rows"], strict=True), 1):
        cfg, rep = slot["configuration_id"], slot["repetition_id"]
        case = f"case-{index:02d}"
        d = ROOT / slot["output_directory"]
        assert all(row[key] == value for key, value in slot.items())
        fingerprints += verify_hashes(d, "bundle_sha256.json")
        assert set(read(d / "bundle_sha256.json")) == {
            p.relative_to(d).as_posix() for p in d.rglob("*.json") if p.name != "bundle_sha256.json"}
        policy = COHORT / "approvals" / f"{rep}.json"
        gov = read(policy)
        b = gov["collection_batches"][cfg]
        for record in (*gov["approvals"].values(), b, gov["fault_adapters"][cfg], gov["grouping_and_capture_policy"]):
            target = (policy.parent / record["evidence"]["path"]).resolve()
            assert target.is_relative_to(policy.parent.resolve()) and digest(target) == record["evidence"]["sha256"]
        for name in ("taxonomy", "protocol"):
            record = gov["approvals"][name]
            assert record["candidate_sha256"] == digest(candidates / f"{name}_candidate.json")
            assert record["actual_approval_status"] == "APPROVED" and record["authority"] == "OPERATOR"
            source = read(policy.parent / record["evidence"]["path"])
            assert source["scope"]["candidate_sha256"] == record["candidate_sha256"]
            assert source["decision_source"] == "USER_OPERATOR_DECLARATION"
        assert b["operator_id"] == "local-project-operator" and b["collection_plan_sha256"] == sha
        assert all(b[k] == slot[k] for k in ("campaign_id", "configuration_id", "repetition_id", "output_directory"))
        approval = b["approval_id"]
        ledger = read(PLAN / "collection_approval_usage" / approval)
        assert (ledger["governance_sha256"], ledger["campaign_id"], ledger["output_directory"]) == (
            digest(policy), slot["campaign_id"], slot["output_directory"])
        consumed = datetime.fromisoformat(ledger["consumed_at"])
        assert previous < consumed < datetime.fromisoformat(b["expires_at"])
        previous = consumed
        attempt, h, r, a, p, result = (read(d / (name + ".json")) for name in (
            "request_attempt", "http_response", "reconciliation", "activation", "postflight", "acceptance_result"))
        assert attempt["post_attempts"] == result["actual_business_posts"] == r["measured_requests"] == 1
        assert result["status"] == "PASS" and result["collection_plan_sha256"] == sha and not result["blind_eligible"]
        assert r["trace_id"] == h["trace_id"] == attempt["trace_id"] == row["trace_id"]
        assert r["run_id"] == attempt["run_id"] == row["run_id"]
        run, trace = r["run_id"], r["trace_id"]
        assert trace not in historical_traces and run not in historical_runs
        for key, value in (("campaign", slot["campaign_id"]), ("run", run), ("trace", trace), ("approval", approval)):
            assert value not in ids[key]
            ids[key].add(value)
        assert p["status"] == "PASS" and set(p["readiness_http"].values()) == {200}
        assert all(not any(flags[1:]) for flags in p["runtime"].values())
        manifest = read(d / "snapshot_manifest.json")
        single, cross = pairing(d, trace, manifest)
        seal, receipt = decode(read(d / "receipts" / f"{trace}.json"))
        assert set(seal.source_event_ids) == set(receipt.observed_event_ids) == set(cross.evidence_event_ids)
        assert (seal.trace_id, seal.run_id) == (trace, run)
        assert receipt.event_content_matches and not r["comparison"]["warnings"]
        assert set(cross.evidence_event_ids).isdisjoint(ids["event"])
        ids["event"].update(cross.evidence_event_ids)
        assert r["producer_events"] == r["docker_events"] == r["es_events"] == len(cross.events)
        assert not seal.transport_handoff_confirmed and not r["trace_complete"]
        pair = {}
        for mode, snap in (("single_service", single), ("cross_service", cross)):
            assert classify(snap, seal, receipt) == manifest[mode]["provenance"]
            path = COHORT / "inference_snapshots" / trace / f"{mode}.json"
            assert digest(path) == manifest[mode]["sha256"] and digest(path) not in ids["snapshot"]
            ids["snapshot"].add(digest(path))
            isolate(read(path))
            pair[mode] = ref(path)
        adapter = ADAPTERS[cfg]
        detail = read(d / "telemetry.json")
        verify_observed(adapter, detail)
        assert a["behavior_confirmed"] and h["status"] == {"normal-a":201,"processing-a":500,"timeout-a":504,"database-a":503,"cascade-a":502}[cfg]
        assert executed(adapter.scenario or "normal", True, cross)
        if cfg == "timeout-a":
            verify_timeouts(a["runtime"])
        if cfg == "database-a":
            assert a["order_db_health_during_fault"] == "healthy"
        if cfg == "normal-a":
            assert all(not any(flags[:2]) for flags in a["runtime"].values())
        dossier_path = COHORT / "reviewer_packets" / f"{trace}.json"
        packet = read(dossier_path)
        assert (packet["trace_id"], packet["run_id"], packet["candidate_mechanism"]) == (trace, run, adapter.mechanism)
        assert packet["verification_status"] == "UNVERIFIED" and packet["reviewer_status"] == "NEEDS_REVIEW"
        assert packet["supporting_evidence"]["event_ids"] == cross.evidence_event_ids
        for v in packet["supporting_evidence"]["artifacts"].values():
            target = (ROOT / v["path"]).resolve()
            assert target.is_relative_to(d.resolve()) and digest(target) == v["sha256"]
        expected_service = {"processing-a":"order","timeout-a":"product","database-a":"order","cascade-a":"product"}.get(cfg)
        assert packet["candidate_service"] == expected_service and packet["candidate_handling"] == adapter.handling
        findings.append({"case_id":case,"run_id":run,"trace_id":trace,"candidate_mechanism":adapter.mechanism,
                         "candidate_root_service":expected_service,"candidate_handling":adapter.handling,
                         "evidence_sufficient_for_review":True,"missing_evidence":["End-to-end Filebeat handoff ACK"],
                         "contradictions":[],"review_status":"NEEDS_REVIEW","ground_truth":"UNVERIFIED","dossier":ref(dossier_path),
                         "observed": {"http":h["status"],"runtime":a["runtime"],"events":detail["docker_events"],"spans":detail["spans"]}})
        sig = signature(read(COHORT / "inference_snapshots" / trace / "cross_service.json")["events"])
        matches = signatures.get(sig, [])
        overlaps.append({"case_id":case,"group":GROUPS[cfg],"signature_sha256":sig,
                         "acceptance_matches":[x for x in matches if "/accept_7a6d2_" in x["path"]],
                         "other_historical_matches":[x for x in matches if "/accept_7a6d2_" not in x["path"]]})
        cut = {"relative_seconds_after_response":420,"clock_provenance":"collector contract; no separately persisted monotonic timestamp"}
        records.append({"case_id":case,"run_id":run,"trace_id":trace,"snapshots":pair,"cutoff":cut,
                        "completeness":{"single_service":single.completeness_status,"cross_service":cross.completeness_status},
                        "group":GROUPS[cfg],"eligibility":"PENDING_REVIEW","review_status":"NEEDS_REVIEW"})
        inference.append({"case_id":case,"snapshots":pair})
        packets.append((case, packet))
    assert fingerprints == 190 and len(records) == 10 and len(ids["event"]) == 42
    pattern = re.compile(b"|".join(re.escape(x.encode()) for k in ("run","trace","event","snapshot") for x in ids[k]))
    for path in (ROOT / "experiments").rglob("*"):
        if (path.is_file() and path.suffix in {".json",".jsonl",".csv"} and not path.is_relative_to(COHORT)
                and not path.is_relative_to(OUT) and not path.is_relative_to(PLAN/"collection_approval_usage")):
            assert not pattern.search(path.read_bytes()), path
    history = validate()
    history["acceptance_hashes"] = sum(verify_hashes(d,"bundle_sha256.json") for d in PLAN.glob("accept_7a6d2_*"))
    history["processing_pilot_hashes"] = verify_hashes(PLAN/"processing_a_development_pilot","bundle_sha256.json")
    assert history["acceptance_hashes"] == 95 and history["research_hashes"] == 63
    return sha,fingerprints,records,inference,findings,packets,overlaps,history


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--write",action="store_true")
    cli.add_argument("--require-lock-ready", action="store_true")
    args=cli.parse_args()
    result=audit()
    if args.write:
        prepare(*result)
    print("PASS integrity; 10 dossiers ready for review; benchmark remains unlocked")
    if args.require_lock_ready:
        raise SystemExit("WAITING_INDEPENDENT_REVIEW: no reviewed lock authorization")


def prepare(sha, hashes, records, inference, findings, packets, overlaps, history):
    OUT.mkdir()
    for folder in ("reviewer_package","reviewer_decision_templates"):
        (OUT/folder).mkdir()
    write(OUT/"cohort_integrity_audit.json", {"status":"PASS","collection_plan_sha256":sha,
          "locked_before_first_post":True,"execution_order":"PASS","unique_campaigns":10,"unique_runs":10,
          "unique_traces":10,"unique_approvals":10,"unique_event_ids":42,"cohort_hashes":hashes,"history":history,
          "historical_identity_and_snapshot_reuse":"PASS","approval_replay":"NONE_OBSERVED",
          "snapshot_pairing_and_isolation":"PASS"})
    write(OUT/"signature_overlap_audit.json", {"proposed_scope":"HELD_OUT_EXECUTIONS_ON_SEEN_CONFIGURATIONS",
          "primary_estimand_compatible":True,"formal_split_policy":"ADJUDICATION_REQUIRED",
          "status":"EXPLORATORY_COHORT_CANDIDATE","rows":overlaps})
    write(OUT/"ground_truth_evidence_audit.json", {"review_ready":10,"verified":0,"rows":findings})
    groups=[]
    for label in GROUPS.values():
        members=[r for r in records if r["group"]==label]
        groups.append({"group":label,"cases":[r["case_id"] for r in members],"status":"UNVERIFIED",
                       **describe_group(label),
                       "evidence":[f["dossier"] for f in findings if f["case_id"] in {r["case_id"] for r in members}]})
    write(OUT/"configuration_grouping_review.json", {"groups":groups,"verified_independent_fault_groups":0})
    write(OUT/"evaluation_manifest.candidate.json", {"status":"CANDIDATE_ONLY","approved":False,"records":records})
    write(OUT/"inference_manifest.candidate.json", {"records":inference})
    write(OUT/"reviewer_package"/"ground_truth_manifest.json", {"rows":findings})
    write(OUT/"reviewer_package"/"index.json", {"dossiers":[f"case-{i:02d}.dossier.json" for i in range(1,11)],
          "group_review":"../configuration_grouping_review.json","overlap":"../signature_overlap_audit.json"})
    for case, packet in packets:
        tag="dossier:"+checksum(packet)
        write(OUT/"reviewer_package"/f"{case}.dossier.json",packet)
        decision={"run_id":packet["run_id"],"reviewer_id":"","reviewed_at":"","decision":"",
                  "reviewed_evidence_references":[tag],"justification":""}
        Decision.model_validate(decision)
        write(OUT/"reviewer_decision_templates"/f"{case}.decision.json",decision)
        write(OUT/"reviewer_decision_templates"/f"{case}.correction.json",{"run_id":packet["run_id"],
              "source_dossier":tag,"candidate_mechanism":None,"candidate_service":None,"candidate_handling":None,
              "reviewer_id":None,"reviewed_at":None,"justification":None,"reviewed_evidence_references":[]})
    write(OUT/"reviewer_decision_templates"/"grouping.decision.json",{"reviewer_id":None,"reviewed_at":None,
          "grouping_sha256":digest(OUT/"configuration_grouping_review.json"),
          "decisions":[{"group":g["group"],"decision":None,"justification":None,"evidence":[]}
                       for g in groups if g["group"]!="NC"]})
    write(OUT/"scoring_protocol.json",{"status":"PRELOCK_CANDIDATE","primary":"Mean paired Cross minus Single root-cause correctness on eligible scorable fault pairs",
          "secondary":["root service accuracy","mechanism accuracy","propagation/handling accuracy","evidence support rate","unsupported claim rate","abstention rate","Normal false attribution","latency","input/output tokens","cost"],
          "outcomes":{"exact":1,"partial":0,"incorrect":0,"abstention":None,"provider_failure":None,"invalid_output":None,"missing_result":None},
          "all_planned_fault_denominator":8,"all_planned_non_success":["abstention","provider_failure","invalid_output","missing_result","partial","incorrect"],
          "fixed":["model","prompt template","output schema","decoding settings","evaluation cases"],
          "changed_only":"context scope","evaluable_pairs":None,"inference_authorized":False})
    write(OUT/"benchmark_lock_readiness.json",{"status":"WAITING_INDEPENDENT_REVIEW","benchmark_locked":False,
          "formal_split_status":"BLOCKED_PROTOCOL_MISMATCH",
          "scope_status":"EXPLORATORY_COHORT_CANDIDATE","gates":{"collection_integrity":True,
          "protocol_compatibility_for_formal_lock":False,"ground_truth_verification":False,"configuration_grouping_verification":False,
          "eligibility_decisions":False,"snapshot_pairing":True,"inference_isolation":True,
          "evaluation_manifest_approval":False,"signature_overlap_handling":False},
          "regression":{"pass":130,"fail":1,"fixture":"INTERMITTENT_UNRESOLVED","explicit_full_pass_lock_rule_found":False},
          "counts":{"verified_ground_truth":0,"verified_groups":0,"blind_eligible":0}})


if __name__ == "__main__":
    main()
