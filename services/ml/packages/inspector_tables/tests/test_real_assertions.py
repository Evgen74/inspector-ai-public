"""PD element–room assertions, the air-exchange system lists and the absence proof on real TRAIN pages
(RT-05, RT-06 of 95_tyumen_dev_fixtures.json; the G-TR-002 warm floor and the G-TR-003/004 local exhausts)."""

from __future__ import annotations

import pytest

from inspector_tables import absence, airx, assertions, spec21110
from inspector_tables.pagesource import PageSource
from inspector_tables.testing import cached_token_dir

pytestmark = pytest.mark.data
GOLD_WARM_FLOOR_ROOMS = {"267", "270", "271", "272"}


def test_rt05_text_assertion_of_the_warm_floor(open_train) -> None:
    page = PageSource(open_train("F0171"), "F0171").page(11)
    found = [a for a in assertions.text_assertions(page) if a.family == "WARM_FLOOR"]
    assert len(found) == 1
    a = found[0]
    assert set(a.rooms) == GOLD_WARM_FLOOR_ROOMS and a.channel == "TEXT" and a.confidence == 0.9
    assert "теплые полы" in a.text and a.box is not None


def test_warm_floor_leaders_on_the_pd_heating_schematic(open_train) -> None:
    """F0171 p99 (the gold PD page): the regulator's two leader lines point into rooms 267/270 and 271/272."""
    page = PageSource(open_train("F0171"), "F0171").page(99)
    found = [a for a in assertions.label_assertions(page, only=("WARM_FLOOR",)) if a.extra.get("leaders")]
    assert len(found) == 1
    assert set(found[0].rooms) == GOLD_WARM_FLOOR_ROOMS and found[0].extra["leaders"] == 2
    x0, y0, _x1, _y1 = page.norm_bbox(found[0].box)
    assert (
        0.28 < x0 < 0.34 and 0.35 < y0 < 0.45
    )  # the markup zone of G-TR-002 on p99: [0.283, 0.350, 0.341, 0.508]


def test_warm_floor_regulator_in_the_pd_specification(open_train) -> None:
    (ls,) = spec21110.parse_page(PageSource(open_train("F0171"), "F0171").page(136))
    found = [a for a in assertions.spec_assertions(ls.items, "F0171") if a.family == "WARM_FLOOR"]
    assert [(a.quantity, a.rooms) for a in found] == [(2.0, [])]


def test_pd_air_exchange_table_lists_the_local_exhausts_of_the_gold_rooms() -> None:
    tokens = cached_token_dir("F0171", [79, 81])
    if tokens is None:
        pytest.skip(
            "no PageTokens of F0171 p79–81 in the token cache (inspector-batch recognize --pages 79-81)"
        )
    import pymupdf

    from inspector_tables.testing import train_path

    src = PageSource(pymupdf.open(train_path("F0171")), "F0171", tokens)
    rooms = {}
    for pg in (79, 81):
        _, rs = airx.parse_page(src.page(pg))
        rooms.update({r.room_no: r for r in rs})
    # 95 §3.3 (F0171 p88): 142 → В2.4–2.6; 140 → В2.7–2.9; 147 → В2.10; 198 → В2.2, В2.3; 314 → В3.1, В3.2
    assert rooms["140"].systems["sys_mo"] == ["В2.7", "В2.8", "В2.9"]
    assert rooms["142"].systems["sys_mo"] == ["В2.4", "В2.5", "В2.6"]
    assert rooms["147"].systems["sys_mo"] == ["В2.10"]
    assert rooms["198"].systems["sys_mo"] == ["В2.2", "В2.3"]
    assert rooms["314"].systems["sys_mo"] == ["В3.1", "В3.2"]
    assert rooms["0012"].name == "Венткамера"  # this PD table prints the vent chamber as «0012»


def test_rt06_absence_needs_every_rd_page_read(open_train) -> None:
    doc = open_train("F0202")
    pages = list(range(1, doc.page_count + 1))
    no_ocr = absence.prove_absence([(PageSource(doc, "F0202"), pages)], "WARM_FLOOR")
    assert no_ocr.absent is None  # outlined sheets and scans without tokens: not provable
    assert {p for _, p in no_ocr.unread} >= set(range(14, 37))
    pd = absence.prove_absence([(PageSource(open_train("F0171"), "F0171"), [11, 99, 136])], "WARM_FLOOR")
    assert pd.absent is False and {h.page_no for h in pd.hits} >= {11, 136}
    tokens = cached_token_dir("F0202", pages)
    if tokens is None:
        pytest.skip("no PageTokens of all F0202 pages in the token cache")
    proof = absence.prove_absence([(PageSource(doc, "F0202", tokens), pages)], "WARM_FLOOR")
    assert proof.absent is True and proof.pages_read == doc.page_count and proof.coverage == 1.0
