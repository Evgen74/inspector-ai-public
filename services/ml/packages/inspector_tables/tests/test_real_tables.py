"""TEP, SPEC_21110, CHANGE_LOG, ID_REGISTRY and AOSR on real TRAIN pages (values checked visually against the
rendered pages; the expected rows are written out here)."""

from __future__ import annotations

import pytest

from inspector_tables import aosr, changelog, registry, spec21110, tep
from inspector_tables.pagesource import PageSource

pytestmark = pytest.mark.data

# (row_no, indicator start, value) — read off the rendered pages (96: «every row label→value exact»)
F0154_P13 = [
    ("1", "Общая площадь", 13060.0), ("2", "Площадь застройки, в том числе:", 4629.7), ("2.1", "Здание школы", 4620.9),
    ("3.", "Площадь покрытий, в том числе:", 5201.17), ("3.1", "Площадь асфальтобетонного покрытия проездов", 1270.8),
    ("3.2", "Площадь асфальтобетонного покрытия отмостки", 355.23),
    ("3.3", "Площадь покрытия из бетонной плитки с возможностью проезда пожарной техники", 1143.77),
    ("3.4", "Площадь резинового покрытия", 2113.86), ("3.5", "Площадь резинового покрытия с возможностью проезда пожарной техники", 115.65),
    ("3.6", "Площадь песчаного покрытия (прыжковая яма)", 19.25), ("3.7", "Площадь покрытия TerraWay", 49.71),
    ("3.8", "Площадь покрытия из газонное решетки с возможность проезда пожарной техники", 132.9),
    ("4", "Площадь озеленения, в том числе:", 3158.02), ("4.1", "Площадь посевного газона", 2685.46),
    ("4.2", "Площадь цветников", 472.56), ("5", "Площадь подпорной стены", 71.11),
]  # fmt: skip
F0101_P9 = [
    ("1", "Площадь земельного участка", None, "0,14/1 401"), ("2", "Площадь застройки, в т.ч.:", 1225.8, ""),
    ("2.1", "Площадь застройки наземной части", 767.0, ""), ("2.2", "Площадь застройки подземной части, выходящая за контур надземной части", 458.8, ""),
    ("3", "Площадь жилого здания, в т. ч.:", 17140.2, "-"), ("3.1", "наземная площадь, в т. ч.:", 13812.0, ""),
    ("3.1.1", "Наземная площадь без террас", 12830.1, ""), ("3.1.2", "террасы в уровне 2-го этажа", 86.9, ""),
    ("3.1.3", "террасы в уровне 16-го этажа", 895.0, ""), ("3.2", "подземная площадь объекта капитального строительства", 3328.2, "-"),
    ("4", "Количество этажей, в т.ч.:", None, ""), (None, "Корпус 1", 19.0, ""), (None, "Корпус 2", 16.0, ""),
    ("5", "Абсолютная высота объекта капитального строительства", 233.7, ""), ("6", "Высота объекта капитального строительства", 74.5, "74,5"),
    ("7", "Плотность застройки", 99.98, ""), ("8", "Суммарная поэтажная площадь объекта в габаритах наружных стен, в т.ч.:", 13997.9, "14000"),
    (None, "Нежилая", 301.2, "295"), (None, "Жилая, в т.ч.:", 13696.7, ""), ("9", "Строительный объем, в т.ч.:", 69201.0, ""),
    (None, "подземная часть, в т.ч.:", 16454.6, ""), (None, "наземная часть, в т.ч.:", 52731.4, ""),
    ("10", "Общая площадь квартир, в т.ч.:", 9608.9, ""), ("10.1", "Площадь квартир, в т.ч.:", 9599.0, ""),
    (None, "Корпус 1", 5782.4, ""), (None, "Корпус 2", 3816.6, ""), ("10.2", "площадь неотапливаемых помещений с коэффициентом", 9.9, ""),
]  # fmt: skip


def _page(open_train, fid: str, pg: int):
    return PageSource(open_train(fid), fid).page(pg)


def test_tep_f0154_p13_every_row_label_to_value(open_train) -> None:
    tables = tep.parse_page(_page(open_train, "F0154", 13))
    assert len(tables) == 2
    rows = [(r.row_no, r.indicator, r.value) for r in tables[0].rows]
    assert rows == F0154_P13
    assert [(r.indicator, r.value) for r in tables[1].rows] == [
        ("Площадь асфальтобетонного покрытия проездов", 22.0)
    ]
    assert all(c["passed"] for c in tables[0].checks)


