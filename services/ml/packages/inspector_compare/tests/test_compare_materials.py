"""The structural materials comparator (``kr.*`` values): conservative set rules per element family, directional
triggers (an increase is never a violation), and the F/W marks → FREE-STRUCTURE group (user-approved rule)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import ExtractedValue
from inspector_compare.engine import compare_object
from inspector_compare.materials import compare_materials

KEY_PARAM = {"kr.concrete_class": "KR-055", "kr.rebar_class": "KR-057"}


def _mv(
    syn: Any, key: str, stage: str, file_id: str, raw: str, rank: float, family: str, page: int = 3
) -> dict[str, Any]:
    thick = key == "kr.thickness"
    code = KEY_PARAM.get(key) or ({"Фундаментная плита": "KR-058"}.get(family) if thick else None)
    v: dict[str, Any] = {
        "value_id": f"m-{key}-{stage}-{file_id}-{family}-{raw}-{page}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": stage,
        "page_no": page,
        "fact_key": key,
        "location": family,
        "location_type": "ELEMENT",
        "value_raw": raw,
        "value_norm": {
            "type": "number" if thick else "enum",
            "value": rank if thick else raw,
            "unit": "мм" if thick else None,
            "rank": rank,
        },
        "method": "REGEX",
        "confidence": 0.85,
        "quality_flag": "OK",
        "pipeline_version": "test",
    }
    if code:
        v["param_code"] = code
    return v


def _violations(result: Any) -> set[tuple[str, str]]:
    return {
        (f["parameter_code"], f["location"])
        for f in result.findings
        if f["violation_label"] == "VIOLATION_PRESENT"
    }


def test_set_rules_are_conservative_and_directional(syn: Any) -> None:
    vals = [
        ExtractedValue.model_validate(v)
        for v in [
            # piles of two classes on both stages: equal (verified), never a violation
            _mv(syn, "kr.concrete_class", "PD", "F9004", "B15", 15, "Сваи"),
            _mv(syn, "kr.concrete_class", "PD", "F9004", "B25", 25, "Сваи"),
            _mv(syn, "kr.concrete_class", "RD", "F9002", "B25", 25, "Сваи"),
            _mv(syn, "kr.concrete_class", "RD", "F9002", "B15", 15, "Сваи"),
            # a stronger ИД batch is not a violation
            _mv(syn, "kr.concrete_class", "ID", "F9003", "B30", 30, "Сваи"),
            # the slab: PD B30 → RD B25 is a downgrade
            _mv(syn, "kr.concrete_class", "PD", "F9004", "B30", 30, "Фундаментная плита"),
            _mv(syn, "kr.concrete_class", "RD", "F9002", "B25", 25, "Фундаментная плита"),
            # thickness increase PD 1000/1200 → RD 1200/1500 is not a violation (NS-C14)
            _mv(syn, "kr.thickness", "PD", "F9004", "1000", 1000, "Фундаментная плита"),
            _mv(syn, "kr.thickness", "PD", "F9004", "1200", 1200, "Фундаментная плита"),
            _mv(syn, "kr.thickness", "RD", "F9002", "1200", 1200, "Фундаментная плита"),
            _mv(syn, "kr.thickness", "RD", "F9002", "1500", 1500, "Фундаментная плита"),
            # F/W: RD F200 W8, ИД F150 W6 → a mark finding
            _mv(syn, "kr.concrete_frost", "RD", "F9002", "F200", 200, "Сваи"),
            _mv(syn, "kr.concrete_frost", "ID", "F9003", "F150", 150, "Сваи"),
            _mv(syn, "kr.concrete_water", "RD", "F9002", "W8", 8, "Сваи"),
            _mv(syn, "kr.concrete_water", "ID", "F9003", "W6", 6, "Сваи"),
            _mv(syn, "kr.concrete_water", "ID", "F9003", "W8", 8, "Сваи"),
        ]
    ]
    diffs, marks = compare_materials(vals, ("PD_RD", "RD_ID", "PD_ID"))
    got = {(d.code, d.axis, d.room, d.outcome) for d in diffs}
    assert ("KR-055", "PD_RD", "Сваи", "EQUAL") in got
    assert ("KR-055", "RD_ID", "Сваи", "EQUAL") in got
    assert ("KR-055", "PD_RD", "Фундаментная плита", "VIOLATION") in got
    assert ("KR-058", "PD_RD", "Фундаментная плита", "EQUAL") in got
    assert not any(d.outcome == "VIOLATION" and d.code == "KR-058" for d in diffs)
    assert [(m.family, m.axis) for m in marks] == [("Сваи", "RD_ID")]
    assert marks[0].values() == {"pd_value": None, "rd_value": "F200, W8", "id_value": "F150, W6"}


def test_engine_emits_kr055_and_free_structure(tmp_path: Path, cfg: Any, syn: Any) -> None:
    values = [
        _mv(syn, "kr.concrete_class", "PD", "F9004", "B30", 30, "Фундаментная плита"),
        _mv(syn, "kr.concrete_class", "RD", "F9002", "B25", 25, "Фундаментная плита"),
        _mv(syn, "kr.rebar_class", "PD", "F9004", "A500С", 500, "Фундаментная плита"),
        _mv(syn, "kr.rebar_class", "RD", "F9002", "A500С", 500, "Фундаментная плита"),
        _mv(syn, "kr.concrete_frost", "RD", "F9002", "F200", 200, "Сваи"),
        _mv(syn, "kr.concrete_frost", "ID", "F9003", "F150", 150, "Сваи", page=6),
        _mv(syn, "kr.concrete_class", "RD", "F9002", "B15", 15, "Сваи"),
        _mv(syn, "kr.concrete_class", "ID", "F9003", "B15", 15, "Сваи", page=6),
    ]
    result = compare_object(syn.make_context(tmp_path, [], values=values), cfg)
    keys = _violations(result)
    assert ("KR-055", "Фундаментная плита") in keys
    assert ("KR-055", "Сваи") not in keys and ("KR-057", "Фундаментная плита") not in keys
    free = [g for g in result.groups if g["parameter_code"].startswith("FREE-STRUCTURE")]
    assert len(free) == 1
    g = free[0]
    assert g["parameter_code"] == "FREE-STRUCTURE-001" and g["locations"] == ["Сваи"]
    assert g["criticality"] == "Существенное (предписание) — требует утверждения"
    assert (g["rd_value"], g["id_value"]) == ("F200", "F150")
    assert {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in g["anchor_evidence"]} == {
        ("RD", "F9002", 3),
        ("ID", "F9003", 6),
    }
    assert "пом." not in g["title"]
    kr055 = next(g for g in result.groups if g["parameter_code"] == "KR-055")
    assert (kr055["pd_value"], kr055["rd_value"]) == ("B30", "B25")
    assert kr055["discrepancy_type"] == "CLASS_DOWNGRADED" and kr055["protocol_status"] == "CRITICAL"
    rows = {f["parameter_code"]: f for f in result.findings if f["location"] == "OBJECT"}
    assert rows.get("KR-057") is None or rows["KR-057"]["violation_label"] != "VIOLATION_PRESENT"
    for doc in result.groups:
        assert not validation_errors("finding_group", doc)


def test_rebar_stirrups_in_id_are_not_a_downgrade(syn: Any) -> None:
    vals = [
        ExtractedValue.model_validate(v)
        for v in [
            _mv(syn, "kr.rebar_class", "RD", "F9002", "A500С", 500, "Плиты перекрытий"),
            _mv(syn, "kr.rebar_class", "ID", "F9003", "A500С", 500, "Плиты перекрытий"),
            _mv(syn, "kr.rebar_class", "ID", "F9003", "A240", 240, "Плиты перекрытий"),
            _mv(syn, "kr.rebar_class", "RD", "F9002", "A500С", 500, "Колонны"),
            _mv(syn, "kr.rebar_class", "ID", "F9005", "A400", 400, "Колонны"),
        ]
    ]
    diffs, _ = compare_materials(vals, ("PD_RD", "RD_ID", "PD_ID"))
    got = {(d.room, d.outcome) for d in diffs if d.code == "KR-057"}
    assert got == {("Плиты перекрытий", "EQUAL"), ("Колонны", "VIOLATION")}
