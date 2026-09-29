"""Mix-parameter value checks (``tx.value``: ODI-116/117/119/121, SPZU-030/031/038, AR-045/049/050, KR-066, ZU-131):
directional pairwise deltas, ordinal classes, element binding (a different element is never compared), ambiguous
readings abstain, and a value pinned to one sub-check (``sub_id``) is evaluated by that sub-check only."""

from __future__ import annotations

from typing import Any

from inspector_common.contracts.models import ExtractedValue
from inspector_common.params import load_params
from inspector_compare.valuecmp import compare_values

STAGE_FILE = {"PD": "F9004", "RD": "F9002", "ID": "F9003"}


def _tx(
    syn: Any,
    code: str,
    stage: str,
    raw: str,
    value: Any,
    *,
    unit: str | None = "м",
    location: str | None = None,
    sub: str | None = None,
    rank: float | None = None,
    ambiguous: bool = False,
    n: int = 0,
) -> dict[str, Any]:
    file_id = STAGE_FILE[stage]
    is_num = isinstance(value, float)
    norm: dict[str, Any] = {"type": "number" if is_num else "enum", "value": value}
    if unit:
        norm["unit"] = unit
    if rank is not None:
        norm["rank"] = rank
    if sub:
        norm["qualifiers"] = {"sub_id": sub}
    return {
        "value_id": f"tx-{code}-{stage}-{raw}-{location}-{sub}-{n}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": stage,
        "page_no": 3,
        "fact_key": "tx.value",
        "param_code": code,
        "location": location or "OBJECT",
        "location_type": "ELEMENT" if location else "OBJECT",
        "value_raw": raw,
        "value_norm": norm,
        "method": "REGEX",
        "confidence": 0.85,
        "quality_flag": "OK",
        "is_ambiguous": ambiguous,
        "pipeline_version": "test",
    }


def _run(values: list[dict[str, Any]], axes: tuple[str, ...] = ("PD_RD",)) -> list[Any]:
    return compare_values([ExtractedValue.model_validate(v) for v in values], load_params(), axes)


def _pair(diffs: list[Any], code: str) -> list[tuple[str, str | None, str]]:
    return [(d.outcome, d.discrepancy_type, d.room) for d in diffs if d.code == code]


def test_width_decrease_is_violation_increase_is_improvement(syn: Any) -> None:
    for code, pd, rd in (
        ("ODI-116", "1,8 м", "1,5 м"),
        ("ODI-117", "1,2 м", "0,9 м"),
        ("SPZU-030", "6,0 м", "4,2 м"),
    ):
        pv, rv = float(pd.split()[0].replace(",", ".")), float(rd.split()[0].replace(",", "."))
        got = _pair(_run([_tx(syn, code, "PD", pd, pv), _tx(syn, code, "RD", rd, rv)]), code)
        assert got == [("VIOLATION", "VALUE_DECREASED", "OBJECT")], code
        back = _pair(_run([_tx(syn, code, "PD", rd, rv), _tx(syn, code, "RD", pd, pv)]), code)
        assert [b[0] for b in back] == ["IMPROVEMENT"], code
        same = _pair(_run([_tx(syn, code, "PD", pd, pv), _tx(syn, code, "RD", pd, pv)]), code)
        assert [b[0] for b in same] == ["EQUAL"], code


def test_ambiguous_reading_never_compares(syn: Any) -> None:
    vals = [
        _tx(syn, "SPZU-031", "PD", "12,0 м", 12.0, ambiguous=True),
        _tx(syn, "SPZU-031", "RD", "6,0 м", 6.0),
    ]
    assert _pair(_run(vals), "SPZU-031") == []


def test_unit_mismatch_abstains_and_counts_compare(syn: Any) -> None:
    got = _run([_tx(syn, "ZU-131", "PD", "95,4 кВт·ч/м²", 95.4, unit="кВт·ч/м²"),
                _tx(syn, "ZU-131", "RD", "0,25 Вт/(м³·°С)", 0.25, unit="Вт/(м³·°С)")])  # fmt: skip
    assert [(d.outcome, d.reason) for d in got if d.code == "ZU-131"] == [("ABSTAIN", "UNIT_MISMATCH")]
    inc = _run([_tx(syn, "ZU-131", "PD", "95,4 кВт·ч/м²", 95.4, unit="кВт·ч/м²"),
                _tx(syn, "ZU-131", "RD", "101,2 кВт·ч/м²", 101.2, unit="кВт·ч/м²")])  # fmt: skip
    assert _pair(inc, "ZU-131") == [("VIOLATION", "VALUE_INCREASED", "OBJECT")]  # INCREASE is the trigger
    dec = _run([_tx(syn, "ZU-131", "PD", "101,2 кВт·ч/м²", 101.2, unit="кВт·ч/м²"),
                _tx(syn, "ZU-131", "RD", "95,4 кВт·ч/м²", 95.4, unit="кВт·ч/м²")])  # fmt: skip
    assert [d.outcome for d in dec if d.code == "ZU-131"] == ["IMPROVEMENT"]
    cnt = _run(
        [_tx(syn, "SPZU-038", "PD", "4", 4.0, unit=None), _tx(syn, "SPZU-038", "RD", "3", 3.0, unit=None)]
    )
    assert _pair(cnt, "SPZU-038") == [("VIOLATION", "VALUE_DECREASED", "OBJECT")]


