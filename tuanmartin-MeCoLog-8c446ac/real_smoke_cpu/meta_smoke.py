import csv
import hashlib
import json
import os
import runpy
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import Model
import losses
from preprocess.__main__ import peak_working_set_mib
from preprocess.npz_io import validate_arrays, vocabulary_manifest
from preprocess.parameters import Vocabulary
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

DATA = ROOT / "real_smoke_cpu/preprocessed_data"
NAMES = ("BGL_training.npz", "HDFS_training.npz", "HDFS_testing.npz")
META = ("key_vocab_size", "char_vocab_size", "max_params", "max_chars")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(name, value):
    with open(name, "x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def entry(file, arguments):
    previous = sys.argv
    sys.argv = [str(ROOT / file), *arguments]
    try:
        print("CLI:", sys.argv, flush=True)
        return runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        sys.argv = previous


def main(folder):
    if torch.cuda.is_available():
        raise RuntimeError("This run requires the CPU PyTorch environment")
    torch.set_num_threads(2)
    folder.mkdir(parents=True)
    os.chdir(folder)
    Path("preprocessed_data").mkdir()
    original_hashes = {p.name: digest(p) for p in ROOT.glob("*.py")}
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((DATA / "validation.json").read_text(encoding="utf-8"))
    vocab_info = manifest["vocabulary"]
    vocab = Vocabulary(vocab_info["keys"], vocab_info["chars"])
    assert vocabulary_manifest(vocab) == vocab_info
    assert validation["vocabulary_sha256"] == vocab_info["sha256"]
    metadata = {}
    input_hashes = {}
    for name in NAMES:
        copy = Path("preprocessed_data") / name
        shutil.copyfile(DATA / name, copy)
        input_hashes[name] = digest(DATA / name)
        assert digest(copy) == input_hashes[name]
        domain, split = name.removesuffix(".npz").split("_")
        seqs = manifest["splits"][domain][split]
        with np.load(copy, allow_pickle=False) as data:
            arrays = {key: data[key] for key in data.files}
        validate_arrays(arrays, 20 if domain == "BGL" else 50, vocab, [len(s["line_ids"]) for s in seqs])
        labels = arrays["y"].argmax(axis=1)
        assert labels.tolist() == [s["label"] for s in seqs]
        assert min(np.bincount(labels, minlength=2)) >= 3
        metadata[name] = {key: int(arrays[key]) for key in META}
        del arrays
    assert all(meta == metadata[NAMES[0]] for meta in metadata.values())

    train = """--log_name BGL --window_size 20 --episodes 10 --k_norm 2 --k_anom 2 --m_query 1
    --temperature 0.07 --lr 1e-5 --num_layers 1 --param_dim 8 --loss_type apcl --margin_mode adaptive
    --margin_scale 1.0 --seed 123 --viz 0 --tag smoke10 --preprocessed_dir ./preprocessed_data""".split()
    grad = []
    observed_losses = []
    original_clip = torch.nn.utils.clip_grad_norm_
    original_apcl = losses.asymmetric_prototype_contrastive_loss

    def check_clip(parameters, max_norm):
        norm = original_clip(parameters, max_norm, error_if_nonfinite=True).item()
        grad.append(norm)
        return norm

    def check_loss(*args, **kwargs):
        value = original_apcl(*args, **kwargs)
        if not torch.isfinite(value):
            raise FloatingPointError("Nonfinite training loss")
        observed_losses.append(value.item())
        return value

    start = time.perf_counter()
    with patch.object(torch.nn.utils, "clip_grad_norm_", check_clip), patch.object(
        losses, "asymmetric_prototype_contrastive_loss", check_loss
    ):
        entry("meta_train.py", train)
    train_seconds = time.perf_counter() - start
    assert len(grad) == len(observed_losses) == 10
    checkpoint, = Path("checkpoints").glob("*_smoke10-latest.pt")
    with next(Path("result").glob("*_loss.csv")).open(newline="") as stream:
        recorded = list(csv.DictReader(stream))
    assert np.allclose(observed_losses, [float(row["loss"]) for row in recorded], rtol=0, atol=1e-8)
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    assert all(torch.isfinite(t).all() for t in state["net"].values())
    assert all(torch.isfinite(t).all() for row in state["optimizer"]["state"].values()
               for t in row.values() if torch.is_tensor(t))
    assert {int(row["step"]) for row in state["optimizer"]["state"].values()} == {10}
    check_model = Model(num_layers=1, window_size=50, nhead=8, **metadata[NAMES[1]])
    strict = check_model.load_state_dict(state["net"], strict=True)
    assert not strict.missing_keys and not strict.unexpected_keys
    save("training_audit.json", {"argv": train, "losses": observed_losses, "gradient_l2_before_clip": grad,
         "seconds": train_seconds, "process_peak_mib_through_train": peak_working_set_mib(),
         "checkpoint": str(checkpoint), "checkpoint_sha256": digest(checkpoint),
         "tensor_count": len(state["net"]), "strict_load": str(strict), "metadata": metadata,
         "vocabulary_sha256": vocab_info["sha256"], "input_sha256": input_hashes,
         "threads": 2, "torch": torch.__version__})
    del check_model
    expected = state["net"]
    del state

    test = """--pretrained_log_name BGL --log_name HDFS --num_layers 1 --param_dim 8 --window_size 50
    --support_include_anomaly --support_size 4 --query_size 0 --episodes 1 --batch_size 8 --seed 123
    --viz 0 --method MeCoLog-smoke --csv_path result/experiments.csv""".split()
    test += ["--load_path", str(checkpoint)]
    start = time.perf_counter()
    result = entry("meta_test.py", test)
    test_seconds = time.perf_counter() - start
    support = result["last_support_idx"]
    query = result["last_query_idx"]
    assert len(support) == 4 and len(query) == 48 and not set(support) & set(query)
    assert set(support) | set(query) == set(range(52))
    assert result["last_support_norm"] == result["last_support_anom"] == 2
    assert result["last_query_norm"] == result["last_query_anom"] == 24
    assert not result["r"].missing_keys and not result["r"].unexpected_keys
    actual = result["model"].state_dict()
    assert expected.keys() == actual.keys() and all(torch.equal(actual[k], v) for k, v in expected.items())
    assert np.isfinite(result["scores_eval"]).all()
    y, pred = result["y_eval"], result["pred"]
    metrics = {}
    for average in ("binary", "macro"):
        precision, recall, f1, _ = precision_recall_fscore_support(
            y, pred, labels=[0, 1], average=average, zero_division=0
        )
        metrics[average] = {"precision": precision, "recall": recall, "f1": f1}
    seqs = manifest["splits"]["HDFS"]["testing"]
    assert np.array_equal(np.flatnonzero(result["valid_mask"]), query)
    with open("query_predictions.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sequence_id", "label", "prediction", "anomaly_score"))
        writer.writerows((seqs[index]["id"], truth, label, score)
                         for index, truth, label, score in zip(query, y, pred, result["scores_eval"]))
    report = {"argv": test, "metrics": metrics, "roc_auc": result["auc"], "average_precision": result["pr_auc"],
              "confusion_matrix_labels": [0, 1], "confusion_matrix": confusion_matrix(y, pred, labels=[0, 1]).tolist(),
              "support_ids": [seqs[i]["id"] for i in support], "query_ids": [seqs[i]["id"] for i in query],
              "load_result": str(result["r"]), "all_loaded_weights_match_after_test": True,
              "seconds": test_seconds, "episode_seconds": result["testing_time_sec"],
              "process_peak_mib_through_test": peak_working_set_mib()}
    assert original_hashes == {p.name: digest(p) for p in ROOT.glob("*.py")}
    assert input_hashes == {name: digest(DATA / name) for name in NAMES}
    save("testing_audit.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "query_ids"}, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
