"""TEP: «Технико-экономические показатели» (96 §6: row aligner, number re-join, ГПЗУ/ПД columns).

Columns: «№ п/п» (hierarchy only), «Наименование» → indicator, «Ед. изм.» → unit, «Кол-во» / «Показатель по
ПД» → value, «Показатель по ГПЗУ» (the permitted limit) → note (the column's header_raw says which; a
dedicated contract column is requested from AG-00). Numbers split by the text layer into thousands groups
(«17» «140,2») are re-joined by the cell joiner. «в т.ч.» children are SUBZONE rows under their parent, by the
printed numbering («3.1» under «3») or, for unnumbered rows («Корпус 1»), under the last «в т.ч.» row.

Indicator → catalog parameter mapping (``PARAM_PATTERNS``) is deliberately literal (the catalog names of
PZ-001…/SPZU-02x, 03 §11 phrasings); an unmapped row still yields a ``tep.value`` fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.grid import ColumnSpec, RawTable, TableSpec, find_tables
from inspector_tables.pagesource import PageData
from inspector_tables.text import first_number, fold, norm_unit, parse_number, resplit_glued, squash

SPEC = TableSpec(
    table_type="TEP",
    anchor=r"^наименовани|^показатели$",
    columns=(
        ColumnSpec("_row_no", (r"^№( п п)?$", r"^n п п$", r"^п п$", r"^№ п$")),
        ColumnSpec("indicator", (r"^наименовани", r"^показатели$", r"^наименование показател")),
        ColumnSpec("unit", (r"^ед", r"единиц")),
        ColumnSpec("note", (r"гпзу", r"примечан", r"нормативн", r"допустим", r"по заданию")),
        ColumnSpec(
            "value",
            (
                r"кол во",
                r"количеств",
                r"значени",
                r"по пд\b",
                r"по проекту",
                r"проектн",
                r"величин",
                r"показател",
            ),
        ),
    ),
    required=frozenset({"indicator", "value"}),
    key_column="indicator",
    caption=r"технико экономическ|\bтэп\b",
    content_keys=(("_row_no", "rowno"),),
)
# column order in the printed table: № | Наименование | Ед. | (ГПЗУ) | ПД
ORDER = ("_row_no", "indicator", "unit", "note", "value")
PARSER_VERSION = "tep-1"

_ROWNO = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,3}\.?$")
_INCL = re.compile(r"(в\s*т\.\s*ч\.?|в\s+том\s+числе)\s*:?\s*$", re.I)

# (param_code, regex on the folded indicator, stage hint) — literal catalog names and the real phrasings of 96 §11
PARAM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("PZ-001", r"^площадь застройки"),
    ("PZ-002", r"^общая площадь (здания|объекта)|^площадь (жилого )?здания"),
    ("PZ-003", r"^полезная площадь"),
    ("PZ-004", r"^строительный объем(?! (подземн|надземн|наземн))"),
    ("PZ-005", r"^(строительный объем )?подземн\w* част"),
    ("PZ-006", r"^(строительный объем )?(надземн|наземн)\w* част"),
    ("PZ-007", r"^(количество этажей|этажность)"),
    ("PZ-008", r"^высота (здания|объекта)"),
    ("PZ-010", r"^количество квартир"),
    # surface parking on the plot (СПЗУ) before the generic «машино-мест» row of the building (PZ-012)
    (
        "SPZU-037",
        r"^(количество )?(наземн\w* |открыт\w* |гостев\w* |приобъектн\w* )(парковочн\w* |машино )?мест"
        r"|^(количество )?(парковочных мест|машино мест) (на|в границах) (участк|открыт|наземн|территори)",
    ),
    ("PZ-012", r"^(количество )?машино мест"),
    ("PZ-019", r"^коэффициент застройки"),
    ("PZ-020", r"^коэффициент (использования|плотности) (территории|застройки)"),
    # object-level ПЗ parameters printed as ТЭП rows (pzparams reads the same values from prose)
    ("PZ-013", r"^(проектная )?(мощность|вместимость) (объекта|здания|учреждения)$|^вместимость$"),
    ("PZ-014", r"^расчетная (электрическая )?(мощность|нагрузка)"),
    ("PZ-016", r"^(суточное )?водопотребление|^суточный расход воды"),
    ("PZ-017", r"^(суммарная |общая )?тепловая нагрузка"),
    ("PZ-018", r"^(максимальный )?(часовой )?расход (природного )?газа"),
    ("PZ-021", r"^класс энерг\w* (эффективности|сбережения)|^класс энергоэффективности"),
    ("PZ-022", r"^степень огнестойкости"),
    ("PZ-023", r"^класс конструктивной пожарной опасности"),
    ("SPZU-025", r"^площадь асфальтобетонного покрытия"),
    ("SPZU-026", r"^площадь (плиточного покрытия|покрытия из (бетонной )?плитки)"),
    ("SPZU-027", r"^площадь озеленения"),
    ("SPZU-028", r"^площадь (детских|спортивных|игровых) (и спортивных )?площадок"),
)


@dataclass(slots=True)
class TepRow:
    kind: str
    row_no: str | None
    indicator: str
    unit: str
    value_raw: str
    value: float | None
    limit_raw: str
    limit: float | None
    raw: object
    page_no: int
    parent: int | None = None
    section: str | None = None
    param_code: str | None = None


@dataclass(slots=True)
class LogicalTep:
    parts: list[RawTable]
    rows: list[TepRow] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    caption: str | None = None


def map_param(indicator: str, parent_indicator: str | None = None) -> str | None:
    f = fold(indicator)
    for code, pat in PARAM_PATTERNS:
        if re.search(pat, f):
            if code in ("PZ-005", "PZ-006") and parent_indicator and "объем" not in fold(parent_indicator):
                continue
            return code
    return None


def _value(raw: str) -> float | None:
    v = parse_number(raw)
    if v is not None:
        return v
    return None


def classify(parts: list[RawTable]) -> list[TepRow]:
    rows: list[TepRow] = []
    last_incl: int | None = None
    for t in parts:
        for r in t.rows:
            row_no = squash(r.text("_row_no")) or None
            indicator = resplit_glued(squash(r.text("indicator")))
            unit = squash(r.text("unit"))
            value_raw = squash(r.text("value"))
            limit_raw = squash(r.text("note"))
            if not any((row_no, indicator, unit, value_raw, limit_raw)):
                continue
            if r.merged:
                text = squash(r.merged_text)
                rows.append(TepRow("SECTION_HEADER", None, text, "", "", None, "", None, r, t.page_no))
                continue
            if row_no and re.fullmatch(r"\d{1,2}(?:\s\d{1,2}){1,8}", row_no) and not indicator:
                continue  # the «1 2 3 4» column-number row under the header
            kind = "DATA"
            if not value_raw and not unit and not limit_raw and indicator and not row_no:
                kind = "SECTION_HEADER"
            rows.append(TepRow(kind, row_no, indicator, unit, value_raw, _value(value_raw), limit_raw, _value(limit_raw), r,
                               t.page_no))  # fmt: skip
            idx = len(rows) - 1
            if kind == "DATA":
                if row_no and _ROWNO.match(row_no):
                    base = row_no.rstrip(".")
                    parent = None
                    if "." in base:
                        prefix = base.rsplit(".", 1)[0]
                        parent = next(
                            (
                                i
                                for i in range(idx - 1, -1, -1)
                                if (rows[i].row_no or "").rstrip(".") == prefix
                            ),
                            None,
                        )
                    if parent is not None:
                        rows[idx].kind = "SUBZONE"
                        rows[idx].parent = parent
                    # unnumbered rows («Корпус 1», «подземная часть») attach to the last NUMBERED «в т.ч.» row
                    last_incl = (
                        idx if _INCL.search(indicator) else (last_incl if parent is not None else None)
                    )
                elif not row_no and last_incl is not None:
                    rows[idx].kind = "SUBZONE"
                    rows[idx].parent = last_incl
            parent = rows[idx].parent
            parent_ind = rows[parent].indicator if parent is not None else None
            if rows[idx].kind != "SECTION_HEADER":
                code = map_param(indicator, parent_ind)
                # a component never inherits its parent's parameter («Площадь застройки наземной части»)
                if code and parent is not None and rows[parent].param_code == code:
                    code = None
                rows[idx].param_code = code
    return rows


def _ulp(raw: str) -> float:
    m = re.search(r"[.,](\d+)\s*$", raw or "")
    return 10.0 ** -len(m.group(1)) if m else 1.0


def checks(rows: list[TepRow]) -> list[dict]:
    """Σ of the «в т.ч.» children vs the parent value, where children share the parent's unit."""
    out: list[dict] = []
    for i, r in enumerate(rows):
        kids = [j for j, c in enumerate(rows) if c.parent == i and c.value is not None]
        if r.value is None or len(kids) < 2 or not _INCL.search(r.indicator):
            continue
        kid_units = {norm_unit(rows[j].unit) or fold(rows[j].unit) for j in kids if rows[j].unit}
        if len(kid_units) > 1:
            continue  # children in different units are not additive
        s = round(sum(rows[j].value for j in kids), 3)  # type: ignore[misc]
        # half a unit of the last printed digit, parent and children (values are rounded as printed)
        tol = 0.5 * _ulp(r.value_raw) + sum(0.5 * _ulp(rows[j].value_raw) for j in kids) + 1e-6
        passed = abs(s - r.value) <= tol
        out.append({"kind": "SUM_MATCHES_TOTAL", "passed": passed, "expected": round(s, 3), "actual": r.value,
                    "rows": sorted({i + 1, *[j + 1 for j in kids]}),
                    "detail": f"«{r.indicator}»: Σ составляющих {s:g}, в таблице {r.value:g}"})  # fmt: skip
    return out


