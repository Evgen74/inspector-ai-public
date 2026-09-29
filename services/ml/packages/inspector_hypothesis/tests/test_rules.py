"""The 12 seed Logical_Rules on facts built from contract artifacts (tables, values, layouts, pages)."""

from __future__ import annotations

import json

import pytest

from inspector_common.contracts.models import ExtractedValue
from inspector_common.params import load_params
from inspector_hypothesis import HypothesisConfig, HypothesisInputs, MemoryPageSource, run_hypotheses
from inspector_hypothesis.facts import FactBuilder, explication_blocks, referenced_families
from inspector_hypothesis.rules import LogicalRule, RuleEngine, load_seed_rules, parse_rule_set
from inspector_hypothesis.testing import (
    A0_PORTRAIT,
    ALT79B_ROOMS,
    OBJECT_ID,
    SHA,
    TYUMEN_P18_ROOMS,
    TYUMEN_P18_SUBZONE,
    doc,
    explication,
    filler,
    layout,
    page,
    table_artifacts,
    title_block,
    typed_table,
)


def _inputs(*, tables=None, values=(), layouts=None, documents=None, pages=()):
    documents = documents or {"F0201": doc("F0201", "RD", "OV", 676), "F0171": doc("F0171", "PD", "OV", 177)}
    return HypothesisInputs(
        OBJECT_ID,
        documents,
        MemoryPageSource(pages),
        layouts=layouts or {},
        tables=tables or {},
        values=list(values),
    )


def _outcomes(inputs, rule_code):
    rules = load_seed_rules()
    rule = rules.get(rule_code)
    facts = FactBuilder(inputs).build(
        referenced_families([rule.condition, rule.expected, rule.applicability])
    )
    return RuleEngine([rule]).evaluate(facts)


def _value(code, stage, value, *, location=None, file_id="F0171", page_no=5):
    return ExtractedValue(
        value_id=f"{code}-{stage}-{location or 'OBJECT'}-{value}",
        object_id=OBJECT_ID,
        file_id=file_id,
        file_sha256=SHA.get(file_id, "0" * 64),
        stage=stage,
        page_no=page_no,
        param_code=code,
        location=location,
        value_raw=str(value),
        value_norm={"type": "number", "value": value},
        method="TABLE",
        confidence=0.95,
        quality_flag="OK",
        pipeline_version="test",
    )


# ── the rule set ──────────────────────────────────────────────────────────────────────────────────


def test_seed_rule_set_has_12_valid_active_rules_with_the_tz_fields():
    rs = load_seed_rules()
    assert len(rs.rules) == len(rs.active) == 12
    assert [r.rule_code for r in rs.rules] == [f"HR-LOG-{n:03d}" for n in range(1, 13)]
    assert rs.language == "IAI-Logic v1" and rs.rules_set_version
    for r in rs.rules:
        d = r.model_dump(mode="json")
        for key in ("id", "rule_name", "condition", "expected", "normative_base", "is_active"):  # ТЗ §10 #9
            assert key in d
        assert str(r.discovery_method) == "LOGICAL_ANALYSIS"
        assert r.message_template and r.base_confidence > 0
    assert len(rs.sha256) == 64


def test_rules_cover_the_sub_checks_moved_out_of_the_matrix():
    by_param = {code: r.rule_code for r in load_seed_rules().rules for code in r.overlaps_matrix_codes}
    for moved in load_params().document["moved_to_logical_rules"]:
        assert moved["code"] in by_param, moved["sub_id"]


def test_malformed_rules_are_rejected():
    good = load_seed_rules().get("HR-LOG-005").model_dump(mode="json")
    with pytest.raises(ValueError):
        LogicalRule.model_validate({**good, "condition": {"exec": ["x"]}})
    with pytest.raises(ValueError):
        LogicalRule.model_validate({**good, "rule_code": "LOG-5"})
    with pytest.raises(ValueError):
        parse_rule_set({"rules_set_version": "x", "rules": [good, good]})


