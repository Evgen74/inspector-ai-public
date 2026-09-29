"""Local caches under ``.cache/registry/`` (git-ignored), keyed by path + size + mtime.

- ``sha256``: lazily computed file digests (the organizer manifest is the reference).
- ``probe``: versioned JSON payloads of cheap probes (PDF page counts and first-page hashes,
  archive listings). A payload is reused only when path, size, mtime_ns and the probe version match.

SQLite (stdlib) in WAL mode, so concurrent CLI runs do not corrupt the cache. The cache is an
accelerator only: deleting it never changes a result.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from inspector_common.paths import ensure_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sha256 (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS probe (
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    version TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (kind, path)
);
"""


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class RegistryCache:
    """Thread-safe (one connection guarded by a lock); ``RegistryCache(None)`` is a no-op cache."""

    def __init__(self, db_path: Path | None) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self.hits = 0
        self.misses = 0
        if db_path is not None:
            ensure_dir(db_path.parent)
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @classmethod
    def at(cls, cache_root: Path) -> RegistryCache:
        return cls(cache_root / "registry" / "registry_cache.sqlite")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # sha256 -------------------------------------------------------------------------------------

    def get_sha256(self, path: Path, size: int, mtime_ns: int) -> str | None:
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT sha256 FROM sha256 WHERE path = ? AND size = ? AND mtime_ns = ?",
                (str(path), size, mtime_ns),
            ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return str(row[0])

    def put_sha256(self, path: Path, size: int, mtime_ns: int, digest: str) -> None:
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sha256 (path, size, mtime_ns, sha256, computed_at) VALUES (?, ?, ?, ?, ?)",
                (str(path), size, mtime_ns, digest, _now()),
            )
            self._conn.commit()

    # probes -------------------------------------------------------------------------------------

    def get_probe(
        self, kind: str, path: Path, size: int, mtime_ns: int, version: str
    ) -> dict[str, Any] | None:
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM probe WHERE kind = ? AND path = ? AND size = ? AND mtime_ns = ? AND version = ?",
                (kind, str(path), size, mtime_ns, version),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put_probe(
        self, kind: str, path: Path, size: int, mtime_ns: int, version: str, payload: dict[str, Any]
    ) -> None:
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO probe (kind, path, size, mtime_ns, version, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (kind, str(path), size, mtime_ns, version, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
