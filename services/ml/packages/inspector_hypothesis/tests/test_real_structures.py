"""Structures met on the real Тюменская artifacts (AG-02B layouts, AG-02C tables, 2026-09-28 integration run), pinned
with their real values so the rules keep reading them right:

- the basement explication of F0201 p17 recognised as two tables side by side, «ИТОГО: 524,0» closing both;
- the 1st-floor explication with group totals, a last group closed by a SUBTOTAL and «ИТОГО 1-ый этаж» over all;
- the basement explication of F0202 p15 whose rows (536,59 м²) do not add up to its «ИТОГО: 532,1» — a real error;
- the same explication reprinted on the plans of ОВ1 and ОВ2.1: one suspicion, every copy as evidence;
- «NoАНО/150321/1-РД-ОВ2.1» (a number sign glued to the cipher) in an act;
- references with the cited page's own cipher, and the RD page of the current «Изм.» row as evidence.
"""

from __future__ import annotations

import pytest

from inspector_hypothesis import HypothesisConfig, HypothesisInputs, MemoryPageSource, run_hypotheses
from inspector_hypothesis.facts import FactBuilder, explication_blocks, explication_chains
from inspector_hypothesis.rules import RuleEngine, load_seed_rules
from inspector_hypothesis.suspicion import reference
from inspector_hypothesis.testing import (
    OBJECT_ID,
    TYUMEN_P18_ROOMS,
    TYUMEN_P18_SUBZONE,
    doc,
    explication,
    layout,
    table_artifacts,
    title_block,
    typed_table,
)

BASEMENT_TITLE = "Экспликация помещений подвала на отм. -2,950"
# F0201 p17, left column (12 rows) and right column (3 rows + totals), as AG-02C returns them
F0201_BASEMENT_LEFT = [
    ("001", "ИТП", "84.9"),
    ("001.1", "Лестница Л-1", "10.5"),
    ("002", "Коридор", "39.3"),
    ("002.1", "Коридор", "20.3"),
    ("003", "Тамбур", "9.7"),
    ("004", "Лестница Л-2", "25.8"),
    ("005", "Водомерный узел", "21.9"),
    ("006", "Венткамера", "71.4"),
    ("008", "Помещение кабельного ввода", "16.9"),
    ("009", "Насосная", "41.7"),
    ("010", "Тамбур", "24.5"),
    ("011", "Лестница Л-3", "26.5"),
]
F0201_BASEMENT_RIGHT = [
    ("012", "Венткамера", "99.7"),
    ("013", "Форкамера", "15.89"),
    ("014", "Форкамера", "15.0"),
]
# F0202 p15 (ОВ2.1, изм. 3): the same basement, edited rooms, total not updated
F0202_BASEMENT_LEFT = [
    ("001", "ИТП", "84.9"),
    ("001.1", "Лестница Л-1", "10.5"),
    ("002", "Коридор", "59.6"),
    ("003", "Тамбур", "9.7"),
    ("003.1", "Помещение СС", "4.2"),
    ("004", "Лестница Л-2", "25.8"),
    ("005", "Водомерный узел", "21.9"),
    ("006", "Венткамера", "86.4"),
    ("008", "техническое пространство (кабельный ввод)", "25.9"),
    ("009", "Насосная", "41.7"),
    ("010", "Тамбур", "17.5"),
]
F0202_BASEMENT_RIGHT = [
    ("010.1", "Помещение СС", "6.4"),
    ("011", "Лестница Л-3", "26.5"),
    ("012", "Венткамера", "115.59"),
]


def _data(rows):
    return [{"room_no": n, "name": name, "area_m2": a, "_kind": "DATA"} for n, name, a in rows]


def _basement(file_id: str, left, right, total: str, page_no: int):
    t1 = typed_table(f"{file_id}-p{page_no}-EXPLICATION-1", "EXPLICATION", _data(left), page_no=page_no,
                     title=BASEMENT_TITLE)  # fmt: skip
    rows2 = [
        *_data(right),
        {"name": "ИТОГО:", "area_m2": total, "_kind": "TOTAL"},
        {"room_no": "007", "name": "Техническое пространство", "area_m2": "3793.1", "_kind": "DATA"},
        {"name": "ИТОГО:", "area_m2": "3793.1", "_kind": "TOTAL"},
    ]
    t2 = typed_table(f"{file_id}-p{page_no}-EXPLICATION-2", "EXPLICATION", rows2, page_no=page_no,
                     title=BASEMENT_TITLE)  # fmt: skip
    return t1, t2


