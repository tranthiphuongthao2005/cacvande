"""Export and validate numeric arrays accepted by original meta-learning scripts."""

import json
import hashlib

import numpy as np

from .embeddings import DIM
from .parameters import C, P, encode_parameters

METADATA = ("key_vocab_size", "char_vocab_size", "max_params", "max_chars")


def vocabulary_manifest(vocab):
    mappings = {"keys": vocab.keys, "chars": vocab.chars, "PAD": 0, "UNK": 1}
    canonical = json.dumps(mappings, sort_keys=True, ensure_ascii=True).encode("ascii")
    return {**mappings, "sha256": hashlib.sha256(canonical).hexdigest()}


def build_arrays(sequences, events, embeddings, vocab, window):
    n = len(sequences)
    arrays = {
        "x": np.zeros((n, window, DIM), dtype=np.float32),
        "y": np.zeros((n, 2), dtype=np.uint8),
        "p_key": np.zeros((n, window, P), dtype=np.int64),
        "p_type": np.zeros((n, window, P), dtype=np.int64),
        "p_val": np.zeros((n, window, P, C), dtype=np.int64),
        "p_num": np.zeros((n, window, P), dtype=np.float32),
        "key_vocab_size": np.array(len(vocab.keys) + 2, dtype=np.int64),
        "char_vocab_size": np.array(len(vocab.chars) + 2, dtype=np.int64),
        "max_params": np.array(P, dtype=np.int64),
        "max_chars": np.array(C, dtype=np.int64),
    }
    for i, sequence in enumerate(sequences):
        if sequence.label not in (0, 1) or not sequence.lines:
            raise ValueError(f"Invalid sequence {sequence.id}")
        arrays["y"][i, sequence.label] = 1
        for j, line in enumerate(sequence.lines[:window]):
            event = events[line.id]
            arrays["x"][i, j] = embeddings[event.template]
            features = encode_parameters(event.parameters, vocab)
            for name, feature in zip(("p_key", "p_type", "p_val", "p_num"), features):
                arrays[name][i, j] = feature
    validate_arrays(arrays, window, vocab, [len(seq.lines) for seq in sequences])
    return arrays


def validate_arrays(arrays, window, vocab, lengths):
    n = len(lengths)
    if window <= 0 or any(length <= 0 for length in lengths):
        raise ValueError("Invalid window or sequence length")
    expected = {
        "x": ((n, window, DIM), np.float32),
        "y": ((n, 2), np.uint8),
        "p_key": ((n, window, P), np.int64),
        "p_type": ((n, window, P), np.int64),
        "p_val": ((n, window, P, C), np.int64),
        "p_num": ((n, window, P), np.float32),
        **{name: ((), np.int64) for name in METADATA},
    }
    for name, (shape, dtype) in expected.items():
        if name not in arrays or arrays[name].shape != shape or arrays[name].dtype != dtype:
            raise ValueError(f"Missing field or invalid shape/dtype: {name}")
    for mapping in (vocab.keys, vocab.chars):
        if sorted(mapping.values()) != list(range(2, len(mapping) + 2)):
            raise ValueError("Vocabulary IDs must be contiguous with PAD=0 and UNK=1")
    sizes = (len(vocab.keys) + 2, len(vocab.chars) + 2, P, C)
    if tuple(int(arrays[name]) for name in METADATA) != sizes:
        raise ValueError("Vocabulary or parameter metadata mismatch")
    if not np.isfinite(arrays["x"]).all() or not np.isfinite(arrays["p_num"]).all():
        raise ValueError("Non-finite features")
    if np.any(arrays["y"] > 1) or np.any(arrays["y"].sum(axis=1) != 1):
        raise ValueError("Invalid one-hot labels")
    for name, size in (("p_key", sizes[0]), ("p_val", sizes[1]), ("p_type", 5)):
        if (arrays[name] < 0).any() or (arrays[name] >= size).any():
            raise ValueError(f"Out-of-range indices: {name}")
    for index, length in enumerate(lengths):
        for name in ("x", "p_key", "p_type", "p_val", "p_num"):
            if np.any(arrays[name][index, length:]):
                raise ValueError(f"Nonzero sequence padding: {name}")


def write_split(path, sequences, events, embeddings, vocab, window):
    arrays = build_arrays(sequences, events, embeddings, vocab, window)
    with path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
