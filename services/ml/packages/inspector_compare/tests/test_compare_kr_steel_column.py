"""KR-056 steel grade, KR-060 column section and KR-062 column rebar diameter: conservative set rules, directional
triggers (a stronger/larger value is never a violation) and the engine path to a finding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import ExtractedValue
from inspector_compare.engine import compare_object
from inspector_compare.materials import compare_materials

CODES = {"kr.steel_grade": "KR-056", "kr.column_section": "KR-060", "kr.column_rebar_diameter": "KR-062"}


def _v(
    syn: Any, key: str, stage: str, file_id: str, raw: str, rank: float, loc: str, page: int = 3
) -> dict[str, Any]:
    return {
        "value_id": f"k-{key}-{stage}-{file_id}-{loc}-{raw}-{page}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": stage,
        "page_no": page,
        "fact_key": key,
        "location": loc,
        "location_type": "ELEMENT",
        "value_raw": raw,
        "value_norm": {"type": "enum", "value": raw, "rank": rank},
        "method": "REGEX",
        "confidence": 0.85,
        "quality_flag": "OK",
        "pipeline_version": "test",
        "param_code": CODES[key],
    }


def _ev(syn: Any, rows: list[dict[str, Any]]) -> list[ExtractedValue]:
    return [ExtractedValue.model_validate(r) for r in rows]


def test_steel_downgrade_equal_and_improvement(syn: Any) -> None:
    vals = _ev(
        syn,
        [
            _v(syn, "kr.steel_grade", "PD", "F9004", "С345", 345, "Фермы"),
            _v(syn, "kr.steel_grade", "RD", "F9002", "С245", 245, "Фермы"),
            _v(syn, "kr.steel_grade", "PD", "F9004", "С245", 245, "Лестницы"),
            _v(syn, "kr.steel_grade", "RD", "F9002", "С245", 245, "Лестницы"),
            _v(syn, "kr.steel_grade", "PD", "F9004", "С245", 245, "Балки"),
            _v(syn, "kr.steel_grade", "RD", "F9002", "С345", 345, "Балки"),
            # mixed RD set: one RD value at the PD level → equal, not a violation
            _v(syn, "kr.steel_grade", "PD", "F9004", "С345", 345, "Связи"),
            _v(syn, "kr.steel_grade", "RD", "F9002", "С245", 245, "Связи"),
            _v(syn, "kr.steel_grade", "RD", "F9002", "С345", 345, "Связи"),
        ],
    )
    diffs, _ = compare_materials(vals, ("PD_RD", "RD_ID", "PD_ID"))
    got = {(d.room, d.outcome) for d in diffs if d.code == "KR-056"}
    assert got == {
        ("Фермы", "VIOLATION"),
        ("Лестницы", "EQUAL"),
        ("Балки", "IMPROVEMENT"),
        ("Связи", "EQUAL"),
    }


def test_steel_in_id_uses_the_best_grade_of_the_act(syn: Any) -> None:
    vals = _ev(
        syn,
        [
            _v(syn, "kr.steel_grade", "RD", "F9002", "С345", 345, "Колонны"),
            _v(syn, "kr.steel_grade", "ID", "F9003", "С345", 345, "Колонны"),
            _v(
                syn, "kr.steel_grade", "ID", "F9003", "С245", 245, "Колонны"
            ),  # gussets next to the main steel
            _v(syn, "kr.steel_grade", "RD", "F9002", "С345", 345, "Балки"),
            _v(syn, "kr.steel_grade", "ID", "F9003", "С245", 245, "Балки"),
        ],
    )
    diffs, _ = compare_materials(vals, ("PD_RD", "RD_ID"))
    got = {(d.room, d.outcome) for d in diffs if d.code == "KR-056"}
    assert got == {("Колонны", "EQUAL"), ("Балки", "VIOLATION")}


def test_column_section_per_mark_area_decrease_only(syn: Any) -> None:
    vals = _ev(
        syn,
        [
            _v(syn, "kr.column_section", "PD", "F9004", "600×600", 360000, "Колонна К1"),
            _v(syn, "kr.column_section", "RD", "F9002", "500×500", 250000, "Колонна К1"),
            _v(syn, "kr.column_section", "PD", "F9004", "400×400", 160000, "Колонна К2"),
            _v(syn, "kr.column_section", "RD", "F9002", "400×400", 160000, "Колонна К2"),
            _v(syn, "kr.column_section", "PD", "F9004", "400×400", 160000, "Колонна К3"),
            _v(syn, "kr.column_section", "RD", "F9002", "500×500", 250000, "Колонна К3"),
            # the same section turned by 90 degrees keeps its area: equal
            _v(syn, "kr.column_section", "PD", "F9004", "300×600", 180000, "Колонна К4"),
            _v(syn, "kr.column_section", "RD", "F9002", "600×300", 180000, "Колонна К4"),
            # a mark present on one stage only compares nothing
            _v(syn, "kr.column_section", "PD", "F9004", "500×500", 250000, "Колонна К5"),
        ],
    )
    diffs, _ = compare_materials(vals, ("PD_RD", "RD_ID"))
    got = {(d.room, d.outcome) for d in diffs if d.code == "KR-060"}
    assert got == {
        ("Колонна К1", "VIOLATION"),
        ("Колонна К2", "EQUAL"),
        ("Колонна К3", "IMPROVEMENT"),
        ("Колонна К4", "EQUAL"),
    }
    viol = next(d for d in diffs if d.outcome == "VIOLATION")
    assert viol.sub_id == "KR-060.a" and viol.discrepancy_type == "VALUE_DECREASED"


def test_column_diameter_pd_rd_and_id(syn: Any) -> None:
    vals = _ev(
        syn,
        [
            _v(syn, "kr.column_rebar_diameter", "PD", "F9004", "Ø25", 25, "Колонны"),
            _v(syn, "kr.column_rebar_diameter", "RD", "F9002", "Ø20", 20, "Колонны"),
            _v(syn, "kr.column_rebar_diameter", "ID", "F9003", "Ø20", 20, "Колонны"),
            _v(syn, "kr.column_rebar_diameter", "ID", "F9003", "Ø12", 12, "Колонны"),
        ],
    )
    diffs, _ = compare_materials(vals, ("PD_RD", "RD_ID"))
    got = {(d.axis, d.outcome) for d in diffs if d.code == "KR-062"}
    assert got == {("PD_RD", "VIOLATION"), ("RD_ID", "EQUAL")}  # best executed bar equals the design


def test_engine_emits_kr060_and_no_false_kr056(tmp_path: Path, cfg: Any, syn: Any) -> None:
    values = [
        _v(syn, "kr.column_section", "PD", "F9004", "600×600", 360000, "Колонна К1"),
        _v(syn, "kr.column_section", "RD", "F9002", "500×500", 250000, "Колонна К1"),
        _v(syn, "kr.steel_grade", "PD", "F9004", "С345", 345, "Фермы"),
        _v(syn, "kr.steel_grade", "RD", "F9002", "С345", 345, "Фермы"),
    ]
    result = compare_object(syn.make_context(tmp_path, [], values=values), cfg)
    label = {(f["parameter_code"], f["location"]): f["violation_label"] for f in result.findings}
    assert label.get(("KR-060", "Колонна К1")) == "VIOLATION_PRESENT"
    assert not any(c == "KR-056" and lab == "VIOLATION_PRESENT" for (c, _), lab in label.items())
    g = next(g for g in result.groups if g["parameter_code"] == "KR-060")
    assert (g["pd_value"], g["rd_value"]) == ("600×600", "500×500")
    for doc in result.groups:
        assert not validation_errors("finding_group", doc)


def test_unmarked_columns_compare_only_identical_sections(syn: Any) -> None:
    vals = _ev(
        syn,
        [
            _v(syn, "kr.column_section", "PD", "F9004", "600×600", 360000, "Колонны"),
            _v(syn, "kr.column_section", "RD", "F9002", "400×400", 160000, "Колонны"),
            _v(syn, "kr.column_section", "PD", "F9004", "600×600", 360000, "Колонны", page=5),
        ],
    )
    diffs, _ = compare_materials(vals, ("PD_RD",))
    assert not [d for d in diffs if d.code == "KR-060"]  # different lists: neither a violation nor equal
    vals += _ev(syn, [_v(syn, "kr.column_section", "RD", "F9002", "600×600", 360000, "Колонны", page=6)])
    diffs, _ = compare_materials(vals, ("PD_RD",))
    assert [(d.room, d.outcome) for d in diffs if d.code == "KR-060"] == [("Колонны", "EQUAL")]