def test_roof_slope_only_the_pinned_sub_check(syn: Any) -> None:
    got = _run([_tx(syn, "AR-045", "PD", "1,7 %", 1.7, unit="%", sub="AR-045.a"),
                _tx(syn, "AR-045", "RD", "1 %", 1.0, unit="%", sub="AR-045.a")])  # fmt: skip
    subs = [(d.sub_id, d.outcome, d.discrepancy_type) for d in got if d.code == "AR-045"]
    assert subs == [("AR-045.a", "VIOLATION", "VALUE_DECREASED")]  # not also the COUNT_DECREASE sub-check .b


def test_railing_height_per_element_only(syn: Any) -> None:
    stairs, roof = "Ограждение лестниц", "Ограждение кровли"
    got = _run([_tx(syn, "AR-049", "PD", "1,2 м", 1.2, location=stairs), _tx(syn, "AR-049", "RD", "1,0 м", 1.0, location=stairs),
                _tx(syn, "AR-049", "PD", "1,2 м", 1.2, location=roof), _tx(syn, "AR-049", "RD", "1,2 м", 1.2, location=roof)])  # fmt: skip
    assert sorted(_pair(got, "AR-049")) == [("EQUAL", None, roof), ("VIOLATION", "VALUE_DECREASED", stairs)]
    # a value of another element does not pair
    other = _run([_tx(syn, "AR-049", "PD", "1,2 м", 1.2, location=stairs), _tx(syn, "AR-049", "RD", "1,0 м", 1.0, location=roof)])  # fmt: skip
    assert _pair(other, "AR-049") == []


def test_finishing_class_downgrade_is_ordinal(syn: Any) -> None:
    loc = "Лестничные клетки: стены"
    down = _run([_tx(syn, "AR-050", "PD", "КМ1", "КМ1", unit=None, location=loc, rank=5.0),
                 _tx(syn, "AR-050", "RD", "КМ3", "КМ3", unit=None, location=loc, rank=3.0)])  # fmt: skip
    assert _pair(down, "AR-050") == [("VIOLATION", "CLASS_DOWNGRADED", loc)]
    up = _run([_tx(syn, "AR-050", "PD", "КМ3", "КМ3", unit=None, location=loc, rank=3.0),
               _tx(syn, "AR-050", "RD", "КМ1", "КМ1", unit=None, location=loc, rank=5.0)])  # fmt: skip
    assert [d[0] for d in _pair(up, "AR-050")] == ["IMPROVEMENT"]


def test_fire_protection_sub_checks(syn: Any) -> None:
    loc = "Колонны"
    vals = [
        _tx(syn, "KR-066", "PD", "R90", "R90", unit=None, location=loc, sub="KR-066.a", rank=90.0),
        _tx(syn, "KR-066", "RD", "R60", "R60", unit=None, location=loc, sub="KR-066.a", rank=60.0),
        _tx(syn, "KR-066", "PD", "вспучивающийся состав", "вспучивающийся состав", unit=None, location=loc, sub="KR-066.c"),
        _tx(syn, "KR-066", "RD", "штукатурка", "штукатурка", unit=None, location=loc, sub="KR-066.c"),
        _tx(syn, "KR-066", "PD", "120 мкм", 120.0, unit="мкм", location="Антикоррозионное покрытие", sub="KR-066.b"),
        _tx(syn, "KR-066", "RD", "120 мкм", 120.0, unit="мкм", location="Антикоррозионное покрытие", sub="KR-066.b"),
    ]  # fmt: skip
    got = {(d.sub_id, d.room): (d.outcome, d.discrepancy_type) for d in _run(vals) if d.code == "KR-066"}
    assert got[("KR-066.a", loc)] == ("VIOLATION", "CLASS_DOWNGRADED")
    assert got[("KR-066.c", loc)][0] == "VIOLATION"
    assert got[("KR-066.b", "Антикоррозионное покрытие")][0] == "EQUAL"
    assert ("KR-066.b", loc) not in got and ("KR-066.a", "Антикоррозионное покрытие") not in got


def test_cabin_short_side_decrease(syn: Any) -> None:
    got = _run([_tx(syn, "ODI-119", "PD", "2,2 м", 2.2), _tx(syn, "ODI-119", "RD", "1,7 м", 1.7)])
    assert _pair(got, "ODI-119") == [("VIOLATION", "VALUE_DECREASED", "OBJECT")]
