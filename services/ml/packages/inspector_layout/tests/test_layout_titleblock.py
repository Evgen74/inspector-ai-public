"""Title-block reader on synthetic ГОСТ Р 21.101 stamps (text layer) and on OCR-like word sets."""

from __future__ import annotations

from pathlib import Path

import pytest

from inspector_layout.codes import CodeRegistry
from inspector_layout.pagescan import PageScanner, ScanOptions, stamp_grid, window_text_chars
from inspector_layout.testing import StampSpec, make_stamp_pdf
from inspector_layout.titleblock import label_kind, parse_sheet, read_title_block
from inspector_layout.words import Word


def _scan(path: Path, page: int = 1, **opts):
    import pymupdf

    sc = PageScanner(CodeRegistry(), ScanOptions(ocr=False, qr_render=False, **opts))
    with pymupdf.open(path) as doc:
        return sc.scan(doc, page, file_id="F9001", stage_hint=None)


@pytest.fixture(scope="module")
def sheets(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("stamps")
    return make_stamp_pdf(
        d / "stamps.pdf",
        [
            StampSpec(),  # form 3, A3
            StampSpec(form="6", sheet="3", code="АНО/150321/1-РД-СП", change_rows=(), split_sheet_label=True),
            None,  # frame only
            StampSpec(sheet="12", sheets="35", stage="П", code="НВС-2025/03-ПЗ", change_rows=()),
        ],
    )


def test_form3_fields(sheets: Path) -> None:
    res = _scan(sheets, 1)
    tb = res.title_block
    assert res.form == "3" and res.words_source == "text_layer"
    assert tb["sheet_number"] == 4
    assert tb["document_code"] == "АНО/150321/1-РД-ОВ1" == tb["document_code_raw"]
    assert (tb["stage_raw"], tb["stage"]) == ("Р", "RD")
    assert tb["object_name"] == "Школа на 600 мест"
    assert tb["sheet_title"] == "План 1-го этажа"
    assert tb["organization"] == "ООО «Проект»"
    assert tb["revision"] == "2"
    rows = [(r["change_no"], r["count"], r["sheet"], r["doc_no"], r["date"]) for r in tb["change_rows"]]
    assert rows == [("1", "-", "Зам.", "582-23", "27.11.23"), ("2", "-", "Зам.", "690-23", "20.03.24")]
    assert tb["provenance"]["text_source"] == "TEXT_LAYER"
    x0, y0, x1, y1 = tb["bbox"]
    assert 0.5 < x0 < x1 <= 1.0 and 0.75 < y0 < y1 <= 1.0


def test_form6_with_split_sheet_label(sheets: Path) -> None:
    res = _scan(sheets, 2)
    tb = res.title_block
    assert res.form == "6"
    assert tb["sheet_number"] == 3
    assert tb["document_code"] == "АНО/150321/1-РД-СП"
    assert tb["stage"] is None and tb["sheets_total"] is None


def test_no_stamp_no_title_block(sheets: Path) -> None:
    res = _scan(sheets, 3)
    assert res.title_block is None


def test_sheets_total_and_pd_stage(sheets: Path) -> None:
    tb = _scan(sheets, 4).title_block
    assert (tb["sheet_number"], tb["sheets_total"], tb["stage"]) == (12, 35, "PD")
    assert tb["document_code"] == "НВС-2025/03-ПЗ"


def test_title_block_validates_against_contract(sheets: Path) -> None:
    from inspector_common.contracts.models import TitleBlock

    for p in (1, 2, 4):
        TitleBlock.model_validate(_scan(sheets, p).title_block)


def test_stamp_grid_detects_ruled_stamp(sheets: Path) -> None:
    import pymupdf

    with pymupdf.open(sheets) as doc:
        assert stamp_grid(doc[0]) is True
        assert stamp_grid(doc[1]) is True
        assert stamp_grid(doc[2]) is False  # the frame line alone is not a stamp


def test_outlined_stamp_is_sparse(tmp_path: Path) -> None:
    """An image-only stamp leaves the stamp core without text: the OCR fallback is then allowed."""
    import pymupdf

    from inspector_layout.words import from_text_layer, page_size_mm

    path = make_stamp_pdf(
        tmp_path / "o.pdf", [StampSpec()], outlined=True, extra_text=[(30, 280, "Примечание к чертежу", 9)]
    )
    with pymupdf.open(path) as doc:
        from inspector_docproc.textlayer import extract_text_layer

        page = doc[0]
        w, h = page_size_mm(page)
        words = from_text_layer(extract_text_layer(page), w, h)
        assert window_text_chars(words, w, h) == 0
        assert stamp_grid(page) is True
    res = _scan(path, 1)  # OCR disabled: nothing to read, no false title block
    assert res.title_block is None


# ── OCR-like word sets (mm) ─────────────────────────────────────────────────────────────────────


def _w(text: str, x0: float, y0: float, x1: float, y1: float, **kw) -> Word:
    return Word(text, x0, y0, x1, y1, source=kw.pop("source", "OCR"), conf=kw.pop("conf", 0.9), **kw)


def _d01_like(sheet_word: Word) -> list[Word]:
    """Word boxes of the real D01 stamp (F0201 p15, A1 841 × 594 mm), OCR spellings."""
    return [
        _w("АНО/150321/1-РД-ОВ1", 753.1, 535.9, 799.4, 542.0, raw="АHO/150321/1-РД-ОB1"),
        _w("2", 655.5, 544.4, 656.9, 548.9),
        _w("Зам.", 672.1, 544.3, 678.3, 549.2),
        _w("690-23", 681.1, 544.2, 690.3, 548.9),
        _w("20.03.2024", 706.4, 544.2, 716.1, 548.9),
        _w("1", 654.8, 550.7, 657.5, 551.6, angle=90),  # OCR: lone digit returned as vertical
        _w("Зам.", 672.0, 549.2, 678.5, 554.2),
        _w("582-23", 681.2, 549.3, 690.4, 554.0),
        _w("27.11.2023", 706.0, 549.3, 716.1, 554.0),
        _w("Школа на 600 мест", 731.3, 548.8, 790.0, 553.9),
        _w("Изм.", 652.8, 554.2, 659.4, 559.2),
        _w("Кол.", 663.0, 554.2, 669.2, 559.2),
        _w("Луст", 672.3, 554.3, 678.7, 559.1),  # OCR «Лист»
        _w("Ngok.", 682.0, 554.0, 690.3, 559.1),  # OCR «№док.»
        _w("Подпись", 693.3, 554.2, 703.3, 558.9),
        _w("Дата", 707.4, 554.2, 714.7, 559.1),
        _w("Стадия", 788.5, 558.9, 797.7, 564.1),
        _w("Лист", 804.9, 559.3, 811.2, 564.1),
        _w("Листов", 821.2, 559.6, 830.3, 563.8),
        _w("PД", 791.4, 566.5, 794.9, 571.7),
        sheet_word,
        _w("Карактеристика систем", 729.1, 577.1, 775.0, 581.3),
        _w("000", 804.2, 579.3, 809.7, 583.9),
        _w("«ТСП»", 811.9, 579.3, 817.8, 583.9),
        _w("Формат:", 800.9, 589.0, 812.0, 593.9),
    ]


def test_ocr_word_quirks_d01() -> None:
    words = _d01_like(_w("2", 807.0, 568.7, 810.0, 569.7, angle=90))
    tb = read_title_block(words, 841.0, 594.0, registry=CodeRegistry())
    assert tb is not None and tb.form == "3"
    assert tb.sheet_number == 2
    assert tb.code == "АНО/150321/1-РД-ОВ1" and tb.code_raw == "АHO/150321/1-РД-ОB1"
    assert (tb.stage_raw, tb.stage) == ("РД", "RD")
    assert [r["change_no"] for r in tb.change_rows] == ["2", "1"]
    assert tb.change_rows[0]["doc_no"] == "690-23" and tb.change_rows[1]["date"] == "27.11.2023"
    assert tb.organization == "ООО «ТСП»"
    assert tb.grid is not None and abs(tb.grid.scale - 1.0) < 0.02


def test_scaled_stamp_still_reads() -> None:
    """A sheet printed at 1:2 (stamp half size) is read through the fitted grid scale."""
    base = _d01_like(_w("7", 807.0, 567.5, 810.0, 571.0))
    words = [
        Word(w.text, 400 + (w.x0 - 400) * 0.5, 300 + (w.y0 - 300) * 0.5, 400 + (w.x1 - 400) * 0.5,
             300 + (w.y1 - 300) * 0.5, w.source, w.conf, w.raw, w.angle)
        for w in base
    ]  # fmt: skip
    tb = read_title_block(words, 620.5, 447.0)
    assert tb is not None and tb.sheet_number == 7
    assert tb.grid is not None and abs(tb.grid.scale - 0.5) < 0.03


def test_code_only_footer_is_not_a_stamp() -> None:
    words = [
        _w("Предложение", 60, 280, 90, 284),
        _w("KR22-031295/1", 92, 280, 120, 284),
        _w("Страница", 150, 280, 170, 284),
    ]
    assert read_title_block(words, 210.0, 297.0) is None


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Стадия", "STAGE"),
        ("Листов", "SHEETS"),
        ("Лист", "SHEET"),
        ("Луст", "SHEET"),
        ("Изм.", "CHANGE"),
        ("Кол.уч", "COUNT"),
        ("№ док.", "DOCNO"),
        ("№gok.", "DOCNO"),
        ("Ngok.", "DOCNO"),
        ("Подпись", "SIGN"),
        ("Дата", "DATE"),
        ("Разраб.", "ROLE"),
        ("Н.контр.", "ROLE"),
        ("листе", None),
        ("План", None),
        ("Лисm", "SHEET"),  # OCR: a stray Latin «m» for «т» (F0164 p13)
        ("Л̛ст", "SHEET"),  # a text layer with one unmapped glyph (F0153)
        ("Подп̛сь", "SIGN"),
        ("ʪата", "DATE"),
    ],
)
def test_label_kinds(text: str, kind: str | None) -> None:
    assert label_kind(text) == kind


