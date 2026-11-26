"""Verify the research handoff bytewise without parsing labels or running a model."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "tuanmartin-MeCoLog-8c446ac"
RUN = ROOT / "real_smoke_cpu"
LOCK = "308e29ba2c48ff92c4ea3230206c99194daeb1e85a5832088c5b635c8285c63b"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audit():
    protocol = read(RUN / "pre_final_audit_seed123/frozen_protocol.json")
    fingerprint = protocol.pop("lock_sha256")
    if fingerprint != LOCK or canonical_hash(protocol) != LOCK:
        raise ValueError("Frozen protocol changed")
    thesis = read(RUN / "thesis_results/ARTIFACT_MANIFEST.json")
    recovery = read(RUN / "final_recovery_seed123/recovery_preflight.json")
    expected = {RUN / name: digest for name, digest in thesis["sources_sha256"].items()}
    expected.update({RUN / "thesis_results" / name: digest for name, digest in thesis["outputs_sha256"].items()})
    expected.update({ROOT / name: digest for name, digest in recovery["original_and_protected_files_sha256"].items()})
    expected.update({RUN / row["feature_path"]: row["feature_sha256"] for row in protocol["final_metadata"].values()
                     if isinstance(row, dict)})
    expected.update({
        RUN / protocol["checkpoint"]: protocol["checkpoint_sha256"],
        RUN / "hdfs_locked_features_seed123/feature_manifest.json": protocol["feature_manifest_sha256"],
        RUN / "pre_final_audit.py": protocol["frozen_scorer_sha256"],
    })
    original = {path.name for path in expected if path.parent == ROOT and path.suffix == ".py"}
    if len(original) != 9:
        raise ValueError("Wrong original source file count")
    for path, digest in expected.items():
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError(f"Research dependency changed: {path.relative_to(ROOT)}")
    return {"research_path": str(ROOT), "protocol_sha256": LOCK, "verified_unique_files": len(expected),
            "original_python_files": sorted(original), "checkpoint_sha256": protocol["checkpoint_sha256"],
            "vocabulary_sha256": protocol["vocabulary_sha256"], "sbert_revision": protocol["sbert_revision"],
            "method": "opaque hashing of protected data; no label parsing or model load"}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
