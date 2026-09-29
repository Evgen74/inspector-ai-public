"""Recogniser batching (M1 speed task): width planning and skipped retries never change a reading.

The speed-up skips retry reads that cannot win (``pipeline._read_retries``). It is exact because (1) the
model is batch-invariant on the CPU provider: a crop's logits depend only on its padded width, not on the
batch size or its position; (2) the planned widths reproduce the RapidOCR batching bit for bit (checked here
against a verbatim copy of the pre-M1 ``Recognizer.__call__``); (3) with skipping on and off, every reading,
rotation and retry decision is the same. The slow test repeats (3) on real pages end to end (PageTokens).
"""

from __future__ import annotations

import math
import sys

import cv2
import numpy as np
import pytest

from inspector_docproc.config import OcrConfig
from inspector_docproc.ocr.engine import RecResult
from inspector_docproc.ocr.pipeline import OcrStats, detect_tiled, quad_size, recognize_crops, rotate_crop
from inspector_docproc.testing import text_image

LINES = [
    (40, 60, "ПРОТОКОЛ ИСПЫТАНИЙ № 284", 16),
    (40, 100, "Фактический класс бетона В25, W6, F150", 12),
    (40, 130, "7", 12),
    (80, 130, "13,9", 12),
    (140, 130, "Ст1", 12),
    (200, 130, "пом. 114", 12),
    (
        40,
        170,
        "Испытательное оборудование: пресс Matest C040PN132, свидетельство № 465529479 от 12.09.2025 г.",
        9,
    ),
    (40, 200, "ГОСТ 18105-2018", 11),
    (40, 230, "Т11", 10),
    (90, 230, "ø20", 10),
    (140, 230, "1", 10),
    (170, 230, "Изм.", 10),
    (40, 260, "Генеральный директор", 11),
    (40, 290, "Итого по разделу 3: 1079,9 м²", 11),
]


def _crops(engine) -> tuple[list[np.ndarray], list[bool]]:
    """Word and line crops of a synthetic page, plus turned copies that the cropper would call vertical."""
    img = np.ascontiguousarray(text_image(LINES, dpi=200)[:, :, ::-1])
    cfg = OcrConfig()
    quads = detect_tiled(engine.det_small, img, cfg, OcrStats())
    crops = [rotate_crop(img, q, cfg.vertical_ratio) for q in quads]
    vertical = [quad_size(q)[1] / max(quad_size(q)[0], 1.0) >= cfg.vertical_ratio for q in quads]
    turned = [np.ascontiguousarray(np.rot90(c, 1)) for c in crops[:8]]  # as if read top-to-bottom
    return crops + turned, vertical + [True] * len(turned)