@pytest.mark.parametrize(
    ("text", "value"),
    [("12", 12), ("О", 0), ("1З", 13), ("5а", "5а"), ("1.1", "1.1"), ("—", None), ("", None), ("- 4 -", 4),
     ("–12–", 12)],
)  # fmt: skip
def test_parse_sheet(text: str, value) -> None:
    assert parse_sheet(text)[0] == value


def test_outlined_stamp_is_read_by_ocr(tmp_path: Path) -> None:
    """The OCR fallback end to end on an image-only stamp (needs the OCR models, not the organizer data)."""
    import pymupdf

    from inspector_docproc.testing import models_available

    if not models_available():
        pytest.skip("OCR models not found in .models/ocr")
    # the QR image is pasted over the start of the sheet title, as on the Тюменская RD stamps
    path = make_stamp_pdf(
        tmp_path / "o.pdf",
        [StampSpec(sheet="17", sheets="24")],
        outlined=True,
        qr_payloads=["https://x.test/7"],
    )
    sc = PageScanner(CodeRegistry(), ScanOptions(ocr=True, qr=True, providers="cpu", threads=2))
    with pymupdf.open(path) as doc:
        res = sc.scan(doc, 1, file_id="F9001", stage_hint="RD")
    tb = res.title_block
    assert res.words_source == "ocr" and res.stamp_grid is True and res.ocr_ms > 0
    assert (tb["sheet_number"], tb["sheets_total"], tb["stage"]) == (17, 24, "RD")
    assert tb["document_code"] == "АНО/150321/1-РД-ОВ1"
    assert tb["provenance"]["text_source"] == "OCR"
    assert res.ocr_hidden_images == 1 and tb["sheet_title"] == "План 1-го этажа"
    assert [q["payload"] for q in res.qr] == ["https://x.test/7"]  # decoded from the untouched page