# ── explications: HR-LOG-005 and HR-LOG-011 ─────────────────────────────────────────────────────────


def test_hr_log_005_fires_on_the_alt79b_pattern_2795_04_vs_2797_27():
    t = explication(
        "ALT79B-PD",
        ALT79B_ROOMS,
        ("Общий итог по этажу", "2797.27"),
        title="Спецификация помещений 1-го этажа",
    )
    inputs = _inputs(tables={"F0171": table_artifacts("F0171", "PD", [t])})
    [o] = _outcomes(inputs, "HR-LOG-005")
    assert o.status == "EMITTED"
    assert o.values["sum_rows"] == pytest.approx(2795.04)
    assert o.values["total"] == pytest.approx(2797.27)
    assert o.values["delta"] == pytest.approx(2.23)
    msg = o.render(o.rule.message_template)
    assert "2795,04 м²" in msg and "2797,27 м²" in msg and "2,23 м²" in msg and "Общий итог по этажу" in msg


def test_hr_log_005_tolerates_rounding_and_abstains_on_missing_values():
    rooms = [("1", "А", "2811.06")]
    rounding = explication("RD", [*rooms, ("2", "Б", "0.00")], ("Итого", "2811.07"))
    inputs = _inputs(tables={"F0201": table_artifacts("F0201", "RD", [rounding])})
    assert [o.status for o in _outcomes(inputs, "HR-LOG-005")] == ["SATISFIED"]
    broken = explication("RD2", [("1", "А", "10.0"), ("2", "Б", "н/д")], ("Итого", "25.0"))
    inputs = _inputs(tables={"F0201": table_artifacts("F0201", "RD", [broken])})
    assert [o.status for o in _outcomes(inputs, "HR-LOG-005")] == ["UNKNOWN"]


def test_hr_log_011_fires_on_the_tyumen_subzone_double_count_and_005_stays_silent():
    t = explication(
        "F0201-p18-1",
        TYUMEN_P18_ROOMS,
        ("ИТОГО:", "1079.9"),
        subzones=TYUMEN_P18_SUBZONE,
        page_no=18,
        title="Экспликация помещений 1 этажа",
    )
    inputs = _inputs(tables={"F0201": table_artifacts("F0201", "RD", [t])})
    [o11] = _outcomes(inputs, "HR-LOG-011")
    [o05] = _outcomes(inputs, "HR-LOG-005")
    assert o11.status == "EMITTED" and o05.status == "SATISFIED"
    assert o11.values["sum_rows"] == pytest.approx(1049.5)
    assert o11.values["sum_sub"] == pytest.approx(30.4)
    msg = o11.render(o11.rule.message_template)
    assert "1079,9 м²" in msg and "30,4 м²" in msg and "1049,5 м²" in msg
    assert o11.stage == "RD" and o11.evidence[0]["pdf_page_number"] == 18


def test_explication_blocks_split_on_subtotals_and_totals():
    rows = [
        {"room_no": "1", "area_m2": "10,0", "_kind": "DATA"},
        {"room_no": "2", "area_m2": "5,5", "_kind": "DATA"},
        {"name": "Итого по секции 1", "area_m2": "15,5", "_kind": "SUBTOTAL"},
        {"room_no": "3", "area_m2": "4,0", "_kind": "DATA"},
        {"name": "Итого по секции 2", "area_m2": "4,0", "_kind": "SUBTOTAL"},
        {"name": "Итого по этажу", "area_m2": "19,5", "_kind": "TOTAL"},
    ]
    blocks = explication_blocks(typed_table("T", "EXPLICATION", rows), file_id="F0201", stage="RD")
    assert [(b["total_kind"], b["n_rows"], b["total"]) for b in blocks] == [
        ("SUBTOTAL", 2, 15.5),
        ("SUBTOTAL", 1, 4.0),
        ("TOTAL", 3, 19.5),
    ]
    assert blocks[0]["decimals"] == 1