def test_tep_f0101_p9_rows_limits_and_real_inconsistencies(open_train) -> None:
    (lt,) = tep.parse_page(_page(open_train, "F0101", 9))
    rows = [(r.row_no, r.indicator, r.value, r.limit_raw) for r in lt.rows if r.kind != "SECTION_HEADER"]
    assert rows == F0101_P9
    codes = {r.indicator: r.param_code for r in lt.rows}
    assert (
        codes["Площадь застройки, в т.ч.:"] == "PZ-001" and codes["Строительный объем, в т.ч.:"] == "PZ-004"
    )
    assert codes["подземная часть, в т.ч.:"] == "PZ-005" and codes["наземная часть, в т.ч.:"] == "PZ-006"
    failed = sorted((c["kind"], c["actual"], c["expected"]) for c in lt.checks if not c["passed"])
    # the building volume is printed in «кв. м.» and its parts sum to 69 186,0, not 69 201,0: document errors
    assert failed == [("SUM_MATCHES_TOTAL", 69201.0, 69186.0), ("UNIT_CONSISTENT", "кв. м.", "м³")]


def test_spec_21110_supply_units_and_the_warm_floor_regulator(open_train) -> None:
    (ls,) = spec21110.parse_page(_page(open_train, "F0171", 105))
    data = [
        (i.cells.get("position"), i.cells.get("type_mark"), i.cells.get("unit"), i.quantity)
        for i in ls.items
        if i.kind == "DATA"
    ]
    assert data == [("П1", "V1.40-4.0x30.R", "компл.", 1.0), ("П2", "V1.0.P63.R-5,5x15", "компл.", 1.0),
                    ("П2.1", "WNP 60-35/28R.2D", "компл.", 1.0), ("П3", "WRW 80-50/40.4D", "компл.", 1.0),
                    ("П4", "WNP 70-40/31.2D", "компл.", 1.0)]  # fmt: skip
    assert [i.cells["name"] for i in ls.items if i.kind == "SECTION_HEADER"] == [
        "ОБОРУДОВАНИЕ",
        "Общеобменная вентиляция",
    ]
    (ls136,) = spec21110.parse_page(_page(open_train, "F0171", 136))
    warm = spec21110.find_items(ls136.items, r"тепл\w* пол")
    assert [(i.cells["type_mark"], i.quantity) for i in warm] == [("Multibox C/RTL", 2.0)]


def test_change_log_permits_of_the_rd_binders(open_train) -> None:
    (lg,) = changelog.parse_page(_page(open_train, "F0201", 6))
    assert lg.permit_no == "839-24" and lg.document_code == "АНО/150321/1-РД-ОВ1"
    assert [(r.cells["change_no"], r.cells["sheets_changed"]) for r in lg.rows] == [
        ("4", "1"),
        ("4", "3"),
        ("4", "10"),
        ("4", "18"),
    ]
    assert "В пом. 195 добавлены системы кондиционирования" in lg.rows[2].cells["note"]
    (lg2,) = changelog.parse_page(_page(open_train, "F0202", 6))
    assert lg2.permit_no == "861-24" and {r.cells["change_no"] for r in lg2.rows} == {"3"}
    assert any("пом.269" in r.cells["note"] for r in lg2.rows)


def test_registry_of_an_act_with_sections_and_page_continuation(open_train) -> None:
    src = PageSource(open_train("F0004"), "F0004")
    (reg,) = registry.parse_page(src.page(5))
    registry.parse_page(src.page(6), reg)
    registry.finalize(reg)
    data = [r for r in reg.rows if r.kind == "DATA"]
    assert len(data) == 15
    assert (
        next(r.cells["doc_name"] for r in reg.rows if r.kind == "SECTION_HEADER")
        == "Исполнительные геодезические схемы"
    )
    assert (data[1].doc_no, data[1].doc_date, data[1].cells["note"]) == ("284", "2026-02-20", "Строймат и К")
    assert data[-1].doc_no == "18-000002344" and data[-1].cells["doc_name"].endswith(
        "П4F(I)200W8"
    )  # p6 continuation
    assert all(c["passed"] for c in reg.checks)


def test_aosr_fields_and_cited_documents_rt10(open_train) -> None:
    """RT-10: п.2 of the Тюменская acts, and the cipher typo of п.4 in F0196."""

    def act(fid: str):
        d = open_train(fid)
        return aosr.parse_act_text("\n".join(d[i].get_text() for i in range(min(3, d.page_count))))

    a195, a196 = act("F0195"), act("F0196")
    assert a195.fields_found == 9 and a196.fields_found == 9
    assert {(r["code"], r["revision"]) for r in a195.doc_refs if r["source"] == "rd_refs"} == {
        ("АНО/150321/1-РД-ОВ2.1", 3)
    }
    assert {(r["code"], r["revision"]) for r in a196.doc_refs if r["source"] == "rd_refs"} == {
        ("АНО/150321/1-РД-ОВ1", 3)
    }
    assert [r["code"] for r in a196.doc_refs if r["source"] == "quality_docs"] == ["АНО1301211-Р-ОВ1"]
    assert (a196.cells["act_no"], a196.cells["start_date"], a196.cells["end_date"]) == (
        "1/ОВ",
        "2024-12-20",
        "2025-04-07",
    )
    a1 = act("F0001")
    assert a1.cells["act_no"] == "1БТ" and a1.cells["next_works"] == "Устройство стены в грунте"
