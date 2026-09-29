"""Structural materials comparator (КР/КЖ ↔ ИД): concrete class B (KR-055), rebar class (KR-057), element thickness
(KR-058/059/061) and the frost/water marks F/W (FREE-STRUCTURE), per element family.

Input: AG-02C ``kr.*`` values (``inspector_tables.materials``), location = the element family («Сваи»,
«Фундаментная плита», …), ``value_norm.rank`` = the ordinal/number to compare. A family often carries several
values per stage (piles of two classes, walls of two thicknesses), so the rules compare *sets*, conservatively:

* PD → RD (design vs design): a violation only when every RD value is below every PD value
  (``max(RD) < min(PD)``); every RD value above every PD value is an improvement (directional trigger, 97 §2.10:
  an increase where the trigger says decrease is NO_VIOLATION); otherwise equal (verified);
* RD → ИД (and PD → ИД when the family has no RD value): the ИД documents one executed element per act, so a
  violation is an ИД value below *every* design value of the family (``min(ИД) < min(RD)``); ИД values above the
  design (a stronger batch, an over-pour) are never a violation;
* F/W marks lower in ИД than in RD are not catalog parameters (KR-055 is the strength class only): they become one
  evidence-bound FREE-STRUCTURE group per family (criticality «Существенное (предписание)», user-approved rule).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from inspector_common.contracts.models import ExtractedValue
from inspector_compare.valuecmp import ValueDiff

MATERIAL_KEYS = frozenset(
    {
        "kr.concrete_class",
        "kr.concrete_frost",
        "kr.concrete_water",
        "kr.rebar_class",
        "kr.thickness",
        "kr.steel_grade",
        "kr.column_section",
        "kr.column_rebar_diameter",
    }
)
PARAM_KEYS = {
    "kr.concrete_class",
    "kr.rebar_class",
    "kr.thickness",
    "kr.steel_grade",
    "kr.column_section",
    "kr.column_rebar_diameter",
}
# KR-056/060/062: a set-vs-set «equal» needs a shared value
NEW_KEYS = {"kr.steel_grade", "kr.column_section", "kr.column_rebar_diameter"}
# keys whose finding is a numeric decrease (VALUE_DECREASED) rather than a class downgrade
NUMERIC_KEYS = {"kr.thickness", "kr.column_section", "kr.column_rebar_diameter"}
# ИД keys where only an act whose *best* value is below the design counts (stirrups/secondary bars/other grades
# sit next to the main ones in every act)
BEST_ID_KEYS = {"kr.rebar_class", "kr.steel_grade", "kr.column_rebar_diameter"}
UNITS = {"kr.thickness": "мм", "kr.column_rebar_diameter": "мм"}
SUB_IDS = {"KR-058": "KR-058.a", "KR-059": "KR-059.a", "KR-061": "KR-061.a", "KR-060": "KR-060.a"}
MARK_KEYS = ("kr.concrete_frost", "kr.concrete_water")
# thickness is compared PD → RD only (seed KR-058/059/061 sub-check .a)
PD_RD_ONLY = {"kr.thickness", "kr.column_section"}


def _stage(v: ExtractedValue) -> str:
    return str(v.stage.value if hasattr(v.stage, "value") else v.stage)


def _usable(v: ExtractedValue) -> bool:
    flag = str(v.quality_flag.value if hasattr(v.quality_flag, "value") else v.quality_flag)
    return flag == "OK" and v.value_norm.rank is not None and bool(v.location)


def _order(v: ExtractedValue) -> tuple:
    return (v.file_id, v.page_no)


def _shared(
    expected: list[ExtractedValue], actual: list[ExtractedValue]
) -> tuple[ExtractedValue, ExtractedValue] | None:
    """The lowest value (by rank) printed on both sides, as an (expected, actual) pair; None when disjoint."""
    common = {v.value_norm.rank for v in expected} & {v.value_norm.rank for v in actual}
    if not common:
        return None
    r = min(common)
    e = min((v for v in expected if v.value_norm.rank == r), key=_order)
    a = min((v for v in actual if v.value_norm.rank == r), key=_order)
    return e, a


@dataclass(slots=True)
class MarkFinding:
    """F/W marks lower in the actual stage than in the design, for one family (→ FREE-STRUCTURE)."""

    family: str
    axis: str
    expected_stage: str
    actual_stage: str
    diffs: list[ValueDiff] = field(default_factory=list)

    def values(self) -> dict[str, str | None]:
        exp = ", ".join(dict.fromkeys(d.expected.value_raw for d in self.diffs if d.expected))
        act = ", ".join(dict.fromkeys(d.actual.value_raw for d in self.diffs if d.actual))
        out: dict[str, str | None] = {"pd_value": None, "rd_value": None, "id_value": None}
        out[f"{self.expected_stage.lower()}_value"] = exp or None
        out[f"{self.actual_stage.lower()}_value"] = act or None
        return out


def _diff(
    code: str,
    key: str,
    axis: str,
    family: str,
    outcome: str,
    e: ExtractedValue,
    a: ExtractedValue,
    exp_stage: str,
    act_stage: str,
) -> ValueDiff:
    dtype = None
    if outcome == "VIOLATION":
        dtype = "VALUE_DECREASED" if key in NUMERIC_KEYS else "CLASS_DOWNGRADED"
    er, ar = float(e.value_norm.rank or 0), float(a.value_norm.rank or 0)
    delta = ar - er if key in NUMERIC_KEYS and key != "kr.column_section" else None
    rel = abs(delta) / er if delta is not None and er else None
    sub = SUB_IDS.get(code)
    return ValueDiff(
        code=code,
        sub_id=sub,
        axis=axis,
        room=family,
        location_type="ELEMENT",
        outcome=outcome,
        discrepancy_type=dtype,
        expected_stage=exp_stage,
        actual_stage=act_stage,
        expected=e,
        actual=a,
        delta_abs=delta,
        delta_rel=rel,
        unit=UNITS.get(key),
        confidence=round(min(e.confidence, a.confidence) * 0.9, 3),
    )


def _sets(values: Iterable[ExtractedValue]) -> dict[tuple[str, str, str, str], list[ExtractedValue]]:
    """(fact key, param code, family, stage) → usable values."""
    out: dict[tuple[str, str, str, str], list[ExtractedValue]] = defaultdict(list)
    for v in values:
        if v.fact_key not in MATERIAL_KEYS or not _usable(v):
            continue
        out[(str(v.fact_key), str(v.param_code or ""), str(v.location), _stage(v))].append(v)
    return out


def compare_materials(
    values: Iterable[ExtractedValue], axes: Iterable[str]
) -> tuple[list[ValueDiff], list[MarkFinding]]:
    """Param diffs (violations, improvements, equals) and F/W mark findings of one object."""
    axis_list = list(axes)
    sets = _sets(values)
    keys = sorted({(k, c, fam) for (k, c, fam, _) in sets})
    diffs: list[ValueDiff] = []
    marks: dict[tuple[str, str], MarkFinding] = {}
    for key, code, family in keys:
        pd = sets.get((key, code, family, "PD"), [])
        rd = sets.get((key, code, family, "RD"), [])
        idv = sets.get((key, code, family, "ID"), [])
        is_mark = key in MARK_KEYS
        if not is_mark and not code:
            continue  # thickness of a family without a catalog parameter
        # PD → RD (design vs design; marks: no FREE on this axis — precision first)
        if not is_mark and "PD_RD" in axis_list and pd and rd:
            e_min = min(pd, key=lambda v: (v.value_norm.rank, _order(v)))
            e_max = max(pd, key=lambda v: v.value_norm.rank)
            a_max = max(rd, key=lambda v: v.value_norm.rank)
            a_min = min(rd, key=lambda v: (v.value_norm.rank, _order(v)))
            if key == "kr.column_section" and family == "Колонны":
                # columns without a mark: the PD list and the RD list may describe different columns (pilons vs
                # columns, one storey vs another) — only an identical printed section is evidence
                shared = _shared(pd, rd)
                if shared is not None:
                    diffs.append(_diff(code, key, "PD_RD", family, "EQUAL", shared[0], shared[1], "PD", "RD"))
                continue
            if a_max.value_norm.rank < e_min.value_norm.rank:
                diffs.append(_diff(code, key, "PD_RD", family, "VIOLATION", e_min, a_max, "PD", "RD"))
            elif a_min.value_norm.rank > e_max.value_norm.rank:
                diffs.append(_diff(code, key, "PD_RD", family, "IMPROVEMENT", e_max, a_min, "PD", "RD"))
            elif key not in NEW_KEYS:
                diffs.append(_diff(code, key, "PD_RD", family, "EQUAL", e_min, a_min, "PD", "RD"))
            else:
                # KR-056/060/062: «equal» only when both stages print the same value; interleaved but disjoint
                # sets (unmarked columns, mixed steel grades) prove nothing either way
                shared = _shared(pd, rd)
                if shared is not None:
                    diffs.append(_diff(code, key, "PD_RD", family, "EQUAL", shared[0], shared[1], "PD", "RD"))
        if key in PD_RD_ONLY or not idv:
            continue
        design, exp_stage, axis = (rd, "RD", "RD_ID") if rd else (pd, "PD", "PD_ID")
        if not design or axis not in axis_list:
            continue
        d_min = min(design, key=lambda v: (v.value_norm.rank, _order(v)))
        # rebar: stirrups/constructive A240 sit next to the working bars in every act, so only an act whose *best*
        # rebar is below the design is a downgrade; concrete/marks: the weakest executed batch counts
        if key in BEST_ID_KEYS:
            low = max(idv, key=lambda v: v.value_norm.rank)
        else:
            low = min(idv, key=lambda v: (v.value_norm.rank, _order(v)))
        if low.value_norm.rank < d_min.value_norm.rank:
            if is_mark:
                mf = marks.setdefault((family, axis), MarkFinding(family, axis, exp_stage, "ID"))
                mf.diffs.append(
                    _diff("FREE-STRUCTURE", key, axis, family, "VIOLATION", d_min, low, exp_stage, "ID")
                )
            else:
                diffs.append(_diff(code, key, axis, family, "VIOLATION", d_min, low, exp_stage, "ID"))
        elif not is_mark:
            if (
                key in NEW_KEYS
            ):  # the best executed value is not below the design: equal only when it is a design value
                shared = _shared(design, [low])
                if shared is None:
                    continue
                d_min, low = shared
            diffs.append(_diff(code, key, axis, family, "EQUAL", d_min, low, exp_stage, "ID"))
    return diffs, sorted(marks.values(), key=lambda m: (m.family, m.axis))
