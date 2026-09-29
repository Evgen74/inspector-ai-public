"""ИД binder page typing and segmentation (header band)."""

from __future__ import annotations

import pytest

from inspector_tables import binder
from inspector_tables.pagesource import PageData, PageSource
from inspector_tables.text import Word


def _page(lines: list[tuple[float, str]], width: float = 595, height: float = 842) -> PageData:
    words = []
    for y, text in lines:
        x = 50.0
        for t in text.split():
            words.append(Word(t, x, y, x + 6 * len(t), y + 10))
            x += 6 * len(t) + 4
    return PageData("F9", 1, width, height, words)


def test_header_band_kinds() -> None:
    assert (
        binder.classify_page(
            _page([(40, "ДОКУМЕНТ О КАЧЕСТВЕ БЕТОННОЙ СМЕСИ"), (60, "партии № 18-1"), (300, "текст " * 5)]),
            1,
            True,
        ).kind
        == "QUALITY_DOCS"
    )
    assert (
        binder.classify_page(
            _page([(40, "ПРОТОКОЛ ИСПЫТАНИЙ № 284"), (300, "образцы кубы бетона " * 3)]), 1, True
        ).kind
        == "LAB_OR_MEASUREMENT"
    )
    assert (
        binder.classify_page(
            _page([(40, "Реестр приложений №1 к акту АОСР №1А"), (300, "Документ о качестве " * 3)]), 1, True
        ).kind
        == "ID_REGISTRY"
    )
    assert binder.classify_page(_page([(40, "КОПИЯ ВЕРНА")]), 1, True).kind == "STAMP_PAGE"
    act = _page(
        [
            (40, "Объект капитального строительства " * 3),
            (420, "АКТ"),
            (432, "освидетельствования скрытых работ"),
            (444, "№ 1БТ"),
        ]
    )
    assert binder.classify_page(act, 1, True).kind == "AOSR"
    assert binder.classify_page(None, 7, False).kind == "UNREAD"


def test_segments_join_stamp_pages_and_untitled_continuations() -> None:
    K = binder.PageKind
    kinds = [K(1, "AOSR", "АКТ", "TEXT_LAYER", 0.9), K(2, "AOSR", "", "TEXT_LAYER", 0.7), K(3, "ID_REGISTRY", "Реестр", "TEXT_LAYER", 0.9),
             K(4, "QUALITY_DOCS", "Документ о качестве № 1", "TOKENS", 0.9), K(5, "UNKNOWN", "", "TOKENS", 0.3),
             K(6, "STAMP_PAGE", "КОПИЯ ВЕРНА", "TOKENS", 0.8), K(7, "QUALITY_DOCS", "Документ о качестве № 2", "TOKENS", 0.9)]  # fmt: skip
    segs = [(s.kind, s.start, s.end) for s in binder.segments(kinds)]
    assert segs == [("AOSR", 1, 2), ("ID_REGISTRY", 3, 3), ("QUALITY_DOCS", 4, 6), ("QUALITY_DOCS", 7, 7)]


@pytest.mark.data
def test_novoslobodskaya_act_binder_text_pages(open_train) -> None:
    doc = open_train("F0012")
    src = PageSource(doc, "F0012")
    kinds = []
    for pg in range(1, 7):
        has_text = len(doc[pg - 1].get_text().strip()) > 5
        kinds.append(binder.classify_page(src.page(pg) if has_text else None, pg, has_text))
    segs = [(s.kind, s.start, s.end) for s in binder.segments(kinds)]
    assert segs[:3] == [("AOSR", 1, 2), ("ISP_GEO_SCHEME", 3, 3), ("UNREAD", 4, 4)]
    assert ("ID_REGISTRY", 5, 6) in segs


@pytest.mark.slow
@pytest.mark.data
def test_binder_page_kinds_on_hand_labelled_novoslobodskaya_pages() -> None:
    """46 visually labelled ИД pages (tests/data/gt_binder_kinds_novoslobodskaya.json), batch code path."""
    from inspector_tables.evaluate import binder_accuracy
    from inspector_tables.testing import train_path

    if train_path("F0004") is None:
        pytest.skip("organizer data not found")
    acc = binder_accuracy()
    assert acc["pages"] == 46
    assert acc["segment_accuracy"] >= 0.85, acc["misses"]
    # the misses are abstentions (UNREAD: scans without OCR) or UNKNOWN — never a wrong document kind
    assert all(m[4] in ("UNREAD", "UNKNOWN") for m in acc["misses"]), acc["misses"]
