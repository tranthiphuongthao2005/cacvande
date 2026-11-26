"""Prepare a labeled BGL to HDFS smoke-test run using local input files."""

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

from .datasets import class_counts, read_bgl, read_hdfs, validate_split
from .embeddings import MODEL_ID, embed_templates
from .npz_io import vocabulary_manifest, write_split
from .parameters import Vocabulary
from .parsing import DrainAdapter


def peak_working_set_mib():
    if sys.platform != "win32":
        return None

    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD), ("page_faults", wintypes.DWORD),
            *((name, ctypes.c_size_t) for name in (
                "peak_working_set", "working_set", "peak_paged_pool", "paged_pool",
                "peak_nonpaged_pool", "nonpaged_pool", "pagefile", "peak_pagefile",
            )),
        ]

    counters = MemoryCounters()
    counters.size = ctypes.sizeof(counters)
    current_process = ctypes.windll.kernel32.GetCurrentProcess
    current_process.restype = wintypes.HANDLE
    memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    memory_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD)
    if memory_info(current_process(), ctypes.byref(counters), counters.size):
        return round(counters.peak_working_set / 2**20, 2)
    return None


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bgl-log", "hdfs-log", "hdfs-labels", "sbert-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--max-sequences", type=int, default=256)
    parser.add_argument("--bgl-start-line", type=int, default=1)
    parser.add_argument("--hdfs-max-retained-lines", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    return parser.parse_args()


def run(args):
    if min(args.max_sequences, args.embedding_batch_size, args.hdfs_max_retained_lines) < 1:
        raise ValueError("Limits and batch size must be positive")
    if args.max_sequences > 2048:
        raise ValueError("This smoke exporter supports at most 2048 sequences per domain")
    if args.output.exists():
        raise ValueError("Choose a new output directory")
    start = time.perf_counter()
    bgl_train, bgl_test = read_bgl(args.bgl_log, args.max_sequences, args.bgl_start_line)
    hdfs_train, hdfs_test, hdfs_report = read_hdfs(
        args.hdfs_log, args.hdfs_labels, args.max_sequences, args.seed, args.hdfs_max_retained_lines
    )
    datasets = {"BGL": (bgl_train, bgl_test), "HDFS": (hdfs_train, hdfs_test)}
    counts = {}
    for domain, (train, test) in datasets.items():
        validate_split(train, test)
        counts[domain] = {"training": class_counts(train), "testing": class_counts(test)}
        if not train or not test:
            raise ValueError(f"Empty {domain} split: {counts[domain]}")
    print(json.dumps({"class_counts": counts, "HDFS_exclusions": hdfs_report}), flush=True)
    if min(counts["BGL"]["training"].values()) < 3 or min(counts["HDFS"]["testing"].values()) < 3:
        raise ValueError("Need 3 unique examples per class in BGL train and HDFS test; expand the subset")

    parsed = {}
    for domain, (train, test) in datasets.items():
        drain = DrainAdapter(domain)
        drain.fit(train)
        drain.transform(train)
        parsed[domain] = drain.transform(test)
    source_ids = {line.id for sequence in bgl_train for line in sequence.lines}
    vocab = Vocabulary.fit(parsed["BGL"][line_id].parameters for line_id in sorted(source_ids))
    templates = {event.template for events in parsed.values() for event in events.values()}
    vectors = embed_templates(templates, args.sbert_dir, args.embedding_batch_size)
    print(f"Embedded {len(templates)} unique templates in {time.perf_counter() - start:.2f}s", flush=True)

    args.output.mkdir(parents=True)
    for domain, splits in datasets.items():
        window = {"BGL": 20, "HDFS": 50}[domain]
        for name, sequences in zip(("training", "testing"), splits):
            write_split(args.output / f"{domain}_{name}.npz", sequences, parsed[domain], vectors, vocab, window)
        with (args.output / f"{domain}_events.jsonl").open("x", encoding="utf-8") as stream:
            for event in parsed[domain].values():
                stream.write(json.dumps({
                    "line_id": event.line_id, "event_id": event.event_id, "template": event.template
                }) + "\n")
    manifest = {
        "arguments": vars(args),
        "model_id": MODEL_ID,
        "class_counts": counts,
        "hdfs_exclusions": hdfs_report,
        "vocabulary": vocabulary_manifest(vocab),
        "elapsed_seconds": time.perf_counter() - start,
        "peak_working_set_mib": peak_working_set_mib(),
        "splits": {
            domain: {
                name: [{"id": seq.id, "label": seq.label, "line_ids": [line.id for line in seq.lines]}
                       for seq in sequences]
                for name, sequences in zip(("training", "testing"), splits)
            }
            for domain, splits in datasets.items()
        },
    }
    with (args.output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, default=str, indent=2)
    print(f"Wrote validated splits and manifest to {args.output}")


def main():
    args = arguments()
    try:
        run(args)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
