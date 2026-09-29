"""Room labels of one drawing page: plans, schematics and explications (96 R-15, 95 R8).

Three printed forms carry a room number on the train drawings:

- **plan label** — the number inside a small circle (F0201 p18: «142» in a ⌀20 pt circle on ``АР_мебель``);
- **schematic label** — the first word(s) of a room caption on a principal scheme: «142 Астрономии и физики»,
  «267, 270» (one cell, two rooms), a lone «012» next to «002 Коридор»;
- **explication row** — the number column of «Экспликация помещений» (name and area in the same row).

A number is accepted only in one of these contexts, so flows («L 140»), sizes, levels and «на 600 мест» are
never rooms. Lone numbers (no circle, no name) are accepted when they share the font, size and layer of the
page's confirmed labels. Tokens are kept exactly as printed («012», «012.1»).
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from inspector_layout.cad.geometry import Circle
from inspector_layout.cad.layers import layer_classes
from inspector_layout.rooms.grammar import ROOM_RE, floor_from_title, fold, ocr_diameter, parse_room_label
from inspector_layout.rooms.tokens import PageText, Tok

PT_PER_MM = 72.0 / 25.4
STAMP_W_MM, STAMP_H_MM = 190.0, 60.0  # ГОСТ Р 21.101 main stamp 185×55 mm + frame margin


@dataclass(slots=True)
class RoomLabel:
    rooms: tuple[str, ...]
    token_ids: list[int]
    box: tuple[float, float, float, float]  # displayed pt (the number tokens)
    source: str  # contract RoomSource
    confidence: float
    text_source: str
    name: str | None = None
    area_m2: float | None = None
    circle: Circle | None = None
    layer: str | None = None
    style: tuple | None = None
    seed: tuple[float, float] | None = None  # region seed (centre of the circle or of the number)

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2


@dataclass(slots=True)
class PageLabels:
    plan_labels: list[RoomLabel] = field(default_factory=list)  # PLAN_LABEL / SCHEMATIC_LABEL (have zones)
    explication: list[RoomLabel] = field(default_factory=list)  # EXPLICATION_TABLE rows
    kind: str = "UNKNOWN"  # PLAN / SCHEMATIC / UNKNOWN
    floor: str | None = None
    explication_boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    title: str | None = None

    @property
    def all(self) -> list[RoomLabel]:
        return self.plan_labels + self.explication

    def rooms(self) -> set[str]:
        return {r for lab in self.plan_labels for r in lab.rooms}


def _clean(text: str) -> str:
    return text.strip().rstrip(",;")


def _room_candidate(t: Tok) -> bool:
    """A token that may print a room number: room grammar, trusted text or a confident OCR read, and not a
    system mark (OCR «0200» is «Ø200»; numbers on duct or heating layers are sizes, flows, node numbers:
    «254» in a circle on «ОВ-Отопление-Схема» of the 3rd-floor plan F0202 p18 is not a room)."""
    text = _clean(t.text)
    if not ROOM_RE.match(text):
        return False
    if t.source.startswith("TEXT_LAYER"):
        return True
    if t.conf < 0.85 or ocr_diameter(text):
        return False
    return not (t.layer and layer_classes(t.layer) & {"DUCT", "AIRFLOW", "HEATING"})


def _style(t: Tok) -> tuple:
    size = round(t.size, 1) if t.size else round(t.text_h, 1)
    return (t.font or "", size, t.layer or "", t.source.startswith("TEXT_LAYER"))


def _style_match(a: tuple, b: tuple) -> bool:
    return a[0] == b[0] and a[2] == b[2] and a[3] == b[3] and abs(a[1] - b[1]) <= 0.15 * max(a[1], b[1], 1e-6)


def in_stamp(t: Tok | tuple, page_w: float, page_h: float) -> bool:
    """Inside the bottom-right main stamp window (only on sheets larger than A4)."""
    if page_w * page_h < 1.3 * 595 * 842:
        return False
    cx = (t.x0 + t.x1) / 2 if isinstance(t, Tok) else (t[0] + t[2]) / 2
    cy = (t.y0 + t.y1) / 2 if isinstance(t, Tok) else (t[1] + t[3]) / 2
    return cx > page_w - STAMP_W_MM * PT_PER_MM and cy > page_h - STAMP_H_MM * PT_PER_MM


def _enclosing_circle(t: Tok, circles_grid: dict, cell: float) -> Circle | None:
    best = None
    th = max(t.text_h, 1.0)
    half = max(t.w, t.h) / 2
    for gx in (int(t.cx // cell) - 1, int(t.cx // cell), int(t.cx // cell) + 1):
        for gy in (int(t.cy // cell) - 1, int(t.cy // cell), int(t.cy // cell) + 1):
            for c in circles_grid.get((gx, gy), ()):
                d = ((c.cx - t.cx) ** 2 + (c.cy - t.cy) ** 2) ** 0.5
                # four glyphs («331б», F0202 p18) may overflow the circle a little: 0.8, not 0.9 of the half-width
                fits = d <= 0.45 * c.r and 0.8 * half <= c.r <= 4.0 * th + half
                if fits and (best is None or c.r < best.r):
                    best = c
    return best


_AREA = re.compile(r"^\d{1,4}[.,]\d{1,2}$")
_QUANTITY_NAME = re.compile(r"^(?:мест[аo]?|мм|см|м[23²³]?|вт|квт|шт|кг|чел)(?![А-Яа-яЁё])", re.IGNORECASE)
_CAPTION = re.compile(r"экспликац", re.IGNORECASE)
_KIND_SCHEMATIC = re.compile(
    r"(?:принципиальн\w*\s+схем|схема\s+систем|аксонометр|схема\s+отоплен|схема\s+вентил)", re.IGNORECASE
)
_KIND_PLAN = re.compile(r"(?:^|\s)план\w*\s", re.IGNORECASE)


def page_kind_and_title(page: PageText) -> tuple[str, str | None, str | None]:
    """(kind, title line, floor) from the sheet texts: the biggest «План…»/«…схема…» line wins."""
    byid = page.by_id()
    best: tuple[float, str, str] | None = None
    for ln in page.lines:
        text = fold(ln.text)
        low = text.lower()
        kind = None
        if _KIND_SCHEMATIC.search(low):
            kind = "SCHEMATIC"
        elif _KIND_PLAN.search(" " + low + " ") or low.startswith("план"):
            kind = "PLAN"
        if kind is None:
            continue
        size = max((byid[i].text_h for i in ln.token_ids), default=0.0)
        if best is None or size > best[0]:
            best = (size, kind, ln.text)
    if best is None:
        return "UNKNOWN", None, None
    return best[1], best[2], floor_from_title(best[2])


def _explication_columns(page: PageText, cands: list[Tok], circled: set[int]) -> list[list[Tok]]:
    """Vertical runs of ≥ 4 room-like numbers with the same left edge: the number column of a table.

    Rows of an explication differ in height (two- and three-line names), so a run tolerates gaps up to
    8 text heights; columns are clustered by left edge with a tolerance, not by rounding (F0201 p18).
    """
    pts = sorted((t for t in cands if t.id not in circled and t.angle % 180 == 0), key=lambda t: t.x0)
    groups: list[list[Tok]] = []
    for t in pts:
        if groups and t.x0 - groups[-1][-1].x0 <= 0.6 * max(t.text_h, 1.0):
            groups[-1].append(t)
        else:
            groups.append([t])
    cols = []
    for toks in groups:
        if len(toks) < 4:
            continue
        toks.sort(key=lambda t: t.cy)
        run = [toks[0]]
        for t in toks[1:]:
            if t.cy - run[-1].cy <= 8.0 * max(t.text_h, 1.0):
                run.append(t)
            else:
                if len(run) >= 4:
                    cols.append(run)
                run = [t]
        if len(run) >= 4:
            cols.append(run)
    return cols


# First words of room names (ГОСТ Р 21.101 explications, СП 118/54 room types): a number with such a word
# printed under it is a room label, a number with any other text under it may be a dimension or a mark.
ROOM_NAME_WORDS = re.compile(
    r"^(?:кабинет|коридор|холл|вестибюль|тамбур|лестни|лифт|санузел|санузлы|с/у|туалет|уборн|душев|раздевал|"
    r"гардероб|кладов|помещ|комнат|зал|рекреац|лаборан|мастерск|венткамер|вентиляцион|электрощит|щитов|итп|"
    r"тепловой|насосн|водомерн|узел|пуи|кухн|прихож|жил|спальн|гостин|столов|буфет|пищеблок|цех|моечн|"
    r"медиц|процедур|учительск|библиотек|читальн|спортивн|актов|техническ|техпод|подполь|серверн|"
    r"пожаробезопасн|пожаро|зона|кладовая|инвентар|охран|диспетчер|вахт|терраса|балкон|лоджия|шахта)",
    re.IGNORECASE,
)


EXPLICATION_NAME_WORDS = re.compile(
    ROOM_NAME_WORDS.pattern[:-1]
    + r"|учебн|универсальн|форкамер|лаборатор|кабинет|архив|склад|офис|переговор|конференц|бытов|душ|"
    r"тренаж|хранил|мусор|электр|игров|медпункт|изолятор|бассейн|фойе|аудитор|класс|рекреац|сануз|"
    r"умывал|кладов|гардероб|раздат|загрузоч|разгрузоч|приём|прием|ожидан|кухонн|холодильн|морозильн)",
    re.IGNORECASE,
)


def _name_head(name: str) -> str:
    """The name without its leading quote, bracket or sub-zone dash: «-зона …» → «зона …»."""
    return name.lstrip('«"(-– ')


def _is_explication(rows: list[tuple[Tok, str | None, float | None]], has_caption: bool) -> bool:
    """A number column is an explication when its rows read as rooms: areas and room-type names.

    Captioned tables («Экспликация помещений») need half of the rows with an area or a room-type name; an
    uncaptioned column needs both (80 % areas and half room names). The «Характеристика отопительно-
    вентиляционных систем» tables (F0201 p15–16) list served rooms next to fan types («Канальный») and powers,
    and a specification caption can sit above a column of positions («Термометр», F0202 p21).
    """
    if len(rows) < 4:
        return False
    n = len(rows)
    with_area = sum(1 for _, _, a in rows if a is not None)
    room_named = sum(1 for _, name, _ in rows if name and EXPLICATION_NAME_WORDS.match(_name_head(name)))
    if has_caption:
        return with_area >= 0.5 * n or room_named >= 0.5 * n
    return with_area >= 0.8 * n and room_named >= 0.5 * n


LineGeom = tuple[float, float, float, float, str, int]  # x0, y0, x1, y1, text, angle


def line_geoms(page: PageText, byid: dict[int, Tok]) -> list[LineGeom]:
    """Boxes of the horizontal text lines of a page (computed once per page for :func:`_name_below`)."""
    out = []
    for ln in page.lines:
        toks = [byid[i] for i in ln.token_ids]
        if not toks or toks[0].angle % 180 != 0:
            continue
        out.append((min(t.x0 for t in toks), toks[0].y0, max(t.x1 for t in toks), max(t.y1 for t in toks),
                    ln.text.strip(), toks[0].angle))  # fmt: skip
    return out


_NAME_START = re.compile(r"^[«\"(]?(?:[-–]\s?)?[А-ЯЁа-яё]")  # «-зона для индивидуальных занятий» (331б)
_CONTINUATION_START = re.compile(r"^[(а-яё]")


def _name_below(geoms: list[LineGeom], toks: list[Tok], start: re.Pattern[str] = _NAME_START) -> str | None:
    """A room name printed on the line right under a number label (≤ 1.2 em below), aligned with it on the left
    edge, the right edge («012» over «Венткамера» on F0171 p88) or the centre; every line must match ``start``."""
    if toks[0].angle % 180 != 0:
        return None
    x0 = min(t.x0 for t in toks)
    x1 = max(t.x1 for t in toks)
    y1 = max(t.y1 for t in toks)
    h = max(t.text_h for t in toks)
    parts: list[str] = []
    for _ in range(3):  # up to three name lines («Раздевальная и» / «санузел для МГН»)
        best = None
        for lx0, ly0, lx1, ly1, text, angle in geoms:
            gap = ly0 - y1
            if not -0.2 * h <= gap <= 1.2 * h or angle != toks[0].angle:
                continue
            aligned = (
                abs(lx0 - x0) <= 0.6 * h
                or abs(lx1 - x1) <= 0.6 * h
                or abs((lx0 + lx1) / 2 - (x0 + x1) / 2) <= 0.6 * h
            )
            if aligned and start.match(text) and (best is None or gap < best[0]):
                best = (gap, text, ly1)
        if best is None:
            break
        parts.append(best[1])
        y1 = best[2]
    if not parts:
        return None
    name = " ".join(parts)
    return re.sub(r"-\s+(?=[а-яё])", "", name)  # «Пожаро- безопасная» → «Пожаробезопасная»


def _with_continuation(name: str, geoms: list[LineGeom], line_toks: list[Tok]) -> str:
    """«140 Физического» + «эксперимента» on the next line (F0171 p88). Only lines that continue a phrase
    (lower-case or «(» first) are taken, so the next room label or a note is never swallowed."""
    below = _name_below(geoms, line_toks, _CONTINUATION_START)
    return re.sub(r"-\s+(?=[а-яё])", "", f"{name} {below}") if below else name


def detect_labels(page: PageText, circles: list[Circle]) -> PageLabels:
    """Room labels of a page (see the module docstring)."""
    out = PageLabels()
    out.kind, out.title, out.floor = page_kind_and_title(page)
    W, H = page.frame.width, page.frame.height
    byid = page.by_id()
    cell = 40.0
    cgrid: dict[tuple[int, int], list[Circle]] = defaultdict(list)
    for c in circles:
        cgrid[(int(c.cx // cell), int(c.cy // cell))].append(c)

    cands = [t for t in page.tokens if _room_candidate(t)]
    circled: dict[int, Circle] = {}
    for t in cands:
        c = _enclosing_circle(t, cgrid, cell)
        if c is not None:
            circled[t.id] = c
    # room-label circles share one radius on a sheet; other circles (round duct sections, bubbles) do not
    radii = Counter(round(c.r, 1) for tid, c in circled.items() if byid[tid].source.startswith("TEXT_LAYER"))
    if sum(radii.values()) >= 5:
        r0 = radii.most_common(1)[0][0]
        circled = {tid: c for tid, c in circled.items() if abs(c.r - r0) <= 0.25 * r0}

    # 1. explication tables: number columns (+ the caption nearby)
    captions = [t for t in page.tokens if _CAPTION.search(fold(t.text)) and not in_stamp(t, W, H)]
    expl_ids: set[int] = set()
    for col in _explication_columns(page, cands, set(circled)):
        plain = sum(1 for t in col if re.match(r"^\d{3,4}[а-яё]?$", _clean(t.text)))
        if plain < 0.6 * len(col):
            continue  # a column of areas or totals («3793.1», «15.89»), not room numbers
        th = statistics.median(t.text_h for t in col)
        x0 = min(t.x0 for t in col)
        top = min(t.y0 for t in col)
        has_caption = any(abs(c.x0 - x0) < 120 * th and 0 <= top - c.cy < 60 * th for c in captions)
        conf = 0.95 if has_caption else 0.75
        right = x0 + 45 * th
        # the table ends where another number column starts to the right (side-by-side tables)
        rows = []
        for t in col:
            row = [
                o for o in page.tokens
                if o.id != t.id and abs(o.cy - t.cy) <= 0.45 * th and t.x1 < o.cx < right and o.angle == t.angle
            ]  # fmt: skip
            row.sort(key=lambda o: o.x0)
            name_parts, area = [], None
            for o in row:
                txt = o.text.strip()
                if area is None and _AREA.match(txt):
                    area = float(txt.replace(",", "."))
                    break
                if ROOM_RE.match(_clean(txt)) and not name_parts:
                    break  # the next table's number column
                if re.search(r"[А-ЯЁа-яё]", txt):
                    name_parts.append(txt)
            rows.append((t, " ".join(name_parts) or None, area))
        named = sum(1 for _, n, _ in rows if n)
        if named < max(2, len(rows) // 3):
            continue  # a column of numbers without names is not an explication
        # «160 мест, Крышный»: a number followed by a unit is a quantity, not a room («331а -зона …» is a room)
        rows = [(t, n, a) for t, n, a in rows if not (n and _QUANTITY_NAME.match(n))]
        if not _is_explication(rows, has_caption):
            continue  # «Характеристика систем»: served rooms next to fan types, powers, …
        for t, name, area in rows:
            expl_ids.add(t.id)
            lab = RoomLabel((_clean(t.text),), [t.id], t.box, "EXPLICATION_TABLE", conf, t.source, name, area,
                            layer=t.layer, style=_style(t))  # fmt: skip
            out.explication.append(lab)
        bx = (x0, top, right, max(t.y1 for t in col))
        out.explication_boxes.append(bx)

    # 2. plan / schematic labels
    geoms = line_geoms(page, byid)
    confirmed: list[RoomLabel] = []
    lone: list[tuple[tuple[str, ...], list[Tok]]] = []
    used: set[int] = set()
    for ln in page.lines:
        if not ln.token_ids:
            continue
        first = byid[ln.token_ids[0]]
        if first.id in expl_ids or (in_stamp(first, W, H) and first.id not in circled):
            continue
        parsed = parse_room_label(ln.text)
        if parsed is None:
            continue
        # tokens holding the numbers: the leading tokens of the line whose text is a room (list)
        num_toks: list[Tok] = []
        for i in ln.token_ids:
            tt = _clean(byid[i].text)
            parts = [p for p in re.split(r"\s*,\s*", tt) if p]
            if parts and all(ROOM_RE.match(p) for p in parts):
                num_toks.append(byid[i])
            else:
                break
        if not num_toks or any(t.id not in {c.id for c in cands} for t in num_toks):
            continue
        box = (min(t.x0 for t in num_toks), min(t.y0 for t in num_toks), max(t.x1 for t in num_toks),
               max(t.y1 for t in num_toks))  # fmt: skip
        circle = circled.get(num_toks[0].id)
        src = num_toks[0].source
        if circle is not None:
            lab = RoomLabel(parsed.rooms, [t.id for t in num_toks], box, "PLAN_LABEL", 0.98, src, parsed.name,
                            circle=circle, layer=num_toks[0].layer, style=_style(num_toks[0]),
                            seed=(circle.cx, circle.cy))  # fmt: skip
            confirmed.append(lab)
        elif parsed.name:
            source = "PLAN_LABEL" if out.kind == "PLAN" else "SCHEMATIC_LABEL"
            conf = 0.95 if src.startswith("TEXT_LAYER") else 0.85
            name = _with_continuation(parsed.name, geoms, [byid[i] for i in ln.token_ids])
            lab = RoomLabel(parsed.rooms, [t.id for t in num_toks], box, source, conf, src, name,
                            layer=num_toks[0].layer, style=_style(num_toks[0]))  # fmt: skip
            confirmed.append(lab)
        else:
            lone.append((parsed.rooms, num_toks))
            continue
        used.update(t.id for t in num_toks)

    # 3. lone numbers (or number lists «267, 270») that look like the confirmed labels of this page, or
    #    whose room name is printed on the next line («267, 270» / «Раздевальная и санузел для МГН»)
    styles = Counter(lab.style for lab in confirmed if lab.style)
    n_circled = sum(1 for lab in confirmed if lab.circle is not None)
    circled_sheet = n_circled >= 3 and n_circled >= 0.8 * len(confirmed)
    for rooms, toks in lone:
        below = _name_below(geoms, toks)
        if circled_sheet and not (below and ROOM_NAME_WORDS.match(_name_head(below))):
            continue  # on a sheet whose room numbers sit in circles, a bare number is a dimension or a mark
        if any(t.id in used for t in toks):
            continue
        t = toks[0]
        st = _style(t)
        support = sum(n for s_, n in styles.items() if _style_match(s_, st))
        name = below
        if name and not (out.kind == "SCHEMATIC" or ROOM_NAME_WORDS.match(_name_head(name))):
            name = None  # text under a bare number that is not a room name (dimensions, notes)
        if support < 3 and not name:
            continue
        source = (
            "SCHEMATIC_LABEL"
            if out.kind == "SCHEMATIC"
            else ("PLAN_LABEL" if out.kind == "PLAN" else "SCHEMATIC_LABEL")
        )
        box = (
            min(x.x0 for x in toks),
            min(x.y0 for x in toks),
            max(x.x1 for x in toks),
            max(x.y1 for x in toks),
        )
        conf = 0.85 if name else 0.8
        confirmed.append(
            RoomLabel(rooms, [x.id for x in toks], box, source, conf, t.source, name, layer=t.layer, style=st)
        )
        used.update(x.id for x in toks)

    # names and areas of plan labels from the explication of the same page
    expl = {lab.rooms[0]: lab for lab in out.explication}
    for lab in confirmed:
        if len(lab.rooms) == 1 and lab.rooms[0] in expl:
            e = expl[lab.rooms[0]]
            lab.name = lab.name or e.name
            lab.area_m2 = e.area_m2
        if lab.seed is None:
            lab.seed = (lab.cx, lab.cy)
    if out.kind == "UNKNOWN" and confirmed:
        out.kind = "PLAN" if sum(1 for lab in confirmed if lab.circle) >= 3 else "SCHEMATIC"
    out.plan_labels = confirmed
    if out.floor is None:
        for c in captions:
            ln = next((line for line in page.lines if c.id in line.token_ids), None)
            fl = floor_from_title(ln.text) if ln else None
            if fl:
                out.floor = fl
                break
    return out
