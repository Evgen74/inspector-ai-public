"""Fire-safety value checks (PPM-102…114) over ``ppm.*`` values: directional, per element, conservative."""

from __future__ import annotations

from typing import Any

from inspector_common.contracts.models import ExtractedValue
from inspector_common.params import load_params
from inspector_compare.valuecmp import compare_values

STAGE_FILE = {"PD": "F9004", "RD": "F9002", "ID": "F9003"}


def _v(syn: Any, code: str, kind: str, stage: str, raw: str, *, loc: str | None = None, rank: float | None = None,
       unit: str | None = None, enum: bool = False, page: int = 3, n: int = 0) -> dict[str, Any]:  # fmt: skip
    file_id = STAGE_FILE[stage]
    norm: dict[str, Any] = {
        "type": "enum" if enum else "number",
        "value": raw if enum else float(raw.replace(",", ".")),
    }
    if rank is not None:
        norm["rank"] = rank
    if unit:
        norm["unit"] = unit
    return {
        "value_id": f"ppm-{code}-{kind}-{stage}-{raw}-{loc}-{page}-{n}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": stage,
        "page_no": page,
        "fact_key": f"ppm.{kind}",
        "param_code": code,
        "location": loc or "OBJECT",
        "location_type": "ELEMENT" if loc else "OBJECT",
        "value_raw": raw,
        "value_norm": norm,
        "method": "REGEX",
        "confidence": 0.85,
        "quality_flag": "OK",
        "pipeline_version": "test",
    }


def _outcomes(values: list[dict[str, Any]], axes: tuple[str, ...] = ("PD_RD",)) -> dict[tuple[str, str], str]:
    diffs = compare_values([ExtractedValue.model_validate(v) for v in values], load_params(), axes)
    return {(d.code, d.room): d.outcome for d in diffs}


def test_smoke_air_flow_decrease_only_per_system_tag(syn: Any) -> None:
    def run(pd: str, rd: str, tag: str = "ВД1") -> str | None:
        vals = [_v(syn, "PPM-112", "air_flow", "PD", pd, loc="ВД1", unit="м³/ч"),
                _v(syn, "PPM-112", "air_flow", "RD", rd, loc=tag, unit="м³/ч")]  # fmt: skip
        return _outcomes(vals).get(("PPM-112", "ВД1"))

    assert run("13000", "11000") == "VIOLATION"
    assert run("13000", "13000") == "EQUAL"
    assert run("13000", "15000") == "IMPROVEMENT"
    assert run("13000", "11000", tag="ВД2") is None  # another system: the element mismatch is not compared


def test_damper_ei_is_ordinal_downgrade(syn: Any) -> None:
    def run(pd: float, rd: float) -> str:
        vals = [_v(syn, "PPM-111", "damper_ei", "PD", f"EI {pd:.0f}", loc="ПД1", rank=pd, enum=True),
                _v(syn, "PPM-111", "damper_ei", "RD", f"EI {rd:.0f}", loc="ПД1", rank=rd, enum=True)]  # fmt: skip
        return _outcomes(vals)[("PPM-111", "ПД1")]

    assert run(90, 60) == "VIOLATION"
    assert run(60, 60) == "EQUAL"
    assert run(60, 90) == "IMPROVEMENT"


def test_door_ei_and_cable_index_and_finishing_class(syn: Any) -> None:
    door = [_v(syn, "PPM-103", "door_ei", "PD", "EI 60", loc="Д-6", rank=60, enum=True),
            _v(syn, "PPM-103", "door_ei", "RD", "EI 30", loc="Д-6", rank=30, enum=True)]  # fmt: skip
    assert _outcomes(door)[("PPM-103", "Д-6")] == "VIOLATION"
    cable = [_v(syn, "PPM-109", "cable_index", "PD", "FRLS", loc="ВВГ 3х1.5", rank=2, enum=True),
             _v(syn, "PPM-109", "cable_index", "RD", "LS", loc="ВВГ 3х1.5", rank=1, enum=True)]  # fmt: skip
    assert _outcomes(cable)[("PPM-109", "ВВГ 3х1.5")] == "VIOLATION"
    km = [_v(syn, "PPM-107", "km", "PD", "КМ2", loc="полы: коридоры", rank=3, enum=True),
          _v(syn, "PPM-107", "km", "RD", "КМ4", loc="полы: коридоры", rank=1, enum=True),
          _v(syn, "PPM-107", "km", "RD", "КМ0", loc="стены и потолки: коридоры", rank=5, enum=True)]  # fmt: skip
    got = _outcomes(km)
    assert got[("PPM-107", "полы: коридоры")] == "VIOLATION"
    assert ("PPM-107", "стены и потолки: коридоры") not in got  # present on one stage only


def test_vpv_and_external_water_and_compartment_area(syn: Any) -> None:
    vals = [
        _v(syn, "PPM-113", "vpv_jets", "PD", "2", loc="число струй"),
        _v(syn, "PPM-113", "vpv_jets", "RD", "1", loc="число струй"),
        _v(syn, "PPM-113", "vpv_flow", "PD", "2,6", loc="расход на струю", unit="л/с"),
        _v(syn, "PPM-113", "vpv_flow", "RD", "2,6", loc="расход на струю", unit="л/с"),
        _v(syn, "PPM-114", "external_flow", "PD", "30", unit="л/с"),
        _v(syn, "PPM-114", "external_flow", "RD", "20", unit="л/с"),
        _v(syn, "PPM-102", "compartment_area", "PD", "2400", loc="Пожарный отсек 1", unit="м²"),
        _v(syn, "PPM-102", "compartment_area", "RD", "3100", loc="Пожарный отсек 1", unit="м²"),
    ]
    got = _outcomes(vals)
    assert got[("PPM-113", "число струй")] == "VIOLATION"
    assert got[("PPM-113", "расход на струю")] == "EQUAL"
    assert got[("PPM-114", "OBJECT")] == "VIOLATION"
    assert got[("PPM-102", "Пожарный отсек 1")] == "VIOLATION"  # area increase


def test_ambiguous_value_is_never_compared(syn: Any) -> None:
    pd = _v(syn, "PPM-112", "air_flow", "PD", "13000", loc="ВД1", unit="м³/ч")
    rd = _v(syn, "PPM-112", "air_flow", "RD", "9000", loc="ВД1", unit="м³/ч")
    rd["is_ambiguous"] = True
    assert _outcomes([pd, rd]) == {}
    # any agreeing reading makes the pair EQUAL (candidate sets)
    rd2 = _v(syn, "PPM-112", "air_flow", "RD", "13000", loc="ВД1", unit="м³/ч", n=1)
    assert (
        _outcomes([pd, rd2, _v(syn, "PPM-112", "air_flow", "RD", "9000", loc="ВД1", unit="м³/ч")])[
            ("PPM-112", "ВД1")
        ]
        == "EQUAL"
    )