# ── ТЗ example: HR-LOG-001 ───────────────────────────────────────────────────────────────────────────


def _lift_inputs(rd_text: str):
    documents = {"F0156": doc("F0156", "RD", "AR", 2), "F0171": doc("F0171", "PD", "OV", 177)}
    pages = [page("F0156", 1, A0_PORTRAIT, [rd_text]), filler("F0156", 2)]
    return _inputs(documents=documents, pages=pages, values=[_value("PZ-007", "PD", 15)])


def test_hr_log_001_reproduces_the_tz_suspicion_example():
    r = run_hypotheses(
        _lift_inputs("План 1 этажа. Лестничная клетка. Коридор"), HypothesisConfig(enable_free=False)
    )
    [s] = [s for s in r.suspicions if s.rule_code == "HR-LOG-001"]
    tz = s.tz_view()
    assert list(tz) == [
        "suspicion_id",
        "discovery_method",
        "confidence",
        "description",
        "pd_reference",
        "rd_reference",
        "review_priority",
        "normative_base",
        "finding_status",
        "inspector_status",
    ]
    assert tz["discovery_method"] == "LOGICAL_ANALYSIS"
    assert tz["description"] == "В РД отсутствует лифтовая шахта при 15 этажах."
    assert tz["normative_base"] == "СП 54.13330.2022, п. 7.1.3"
    assert (tz["confidence"], tz["review_priority"], tz["finding_status"], tz["inspector_status"]) == (
        0.87,
        "HIGH",
        "SUSPICION",
        "PENDING",
    )
    assert tz["pd_reference"] == "F0171, стр.5"


def test_hr_log_001_is_satisfied_by_a_lift_and_unknown_without_full_rd():
    r = run_hypotheses(
        _lift_inputs("Пассажирский лифт грузоподъёмностью 1000 кг"), HypothesisConfig(enable_free=False)
    )
    assert not any(s.rule_code == "HR-LOG-001" for s in r.suspicions)
    partial = _lift_inputs("План 1 этажа")
    partial.pages._pages.pop(("F0156", 2))
    [o] = [
        o
        for o in run_hypotheses(partial, HypothesisConfig(enable_free=False)).rule_outcomes
        if o.rule.rule_code == "HR-LOG-001"
    ]
    assert o.status == "UNKNOWN"


# ── ИД rules: HR-LOG-002, -007, -008, -009, -010 ─────────────────────────────────────────────────────


def _aosr_inputs(refs: str, act_date: str = "07.04.2025"):
    documents = {
        "F0201": doc("F0201", "RD", "OV", 676),
        "F0202": doc("F0202", "RD", "OV", 36),
        "F0196": doc("F0196", "ID", "OV", 3),
    }
    layouts = {
        "F0201": layout(
            "F0201",
            "RD",
            676,
            [title_block(18, "АНО/150321/1-РД-ОВ1", 5, [("3", "20.05.2024"), ("4", "11.08.2024")])],
        ),
        "F0202": layout(
            "F0202", "RD", 36, [title_block(17, "АНО/150321/1-РД-ОВ2.1", 4, [("3", "01.03.2024")])]
        ),
    }
    aosr = typed_table(
        "F0196-aosr-1",
        "AOSR",
        [{"act_no": "1/ОВ", "act_date": act_date, "work_name": "Монтаж воздуховодов", "rd_refs": refs}],
        page_no=1,
    )
    return _inputs(
        documents=documents, layouts=layouts, tables={"F0196": table_artifacts("F0196", "ID", [aosr])}
    )


def test_hr_log_002_flags_a_cipher_absent_from_the_rd_set_and_names_the_closest():
    inputs = _aosr_inputs("Исполнительные чертежи АНО1301211-Р-ОВ1")
    [o] = _outcomes(inputs, "HR-LOG-002")
    assert o.status == "EMITTED"
    msg = o.render(o.rule.message_template)
    assert "АНО1301211-Р-ОВ1" in msg and "ближайший шифр: АНО/150321/1-РД-ОВ1" in msg
    ok = _aosr_inputs("АНО/150321/1-РД-ОВ1 - изм. 4")
    assert [o.status for o in _outcomes(ok, "HR-LOG-002")] == ["SATISFIED"]


