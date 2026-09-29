"""ИД-internal TOLERANCE_CHECK (axis NORM_ID): measured deviations on an executive geodetic scheme (ИГС) against the
допуск printed on the same sheet (seed sub-checks KR-054.b, KR-058.b, KR-059.b, KR-061.b; pilot OKT103-V01:
«Допуски на листе: 15 мм, ±12 мм и 20 мм. Факт: +491/+552, +980/+537 и +201/+349 мм» → KR-054).

Evidence-bound and conservative:

* both anchors are the one ИД page that prints the tolerance and the deviations (``id.tolerance`` and
  ``id.deviation`` values with qualifier source=IGS_ANNOTATION, AG-02C ``inspector_tables.igs``);
* only the sheet's own tolerance is used (TOLERANCE_NOT_FOUND → abstain; the normative fallback of the seed is
  not applied), and a deviation breaches it only above the **largest** tolerance printed on the page (a sheet
  that states 15 / ±12 / 20 мм is read at 20 мм);
* a page fires only with ≥ 2 deviations read and either ≥ 2 breaches or one breach of at least twice the
  tolerance (a single OCR slip does not make a finding);
* the code follows the scheme: thickness tolerances on walls → KR-061, on a foundation slab → KR-058, on floor
  slabs → KR-059 (direction DECREASE: only negative deviations count); elevation-only tolerances on a slab →
  KR-058/KR-059 (DECREASE); everything else (axes, columns, piles, plan position) → KR-054 (ANY);
  elevation-only tolerances elsewhere abstain;
* one finding per code at location OBJECT; the page with the largest breach ratio is the anchor.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from inspector_common.contracts.models import ExtractedValue
from inspector_compare.valuecmp import ValueDiff

SOURCE = "IGS_ANNOTATION"
MIN_DEVIATIONS = 2
MIN_BREACHES = 2
STRONG_RATIO = 2.0


@dataclass(slots=True)
class PageVerdict:
    file_id: str
    page_no: int
    code: str | None
    direction: str
    tolerance: ExtractedValue
    worst: ExtractedValue | None
    breaches: int
    deviations: int
    ratio: float
    reason: str | None = None


def _q(v: ExtractedValue) -> dict:
    return dict(v.value_norm.qualifiers or {})


def _num(v: ExtractedValue) -> float | None:
    try:
        return float(v.value_norm.value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _usable(v: ExtractedValue) -> bool:
    flag = str(v.quality_flag.value if hasattr(v.quality_flag, "value") else v.quality_flag)
    return flag == "OK" and _num(v) is not None


def route(element_kind: str | None, kinds: set[str | None]) -> tuple[str | None, str]:
    """(catalog code, direction) of one scheme page; code None = abstain."""
    stated = {k for k in kinds if k}
    if "THICKNESS" in stated:
        return {"WALL": "KR-061", "FOUNDATION_SLAB": "KR-058", "FLOOR_SLAB": "KR-059"}.get(
            element_kind or ""
        ), "DECREASE"
    if stated == {"ELEVATION"}:
        return {"FOUNDATION_SLAB": "KR-058", "FLOOR_SLAB": "KR-059"}.get(element_kind or ""), "DECREASE"
    return "KR-054", "ANY"


def _excess(d: ExtractedValue, direction: str) -> float:
    """|deviation| that counts against the tolerance (DECREASE: only a negative, thinner/lower deviation)."""
    x = _num(d) or 0.0
    if direction == "DECREASE" and x >= 0:
        return 0.0
    return abs(x)


def page_verdicts(values: Iterable[ExtractedValue]) -> list[PageVerdict]:
    by_page: dict[tuple[str, int], dict[str, list[ExtractedValue]]] = defaultdict(lambda: defaultdict(list))
    for v in values:
        if v.fact_key not in ("id.tolerance", "id.deviation") or _q(v).get("source") != SOURCE:
            continue
        stage = str(v.stage.value if hasattr(v.stage, "value") else v.stage)
        if stage != "ID" or not _usable(v):
            continue
        by_page[(v.file_id, v.page_no)][v.fact_key].append(v)
    out: list[PageVerdict] = []
    for (fid, pg), facts in sorted(by_page.items()):
        tols = facts.get("id.tolerance") or []
        devs = facts.get("id.deviation") or []
        if not tols:
            continue
        tol = max(tols, key=lambda t: (_num(t) or 0.0, -t.confidence))
        tol_mm = abs(_num(tol) or 0.0)
        element_kind = _q(tol).get("element_kind")
        code, direction = route(element_kind, {_q(t).get("kind") for t in tols})
        if tol_mm <= 0:
            continue
        if code is None:
            out.append(
                PageVerdict(fid, pg, None, direction, tol, None, 0, len(devs), 0.0, "ELEMENT_KEY_UNRESOLVED")
            )
            continue
        if len(devs) < MIN_DEVIATIONS:
            out.append(PageVerdict(fid, pg, code, direction, tol, None, 0, len(devs), 0.0, "VALUE_NOT_FOUND"))
            continue

        breaches = [d for d in devs if _excess(d, direction) > tol_mm + 1e-9]
        worst = max(devs, key=lambda d: (_excess(d, direction), d.confidence))
        ratio = _excess(worst, direction) / tol_mm
        out.append(PageVerdict(fid, pg, code, direction, tol, worst if breaches else None, len(breaches), len(devs),
                               ratio))  # fmt: skip
    return out


def fires(v: PageVerdict) -> bool:
    return (
        v.code is not None
        and v.worst is not None
        and v.reason is None
        and (v.breaches >= MIN_BREACHES or v.ratio >= STRONG_RATIO)
    )


def tolerance_diffs(values: Iterable[ExtractedValue]) -> tuple[list[ValueDiff], list[PageVerdict]]:
    """One VIOLATION diff per code (the worst page) plus an EQUAL diff per code whose pages all passed; the
    verdicts of every page (for the trace and abstentions)."""
    verdicts = page_verdicts(values)
    by_code: dict[str, list[PageVerdict]] = defaultdict(list)
    for v in verdicts:
        if v.code is not None and v.reason is None:
            by_code[v.code].append(v)
    diffs: list[ValueDiff] = []
    for code, vs in sorted(by_code.items()):
        firing = [v for v in vs if fires(v)]
        sub_id = f"{code}.b"
        if not firing:
            v = vs[0]
            diffs.append(ValueDiff(code=code, sub_id=sub_id, axis="NORM_ID", room="OBJECT", location_type="OBJECT",
                                   outcome="EQUAL", discrepancy_type=None, expected_stage="ID", actual_stage="ID",
                                   expected=v.tolerance, actual=v.tolerance, unit="мм", confidence=0.0,
                                   mode="TOLERANCE"))  # fmt: skip
            continue
        best = max(firing, key=lambda v: (v.ratio, v.breaches, -v.page_no))
        assert best.worst is not None
        tol_mm = abs(_num(best.tolerance) or 0.0)
        dev_mm = abs(_num(best.worst) or 0.0)
        conf = round(min(best.tolerance.confidence, best.worst.confidence) * 0.9, 3)
        diffs.append(
            ValueDiff(
                code=code,
                sub_id=sub_id,
                axis="NORM_ID",
                room="OBJECT",
                location_type="OBJECT",
                outcome="VIOLATION",
                discrepancy_type="TOLERANCE_EXCEEDED",
                expected_stage="ID",
                actual_stage="ID",
                expected=best.tolerance,
                actual=best.worst,
                delta_abs=round(dev_mm - tol_mm, 3),
                delta_rel=round((dev_mm - tol_mm) / tol_mm, 4) if tol_mm else None,
                unit="мм",
                confidence=conf,
                mode="TOLERANCE",
            )
        )
    return diffs, verdicts


def ru_mm(v: ExtractedValue | None, signed: bool = False) -> str | None:
    x = _num(v) if v is not None else None
    if x is None:
        return None
    text = (f"{x:+g}" if signed else f"{abs(x):g}").replace(".", ",").replace("-", "−")
    return f"{text} мм"


def id_value_text(diff: ValueDiff) -> str:
    """«+491 мм при допуске 20 мм» — the id_value of a tolerance finding (the ИД sheet states both)."""
    return f"{ru_mm(diff.actual, signed=True)} при допуске {ru_mm(diff.expected)}"
