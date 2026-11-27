import hashlib
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REVISION = "b404353e5a0ef9cdf6a4500baa81aaec875d4db0"
FILES = [
  [
    "BGL.zip",
    57489019,
    "md5",
    "4452953c470f2d95fcb32d5f6e733f7a"
  ],
  [
    "HDFS_v1.zip",
    186645559,
    "md5",
    "76a24b4d9a6164d543fb275f89773260"
  ],
  [
    "model.safetensors",
    265462608,
    "sha256",
    "3d58b7cb2697fad5b606046557e98380a868824a4d8a508bd04e97b2fb1559b8"
  ],
  [
    "1_Pooling/config.json",
    190,
    "git-sha1",
    "4e09f293dfe90bba49f87cfe7996271f07be2666"
  ],
  [
    "config.json",
    550,
    "git-sha1",
    "e6268961aa07e5315a77000a6f1f7a45f34ab6eb"
  ],
  [
    "config_sentence_transformers.json",
    122,
    "git-sha1",
    "b974b349cb2d419ada11181750a733ff82f291ad"
  ],
  [
    "modules.json",
    229,
    "git-sha1",
    "f7640f94e81bb7f4f04daf1668850b38763a13d9"
  ],
  [
    "sentence_bert_config.json",
    53,
    "git-sha1",
    "5fd10429389515d3e5cccdeda08cae5fea1ae82e"
  ],
  [
    "special_tokens_map.json",
    112,
    "git-sha1",
    "e7b0375001f109a6b8873d756ad4f7bbb15fbaa5"
  ],
  [
    "tokenizer.json",
    466081,
    "git-sha1",
    "40c4a0f6c414c8218190234bbce9bf4cc04fa3ac"
  ],
  [
    "tokenizer_config.json",
    450,
    "git-sha1",
    "51d7e16c00984f649bd3fb82dafc438ef7251ffb"
  ],
  [
    "vocab.txt",
    231508,
    "git-sha1",
    "fb140275c155a9c7c5a3b3e0e77a9e839594a938"
  ]
]

def acquire(row):
    name, size, algorithm, expected = row
    archive = name.endswith(".zip")
    url = (
        f"https://zenodo.org/api/records/8196385/files/{name}/content" if archive else
        f"https://huggingface.co/sentence-transformers/distilbert-base-nli-mean-tokens/resolve/{REVISION}/{name}"
    )
    file = ROOT / ("archives" if archive else "sbert") / name
    file.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    commands = []
    cache_hit = file.exists()
    if not cache_hit:
        partial = file.with_name(file.name + ".partial")
        curl = ["curl.exe", "--fail", "--silent", "--show-error", "--location",
                "--max-time", "1800", "--speed-limit", "10000", "--speed-time", "40"]
        if name == "HDFS_v1.zip":
            offset = partial.stat().st_size if partial.exists() else 0

            def receive(start):
                end = min(start + 24 * 2**20, size) - 1
                piece = partial.with_name(f"{partial.name}.{start}")
                length = end - start + 1
                command = [*curl, "--retry", "2", "--range", f"{start}-{end}",
                           "--max-filesize", str(length), "--output", str(piece), url]
                if not piece.exists() or piece.stat().st_size != length:
                    subprocess.run(command, check=True)
                if piece.stat().st_size != length:
                    raise ValueError(f"Wrong length for HDFS range {start}-{end}")
                return piece, command

            with ThreadPoolExecutor(max_workers=4) as ranges, partial.open("ab") as target:
                for piece, command in ranges.map(receive, range(offset, size, 24 * 2**20)):
                    with piece.open("rb") as stream:
                        shutil.copyfileobj(stream, target)
                    target.flush()
                    piece.unlink()
                    commands.append(command)
        else:
            command = [*curl, "--retry", "2", "--max-filesize", str(max(size, 1_000_000)),
                       "--output", str(partial), url]
            subprocess.run(command, check=True)
            commands.append(command)
    else:
        partial = file
    if partial.stat().st_size != size:
        raise ValueError(f"Unexpected size: {name}")
    with partial.open("rb") as stream:
        if algorithm == "git-sha1":
            digest = hashlib.sha1(f"blob {size}\0".encode() + stream.read()).hexdigest()
        else:
            digest = hashlib.file_digest(stream, algorithm).hexdigest()
    if digest != expected:
        raise ValueError(f"Checksum mismatch: {name}")
    if not cache_hit:
        partial.rename(file)
    print(f"Verified {name}: {size} bytes", flush=True)
    return {"path": str(file.relative_to(ROOT)), "url": url, "bytes": size,
            "checksum": f"{algorithm}:{digest}", "seconds": time.perf_counter() - start,
            "cache_hit": cache_hit, "commands": commands}

if __name__ == "__main__":
    started = time.perf_counter()
    total = sum(row[1] for row in FILES)
    if total > 550_000_000:
        raise SystemExit("Download cap exceeded")
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(acquire, FILES))
    with (ROOT / "provenance.json").open("x", encoding="utf-8") as stream:
        json.dump({"sbert_revision": REVISION, "total_bytes": total,
                   "elapsed_seconds": time.perf_counter() - started, "files": records}, stream, indent=2)
