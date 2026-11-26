"""Verify the operator-approved Stage 9.1 scope without importing LLM code."""

import hashlib
import json
import subprocess
from pathlib import Path

from tools.audit_research import audit

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "b68eba6e98cd36fe07019ab023b10bf169e3a598"
EXPERIMENTS = ROOT / "experiments"
FROZEN = EXPERIMENTS / "benchmark_7a8r_exploratory"
COHORT = EXPERIMENTS / "benchmark_7a7"
PLAN = EXPERIMENTS / "benchmark_7a5"
LLM_BLOBS = {
    "app/llm_analysis.py": "d79e0af2d4749f22887acc8ca363ddfd299b60f73f31a6bc23a3d51c6e9412c0",
    "app/llm_provider.py": "5603e1df11e0cd4aa46ee39f2a63a1c72623722833089d3f61945a9014ae7d2e",
}
HISTORICAL = {
    **{(EXPERIMENTS / f"benchmark_7a4_batch{i:02}", "bundle_sha256.json"): count
       for i, count in enumerate((17, 20, 21), 1)},
    (EXPERIMENTS / "benchmark_7a1_pilot_seed124", "checksum_manifest.json"): 33,
    (EXPERIMENTS / "benchmark_7a2_verification", "checksum_manifest.json"): 9,
    (EXPERIMENTS / "benchmark_7a3_smoke", "checksum_manifest.json"): 4,
    (EXPERIMENTS / "benchmark_7a3b_smoke", "checksum_manifest.json"): 4,
    (PLAN / "normal_a_integration_smoke", "bundle_sha256.json"): 15,
    (PLAN / "processing_a_development_pilot", "bundle_sha256.json"): 18,
    (PLAN / "normal_a_integration_smoke", "checksum_manifest.json"): 10,
    (PLAN / "processing_a_development_pilot", "checksum_manifest.json"): 12,
}
STAGE_FILES = {
    "app/detection_api.py", "app/rule_detection.py", "services/detection/Dockerfile",
    "tests/test_rule_detection.py", "tools/check_stage_9_1_integrity.py",
    "docs/STAGE_9_1_SCOPED_INTEGRITY.md", "docs/STAGE_9_1_RULE_BASED_DETECTION.md",
    "app/hybrid_detection.py", "tests/test_hybrid_detection.py", "tests/test_hybrid_api.py",
    "docs/STAGE_9_2_HYBRID_DETECTION_ROUTER.md",
    "app/monitoring_client.py", "app/monitoring_config.py", "app/monitoring_models.py",
    "app/monitoring_store.py", "app/monitoring_worker.py",
    "tests/test_monitoring_worker.py", "tests/test_monitoring_store.py", "tests/test_monitoring_integration.py",
    "compose.monitoring.yaml", "services/monitoring/Dockerfile", "docs/STAGE_9_3_AUTOMATIC_LOG_MONITORING.md",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_digests(directory, entries, count):
    if len(entries) != count:
        raise ValueError(f"Expected {count} entries in {directory.relative_to(ROOT)}, found {len(entries)}")
    for name, expected in entries.items():
        path = (directory / name).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Digest or scope mismatch: {directory.relative_to(ROOT)}/{name}")
    return count


def frozen():
    lines = (FROZEN / "freeze_manifest.sha256").read_text(encoding="ascii").splitlines()
    entries = {name: sha for sha, name in (line.split("  ", 1) for line in lines)}
    if len(lines) != 8:
        raise ValueError("Unexpected frozen manifest line count")
    return verify_digests(FROZEN, entries, 8)


def verify_manifest(directory, name, count):
    return verify_digests(directory, read_json(directory / name), count)


def bundles(directories, directory_count, expected):
    if len(set(directories)) != directory_count:
        raise ValueError("Unexpected bundle coverage")
    total = 0
    for directory in directories:
        manifest = read_json(directory / "bundle_sha256.json")
        total += verify_digests(directory, manifest, len(manifest))
    if total != expected:
        raise ValueError(f"Expected {expected} bundle digests, found {total}")
    return total


def cohort():
    verify_digests(COHORT, {"collection_plan.json": (COHORT / "collection_plan.sha256").read_text().strip()}, 1)
    plan = read_json(COHORT / "collection_plan.json")
    verify_digests(ROOT, plan["fingerprints"], len(plan["fingerprints"]))
    directories = [ROOT / slot["output_directory"] for slot in plan["slots"]]
    return bundles(directories, 10, 190)


def research():
    count = audit()["verified_unique_files"]
    if count != 63:
        raise ValueError(f"Expected 63 research fingerprints, found {count}")
    return count


def unchanged_known_llm_sources():
    for name, expected in LLM_BLOBS.items():
        contents = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(contents).hexdigest() != expected:
            raise ValueError(f"New LLM source drift: {name}")
    return "baseline byte content verified (LF/CRLF)"


def git_names(*arguments):
    output = subprocess.check_output(["git", *arguments], cwd=ROOT)
    return set(filter(None, output.decode("utf-8").split("\0")))


def main():
    report = {
        "baseline_commit": BASELINE,
        "mandatory": {},
        "known_limitations": [
            "HISTORICAL_SCOPE_UNRESOLVED", "LLM_SOURCE_DIGEST_MISMATCH", "FULL_LLM_BENCHMARK_INTEGRITY_FAIL",
        ],
        "new_mismatches": {},
    }
    changed = (git_names("diff", "--no-ext-diff", "--name-only", "-z", BASELINE, "--")
               | git_names("diff", "--cached", "--no-ext-diff", "--name-only", "-z", BASELINE, "--")
               | git_names("ls-files", "--others", "--exclude-standard", "-z"))
    report["protected_or_out_of_scope_changes"] = sorted(changed - STAGE_FILES - {"git"})

    def check(label, verify, *args):
        try:
            report["mandatory"][label] = {"count_or_result": verify(*args), "status": "PASS"}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report["mandatory"][label] = {"status": "FAIL"}
            report["new_mismatches"][label] = str(exc)

    check("frozen", frozen)
    check("cohort", cohort)
    check("acceptance", bundles, sorted(PLAN.glob("accept_7a6d2_*")), 5, 95)
    check("research", research)
    check("llm_sources_vs_approved_baseline", unchanged_known_llm_sources)
    check("historical_draft_protocol", lambda: verify_digests(
        PLAN, {"evaluation_protocol.json": read_json(PLAN / "collector_validation.json")[
            "draft_protocol_file_sha256"]}, 1
    ))
    for (directory, name), count in HISTORICAL.items():
        check((directory / name).relative_to(ROOT).as_posix(), verify_manifest, directory, name, count)
    report["scoped_integrity"] = (
        "FAIL" if report["new_mismatches"] or report["protected_or_out_of_scope_changes"] else "PASS"
    )
    print(json.dumps(report, indent=2))
    return int(report["scoped_integrity"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
