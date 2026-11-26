"""Plan-bound collection using the shared gated adapter and isolated exports."""
import argparse
import json
from pathlib import Path

from tools.collect_benchmark_7a1 import digest, write
from tools.collect_benchmark_7a6c import execute
from tools.collection_gate_7a6b import CollectionBlocked, PostGate
from tools.consolidate_7a4 import consolidate, pairing, verify_hashes
from tools.fault_adapters_7a6c import ADAPTERS
from tools.validate_7a5d import PLAN, ROOT, read

COHORT = ROOT / "experiments/benchmark_7a7"


def locked_plan():
    file = COHORT / "collection_plan.json"
    expected = (COHORT / "collection_plan.sha256").read_text(encoding="ascii").strip()
    if digest(file) != expected:
        raise CollectionBlocked("Collection plan digest mismatch")
    plan = read(file)
    for name, sha in plan["fingerprints"].items():
        if digest(ROOT/name) != sha:
            raise CollectionBlocked("Configuration fingerprint drift")
    slots = plan["slots"]
    if len(slots) != 10 or len({slot["campaign_id"] for slot in slots}) != 10:
        raise CollectionBlocked("Unexpected plan capacity or duplicate campaign")
    return plan, expected


class CohortGate(PostGate):
    def __init__(self, slot_id):
        plan, self.plan_sha = locked_plan()
        self.slot = next(s for s in plan["slots"] if s["repetition_id"] == slot_id)
        self.cohort_id = plan["cohort_id"]
        self.adapter = ADAPTERS[self.slot["configuration_id"]]
        output = ROOT / self.slot["output_directory"]
        super().__init__(COHORT / "approvals" / (slot_id + ".json"), self.slot["campaign_id"], output)

    def scope(self):
        return self.adapter.configuration, 792

    def output_parent(self):
        return COHORT / "runs"

    def check_binding(self, entry):
        _, current = locked_plan()
        if (current != self.plan_sha or entry["collection_plan_sha256"] != current
                or entry["cohort"] != self.cohort_id or entry["repetition_id"] != self.slot["repetition_id"]
                or entry["blind_eligible"] is not False or entry["overall_seconds"] != 792):
            raise CollectionBlocked("Approval does not bind the locked cohort slot")


def expose():
    rows, *_ = consolidate()
    ids = {(r["run_id"], r["trace_id"]) for r in rows}
    for d in PLAN.glob("*"):
        if (d / "reconciliation.json").is_file():
            r = read(d / "reconciliation.json")
            ids.add((r["run_id"], r["trace_id"]))
    return {i for i, _ in ids}, {t for _, t in ids}


def export(gate):
    d = gate.output
    expected = {p.relative_to(d).as_posix() for p in d.rglob("*.json") if p.name != "bundle_sha256.json"}
    if set(read(d / "bundle_sha256.json")) != expected:
        raise ValueError("Incomplete bundle manifest")
    verify_hashes(d, "bundle_sha256.json")
    r = read(d / "reconciliation.json")
    trace, run = r["trace_id"], r["run_id"]
    runs, traces = expose()
    prior_events = set()
    for path in (COHORT / "reviewer_packets").glob("*.json"):
        row = read(path)
        runs.add(row["run_id"])
        traces.add(row["trace_id"])
        prior_events.update(row["supporting_evidence"]["event_ids"])
    manifest = read(d / "snapshot_manifest.json")
    single, cross = pairing(d, trace, manifest)
    if run in runs or trace in traces or prior_events.intersection(cross.evidence_event_ids):
        raise ValueError("Run, trace or event identity reused")
    source = read(d / "labels/dossier.json")
    assert source["verification_status"] == "UNVERIFIED"
    for mode in ("single_service", "cross_service"):
        name = manifest[mode]["path"]
        output = COHORT / "inference_snapshots" / trace / f"{mode}.json"
        output.parent.mkdir(exist_ok=True)
        with output.open("xb") as stream:
            stream.write((d / name).read_bytes())
    refs = {name: {"path": (d / name).relative_to(ROOT).as_posix(), "sha256": digest(d / name)}
            for name in (*source["references"], "labels/dossier.json", "bundle_sha256.json")}
    packet = {**source, "configuration_id": gate.adapter.configuration, "repetition_id": gate.slot["repetition_id"],
              "supporting_evidence": {"event_ids": cross.evidence_event_ids, "artifacts": refs},
              "evidence_sufficient_for_candidate_review": True,
              "normal_negative_case": gate.adapter.scenario is None,
              "snapshot_provenance": manifest, "technical_status": "TECHNICALLY_VALID"}
    write(COHORT / "reviewer_packets" / (trace + ".json"), packet)
    print(json.dumps({"trace_id": trace, "post_count": 1, "source_events": r["es_events"],
                      "single": single.event_count, "cross": cross.event_count, "status": "NEEDS_REVIEW"}))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--slot", required=True)
    cli.add_argument("--live", action="store_true")
    args = cli.parse_args()
    gate = CohortGate(args.slot)
    if not args.live:
        print("Plan and runtime scope valid; zero POST")
        return
    stability = read(COHORT / "stability.json")
    if (stability["plan_sha256"] != gate.plan_sha or len(stability["probes"]) != 40
            or any(row["status"] != 200 or row["seconds"] >= 4 for row in stability["probes"])):
        raise CollectionBlocked("Stability gate did not verify 40 HTTP 200 responses")
    plan, _ = locked_plan()
    for previous in plan["slots"]:
        if previous["repetition_id"] == args.slot:
            break
        path = ROOT / previous["output_directory"]
        if not (path / "acceptance_result.json").is_file() or read(path / "acceptance_result.json")["status"] != "PASS":
            raise CollectionBlocked("A previous slot has not passed")
        trace = read(path / "reconciliation.json")["trace_id"]
        if not (COHORT / "reviewer_packets" / (trace + ".json")).is_file():
            raise CollectionBlocked("A previous slot has not passed export verification")
    metadata = {**gate.slot, "cohort": gate.cohort_id, "collection_plan_sha256": gate.plan_sha,
                "split": "EVALUATION_CANDIDATE", "blind_eligible": False}
    if not execute(gate.adapter, gate.output, gate, metadata=metadata):
        raise SystemExit(1)
    export(gate)


if __name__ == "__main__":
    main()
