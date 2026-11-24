"""Offline audit of the 7A.5D drafts and reviewer evidence links."""
import argparse
import json
from tools.audit_research import audit
from tools.collect_benchmark_7a1 import digest
from tools.consolidate_7a4 import consolidate, verify_hashes
from tools.validate_7a5 import PLAN, ROOT, read, require

CASCADE = "1d3140d225414983ac361d14ed978220"
PILOTS = {"4f37659b37694381bc2e61666632e079", "70c9a115abfe487eacd82453dfd47aaa"}


def descriptor(path):
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}


def packets(queue):
    items = []
    for row in queue:
        run = row["run_id"]
        dossier = ROOT / row["evidence_dossier_path"]
        form = ROOT / row["reviewer_form_path"]
        packet = {"run_id": run, "dossier": descriptor(dossier), "form": descriptor(form),
                  "status": "NEEDS_REVIEW", "review_scope": "GROUND_TRUTH_REVIEW_ONLY",
                  "evidence_status": "SUFFICIENT_FOR_REVIEW", "supporting_artifacts": [],
                  "limitations": row["missing_evidence"]}
        batch = dossier.parent.parent
        if batch.name.startswith("benchmark_7a4_batch"):
            packet["supporting_artifacts"] = [descriptor(batch / name) for name in ("activation.json", "telemetry.json")]
        else:
            pilot = ROOT / "experiments/benchmark_7a1_pilot_seed124"
            packet["supporting_artifacts"] = [descriptor(pilot / folder / f"{run}.json") for folder in ("runs", "telemetry", "collector_receipts/labels")]
        if run in PILOTS:
            packet["evidence_status"] = "MISSING_EVIDENCE"
            packet["missing"] = "Independent per-run runtime activation record; saved config, HTTP and labels are not independent readback"
        if run == CASCADE:
            activation = read(batch / "activation.json")
            events = read(batch / "telemetry.json")["docker_events"]
            product, = [e for e in events if (e["service"], e["status"]) == ("product", 503)]
            failures = [e for e in events if e["event"] == "dependency_attempt_failed" and e["dependency"] == "product"]
            order, = [e for e in events if (e["service"], e["event"], e["status"]) == ("order", "request_completed", 502)]
            require(activation["runtime"]["product"][1] == "unavailable" and len(failures) == 1
                    and product["trace_id"] == failures[0]["trace_id"] == order["trace_id"] == read(dossier)["trace_id"],
                    "Cascade supplement evidence mismatch")
            packet["candidate_supplement"] = {"authorship": "SYSTEM_PREPARED_NOT_REVIEWED",
                "mechanism": "dependency_unavailable", "service": "product", "handling": ["propagated"],
                "basis": "Runtime Product unavailable and correlated 503, dependency failure, and Order 502; single attempt",
                "event_ids": [product["event_id"], failures[0]["event_id"], order["event_id"]]}
        items.append(packet)
    return {"version": "7A.5D-v1", "status": "DRAFT_REVIEW_QUEUE", "items": items}


def validate(*, write_manifest=False):
    taxonomy = read(PLAN / "taxonomy_v2_draft.json")
    cohort = read(PLAN / "cohort_v2_draft.json")
    protocol = read(PLAN / "evaluation_protocol_v2_draft.json")
    decisions = read(PLAN / "operator_decisions_pending.json")
    mechanisms, handling = set(taxonomy["mechanisms"]), set(taxonomy["handling"])
    require(len(mechanisms) == 6 and len(handling) == 4 and taxonomy["handling_multilabel"]
            and not taxonomy["historical_relabeling"], "Invalid taxonomy dimensions")
    require(len(taxonomy["legacy_mapping"]) == 7 and all(
        row["mechanism"] in mechanisms and set(row["handling"]) <= handling
        for row in taxonomy["legacy_mapping"].values()), "Invalid legacy mapping")
    slots = cohort["slots"]
    ready = {r["id"] for r in slots if r["status"] in {"PATH_VERIFIED", "FIXTURE_PATH"}}
    require(len(slots) == 14 and {r["id"] for r in slots} == {r["id"] for r in read(PLAN / "configuration_matrix.json")["slots"]}
            and len(ready) == cohort["engineering_paths_available"] == 9
            and cohort["slots_excluded_or_blocked"] == len(slots) - len(ready)
            and {b["configuration"] for b in cohort["batches"]} == ready
            and sum(b["request_cap"] for b in cohort["batches"]) == cohort["budget_pairs_ceiling"]
            and all(b["authorization"] == "PENDING" and b["extra_post_retries"] == 0 for b in cohort["batches"]),
            "Invalid cohort grouping or budget")
    overlapping = {r["group_hint"] for r in slots if r["id"] in {"unavailable-a", "unavailable-b", "retry-a", "cascade-a"}}
    require(len(overlapping) == 1 and cohort["independent_verified"] == 0, "Related Product slots split")
    require(protocol["status"] == "DRAFT" and protocol["lock_sha256"] is None
            and not protocol["provider_calls_authorized"] and not cohort["collection_authorized"]
            and not decisions["collection_authorized"] and not decisions["provider_authorized"]
            and digest(PLAN / "evaluation_protocol.json") == read(PLAN / "collector_validation.json")["draft_protocol_file_sha256"],
            "Protocol version or authorization mismatch")
    _, queue, summaries, history = consolidate()
    expected = packets(queue)
    target = PLAN / "reviewer_packet_manifest.json"
    if write_manifest:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(expected, stream, indent=2)
            stream.write("\n")
    require(read(target) == expected, "Packet provenance mismatch")
    smoke_hashes = verify_hashes(PLAN / "normal_a_integration_smoke", "bundle_sha256.json")
    return {"sufficient_for_review": len(queue) - len(PILOTS), "missing_evidence": len(PILOTS),
            "batch_hashes": [r["batch_verified_hashes"] for r in summaries],
            "historical": history, "smoke_hashes": smoke_hashes, "research_hashes": audit()["verified_unique_files"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", action="store_true")
    print(json.dumps(validate(write_manifest=parser.parse_args().write_manifest)))