# ── OCR repairs: change-row kinds, organisation quotes, QR over the title ────────────────────────


@pytest.mark.parametrize(
    ("text", "out"),
    [("3ам.", "Зам."), ("Зам.", "Зам."), ("Hов.", "Нов."), ("Aннул.", "Аннул."), ("3ам", "Зам"), ("2", "2"),
     ("-", "-"), ("Замена", "Замена")],
)  # fmt: skip
def test_fold_change_kind(text: str, out: str) -> None:
    from inspector_layout.titleblock import fold_change_kind

    assert fold_change_kind(text) == out


@pytest.mark.parametrize(
    ("text", "out"),
    [
        ("ООО ТСП»", "ООО «ТСП»"),
        ("ООО «ТСП", "ООО «ТСП»"),
        ("ООО ТСП", "ООО «ТСП»"),
        ("ООО «ТСП»", "ООО «ТСП»"),
        ("АО «Мосинжпроект»", "АО «Мосинжпроект»"),
        ("ООО «Фирма «Проект»", "ООО «Фирма «Проект»"),  # nested, unbalanced: left alone
        ("Проектное бюро", "Проектное бюро"),
    ],
)
def test_balance_org_quotes(text: str, out: str) -> None:
    from inspector_layout.titleblock import balance_org_quotes

    assert balance_org_quotes(text) == out


