"""TokenStore: PageTokens and region OCR by (file_id, page) for AG-02B/AG-02C (synthetic files, CPU)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_common.paths import DataPaths
from inspector_docproc.api import TokenStore, UnknownFileError, load_page_tokens
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.inputs import FileJob
from inspector_docproc.runner import run_recognition
from inspector_docproc.testing import make_pdf, make_scan_pdf, make_zone_pdf, models_available, text_image

TEXT = [(60, 90 + 18 * i, f"Раздел {i} проектной документации", 11) for i in range(10)]


def _paths(tmp_path: Path) -> DataPaths:
    return DataPaths(tmp_path / "data", tmp_path / "models", tmp_path / "cache", tmp_path / "runs")


@pytest.fixture()
def run(tmp_path: Path) -> tuple[Path, Path, str]:
    import pymupdf

    single = make_pdf(tmp_path / "one.pdf", TEXT)
    out = pymupdf.open()
    for _ in range(2):
        with pymupdf.open(single) as d:
            out.insert_pdf(d)
    pdf = tmp_path / "doc.pdf"
    out.save(pdf)
    job = FileJob("F9200", "OBJ-TEST", "PD", "doc.pdf", pdf, "d" * 64, 2)
    run_dir = tmp_path / "runs" / "r1"
    run_recognition(
        [job], pages_spec="1", cfg=RecognitionConfig(), exec_cfg=ExecutionConfig(providers="cpu", workers=1),
        run_dir=run_dir, cache_root=tmp_path / "cache",
    )  # fmt: skip
    return run_dir, pdf, "d" * 64


@pytest.mark.skipif(not models_available(), reason="OCR models not found (make fetch-models)")
def test_page_from_run_directory(run, tmp_path) -> None:
    run_dir, pdf, sha = run
    with TokenStore.for_run(run_dir, paths=_paths(tmp_path)) as store:
        store.register("F9200", pdf, sha, object_id="OBJ-TEST")
        assert store.pages("F9200") == [1] and store.pages("F0000") == []
        doc = store.page("F9200", 1)
        assert doc is not None and validation_errors("page_tokens", doc) == []
        assert doc == load_page_tokens(run_dir, "F9200", 1)
        words = store.words("F9200", 1)
        assert [w["text"] for w in words][:3] == ["Раздел", "0", "проектной"]
        assert store.pipeline_version() == store.tokens_index()["pipeline_version"]
        assert store.page("F9200", 2) is None  # not in the run, not cached, on_miss="none"


@pytest.mark.skipif(not models_available(), reason="OCR models not found (make fetch-models)")
def test_cache_fallback_and_recognize_on_miss(run, tmp_path) -> None:
    run_dir, pdf, sha = run
    pv = TokenStore.for_run(run_dir).pipeline_version()
    store = TokenStore(paths=_paths(tmp_path), pipeline_version=pv, on_miss="recognize")
    store.register("F9200", pdf, sha, object_id="OBJ-TEST")
    assert store.page("F9200", 1)["page_no"] == 1  # from the cache (no run directory)
    fresh = store.page("F9200", 2)  # recognized now, then cached
    assert fresh is not None and fresh["page_no"] == 2 and validation_errors("page_tokens", fresh) == []
    other = TokenStore(paths=_paths(tmp_path), pipeline_version=pv)
    other.register("F9200", pdf, sha)
    assert other.page("F9200", 2) == fresh  # the recognized page was cached under the same version
    with pytest.raises(UnknownFileError):
        store.file("F0000")
    store.close()


def test_words_drop_abstain_and_zone_tokens() -> None:
    store = TokenStore()
    doc = {
        "tokens": [
            {"id": 0, "text": "a", "quality_flag": "OK", "source": "TEXT_LAYER"},
            {"id": 1, "text": "b", "quality_flag": "LOW_QUALITY", "source": "OCR"},
            {"id": 2, "text": "c", "quality_flag": "ABSTAIN", "source": "OCR"},
            {"id": 3, "text": "d", "quality_flag": "OK", "source": "OCR"},
            {"id": 4, "text": "e", "quality_flag": "OK", "source": "OCR"},
        ],
        "zones": [{"kind": "QR", "attrs": {"token_ids": [3]}}, {"kind": "SEAL", "attrs": {"token_ids": [4]}}],
    }
    store.page = lambda f, p: doc  # type: ignore[method-assign]
    assert [w["text"] for w in store.words("F1", 1)] == ["a", "b", "e"]
    assert [w["text"] for w in store.words("F1", 1, min_quality="OK")] == ["a", "e"]
    assert [w["text"] for w in store.words("F1", 1, exclude_zone_kinds={"QR", "SEAL"})] == ["a", "b"]
    assert [w["text"] for w in store.words("F1", 1, sources={"OCR"})] == ["b", "e"]
    assert [z["kind"] for z in store.zones("F1", 1, kinds={"SEAL"})] == ["SEAL"]


@pytest.mark.skipif(not models_available(), reason="OCR models not found")
def test_ocr_region_by_file_and_page(tmp_path) -> None:
    img = np.ascontiguousarray(
        text_image([(60, 90, "ПРОТОКОЛ ИСПЫТАНИЙ № 284", 16), (60, 400, "Инженер", 13)], dpi=200)
    )
    pdf = make_scan_pdf(tmp_path / "s.pdf", img)
    with TokenStore(paths=_paths(tmp_path)) as store:
        store.register("F9201", pdf, "e" * 64)
        res = store.ocr_region("F9201", 1, [0.0, 0.05, 1.0, 0.2], dpi=300)
        assert res["render_dpi"] == 300
        assert "ПРОТОКОЛ" in " ".join(t["text"] for t in res["tokens"])
        assert all(0.05 <= t["bbox"][1] <= t["bbox"][3] <= 0.2 for t in res["tokens"])


@pytest.mark.skipif(not models_available(), reason="OCR models not found")
def test_zones_through_the_store(tmp_path) -> None:
    pdf, _ = make_zone_pdf(tmp_path / "z.pdf", dpi=100)
    with TokenStore(paths=_paths(tmp_path), on_miss="recognize") as store:
        store.register("F9202", pdf, "f" * 64)
        kinds = sorted(z["kind"] for z in store.zones("F9202", 1))
        assert "QR" in kinds and "SEAL" in kinds, kinds
        payloads = [z["attrs"].get("payload") for z in store.zones("F9202", 1, kinds={"QR"})]
        assert "https://example.invalid/sign/7" in payloads
