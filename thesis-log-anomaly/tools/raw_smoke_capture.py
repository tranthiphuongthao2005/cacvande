"""Copy one opted-in Gemini response from container tmpfs to an ignored local file."""

import hashlib
import re
import subprocess
from pathlib import Path


CONTAINER_PATH = "/private-response/model-response.txt"
MAX_BYTES = 65536
APPROVAL_ID = re.compile(r"^gemini-smoke-7b1-[0-9]{3}$")


def copy_one_raw_response(approval_id, mode, root, container="thesis-log-anomaly-llm-service-1"):
    if not APPROVAL_ID.fullmatch(approval_id) or mode not in {"single_service", "cross_service"}:
        raise ValueError("Invalid raw capture scope")
    local_dir = Path(root) / "experiments/gemini_smoke_7b1/private"
    filename = f"{approval_id}.{mode}.raw.txt"
    target = local_dir / filename
    partial = local_dir / (filename + ".part")
    if target.exists() or partial.exists():
        return {"status": "ALREADY_PRESENT"}
    try:
        completed = subprocess.run(
            ("docker", "exec", container, "cat", CONTAINER_PATH),
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "READ_FAILED"}
    if completed.returncode:
        return {"status": "NOT_AVAILABLE"}
    raw = completed.stdout
    if not raw or len(raw) > MAX_BYTES:
        return {"status": "INVALID_SIZE"}
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        with partial.open("xb") as stream:
            stream.write(raw)
        partial.rename(target)
    except OSError:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        return {"status": "WRITE_FAILED"}
    return {"status": "SAVED", "path": str(target.relative_to(root)).replace("\\", "/"),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
