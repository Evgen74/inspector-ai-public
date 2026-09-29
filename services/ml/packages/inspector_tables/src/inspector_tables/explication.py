"""EXPLICATION: «Экспликация помещений» with row kinds and Σ self-checks (96 §6, 97 §1.5).

Row kinds (TableRowKind): SECTION_HEADER (a full-width group title «Группа начальных классов»), DATA (a
room), SUBZONE (the «в том числе» children of a room: counted inside the parent, never as rooms), TOTAL
(«ИТОГО…»), SUBTOTAL (an unlabeled sum row). Side-by-side tables with the same caption and header top are
one logical table: groups continue across them (F0201 p18 has four).

Σ checks per group (rows between totals): the sum of DATA areas must equal the printed total. When it
does not, but it does once the sub-zones are added, the document counted a «в том числе» area twice:
SUBZONE_DOUBLE_COUNT (a real document error, 97 §1.5, a SUSPICION for AG-04, never silent data). A final
TOTAL after the last group total is the grand total and is checked against Σ of all rooms.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from inspector_tables.grid import ColumnSpec, RawRow, RawTable, TableSpec, find_tables
from inspector_tables.pagesource import PageData
from inspector_tables.text import (
    cyrillic_code,
    fold,
    group_lines,
    lines_text,
    number_value,
    parse_number,
    resplit_glued,
    squash,
)

SPEC = TableSpec(
    table_type="EXPLICATION",
    anchor=r"^наименовани",
    columns=(
        ColumnSpec("room_no", (r"^(номер|ном|№|n|поз|пом n|пом №)", r"^n п п$")),
        ColumnSpec("name", (r"наименовани",)),
        ColumnSpec("area", (r"площад", r"(^|\s)м2$", r"м²", r"^кв м$")),
        ColumnSpec("category", (r"^кат", r"категори", r"класс функц")),
        ColumnSpec("floor", (r"^этаж",)),
        ColumnSpec("note", (r"примечан",)),
    ),
    required=frozenset({"name", "area"}),
    key_column="name",
    caption=r"экспликаци",
    content_keys=(("area", "fraction"), ("room_no", "room")),
)

_TOTAL = re.compile(r"^(итого|всего|итог)\b", re.I)
_SUBZONE_PARENT = re.compile(r"(в\s+том\s+числе|в\s+т\.\s*ч\.?)\s*:?\s*$", re.I)
_ROOM_NO = re.compile(r"^(?:[0-9]{1,4}(?:[.\-/][0-9]{1,4}){0,2}[а-яa-z]?|[А-ЯA-Z]?[0-9]{1,4}[а-яa-z]?)$")
_CATEGORY = re.compile(r"^(А|Б|В[1-4]?|Г[1-4]?|Д|Ф[1-5](?:\.\d)?)$")
PARSER_VERSION = "explication-1"


def norm_room_no(raw: str) -> str | None:
    s = squash(raw).replace(" ", "")
    if not s:
        return None
    s = re.sub(r"(?<=\d)([a-zA-Z])$", lambda m: cyrillic_code(m.group(1)), s)
    return s


def norm_category(raw: str) -> str | None:
    """Fire-hazard / functional category («В4», «Д», «Ф4.1»); None when the cell holds something else."""
    s = squash(raw).replace(" ", "")
    if not s:
        return None
    c = cyrillic_code(s.upper())
    return c if _CATEGORY.match(c) else None


def area_tolerance(n_rows: int) -> float:
    """Σ of n values rounded to 0.1: sd of one rounding error is 0.029 → 2 sd plus one last digit."""
    return 0.051 + 2 * 0.0289 * math.sqrt(max(n_rows, 1))


@dataclass(slots=True)
class ExplRow:
    kind: str
    room_no: str | None
    room_raw: str
    name: str
    area: float | None
    area_raw: str
    category: str | None
    category_raw: str
    raw: RawRow
    table_index: int
    page_no: int
    parent: int | None = None  # index into the logical row list
    section: str | None = None


@dataclass(slots=True)
class LogicalExplication:
    parts: list[RawTable]
    rows: list[ExplRow] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    caption: str | None = None


def _is_blank(s: str) -> bool:
    return not squash(s)


def _split_band(r: RawRow, t: RawTable) -> list[tuple[str, str, float | None, str]] | None:
    """A row without a room number that stacks a sum and a group title in one band (Новослободская: the
    group Σ «850,5» and the next title «МОП» share a merged cell) → [(kind, text, area, area_raw), …]."""
    if not r.merged and squash(r.text("room_no")):
        return None
    lines = group_lines(r.all_words)
    if len(lines) < 2:
        return None
    area_col = next((c for c in t.columns if c.key == "area"), None)
    numeric = [ln for ln in lines if parse_number(ln.text) is not None]
    textual = [ln for ln in lines if parse_number(ln.text) is None]
    if not numeric:
        return None
    if textual:
        # the sum must sit wholly above or below the title (a two-line name with its area in between is a room)
        t_top, t_bot = min(ln.y0 for ln in textual), max(ln.y1 for ln in textual)
        if any(not (ln.y1 <= t_top + 0.5 or ln.y0 >= t_bot - 0.5) for ln in numeric):
            return None
    out: list[tuple[str, str, float | None, str]] = []
    for ln in lines:
        txt = ln.text
        num = parse_number(txt)
        in_area = area_col is not None and area_col.x0 - 2 <= (ln.x0 + ln.x1) / 2 <= area_col.x1 + 2
        if num is not None and (in_area or area_col is None):
            out.append(("SUBTOTAL", "", num, txt))
        elif _TOTAL.match(txt):
            m = re.search(r"([\d\s]+[.,]\d+)\s*$", txt)
            out.append(
                (
                    "TOTAL",
                    txt[: m.start()].strip() if m else txt,
                    parse_number(m.group(1)) if m else None,
                    m.group(1).strip() if m else "",
                )
            )
        elif out and out[-1][0] == "SECTION_HEADER":
            out[-1] = ("SECTION_HEADER", squash(out[-1][1] + " " + txt), None, "")
        else:
            out.append(("SECTION_HEADER", txt, None, ""))
    if not any(k == "SUBTOTAL" for k, *_ in out):
        return None
    return out


def classify_rows(tables: list[RawTable]) -> list[ExplRow]:
    rows: list[ExplRow] = []
    section: str | None = None
    for ti, t in enumerate(tables):
        for r in t.rows:
            room_raw, name, area_raw, cat_raw = (
                r.text("room_no"),
                r.text("name"),
                r.text("area"),
                r.text("category"),
            )
            area = parse_number(area_raw)
            texts = [room_raw, name, area_raw, cat_raw]
            if all(_is_blank(x) for x in texts) and not r.merged_text:
                continue
            split = _split_band(r, t)
            if split:
                for kind, text, value, raw in split:
                    if kind == "SECTION_HEADER":
                        section = text
                    rows.append(ExplRow(kind, None, "", text, value, raw, None, "", r, ti, t.page_no))
                    if kind != "SECTION_HEADER":
                        rows[-1].section = section
                continue
            name = resplit_glued(squash(name))
            full = squash(" ".join(x for x in (r.merged_text or name,) if x))
            if r.merged and parse_number(full) is not None:
                kind = "SUBTOTAL"
                area, area_raw, name = parse_number(full), full, ""
            elif _TOTAL.match(squash(name)) or (r.merged and _TOTAL.match(full)):
                kind = "TOTAL"
                if area is None and r.merged:
                    m = re.search(r"([\d\s]+[.,]\d+)\s*$", full)
                    area = parse_number(m.group(1)) if m else None
                    area_raw = m.group(1).strip() if m else area_raw
            elif (
                r.merged
                or (area is None and _is_blank(room_raw) and _is_blank(cat_raw) and not _is_blank(name))
                or (area is None and _is_blank(room_raw) and not _is_blank(name) and not _is_blank(area_raw))
            ):
                kind = "SECTION_HEADER"
                section = squash(r.merged_text or lines_text(r.all_words))
                name = section
                area_raw = cat_raw = ""
            elif area is not None and _is_blank(name) and _is_blank(room_raw):
                kind = "SUBTOTAL"
            else:
                kind = "DATA"
            rows.append(
                ExplRow(
                    kind,
                    norm_room_no(room_raw) if kind != "SECTION_HEADER" else None,
                    room_raw,
                    squash(name),
                    area,
                    squash(area_raw),
                    norm_category(cat_raw),
                    squash(cat_raw),
                    r,
                    ti,
                    t.page_no,
                )
            )
            if kind != "SECTION_HEADER":
                rows[-1].section = section
    _mark_subzones(rows)
    _mark_grand_totals(rows)
    return rows


def _mark_grand_totals(rows: list[ExplRow]) -> None:
    """An unlabeled sum right after another sum closes nothing new: it is the grand total."""
    prev_sum = False
    for r in rows:
        if r.kind in ("SUBTOTAL", "TOTAL"):
            if prev_sum and r.kind == "SUBTOTAL":
                r.kind = "TOTAL"
            prev_sum = True
        elif r.kind in ("DATA", "SUBZONE"):
            prev_sum = False


def _digits(room: str | None) -> int:
    return len(re.match(r"\d*", room or "").group(0))


def _mark_subzones(rows: list[ExplRow]) -> None:
    """Rows after a «…, в том числе:» room are its sub-zones: the first one always, the next ones while they
    carry no room number of their own (or a number shorter than the parent's, e.g. «10» under «130»)."""
    i = 0
    while i < len(rows):
        r = rows[i]
        if r.kind == "DATA" and _SUBZONE_PARENT.search(r.name):
            j = i + 1
            first = True
            while j < len(rows) and rows[j].kind == "DATA" and rows[j].area is not None:
                c = rows[j]
                shorter = r.room_no and c.room_no and _digits(c.room_no) < _digits(r.room_no)
                lettered = bool(
                    r.room_no and c.room_no and re.fullmatch(re.escape(r.room_no) + r"[а-яa-z]", c.room_no)
                )
                if first or not c.room_no or shorter or lettered:
                    c.kind = "SUBZONE"
                    c.parent = i
                    first = False
                    j += 1
                else:
                    break
            i = j
        else:
            i += 1


def sum_checks(rows: list[ExplRow]) -> list[dict]:
    checks: list[dict] = []
    group: list[int] = []
    closed_totals: list[tuple[int, float]] = []
    all_rooms: list[int] = []
    for idx, r in enumerate(rows):
        if r.kind in ("DATA", "SUBZONE"):
            group.append(idx)
            if r.kind == "DATA":
                all_rooms.append(idx)
            continue
        if r.kind not in ("TOTAL", "SUBTOTAL") or r.area is None:
            continue
        data = [i for i in group if rows[i].kind == "DATA" and rows[i].area is not None]
        subs = [i for i in group if rows[i].kind == "SUBZONE" and rows[i].area is not None]
        if not data:
            if closed_totals and r.kind == "TOTAL":
                checks.append(_grand_check(rows, idx, closed_totals, all_rooms))
            continue
        s = round(sum(rows[i].area for i in data), 2)  # type: ignore[misc]
        tol = area_tolerance(len(data))
        total = float(r.area)
        if abs(s - total) <= tol:
            checks.append({"kind": "SUM_MATCHES_TOTAL", "passed": True, "expected": number_value(s),
                           "actual": number_value(total), "rows": _rownos(rows, [*data, idx]),
                           "detail": f"Σ {len(data)} помещений = {_fmt(s)} м², итог {_fmt(total)} м²."})  # fmt: skip
        else:
            sub_sum = round(sum(rows[i].area for i in subs), 2)  # type: ignore[misc]
            if subs and abs(s + sub_sum - total) <= tol:
                parents = sorted({rows[i].parent for i in subs if rows[i].parent is not None})
                names = "; ".join(f"«{rows[i].name}» ({_fmt(rows[i].area)} м²)" for i in subs)
                checks.append({"kind": "SUBZONE_DOUBLE_COUNT", "passed": False, "expected": number_value(s),
                               "actual": number_value(total), "rows": _rownos(rows, [*parents, *subs, idx]),
                               "detail": f"Итог {_fmt(total)} м² = Σ помещений {_fmt(s)} м² + подзона «в том числе» "
                                         f"{_fmt(sub_sum)} м²: подзона учтена дважды. {names}"})  # fmt: skip
            else:
                checks.append({"kind": "SUM_MATCHES_TOTAL", "passed": False, "expected": number_value(s),
                               "actual": number_value(total), "rows": _rownos(rows, [*data, idx]),
                               "detail": f"Σ {len(data)} помещений = {_fmt(s)} м², в таблице итог {_fmt(total)} м² "
                                         f"(расхождение {_fmt(round(total - s, 2))} м²)."})  # fmt: skip
        closed_totals.append((idx, total))
        group = []
    return checks


def _grand_check(rows: list[ExplRow], idx: int, closed: list[tuple[int, float]], rooms: list[int]) -> dict:
    total = float(rows[idx].area)  # type: ignore[arg-type]
    s_rooms = round(sum(rows[i].area for i in rooms if rows[i].area is not None), 2)  # type: ignore[misc]
    s_totals = round(sum(t for _, t in closed), 2)
    tol = area_tolerance(len(rooms))
    # the grand total is consistent when it equals Σ of the printed group totals (the chain of totals) or Σ of
    # the rooms; a group-level double count is reported by its own group check
    by_totals = abs(s_totals - total) <= tol
    by_rooms = abs(s_rooms - total) <= tol
    expected = s_totals if by_totals and not by_rooms else s_rooms
    detail = (f"Общий итог {_fmt(total)} м²; Σ групповых итогов {_fmt(s_totals)} м²; "
              f"Σ всех помещений (без подзон) {_fmt(s_rooms)} м².")  # fmt: skip
    return {"kind": "SUM_MATCHES_TOTAL", "passed": by_totals or by_rooms, "expected": number_value(expected),
            "actual": number_value(total), "rows": _rownos(rows, [i for i, _ in closed] + [idx]), "detail": detail}  # fmt: skip


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    return (
        f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        if abs(v - round(v, 1)) > 1e-9
        else f"{v:.1f}".replace(".", ",")
    )


def _rownos(rows: list[ExplRow], idxs: list[int]) -> list[int]:
    return sorted({i + 1 for i in idxs})


# ── page-level driver ─────────────────────────────────────────────────────────────────────────────


def _explication_new_row(cells: dict[str, str]) -> bool:
    room = squash(cells.get("room_no", ""))
    area = parse_number(cells.get("area"))
    return (
        bool(room and _ROOM_NO.match(room.replace(" ", "")))
        or area is not None
        or bool(_TOTAL.match(squash(cells.get("name", ""))))
    )


def join_continuations(tables: list[RawTable]) -> list[list[RawTable]]:
    """Group the parts of one explication laid out left to right on a sheet. With the same (non-empty)
    caption, a part to the right continues the previous one even when it starts lower (F0201 p17) or sits a
    little apart (F0129 p27); without a caption the header tops must also line up."""
    groups: list[list[RawTable]] = []
    for t in sorted(tables, key=lambda t: (t.page_no, t.box.x0, t.header_box.y0)):
        if groups:
            prev = groups[-1][-1]
            width = max(prev.box.x1 - prev.box.x0, 100)
            gap = t.box.x0 - prev.box.x1
            adjacent = (
                prev.page_no == t.page_no and -2 <= gap <= max(40.0, 0.15 * width) and prev.keys == t.keys
            )
            same_caption = bool(t.caption and prev.caption and fold(prev.caption) == fold(t.caption))
            same_band = abs(prev.header_box.y0 - t.header_box.y0) <= 0.02 * max(
                prev.box.y1 - prev.box.y0, 200
            )
            if adjacent and (same_caption or (t.caption is None and same_band)):
                groups[-1].append(t)
                continue
        groups.append([t])
    return groups


def parse_page(page: PageData) -> list[LogicalExplication]:
    raw = find_tables(page, SPEC, new_row=_explication_new_row)
    out = []
    for parts in join_continuations(raw):
        le = LogicalExplication(parts, caption=parts[0].caption)
        le.rows = classify_rows(parts)
        if not any(r.kind in ("DATA", "SUBZONE") for r in le.rows):
            continue
        le.checks = sum_checks(le.rows)
        out.append(le)
    return out