def test_hr_log_009_flags_an_act_citing_an_outdated_revision():
    [o] = _outcomes(_aosr_inputs("АНО/150321/1-РД-ОВ1 - изм. 3"), "HR-LOG-009")
    assert o.status == "EMITTED"
    assert "изм. 3" in o.render(o.rule.message_template) and "изм. 4 от 11.08.2024" in o.render(
        o.rule.message_template
    )
    # an act dated before revision 4 was issued may cite revision 3
    [o] = _outcomes(_aosr_inputs("АНО/150321/1-РД-ОВ1 - изм. 3", act_date="01.07.2024"), "HR-LOG-009")
    assert o.status == "SATISFIED"


def test_hr_log_010_flags_an_act_dated_before_the_cited_revision():
    [o] = _outcomes(_aosr_inputs("АНО/150321/1-РД-ОВ1 - изм. 4", act_date="01.07.2024"), "HR-LOG-010")
    assert o.status == "EMITTED"
    [o] = _outcomes(_aosr_inputs("АНО/150321/1-РД-ОВ1 - изм. 4"), "HR-LOG-010")
    assert o.status == "SATISFIED"


def _works_inputs(rd_pages_read: int):
    documents = {"F0203": doc("F0203", "RD", "KR", 2), "F0197": doc("F0197", "ID", "KR", 1)}
    pages = [page("F0197", 1, A0_PORTRAIT, ["Исполнительная схема. Ремонт свай в осях 1-3"])]
    pages += [filler("F0203", p, text="Фундаментная плита. Армирование") for p in range(1, rd_pages_read + 1)]
    return _inputs(documents=documents, pages=pages)


def test_hr_log_007_id_works_without_rd_basis():
    [o] = _outcomes(_works_inputs(2), "HR-LOG-007")
    assert o.status == "EMITTED"
    assert "ремонт свай" in o.render(o.rule.message_template).lower()
    [o] = _outcomes(_works_inputs(1), "HR-LOG-007")  # RD not fully read: no claim
    assert o.status == "UNKNOWN"


def test_hr_log_008_tolerance_on_executive_schemes():
    rows = [
        {
            "element": "Плита перекрытия",
            "parameter": "Отметка верха",
            "design_value": "12.300",
            "actual_value": "12.270",
            "deviation": "-30",
            "tolerance": "±20",
            "unit": "мм",
        },
        {
            "element": "Плита перекрытия",
            "parameter": "Отметка верха",
            "deviation": "+30",
            "tolerance": "±20",
            "unit": "мм",
        },
        {
            "element": "Колонна",
            "parameter": "Привязка осей",
            "deviation": "+30",
            "tolerance": "±12",
            "unit": "мм",
        },
        {
            "element": "Стена",
            "parameter": "Отметка верха",
            "deviation": "-5",
            "tolerance": "±20",
            "unit": "мм",
        },
    ]
    t = typed_table("ИГС-1", "DEVIATION", rows, page_no=1)
    inputs = _inputs(
        documents={"F0197": doc("F0197", "ID", "KR", 1)},
        tables={"F0197": table_artifacts("F0197", "ID", [t])},
    )
    statuses = [o.status for o in _outcomes(inputs, "HR-LOG-008")]
    # below design beyond tolerance; over-pour is context (Q4c); axes belong to KR-054 (matrix); within tolerance
    assert statuses == ["EMITTED", "SATISFIED", "NOT_APPLICABLE", "SATISFIED"]


# ── ТЭП rules: HR-LOG-003, -004, -006, -012 ─────────────────────────────────────────────────────────


