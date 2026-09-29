"""EXPLICATION on real TRAIN pages against hand ground truth (96 R-08: ≥ 0.98 of rows exact).

GT files (tests/data/gt_explication_*.json) are visual transcriptions of rendered crops, made without the
text layer or the parser (see their ``method``). Text-layer-only parsing is measured here; the one row whose
name is drawn as curves on F0201 p18 (row 193) needs OCR tokens, covered by the token test below.
"""

from __future__ import annotations

import pytest

from inspector_tables import explication
from inspector_tables.evaluate import compare, explication_keys, gt_rows
from inspector_tables.pagesource import PageSource
from inspector_tables.testing import DATA_DIR, cached_token_dir

pytestmark = pytest.mark.data

GT = {("F0201", 18): "gt_explication_F0201_p18.json", ("F0202", 17): "gt_explication_F0202_p17.json",
      ("F0104", 22): "gt_explication_F0104_p22.json"}  # fmt: skip


def _parse(open_train, fid: str, pg: int, tokens=None):
    return explication.parse_page(PageSource(open_train(fid), fid, tokens).page(pg))


def test_explication_rows_exact_on_three_real_pages(open_train) -> None:
    exact = total = 0
    per_page = {}
    for (fid, pg), name in GT.items():
        les = _parse(open_train, fid, pg)
        parsed = [k for le in les for k in explication_keys(le.rows)]
        acc = compare(parsed, gt_rows(DATA_DIR / name))
        per_page[(fid, pg)] = (acc.exact, acc.gt_rows)
        exact += acc.exact
        total += acc.gt_rows
    assert per_page[("F0104", 22)] == (25, 25)
    assert per_page[("F0201", 18)][0] >= 118  # 119 GT rows; 193's name is outlined (no text layer)
    assert per_page[("F0202", 17)] == (80, 80)  # row 250: a condensed font without spaces, re-segmented
    assert exact / total >= 0.98, per_page


def test_f0201_p18_side_by_side_parts_and_real_double_counts(open_train) -> None:
    les = _parse(open_train, "F0201", 18)
    assert len(les) == 1 and len(les[0].parts) == 4
    checks = [(c["kind"], c["passed"], c["expected"], c["actual"]) for c in les[0].checks]
    # 97 §1.5: the «в том числе» zone (30.4 m²) of room 102 counted twice; and the same for room 130 (65.8)
    assert ("SUBZONE_DOUBLE_COUNT", False, 1049.5, 1079.9) in checks
    assert ("SUBZONE_DOUBLE_COUNT", False, 490.9, 556.7) in checks
    assert sum(1 for k, p, *_ in checks if k == "SUM_MATCHES_TOTAL" and p) == 5
    grand = checks[-1]
    assert (
        grand[0] == "SUM_MATCHES_TOTAL" and grand[1] is False and grand[3] == 4168.9
    )  # printed grand total ≠ Σ


def test_f0104_p22_stacked_subtotal_and_title_band(open_train) -> None:
    (le,) = _parse(open_train, "F0104", 22)
    assert [c["passed"] for c in le.checks] == [True] * 5  # four groups and the grand total 1030,7
    kinds = [r.kind for r in le.rows]
    assert kinds.count("SUBTOTAL") == 4 and kinds.count("TOTAL") == 1 and kinds.count("SECTION_HEADER") == 4


def test_f0201_p18_with_page_tokens_reads_the_outlined_row() -> None:
    tokens = cached_token_dir("F0201", [18])
    if tokens is None:
        pytest.skip("no PageTokens for F0201 p18 in the token cache (inspector-batch recognize)")
    import pymupdf

    from inspector_tables.testing import train_path

    doc = pymupdf.open(train_path("F0201"))
    les = explication.parse_page(PageSource(doc, "F0201", tokens).page(18))
    acc = compare([k for le in les for k in explication_keys(le.rows)], gt_rows(DATA_DIR / GT[("F0201", 18)]))
    assert acc.exact >= 118 and ("DATA", "193", "Помещение временного хранения пищевых отходов с местом обработки бачков",
                                 7.6, "В4") in [k for le in les for k in explication_keys(le.rows)]  # fmt: skip


def test_pd_twin_of_the_explication_parses_rotated_sheet(open_train) -> None:
    """F0156 p27 (PD АР, /Rotate 270): the same school; its groups hold the same double counts."""
    (le,) = _parse(open_train, "F0156", 27)
    assert sum(1 for r in le.rows if r.kind == "DATA") >= 95
    kinds = [(c["kind"], c["passed"]) for c in le.checks]
    assert kinds.count(("SUBZONE_DOUBLE_COUNT", False)) == 2
    assert not any(r.name.startswith(("Условные", "АНО/")) for r in le.rows)  # the title block is not a row
