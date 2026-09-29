"""Model registry: manifest roles, sha256 verification, provider resolution."""

from __future__ import annotations

import hashlib
import json

import pytest

from inspector_common.errors import InspectorError
from inspector_docproc.models import (
    ROLE_DET_FALLBACK,
    ROLE_DET_PRIMARY,
    ROLE_REC_PRIMARY,
    ModelRegistry,
    resolve_provider_mode,
)


def _manifest(tmp_path, payload: bytes, sha: str | None = None) -> ModelRegistry:
    models = tmp_path / "models" / "ocr"
    models.mkdir(parents=True)
    (models / "fake_det.onnx").write_bytes(payload)
    entry = {
        "path": "ocr/fake_det.onnx",
        "size_bytes": len(payload),
        "sha256": sha or hashlib.sha256(payload).hexdigest(),
        "role": ROLE_DET_PRIMARY,
        "required": True,
    }
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"schema_version": 1, "models_root": "models", "files": [entry]}))
    return ModelRegistry(man, tmp_path / "models", tmp_path / "cache")


def test_real_manifest_has_the_three_runtime_roles() -> None:
    reg = ModelRegistry()
    names = {reg.by_role(r).name for r in (ROLE_DET_PRIMARY, ROLE_DET_FALLBACK, ROLE_REC_PRIMARY)}
    assert names == {
        "PP-OCRv6_det_small.onnx",
        "PP-OCRv6_det_medium.onnx",
        "cyrillic_PP-OCRv5_rec_mobile.onnx",
    }


def test_verify_accepts_matching_and_rejects_modified_files(tmp_path) -> None:
    reg = _manifest(tmp_path, b"model-bytes")
    reg.verify(reg.by_role(ROLE_DET_PRIMARY))
    bad = _manifest(tmp_path / "b", b"model-bytes", sha="0" * 64)
    with pytest.raises(InspectorError) as exc:
        bad.verify(bad.by_role(ROLE_DET_PRIMARY))
    assert exc.value.code == "MODEL_ARTIFACT_INTEGRITY_FAILED"


def test_missing_model_and_role(tmp_path) -> None:
    reg = _manifest(tmp_path, b"x")
    (tmp_path / "models" / "ocr" / "fake_det.onnx").unlink()
    with pytest.raises(InspectorError) as exc:
        reg.verify(reg.by_role(ROLE_DET_PRIMARY))
    assert exc.value.code == "OCR_MODEL_MISSING"
    with pytest.raises(InspectorError):
        reg.by_role(ROLE_REC_PRIMARY)


def test_provider_resolution() -> None:
    assert resolve_provider_mode("cpu") == "cpu"
    assert resolve_provider_mode("auto") in ("cpu", "coreml", "cuda")
    with pytest.raises(ValueError):
        resolve_provider_mode("tpu")