def _inputs(tables_by_file, layouts=None):
    documents = {
        "F0201": doc("F0201", "RD", "OV", 676),
        "F0202": doc("F0202", "RD", "OV", 36),
        "F0196": doc("F0196", "ID", "OV", 3),
        "F0195": doc("F0195", "ID", "OV", 2),
    }
    tables = {fid: table_artifacts(fid, "RD" if fid in ("F0201", "F0202") else "ID", ts)
              for fid, ts in tables_by_file.items()}  # fmt: skip
    return HypothesisInputs(OBJECT_ID, documents, MemoryPageSource(), layouts=layouts or {}, tables=tables)


def _outcomes(inputs, rule_code):
    facts = FactBuilder(inputs).build()
    return RuleEngine([load_seed_rules().get(rule_code)]).evaluate(facts)


def test_a_column_split_explication_is_summed_across_both_tables():
    t1, t2 = _basement("F0201", F0201_BASEMENT_LEFT, F0201_BASEMENT_RIGHT, "524.0", 17)
    assert [[t.table_id for t in c] for c in explication_chains([t2, t1])] == [[t1.table_id, t2.table_id]]
    blocks = explication_blocks([t1, t2], file_id="F0201", stage="RD")
    assert [(round(sum(r["area_m2"] for r in b["rows"]), 2), b["total"]) for b in blocks] == [
        (523.99, 524.0),
        (3793.1, 3793.1),
    ]
    assert blocks[0]["continued_from"] == [t1.table_id]
    statuses = [o.status for o in _outcomes(_inputs({"F0201": [t1, t2]}), "HR-LOG-005")]
    assert statuses == ["SATISFIED", "NOT_APPLICABLE"]  # the one-room block is below the 2-row minimum


def test_tables_of_another_title_or_a_closed_table_do_not_chain():
    t1, t2 = _basement("F0201", F0201_BASEMENT_LEFT, F0201_BASEMENT_RIGHT, "524.0", 17)
    other = t2.model_copy(update={"title": "Экспликация помещений 1 этажа"})
    assert len(explication_chains([t1, other])) == 2
    closed = explication("F0201-x", [("1", "А", "10.0"), ("2", "Б", "5.0")], ("Итого", "15.0"), page_no=17,
                         title=BASEMENT_TITLE)  # fmt: skip
    assert len(explication_chains([closed, t2])) == 2


def test_the_real_basement_total_of_f0202_is_flagged():
    t1, t2 = _basement("F0202", F0202_BASEMENT_LEFT, F0202_BASEMENT_RIGHT, "532.1", 15)
    [o, _] = _outcomes(_inputs({"F0202": [t1, t2]}), "HR-LOG-005")
    assert o.status == "EMITTED"
    assert (round(o.values["sum_rows"], 2), o.values["total"], round(o.values["delta"], 2)) == (
        536.59,
        532.1,
        -4.49,
    )
    assert "536,59 м² не равна итогу «ИТОГО:» 532,10 м²: расхождение −4,49 м²" in o.render(
        o.rule.message_template
    )


def _first_floor(total_floor: str):
    """Groups closed by TOTAL rows, the last one by a SUBTOTAL, then the floor total (F0201 p18 layout)."""
    rows: list[dict] = [{"name": "Группа А", "_kind": "SECTION_HEADER"}]
    rows += _data([("101", "Тамбур", "8.6"), ("102", "Вестибюль", "134.0")])
    rows += [{"name": "ИТОГО:", "area_m2": "142.6", "_kind": "TOTAL"}]
    rows += [{"name": "Группа Б", "_kind": "SECTION_HEADER"}]
    rows += _data([("124", "Тамбур", "14.3"), ("125", "Тамбур", "14.2")])
    rows += [{"name": "ИТОГО", "area_m2": "28.5", "_kind": "TOTAL"}]
    rows += [{"name": "Спортивная группа", "_kind": "SECTION_HEADER"}]
    rows += _data([("1001", "Рекреация", "61.2"), ("1005", "Раздевальная", "21.7")])
    rows += [{"name": "", "area_m2": "82.9", "_kind": "SUBTOTAL"}]
    rows += [{"name": "ИТОГО 1-ый этаж:", "area_m2": total_floor, "_kind": "TOTAL"}]
    return typed_table("F0201-p18-EXPLICATION-3", "EXPLICATION", rows, page_no=18,
                       title="Экспликация помещений 1 этажа")  # fmt: skip


