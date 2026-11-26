"""Run and audit the real-data preprocessing and CPU forward checks."""

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

import numpy as np

from preprocess.__main__ import peak_working_set_mib, run
from preprocess.datasets import BLOCK, class_counts, read_bgl
from preprocess.npz_io import validate_arrays, vocabulary_manifest
from preprocess.parameters import Vocabulary

SEED = 123


class ZipText:
    def __init__(self, archive, filename):
        self.archive = archive
        members = [item for item in archive.infolist() if not item.is_dir() and Path(item.filename).name == filename]
        if len(members) != 1:
            raise ValueError(f"Expected one {filename} in {archive.filename}")
        self.member = members[0]

    def open(self, *, encoding, errors="strict", newline=None):
        return io.TextIOWrapper(self.archive.open(self.member), encoding=encoding, errors=errors, newline=newline)

    def __str__(self):
        return f"{self.archive.filename}!/{self.member.filename}"


def args_for(bgl, hdfs, labels, start, output):
    return argparse.Namespace(
        bgl_log=bgl, hdfs_log=hdfs, hdfs_labels=labels,
        sbert_dir=ROOT / "sbert", output=output,
        max_sequences=256, bgl_start_line=start, hdfs_max_retained_lines=50000,
        seed=SEED, embedding_batch_size=4,
    )


def preprocess(start, output):
    with ZipFile(ROOT / "archives/BGL.zip") as bgl, ZipFile(ROOT / "archives/HDFS_v1.zip") as hdfs:
        args = args_for(ZipText(bgl, "BGL.log"), ZipText(hdfs, "HDFS.log"),
                        ZipText(hdfs, "anomaly_label.csv"), start, output)
        for member in (args.bgl_log, args.hdfs_log, args.hdfs_labels):
            print(f"Streaming {member} ({member.member.file_size} bytes)", flush=True)
        run(args)


def inspect_bgl(start, candidates):
    with ZipFile(ROOT / "archives/BGL.zip") as archive:
        raw = ZipText(archive, "BGL.log")
        for offset in range(candidates):
            line = start + offset * 256 * 20
            train, test = read_bgl(raw, 256, line)
            counts = {"training": class_counts(train), "testing": class_counts(test)}
            ready = min(counts["training"].values()) >= 3 and min(counts["testing"].values()) >= 1
            print(json.dumps({"start": line, **counts, "ready": ready}), flush=True)
            if ready:
                return
        raise SystemExit("No BGL candidate meets class counts")


def truth_from_archives(manifest):
    with ZipFile(ROOT / "archives/BGL.zip") as bgl:
        train, test = read_bgl(ZipText(bgl, "BGL.log"), 256, manifest["arguments"]["bgl_start_line"])
        for split, sequences in (("training", train), ("testing", test)):
            assert manifest["splits"]["BGL"][split] == [
                {"id": seq.id, "label": seq.label, "line_ids": [line.id for line in seq.lines]}
                for seq in sequences
            ]
    expected = {seq["id"]: seq["label"] for split in manifest["splits"]["HDFS"].values() for seq in split}
    expected_lines = {seq["id"]: seq["line_ids"]
                      for split in manifest["splits"]["HDFS"].values() for seq in split}
    collected = {block: [] for block in expected}
    with ZipFile(ROOT / "archives/HDFS_v1.zip") as hdfs:
        with ZipText(hdfs, "anomaly_label.csv").open(encoding="utf-8-sig", newline="") as stream:
            actual = {row["BlockId"]: {"Normal": 0, "Anomaly": 1}[row["Label"]]
                      for row in csv.DictReader(stream) if row["BlockId"] in expected}
        scanned = 0
        with ZipText(hdfs, "HDFS.log").open(encoding="utf-8", errors="replace") as stream:
            for scanned, line in enumerate(stream, 1):
                for block in {match.group() for match in BLOCK.finditer(line)} & expected.keys():
                    collected[block].append(scanned)
    assert actual == expected
    assert collected == expected_lines
    return scanned


