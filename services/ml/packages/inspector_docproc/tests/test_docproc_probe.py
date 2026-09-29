"""OCR arbitration of garbled-layer verdicts (RouterConfig.layer_probe) on synthetic replicas of real defects.

``garble_to_unicode`` keeps the Russian glyphs on screen and shifts only the extracted Unicode (95 R1, 94):
the constant-shift repair must be accepted and confirmed by the recogniser, a wrong repair rejected, and a
symbol-heavy but correct layer (SCAD printouts) must be trusted instead of being sent to full OCR.
"""

from __future__ import annotations

import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.recognize import PageRecognizer
from inspector_docproc.router import RoutePlan, route
from inspector_docproc.testing import garble_to_unicode, make_pdf
from inspector_docproc.textlayer import extract_text_layer

RU = [
    "Общество с ограниченной ответственностью",
    "Раздел проектной документации строительства здания",
    "Сведения об инженерном оборудовании и сетях",
    "Заказчик автономная некоммерческая организация",
    "Пояснительная записка к проекту организации",
]
SHIFT = 0x1D6


@pytest.fixture()
def recognizer(ocr_engine) -> PageRecognizer:
    return PageRecognizer(RecognitionConfig(), ExecutionConfig(providers="cpu", threads=2), engine=ocr_engine)


def _garbled_pdf(tmp_path):
    clean = make_pdf(tmp_path / "clean.pdf", [(60, 80 + 20 * i, t, 11) for i, t in enumerate(RU * 2)])
    return garble_to_unicode(clean, SHIFT, tmp_path / "garbled.pdf")


def test_synthetic_replica_extracts_shifted_glyph_codes(tmp_path) -> None:
    import pymupdf

    with pymupdf.open(_garbled_pdf(tmp_path)) as doc:
        words = [w.text for w in extract_text_layer(doc[0]).visible_words]
    assert words[0] == "".join(chr(ord(c) - SHIFT) for c in "Общество")


def test_repaired_layer_is_confirmed_by_ocr(tmp_path, recognizer) -> None:
    import pymupdf

    with pymupdf.open(_garbled_pdf(tmp_path)) as doc:
        page = doc[0]
        layer = extract_text_layer(page)
        facts, plan, _ = route(page, layer, recognizer.cfg.router, recognizer.lexicon)
        assert plan.page_class == "BROKEN_ENCODING" and plan.repaired
        plan2, probe = recognizer._verify_garble_verdict(page, layer, facts, plan)
        assert probe is not None and probe["agreement"] >= 0.9, probe
        assert plan2 is plan  # the repair stands

        out = recognizer.recognize_page(doc, 1, file_id="F9101", file_sha256="a" * 64)
    assert validation_errors("page_tokens", out) == []
    assert out["page_class"] == "BROKEN_ENCODING" and out["text_source"] == "TEXT_LAYER_REPAIRED"
    first = out["tokens"][0]
    assert first["text"] == "Общество" and first["text_raw"] == "Ɉɛɳɟɫɬɜɨ"
    assert first["corrected_by"] == "glyph_shift_repair" and first["source"] == "TEXT_LAYER_REPAIRED"
    assert out["ext"]["layer_probe"]["agreement"] >= 0.9


def test_repair_that_does_not_read_like_the_page_is_rejected(tmp_path, recognizer, monkeypatch) -> None:
    import pymupdf

    monkeypatch.setattr(recognizer, "_probe_layer", lambda page, words: {"words": 12, "agreement": 0.3})
    with pymupdf.open(_garbled_pdf(tmp_path)) as doc:
        page = doc[0]
        layer = extract_text_layer(page)
        facts, plan, _ = route(page, layer, recognizer.cfg.router, recognizer.lexicon)
        plan2, probe = recognizer._verify_garble_verdict(page, layer, facts, plan)
    assert probe == {"words": 12, "agreement": 0.3}
    assert (plan2.action, plan2.reason, plan2.trusted_text) == ("ocr_full", "repair_rejected_by_ocr", False)


def test_symbol_heavy_correct_layer_is_trusted_after_ocr_probe(tmp_path, recognizer) -> None:
    """A SCAD-like printout (ASCII brackets and formulas) looks «garbled» to the statistics only."""
    import pymupdf

    rows = [
        "[T=2.15 / f=0.46Hz] <N=12> {Ux=0.003}",
        "Node 118 [Rz=-4.21] <Mx=12.8> {Qy=0.77}",
        "Element 47 [T=1.03 / f=0.97Hz] <Uz=0.019>",
        "Load case 3 [Sum=145.2] <Kz=1.15> {c=0.8}",
    ]
    path = make_pdf(tmp_path / "scad.pdf", [(40, 80 + 22 * i, t, 12) for i, t in enumerate(rows * 3)])
    with pymupdf.open(path) as doc:
        page = doc[0]
        layer = extract_text_layer(page)
        facts, plan, _ = route(page, layer, recognizer.cfg.router, recognizer.lexicon)
        assert (plan.page_class, plan.action) == ("BROKEN_ENCODING", "ocr_full"), facts.text
        plan2, probe = recognizer._verify_garble_verdict(page, layer, facts, plan)
    assert probe is not None and probe["agreement"] >= 0.75, probe
    assert isinstance(plan2, RoutePlan)
    assert (plan2.page_class, plan2.action, plan2.reason) == ("VECTOR", "text", "layer_verified_by_ocr")