def test_a_floor_total_over_group_totals_is_checked_against_the_groups():
    blocks = explication_blocks(_first_floor("254.0"), file_id="F0201", stage="RD")
    grand = blocks[-1]
    assert (grand["level"], grand["hierarchy_unresolved"], grand["n_rows"]) == ("GRAND", False, 4)
    statuses = [o.status for o in _outcomes(_inputs({"F0201": [_first_floor("254.0")]}), "HR-LOG-005")]
    assert statuses == ["SATISFIED"] * 4  # two groups, the subtotal of the last one, the floor


def test_an_unresolved_floor_total_is_not_reported_as_an_arithmetic_error():
    blocks = explication_blocks(_first_floor("4168.9"), file_id="F0201", stage="RD")
    assert (blocks[-1]["level"], blocks[-1]["hierarchy_unresolved"]) == ("GRAND", True)
    statuses = [o.status for o in _outcomes(_inputs({"F0201": [_first_floor("4168.9")]}), "HR-LOG-005")]
    assert statuses == ["SATISFIED", "SATISFIED", "SATISFIED", "NOT_APPLICABLE"]


def test_a_large_gap_is_a_recognition_gap_not_a_finding():
    t = explication("F0201-t", [("1", "А", "100.0"), ("2", "Б", "30.0")], ("ИТОГО:", "524.0"), page_no=17)
    [o] = _outcomes(_inputs({"F0201": [t]}), "HR-LOG-005")
    assert o.status == "NOT_APPLICABLE"


def test_copies_of_one_explication_in_two_documents_are_one_suspicion():
    def p18(fid, page_no):
        return explication(f"{fid}-p{page_no}-EXPLICATION-1", TYUMEN_P18_ROOMS, ("ИТОГО:", "1079.9"),
                           subzones=TYUMEN_P18_SUBZONE, page_no=page_no)  # fmt: skip

    inputs = _inputs({"F0201": [p18("F0201", 18), p18("F0201", 23)], "F0202": [p18("F0202", 16)]})
    r = run_hypotheses(inputs, HypothesisConfig(enable_free=False))
    [s] = [s for s in r.suspicions if s.rule_code == "HR-LOG-011"]
    assert sorted((e.file_id, e.pdf_page_number) for e in s.evidence) == [
        ("F0201", 18),
        ("F0201", 23),
        ("F0202", 16),
    ]
    assert len(s.explanation["copies"]) == 3
    assert s.rd_reference == "F0201, стр.18; F0201, стр.23; F0202, стр.16"
    [row] = r.section6_rows(1)
    assert row.no == 1 and row.card_ref == "Б.1"


def test_a_number_sign_glued_to_a_cipher_is_not_part_of_it():
    blocks = [title_block(14, "АНО/150321/1-РД-ОВ2.1", 1, [("3", "22.08.2024")])]
    act = typed_table("F0195-aosr-1", "AOSR", [{
        "act_no": "1-ОВ2.1", "act_date": "2024-12-20", "work_name": "Монтаж системы отопления",
        "rd_refs": "АНО/150321/1-РД-ОВ2.1 - изм. 3", "quality_docs": "Исполнительные чертежи NoАНО/150321/1-РД-ОВ2.1",
    }], page_no=1)  # fmt: skip
    inputs = _inputs({"F0195": [act]}, layouts={"F0202": layout("F0202", "RD", 36, blocks)})
    outcomes = _outcomes(inputs, "HR-LOG-002")
    # п.2 «…ОВ2.1 - изм. 3» and п.4 «NoАНО…ОВ2.1»: one known cipher, cited once (with its revision)
    assert [(o.item["code"], o.item["field_ru"], o.item["revision"], o.status) for o in outcomes] == [
        ("АНО/150321/1-РД-ОВ2.1", "п. 2", 3, "SATISFIED")
    ]


