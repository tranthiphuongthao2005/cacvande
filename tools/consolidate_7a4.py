"""Read-only consolidation of 7A4 experiment bundles."""

import argparse
import csv
import json
from pathlib import Path

from app.benchmark import isolate, validate_context
from app.micro_dataset import checksum
from app.telemetry_receipts import decode
from tools.audit_research import audit
from tools.collect_benchmark_7a1 import digest
from tools.verify_ground_truth_7a2 import read

ROOT = Path(__file__).resolve().parents[1]
MECHANISMS = {"cascade": "Product unavailable -> Order dependency failure",
              "timeout": "Product delay exceeds Order deadline",
              "database": "Order request repository connection fails"}


def verify_hashes(directory, name):
    manifest = read(directory / name)
    for relative, expected in manifest.items():
        file = (directory / relative).resolve(strict=True)
        if not file.is_relative_to(directory.resolve()) or digest(file) != expected:
            raise ValueError(f"Checksum mismatch: {relative}")
    return len(manifest)


def pairing(directory, trace, descriptor):
    result = {}
    for mode, service in (("single_service", "order"), ("cross_service", None)):
        item = descriptor[mode]
        path = (directory / item["path"]).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or digest(path) != item["sha256"]:
            raise ValueError("Snapshot checksum mismatch")
        result[mode] = validate_context(read(path), trace, mode, service)
        if (result[mode].evidence_event_ids != item["event_ids"] or
                result[mode].completeness_status != item["completeness"] or not item.get("provenance")):
            raise ValueError("Snapshot provenance mismatch")
    single, cross = result["single_service"], result["cross_service"]
    if single.events != [event for event in cross.events if event.service_name == "order"]:
        raise ValueError("Single does not match Order projection of Cross")
    return single, cross