def _reference_call(rec, crops: list[np.ndarray]) -> list[RecResult]:
    """The pre-M1 ``Recognizer.__call__`` (RapidOCR batching), kept verbatim as the oracle."""
    hgt = rec.cfg.rec_height
    base_ratio = 320 / 48
    ratios = [c.shape[1] / float(c.shape[0]) for c in crops]
    order = np.argsort(np.array(ratios))
    out: list[RecResult | None] = [None] * len(crops)
    n = rec.cfg.rec_batch
    for beg in range(0, len(crops), n):
        idx = [int(i) for i in order[beg : beg + n]]
        max_ratio = max([base_ratio, *(ratios[i] for i in idx)])
        img_w = int(hgt * max_ratio)
        batch = np.zeros((len(idx), 3, hgt, img_w), dtype=np.float32)
        resized_w: list[int] = []
        for k, i in enumerate(idx):
            crop = crops[i]
            if crop.ndim == 2:
                crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
            rw = max(min(img_w, math.ceil(hgt * ratios[i])), 1)
            resized = cv2.resize(crop, (rw, hgt)).astype(np.float32)
            batch[k, :, :, :rw] = (resized.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
            resized_w.append(rw)
        preds = rec._run(batch)
        px_per_step = img_w / float(preds.shape[1])
        idx_arr, prob_arr = preds.argmax(axis=2), preds.max(axis=2)
        for k, i in enumerate(idx):
            out[i] = rec._decode(idx_arr[k], prob_arr[k], px_per_step, resized_w[k])
    return [r if r is not None else RecResult("", 0.0) for r in out]


def _same(a: RecResult, b: RecResult) -> bool:
    return (a.text, a.score, a.char_pos, a.char_prob, a.step) == (
        b.text,
        b.score,
        b.char_pos,
        b.char_prob,
        b.step,
    )


def test_model_is_batch_invariant(ocr_engine) -> None:
    """Logits of a crop are bit-identical whether it is read alone, in a batch of 6 or in a batch of 18 (macOS arm64,
    the reference host). The x86-64 CPU kernels of ONNX Runtime block GEMMs by batch size, so on Linux the logits may
    differ in the last float digits; there the decoded characters (argmax) must still be identical."""
    crops, _ = _crops(ocr_engine)
    rng = np.random.default_rng(3)
    batch = np.zeros((18, 3, 48, 320), np.float32)
    for k, i in enumerate(rng.choice(len(crops), 18, replace=False)):
        c = crops[int(i)]
        rw = max(1, min(320, math.ceil(48 * c.shape[1] / c.shape[0])))
        batch[k, :, :, :rw] = (
            cv2.resize(c, (rw, 48)).astype(np.float32).transpose(2, 0, 1) / 255.0 - 0.5
        ) / 0.5
    pool = ocr_engine.rec.pool
    big = pool.run_cpu(batch)
    six = np.concatenate([pool.run_cpu(batch[j : j + 6]) for j in range(0, 18, 6)])
    alone = np.concatenate([pool.run_cpu(batch[j : j + 1]) for j in range(18)])
    if sys.platform == "darwin":
        assert np.array_equal(big, six) and np.array_equal(big, alone)
    else:
        assert np.allclose(big, six, rtol=1e-4, atol=1e-6) and np.allclose(big, alone, rtol=1e-4, atol=1e-6)
        assert np.array_equal(big.argmax(-1), six.argmax(-1)) and np.array_equal(
            big.argmax(-1), alone.argmax(-1)
        )


def test_planned_batching_equals_rapidocr_batching(ocr_engine) -> None:
    crops, _ = _crops(ocr_engine)
    rec = ocr_engine.rec
    assert len({w for w in rec.plan_widths([c.shape[:2] for c in crops])}) > 2  # short and long crops
    ref = _reference_call(rec, crops)
    got = rec(crops)
    assert all(_same(a, b) for a, b in zip(ref, got, strict=True))
    # any subset read with the widths planned for the whole set gets exactly the full-set readings
    widths = rec.plan_widths([c.shape[:2] for c in crops])
    sub = list(range(0, len(crops), 3))
    part = rec([crops[i] for i in sub], widths=[widths[i] for i in sub])
    assert all(_same(ref[i], r) for i, r in zip(sub, part, strict=True))
    with pytest.raises(ValueError):
        rec(crops[:2], widths=[320])


def test_skipping_futile_retries_changes_nothing(ocr_engine) -> None:
    crops, vertical = _crops(ocr_engine)
    cfg = OcrConfig()
    quads = [np.zeros((4, 2), np.float32)] * len(crops)
    results = {}
    for skip in (False, True):
        ocr_engine.skip_futile_retries = skip
        try:
            stats = OcrStats()
            results[skip] = (recognize_crops(ocr_engine, quads, crops, vertical, cfg, stats), stats)
        finally:
            ocr_engine.skip_futile_retries = True
    (full, s_full), (fast, s_fast) = results[False], results[True]
    assert [(r.via, r.rot_k) for r in full] == [(r.via, r.rot_k) for r in fast]
    assert all(_same(a.res, b.res) for a, b in zip(full, fast, strict=True))
    assert (s_full.n_retry180, s_full.n_unrotated) == (s_fast.n_retry180, s_fast.n_unrotated)
    assert s_full.n_retry_skipped == 0 and s_fast.n_retry_skipped > 0


def _comparable(doc: dict) -> dict:
    """PageTokens without run-dependent fields (timings, stage seconds, skipped-retry counter)."""
    out = {k: v for k, v in doc.items() if k != "timings_ms"}
    ocr = dict((out.get("ext") or {}).get("ocr") or {})
    for k in ("det_s", "rec_s", "n_retry_skipped"):
        ocr.pop(k, None)
    if ocr:
        out["ext"] = {**out["ext"], "ocr": ocr}
    return out


@pytest.mark.slow
@pytest.mark.data
@pytest.mark.parametrize("page_id", ["B04", "B06", "D03", "C04"])
def test_real_pages_identical_with_and_without_skipping(page_id: str) -> None:
    """End to end on benchmark pages (rotated scan, seals, outlined text, table scan): same PageTokens."""
    import pymupdf

    from inspector_common.settings import Settings
    from inspector_docproc.bench.suites import load_benchmark
    from inspector_docproc.config import ExecutionConfig, RecognitionConfig
    from inspector_docproc.recognize import PageRecognizer
    from inspector_docproc.testing import models_available

    paths = Settings().paths
    if not paths.has_package() or not models_available():
        pytest.skip("organizer data or OCR models not found")
    entry = next(e for e in load_benchmark()["pages"] if e["id"] == page_id)
    rec = PageRecognizer(RecognitionConfig(), ExecutionConfig(providers="cpu", threads=2))
    docs = {}
    with pymupdf.open(paths.document_path(entry["relative_path"])) as doc:
        for skip in (False, True):
            rec.engine.skip_futile_retries = skip
            docs[skip] = rec.recognize_page(
                doc, entry["pdf_page_number"], file_id=entry["file_id"], file_sha256=entry["file_sha256"]
            )
    rec.close()
    assert _comparable(docs[False]) == _comparable(docs[True])
