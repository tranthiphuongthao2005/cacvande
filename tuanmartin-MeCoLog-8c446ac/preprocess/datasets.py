"""Read bounded smoke-test subsets and retain original line identities."""

import csv
import random
import re
from dataclasses import dataclass

BLOCK = re.compile(r"(?<!\w)blk_-?\d+(?!\w)")
LABELS = {"Normal": 0, "Anomaly": 1}


@dataclass(frozen=True)
class Line:
    id: int
    text: str


@dataclass(frozen=True)
class Sequence:
    id: str
    label: int
    lines: tuple[Line, ...]


def read_bgl(path, limit, start_line=1):
    if start_line < 1 or (start_line - 1) % 20:
        raise ValueError("BGL start line must be 1 plus a multiple of 20")
    sequences = []
    window = []
    alert = False
    with path.open(encoding="utf-8", errors="replace") as stream:
        for number, raw in enumerate(stream, 1):
            if number < start_line:
                continue
            fields = raw.split(maxsplit=9)
            if len(fields) != 10:
                raise ValueError(f"Malformed BGL line {number}")
            window.append(Line(number, raw.strip()))
            alert |= fields[0] != "-"
            if len(window) == 20:
                sequences.append(Sequence(f"BGL:{window[0].id}", int(alert), tuple(window)))
                window, alert = [], False
                if len(sequences) == limit:
                    break
    boundary = len(sequences) * 4 // 5
    return sequences[:boundary], sequences[boundary:]


def sample_block_labels(path, limit, seed):
    """Stratified reservoir sampling keeps the requested number of IDs in RAM."""
    rng = random.Random(seed)
    capacity = (limit // 2, limit - limit // 2)
    pools = [[], []]
    counts = [0, 0]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"BlockId", "Label"}.issubset(reader.fieldnames or ()):
            raise ValueError("Expected HDFS CSV columns BlockId and Label")
        for row in reader:
            block, label = row["BlockId"], row["Label"]
            if not block or not BLOCK.fullmatch(block) or label not in LABELS:
                raise ValueError(f"Invalid HDFS ground truth at CSV line {reader.line_num}")
            label = LABELS[label]
            counts[label] += 1
            if len(pools[label]) < capacity[label]:
                pools[label].append(block)
            else:
                slot = rng.randrange(counts[label])
                if slot < capacity[label]:
                    pools[label][slot] = block
    memberships = {}
    for label, pool in enumerate(pools):
        rng.shuffle(pool)
        boundary = len(pool) * 4 // 5
        for index, block in enumerate(pool):
            if block in memberships:
                raise ValueError(f"Duplicate ground truth for sampled BlockId {block}")
            memberships[block] = (int(index >= boundary), label)
    return memberships


def read_hdfs(path, labels, limit, seed, max_lines=50000):
    memberships = sample_block_labels(labels, limit, seed)
    sessions = {block: [] for block in memberships}
    shared = set()
    retained = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for number, raw in enumerate(stream, 1):
            blocks = {match.group() for match in BLOCK.finditer(raw)} & memberships.keys()
            if len({memberships[block][0] for block in blocks}) > 1:
                shared.update(blocks)
            if blocks:
                retained += len(blocks)
                if retained > max_lines:
                    raise ValueError("HDFS retained-line budget exceeded. Reduce --max-sequences.")
                line = Line(number, raw.strip())
                for block in blocks:
                    sessions[block].append(line)
    splits = ([], [])
    for block, (split, label) in memberships.items():
        if block not in shared and sessions[block]:
            splits[split].append(Sequence(block, label, tuple(sessions[block])))
    missing = sum(not lines for lines in sessions.values())
    return splits[0], splits[1], {"shared_sessions_excluded": len(shared), "missing_sessions": missing}


def class_counts(sequences):
    return {name: sum(seq.label == value for seq in sequences) for name, value in LABELS.items()}


def validate_split(train, test):
    train_ids = {seq.id for seq in train}
    test_ids = {seq.id for seq in test}
    if len(train_ids) != len(train) or len(test_ids) != len(test) or train_ids & test_ids:
        raise ValueError("Duplicate or shared sequence IDs")
    train_lines = {line.id for seq in train for line in seq.lines}
    if any(line.id in train_lines for seq in test for line in seq.lines):
        raise ValueError("Raw lines shared across train and test")
