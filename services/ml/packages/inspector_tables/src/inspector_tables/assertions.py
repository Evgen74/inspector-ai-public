"""PD element–room assertions (97 §2.13, §3.3 «AG-02C PD element–room assertions + absence proof → AG-07»).

An assertion says «the PD provides element family F in rooms R» with its evidence. Four channels, in
decreasing strength:

* TEXT — a sentence of the explanatory note naming the element and a room list: «В помещениях … (пом. 267,
  270, 271, 272) предусмотрена система подогрева полов (теплые полы)» (F0171 p11);
* TABLE — the air-exchange table (``airx``): the systems serving each room («140 → В2.7, В2.8, В2.9»);
* LABEL — a drawing leader/legend line naming the element, with the room labels printed next to it
  («Регулятор для системы “теплый пол” Multibox C/RTL» by «267, 270 / 271, 272» on F0171 p99);
* SPEC — a specification item naming the element (no room; object-level, with quantity) (F0171 p136).

Element families, their anchor phrases and tag patterns come from AG-03's change map
(``packages/contracts/seed/change_matrix_map.json`` → ``element_families``); nothing is hard-coded here but
the phrase-to-regex stemming.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from inspector_tables.pagesource import PageData
from inspector_tables.text import Box, Word, fold, group_lines, segments, squash

ROOM_LIST = re.compile(
    r"(?<![а-я])пом(?:ещени[йяеюи]|ещ)?\.?\s*(?:№\s*)?"
    r"(?P<list>-?\d{2,4}(?:[.\-]\d{1,3})?[а-я]?(?:\s*(?:,|;|и)\s*(?:№\s*)?-?\d{2,4}(?:[.\-]\d{1,3})?[а-я]?)*)",
    re.I,
)
ROOM_TOKEN = re.compile(r"-?\d{2,4}(?:[.\-]\d{1,3})?[а-я]?")
LABEL_ROOM = re.compile(r"^\d{3,4}[а-я]?(?:\.\d{1,2})?,?$")
SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[А-ЯЁA-Z«\"(])")


@dataclass(frozen=True, slots=True)
class Family:
    code: str
    label_ru: str
    topic: str | None
    patterns: tuple[re.Pattern[str], ...]
    tag_patterns: tuple[re.Pattern[str], ...]


def _stem_regex(phrase: str) -> str:
    """«тёплый пол» → «тепл\\w*\\s+пол\\w*»: each word cut to its stem (≥ 3 letters) so inflections match."""
    words = fold(phrase).split()
    parts = []
    for w in words:
        stem = w if len(w) <= 4 else w[: max(4, len(w) - 2)]
        parts.append(re.escape(stem) + r"\w*")
    return r"(?<!\w)" + r"\s+".join(parts)


@lru_cache(maxsize=1)
def families() -> tuple[Family, ...]:
    from inspector_common.params import load_change_map

    out = []
    for f in load_change_map().document["element_families"]:
        pats = tuple(re.compile(_stem_regex(a)) for a in f.get("anchors", []) if fold(a))
        tags = tuple(re.compile(t) for t in f.get("tag_patterns", []))
        out.append(Family(f["family"], f.get("label_ru", f["family"]), f.get("topic"), pats, tags))
    return tuple(out)


def family(code: str) -> Family:
    for f in families():
        if f.code == code:
            return f
    raise KeyError(code)


def match_families(text: str, only: tuple[str, ...] | None = None) -> list[tuple[Family, str]]:
    f = fold(text)
    out = []
    for fam in families():
        if only and fam.code not in only:
            continue
        for p in fam.patterns:
            m = p.search(f)
            if m:
                out.append((fam, m.group(0)))
                break
    return out


@dataclass(slots=True)
class ElementAssertion:
    family: str
    rooms: list[str]
    channel: str  # TEXT | TABLE | LABEL | SPEC
    file_id: str
    page_no: int
    text: str
    anchor: str
    box: Box | None
    confidence: float
    quantity: float | None = None
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def rooms_in(text: str) -> list[str]:
    out: list[str] = []
    for m in ROOM_LIST.finditer(text):
        out.extend(ROOM_TOKEN.findall(m.group("list")))
    return list(dict.fromkeys(out))


def _words_box(words: list[Word]) -> Box | None:
    return Box.of_words(words)


def text_assertions(page: PageData, only: tuple[str, ...] | None = None) -> list[ElementAssertion]:
    """Sentences (possibly wrapped over lines) that name an element family and a room list."""
    lines = group_lines(page.words)
    if not lines:
        return []
    # the page as one stream with a word index, so a sentence maps back to its boxes
    stream: list[tuple[str, Word]] = []
    for ln in lines:
        for w in ln.words:
            stream.append((w.text, w))
    text = " ".join(t for t, _ in stream)
    offsets = []
    pos = 0
    for t, _ in stream:
        offsets.append(pos)
        pos += len(t) + 1
    out: list[ElementAssertion] = []
    start = 0
    for sent in SENTENCE_SPLIT.split(text):
        s0 = text.find(sent, start)
        start = s0 + len(sent)
        fams = match_families(sent, only)
        if not fams:
            continue
        rooms = rooms_in(sent)
        if not rooms:
            continue
        ws = [w for (t, w), o in zip(stream, offsets, strict=False) if s0 <= o < s0 + len(sent)]
        for fam, anchor in fams:
            out.append(ElementAssertion(fam.code, rooms, "TEXT", page.file_id, page.page_no, squash(sent), anchor,
                                        _words_box(ws), 0.9))  # fmt: skip
    return out


A4_AREA_PT2 = 595.0 * 842.0


def is_drawing(page: PageData) -> bool:
    """A drawing sheet (A2 and larger, or A3 with sparse text), where labels sit next to what they name."""
    area = page.width * page.height
    if area >= 3.5 * A4_AREA_PT2:
        return True
    return area >= 1.8 * A4_AREA_PT2 and len(page.words) < 400


def _label_groups(page: PageData) -> list[tuple[list[str], Box]]:
    """Room labels, with comma lists on one baseline joined: «267,» «270» → ([267, 270], box)."""
    words = sorted((w for w in page.words if LABEL_ROOM.match(w.text)), key=lambda w: (round(w.cy), w.x0))
    groups: list[tuple[list[str], Box, Word]] = []
    for w in words:
        if groups:
            rooms, box, last = groups[-1]
            if (
                last.text.endswith(",")
                and abs(last.cy - w.cy) < 0.5 * w.h
                and 0 <= w.x0 - last.x1 < 2.5 * w.h
            ):
                rooms.append(w.text.rstrip(","))
                groups[-1] = (rooms, box.union(Box(w.x0, w.y0, w.x1, w.y1)), w)
                continue
        groups.append(([w.text.rstrip(",")], Box(w.x0, w.y0, w.x1, w.y1), w))
    return [(r, b) for r, b, _ in groups]


def diagonal_segments(page: PageData) -> list[tuple[float, float, float, float]]:
    """Straight non-axis-aligned segments of the page (leader lines), displayed points; cached per page."""
    cached = getattr(page, "_diagonals", None)
    if cached is not None:
        return cached
    out: list[tuple[float, float, float, float]] = []
    if page._page is not None:
        m = page._page.rotation_matrix
        a, b, c, d, e, f = m.a, m.b, m.c, m.d, m.e, m.f
        for dr in page.drawings():
            for it in dr.get("items", ()):
                if it[0] != "l":
                    continue
                (x0, y0), (x1, y1) = it[1], it[2]
                dx, dy = abs(x1 - x0), abs(y1 - y0)
                if dx < 3 or dy < 3:
                    continue
                length = (dx * dx + dy * dy) ** 0.5
                if not 15 <= length <= 900:
                    continue
                out.append(
                    (a * x0 + c * y0 + e, b * x0 + d * y0 + f, a * x1 + c * y1 + e, b * x1 + d * y1 + f)
                )
    page._diagonals = out  # type: ignore[attr-defined]
    return out


_CELL = 64.0


def _diagonal_index(page: PageData) -> dict[tuple[int, int], list[int]]:
    """Grid index (64 pt cells) of both endpoints of every diagonal segment; cached per page. Site plans carry
    hatching with 10⁵ diagonals, so a text block only looks at the cells around it."""
    cached = getattr(page, "_diag_index", None)
    if cached is not None:
        return cached
    index: dict[tuple[int, int], list[int]] = {}
    for i, (ax, ay, bx, by) in enumerate(diagonal_segments(page)):
        for x, y in ((ax, ay), (bx, by)):
            index.setdefault((int(x // _CELL), int(y // _CELL)), []).append(i)
    page._diag_index = index  # type: ignore[attr-defined]
    return index


def leader_endpoints(page: PageData, box: Box, pad: float = 10.0) -> list[tuple[float, float]]:
    """Far ends of the leader lines that start at a text block (diagonal segments with one end on the block's
    left/right edge and the other outside it)."""
    grown = Box(box.x0 - pad, box.y0 - 4.0, box.x1 + pad, box.y1 + 4.0)
    segs = diagonal_segments(page)
    index = _diagonal_index(page)
    cand: set[int] = set()
    for cx in range(int(grown.x0 // _CELL), int(grown.x1 // _CELL) + 1):
        for cy in range(int(grown.y0 // _CELL), int(grown.y1 // _CELL) + 1):
            cand.update(index.get((cx, cy), ()))
    out: list[tuple[float, float]] = []
    for i in cand:
        ax, ay, bx, by = segs[i]
        ina = grown.x0 <= ax <= grown.x1 and grown.y0 <= ay <= grown.y1
        inb = grown.x0 <= bx <= grown.x1 and grown.y0 <= by <= grown.y1
        if ina == inb:
            continue
        nx, far = (ax, (bx, by)) if ina else (bx, (ax, ay))
        # a leader starts at the left or right edge of the text block (the underline's end)
        if min(abs(nx - box.x0), abs(nx - box.x1)) <= pad + 2:
            out.append(far)
    return sorted(dict.fromkeys((round(x, 1), round(y, 1)) for x, y in out))


def label_assertions(
    page: PageData, radius_pt: float = 160.0, only: tuple[str, ...] | None = None
) -> list[ElementAssertion]:
    """Drawing text naming an element family → rooms. When leader lines start at the text, the rooms are the
    labels of the cells their far ends point into (confidence 0.8); otherwise the nearest labels (0.5).
    Text pages are skipped."""
    if not is_drawing(page):
        return []
    lines = segments(page.words)
    groups = _label_groups(page)
    out: list[ElementAssertion] = []
    for _i, ln in enumerate(lines):
        fams = match_families(ln.text, only)
        if not fams:
            continue
        # the text block: this line plus adjacent lines of the same label (stacked within 1.8 line heights)
        block = Box(ln.x0, ln.y0, ln.x1, ln.y1)
        text = ln.text
        for other in lines:
            if other is ln:
                continue
            if abs(other.x0 - ln.x0) < 3 * (ln.y1 - ln.y0) and (
                0 <= block.y0 - other.y1 < 1.8 * (ln.y1 - ln.y0)
                or 0 <= other.y0 - block.y1 < 1.8 * (ln.y1 - ln.y0)
            ):
                block = block.union(Box(other.x0, other.y0, other.x1, other.y1))
                text = (
                    squash(" ".join(x.text for x in sorted([ln, other], key=lambda x: x.y0)))
                    if len(text) < 200
                    else text
                )
        ends = leader_endpoints(page, block)
        rooms: list[str] = []
        boxes = [block]
        confidence = 0.5
        if ends:
            v_walls = [r for r in page.rulings()[0] if r.length >= 20]
            for ex, ey in ends:
                # the room label of the cell the leader points into: a label left of the end, at or above its
                # level, with no wall (vertical line) between them
                cand = []
                for r, b in groups:
                    if b.x0 > ex + 2 or ex - b.x0 > 300 or b.y0 > ey + 15 or ey - b.y1 > 120:
                        continue
                    wall = any(
                        b.x1 + 1 < w.pos < ex - 1 and w.covers((b.y0 + b.y1) / 2, 1.0) for w in v_walls
                    )
                    if not wall:
                        cand.append((ex - b.x0 + abs(ey - b.y0), r, b))
                if cand:
                    _, r, b = min(cand, key=lambda c: c[0])
                    rooms.extend(r)
                    boxes.append(b)
            if rooms:
                confidence = 0.8
        if not rooms:
            near = []
            for r, b in groups:
                dx = max(block.x0 - b.x1, 0, b.x0 - block.x1)
                dy = max(block.y0 - b.y1, 0, b.y0 - block.y1)
                dd = (dx * dx + dy * dy) ** 0.5
                if dd <= radius_pt:
                    near.append((dd, r, b))
            near.sort(key=lambda x: x[0])
            if near:
                cut = max(1.6 * near[0][0], 30.0)
                for dd, r, b in near[:4]:
                    if dd <= cut:
                        rooms.extend(r)
                        boxes.append(b)
        rooms = list(dict.fromkeys(rooms))
        if not rooms:
            continue
        box = boxes[0]
        for b in boxes[1:]:
            box = box.union(b)
        for fam, anchor in fams:
            out.append(ElementAssertion(fam.code, rooms, "LABEL", page.file_id, page.page_no, text, anchor, box, confidence,
                                        extra={"leaders": len(ends)}))  # fmt: skip
    # one assertion per family and room set (a block matched on several of its lines)
    uniq: dict[tuple[str, tuple[str, ...]], ElementAssertion] = {}
    for a in out:
        k = (a.family, tuple(sorted(a.rooms)))
        if k not in uniq or a.confidence > uniq[k].confidence:
            uniq[k] = a
    return list(uniq.values())


def spec_assertions(items: list, file_id: str, only: tuple[str, ...] | None = None) -> list[ElementAssertion]:
    """Specification items (spec21110.SpecItem) naming an element family: object-level, with quantity."""
    from inspector_tables.spec21110 import item_text

    out: list[ElementAssertion] = []
    for it in items:
        if it.kind != "DATA":
            continue
        txt = item_text(it)
        for fam, anchor in match_families(txt, only):
            boxes = [r.box for r in it.raws if r.box is not None]
            box = boxes[0] if boxes else None
            for b in boxes[1:]:
                box = box.union(b) if box else b
            out.append(ElementAssertion(fam.code, [], "SPEC", file_id, it.page_no, txt, anchor, box, 0.8,
                                        quantity=it.quantity, extra={"unit": it.cells.get("unit")}))  # fmt: skip
    return out


def table_assertions(rooms: list, file_id: str) -> list[ElementAssertion]:
    """Air-exchange rows (airx.RoomSystems) → one assertion per room and system role, with the tags."""
    role_family = {"sys_supply": "VENT_SUPPLY_UNIT", "sys_exhaust": "VENT_EXHAUST_UNIT", "sys_mo": "VENT_EXHAUST_BRANCH",
                   "sys_comp": "VENT_SUPPLY_UNIT"}  # fmt: skip
    known = {f.code for f in families()}
    out: list[ElementAssertion] = []
    for r in rooms:
        for role, tags in r.systems.items():
            if not tags:
                continue
            fam = role_family.get(role)
            if fam not in known:
                continue
            out.append(ElementAssertion(fam, [r.room_no], "TABLE", file_id, r.page_no, f"{r.room_no} {r.name}: {', '.join(tags)}",
                                        role, r.box, 0.85, tags=list(tags), extra={"role": role, "raw": r.raw.get(role)}))  # fmt: skip
    return out