def test_tep_rules_on_extracted_values():
    tep = typed_table(
        "TEP", "TEP", [{"indicator": "Площадь участка", "unit": "м²", "value": "10000"}], page_no=3
    )
    values = [
        _value("PZ-001", "PD", 3000),
        _value("PZ-019", "PD", 45),  # 3000/10000 = 30 %, not 45 %
        _value("PZ-010", "PD", 100),
        _value("PZ-011", "PD", 60, location="1-комн."),
        _value("PZ-011", "PD", 30, location="2-комн."),  # Σ 90 ≠ 100
        _value("PZ-007", "PD", 10),
        _value("PZ-008", "PD", 90.0),  # 9 m per floor
    ]
    inputs = _inputs(values=values, tables={"F0171": table_artifacts("F0171", "PD", [tep])})
    assert [o.status for o in _outcomes(inputs, "HR-LOG-004")] == ["EMITTED"]
    assert [o.status for o in _outcomes(inputs, "HR-LOG-006")] == ["EMITTED"]
    assert [o.status for o in _outcomes(inputs, "HR-LOG-012")] == ["EMITTED"]
    assert [o.status for o in _outcomes(inputs, "HR-LOG-003")] == [
        "UNKNOWN"
    ]  # no floor explications: no facts
    good = [
        _value("PZ-001", "PD", 4500),
        _value("PZ-019", "PD", 0.45),
        _value("PZ-007", "PD", 10),
        _value("PZ-008", "PD", 33.0),
    ]
    inputs = _inputs(values=good, tables={"F0171": table_artifacts("F0171", "PD", [tep])})
    assert [o.status for o in _outcomes(inputs, "HR-LOG-004")] == ["SATISFIED"]  # КЗ given as a fraction
    assert [o.status for o in _outcomes(inputs, "HR-LOG-012")] == ["SATISFIED"]


def test_hr_log_003_sums_floor_totals():
    floors = [
        explication(
            f"F{n}",
            [("1", "А", "100.0")],
            ("Итого по этажу", "100.0"),
            title=f"Экспликация помещений {n} этажа",
        )
        for n in (1, 2)
    ]
    values = [_value("PZ-002", "RD", 250.0, file_id="F0201"), _value("PZ-007", "RD", 2, file_id="F0201")]
    inputs = _inputs(values=values, tables={"F0201": table_artifacts("F0201", "RD", floors)})
    [o] = _outcomes(inputs, "HR-LOG-003")
    assert o.status == "EMITTED" and o.values["floors_sum"] == pytest.approx(200.0)


def test_rule_suspicions_are_section_6_only_and_json_ready():
    t = explication("ALT79B-PD", ALT79B_ROOMS, ("Общий итог по этажу", "2797.27"))
    r = run_hypotheses(
        _inputs(tables={"F0171": table_artifacts("F0171", "PD", [t])}), HypothesisConfig(enable_free=False)
    )
    [s] = r.suspicions
    assert s.rule_code == "HR-LOG-005" and not s.exported and s.parameter_code is None
    assert s.stage_cells == {"PD": "Σ 2795,04 м² ≠ итог 2797,27 м²", "RD": "—", "ID": "—"}
    assert s.evidence_bind_status == "BOUND"  # page + row bbox of the total
    assert r.free_groups == [] and r.free_findings == []
    json.dumps(r.to_json(), ensure_ascii=False)


def test_dates_parse_in_every_format_the_recognisers_write():
    from inspector_hypothesis.facts import parse_date

    assert parse_date("07.04.2025") == parse_date("2025-04-07") == parse_date("07/04/25") == "2025-04-07"
    assert parse_date("от 11.08.2024 г.") == "2024-08-11"
    assert parse_date("31.02.2024") is None and parse_date("изм. 4") is None and parse_date(None) is None


def test_hr_log_009_fires_with_iso_act_dates_as_ag02c_writes_them():
    [o] = _outcomes(_aosr_inputs("АНО/150321/1-РД-ОВ1 - изм. 3", act_date="2025-04-07"), "HR-LOG-009")
    assert o.status == "EMITTED"


