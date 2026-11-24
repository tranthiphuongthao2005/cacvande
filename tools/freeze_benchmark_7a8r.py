"""Freeze and verify the 7A.8R exploratory dataset without provider calls."""
import argparse
import json
import os
from pathlib import Path
from random import Random

from app.benchmark import isolate
from app.llm_analysis import ModelAnalysis, PROMPT, PROMPT_VERSION
from app.micro_dataset import checksum
from tools.audit_benchmark_7a8 import OUT as FORMAL, audit
from tools.collect_benchmark_7a1 import digest, write
from tools.collect_benchmark_7a7 import COHORT, ROOT, locked_plan, read
from tools.consolidate_7a4 import pairing, verify_hashes
from tools.fault_adapters_7a6c import ADAPTERS, verify_observed, verify_timeouts
from tools.validate_7a5d import PLAN, validate

OUT = ROOT / "experiments/benchmark_7a8r_exploratory"
TYPE = "CONTROLLED_EXPLORATORY_EVALUATION"
SCOPE = "HELD_OUT_EXECUTIONS_ON_SEEN_CONFIGURATIONS"
SOURCE = "FAULT_INJECTION_DERIVED"
MODES = ("single_service", "cross_service")
FROZEN = {"exploratory_protocol.json", "reference_labels.json", "reference_label_audit.json",
          "evaluation_manifest.json", "inference_manifest.json", "scoring_protocol.json",
          "evaluation_plan.json", "limitations.json"}
LIMITS = ["Ten executions, five seen configurations, four candidate failure families",
          "Fault prevalence 80% by design; two executions per configuration",
          "Observable signatures overlap development and acceptance data",
          "Reference labels have no independent ground-truth review",
          "Single UNKNOWN; Cross PARTIAL; TRACE_COMPLETE=false; Filebeat handoff UNCONFIRMED",
          "Processing fixture INTERMITTENT_UNRESOLVED; regression 130 PASS, 1 FAIL",
          "Microservice MeCoLog scoring remains unverified; no broad generalization"]
STATUS = {"normal-a": (201, None), "processing-a": (500, "order_processing_error"),
          "timeout-a": (504, "dependency_timeout"), "database-a": (503, "database_unavailable"),
          "cascade-a": (502, "dependency_unavailable")}


def file_ref(path):
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}


def checked(ref, scope):
    path = (ROOT / ref["path"]).resolve(strict=True)
    if not path.is_relative_to(scope.resolve()) or digest(path) != ref["sha256"]:
        raise ValueError("Evidence scope or digest mismatch")
    return path


def label_checks(config, activation, detail, response):
    verify_observed(ADAPTERS[config], detail)
    status, error = STATUS[config]
    if (response["status"], response["body"].get("error", {}).get("code")) != (status, error):
        raise ValueError("HTTP contract mismatch")
    events = detail["docker_events"]
    event_names = {e["event"] for e in events if e["service"] == "order"}
    runtime = activation["runtime"]
    active = {
        service: row[1] or "" for service, row in runtime.items()
    }
    expected = {"user": "", "product": {"timeout-a": "delay", "cascade-a": "unavailable"}.get(config, ""),
                "order": {"processing-a": "processing", "database-a": "database"}.get(config, "")}
    if active != expected or not activation["behavior_confirmed"]:
        raise ValueError("Runtime activation mismatch")
    if config == "normal-a" and any(row[0] for row in runtime.values()):
        raise ValueError("Normal has lab activation")
    if config == "processing-a":
        hook = [e for e in events if e["service"] == "order" and e["event"] == "order_processing_failed"]
        deps = [e for e in events if e["service"] in {"product", "user"} and e.get("status") == 200]
        if len(hook) != 1 or len(deps) != 2 or not all(e["timestamp"] < hook[0]["timestamp"] for e in deps):
            raise ValueError("Processing stage evidence mismatch")
    if config == "timeout-a":
        verify_timeouts(runtime)
        if "dependency_attempt_failed" not in event_names:
            raise ValueError("Timeout caller evidence missing")
    if config == "database-a" and (activation["order_db_health_during_fault"] != "healthy"
                                   or "database_connection_failed" not in event_names):
        raise ValueError("Request DSN evidence missing")


