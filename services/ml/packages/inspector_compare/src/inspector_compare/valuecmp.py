"""Value comparators over extracted values (AG-02C ``values/<object_id>.jsonl``), per matrix rule (04 §3.5.1–3.5.2).

For each parameter, the seed ``comparison_rule`` (or its ``sub_checks``) of type PAIRWISE_DELTA, ORDINAL_COMPARE or
ENUM_CHANGE is evaluated on every compare pair (expected stage → actual stage) where both stages have a value for
the same location (or the object):

- **directional triggers** (97 §2.10): DECREASE fires only on a decrease beyond the tolerance, INCREASE only on an
  increase, DOWNGRADE only on a lower ordinal rank; the opposite direction is an IMPROVEMENT (context, never a
  violation); ANY fires both ways;
- tolerance: ``max(abs, rel·|expected|, ½ unit of the shown precision)`` (SOURCE_PRECISION rounding);
- values with another unit, an ambiguous reading or a LOW_QUALITY/ABSTAIN flag abstain (AbstainReason).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from inspector_common.contracts.models import ExtractedValue
from inspector_compare.observe import PageRef
from inspector_compare.values import ru_number

# LAYER_STACK (ZU-125/128): the extracted value is the total thickness of the insulation layer of one material
# group, compared like a numeric delta in the rule's direction (THICKNESS_DECREASED → VALUE_DECREASED).
SUPPORTED = {"PAIRWISE_DELTA", "ORDINAL_COMPARE", "ENUM_CHANGE", "LAYER_STACK"}
AXIS_OF = {("PD", "RD"): "PD_RD", ("RD", "ID"): "RD_ID", ("PD", "ID"): "PD_ID"}


@dataclass(slots=True)
class ValueDiff:
    code: str
    sub_id: str | None
    axis: str
    room: str  # location token («OBJECT» for object-level values)
    location_type: str
    outcome: str  # VIOLATION | IMPROVEMENT | EQUAL | ABSTAIN
    discrepancy_type: str | None
    expected_stage: str
    actual_stage: str
    expected: ExtractedValue | None
    actual: ExtractedValue | None
    delta_abs: float | None = None
    delta_rel: float | None = None
    unit: str | None = None
    confidence: float = 0.0
    reason: str | None = None
    mode: str = "VALUE"
    revision_labels: list[str] = field(default_factory=list)
    texts: dict[str, str] | None = (
        None  # printed values when the extracted value is not the compared one (spec items)
    )

    @property
    def is_violation(self) -> bool:
        return self.outcome == "VIOLATION"

    def _ref(self, v: ExtractedValue | None) -> list[PageRef]:
        if v is None:
            return []
        return [PageRef(str(v.stage.value if hasattr(v.stage, "value") else v.stage), v.file_id, v.page_no)]

    def expected_pages(self) -> list[PageRef]:
        return self._ref(self.expected)

    def actual_pages(self) -> list[PageRef]:
        return self._ref(self.actual)

    def boxes(self, v: ExtractedValue | None) -> list[list[float]]:
        if v is None or v.geometry is None or not v.geometry.boxes:
            return []
        return [list(b) for b in v.geometry.boxes]


def _decimals(raw: str) -> int:
    m = re.search(r"\d+[.,](\d+)", raw or "")
    return len(m.group(1)) if m else 0


def _num(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def format_value(v: ExtractedValue | None) -> str | None:
    """Russian cell text of an extracted value: «1,0 м», «B35», «850 м²»."""
    if v is None:
        return None
    norm = v.value_norm
    dtype = str(norm.type.value if hasattr(norm.type, "value") else norm.type)
    if dtype == "number":
        n = _num(norm.value)
        if n is None:
            return v.value_raw
        text = ru_number(n, _decimals(v.value_raw) or None)
        return f"{text} {norm.unit}" if norm.unit else text
    return str(norm.value) if norm.value is not None else v.value_raw


def _usable(v: ExtractedValue) -> bool:
    flag = str(v.quality_flag.value if hasattr(v.quality_flag, "value") else v.quality_flag)
    return flag == "OK" and not v.is_ambiguous and (v.candidate_rank or 1) == 1


def best_values(values: Iterable[ExtractedValue]) -> dict[tuple[str, str, str], ExtractedValue]:
    """(param code, location, stage) → the most confident usable value (ties: lower file id, then page)."""
    groups: dict[tuple[str, str, str], list[ExtractedValue]] = defaultdict(list)
    for v in values:
        if not v.param_code or not _usable(v):
            continue
        stage = str(v.stage.value if hasattr(v.stage, "value") else v.stage)
        groups[(str(v.param_code), v.location or "OBJECT", stage)].append(v)
    return {k: sorted(vs, key=lambda v: (-v.confidence, v.file_id, v.page_no))[0] for k, vs in groups.items()}


def _sub_checks(rule: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    subs = rule.get("sub_checks")
    return list(subs) if subs else [rule]


def evaluate_pair(
    sub: Mapping[str, Any], expected: ExtractedValue, actual: ExtractedValue
) -> tuple[str, str | None, float | None, float | None, str | None]:
    """(outcome, discrepancy_type, delta_abs, delta_rel, reason) for one sub-check on one value pair."""
    rule_type = sub.get("rule_type")
    direction = str(sub.get("direction") or "ANY")
    e_norm, a_norm = expected.value_norm, actual.value_norm
    if rule_type in ("ORDINAL_COMPARE", "ENUM_CHANGE") or direction == "DOWNGRADE":
        if e_norm.rank is None or a_norm.rank is None:
            if rule_type == "ENUM_CHANGE" and direction == "ANY":
                same = str(e_norm.value) == str(a_norm.value)
                return (
                    ("EQUAL", None, None, None, None)
                    if same
                    else ("VIOLATION", "VALUE_CHANGED", None, None, None)
                )
            return "ABSTAIN", None, None, None, "UNKNOWN_SCALE_VALUE"
        if a_norm.rank < e_norm.rank:
            return "VIOLATION", "CLASS_DOWNGRADED", None, None, None
        if a_norm.rank > e_norm.rank:
            return (
                ("VIOLATION", "VALUE_CHANGED", None, None, None)
                if direction == "ANY"
                else ("IMPROVEMENT", None, None, None, None)
            )
        return "EQUAL", None, None, None, None
    if rule_type not in ("PAIRWISE_DELTA", "LAYER_STACK"):
        return "ABSTAIN", None, None, None, "RULE_NOT_SUPPORTED"
    if (e_norm.unit or None) != (a_norm.unit or None):
        return "ABSTAIN", None, None, None, "UNIT_MISMATCH"
    e, a = _num(e_norm.value), _num(a_norm.value)
    if e is None or a is None:
        return "ABSTAIN", None, None, None, "VALUE_NOT_FOUND"
    tol = sub.get("tolerance") or {}
    shown = min(_decimals(expected.value_raw), _decimals(actual.value_raw))
    eps = Decimal("0.5") * Decimal(10) ** -shown
    if tol.get("abs") is not None:
        eps = max(eps, Decimal(str(tol["abs"])))
    if tol.get("rel") is not None and e != 0:
        eps = max(eps, Decimal(str(tol["rel"])) * abs(e))
    delta = a - e
    rel = float(abs(delta) / abs(e)) if e != 0 else None
    if abs(delta) <= eps:
        return "EQUAL", None, float(delta), rel, None
    decreased = delta < 0
    if (direction == "DECREASE" and not decreased) or (direction == "INCREASE" and decreased):
        return "IMPROVEMENT", None, float(delta), rel, None
    return "VIOLATION", "VALUE_DECREASED" if decreased else "VALUE_INCREASED", float(delta), rel, None


def _basis(v: ExtractedValue) -> str | None:
    q = v.value_norm.qualifiers or {}
    return q.get("basis") if isinstance(q, Mapping) else None


def candidate_values(values: Iterable[ExtractedValue]) -> dict[tuple[str, str, str], list[ExtractedValue]]:
    """(param code, location, stage) → every usable design value, most confident first. A ГПЗУ limit column of a
    ТЭП (qualifier basis=ГПЗУ) is a permitted bound, not a design value, and is never compared pairwise."""
    groups: dict[tuple[str, str, str], list[ExtractedValue]] = defaultdict(list)
    for v in values:
        if not v.param_code or not _usable(v) or _basis(v) == "ГПЗУ":
            continue
        stage = str(v.stage.value if hasattr(v.stage, "value") else v.stage)
        groups[(str(v.param_code), v.location or "OBJECT", stage)].append(v)
    return {k: sorted(vs, key=lambda v: (-v.confidence, v.file_id, v.page_no)) for k, vs in groups.items()}


def _with_unit(v: ExtractedValue, unit: str | None) -> ExtractedValue:
    """A value without a printed unit read in the catalog unit (a ТЭП sub-row «- подземная часть» under a row that
    states «м³»); a value with another unit keeps it (UNIT_MISMATCH abstains). Counts (шт., ед.) are unitless."""
    if unit == "COUNT":
        if v.value_norm.unit is None:
            return v
        return v.model_copy(update={"value_norm": v.value_norm.model_copy(update={"unit": None})})
    if v.value_norm.unit or not unit:
        return v
    return v.model_copy(update={"value_norm": v.value_norm.model_copy(update={"unit": unit})})


_RANK = {"EQUAL": 0, "IMPROVEMENT": 1, "VIOLATION": 2, "ABSTAIN": 3}
MAX_CANDIDATES = 8


def evaluate_sets(
    sub: Mapping[str, Any],
    expected: list[ExtractedValue],
    actual: list[ExtractedValue],
    unit: str | None = None,
) -> tuple[ExtractedValue, ExtractedValue, tuple[str, str | None, float | None, float | None, str | None]]:
    """Conservative set rule over the candidate values of both stages: EQUAL when any reading agrees, then an
    IMPROVEMENT; a VIOLATION only when no pair agrees, reported on the closest pair (the smallest |Δ|)."""
    best: tuple[Any, ...] | None = None
    for e in expected[:MAX_CANDIDATES]:
        for a in actual[:MAX_CANDIDATES]:
            e_u, a_u = _with_unit(e, unit), _with_unit(a, unit)
            res = evaluate_pair(sub, e_u, a_u)
            key = (
                _RANK[res[0]],
                abs(res[2]) if res[2] is not None else float("inf"),
                -min(e.confidence, a.confidence),
            )
            if best is None or key < best[0]:
                best = (key, e, a, res)
    assert best is not None
    return best[1], best[2], best[3]


COUNT_UNITS = frozenset({"шт.", "шт", "ед.", "ед", "эт.", "эт", "м/м", "маш.-мест", "кв."})
MEASURE_UNITS = frozenset({"м²", "м³", "м", "мм", "мм²"})


def _catalog_unit(spec: Any) -> str | None:
    """The catalog unit when it is a measure the ТЭП prints in canonical form; «COUNT» for counts (шт., ед.)."""
    unit = str(getattr(spec, "unit", "") or "").strip()
    if unit in MEASURE_UNITS:
        return unit
    if unit in COUNT_UNITS:
        return "COUNT"
    return None


def _for_sub(vs: list[ExtractedValue] | None, sub: Mapping[str, Any]) -> list[ExtractedValue]:
    """The values that belong to this sub-check: a value pinned to one sub-check (qualifier ``sub_id``) is compared
    only by it; a value without the qualifier belongs to every sub-check."""
    sid = sub.get("sub_id")
    return [
        v
        for v in vs or []
        if not isinstance(v.value_norm.qualifiers, Mapping)
        or not v.value_norm.qualifiers.get("sub_id")
        or v.value_norm.qualifiers.get("sub_id") == sid
    ]


def compare_values(values: Iterable[ExtractedValue], params: Any, axes: Iterable[str]) -> list[ValueDiff]:
    """Every value comparison of the object (violations, improvements, equals, abstentions)."""
    cands = candidate_values(values)
    by_param: dict[str, dict[str, dict[str, list[ExtractedValue]]]] = defaultdict(lambda: defaultdict(dict))
    for (code, loc, stage), vs in cands.items():
        by_param[code][loc][stage] = vs
    axis_list = list(axes)
    out: list[ValueDiff] = []
    for code in sorted(by_param):
        try:
            spec = params.get(code)
        except Exception:
            continue
        unit = _catalog_unit(spec)
        for sub in _sub_checks(spec.comparison_rule):
            if sub.get("rule_type") not in SUPPORTED:
                continue
            pairs = [(p.get("expected"), p.get("actual")) for p in sub.get("compare") or []]
            for loc, stages in sorted(by_param[code].items()):
                for exp_stage, act_stage in pairs:
                    axis = AXIS_OF.get((exp_stage, act_stage))
                    if axis is None or axis not in axis_list:
                        continue
                    es, as_ = _for_sub(stages.get(exp_stage), sub), _for_sub(stages.get(act_stage), sub)
                    if not es or not as_:
                        continue
                    e, a, (outcome, dtype, d_abs, d_rel, reason) = evaluate_sets(sub, es, as_, unit)
                    out.append(
                        ValueDiff(
                            code=code,
                            sub_id=sub.get("sub_id"),
                            axis=axis,
                            room=loc,
                            location_type=str(
                                e.location_type.value
                                if hasattr(e.location_type, "value")
                                else e.location_type
                            )
                            if e.location_type
                            else ("OBJECT" if loc == "OBJECT" else "ELEMENT"),
                            outcome=outcome,
                            discrepancy_type=dtype,
                            expected_stage=exp_stage,
                            actual_stage=act_stage,
                            expected=e,
                            actual=a,
                            delta_abs=d_abs,
                            delta_rel=d_rel,
                            unit=e.value_norm.unit
                            or a.value_norm.unit
                            or (unit if unit != "COUNT" else None),
                            confidence=round(min(e.confidence, a.confidence) * 0.9, 3),
                            reason=reason,
                        )
                    )
    return out


def delta_text(diff: ValueDiff, fmt: Any) -> str | None:
    """{delta} of the templates by ``delta_format`` (PCT «16%», ABS «0,3 м», NONE/COUNT → None here)."""
    if isinstance(fmt, Mapping):
        fmt = fmt.get("default")
    fmt = str(fmt or "NONE").upper()
    if fmt == "PCT" and diff.delta_rel is not None:
        pct = Decimal(str(diff.delta_rel * 100)).quantize(Decimal("0.1"))
        return ru_number(pct) + "%"
    if fmt == "ABS" and diff.delta_abs is not None:
        text = ru_number(Decimal(str(abs(diff.delta_abs))))
        return f"{text} {diff.unit}" if diff.unit else text
    return None
