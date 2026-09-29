from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from inspector_common.hashing import (
    canonical_json,
    config_hash,
    input_manifest_hash,
    sha256_bytes,
    sha256_file,
    sha256_json,
)
from inspector_common.paths import contracts_dir

VECTORS = json.loads((contracts_dir() / "vectors" / "hashing.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["sha256_bytes"])
def test_sha256_bytes_vectors(case: dict) -> None:
    assert sha256_bytes(case["input_utf8"].encode("utf-8")) == case["sha256"]


def test_sha256_file_streams_in_chunks(tmp_path: Path) -> None:
    data = b"x" * (3 * 1024 * 1024 + 17)
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    assert sha256_file(path, chunk_size=1 << 20) == sha256_bytes(data)


@pytest.mark.parametrize("case", VECTORS["canonical_json"])
def test_canonical_json_vectors(case: dict) -> None:
    assert canonical_json(case["input"]).decode("utf-8") == case["canonical"]
    assert sha256_json(case["input"]) == case["sha256"]


def test_canonical_json_rejects_nan_and_non_string_keys() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": math.nan})
    with pytest.raises(TypeError):
        canonical_json({1: "a"})


@pytest.mark.parametrize("case", VECTORS["input_manifest_hash"])
def test_input_manifest_hash_vectors_and_order_independence(case: dict) -> None:
    rows = case["rows"]
    assert input_manifest_hash(rows) == case["expected"]
    assert input_manifest_hash(list(reversed(rows))) == case["expected"]
    changed = [dict(rows[0], pdf_pages=rows[0]["pdf_pages"] + 1), rows[1]]
    assert input_manifest_hash(changed) != case["expected"]


def test_config_hash_is_key_order_independent() -> None:
    assert config_hash({"a": 1, "b": {"x": 0.9, "y": [1, 2]}}) == config_hash(
        {"b": {"y": [1, 2], "x": 0.9}, "a": 1}
    )