def test_ocr_change_kind_and_org_repaired() -> None:
    words = _d01_like(_w("2", 807.0, 568.7, 810.0, 569.7, angle=90))
    words = [(_w("3ам.", w.x0, w.y0, w.x1, w.y1) if w.text == "Зам." else w) for w in words]
    words = [w for w in words if w.text != "«ТСП»"] + [_w("ТСП»", 811.9, 579.3, 817.8, 583.9)]
    tb = read_title_block(words, 841.0, 594.0, registry=CodeRegistry())
    assert tb is not None
    assert [r["sheet"] for r in tb.change_rows] == ["Зам.", "Зам."]
    assert tb.organization == "ООО «ТСП»"


def test_text_layer_values_are_not_repaired(sheets: Path) -> None:
    """A text layer is what the stamp prints: no kind fold, no quote repair."""
    tb = _scan(sheets, 1).title_block
    assert tb["organization"] == "ООО «Проект»"
    assert [r["sheet"] for r in tb["change_rows"]] == ["Зам.", "Зам."]


def test_hide_window_images_leaves_the_source_page(tmp_path: Path) -> None:
    """The Exon QR is pasted over the sheet title: the OCR copy drops it, the source page keeps it for QR."""
    import pymupdf

    from inspector_layout.pagescan import OCR_WINDOW_MM, _window_images, hide_window_images

    path = make_stamp_pdf(
        tmp_path / "q.pdf", [StampSpec(), StampSpec()], qr_payloads=["https://x.test/1", None]
    )
    with pymupdf.open(path) as doc:
        w, h = doc[0].rect.width / (72 / 25.4), doc[0].rect.height / (72 / 25.4)
        win = [1 - OCR_WINDOW_MM[0] / w, 1 - OCR_WINDOW_MM[1] / h, 1.0, 1.0]
        hidden = hide_window_images(doc[0], win)
        assert hidden is not None
        tmp, tpage, n = hidden
        try:
            assert n == 1 and _window_images(tpage, win) == []
            assert tpage.rect == doc[0].rect
        finally:
            tmp.close()
        assert len(_window_images(doc[0], win)) == 1  # the source document is untouched
        assert hide_window_images(doc[1], win) is None  # nothing to hide


# ── code line assembly, stamp bounds, virtual anchors, garbled layers ──────────────────────────


def test_code_split_into_ocr_tokens_is_joined() -> None:
    """F0162 p14: OCR returns «АНО» (a little lower) + «/150321/1-П-ИОС» + «5.1.4»."""
    words = _d01_like(_w("2", 807.0, 568.7, 810.0, 569.7, angle=90))
    words = [w for w in words if not w.text.startswith("АНО/")]
    words += [
        _w("/150321/1-П-ИОС", 757.0, 535.8, 800.2, 543.1),
        _w("5.1.4", 801.3, 535.8, 810.9, 543.0),
        _w("АНО", 745.0, 536.0, 754.7, 543.2, conf=0.52),
    ]
    tb = read_title_block(words, 841.0, 594.0, registry=CodeRegistry(), stage_hint="PD")
    assert tb is not None and tb.code == "АНО/150321/1-П-ИОС5.1.4"


def test_overlapping_text_layer_runs_are_one_code() -> None:
    """F0148 p371: text-layer runs «АНО» «/150321/1-» «П» «-ПЗУ» overlap by ≈ 0.6 mm."""
    words = _d01_like(_w("2", 807.0, 568.7, 810.0, 569.7, angle=90))
    words = [w for w in words if not w.text.startswith("АНО/")]
    words += [
        _w("АНО", 760.0, 536.0, 767.6, 540.8, source="TEXT_LAYER"),
        _w("/150321/1-", 767.0, 536.0, 784.2, 540.8, source="TEXT_LAYER"),
        _w("П", 783.7, 536.0, 786.9, 540.8, source="TEXT_LAYER"),
        _w("-ПЗУ", 786.3, 536.0, 795.2, 540.8, source="TEXT_LAYER"),
    ]
    tb = read_title_block(words, 841.0, 594.0)
    assert tb is not None and tb.code == "АНО/150321/1-П-ПЗУ" and tb.code_basis == "text_layer"


