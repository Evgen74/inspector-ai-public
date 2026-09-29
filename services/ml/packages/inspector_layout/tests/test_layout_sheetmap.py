"""Sheet ↔ page map: groups per document code, support, smoothing, QR fill, duplicates."""

from __future__ import annotations

from inspector_common.contracts.models import SheetPageEntry
from inspector_layout.sheetmap import PageSheet, build_sheet_map

OV1 = "АНО/150321/1-РД-ОВ1"
SPEC = "АНО/150321/1-РД-ОВ1.С"


def _map(pages: list[PageSheet]) -> dict[int, dict]:
    out = build_sheet_map(pages)
    for e in out:
        SheetPageEntry.model_validate(e)
    return {e["pdf_page_number"]: e for e in out}


def _ps(page: int, sheet, code: str | None = OV1, **kw) -> PageSheet:
    return PageSheet(page=page, sheet=sheet, code=code, confidence=0.9, title_block=True, **kw)


def test_linear_run_is_title_block_basis() -> None:
    m = _map([_ps(p, p - 13) for p in range(14, 20)])
    assert [m[p]["sheet_number"] for p in range(14, 20)] == [1, 2, 3, 4, 5, 6]
    assert {e["basis"] for e in m.values()} == {"TITLE_BLOCK"}
    assert all(e["duplicate_of_page"] is None for e in m.values())


def test_misread_between_consistent_neighbours_is_smoothed() -> None:
    """F0202 p19 was once read «9» between sheets 5 and 7 (95 R5)."""
    m = _map([_ps(17, 4), _ps(18, 5), _ps(19, 9), _ps(20, 7), _ps(21, 8)])
    assert m[19]["sheet_number"] == 6 and m[19]["basis"] == "SEQUENCE_SMOOTHED"
    assert m[19]["confidence"] < 0.8


def test_missing_reading_is_filled() -> None:
    m = _map([_ps(20, 7), _ps(21, None), _ps(22, 9), _ps(23, 10)])
    assert m[21]["sheet_number"] == 8 and m[21]["basis"] == "SEQUENCE_SMOOTHED"


def test_duplicate_sheets_are_flagged_not_dropped() -> None:
    """F0201 p27–p31 print 14, 15, 14, 15, 16."""
    m = _map([_ps(26, 13), _ps(27, 14), _ps(28, 15), _ps(29, 14), _ps(30, 15), _ps(31, 16), _ps(32, 17)])
    assert [m[p]["sheet_number"] for p in range(26, 33)] == [13, 14, 15, 14, 15, 16, 17]
    assert m[29]["duplicate_of_page"] == 27 and m[30]["duplicate_of_page"] == 28
    assert m[31]["duplicate_of_page"] is None
    assert all(m[p]["basis"] == "TITLE_BLOCK" for p in m)


def test_numbering_restarts_per_document_code() -> None:
    m = _map([_ps(47, 32), _ps(48, 33), _ps(49, 1, SPEC), _ps(50, 2, SPEC), _ps(51, 3, SPEC)])
    assert m[49]["sheet_number"] == 1 and m[49]["duplicate_of_page"] is None
    assert m[49]["document_code"] == SPEC and m[48]["document_code"] == OV1


def test_codeless_cover_is_not_a_duplicate_of_sheet_one() -> None:
    """A cover «Лист 1 / Листов 1» without a readable шифр before sheet 1 of the document (F0202 p6/p10)."""
    m = _map([_ps(6, 1, None), _ps(10, 1, "СП"), _ps(11, 2, "СП"), _ps(12, 3, "СП")])
    assert m[10]["duplicate_of_page"] is None
    assert m[6]["document_code"] is None


def test_codeless_page_joins_its_document() -> None:
    m = _map([_ps(20, 7), _ps(21, 8, None), _ps(22, 9)])
    assert m[21]["document_code"] == OV1 and m[21]["basis"] == "TITLE_BLOCK"


def test_qr_page_fills_a_stamp_without_sheet() -> None:
    key = "exon:3eb2aa9d/1"
    pages = [_ps(p, p - 13, qr_key=key, qr_page=p) for p in (14, 15, 16)]
    pages.append(_ps(17, None, qr_key=key, qr_page=17))
    m = _map(pages)
    assert m[17]["sheet_number"] == 4 and m[17]["basis"] == "QR"


def test_no_fill_after_the_last_sheet() -> None:
    """Unstamped appendix pages after the last sheet carry the QR of the file but are not sheets."""
    key = "exon:3eb2aa9d/1"
    pages = [_ps(p, p - 48, SPEC, qr_key=key, qr_page=p) for p in (170, 171, 172)]
    pages += [PageSheet(page=p, qr_key=key, qr_page=p) for p in (173, 174)]
    m = _map(pages)
    assert 173 not in m and 174 not in m