def files_for(record, packet):
    trace = record["trace_id"]
    d = COHORT / "runs" / packet["repetition_id"]
    return {"reviewer_dossier": COHORT / "reviewer_packets" / f"{trace}.json",
            **{name: d / name for name in ("activation.json", "activation_readback.json", "telemetry.json",
                                           "http_response.json", "snapshot_manifest.json")},
            "receipt": d / "receipts" / f"{trace}.json"}


def scope_record():
    return {"evaluation_type": TYPE, "evaluation_scope": SCOPE, "reference_label_source": SOURCE,
            "independent_review": "NOT_PERFORMED", "statistical_scope": "DESCRIPTIVE_PAIRED_COMPARISON"}


def freeze():
    sha, cohort_hashes, records, inference, _, packets, overlaps, history = audit()
    formal = read(FORMAL / "benchmark_lock_readiness.json")
    if formal["benchmark_locked"] or any(formal["counts"].values()):
        raise ValueError("Unexpected formal benchmark status")
    refs, audits = [], []
    run_references = []
    for row, (case, packet) in zip(records, packets, strict=True):
        if row["case_id"] != case:
            raise ValueError("Case mapping mismatch")
        config = packet["configuration_id"]
        files = files_for(row, packet)
        contradictions = []
        try:
            label_checks(config, read(files["activation.json"]), read(files["telemetry.json"]),
                         read(files["http_response.json"]))
        except (KeyError, TypeError, ValueError) as exc:
            contradictions.append(str(exc))
        state = "UNRESOLVED" if contradictions else "DERIVED_UNVERIFIED"
        reference = {"case_id": case, "status": state, "reference_label_source": SOURCE,
                     "candidate_root_mechanism": packet["candidate_mechanism"],
                     "candidate_root_service": packet["candidate_service"],
                     "candidate_handling": packet["candidate_handling"],
                     "observed_failure_service": None if config == "normal-a" else "order",
                     "candidate_group": row["group"], "run_id": row["run_id"], "trace_id": row["trace_id"],
                     "configuration_id": config, "repetition_id": packet["repetition_id"],
                     "evidence": {key: file_ref(path) for key, path in files.items()},
                     "event_ids": packet["supporting_evidence"]["event_ids"],
                     "known_limitations": ["Bounded observed capture; no independent reviewer"],
                     "contradictions": contradictions}
        if config == "processing-a":
            reference["known_limitations"].append("Before INSERT established by hook placement, no transaction audit")
        if config == "timeout-a":
            reference["known_limitations"].append("Delay originates at Product; timeout is observed by Order")
        if config == "database-a":
            reference["known_limitations"].append("Request DSN connection failure, not database crash")
        refs.append(reference)
        run_references.append({"case_id":case, "snapshots":row["snapshots"], "cutoff":row["cutoff"],
                               "completeness":row["completeness"], "pairing":"SAME_TRACE_ORDER_PROJECTION",
                               "reference_case_id":case})
        audits.append({"case_id": case, "provenance_integrity": "PASS", "technical_consistency": state,
                       "contradictions": contradictions})
    case_ids = [r["case_id"] for r in inference]
    Random(782).shuffle(case_ids)
    calls = [{"case_id": c, "mode": mode} for i,c in enumerate(case_ids)
             for mode in (MODES if i % 2 == 0 else MODES[::-1])]
    call_plan = {
        "calls": [{"sequence": i, **c} for i,c in enumerate(calls,1)], "max_calls":20, "retries":0,
        "conversation_history":False, "store_at_provider":False,
        "prompt_version":PROMPT_VERSION,"prompt_sha256":checksum(PROMPT),"model_snapshot":None,
        "input_evidence_ascii_bytes":7000,"max_output_tokens":800,"decoding":"SDK defaults; no tools",
        "output_schema":ModelAnalysis.model_json_schema(),
        "source_code":[file_ref(ROOT/p) for p in ("app/llm_analysis.py","app/llm_provider.py")],
        "result_storage":{"root":"separate run directory outside the freeze",
            "required_fields":["case_id","mode","sequence","outcome","model_snapshot","response_id",
               "parsed_output","validation_warnings","input_event_ids","latency_ms","input_tokens",
               "output_tokens","cost_usd","price_source","attempt_count"],
            "policy":"Append one attempt record per scheduled call, preserve missing/failed, keep scoring separate"},
        "authorized":False}
    scoring = {
        "status":"FROZEN_PRE_OUTPUT","primary":"Mean paired Cross minus Single exact root cause accuracy",
        "scorable_pair":"Both fault outputs valid ANALYZED and reference resolved",
        "outcomes":{"CORRECT":1,"PARTIALLY_CORRECT":0,"INCORRECT":0,"ABSTAINED":None,
                    "INVALID_OUTPUT":None,"PROVIDER_FAILURE":None,"MISSING_RESULT":None},
        "all_planned_fault_denominator":8,
        "all_planned_rule":"Each mode: exact correct / 8; each other outcome counts zero, including unresolved reference",
        "pair_buckets":["both_correct","cross_only_correct","single_only_correct","both_incorrect","non_scorable"],
        "grouping":"Report four candidate groups with two executions each; no independent execution or significance claim",
        "secondary":{"mechanism_accuracy":"correct component / scorable analyzed fault outputs with resolved component",
                     "root_service_accuracy":"correct service / scorable analyzed fault outputs with reference service",
                     "exact_accuracy":"exact correct / scorable fault outputs in eligible pairs",
                     "partial_correctness":"partial / scorable analyzed fault outputs",
                     "propagation_handling_accuracy":"correct handling / scorable analyzed fault outputs with resolved handling",
                     "evidence_support_rate":"supported / all scorable claims",
                     "unsupported_claim_rate":"unsupported or hallucinated / all scorable claims, including uncited claims if scorable",
                     "abstention_rate":"abstained / schema-valid returned outputs",
                     "normal_false_attribution_rate":"false fault attribution / scorable analyzed Normal outputs",
                     "latency":"per attempted call with observed latency; report coverage",
                     "token_usage":"per attempt with provider usage; report coverage",
                     "cost":"priced attempt usage with documented tariff; missing is null"},
        "exact_rule":"Correct mechanism and root service plus supporting trace evidence; no symptom-only credit",
        "partial_rule":"Correct bounded aspect but missing or under-specified mechanism/service/evidence; never exact",
        "report":"Report counts and denominators by mode and group, failures and missing for all scheduled calls; null if denominator zero"}
    files = {
        "exploratory_protocol.json":{**scope_record(),"status":"FROZEN_PRE_OUTPUT","cases":10,"fault_cases":8,
                                    "normal_cases":2,"formal_benchmark_locked":False,"blind_eligible":0},
        "reference_labels.json":{"source":SOURCE,"independently_verified":0,"records":refs},
        "reference_label_audit.json":{"records":audits,"provenance_valid":10,
             "unresolved":sum(bool(x["contradictions"]) for x in audits),"cohort_hashes":cohort_hashes,"history":history},
        "evaluation_manifest.json":{"status":"EXPLORATORY_DATASET_FROZEN","collection_plan_sha256":sha,"records":run_references},
        "inference_manifest.json":{"records":inference},"scoring_protocol.json":scoring,
        "evaluation_plan.json":call_plan,"limitations.json":{"items":LIMITS,"overlap_matches":len(overlaps)}}
    OUT.mkdir()
    for name,value in files.items():
        write(OUT/name,value)
    with (OUT/"freeze_manifest.sha256").open("x",encoding="ascii",newline="\n") as stream:
        for name in sorted(FROZEN):
            stream.write(f"{digest(OUT/name)}  {name}\n")
    write(OUT/"exploratory_readiness.json",gate())