def _bundled_rd_inputs(refs: str, quality: str | None = None):
    """F0201 as it really is: one PDF with the drawings «…-РД-ОВ1» (a few sheets, the «Изм.» rows on the general
    data sheet) and the much longer specification «…-РД-ОВ1.С»; one title block's code was not read."""
    blocks = [title_block(14, "АНО/150321/1-РД-ОВ1", 1, [("4", "11.08.2024"), ("2", "20.03.2024")])]
    blocks += [title_block(p, "АНО/150321/1-РД-ОВ1", p - 13) for p in (15, 16)]
    blocks += [title_block(17, None, 4, [("3", "20.05.2024")])]  # code unreadable: belongs to ОВ1 (page 16)
    blocks += [title_block(p, "АНО/150321/1-РД-ОВ1.С", p - 99) for p in range(100, 130)]
    documents = {
        "F0201": doc("F0201", "RD", "OV", 676, name="АНО-150321-1-РД-ОВ1 изм. 4_в1 (1).pdf"),
        "F0196": doc("F0196", "ID", "OV", 3),
    }
    row = {"act_no": "1/ОВ", "act_date": "2025-04-07", "work_name": "Монтаж воздуховодов", "rd_refs": refs}
    if quality is not None:
        row["quality_docs"] = quality
    aosr = typed_table("F0196-aosr-1", "AOSR", [row], page_no=1)
    return _inputs(
        documents=documents,
        layouts={"F0201": layout("F0201", "RD", 676, blocks)},
        tables={"F0196": table_artifacts("F0196", "ID", [aosr])},
    )


def test_every_document_of_a_bundled_file_is_registered_with_its_own_revisions():
    inputs = _bundled_rd_inputs("АНО/150321/1-РД-ОВ1 - изм. 3")
    rd = FactBuilder(inputs).build()["documents"]["RD"]
    main, spec = rd["by_key"]["АНО1503211РОВ1"], rd["by_key"]["АНО1503211РОВ1С"]
    assert main["current_revision"] == 4 and main["revision_dates"] == {
        "2": "2024-03-20",
        "3": "2024-05-20",  # from the title block whose code was not read
        "4": "2024-08-11",
    }
    assert spec["current_revision"] is None and spec["source"] == "TITLE_BLOCK"
    assert rd["complete"] is True
    # the act cites the drawings, not the specification: known, but an outdated revision
    assert [o.status for o in _outcomes(inputs, "HR-LOG-002")] == ["SATISFIED"]
    [o9] = _outcomes(inputs, "HR-LOG-009")
    assert o9.status == "EMITTED"
    assert "изм. 3" in o9.render(o9.rule.message_template)
    assert "изм. 4 от 11.08.2024" in o9.render(o9.rule.message_template)
    [o10] = _outcomes(inputs, "HR-LOG-010")  # act 07.04.2025 after изм. 3 of 20.05.2024
    assert o10.status == "SATISFIED"


def test_a_cipher_typo_in_item_4_of_an_act_is_flagged_and_certificates_are_not():
    inputs = _bundled_rd_inputs(
        "АНО/150321/1-РД-ОВ1 - изм. 4",
        quality="Исполнительные чертежи АНО1301211-Р-ОВ1; сертификат соответствия № РОСС RU.АЯ46.Н12345",
    )
    outcomes = _outcomes(inputs, "HR-LOG-002")
    assert sorted((o.item["code"], o.item["field_ru"], o.status) for o in outcomes) == [
        ("АНО/150321/1-РД-ОВ1", "п. 2", "SATISFIED"),
        ("АНО1301211-Р-ОВ1", "п. 4", "EMITTED"),
    ]
    [bad] = [o for o in outcomes if o.emitted]
    msg = bad.render(bad.rule.message_template)
    assert msg.startswith("Акт 1/ОВ (п. 4) ссылается на документ «АНО1301211-Р-ОВ1»")
    assert "ближайший шифр: АНО/150321/1-РД-ОВ1)" in msg