def consolidate(root=ROOT / "experiments"):
    inventory, queue, summaries, trace_ids, event_ids = [], [], [], set(), set()
    history = read(root / "benchmark_7a_audit.json")["rows"]
    for row in history:
        trace_ids.add(row["trace_id"])
        source = root / "telemetry" / f"{row['trace_id']}.jsonl"
        if source.is_file():
            for line in source.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("trace_id") == row["trace_id"] and event.get("event_id"):
                    event_ids.add(event["event_id"])
        inventory.append({"cohort": row["source_class"], "run_id": row["run_id"], "trace_id": row["trace_id"],
                          "fault_family": row["scenario"], "observed_event_count": row["event_count"],
                          "cross_completeness": row["completeness"],
                          "ground_truth_status": row["ground_truth_availability"],
                          "independence_group": row["independence_group"], "eligibility": "EXCLUDED",
                          "exclusion_reason": "Previously observed historical or development data"})
    for path in (root / "micro_pilot_seed123/observations").glob("*.json"):
        value = read(path)
        event_ids.update(event["event_id"] for event in value["events"])
    historical_hashes = {}
    for name in ("benchmark_7a1_pilot_seed124", "benchmark_7a2_verification", "benchmark_7a3_smoke",
                 "benchmark_7a3b_smoke"):
        historical_hashes[name] = verify_hashes(root / name, "checksum_manifest.json")
    pilot = root / "benchmark_7a1_pilot_seed124"
    for run in read(pilot / "run_manifest.json")["runs"]:
        inventory.append({"cohort": "development_pilot_7a1", "run_id": run["run_id"], "trace_id": run["trace_id"],
                          "campaign": run["campaign_id"], "fault_family": run["scenario_family"],
                          "http_response": run["http_status"], "observed_event_count": run["event_count"],
                          "cross_completeness": run["completeness"], "ground_truth_status": "NEEDS_REVIEW",
                          "independence_group": run["independence_group"], "eligibility": "EXCLUDED",
                          "exclusion_reason": "Previously observed development pilot"})
        event_ids.update(run["snapshots"]["cross_service"]["event_ids"])
        trace_ids.add(run["trace_id"])
    for name, receipt in (("benchmark_7a3_smoke", "smoke.json"), ("benchmark_7a3b_smoke", "reconciliation.json")):
        record = read(root / name / receipt)
        snapshot = read(root / name / "snapshot.json")
        isolate(snapshot)
        trace_ids.add(record["trace_id"])
        event_ids.update(snapshot["evidence_event_ids"])
        inventory.append({"cohort": "engineering_smoke", "run_id": record["run_id"], "trace_id": record["trace_id"],
                          "campaign": name, "observed_event_count": snapshot["event_count"],
                          "cross_completeness": snapshot["completeness_status"], "eligibility": "EXCLUDED",
                          "exclusion_reason": "Engineering smoke"})

    def pending(directory, dossier_path, form_path, priority):
        dossier, form = read(directory / dossier_path), read(directory / form_path)
        if (form["dossier_sha256"] != checksum(dossier) or form["run_id"] != dossier["run_id"]
                or form["status"] != "NEEDS_REVIEW" or
                any(form[k] is not None for k in ("reason", "reviewer_id", "reviewed_at"))):
            raise ValueError("Unexpected or unbound reviewer form")
        return {"run_id": dossier["run_id"], "fault_family": dossier["scenario_family"],
                "evidence_dossier_path": f"experiments/{directory.name}/{dossier_path}",
                "reviewer_form_path": f"experiments/{directory.name}/{form_path}",
                "review_priority": priority,
                "missing_evidence": "; ".join(dossier.get("missing_evidence") or ["Independent review and delivery ACK"])}

    review_dir = root / "benchmark_7a2_verification"
    for path in sorted((review_dir / "dossiers").glob("*.json")):
        queue.append(pending(review_dir, f"dossiers/{path.name}", f"review_forms/{path.name}", "P2-development"))
    for i in range(1, 4):
        directory = root / f"benchmark_7a4_batch{i:02}"
        files = verify_hashes(directory, "bundle_sha256.json")
        campaign = read(directory / "campaign_manifest.json")
        row, = read(directory / "run_manifest.json")["runs"]
        candidate, = read(directory / "evaluation_candidates.json")
        trace, rid = row["trace_id"], row["run_id"]
        rec = read(directory / "reconciliation.json")
        act = read(directory / "activation.json")
        descriptor = read(directory / "snapshot_manifest.json")
        if "snapshots" in descriptor and (descriptor["run_id"], descriptor["trace_id"]) != (rid, trace):
            raise ValueError("Pair identity mismatch")
        single, cross = pairing(directory, trace, descriptor.get("snapshots", descriptor))
        seal, receipt = decode(read(directory / "receipts" / f"{trace}.json"))
        signature = checksum([(e.service_name, e.message, e.status_code) for e in cross.events])
        if (trace in trace_ids or set(cross.evidence_event_ids) & event_ids
                or (seal.run_id, seal.trace_id) != (rid, trace)
                or not act["behavior_confirmed"] or act["http_status"] != row["http_status"]
                or candidate["run_id"] != rid or campaign["variant"] != row["scenario"]
                or campaign["locked_evaluation"] or candidate["eligibility_decision"] != "EXCLUDED"
                or row["status"] != "TECHNICALLY_VALID" or not receipt.event_content_matches
                or not any(old["observable_status_signature_sha256"] == signature for old in history)
                or not set(cross.evidence_event_ids) == set(receipt.observed_event_ids)
                or {rec[k] for k in ("producer_events", "docker_events", "es_events")} != {cross.event_count}):
            raise ValueError("Batch evidence or eligibility mismatch")
        trace_ids.add(trace)
        event_ids.update(cross.evidence_event_ids)
        queue.append(pending(directory, "labels/dossier.json", "labels/reviewer_form.json", "P1-batch"))
        summary = {"cohort": "candidate_audit", "run_id": rid, "trace_id": trace,
                   "campaign": directory.name, "fault_family": candidate["fault_family"],
                   "fault_mechanism": MECHANISMS[row["scenario"]], "affected_service": "order",
                   "http_response": row["http_status"], "activation_evidence": f"experiments/{directory.name}/activation.json",
                   **{k: rec[k] for k in ("producer_events", "docker_events", "es_events")},
                   "cross_completeness": cross.completeness_status, "single_completeness": single.completeness_status,
                   "ground_truth_status": "NEEDS_REVIEW", "single_cross_pair": "PAIRED",
                   "independence_group": candidate["independence_group"], "eligibility": "EXCLUDED",
                   "exclusion_reason": "; ".join(candidate["exclusion_reasons"]),
                   "batch_verified_hashes": files}
        summaries.append(summary)
        inventory.append(summary)
    queue.sort(key=lambda x: (x["review_priority"], x["run_id"]))
    return inventory, queue, summaries, historical_hashes


def write_csv(path, rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    inventory, queue, summaries, hashes = consolidate()
    protected = audit()["verified_unique_files"]
    if not args.check_only:
        names = ("benchmark_7a4_consolidated_inventory.csv", "benchmark_7a4_reviewer_queue.csv")
        paths = [args.output_dir / name for name in names]
        if any(path.exists() for path in paths):
            raise FileExistsError("Consolidation outputs already exist")
        for path, rows in zip(paths, (inventory, queue)):
            write_csv(path, rows)
    print({"inventory_rows": len(inventory), "review_queue": len(queue),
           "technically_valid": len(summaries), "batch_hashes": [r["batch_verified_hashes"] for r in summaries],
           "historical_hashes": hashes, "research_hashes": protected})


if __name__ == "__main__":
    main()