def test_drawing_code_above_the_stamp_is_not_the_code(tmp_path: Path) -> None:
    """A topographic plan's own sheet nomenclature «A-XVI-16-02» printed large above the stamp (F0148)."""
    path = make_stamp_pdf(
        tmp_path / "t.pdf", [StampSpec(change_rows=())], extra_text=[(300, 225, "A-XVI-16-02", 18)]
    )
    tb = _scan(path, 1).title_block
    assert tb["document_code"] == "АНО/150321/1-РД-ОВ1"


def test_sheet_value_read_when_its_label_is_not() -> None:
    """«Стадия» and «Листов» read, «Лист» lost: the cell comes from the fitted grid (F0164 p13)."""
    words = [w for w in _d01_like(_w("5", 807.0, 567.5, 810.0, 571.0)) if w.text != "Лист"]
    tb = read_title_block(words, 841.0, 594.0)
    assert tb is not None and tb.sheet_number == 5 and tb.form == "3"


def test_garbled_labels_anchor_but_garbled_values_are_dropped() -> None:
    """F0153: labels with one unmapped glyph still anchor the stamp; a mojibake шифр is not a code."""
    tl = {"source": "TEXT_LAYER", "conf": 0.5}
    words = [
        _w("Кол.", 32.5, 283.0, 38.5, 286.5, source="TEXT_LAYER"),
        _w("Л̛", 42.0, 283.0, 44.5, 286.5, **tl),
        _w("ст", 45.0, 283.0, 47.5, 286.5, source="TEXT_LAYER"),
        _w("№док", 51.5, 283.0, 58.5, 286.5, source="TEXT_LAYER"),
        _w("Подп̛", 62.0, 283.0, 68.0, 286.5, **tl),
        _w("сь", 68.5, 283.0, 71.5, 286.5, source="TEXT_LAYER"),
        _w("ʪата", 76.5, 283.0, 83.0, 286.5, **tl),
        _w("ȺɇɈ/150321/1-ɉ-ȻЭɈКɋ10(1).ɉɁ", 98.0, 278.0, 182.0, 285.5, **tl),
        _w("Л̛ст", 196.0, 275.5, 203.5, 280.0, **tl),
        _w("4", 198.5, 283.0, 200.5, 287.5, source="TEXT_LAYER"),
    ]
    tb = read_title_block(words, 210.0, 297.0)
    assert tb is not None and tb.form == "6" and tb.sheet_number == 4
    assert tb.code is None


def test_page_wide_offset_repairs_words_a_font_could_not(monkeypatch) -> None:
    """docproc keeps a font unrepaired when its few checkable words already hit the lexicon; the stamp reader
    applies the page's one confirmed offset to the words still garbled (F0153 p5)."""
    from types import SimpleNamespace

    import inspector_docproc.repair as rep
    import inspector_docproc.textlayer as tl
    from inspector_docproc.textlayer import TextLayer, TextWord

    shift = 0x1D6
    garbled = "".join(chr(ord(c) - shift) if "А" <= c <= "я" else c for c in "АНО/150321/1-П-ПЗ")
    words = [
        TextWord(garbled, [0.5, 0.9, 0.9, 0.93], "Times", 10.0, 0, 0, 0, True),
        TextWord("Ɍɚɦ", [0.1, 0.1, 0.2, 0.12], "Times", 10.0, 0, 0, 1, True),
    ]
    monkeypatch.setattr(tl, "extract_text_layer", lambda page: TextLayer(words=list(words)))

    def fake_repair(ws, cfg=None, lexicon=None):
        for w in ws:
            w.garbled = rep.word_is_garbled(w.text)
        return SimpleNamespace(
            unrepaired_words=sum(w.garbled for w in ws),
            fonts=[SimpleNamespace(offset=shift, digit_offset=None, accepted=True)],
        )

    monkeypatch.setattr(rep, "repair_words", fake_repair)
    sc = PageScanner(CodeRegistry(), ScanOptions(ocr=False, qr=False))
    sc._lexicon = object()  # no lexicon load
    layer = sc.text_layer(None)
    texts = {w.text for w in layer.words}
    assert "АНО/150321/1-П-ПЗ" in texts and "Там" in texts
    assert all(w.repaired and not w.garbled for w in layer.words)
