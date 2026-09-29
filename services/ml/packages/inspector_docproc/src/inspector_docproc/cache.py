"""PageTokens cache keyed by file sha256 + pipeline version (97: compressed JSON, never page renders).

Layout: ``<cache_root>/tokens/<pipeline_version>/<sha[:2]>/<sha256>/p00001.json.gz``. Writes are atomic
(temp file + rename), so a crashed run resumes from the pages already written. A run directory gets
hard links (copies across file systems) under ``runs/<run_id>/tokens/<file_id>/``.
"""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import orjson

from inspector_common.paths import ensure_dir


def page_file_name(page_no: int) -> str:
    return f"p{page_no:05d}.json.gz"


def dumps_gz(doc: dict[str, Any]) -> bytes:
    return gzip.compress(orjson.dumps(doc), compresslevel=6, mtime=0)


def load_gz(path: Path) -> dict[str, Any]:
    return orjson.loads(gzip.decompress(path.read_bytes()))


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class TokenCache:
    def __init__(self, cache_root: Path, pipeline_version: str) -> None:
        self.root = cache_root / "tokens" / pipeline_version
        self.pipeline_version = pipeline_version

    def path(self, sha256: str, page_no: int) -> Path:
        return self.root / sha256[:2] / sha256 / page_file_name(page_no)

    def has(self, sha256: str, page_no: int) -> bool:
        return self.path(sha256, page_no).is_file()

    def get(self, sha256: str, page_no: int) -> dict[str, Any] | None:
        p = self.path(sha256, page_no)
        if not p.is_file():
            return None
        try:
            return load_gz(p)
        except (OSError, ValueError, EOFError):
            return None

    def put(self, sha256: str, page_no: int, doc: dict[str, Any]) -> Path:
        p = self.path(sha256, page_no)
        ensure_dir(p.parent)
        atomic_write(p, dumps_gz(doc))
        return p


def link_into(src: Path, dst: Path) -> None:
    """Hard-link a cached page into a run directory (copy when linking is impossible)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
