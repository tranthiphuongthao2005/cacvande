"""Freeze HDFS pools using official labels and raw line identities only."""

import csv
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from preprocess.datasets import BLOCK
from run import ZipText

SEED = 123
PER_CLASS = {
    "development_support": 20,
    "development_query": 100,
    "final_support": 20,
    "final_query": 100,
}


def sha(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def main(output):
    previous = json.loads((HERE / "preprocessed_data/manifest.json").read_text())
    old = [seq for split in previous["splits"]["HDFS"].values() for seq in split]
    excluded_ids = {seq["id"] for seq in old}
    excluded_lines = {line for seq in old for line in seq["line_ids"]}
    archive_path = HERE / "archives/HDFS_v1.zip"
    with archive_path.open("rb") as stream:
        archive_md5 = hashlib.file_digest(stream, "md5").hexdigest()
    if archive_md5 != "76a24b4d9a6164d543fb275f89773260":
        raise ValueError("Official HDFS_v1 archive checksum mismatch")
    rng = random.Random(SEED)
    candidates = {"Normal": [], "Anomaly": []}
    seen = set()
    with ZipFile(archive_path) as archive:
        with ZipText(archive, "anomaly_label.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                block, label = row["BlockId"], row["Label"]
                if block in seen or not BLOCK.fullmatch(block) or label not in candidates:
                    raise ValueError("Invalid or duplicate official HDFS label")
                seen.add(block)
                if block not in excluded_ids:
                    candidates[label].append(block)
        for ids in candidates.values():
            rng.shuffle(ids)
            del ids[1024:]
        matched = {block: [] for ids in candidates.values() for block in ids}
        shared = set()
        old_overlap = set()
        with ZipText(archive, "HDFS.log").open(encoding="utf-8", errors="replace") as stream:
            for line_id, raw in enumerate(stream, 1):
                blocks = {match.group() for match in BLOCK.finditer(raw)}
                selected = blocks & matched.keys()
                if len(blocks) > 1:
                    shared.update(selected)
                if line_id in excluded_lines:
                    old_overlap.update(selected)
                for block in selected:
                    matched[block].append(line_id)
    result = {name: [] for name in PER_CLASS}
    for label, ids in candidates.items():
        usable = [block for block in ids if matched[block] and block not in shared and block not in old_overlap]
        if len(usable) < sum(PER_CLASS.values()):
            raise ValueError(f"Insufficient independent {label} candidates: {len(usable)}")
        offset = 0
        for name, count in PER_CLASS.items():
            result[name].extend({"block_id": block, "label": label, "raw_line_ids": matched[block]}
                                for block in usable[offset:offset + count])
            offset += count

    all_blocks, all_lines = set(excluded_ids), set(excluded_lines)
    summary = {}
    for name, entries in result.items():
        blocks = {seq["block_id"] for seq in entries}
        lines = [line for seq in entries for line in seq["raw_line_ids"]]
        if len(blocks) != len(entries) or len(set(lines)) != len(lines) or all_blocks & blocks or all_lines & set(lines):
            raise ValueError(f"Pool overlap: {name}")
        all_blocks.update(blocks)
        all_lines.update(lines)
        lengths = [len(seq["raw_line_ids"]) for seq in entries]
        summary[name] = {
            "counts": dict(Counter(seq["label"] for seq in entries)),
            "lines": len(lines), "length_range": [min(lengths), max(lengths)],
            "sessions_over_50": sum(length > 50 for length in lengths),
            "sha256": sha(entries),
        }
    report = {
        "seed": SEED, "archive_md5": archive_md5, "raw_lines_scanned": line_id,
        "excluded_previous_ids": len(excluded_ids), "excluded_previous_lines": len(excluded_lines),
        "candidate_count_per_class": {label: len(ids) for label, ids in candidates.items()},
        "candidates_on_multiblock_lines": len(shared),
        "candidate_overlap_with_previous_lines": len(old_overlap),
        "missing_candidate_sessions": sum(not lines for lines in matched.values()),
        "split_sha256": sha(result), "summary": summary, "pools": result,
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({key: val for key, val in report.items() if key != "pools"}, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
