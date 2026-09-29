"""Page router and garbled-layer repair on synthetic pages (one per page class)."""

from __future__ import annotations

import numpy as np
import pytest

from inspector_docproc.lexicon import load_lexicon, text_stats
from inspector_docproc.repair import is_suspicious, repair_words, shift_text, word_is_garbled
from inspector_docproc.router import route
from inspector_docproc.testing import make_pdf, make_scan_pdf, text_image
from inspector_docproc.textlayer import TextWord, extract_text_layer

RU = [
    "Общество с ограниченной ответственностью",
    "Раздел проектной документации строительства здания",
    "Сведения об инженерном оборудовании и сетях",
    "Заказчик автономная некоммерческая организация",
    "Пояснительная записка к проекту организации",
]
SHIFT = 0x1D6  # the constant glyph shift seen on Тюменская PD layers (95 R1)


def garble(text: str) -> str:
    return "".join(chr(ord(c) - SHIFT) if "А" <= c <= "я" else c for c in text)


def _route(path):
    import pymupdf

    with pymupdf.open(path) as doc:
        page = doc[0]
        layer = extract_text_layer(page)
        facts, plan, report = route(page, layer)
        return facts, plan, report, layer


def test_lexicon_is_available_and_russian() -> None:
    lex = load_lexicon()
    assert len(lex) > 10_000
    hit, n = lex.hit_ratio(" ".join(RU).split())
    assert n >= 15 and hit >= 0.9


def test_vector_text_page(tmp_path) -> None:
    lines = [(60, 80 + 20 * i, t, 11) for i, t in enumerate(RU * 2)]
    facts, plan, _, _ = _route(make_pdf(tmp_path / "v.pdf", lines))
    assert plan.page_class == "VECTOR" and plan.action == "text"
    assert facts.lexicon_hit >= 0.9


def test_large_sheet_gets_coverage_ocr(tmp_path) -> None:
    lines = [(60, 80 + 20 * i, t, 11) for i, t in enumerate(RU * 2)]
    _, plan, _, _ = _route(make_pdf(tmp_path / "a3.pdf", lines, size=(1191, 842)))
    assert plan.page_class == "VECTOR" and plan.action == "text+coverage"


def test_empty_and_stamp_pages(tmp_path) -> None:
    import pymupdf

    _, plan, _, _ = _route(make_pdf(tmp_path / "e.pdf", []))
    assert plan.page_class == "EMPTY" and plan.action == "none"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    stamp = np.full((80, 160, 3), 255, np.uint8)
    stamp[20:60, 20:140] = (40, 40, 200)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 160, 80, stamp.tobytes(), False)
    page.insert_image(pymupdf.Rect(400, 650, 560, 730), pixmap=pix)
    page.insert_text((300, 780), "6", fontsize=9)
    doc.save(tmp_path / "s.pdf")
    _, plan, _, _ = _route(tmp_path / "s.pdf")
    # the stamp image itself is OCR'd (e-signature sheets carry certificates and dates), nothing else
    assert plan.page_class == "STAMP_PAGE" and plan.action == "ocr_images"


def test_scan_hidden_layer_and_hybrid(tmp_path) -> None:
    img = text_image([(60, 100, "ПРОТОКОЛ ИСПЫТАНИЙ № 25", 16)], dpi=100)
    _, plan, _, _ = _route(make_scan_pdf(tmp_path / "scan.pdf", img))
    assert (plan.page_class, plan.action, plan.orientation) == ("RASTER_SCAN", "ocr_full", True)
    _, plan, _, _ = _route(make_scan_pdf(tmp_path / "hid.pdf", img, hidden_text=" ".join(RU)))
    assert plan.page_class == "RASTER_HIDDEN_OCR" and plan.action == "ocr_full"
    visible = [(60, 200 + 14 * i, t, 10) for i, t in enumerate(RU)]
    _, plan, _, _ = _route(make_scan_pdf(tmp_path / "hyb.pdf", img, extra_visible=visible))
    assert plan.page_class == "HYBRID" and plan.action == "text+coverage"
    junk = [(60, 200 + 14 * i, "lVШТАЛЛОПРОКАТНЬIЙ АIМЕfАЛЛ /&::СЕРВИС Mеталл", 10) for i in range(6)]
    _, plan, _, _ = _route(make_scan_pdf(tmp_path / "junk.pdf", img, extra_visible=junk))
    assert plan.page_class == "HYBRID" and plan.action == "ocr_full" and not plan.trusted_text


