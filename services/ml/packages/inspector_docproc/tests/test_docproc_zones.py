"""Zones (R-10): seals, handwriting and QR codes on synthetic scans; token flags; PageTokens contract."""

from __future__ import annotations

import numpy as np
import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_docproc.bench.metrics import box_iou, score_zones
from inspector_docproc.config import ExecutionConfig, RecognitionConfig, ZoneConfig
from inspector_docproc.recognize import PageRecognizer
from inspector_docproc.testing import make_zone_pdf, text_image, zone_page_image
from inspector_docproc.zones import Zone, assign_tokens, colour_ink_mask, detect_zones, qr_from_images

CFG = ZoneConfig()


def _bgr(rgb: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _best(zones: list[Zone], kind: str, box: list[float]) -> float:
    return max((box_iou(z.bbox, box) for z in zones if z.kind == kind), default=0.0)


def test_detects_seal_signature_and_printed_qr() -> None:
    img, boxes = zone_page_image(dpi=150)
    zones, diag = detect_zones(_bgr(img), 150, [], CFG)
    assert _best(zones, "SEAL", boxes["seal"]) >= 0.6, [(z.kind, z.bbox) for z in zones]
    assert _best(zones, "HANDWRITING", boxes["signature"]) >= 0.3, [(z.kind, z.bbox) for z in zones]
    qr = [z for z in zones if z.kind == "QR"]
    assert len(qr) == 1 and box_iou(qr[0].bbox, boxes["qr"]) >= 0.6
    assert qr[0].attrs.get("payload") == "https://example.invalid/doc/42"
    assert sum(z.kind == "SEAL" for z in zones) == 1  # the inner ring is not a second seal
    sig = [z for z in zones if z.kind == "HANDWRITING"]
    assert all(z.attrs["subkind"] == "SIGNATURE" for z in sig)
    assert diag["mask"].shape[0] == pytest.approx(img.shape[0] * 100 / 150, abs=1)


def test_black_text_page_has_no_zones() -> None:
    img = text_image(
        [(60, 90 + 30 * i, f"Строка текста номер {i} класс В25", 13) for i in range(20)], dpi=150
    )
    zones, diag = detect_zones(_bgr(img), 150, [], CFG)
    assert zones == [] and diag["colour_share"] == 0.0


def test_colour_mask_keeps_thin_light_blue_strokes() -> None:
    """Blue CAD signatures render as thin anti-aliased light-blue strokes (V = 255): they are ink."""
    img = np.full((60, 60, 3), 255, np.uint8)
    img[30, 5:55] = (255, 200, 170)  # BGR light blue line
    assert colour_ink_mask(img, CFG)[30, 30] == 255
    img[40, 5:55] = (120, 120, 120)  # grey is not colour ink
    assert colour_ink_mask(img, CFG)[40, 30] == 0


def test_vector_sheet_handwriting_only_in_title_block() -> None:
    """On drawing sheets colour line work (valves, pipes) outside the title block is not handwriting."""
    img, _boxes = zone_page_image(dpi=150)
    zones, _ = detect_zones(_bgr(img), 150, [], CFG, vector_sheet=True)
    assert not any(z.kind == "HANDWRITING" for z in zones)  # the signature is mid-page on this A4


def test_handwritten_tokens_abstain_printed_tokens_keep_flags() -> None:
    zone = Zone("HANDWRITING", [0.1, 0.1, 0.5, 0.5], 0.8, {"subkind": "SIGNATURE"})
    colour = np.zeros((100, 100), np.uint8)
    dark = np.zeros((100, 100), np.uint8)
    colour[20:30, 20:30] = 255  # a blue-ink token
    dark[35:45, 20:30] = 255  # a black printed token under the signature
    colour[36:38, 20:30] = 255  # crossed by a blue stroke
    toks = [
        {
            "id": 0,
            "text": "Сд",
            "bbox": [0.2, 0.2, 0.3, 0.3],
            "conf": 0.62,
            "source": "OCR",
            "quality_flag": "LOW_QUALITY",
        },
        {
            "id": 1,
            "text": "подпись",
            "bbox": [0.2, 0.35, 0.3, 0.45],
            "conf": 0.7,
            "source": "OCR",
            "quality_flag": "LOW_QUALITY",
        },
        {
            "id": 2,
            "text": "04",
            "bbox": [0.21, 0.21, 0.29, 0.29],
            "conf": 0.97,
            "source": "OCR",
            "quality_flag": "OK",
        },
        {
            "id": 3,
            "text": "Лист",
            "bbox": [0.7, 0.7, 0.8, 0.8],
            "conf": 0.9,
            "source": "OCR",
            "quality_flag": "OK",
        },
    ]
    counts = assign_tokens([zone], toks, colour, dark, CFG)
    assert zone.attrs["token_ids"] == [0, 1, 2]
    assert [t["quality_flag"] for t in toks] == ["ABSTAIN", "LOW_QUALITY", "OK", "OK"]
    assert counts == {"tokens_in_zones": 3, "tokens_abstained": 1, "tokens_under_seal": 0}


def test_qr_from_embedded_image_is_decoded(tmp_path) -> None:
    import pymupdf

    path, boxes = make_zone_pdf(tmp_path / "z.pdf", dpi=100)
    with pymupdf.open(path) as doc:
        found = qr_from_images(doc[0], CFG)
    assert len(found) == 1
    assert box_iou(found[0].bbox, boxes["qr_image"]) >= 0.9
    assert found[0].attrs["payload"] == "https://example.invalid/sign/7"
    assert found[0].attrs["method"] == "embedded_image"


def test_score_zones_counts_hits_and_false_alarms() -> None:
    gt = [{"type": "SEAL_ROUND", "bbox_norm": [0.1, 0.1, 0.3, 0.3]},
          {"type": "HANDWRITING_SIGNATURE", "bbox_norm": [0.5, 0.5, 0.6, 0.55]}]  # fmt: skip
    pred = [
        {"kind": "SEAL", "bbox": [0.11, 0.1, 0.3, 0.31]},
        {"kind": "HANDWRITING", "bbox": [0.8, 0.8, 0.9, 0.9]},
    ]
    res = score_zones(pred, gt)
    assert res["SEAL"] == {"n_gt": 1, "hit": 1, "covered": 1, "n_pred": 1, "false_alarm": 0}
    assert res["HANDWRITING"] == {"n_gt": 1, "hit": 0, "covered": 0, "n_pred": 1, "false_alarm": 1}


def test_page_tokens_carry_zones(tmp_path, ocr_engine) -> None:
    """Production page path: zones in the contract, tokens listed, warnings, QR payloads."""
    import pymupdf

    path, _boxes = make_zone_pdf(tmp_path / "z.pdf", dpi=150)
    rec = PageRecognizer(RecognitionConfig(), ExecutionConfig(providers="cpu", threads=2), engine=ocr_engine)
    with pymupdf.open(path) as doc:
        out = rec.recognize_page(doc, 1, file_id="F9101", file_sha256="3" * 64)
    assert validation_errors("page_tokens", out) == []
    kinds = sorted(z["kind"] for z in out["zones"])
    assert kinds.count("SEAL") == 1 and kinds.count("QR") == 2 and "HANDWRITING" in kinds, kinds
    payloads = {z["attrs"].get("payload") for z in out["zones"] if z["kind"] == "QR"}
    assert payloads == {"https://example.invalid/doc/42", "https://example.invalid/sign/7"}
    assert {"HANDWRITING_ZONES"} <= set(out["warnings"])
    assert all(z["source"] == "AUTO" and "token_ids" in z["attrs"] for z in out["zones"])
    by_kind = {z["kind"]: z for z in out["zones"]}
    assert (
        by_kind["HANDWRITING"]["quality_flag"] == "ABSTAIN"
        and by_kind["SEAL"]["quality_flag"] == "LOW_QUALITY"
    )
    assert out["timings_ms"]["zones_ms"] > 0
    assert out["ext"]["zones"]["n"] == len(out["zones"])
    # the printed text is still read and never ABSTAINed by a zone
    text = " ".join(t["text"] for t in out["tokens"] if t["quality_flag"] != "ABSTAIN")
    assert "ПРОТОКОЛ" in text and "Инженер" in text


def test_stamp_page_images_are_read(tmp_path, ocr_engine) -> None:
    """A near-blank page with small stamp images (e-signature sheet) is STAMP_PAGE and its stamps are OCR'd."""
    import pymupdf

    stamp = text_image(
        [(8, 22, "ДОКУМЕНТ ПОДПИСАН", 12), (8, 42, "Действителен с 23.03.2026", 10)], size=(200, 60), dpi=200
    )
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    pix = pymupdf.Pixmap(pymupdf.csRGB, stamp.shape[1], stamp.shape[0], stamp.tobytes(), False)
    page.insert_image(pymupdf.Rect(40, 40, 240, 100), pixmap=pix)
    doc.save(tmp_path / "st.pdf")
    rec = PageRecognizer(RecognitionConfig(), ExecutionConfig(providers="cpu", threads=2), engine=ocr_engine)
    with pymupdf.open(tmp_path / "st.pdf") as d:
        out = rec.recognize_page(d, 1, file_id="F9102", file_sha256="4" * 64)
    assert validation_errors("page_tokens", out) == []
    assert (
        out["page_class"] == "STAMP_PAGE"
        and out["is_stamp_page"]
        and out["ext"]["route"]["action"] == "ocr_images"
    )
    text = " ".join(t["text"] for t in out["tokens"])
    assert "ПОДПИСАН" in text and "23.03.2026" in text, text
    assert all(t["bbox"][0] >= 0.04 and t["bbox"][2] <= 0.3 and t["bbox"][3] <= 0.18 for t in out["tokens"])
    assert out["ext"]["ocr"]["regions"] == 1
