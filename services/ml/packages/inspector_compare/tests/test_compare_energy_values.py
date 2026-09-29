"""Energy-efficiency value checks (ZU-124…128) over ``ee.*`` values: class downgrade (ordinal), λ increase, window Ro
decrease and insulation thickness decrease (LAYER_STACK) — directional, per insulation material group, and
conservative over candidate sets (any agreeing reading makes the pair EQUAL)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import ExtractedValue
from inspector_common.params import load_params
from inspector_compare.engine import compare_object
from inspector_compare.valuecmp import compare_values

STAGE_FILE = {"PD": "F9004", "RD": "F9002", "ID": "F9003"}
KEYS = {
    "ZU-124": ("ee.class", "enum", None),
    "ZU-125": ("ee.wall_insulation_thickness", "number", "мм"),
    "ZU-126": ("ee.insulation_lambda", "number", "Вт/(м·°С)"),
    "ZU-127": ("ee.window_ro", "number", "м²·°С/Вт"),
    "ZU-128": ("ee.roof_insulation_thickness", "number", "мм"),
}
MAT = "Минеральная вата / сэндвич-панель"
XPS = "Пенополистирол (XPS/EPS)"
RANK = {"A": 8, "B": 6, "C": 4, "D": 2}


def _ee(syn: Any, code: str, stage: str, raw: str, *, material: str | None = None, page: int = 3, n: int = 0) -> dict[str, Any]:  # fmt: skip
    key, vtype, unit = KEYS[code]
    file_id = STAGE_FILE[stage]
    norm: dict[str, Any] = {"type": vtype, "value": raw if vtype == "enum" else float(raw.replace(",", "."))}
    if vtype == "enum":
        norm["rank"] = RANK[raw]
    if unit:
        norm["unit"] = unit
    return {
        "value_id": f"ee-{code}-{stage}-{raw}-{material}-{page}-{n}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": stage,
        "page_no": page,
        "fact_key": key,
        "param_code": code,
        "location": material or "OBJECT",
        "location_type": "ELEMENT" if material else "OBJECT",
        "value_raw": raw,
        "value_norm": norm,
        "method": "REGEX",
        "confidence": 0.85,
        "quality_flag": "OK",
        "pipeline_version": "test",
    }


def _outcomes(values: list[dict[str, Any]], axes: tuple[str, ...] = ("PD_RD",)) -> dict[tuple[str, str], tuple[str, str | None, str | None]]:  # fmt: skip
    diffs = compare_values([ExtractedValue.model_validate(v) for v in values], load_params(), axes)
    return {
        (d.code, d.room): (
            d.outcome,
            d.expected.value_raw if d.expected else None,
            d.actual.value_raw if d.actual else None,
        )
        for d in diffs
    }


def test_class_is_ordinal_and_directional(syn: Any) -> None:
    assert _outcomes([_ee(syn, "ZU-124", "PD", "B"), _ee(syn, "ZU-124", "RD", "C")])[("ZU-124", "OBJECT")] == (
        "VIOLATION", "B", "C")  # fmt: skip
    assert (
        _outcomes([_ee(syn, "ZU-124", "PD", "B"), _ee(syn, "ZU-124", "RD", "A")])[("ZU-124", "OBJECT")][0]
        == "IMPROVEMENT"
    )
    assert (
        _outcomes([_ee(syn, "ZU-124", "PD", "C"), _ee(syn, "ZU-124", "RD", "C")])[("ZU-124", "OBJECT")][0]
        == "EQUAL"
    )
    # RD → ИД (the executed building's passport)
    got = _outcomes([_ee(syn, "ZU-124", "RD", "B"), _ee(syn, "ZU-124", "ID", "C")], ("RD_ID",))
    assert got[("ZU-124", "OBJECT")][0] == "VIOLATION"


def test_lambda_increase_only_and_precision(syn: Any) -> None:
    def run(pd: str, rd: str) -> str:
        vals = [_ee(syn, "ZU-126", "PD", pd, material=MAT), _ee(syn, "ZU-126", "RD", rd, material=MAT)]
        return _outcomes(vals)[("ZU-126", MAT)][0]

    assert run("0,040", "0,045") == "VIOLATION"
    assert run("0,040", "0,040") == "EQUAL"
    assert run("0,040", "0,035") == "IMPROVEMENT"
    assert run("0,04", "0,04") == "EQUAL"


def test_window_ro_decrease(syn: Any) -> None:
    got = _outcomes([_ee(syn, "ZU-127", "PD", "0,65"), _ee(syn, "ZU-127", "RD", "0,55")])
    assert got[("ZU-127", "OBJECT")] == ("VIOLATION", "0,65", "0,55")
    assert (
        _outcomes([_ee(syn, "ZU-127", "PD", "0,65"), _ee(syn, "ZU-127", "RD", "0,70")])[("ZU-127", "OBJECT")][
            0
        ]
        == "IMPROVEMENT"
    )


def test_thickness_layer_stack_within_one_material_group(syn: Any) -> None:
    vals = [
        _ee(syn, "ZU-125", "PD", "200", material=MAT),
        _ee(syn, "ZU-125", "RD", "150", material=MAT),
        # another material group is never compared against the wall panel
        _ee(syn, "ZU-125", "PD", "50", material=XPS),
        _ee(syn, "ZU-125", "RD", "310", material=XPS),
    ]
    got = _outcomes(vals)
    assert got[("ZU-125", MAT)] == ("VIOLATION", "200", "150")
    assert got[("ZU-125", XPS)][0] == "IMPROVEMENT"
    # a group present on one stage only is not compared at all
    assert ("ZU-128", XPS) not in _outcomes([_ee(syn, "ZU-128", "PD", "200", material=XPS)])


def test_candidate_sets_prefer_no_finding(syn: Any) -> None:
    # PD roof XPS 150 and 200 (thermal calculation vs build-up), RD 200 → equal on the agreeing pair
    vals = [_ee(syn, "ZU-128", "PD", "150", material=XPS), _ee(syn, "ZU-128", "PD", "200", material=XPS, n=1),
            _ee(syn, "ZU-128", "RD", "200", material=XPS)]  # fmt: skip
    assert _outcomes(vals)[("ZU-128", XPS)][0] == "EQUAL"
    # RD lower than every PD candidate → a violation, reported on the closest pair
    vals[-1] = _ee(syn, "ZU-128", "RD", "100", material=XPS)
    assert _outcomes(vals)[("ZU-128", XPS)] == ("VIOLATION", "150", "100")


def test_engine_emits_energy_findings_and_verifies_equal(tmp_path: Path, cfg: Any, syn: Any) -> None:
    values = [
        _ee(syn, "ZU-124", "PD", "B", page=5),
        _ee(syn, "ZU-124", "RD", "C", page=2),
        _ee(syn, "ZU-126", "PD", "0,040", material=MAT, page=6),
        _ee(syn, "ZU-126", "RD", "0,040", material=MAT, page=4),
        _ee(syn, "ZU-128", "PD", "200", material=XPS, page=7),
        _ee(syn, "ZU-128", "RD", "150", material=XPS, page=3),
    ]
    result = compare_object(syn.make_context(tmp_path, [], values=values), cfg)
    viol = {f["parameter_code"]: f for f in result.findings if f["violation_label"] == "VIOLATION_PRESENT"}
    assert set(viol) >= {"ZU-124", "ZU-128"} and "ZU-126" not in viol
    assert (viol["ZU-124"]["pd_value"], viol["ZU-124"]["rd_value"]) == ("B", "C")
    assert viol["ZU-128"]["location"] == XPS
    assert (viol["ZU-128"]["pd_value"], viol["ZU-128"]["rd_value"]) == ("200 мм", "150 мм")
    assert {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in viol["ZU-124"]["evidence"]} == {
        ("PD", "F9004", 5),
        ("RD", "F9002", 2),
    }
    zu126 = next(f for f in result.findings if f["parameter_code"] == "ZU-126")
    assert zu126["decision_trace"]["verified_by_comparator"] is True
    for doc in result.findings:
        assert not validation_errors("finding", doc)