def test_references_carry_the_cited_pages_own_cipher_and_the_revision_page():
    blocks = [title_block(14, "АНО/150321/1-РД-ОВ1", 1, [("4", "11.08.2024"), ("2", "20.03.2024")])]
    blocks += [title_block(18, "АНО/150321/1-РД-ОВ1", 5), title_block(19, None, 6)]
    blocks += [title_block(p, "АНО/150321/1-РД-ОВ1.С", p - 99) for p in range(100, 140)]
    layouts = {"F0201": layout("F0201", "RD", 676, blocks)}
    act = typed_table("F0196-aosr-1", "AOSR", [{"act_no": "1/ОВ", "act_date": "2025-04-07",
                      "rd_refs": "АНО/150321/1-РД-ОВ1 - изм. 3"}], page_no=1)  # fmt: skip
    inputs = _inputs({"F0196": [act]}, layouts=layouts)
    # the file's majority cipher is the specification; page 18 and the unread page 19 belong to the drawings
    assert inputs.page_code("F0201", 18) == inputs.page_code("F0201", 19) == "АНО/150321/1-РД-ОВ1"
    assert inputs.page_code("F0201", 120) == "АНО/150321/1-РД-ОВ1.С"
    assert (
        reference(inputs, {"file_id": "F0201", "pdf_page_number": 18}) == "АНО/150321/1-РД-ОВ1, л.5, стр.18"
    )
    r = run_hypotheses(inputs, HypothesisConfig(enable_free=False))
    [s] = [s for s in r.suspicions if s.rule_code == "HR-LOG-009"]
    assert s.rd_reference == "АНО/150321/1-РД-ОВ1, л.1, стр.14"  # the sheet with the «Изм. 4» row
    assert s.id_reference == "F0196, стр.1"
    assert str(s.review_priority) == "HIGH" and s.confidence == pytest.approx(0.85)


def test_the_plots_tep_total_area_is_the_plot_area():
    """F0154 p13 «2.5. Технико-экономические показатели земельного участка» (real rows)."""
    rows = [
        {"indicator": "1 Общая площадь", "unit": "м2", "value": "13060,00", "_kind": "DATA"},
        {"indicator": "2 Площадь застройки, в том числе:", "unit": "м2", "value": "4629,70", "_kind": "DATA"},
        {"indicator": "2.1 Здание школы", "unit": "м2", "value": "4620,90", "_kind": "SUBZONE"},
        {
            "indicator": "4 Площадь озеленения, в том числе:",
            "unit": "м2",
            "value": "3158,02",
            "_kind": "DATA",
        },
    ]
    plot = typed_table("F0154-p13-TEP-1", "TEP", rows, page_no=13,
                       title="2.5. Технико-экономические показатели земельного участка.")  # fmt: skip
    inputs = HypothesisInputs(
        OBJECT_ID,
        {"F0154": doc("F0154", "PD", "PZ", 40)},
        MemoryPageSource(),
        tables={"F0154": table_artifacts("F0154", "PD", [plot])},
    )
    tep = FactBuilder(inputs).build()["tables"]["TEP"]["PD"]
    assert tep["plot_area_m2"] == 13060.0 and "total_area_m2" not in tep
    building = plot.model_copy(update={"title": "Технико-экономические показатели здания"})
    inputs.tables = {"F0154": table_artifacts("F0154", "PD", [building])}
    assert FactBuilder(inputs).build()["tables"]["TEP"]["PD"]["total_area_m2"] == 13060.0


def test_a_file_name_cipher_is_read_up_to_the_underscore():
    documents = {"F0202": doc("F0202", "RD", "OV", 36, name="АНО-150321-1-РД-ОВ2.1_изм. 3_в1.pdf")}
    inputs = HypothesisInputs(OBJECT_ID, documents, MemoryPageSource())
    rd = FactBuilder(inputs).build()["documents"]["RD"]
    assert rd["code_keys"] == ["АНО1503211РОВ21"]
    assert rd["by_key"]["АНО1503211РОВ21"]["current_revision"] is None  # a file name never gives a revision
