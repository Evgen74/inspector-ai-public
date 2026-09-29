"""SHA-256 helpers and the canonical hashes shared by every stage.

Definitions (golden vectors in packages/contracts/vectors/hashing.json):

- ``sha256_file``: lowercase hex of the file bytes (90 §3.3.6), streamed in 1 MiB chunks.
- ``canonical_json``: UTF-8 JSON with sorted keys, no insignificant whitespace, non-ASCII kept
  as is, string keys only, no NaN/Infinity. Floats use Python's shortest round-trip repr, which
  matches RFC 8785 (JCS) for magnitudes in [1e-6, 1e21); integers and strings always match JCS.
- ``input_manifest_hash``: sha256 over the object's manifest rows, each row as canonical JSON,
  sorted by ``file_id``, joined with ``\\n`` (93 §3.9, 97 §2.5).
- ``config_hash``: sha256 of the canonical JSON of the frozen run config.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1 << 20


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _check_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: non-string key {key!r} is not allowed in canonical JSON")
            _check_keys(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _check_keys(item, f"{path}[{index}]")


def canonical_json(value: Any) -> bytes:
    """Deterministic JSON bytes (see module docstring). Raises on NaN/Infinity and non-string keys."""
    _check_keys(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def input_manifest_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    """Hash of one object's manifest rows (order-independent)."""
    ordered = sorted(rows, key=lambda row: str(row["file_id"]))
    return sha256_bytes(b"\n".join(canonical_json(dict(row)) for row in ordered))


def config_hash(config: Mapping[str, Any]) -> str:
    return sha256_json(dict(config))


def short(digest: str, n: int = 12) -> str:
    """Display form of a digest (never used as an identifier)."""
    return digest[:n]
