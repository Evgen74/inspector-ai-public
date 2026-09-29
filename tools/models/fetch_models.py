#!/usr/bin/env python3
"""Download the three required OCR models into .models/ocr and verify them against tools/models/manifest.json.

    python tools/models/fetch_models.py                 # fetch what is missing or damaged
    python tools/models/fetch_models.py --models-root /data/models

This is a developer/installation tool, NOT product code: the running product never touches the network
(CLAUDE.md rule 6). The files are the public PP-OCR ONNX exports published by the RapidOCR project at the tag
that ``rapidocr`` 3.9.x pins (its ``default_models.yaml``); a downloaded file is accepted only when its size
and sha256 equal the manifest entry, so a wrong or tampered file can never enter ``.models/``.

Only the OCR files (detector small + medium, Cyrillic recogniser) are fetched: they are all the recognition
pipeline needs. The e5 embedder is pinned in the manifest as well but is not fetched here (Hugging Face
snapshot, ~0.5 GB): ``verify_models.py`` reports it missing, and only the hypothesis package uses it.

Stdlib only. Exit 0 = all OCR models present and verified, 1 = download or verification failed, 2 = usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).resolve().with_name("manifest.json")
DEFAULT_MODELS_ROOT = REPO_ROOT / ".models"

BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx"
# manifest file name → download URL (public, versioned by tag; the sha256 in the manifest is the authority)
SOURCES = {
    "PP-OCRv6_det_small.onnx": f"{BASE}/PP-OCRv6/det/PP-OCRv6_det_small.onnx",
    "PP-OCRv6_det_medium.onnx": f"{BASE}/PP-OCRv6/det/PP-OCRv6_det_medium.onnx",
    "cyrillic_PP-OCRv5_rec_mobile.onnx": f"{BASE}/PP-OCRv5/rec/cyrillic_PP-OCRv5_rec_mobile.onnx",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def is_valid(path: Path, size: int, sha256: str) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256_file(path) == sha256


def download(url: str, dest: Path, size: int, sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".part", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=120) as resp:
            shutil.copyfileobj(resp, out, 1 << 20)
        if not is_valid(tmp, size, sha256):
            raise RuntimeError(f"{dest.name}: размер или sha256 скачанного файла не совпадает с манифестом")
        os.replace(tmp, dest)  # atomic: a half-written file never carries the final name
    finally:
        tmp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--models-root", type=Path, default=Path(os.environ.get("INSPECTOR_MODELS_ROOT", DEFAULT_MODELS_ROOT))
    )
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries = {Path(f["path"]).name: f for f in manifest["files"] if f["path"].startswith("ocr/")}
    failed = 0
    for name, url in SOURCES.items():
        entry = entries.get(name)
        if entry is None:
            print(f"{name}: нет в манифесте", file=sys.stderr)
            failed += 1
            continue
        dest = args.models_root / entry["path"]
        if is_valid(dest, int(entry["size_bytes"]), str(entry["sha256"])):
            print(f"ok       {entry['path']}")
            continue
        print(f"загрузка {entry['path']} ({int(entry['size_bytes']) / 1e6:.1f} МБ) …", flush=True)
        try:
            download(url, dest, int(entry["size_bytes"]), str(entry["sha256"]))
        except (OSError, RuntimeError) as exc:
            print(f"ОШИБКА {name}: {exc}", file=sys.stderr)
            failed += 1
        else:
            print(f"ok       {entry['path']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
