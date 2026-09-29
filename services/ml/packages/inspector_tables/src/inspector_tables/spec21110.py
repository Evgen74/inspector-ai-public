"""SPEC_21110: equipment specification by ГОСТ 21.110 («Спецификация оборудования, изделий и материалов»).

Columns: Позиция | Наименование и техническая характеристика | Тип, марка, обозначение документа | Код
оборудования | Завод-изготовитель (Поставщик) | Единица измерения | Количество | Масса единицы, кг | Примечание.

Every printed line of the form is its own ruled row, so one item spans several rows: a row that carries a
position, a unit or a quantity starts an item; a row with only name/type text continues the previous item.
Centered name-only rows («ОБОРУДОВАНИЕ», «Общеобменная вентиляция») are section titles. The column-number
row («1 2 3 … 9») under the header is skipped. The same form repeats on every sheet of the section: the
parser runs per page and the batch joins consecutive pages (CONTINUATION_JOINED).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.grid import ColumnSpec, RawRow, RawTable, TableSpec, find_tables
from inspector_tables.pagesource import PageData
from inspector_tables.text import fold, join_lines, parse_number, resplit_glued, squash

SPEC = TableSpec(
    table_type="SPEC_21110",
    anchor=r"^наименовани",
    columns=(
        ColumnSpec("position", (r"^поз", r"^позиция", r"^марка поз")),
        ColumnSpec("name", (r"^наименование и техническ", r"^наименование")),
        ColumnSpec("type_mark", (r"^тип", r"марка", r"обозначение документа", r"опросного")),
        ColumnSpec("code", (r"^код",)),
        ColumnSpec("manufacturer", (r"завод", r"изготовител", r"поставщик", r"производител")),
        ColumnSpec("unit", (r"^ед", r"единиц")),
        ColumnSpec("quantity", (r"^кол", r"количеств")),
        ColumnSpec("mass", (r"^масса",)),
        ColumnSpec("note", (r"примечан",)),
    ),
    required=frozenset({"name", "quantity"}),
    key_column="name",
    caption=r"спецификаци",
)
PARSER_VERSION = "spec21110-1"
KEYS = ("position", "name", "type_mark", "code", "manufacturer", "unit", "quantity", "mass", "note")


@dataclass(slots=True)
class SpecItem:
    kind: str
    cells: dict[str, str]
    raws: list[RawRow]
    page_no: int
    section: str | None = None

    @property
    def quantity(self) -> float | None:
        return parse_number(self.cells.get("quantity"))


@dataclass(slots=True)
class LogicalSpec:
    parts: list[RawTable]
    items: list[SpecItem] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    caption: str | None = None


def _is_number_row(cells: dict[str, str]) -> bool:
    vals = [squash(v) for v in cells.values() if squash(v)]
    return len(vals) >= 4 and all(re.fullmatch(r"\d{1,2}", v) for v in vals)


def _centered(r: RawRow, t: RawTable) -> bool:
    col = next((c for c in t.columns if c.key == "name"), None)
    cell = r.cells.get("name")
    if col is None or cell is None or cell.box is None:
        return False
    width = col.x1 - col.x0
    left_gap = cell.box.x0 - col.x0
    center_off = abs((cell.box.x0 + cell.box.x1) / 2 - (col.x0 + col.x1) / 2)
    return left_gap > 0.12 * width and center_off < 0.12 * width


def build_items(parts: list[RawTable]) -> list[SpecItem]:
    items: list[SpecItem] = []
    section: str | None = None
    for t in parts:
        for r in t.rows:
            cells = {k: squash(r.text(k)) for k in KEYS}
            if not any(cells.values()) or _is_number_row(cells):
                continue
            cells["name"] = resplit_glued(cells["name"])
            starts = bool(cells["position"] or cells["unit"] or cells["quantity"])
            only_name = cells["name"] and not any(cells[k] for k in KEYS if k != "name")
            if only_name and _centered(r, t):
                section = cells["name"]
                items.append(SpecItem("SECTION_HEADER", {"name": cells["name"]}, [r], t.page_no))
                continue
            prev = items[-1] if items and items[-1].kind == "DATA" else None
            pending = prev is not None and not (prev.cells.get("quantity") or prev.cells.get("unit"))
            lower = cells["name"][:1].islower() or cells["name"][:1] in '(«"-'
            if (
                prev is not None
                and not cells["position"]
                and (
                    (not starts and (lower or pending))
                    or (starts and pending and (lower or not prev.cells.get("position")))
                )
            ):
                # a lowercase line continues the item; a quantity line completes a pending (name-only) item
                for k, v in cells.items():
                    if v:
                        prev.cells[k] = join_lines(prev.cells[k], v) if prev.cells.get(k) else v
                prev.raws.append(r)
            else:
                items.append(SpecItem("DATA", dict(cells), [r], t.page_no, section))
    return items


def parse_page(page: PageData) -> list[LogicalSpec]:
    out = []
    for t in find_tables(page, SPEC, allow_aligned=False):
        keys = set(t.keys)
        if not ({"type_mark", "unit"} & keys) or "area" in keys:
            continue
        ls = LogicalSpec([t], caption=t.caption)
        ls.items = build_items([t])
        data = [i for i in ls.items if i.kind == "DATA"]
        if not data:
            continue
        with_qty = sum(1 for i in data if i.cells.get("quantity"))
        ls.checks.append({"kind": "HEADER_MATCHED", "passed": True, "expected": None, "actual": ", ".join(sorted(keys)),
                          "detail": f"Позиций: {len(data)}, с количеством: {with_qty}"})  # fmt: skip
        out.append(ls)
    return out


def item_text(it: SpecItem) -> str:
    return " ".join(v for k in ("position", "name", "type_mark", "manufacturer") if (v := it.cells.get(k)))


def find_items(items: list[SpecItem], pattern: str) -> list[SpecItem]:
    rx = re.compile(pattern)
    return [it for it in items if it.kind == "DATA" and rx.search(fold(item_text(it)))]