def validate_and_forward(output):
    started = time.perf_counter()
    import torch
    from dataloader import DataGenerator
    from losses import apcl_loss
    from model import Model

    if (output / "validation.json").exists():
        raise ValueError("Validation already exists for this output")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((ROOT / "provenance.json").read_text(encoding="utf-8"))
    hdfs_lines_scanned = truth_from_archives(manifest)
    vocab_info = manifest["vocabulary"]
    vocab = Vocabulary(vocab_info["keys"], vocab_info["chars"])
    assert vocabulary_manifest(vocab) == vocab_info
    results = {"vocabulary_sha256": vocab_info["sha256"], "splits": {}, "drain": {}, "forward": {},
               "hdfs_raw_lines_scanned": hdfs_lines_scanned}
    templates = set()
    for domain, window in (("BGL", 20), ("HDFS", 50)):
        partitions = manifest["splits"][domain]
        train_ids, test_ids = ({seq["id"] for seq in partitions[split]} for split in ("training", "testing"))
        train_lines, test_lines = (
            {line for seq in partitions[split] for line in seq["line_ids"]} for split in ("training", "testing")
        )
        assert not train_ids & test_ids and not train_lines & test_lines
        with (output / f"{domain}_events.jsonl").open(encoding="utf-8") as stream:
            events = [json.loads(line) for line in stream]
        assert len(events) == len(train_lines | test_lines)
        assert {event["line_id"] for event in events} == train_lines | test_lines
        domain_templates = {event["template"] for event in events}
        assert len({event["event_id"] for event in events}) == len(domain_templates)
        results["drain"][domain] = {"unique_raw_lines": len(events), "templates": len(domain_templates)}
        templates.update(domain_templates)
        for split, sequences in partitions.items():
            path = output / f"{domain}_{split}.npz"
            lengths = [len(seq["line_ids"]) for seq in sequences]
            assert all(seq["line_ids"] == sorted(set(seq["line_ids"])) for seq in sequences)
            assert len({seq["id"] for seq in sequences}) == len(sequences)
            with np.load(path, allow_pickle=False) as data:
                arrays = {name: data[name] for name in data.files}
            validate_arrays(arrays, window, vocab, lengths)
            labels = arrays["y"].argmax(axis=1)
            assert labels.tolist() == [seq["label"] for seq in sequences]
            counts = {"Normal": int(sum(labels == 0)), "Anomaly": int(sum(labels == 1))}
            assert counts == manifest["class_counts"][domain][split] and min(counts.values()) > 0
            slots = len(lengths) * window
            padding = slots - sum(min(window, length) for length in lengths)
            results["splits"][path.name] = {
                "fields": {name: {"shape": list(value.shape), "dtype": str(value.dtype)}
                           for name, value in arrays.items()},
                "class_counts": counts, "padding_slots": padding, "slots": slots,
                "padding_ratio": padding / slots, "long_sequences": sum(length > window for length in lengths),
                "events_beyond_window": sum(max(0, length - window) for length in lengths),
                "line_assignments": sum(lengths), "bytes": path.stat().st_size,
            }
            del arrays
    results["unique_templates_and_sbert_embeddings"] = len(templates)

    torch.manual_seed(SEED)
    torch.set_num_threads(2)
    model = Model(num_layers=1, window_size=50, key_vocab_size=len(vocab.keys) + 2,
                  char_vocab_size=len(vocab.chars) + 2, max_params=8, max_chars=16).eval()
    for domain, split, window in (("BGL", "training", 20), ("HDFS", "testing", 50)):
        with np.load(output / f"{domain}_{split}.npz", allow_pickle=False) as data:
            labels = data["y"].argmax(axis=1)
            indices = [np.flatnonzero(labels == cls)[:3] for cls in (0, 1)]
            assert all(len(group) == 3 for group in indices)
            support = np.concatenate([group[:2] for group in indices])
            query = np.concatenate([group[2:] for group in indices])
            selection = np.concatenate((support, query))
            assert len(set(selection)) == 6
            params = tuple(data[name][selection] for name in ("p_key", "p_type", "p_val", "p_num"))
            dataset = DataGenerator(data["x"][selection], labels[selection], window, p=params, max_params=8)
        batch = [dataset[index] for index in range(len(selection))]
        x = torch.tensor(np.stack([row[0] for row in batch]), dtype=torch.float32)
        y = torch.tensor([row[1] for row in batch], dtype=torch.long)
        p = tuple(torch.from_numpy(np.stack([row[2][j] for row in batch])) for j in range(4))
        forward_started = time.perf_counter()
        with torch.inference_mode():
            encoded = model(x, p)
            loss = apcl_loss(encoded[:4], y[:4], encoded[4:], y[4:], temperature=0.07)
        assert tuple(encoded.shape) == (6, 768) and torch.isfinite(encoded).all() and torch.isfinite(loss)
        sequences = manifest["splits"][domain][split]
        results["forward"][domain] = {
            "shape": list(encoded.shape), "finite": True, "apcl": loss.item(), "temperature": 0.07,
            "seconds": time.perf_counter() - forward_started,
            "support": [sequences[i]["id"] for i in support], "query": [sequences[i]["id"] for i in query],
        }
        if domain == "BGL":
            with torch.inference_mode():
                extended = torch.cat((x, x.new_zeros((len(x), 30, 768))), dim=1)
                extended_p = tuple(torch.cat((value, value.new_zeros(
                    (len(x), 30, *value.shape[2:]))), dim=1) for value in p)
                longer = model(extended, extended_p)
                empty_event = tuple(value[:1, -1:] for value in extended_p)
                empty_signal = model.param_encoder(*empty_event).norm().item()
            results["padding_probe"] = {"bgl_max_cls_difference_20_to_50":
                                        (encoded - longer).abs().max().item(),
                                        "empty_event_parameter_l2": empty_signal}
    results.update({"seed": SEED, "device": "cpu", "threads": 2, "sbert_revision": provenance["sbert_revision"],
                    "elapsed_seconds": time.perf_counter() - started,
                    "peak_working_set_mib": peak_working_set_mib()})
    with (output / "validation.json").open("x", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2)
    print(json.dumps({k: v for k, v in results.items() if k != "splits"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("inspect-bgl", "preprocess", "validate"))
    parser.add_argument("--bgl-start-line", type=int, default=1)
    parser.add_argument("--bgl-candidates", type=int, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / "preprocessed_data")
    args = parser.parse_args()
    if args.stage == "inspect-bgl":
        inspect_bgl(args.bgl_start_line, args.bgl_candidates)
    elif args.stage == "preprocess":
        preprocess(args.bgl_start_line, args.output)
    else:
        validate_and_forward(args.output)
