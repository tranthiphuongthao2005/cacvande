"""Evaluate representation and protocol evidence without MeCoLog forward."""

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

from app.mecolog_runtime import CHECKPOINT, CHECKPOINT_SHA, build_candidates, candidate_resources, digest
from app.micro_dataset import (POOLS, checksum, groups_for, inputs_and_labels, propose_assignment,
                               validate_assignment)
from app.micro_parser import CATALOG_VERSION, parse_event, typed_features
from tools.audit_research import audit
from tools.collect_micro_dataset import write


def check_compatibility(root, research, seed, with_features):
    import json

    observations, labels = inputs_and_labels(root)
    receipt = json.loads((root / "collection.json").read_text(encoding="utf-8"))
    actual = {run: (checksum(session.model_dump(mode="json")), checksum(labels[run]))
              for run, session in observations.items()}
    expected = {row["run_id"]: (row["observation_sha256"], row["label_sha256"]) for row in receipt["runs"]}
    if actual != expected or len(expected) != len(receipt["runs"]):
        raise ValueError("Collection fingerprint mismatch")
    ids = [event.event_id for session in observations.values() for event in session.events]
    if len(ids) != len(set(ids)) or len(observations) != len({s.trace_id for s in observations.values()}):
        raise ValueError("Duplicate observation lineage")
    groups = groups_for(observations, labels)
    assignment = propose_assignment(observations, labels, seed)
    if assignment != propose_assignment(dict(reversed(list(observations.items()))), labels, seed):
        raise ValueError("Nondeterministic group assignment")
    counts = {}
    for pool in POOLS:
        rows = assignment[pool]
        counts[pool] = {"normal": sum(labels[r]["label"] == 0 for r in rows),
                        "anomaly": sum(labels[r]["label"] == 1 for r in rows),
                        "fault_types": dict(Counter(labels[r]["fault_type"] for r in rows))}
    blocker = None
    try:
        stats = validate_assignment(observations, labels, assignment)
    except ValueError as exc:
        stats, blocker = None, str(exc)
    checkpoint = research / "real_smoke_cpu" / CHECKPOINT
    before = digest(checkpoint)
    if before != CHECKPOINT_SHA:
        raise ValueError("Unexpected checkpoint digest")
    events = [parse_event(s.trace_id, e) for s in observations.values() for e in s.events]
    if events != [parse_event(s.trace_id, e) for s in observations.values() for e in s.events]:
        raise ValueError("Nondeterministic parser")
    n = len(observations)
    lengths = [len(s.events) for s in observations.values()]
    report = {
        "scoring": "NOT_READY_FOR_SCORING", "scoring_enabled": False, "model_forward": False,
        "parser_version": CATALOG_VERSION,
        "observations": n, "events": len(events), "rejected_runs": len(list((root / "rejected").glob("*.json"))),
        "fault_types": dict(Counter(row["fault_type"] for row in labels.values())),
        "unique_templates": len({e.template for e in events}), "unknown_events": sum(e.unknown_template for e in events),
        "partial_sessions": sum(s.source_metadata.completeness == "partial" for s in observations.values()),
        "length_histogram": dict(sorted(Counter(lengths).items())),
        "padding_positions_window50": sum(max(50 - length, 0) for length in lengths),
        "truncated_events_window50": sum(max(length - 50, 0) for length in lengths),
        "ground_truth_isolated_by_schema": True, "unique_trace_event_ids": True,
        "split_seed": seed, "draft_counts": counts, "independence_groups": len(set(groups.values())),
        "draft_assignment": assignment, "draft_assignment_sha256": checksum(assignment),
        "group_sizes": sorted(Counter(groups.values()).values(), reverse=True),
        "groups_per_label": {
            str(label): len({groups[run] for run in observations if labels[run]["label"] == label})
            for label in (0, 1)
        },
        "protocol_locked": False, "split_blocker": blocker, "valid_split_stats": stats,
        "anomaly_lengths": {"short": sum(labels[r]["label"] == 1 and len(s.events) <= 4
                                          for r, s in observations.items()),
                            "long": sum(labels[r]["label"] == 1 and len(s.events) > 4
                                         for r, s in observations.items())},
        "explicit_blockers": ["REPRESENTATION_EFFECT_UNVERIFIED", "NO_APPROVED_INDEPENDENT_PROTOCOL"],
    }
    support = None if stats is None else stats["support"]
    eligible = bool(support and not support["partial"] and all(not row["partial"] for row in stats.values()))
    report["support_readiness"] = {
        "single_structural_minimum": eligible,
        "multi_structural_minimum_without_fallback": bool(
            eligible and min(support["anomaly_short"], support["anomaly_long"]) >= 2),
        "approved_for_scoring": False,
    }
    if with_features:
        import torch

        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        drain, vocab, embed, replay = candidate_resources(research)
        vectors = {}
        variants, sessions = {}, list(observations.values())
        for name, positional in [("catalog_named", False), ("catalog_positional", True), ("hdfs_replay", None)]:
            parser = None
            if positional is not None:
                def parser(trace_id, event):
                    result = parse_event(trace_id, event)
                    return result.template, result.unknown_template, typed_features(result, positional=positional)

            def cached(templates):
                new = sorted(set(templates) - vectors.keys())
                if new:
                    vectors.update(embed(new))
                return {key: vectors[key] for key in templates}

            batches, shapes, counts = [], [], Counter()
            for start in range(0, n, 8):
                subset = sessions[start:start+8]
                arrays, diagnostics = build_candidates(subset, drain, vocab, cached, parser)
                second, again = build_candidates(subset, drain, vocab, cached, parser)
                if diagnostics != again or any(arrays[k].tobytes() != second[k].tobytes() for k in arrays):
                    raise ValueError("Candidate tensor materialization was nondeterministic")
                batches.append({k: hashlib.sha256(v.tobytes()).hexdigest() for k, v in arrays.items()})
                shapes.append({k: list(v.shape) for k, v in arrays.items()})
                for row in diagnostics:
                    counts.update({k: v for k, v in row.items() if k != "trace_id"})
            variants[name] = {"schema_valid": True, "counts": dict(counts), "batch_shapes": shapes,
                              "candidate_fingerprint": checksum(batches), "cached_sbert_replay_equal": True}
        report.update({"drain_training_lines_replayed": replay, "tensor_variants": variants})
    if digest(checkpoint) != before:
        raise ValueError("Checkpoint bytes changed")
    report["research_audit"] = audit()
    return report


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--dataset", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--research", type=Path, default=Path(__file__).resolve().parents[2] / "tuanmartin-MeCoLog-8c446ac")
    cli.add_argument("--seed", type=int, default=123)
    cli.add_argument("--features", action="store_true")
    cli.add_argument("--ml-site-packages", type=Path)
    args = cli.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.ml_site_packages:
        sys.path.append(str(args.ml_site_packages.resolve(strict=True)))
    write(args.output, check_compatibility(args.dataset, args.research, args.seed, args.features))


if __name__ == "__main__":
    main()