def gate(authorization=None):
    entries = [line.split("  ",1) for line in (OUT/"freeze_manifest.sha256").read_text(encoding="ascii").splitlines()]
    if len(entries) != len(FROZEN) or {name for _,name in entries} != FROZEN:
        raise ValueError("Freeze coverage mismatch")
    for sha,name in entries:
        if digest(OUT/name) != sha:
            raise ValueError("Frozen file digest mismatch")
    plan, sha = locked_plan()
    rules=read(OUT/"exploratory_protocol.json")
    ev=read(OUT/"evaluation_manifest.json")
    inf=read(OUT/"inference_manifest.json")
    if set(inf) != {"records"}:
        raise ValueError("Unexpected inference fields")
    isolate(inf)
    labels=read(OUT/"reference_labels.json")
    calls=read(OUT/"evaluation_plan.json")
    scoring=read(OUT/"scoring_protocol.json")
    history=validate()
    history["acceptance_hashes"]=sum(verify_hashes(d,"bundle_sha256.json") for d in PLAN.glob("accept_7a6d2_*"))
    history["cohort_hashes"]=0
    observed_pairs=set()
    for slot,row,input_case,label in zip(plan["slots"],ev["records"],inf["records"],labels["records"],strict=True):
        if input_case != {"case_id":row["case_id"],"snapshots":row["snapshots"]}:
            raise ValueError("Inference metadata leakage or case mismatch")
        if label["case_id"] != row["case_id"] or label["configuration_id"] != slot["configuration_id"]:
            raise ValueError("Reference binding mismatch")
        d=ROOT/slot["output_directory"]
        history["cohort_hashes"]+=verify_hashes(d,"bundle_sha256.json")
        t=label["trace_id"]
        manifest=read(d/"snapshot_manifest.json")
        source_pair=pairing(d,t,manifest)
        if set(input_case["snapshots"]) != set(MODES):
            raise ValueError("Unexpected snapshot modes")
        for mode in MODES:
            p=checked(input_case["snapshots"][mode],COHORT/"inference_snapshots"/t)
            if digest(p)!=manifest[mode]["sha256"]:
                raise ValueError("Snapshot reuse or digest mismatch")
            isolate(read(p))
            observed_pairs.add((row["case_id"],mode))
        for key,expected in files_for({"trace_id":t},{"repetition_id":slot["repetition_id"]}).items():
            if checked(label["evidence"][key],COHORT) != expected.resolve():
                raise ValueError("Reference provenance mismatch")
        if label["event_ids"] != source_pair[1].evidence_event_ids or label["reference_label_source"] != SOURCE:
            raise ValueError("Reference event provenance mismatch")
    structure=({k:rules[k] for k in scope_record()}==scope_record()
               and ev["collection_plan_sha256"]==sha and len(observed_pairs)==20
               and len(calls["calls"])==20 and calls["retries"]==0
               and {(c["case_id"],c["mode"]) for c in calls["calls"]}==observed_pairs
               and [c["sequence"] for c in calls["calls"]]==list(range(1,21))
               and scoring["all_planned_fault_denominator"]==8)
    for descriptor in calls["source_code"]:
        checked(descriptor,ROOT/"app")
    if (not structure or calls["output_schema"]!=ModelAnalysis.model_json_schema()
            or calls["prompt_sha256"]!=checksum(PROMPT)
            or (history["cohort_hashes"],history["acceptance_hashes"],history["research_hashes"])!=(190,95,63)):
        raise ValueError("Frozen protocol or integrity gate failed")
    auth=read(authorization) if authorization else {}
    approved=(auth.get("decision_source")=="USER_OPERATOR_DECLARATION" and auth.get("status")=="APPROVED"
              and auth.get("operator_id")=="local-project-operator" and auth.get("max_calls")==20
              and auth.get("retries")==0 and auth.get("evaluation_type")==TYPE
              and auth.get("freeze_index_sha256")==digest(OUT/"freeze_manifest.sha256"))
    model=auth.get("model_snapshot")
    cost=auth.get("cost_ceiling_usd")
    gates={"frozen_manifest":True,"snapshot_integrity":True,"reference_label_provenance":True,
           "inference_isolation":True,"scoring_protocol_and_call_order":True,"scope_declaration":True,
           "operator_authorization":approved,"model_configuration":approved and isinstance(model,str) and bool(model.strip()),
           "credential_available_in_shell":bool(os.getenv("OPENAI_API_KEY","").strip()),
           "cost_approval":approved and type(cost) in (int,float) and 0<cost<float("inf")
                           and bool(auth.get("price_source"))}
    formal = read(FORMAL/"benchmark_lock_readiness.json")
    return {"dataset_status":"EXPLORATORY_DATASET_FROZEN","formal_benchmark_status":formal["status"],
            "formal_split_status":formal["formal_split_status"],"formal_benchmark_locked":formal["benchmark_locked"],
            "formal_counts":formal["counts"],"gates":gates,"all_checks_met":all(gates.values()),
            "execution_authorized_by_tool":False,"api_calls":0,"freeze_index_sha256":digest(OUT/"freeze_manifest.sha256"),
            "integrity":history}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--freeze",action="store_true")
    cli.add_argument("--authorization",type=Path)
    cli.add_argument("--require-ready",action="store_true")
    args=cli.parse_args()
    if args.freeze:
        freeze()
    result=gate(args.authorization)
    print(json.dumps(result,indent=2))
    if args.require_ready and not result["all_checks_met"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
