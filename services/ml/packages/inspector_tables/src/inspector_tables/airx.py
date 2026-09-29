"""«Таблица воздухообменов помещений»: the PD ventilation system list per room (IOS4-078/079 evidence).

The PD ОВ volume lists, for every room, its supply system, exhaust system, compensation system for local
exhausts and the local-exhaust (М.О.) systems (F0171 p79–81: «140 … П6 | ВЕ | … | В2.7, В2.8, В2.9»). On
Тюменская the table is a raster inset inside a vector A1 sheet, so it is read from OCR tokens with raster
rulings. There is no contract TableType for it yet (requested from AG-00 as AIR_EXCHANGE); its rows are
emitted as element–room facts (``pd.room_systems``) that the per-room comparators use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.grid import ColumnSpec, RawTable, TableSpec, find_tables
from inspector_tables.pagesource import PageData
from inspector_tables.text import Box, squash

SPEC = TableSpec(
    table_type="AIR_EXCHANGE",
    anchor=r"^наименование$",
    columns=(
        ColumnSpec("room_no", (r"^номер",)),
        ColumnSpec("name", (r"^наименование( помещ\w*)?$",)),
        ColumnSpec("category", (r"^кат",)),
        ColumnSpec("temp", (r"темпер", r"^внут")),
        ColumnSpec("area", (r"^пло", r"площад")),
        ColumnSpec("height", (r"^высо",)),
        ColumnSpec("volume", (r"^об[ъь]",)),
        ColumnSpec("sys_supply", (r"наимен\w* приточн",)),
        ColumnSpec("sys_exhaust", (r"наимен\w* вытяжн\w* систем\w*$",)),
        ColumnSpec("sys_comp", (r"наимен\w* систем\w* компенсац", r"компенсац\w* м ?о")),
        ColumnSpec("sys_mo", (r"наимен\w* вытяжн\w* систем\w* от м ?о", r"систем\w* от м ?о")),
        ColumnSpec("note", (r"примечан",)),
    ),
    required=frozenset({"room_no", "name"}),
    key_column="name",
    caption=r"воздухообмен|теплоизбыт",
    max_header_pt=260.0,
)
PARSER_VERSION = "airx-1"
SYSTEM_KEYS = ("sys_supply", "sys_exhaust", "sys_comp", "sys_mo")
_LAT2CYR_TAG = str.maketrans({"B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О", "P": "Р", "C": "С",
                              "T": "Т", "X": "Х", "N": "П", "Π": "П", "П": "П", "b": "В", "e": "Е"})  # fmt: skip
_TAG = re.compile(r"^(?:[ПВКДА][ЕДП]?\d{1,2}(?:\.\d{1,2})?|[ПВ]Е)$")


def norm_tag(tok: str) -> str | None:
    """«B2.7» → «В2.7», «N6» → «П6», «ПЗ» → «П3», «BE» → «ВЕ»; None when the token is not a system tag."""
    t = squash(tok).strip(",;.").upper().translate(_LAT2CYR_TAG).replace(",", ".")
    m = re.match(r"^([ПВКДА][ЕДП]?)(.*)$", t)
    if m and m.group(2):
        rest = m.group(2).translate(str.maketrans({"З": "3", "О": "0", "O": "0", "Б": "6"}))
        t = m.group(1) + rest
    return t if _TAG.match(t) else None


def split_tags(text: str) -> list[str]:
    """«В2.7, В2.8, В2.9» / «В2.7,8,9» / «В2.4-В2.6» → [В2.7, В2.8, В2.9]."""
    out: list[str] = []
    s = squash(text)
    if not s or s in ("-", "—"):
        return out
    base = None
    for part in re.split(r"[;,\s]+", s):
        if not part:
            continue
        rng = re.match(r"^(.+?)[-–](.+)$", part)
        if rng and norm_tag(rng.group(1)):
            a = norm_tag(rng.group(1))
            b = norm_tag(rng.group(2)) or (
                f"{a.rsplit('.', 1)[0]}.{rng.group(2)}" if a and "." in a and rng.group(2).isdigit() else None
            )
            if a and b and a.rsplit(".", 1)[0] == b.rsplit(".", 1)[0] and "." in a:
                prefix = a.rsplit(".", 1)[0]
                lo, hi = int(a.rsplit(".", 1)[1]), int(b.rsplit(".", 1)[1])
                if 0 <= hi - lo <= 12:
                    out.extend(f"{prefix}.{i}" for i in range(lo, hi + 1))
                    base = prefix
                    continue
        tag = norm_tag(part)
        if tag:
            out.append(tag)
            base = tag.rsplit(".", 1)[0] if "." in tag else None
        elif base and re.fullmatch(r"\d{1,2}", part):
            out.append(f"{base}.{part}")
    return list(dict.fromkeys(out))


@dataclass(slots=True)
class RoomSystems:
    room_no: str
    name: str
    systems: dict[str, list[str]]
    page_no: int
    box: Box | None
    raw: dict[str, str] = field(default_factory=dict)


def parse_page(page: PageData) -> tuple[list[RawTable], list[RoomSystems]]:
    tables = [t for t in find_tables(page, SPEC, allow_aligned=False) if set(SYSTEM_KEYS) & set(t.keys)]
    rooms: list[RoomSystems] = []
    for t in tables:
        for r in t.rows:
            room = squash(r.text("room_no")).replace(" ", "")
            if not re.fullmatch(r"\d{1,4}(?:\.\d{1,2})?[а-яa-z]?", room or ""):
                continue
            systems = {k: split_tags(r.text(k)) for k in SYSTEM_KEYS if k in r.cells}
            rooms.append(RoomSystems(room, squash(r.text("name")), systems, t.page_no, r.box,
                                     {k: squash(r.text(k)) for k in SYSTEM_KEYS if k in r.cells}))  # fmt: skip
    return tables, rooms