def test_text_as_curves(tmp_path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    shape = page.new_shape()
    for i in range(4000):
        x, y = 30 + (i % 100) * 5, 30 + (i // 100) * 18
        shape.draw_line((x, y), (x + 3, y + 8))
    shape.finish(color=(0, 0, 0), width=0.3)
    shape.commit()
    doc.save(tmp_path / "o.pdf")
    facts, plan, _, _ = _route(tmp_path / "o.pdf")
    assert facts.stream_bytes >= 60_000
    assert plan.page_class == "VECTOR_OUTLINED_TEXT" and plan.action == "ocr_full"


def test_garbled_layer_is_repaired_with_raw_text_kept(tmp_path) -> None:
    lines = [(60, 80 + 20 * i, garble(t), 11) for i, t in enumerate(RU * 2)]
    facts, plan, report, layer = _route(make_pdf(tmp_path / "g.pdf", lines, font="cjk"))
    assert facts.garbled_word_share > 0.5
    assert plan.page_class == "BROKEN_ENCODING" and plan.repaired and plan.action == "text"
    assert report is not None and report.fully_repaired
    assert any(f.offset == SHIFT and f.accepted for f in report.fonts)
    texts = " ".join(w.text for w in layer.visible_words)
    assert "организация" in texts and "документации" in texts
    repaired = [w for w in layer.visible_words if w.repaired]
    assert repaired and all(w.text_raw and word_is_garbled(w.text_raw) for w in repaired)


def test_unrepairable_garble_goes_to_ocr(tmp_path) -> None:
    # glyph-index text without a constant shift («=5>><<5DG5E>4O»): only OCR can read it
    junk = "Ɂ4>47G<> - Ⱥ6F>=><=4O =5>><<5DG5E>4O >D74=<74F<O Ɇ>E>64 ɉ$ɈȿɄ&ɇȺ/"
    lines = [(40, 80 + 20 * i, junk, 11) for i in range(8)]
    _, plan, _, _ = _route(make_pdf(tmp_path / "u.pdf", lines, font="cjk"))
    assert plan.page_class == "BROKEN_ENCODING" and plan.action == "ocr_full" and not plan.trusted_text


def test_shift_and_suspicious_chars() -> None:
    assert shift_text(garble("организация"), SHIFT) == "организация"
    assert not is_suspicious("Ø") and not is_suspicious("№") and is_suspicious("ɨ")
    assert shift_text("\x13\x14", SHIFT, digit_offset=0x1D) == "01"


def test_repair_words_requires_lexicon_confirmation() -> None:
    words = [TextWord(garble(w), [0, 0, 1, 1], "F1", 10, 0, 0, i) for i, w in enumerate(" ".join(RU).split())]
    report = repair_words(words)
    assert report.fully_repaired and all(w.repaired for w in words if "А" <= w.text[0] <= "я")
    noise = [
        TextWord("ɀɀɀɀ ʁʁʁʁʁ", [0, 0, 1, 1], "F2", 10, 0, 0, i) for i in range(5)
    ]  # no shift makes words
    report2 = repair_words(noise)
    assert not report2.fully_repaired and report2.unrepaired_words == 5


@pytest.mark.parametrize(("text", "moj"), [("Здание школы", 0.0), ("Ɂ4>47G<>", 0.5)])
def test_text_stats_mojibake_ratio(text: str, moj: float) -> None:
    assert text_stats([text])["mojibake_ratio"] >= moj


def test_control_char_offset_and_word_split() -> None:
    """A font that also shifts spaces/digits into control characters (+0x1D) is repaired and re-split."""
    from inspector_docproc.repair import split_repaired

    def enc(t: str) -> str:
        return "".join(
            chr(ord(c) - 0x228) if "А" <= c <= "я" else chr(ord(c) - 0x1D) if c in " 0123456789.," else c
            for c in t
        )

    words = [
        TextWord(enc("Протокол проверки электронной подписи 12.10.2021"), [0, 0, 1, 0.1], "V", 10, 0, 0, i)
        for i in range(6)
    ]
    report = repair_words(words)
    assert report.fully_repaired
    out = split_repaired(words)
    assert [w.text for w in out[:5]] == ["Протокол", "проверки", "электронной", "подписи", "12.10.2021"]
    assert out[0].bbox[2] < out[1].bbox[0] + 1e-6 and all(w.repaired and w.text_raw for w in out[:5])
