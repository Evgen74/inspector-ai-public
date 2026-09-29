"""OCR core, orientation and full page recognition on synthetic pages (CPU engine; skipped without models)."""

from __future__ import annotations

import numpy as np
import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_common.geometry import bbox_iou
from inspector_docproc.bench.metrics import norm_relaxed
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.ocr.pipeline import ocr_image
from inspector_docproc.orientation import detect_orientation, rotate_image
from inspector_docproc.recognize import PageRecognizer
from inspector_docproc.testing import ink_bbox, make_pdf, make_scan_pdf, text_image

LINES = [
    (60, 90, "ПРОТОКОЛ ИСПЫТАНИЙ № 284", 16),
    (60, 130, "Шифр проекта АНО/150321/1-РД-ОВ1", 13),
    (60, 165, "Фактический класс бетона В25", 13),
    (60, 200, "Дата испытаний 20.02.2026 г.", 13),
    (60, 235, "Прочность образца 22,6 МПа", 13),
    (60, 270, "Испытательная лаборатория", 13),
]


@pytest.fixture(scope="module")
def page_image() -> np.ndarray:
    return text_image(LINES, dpi=200)[:, :, ::-1].copy()  # BGR like the pipeline


def test_ocr_reads_synthetic_lines_with_word_boxes(ocr_engine, page_image) -> None:
    lines, stats = ocr_image(ocr_engine, page_image)
    text = " ".join(ln.text for ln in lines if ln.score >= 0.5)
    for probe in ("ПРОТОКОЛ", "20.02.2026", "22,6", "Испытательная"):
        assert norm_relaxed(probe) in norm_relaxed(text), text
    assert stats.n_boxes >= len(LINES)
    for ln in lines:
        x0, y0, x1, y1 = ln.bbox
        for w in ln.words:  # word quads stay inside their line (1 px tolerance)
            assert w.quad[:, 0].min() >= x0 - 1 and w.quad[:, 0].max() <= x1 + 1
            assert w.quad[:, 1].min() >= y0 - 1 and w.quad[:, 1].max() <= y1 + 1


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_orientation_detects_quarter_turns(ocr_engine, page_image, turns) -> None:
    rotated = rotate_image(page_image, -turns)  # content turned clockwise by 90·turns
    assert detect_orientation(ocr_engine, rotated).content_rotation == 90 * turns


@pytest.mark.parametrize(
    ("rotate", "crop", "stored_upright"),
    [
        (0, None, True),
        (90, (20, 30, 822, 575), True),
        (270, None, True),
        (90, None, False),
        (180, None, False),
    ],
)
def test_scan_page_tokens_land_on_the_ink(tmp_path, ocr_engine, rotate, crop, stored_upright) -> None:
    """PageTokens of a rotated/cropped scan: schema-valid, located on the displayed ink.

    ``stored_upright``: the image is stored turned so that the page reads upright after /Rotate (real
    scans with /Rotate 270); otherwise /Rotate turns readable content and the orientation detector must
    report it as content rotation.
    """
    import pymupdf

    img = text_image(LINES, dpi=200)
    size = (595, 842)
    if stored_upright and rotate:
        img = np.ascontiguousarray(np.rot90(img, rotate // 90))  # CCW: /Rotate turns it back upright
        if rotate in (90, 270):
            size = (842, 595)
    path = make_scan_pdf(tmp_path / "scan.pdf", img, size=size, rotate=rotate, cropbox=crop)
    rec = PageRecognizer(RecognitionConfig(), ExecutionConfig(providers="cpu", threads=2), engine=ocr_engine)
    with pymupdf.open(path) as doc:
        out = rec.recognize_page(doc, 1, file_id="F9001", file_sha256="0" * 64)
        ink = ink_bbox(doc[0])
    assert validation_errors("page_tokens", out) == []
    assert out["page_class"] == "RASTER_SCAN" and out["text_source"] == "OCR"
    expected = 0 if stored_upright else rotate
    assert out["page"]["rotate"] == rotate and out["page"]["content_rotation"] == expected
    ocr = [t for t in out["tokens"] if t["source"] == "OCR"]
    assert len(ocr) >= 15
    union = [
        min(t["bbox"][0] for t in ocr),
        min(t["bbox"][1] for t in ocr),
        max(t["bbox"][2] for t in ocr),
        max(t["bbox"][3] for t in ocr),
    ]
    assert bbox_iou(union, ink) > 0.8, (union, ink)
    assert sum(t["angle"] == expected for t in ocr) >= 0.9 * len(ocr)
    for t in ocr:
        if t.get("corrected_by"):
            assert t["text_raw"] != t["text"]
    text = " ".join(line["text"] for line in out["lines"])
    assert norm_relaxed("ПРОТОКОЛ ИСПЫТАНИЙ") in norm_relaxed(text)


def test_vector_page_uses_the_text_layer(tmp_path) -> None:
    import pymupdf

    path = make_pdf(
        tmp_path / "v.pdf", [(60, 90 + 20 * i, t, 12) for i, (_, _, t, _) in enumerate(LINES * 2)], rotate=90
    )
    rec = PageRecognizer(RecognitionConfig(), ExecutionConfig(providers="cpu"))
    with pymupdf.open(path) as doc:
        out = rec.recognize_page(doc, 1, file_id="F9002", file_sha256="1" * 64)
    assert validation_errors("page_tokens", out) == []
    assert out["page_class"] == "VECTOR" and out["text_source"] == "TEXT_LAYER"
    assert all(t["source"] == "TEXT_LAYER" and t["conf"] == 1.0 and t["angle"] == 90 for t in out["tokens"])
    assert {line["text"] for line in out["lines"]} >= {"ПРОТОКОЛ ИСПЫТАНИЙ № 284"}
    assert "det_ms" not in out["timings_ms"]  # no OCR on a clean A4 text page


def test_ocr_region_returns_whole_page_coordinates(tmp_path, ocr_engine) -> None:
    """Region OCR (title blocks at 300 dpi, AG-02B): tokens in whole-page space on a rotated, cropped scan."""
    import pymupdf

    img = np.ascontiguousarray(np.rot90(text_image(LINES, dpi=200), 1))  # upright after /Rotate 90
    path = make_scan_pdf(tmp_path / "r.pdf", img, size=(842, 595), rotate=90, cropbox=(20, 30, 822, 575))
    rec = PageRecognizer(RecognitionConfig(), ExecutionConfig(providers="cpu", threads=2), engine=ocr_engine)
    region = [0.05, 0.05, 0.95, 0.40]
    with pymupdf.open(path) as doc:
        full = rec.recognize_page(doc, 1, file_id="F9003", file_sha256="2" * 64)
        out = rec.ocr_region(doc[0], region, dpi=300)
    assert out["render_dpi"] == 300 and not out["capped"] and len(out["tokens"]) >= 15
    for t in out["tokens"]:
        assert t["source"] == "OCR" and t["line_id"] is not None
        assert region[0] - 0.01 <= t["bbox"][0] <= t["bbox"][2] <= region[2] + 0.01
        assert region[1] - 0.01 <= t["bbox"][1] <= t["bbox"][3] <= region[3] + 0.01
    by_text = {t["text"]: t["bbox"] for t in full["tokens"]}
    matched = [bbox_iou(t["bbox"], by_text[t["text"]]) for t in out["tokens"] if t["text"] in by_text]
    assert len(matched) >= 0.8 * len(out["tokens"])
    assert np.median(matched) > 0.7, matched
    assert all(line["token_ids"] for line in out["lines"])
    with pytest.raises(ValueError):
        rec.ocr_region(None, [0.5, 0.5, 0.5, 0.9])
