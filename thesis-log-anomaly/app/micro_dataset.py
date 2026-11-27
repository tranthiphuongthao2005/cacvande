"""Offline label isolation, conservative grouping and split checks."""

import hashlib
import json
from collections import Counter, defaultdict
from random import Random

from app.contracts import DetectionSession
from app.micro_parser import parse_event
from app.prototypes import Lineage, validate_pools

POOLS = ("support", "development", "evaluation")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def inputs_and_labels(root):
    observations, labels = {}, {}
    for file in sorted((root / "observations").glob("*.json")):
        raw = file.read_text(encoding="utf-8")
        session = DetectionSession.model_validate_json(raw)
        if session.model_dump(mode="json") != json.loads(raw):
            raise ValueError("Noncanonical observation")
        observations[file.stem] = session
    for file in sorted((root / "labels").glob("*.json")):
        label = json.loads(file.read_text(encoding="utf-8"))
        if label["run_id"] != file.stem or type(label["label"]) is not int or label["label"] not in (0, 1):
            raise ValueError("Invalid label provenance")
        if not label["family"] or not label["fault_type"] or not label["provenance"]:
            raise ValueError("Incomplete label provenance")
        labels[file.stem] = label
    if not observations or observations.keys() != labels.keys():
        raise ValueError("Missing observation/label pair")
    for key, session in observations.items():
        if session.trace_id != labels[key]["trace_id"]:
            raise ValueError("Trace and label lineage differ")
    return observations, labels


def signatures(session):
    templates = [parse_event(session.trace_id, e).template for e in session.events]
    # Collapse adjacent retry repeats when grouping; retries remain present in features.
    collapsed = [template for i, template in enumerate(templates) if i == 0 or templates[i - 1] != template]
    return {checksum(collapsed), checksum(sorted(set(templates)))}


def groups_for(observations, labels):
    parent = {run: run for run in observations}
    owner = {}

    def root(run):
        while parent[run] != run:
            run = parent[run]
        return run

    for run, session in sorted(observations.items()):
        keys = signatures(session) | {"family:" + labels[run]["family"]}
        for key in sorted(keys):
            first = owner.setdefault(key, run)
            a, b = sorted((root(run), root(first)))
            parent[b] = a
    return {run: root(run) for run in observations}


def validate_assignment(observations, labels, assignment):
    groups = groups_for(observations, labels)
    if (set(assignment) != set(POOLS) or set(observations) != {r for runs in assignment.values() for r in runs}
            or len(observations) != sum(map(len, assignment.values()))):
        raise ValueError("Each run must appear exactly once in a named pool")
    pools = [[Lineage(observations[r].trace_id, frozenset(e.event_id for e in observations[r].events),
                      groups[r]) for r in assignment[name]] for name in POOLS]
    validate_pools(*pools)
    stats = {}
    for name in POOLS:
        rows = assignment[name]
        counts = Counter(labels[r]["label"] for r in rows)
        if set(counts) != {0, 1}:
            raise ValueError(f"Both classes required in {name}")
        anomaly = [len(observations[r].events) for r in rows if labels[r]["label"] == 1]
        stats[name] = {"normal": counts[0], "anomaly": counts[1],
                       "fault_types": dict(Counter(labels[r]["fault_type"] for r in rows)),
                       "anomaly_short": sum(n <= 4 for n in anomaly),
                       "anomaly_long": sum(n > 4 for n in anomaly),
                       "partial": sum(observations[r].source_metadata.completeness != "complete" for r in rows)}
    return stats


def propose_assignment(observations, labels, seed):
    buckets = defaultdict(list)
    for run, group in groups_for(observations, labels).items():
        buckets[group].append(run)
    partitions = defaultdict(list)
    for group, runs in sorted(buckets.items()):
        partitions[tuple(sorted({labels[r]["label"] for r in runs}))].append(group)
    rng = Random(seed)
    assignment = {name: [] for name in POOLS}
    for group_ids in partitions.values():
        rng.shuffle(group_ids)
        for i, group in enumerate(group_ids):
            assignment[POOLS[i % len(POOLS)]].extend(sorted(buckets[group]))
    return assignment