def test_unsupported_isolated_reading_is_kept() -> None:
    m = _map([_ps(5, 12, "X-1-АР")])
    assert m[5]["sheet_number"] == 12 and m[5]["basis"] == "TITLE_BLOCK"


def test_string_sheet_numbers_pass_through() -> None:
    m = _map([_ps(3, "5а"), _ps(4, 6)])
    assert m[3]["sheet_number"] == "5а"


def test_empty() -> None:
    assert build_sheet_map([]) == []


def test_text_layer_reading_is_never_overridden() -> None:
    """A text-layer «3» between 3 and 5 is what the stamp prints: a duplicate, not a misread 4."""
    pages = [_ps(1, 1), _ps(2, 2), _ps(3, 3), _ps(4, 3), _ps(5, 5)]
    for p in pages:
        p.trusted = True
    m = _map(pages)
    assert m[4]["sheet_number"] == 3 and m[4]["duplicate_of_page"] == 3 and m[4]["basis"] == "TITLE_BLOCK"
    ocr = _map([_ps(1, 1), _ps(2, 2), _ps(3, 3), _ps(4, 3), _ps(5, 5)])  # the same readings from OCR
    assert ocr[4]["sheet_number"] == 4 and ocr[4]["basis"] == "SEQUENCE_SMOOTHED"


def test_one_sheet_document_is_sheet_one() -> None:
    """ГОСТ Р 21.101: «Лист» blank and «Листов 1» on a one-sheet document (F0161 p5 «Содержание»)."""
    m = _map(
        [_ps(5, None, "X-С", sheets_total=1), _ps(6, None, "X-ГЗ", sheets_total=1), _ps(7, None, "X-ТЧ")]
    )
    assert m[5]["sheet_number"] == 1 and m[5]["basis"] == "TITLE_BLOCK" and m[5]["duplicate_of_page"] is None
    assert m[6]["sheet_number"] == 1 and m[6]["duplicate_of_page"] is None
    assert 7 not in m  # a blank «Лист» without «Листов» stays unmapped


def test_second_first_sheet_opens_a_new_document() -> None:
    """F0204: drawings 1–9 (Листов 9), then the specification 1–8 (Листов 8) under the same шифр."""
    code = "АНО/150321/1-РД-ВК"
    pages = [_ps(p, p - 5, code, sheets_total=9 if p == 6 else None) for p in range(6, 15)]
    pages += [_ps(15, 1, code, sheets_total=8)] + [_ps(p, p - 14, code) for p in range(16, 23)]
    m = _map(pages)
    assert [m[p]["sheet_number"] for p in range(15, 23)] == list(range(1, 9))
    assert all(m[p]["duplicate_of_page"] is None for p in m)


def test_drawings_after_the_text_part_open_a_new_document() -> None:
    """F0190: the text part prints sheets 3–6, then the drawings start «1 / 4» under the same шифр."""
    code = "АНО/150321/1-П-ООС8.2"
    pages = [_ps(p, p - 2, code) for p in range(5, 9)] + [_ps(17, 1, code, sheets_total=4)]
    pages += [_ps(p, p - 16, code, sheets_total=4) for p in range(18, 21)]
    m = _map(pages)
    assert [m[p]["sheet_number"] for p in (17, 18, 19, 20)] == [1, 2, 3, 4]
    assert all(m[p]["duplicate_of_page"] is None for p in m)


def test_numbering_restart_opens_a_new_document() -> None:
    """Новослободская F0104: the text part «1…11», then the drawings «1…30» under the same шифр."""
    code = "НВС-2025/03-АР"
    pages = [_ps(p, p - 7, code, trusted=True) for p in range(8, 19)]
    pages += [_ps(p, p - 18, code, trusted=True) for p in range(19, 25)]
    m = _map(pages)
    assert [m[p]["sheet_number"] for p in range(19, 25)] == [1, 2, 3, 4, 5, 6]
    assert all(m[p]["duplicate_of_page"] is None for p in m)


def test_isolated_ocr_one_is_not_a_restart() -> None:
    """An OCR «1» between 6 and 8 is a misread 7 (smoothed), not a new document."""
    m = _map(
        [_ps(p, p, "X-1-АР") for p in (5, 6)]
        + [_ps(7, 1, "X-1-АР"), _ps(8, 8, "X-1-АР"), _ps(9, 9, "X-1-АР")]
    )
    assert m[7]["sheet_number"] == 7 and m[7]["basis"] == "SEQUENCE_SMOOTHED"