def unit_checks(rows: list[TepRow]) -> list[dict]:
    """UNIT_CONSISTENT: the printed unit of a parameter row must be the catalog unit (F0101 p9 prints the
    building volume in «кв. м.»: a real document error)."""
    from inspector_common.params import get_param

    out: list[dict] = []
    for i, r in enumerate(rows):
        if not r.param_code or not r.unit:
            continue
        try:
            expected = norm_unit(get_param(r.param_code).unit)
        except Exception:
            continue
        got = norm_unit(r.unit)
        if not expected or not got or expected in ("эт.",):
            continue
        out.append({"kind": "UNIT_CONSISTENT", "passed": got == expected, "expected": expected, "actual": r.unit,
                    "rows": [i + 1], "detail": f"«{r.indicator}» ({r.param_code}): единица «{r.unit}», по каталогу «{expected}»"})  # fmt: skip
    return out


def _new_row(cells: dict[str, str]) -> bool:
    return bool(_ROWNO.match(squash(cells.get("_row_no", "")))) or bool(first_number(cells.get("value", "")))


def parse_page(page: PageData) -> list[LogicalTep]:
    """Every ТЭП table on the page. A table counts as ТЭП only when its caption says so or its header has
    both a unit column and a value column (so that ordinary «Наименование» tables are not taken)."""
    out = []
    for t in find_tables(page, SPEC, new_row=_new_row):
        keys = set(t.keys)
        caption_ok = bool(t.caption and re.search(SPEC.caption or "", fold(t.caption)))
        near_caption = _caption_above(page, t)
        if not (caption_ok or near_caption or {"unit", "value"} <= keys):
            continue
        if "area" in keys or "room_no" in keys:
            continue
        le = LogicalTep([t], caption=t.caption if caption_ok else (near_caption or t.caption))
        le.rows = classify([t])
        if not any(r.kind in ("DATA", "SUBZONE") and (r.value is not None or r.value_raw) for r in le.rows):
            continue
        le.checks = checks(le.rows) + unit_checks(le.rows)
        out.append(le)
    return out


def _caption_above(page: PageData, t: RawTable) -> str | None:
    """The ТЭП caption is often a numbered heading well above the table («2.5. Технико-экономические …»)."""
    from inspector_tables.text import group_lines

    lines = group_lines([w for w in page.words if w.cy < t.box.y0 and t.box.y0 - w.cy < 260])
    for ln in reversed(lines):
        if re.search(SPEC.caption or "", fold(ln.text)):
            return ln.text
    return None
