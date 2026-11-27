import pytest

from tools.consolidate_7a4 import ROOT, consolidate, pairing, verify_hashes
from tools.verify_ground_truth_7a2 import read


def test_consolidated_batches_remain_excluded_and_review_unfilled():
    inventory, queue, batches, hashes = consolidate()
    assert len(inventory) == len({r["trace_id"] for r in inventory}) == 43
    assert len(queue) == len({r["run_id"] for r in queue}) == 7
    assert [row["batch_verified_hashes"] for row in batches] == [17, 20, 21]
    assert sum(row["es_events"] for row in batches) == 14
    assert all(row["eligibility"] == "EXCLUDED" for row in inventory)
    assert all(row["ground_truth_status"] == "NEEDS_REVIEW" for row in batches)
    assert all(row["single_cross_pair"] == "PAIRED" for row in batches)
    assert sum(hashes.values()) == 50


def test_snapshot_checksum_and_scope_changes_rejected():
    directory = ROOT / "experiments/benchmark_7a4_batch03"
    manifest = read(directory / "snapshot_manifest.json")
    inputs = manifest["snapshots"]
    inputs["single_service"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        pairing(directory, manifest["trace_id"], inputs)
    assert verify_hashes(directory, "bundle_sha256.json") == 21
