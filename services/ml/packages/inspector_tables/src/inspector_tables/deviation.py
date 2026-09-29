"""DEVIATION: «Ведомость отклонений» / tolerance tables of executive (ИГС) documentation.

Header grammar: № п/п | Конструкция (элемент) | Оси | Контролируемый параметр | Проектное значение |
Фактическое значение | Отклонение | Допуск (допустимое отклонение) | Ед. изм. | Примечание. The anchor is the
«Фактическое» header, which only these tables carry. Works on the text layer and on OCR tokens (scanned ИД:
ruled via raster rulings, or aligned by rows).

Per row the parser computes the deviation (actual − design) when both are numbers, compares it with the
printed one, and tests it against the tolerance («±10», «+5/−10», «10» → ±10). There is no TableCheckKind
for a tolerance breach yet (requested from AG-00): the verdict travels on the ``id.deviation`` value
(qualifiers ``within_tolerance``, ``computed_deviation``), where the ИД comparators read it.

No train page has such a table in its text layer (the Новослободская executive schemes print deviations as
drawing annotations); the parser is covered by synthetic tables and runs on OCR tokens of scanned binders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.grid import ColumnSpec, RawRow, RawTable, TableSpec, find_tables
from inspector_tables.pagesource import PageData
from inspector_tables.text import parse_number, squash

SPEC = TableSpec(
    table_type="DEVIATION",
    anchor=r"^фактическ",
    columns=(
        ColumnSpec("_row_no", (r"^№( п п)?$", r"^n п п$", r"^п п$")),
        ColumnSpec("element", (r"^конструкци", r"^элемент", r"^наименование (конструкц|элемент|работ)")),
        ColumnSpec("axes", (r"^ос[иь]", r"в осях", r"^оси")),
        ColumnSpec("parameter", (r"^параметр", r"^контролируем", r"^наименование параметр", r"^показател")),
        ColumnSpec("design_value", (r"проектн",)),
        ColumnSpec("actual_value", (r"фактическ",)),
        ColumnSpec("deviation", (r"^отклонени", r"^фактическое отклонени")),
        ColumnSpec("tolerance", (r"допуск", r"допустим", r"предельн")),
        ColumnSpec("unit", (r"^ед",)),
        ColumnSpec("note", (r"примечан", r"заключени", r"вывод")),
    ),
    required=frozenset({"actual_value"}),
    key_column="parameter",
    caption=r"отклонени|исполнительн|ведомост",
)
PARSER_VERSION = "deviation-1"
KEYS = (
    "element",
    "axes",
    "parameter",
    "design_value",
    "actual_value",
    "deviation",
    "tolerance",
    "unit",
    "note",
)
_TOL_PM = re.compile(r"^±\s*(\d+(?:[.,]\d+)?)$")
_TOL_PAIR = re.compile(r"^\+?\s*(\d+(?:[.,]\d+)?)\s*/\s*[-−–]\s*(\d+(?:[.,]\d+)?)$")


def parse_tolerance(raw: str | None) -> tuple[float, float] | None:
    """«±10» → (−10, 10); «+5/−10» → (−10, 5); «10» → (−10, 10); None when not a tolerance."""
    s = squash(raw or "").replace(" ", "")
    if not s:
        return None
    m = _TOL_PM.match(s)
    if m:
        v = float(m.group(1).replace(",", "."))
        return (-v, v)
    m = _TOL_PAIR.match(s)
    if m:
        return (-float(m.group(2).replace(",", ".")), float(m.group(1).replace(",", ".")))
    v = parse_number(s)
    if v is not None:
        return (-abs(v), abs(v))
    return None


@dataclass(slots=True)
class DeviationRow:
    cells: dict[str, str]
    raw: RawRow
    page_no: int
    computed: float | None = None
    within: bool | None = None
    consistent: bool | None = None  # printed deviation == actual − design


@dataclass(slots=True)
class LogicalDeviation:
    parts: list[RawTable]
    rows: list[DeviationRow] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    caption: str | None = None


def _new_row(cells: dict[str, str]) -> bool:
    return bool(squash(cells.get("_row_no", ""))) or parse_number(cells.get("actual_value")) is not None


def evaluate(row: DeviationRow) -> None:
    design = parse_number(row.cells.get("design_value"))
    actual = parse_number(row.cells.get("actual_value"))
    printed = parse_number(row.cells.get("deviation"))
    if design is not None and actual is not None:
        row.computed = round(actual - design, 6)
        if printed is not None:
            row.consistent = abs(row.computed - printed) <= 0.51 * _ulp(row.cells.get("deviation", ""))
    dev = printed if printed is not None else row.computed
    tol = parse_tolerance(row.cells.get("tolerance"))
    if dev is not None and tol is not None:
        row.within = tol[0] - 1e-9 <= dev <= tol[1] + 1e-9


def _ulp(raw: str) -> float:
    m = re.search(r"[.,](\d+)\s*$", raw or "")
    return 10.0 ** -len(m.group(1)) if m else 1.0


def parse_page(page: PageData) -> list[LogicalDeviation]:
    out = []
    for t in find_tables(page, SPEC, new_row=_new_row):
        keys = set(t.keys)
        # a deviation table states the deviation or the tolerance; «нормируемое / расчётное / фактическое
        # значение» of an energy passport (F0152 p64) has neither
        if not ({"deviation", "tolerance"} & keys) or not ({"design_value", "deviation"} & keys):
            continue
        ld = LogicalDeviation([t], caption=t.caption)
        for r in t.rows:
            cells = {k: squash(r.text(k)) for k in KEYS}
            if not any(cells.values()) or r.merged:
                continue
            if (
                all(re.fullmatch(r"\d{1,2}", v) for v in cells.values() if v)
                and sum(1 for v in cells.values() if v) >= 3
            ):
                continue
            row = DeviationRow(cells, r, t.page_no)
            evaluate(row)
            ld.rows.append(row)
        if not ld.rows:
            continue
        n_bad = sum(1 for r in ld.rows if r.within is False)
        ld.checks.append({"kind": "ROW_COUNT", "passed": True, "expected": None, "actual": len(ld.rows),
                          "detail": f"Строк: {len(ld.rows)}; вне допуска: {n_bad}"})  # fmt: skip
        out.append(ld)
    return out
