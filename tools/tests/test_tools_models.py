from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vm = _load("verify_models", "tools/models/verify_models.py")


@pytest.fixture()
def fake_models(tmp_path: Path) -> Path:
    root = tmp_path / ".models"
    (root / "ocr").mkdir(parents=True)
    (root / "ocr" / "PP-OCRv6_det_small.onnx").write_bytes(b"det")
    (root / "ocr" / "cyrillic_PP-OCRv5_rec_mobile.onnx").write_bytes(b"rec")
    (root / "ocr" / "PP-OCRv6_rec_tiny.onnx").write_bytes(b"candidate")
    snap = root / "hf" / "models--intfloat--multilingual-e5-small"
    (snap / "blobs").mkdir(parents=True)
    (snap / "snapshots" / "rev").mkdir(parents=True)
    (snap / "blobs" / "abc").write_text("{}", encoding="utf-8")
    (snap / "snapshots" / "rev" / "config.json").symlink_to("../../blobs/abc")
    (snap / "blobs" / "abc.lock").write_text("", encoding="utf-8")
    return root


def test_update_then_verify_roundtrip(fake_models: Path, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest_path), "--update"]) == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_path = {f["path"]: f for f in manifest["files"]}
    assert set(by_path) == {
        "ocr/PP-OCRv6_det_small.onnx",
        "ocr/cyrillic_PP-OCRv5_rec_mobile.onnx",
        "ocr/PP-OCRv6_rec_tiny.onnx",
        "hf/models--intfloat--multilingual-e5-small/blobs/abc",
    }
    assert by_path["ocr/PP-OCRv6_det_small.onnx"]["required"] is True
    assert by_path["ocr/PP-OCRv6_rec_tiny.onnx"]["role"] == "benchmark_candidate"
    assert by_path["hf/models--intfloat--multilingual-e5-small/blobs/abc"]["aliases"] == [
        "hf/models--intfloat--multilingual-e5-small/snapshots/rev/config.json"
    ]
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest_path), "--all"]) == 0


def test_tampered_or_missing_model_fails(fake_models: Path, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    vm.main(["--models-root", str(fake_models), "--manifest", str(manifest_path), "--update"])
    (fake_models / "ocr" / "PP-OCRv6_det_small.onnx").write_bytes(b"DET")  # same size, other bytes
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest_path), "--quick"]) == 0
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest_path)]) == 1
    (fake_models / "ocr" / "PP-OCRv6_det_small.onnx").unlink()
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest_path), "--quick"]) == 1


def test_committed_manifest_shape() -> None:
    manifest = json.loads((REPO / "tools" / "models" / "manifest.json").read_text(encoding="utf-8"))
    required = {f["path"] for f in manifest["files"] if f["required"]}
    for name in (
        "ocr/PP-OCRv6_det_small.onnx",
        "ocr/PP-OCRv6_det_medium.onnx",
        "ocr/cyrillic_PP-OCRv5_rec_mobile.onnx",
    ):
        assert name in required
    by_path = {f["path"]: f for f in manifest["files"]}
    # sha256 prefixes recorded in docs/analysis/96 §16
    assert by_path["ocr/PP-OCRv6_det_small.onnx"]["sha256"].startswith("090f04ab")
    assert by_path["ocr/PP-OCRv6_det_medium.onnx"]["sha256"].startswith("92078b73")
    e5_aliases = [
        a for f in manifest["files"] if f["role"] == "embedder_e5_small" for a in f.get("aliases", [])
    ]
    assert any(a.endswith("/model.safetensors") for a in e5_aliases)
    assert any(a.endswith("/tokenizer.json") for a in e5_aliases)


@pytest.mark.slow
def test_real_models_match_manifest_quick() -> None:
    if not (REPO / ".models" / "hf").is_dir():  # a partial install (OCR models only, `make fetch-models`)
        pytest.skip("full .models/ (with the e5 embedder) not present")
    assert vm.main(["--quick", "--all"]) == 0


@pytest.mark.slow
def test_real_models_match_manifest_full_sha256() -> None:
    if not (REPO / ".models" / "hf").is_dir():  # a partial install (OCR models only, `make fetch-models`)
        pytest.skip("full .models/ (with the e5 embedder) not present")
    assert vm.main(["--all"]) == 0


def test_ocr_only_verification_ignores_the_embedder(fake_models: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest), "--update"]) == 0
    for hf in (fake_models / "hf").rglob("*"):  # a machine without the e5 embedder
        if hf.is_file() or hf.is_symlink():
            hf.unlink()
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest)]) == 1
    assert vm.main(["--models-root", str(fake_models), "--manifest", str(manifest), "--ocr-only"]) == 0


def test_fetch_sources_cover_exactly_the_required_ocr_models() -> None:
    fm = _load("fetch_models", "tools/models/fetch_models.py")
    manifest = json.loads((REPO / "tools" / "models" / "manifest.json").read_text(encoding="utf-8"))
    required_ocr = {
        Path(f["path"]).name for f in manifest["files"] if f["path"].startswith("ocr/") and f["required"]
    }
    assert set(fm.SOURCES) == required_ocr
    assert all(url.startswith("https://") and url.endswith(name) for name, url in fm.SOURCES.items())


def test_fetch_accepts_only_a_file_that_matches_the_manifest(tmp_path: Path, monkeypatch) -> None:
    import hashlib
    import io

    fm = _load("fetch_models", "tools/models/fetch_models.py")
    payload = b"onnx-bytes"
    entry = {
        "path": "ocr/PP-OCRv6_det_small.onnx",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "required": True,
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": [entry]}), encoding="utf-8")
    served = {"body": payload}
    monkeypatch.setattr(fm.urllib.request, "urlopen", lambda url, timeout=0: io.BytesIO(served["body"]))
    monkeypatch.setattr(
        fm, "SOURCES", {"PP-OCRv6_det_small.onnx": "https://example.invalid/PP-OCRv6_det_small.onnx"}
    )
    root = tmp_path / "models"
    assert fm.main(["--manifest", str(manifest), "--models-root", str(root)]) == 0
    assert (root / entry["path"]).read_bytes() == payload
    (root / entry["path"]).unlink()
    served["body"] = b"tampered!!"  # same length, other bytes: must not land in .models
    assert fm.main(["--manifest", str(manifest), "--models-root", str(root)]) == 1
    assert not (root / entry["path"]).exists() and not list((root / "ocr").glob("*.part"))
