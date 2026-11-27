"""Run the original BGL training entrypoint and audit the fixed 100-episode checkpoint."""

import csv
import ctypes
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from meta_smoke import DATA, ROOT, Model, digest, entry, losses, np, peak_working_set_mib, save, torch
from preprocess.npz_io import validate_arrays, vocabulary_manifest
from preprocess.parameters import Vocabulary


def available_ram_mib():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("size", ctypes.c_ulong), ("load", ctypes.c_ulong),
            ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
            ("remaining", ctypes.c_ulonglong * 5),
        ]

    state = MemoryStatus()
    state.size = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        raise OSError("Cannot measure available RAM")
    return state.available / 2**20


def main(folder, protocol):
    frozen = json.loads(protocol.read_text(encoding="utf-8"))
    ram = available_ram_mib()
    free = shutil.disk_usage(DATA).free
    if ram < 768 or free < 256 * 2**20 or torch.cuda.is_available():
        raise RuntimeError(f"Insufficient CPU resources: available RAM {ram:.1f} MiB, disk {free} bytes")
    invariants = list(ROOT.glob("*.py")) + list(DATA.glob("*.npz"))
    invariants += list((DATA.parent / "meta_smoke_seed123/checkpoints").glob("*.pt"))
    before = {path: digest(path) for path in invariants}
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    verified = json.loads((DATA / "validation.json").read_text(encoding="utf-8"))
    v = manifest["vocabulary"]
    vocab = Vocabulary(v["keys"], v["chars"])
    assert vocabulary_manifest(vocab) == v and verified["vocabulary_sha256"] == v["sha256"]
    with np.load(DATA / "BGL_training.npz", allow_pickle=False) as data:
        entries = manifest["splits"]["BGL"]["training"]
        validate_arrays(data, 20, vocab, [len(e["line_ids"]) for e in entries])
        y = data["y"].argmax(1)
        assert y.tolist() == [e["label"] for e in entries] and np.bincount(y).tolist() == [104, 100]
        metadata = {k: int(data[k]) for k in ("key_vocab_size", "char_vocab_size", "max_params", "max_chars")}

    folder.mkdir(parents=True)
    os.chdir(folder)
    torch.set_num_threads(2)
    args = """--log_name BGL --window_size 20 --episodes 100 --k_norm 2 --k_anom 2 --m_query 1
    --temperature 0.07 --lr 1e-5 --num_layers 1 --param_dim 8 --loss_type apcl
    --margin_mode adaptive --margin_scale 1.0 --seed 123 --viz 0 --tag baseline100""".split()
    args += ["--preprocessed_dir", str(DATA)]
    grad, loss = [], []
    original_clip = torch.nn.utils.clip_grad_norm_
    original_loss = losses.asymmetric_prototype_contrastive_loss
    started = time.perf_counter()
    started_utc = datetime.now(timezone.utc).isoformat()

    def clip(params, max_norm):
        norm = original_clip(params, max_norm, error_if_nonfinite=True)
        grad.append(norm.item())
        if time.perf_counter() - started > 120 or peak_working_set_mib() > 1024:
            raise RuntimeError("100-episode CPU budget exceeded")
        return norm

    def apcl(*args, **kwargs):
        value = original_loss(*args, **kwargs)
        if not torch.isfinite(value):
            raise FloatingPointError("Nonfinite APCL")
        loss.append(value.item())
        return value

    with patch.object(torch.nn.utils, "clip_grad_norm_", clip), patch.object(
        losses, "asymmetric_prototype_contrastive_loss", apcl
    ):
        entry("meta_train.py", args)
    elapsed = time.perf_counter() - started
    peak = peak_working_set_mib()
    assert len(loss) == len(grad) == 100
    with next(Path("result").glob("*_loss.csv")).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [int(row["step"]) for row in rows] == list(range(1, 101))
    assert np.allclose([float(row["loss"]) for row in rows], loss, rtol=0, atol=1e-8)
    checkpoint, = Path("checkpoints").glob("*_baseline100-latest.pt")
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    assert all(torch.isfinite(t).all() for t in state["net"].values())
    assert all(torch.isfinite(t).all() for row in state["optimizer"]["state"].values()
               for t in row.values() if torch.is_tensor(t))
    assert {int(row["step"]) for row in state["optimizer"]["state"].values()} == {100}
    model = Model(num_layers=1, window_size=50, nhead=8, **metadata)
    load = model.load_state_dict(state["net"], strict=True)
    assert not load.missing_keys and not load.unexpected_keys
    assert before == {path: digest(path) for path in invariants}

    audit = {
        "argv": args, "start_utc": started_utc, "seconds": elapsed, "peak_working_set_mib_train": peak,
        "peak_working_set_mib_with_checkpoint_audit": peak_working_set_mib(),
        "available_ram_mib_before_run": ram, "disk_free_before_run_bytes": free,
        "torch": torch.__version__, "threads": 2, "losses": loss, "gradient_l2_before_clip": grad,
        "checkpoint": str(checkpoint), "checkpoint_bytes": checkpoint.stat().st_size,
        "checkpoint_sha256": digest(checkpoint), "tensor_count": len(state["net"]),
        "strict_load": str(load), "metadata": metadata, "hdfs_protocol_sha256": frozen["split_sha256"],
        "vocabulary_sha256": v["sha256"], "bgl_training_sha256": before[DATA / "BGL_training.npz"],
        "original_files_npz_and_smoke_checkpoint_unchanged": True,
    }
    save("training_audit.json", audit)
    print(json.dumps({k: val for k, val in audit.items() if k not in ("losses", "gradient_l2_before_clip")}))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
