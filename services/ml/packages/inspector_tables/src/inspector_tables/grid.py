"""Header-anchored grid engine (96 §6): find a table from a header keyword, not from a generic detector.

For each anchor word (e.g. «Наименование») of a table type:

1. **Ruled mode.** Vertical rulings that cross the anchor are its cell borders; the nearest horizontal
   rulings above/below give the header band. Every vertical ruling crossing the band and running on into
   the body is a column border. Header text per column is matched against the type's column grammar, and
   the table is grown left/right from the anchor while the column keys keep the canonical order. That order
   rule is what separates side-by-side tables sharing a border (F0201 p18: four explications in a row).
   Row separators are the horizontal rulings spanning the key column; merged cells are rows where an
   interior border does not cross the row.
2. **Aligned mode** (no usable rulings: scans without detected lines, text tables). Columns come from the
   header words' x-extents, body lines are grouped into rows by a type-specific «new row» rule.

The engine returns :class:`RawTable` objects; the typed parsers turn them into contract rows.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from inspector_tables.pagesource import PageData
from inspector_tables.text import Box, Ruling, TextLine, Word, fold, group_lines, lines_text


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    key: str
    patterns: tuple[str, ...]  # regexes on the folded header text of the column

    def matches(self, folded: str) -> bool:
        return any(re.search(p, folded) for p in self.patterns)


@dataclass(frozen=True, slots=True)
class TableSpec:
    table_type: str
    anchor: str  # regex on a folded word (or on the folded line for multi-word anchors)
    columns: tuple[ColumnSpec, ...]  # canonical left-to-right order
    required: frozenset[str]
    key_column: str
    caption: str | None = None  # regex on the folded caption line
    anchor_on_line: bool = False
    max_header_pt: float = 140.0
    # key inference from body content for columns whose header is outlined/unreadable: (key, predicate)
    content_keys: tuple[tuple[str, str], ...] = ()

    def classify(self, header_text: str) -> str | None:
        f = fold(header_text)
        if not f:
            return None
        for c in self.columns:
            if c.matches(f):
                return c.key
        return None

    def order(self, key: str) -> int:
        for i, c in enumerate(self.columns):
            if c.key == key:
                return i
        return -1


@dataclass(slots=True)
class Column:
    x0: float
    x1: float
    key: str | None
    header: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(slots=True)
class RawCell:
    text: str
    words: list[Word]
    box: Box | None


@dataclass(slots=True)
class RawRow:
    y0: float
    y1: float
    cells: dict[str, RawCell]  # column key → cell
    merged: bool = False  # no interior border crosses the row (full-width cell)
    merged_text: str = ""
    spans: list[tuple[int, int]] = field(default_factory=list)  # merged column index ranges

    def text(self, key: str) -> str:
        c = self.cells.get(key)
        return c.text if c else ""

    @property
    def box(self) -> Box | None:
        boxes = [c.box for c in self.cells.values() if c.box is not None]
        if not boxes:
            return None
        b = boxes[0]
        for o in boxes[1:]:
            b = b.union(o)
        return b

    @property
    def all_words(self) -> list[Word]:
        return [w for c in self.cells.values() for w in c.words]


@dataclass(slots=True)
class RawTable:
    table_type: str
    page_no: int
    box: Box
    header_box: Box
    columns: list[Column]
    rows: list[RawRow]
    caption: str | None
    method: str  # "rulings" | "raster_rulings" | "aligned" | "continuation"
    anchor: Word | None = None
    page: PageData | None = None  # for normalized output boxes

    @property
    def keys(self) -> list[str]:
        return [c.key for c in self.columns if c.key]


# ── ruled mode ────────────────────────────────────────────────────────────────────────────────────


def _crossing_v(v: list[Ruling], y: float, x_lo: float, x_hi: float) -> list[float]:
    return sorted(r.pos for r in v if r.covers(y, 0.5) and x_lo <= r.pos <= x_hi)


def _dedupe(xs: list[float], tol: float = 2.0) -> list[float]:
    out: list[float] = []
    for x in sorted(xs):
        if out and x - out[-1] <= tol:
            out[-1] = (out[-1] + x) / 2
        else:
            out.append(x)
    return out


def _header_band(
    anchor: Word, v: list[Ruling], h: list[Ruling], max_pt: float
) -> tuple[float, float, float, float] | None:
    """(left, right, top, bottom) of the anchor's header cell from the rulings around it."""
    xs = _crossing_v(v, anchor.cy, anchor.x0 - 600, anchor.x1 + 600)
    left = [x for x in xs if x <= anchor.x0 + 1]
    right = [x for x in xs if x >= anchor.x1 - 1]
    if not left or not right:
        return None
    lx, rx = left[-1], right[0]
    mid = (anchor.x0 + anchor.x1) / 2
    ys = sorted(r.pos for r in h if r.lo <= mid + 1 and r.hi >= mid - 1)
    above = [y for y in ys if y <= anchor.y0 + 0.5 and anchor.y0 - y <= max_pt]
    below = [y for y in ys if y >= anchor.y1 - 0.5 and y - anchor.y1 <= max_pt]
    if not above or not below:
        return None
    return lx, rx, above[-1], below[0]


def _column_borders(v: list[Ruling], top: float, bottom: float, x_lo: float, x_hi: float) -> list[float]:
    """Vertical rulings crossing the lower part of the header band and continuing into the body."""
    y_probe = bottom - 0.3 * (bottom - top)
    below = [r for r in v if r.hi >= bottom + 3 and r.lo <= bottom + 160]
    xs = []
    for r in v:
        if not (r.covers(y_probe, 0.5) and x_lo <= r.pos <= x_hi):
            continue
        # the border runs on into the body, possibly after a full-width row (section title) under the header
        if r.hi >= bottom + 3 or any(abs(o.pos - r.pos) <= 1.5 for o in below):
            xs.append(r.pos)
    return _dedupe(xs)


def _cell_words(words: list[Word], x0: float, x1: float, y0: float, y1: float) -> list[Word]:
    return [w for w in words if x0 <= w.cx <= x1 and y0 <= w.cy <= y1]


CONTENT_PREDICATES: dict[str, Callable[[str], bool]] = {
    "room": lambda t: bool(
        re.fullmatch(r"(?:[0-9]{1,4}(?:[.\-/][0-9]{1,4}){0,2}[а-яa-zА-ЯA-Z]?)", t.replace(" ", ""))
    ),
    "decimal": lambda t: bool(re.fullmatch(r"[+\-−]?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d{1,3})?", t)),
    "fraction": lambda t: bool(re.fullmatch(r"[+\-−]?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)[.,]\d{1,3}", t)),
    "int": lambda t: bool(re.fullmatch(r"\d{1,4}", t)),
    "rowno": lambda t: bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){0,3}\.?", t)),
}


def _infer_key(spec: TableSpec, words: list[Word], col: Column, bottom: float, used: set[str]) -> str | None:
    """Key of a header-less column from its body: the first content rule that ≥ 60 % of its lines satisfy."""
    if not spec.content_keys:
        return None
    body = [w for w in words if col.x0 <= w.cx <= col.x1 and bottom < w.cy <= bottom + 500]
    texts = [ln.text for ln in group_lines(body)]
    if len(texts) < 2:
        return None
    for key, pred in spec.content_keys:
        if key in used:
            continue
        ok = sum(1 for t in texts if CONTENT_PREDICATES[pred](t))
        if ok >= max(2, 0.6 * len(texts)):
            return key
    return None


def _grow_columns(
    spec: TableSpec, borders: list[float], anchor: Word, words: list[Word], top: float, bottom: float
) -> list[Column] | None:
    cols: list[Column] = []
    for a, b in itertools.pairwise(borders):
        if b - a < 3:
            continue
        ws = _cell_words(words, a, b, top, bottom)
        text = lines_text(ws)
        cols.append(Column(a, b, spec.classify(text), text))
    idx = next((i for i, c in enumerate(cols) if c.x0 <= anchor.cx <= c.x1), None)
    if idx is None or cols[idx].key is None:
        return None
    for i, c in enumerate(cols):
        if c.key is None and abs(i - idx) <= 6:
            c.key = _infer_key(spec, words, c, bottom, set())
            if c.key:
                c.header = c.header or ""
    lo = hi = idx
    used = {cols[idx].key}
    # grow left: keys must come earlier in the canonical order; unknown headed columns are allowed inside
    while lo - 1 >= 0:
        c = cols[lo - 1]
        leftmost_known = next((cols[i].key for i in range(lo, hi + 1) if cols[i].key), None)
        if c.key is None:
            if not c.header or not _known_further(cols, lo - 1, -1, spec, used, leftmost_known):
                break
        elif c.key in used or (leftmost_known and spec.order(c.key) >= spec.order(leftmost_known)):
            break
        if c.key:
            used.add(c.key)
        lo -= 1
    while hi + 1 < len(cols):
        c = cols[hi + 1]
        rightmost_known = next((cols[i].key for i in range(hi, lo - 1, -1) if cols[i].key), None)
        if c.key is None:
            if not c.header or not _known_further(cols, hi + 1, +1, spec, used, rightmost_known):
                break
        elif c.key in used or (rightmost_known and spec.order(c.key) <= spec.order(rightmost_known)):
            break
        if c.key:
            used.add(c.key)
        hi += 1
    return cols[lo : hi + 1]


def _known_further(
    cols: list[Column], i: int, step: int, spec: TableSpec, used: set[str], edge_key: str | None
) -> bool:
    """An unknown headed column is inside the table when a compatible known column follows it."""
    j = i + step
    while 0 <= j < len(cols):
        k = cols[j].key
        if k:
            if k in used or edge_key is None:
                return False
            return spec.order(k) < spec.order(edge_key) if step < 0 else spec.order(k) > spec.order(edge_key)
        if not cols[j].header:
            return False
        j += step
    return False


def _outer_bottom(v: list[Ruling], x: float, header_bottom: float) -> float | None:
    best = None
    for r in v:
        if abs(r.pos - x) <= 1.5 and r.lo <= header_bottom + 2 and r.hi > header_bottom + 3:
            best = max(best or r.hi, r.hi)
    return best


def _row_separators(h: list[Ruling], col: Column, y_lo: float, y_hi: float) -> list[float]:
    ys = [r.pos for r in h if r.lo <= col.x0 + 2.5 and r.hi >= col.x1 - 2.5 and y_lo - 1 <= r.pos <= y_hi + 1]
    return _dedupe(ys, 1.5)


def _build_rows(
    page: PageData, cols: list[Column], seps: list[float], v: list[Ruling], x0: float, x1: float
) -> list[RawRow]:
    rows: list[RawRow] = []
    interior = [c.x0 for c in cols[1:]]
    body_words = [w for w in page.words if x0 - 1 <= w.cx <= x1 + 1 and seps[0] - 1 <= w.cy <= seps[-1] + 1]
    for a, b in itertools.pairwise(seps):
        if b - a < 2.0:
            continue
        mid = (a + b) / 2
        # a row exists only between the table's outer borders (below the table they stop; the page frame
        # or a title block may continue)
        outer = [any(abs(r.pos - x) <= 1.5 and r.covers(mid, 0.5) for r in v) for x in (x0, x1)]
        if not all(outer):
            if rows:
                break
            continue
        ws = [w for w in body_words if a <= w.cy <= b]
        present = [any(abs(r.pos - x) <= 1.5 and r.covers(mid, 0.5) for r in v) for x in interior]
        # spans of columns not separated by a present border
        spans: list[tuple[int, int]] = []
        start = 0
        for i, p in enumerate(present):
            if p:
                spans.append((start, i))
                start = i + 1
        spans.append((start, len(cols) - 1))
        merged = len(cols) > 1 and not any(present)
        cells: dict[str, RawCell] = {}
        for c in cols:
            if not c.key:
                continue
            cw = [w for w in ws if c.x0 <= w.cx <= c.x1]
            cells[c.key] = RawCell(lines_text(cw), cw, Box.of_words(cw) or Box(c.x0, a, c.x1, b))
            if not cw:
                cells[c.key].box = None
        rows.append(
            RawRow(a, b, cells, merged, lines_text(ws) if merged else "", [s for s in spans if s[1] > s[0]])
        )
    return rows


def find_ruled(page: PageData, spec: TableSpec, anchor: Word) -> RawTable | None:
    v, h = page.rulings()
    if not v or not h:
        return None
    band = _header_band(anchor, v, h, spec.max_header_pt)
    if band is None:
        return None
    _lx, _rx, top, bottom = band
    borders = _column_borders(v, top, bottom, 0.0, page.width)
    if len(borders) < 2:
        return None
    cols = _grow_columns(spec, borders, anchor, page.words, top, bottom)
    if not cols or not spec.required <= {c.key for c in cols if c.key}:
        return None
    x0, x1 = cols[0].x0, cols[-1].x1
    ends = [e for e in (_outer_bottom(v, x0, bottom), _outer_bottom(v, x1, bottom)) if e is not None]
    if not ends:
        return None
    table_bottom = max(ends)
    key_col = next((c for c in cols if c.key == spec.key_column), max(cols, key=lambda c: c.x1 - c.x0))
    seps = _row_separators(h, key_col, bottom, table_bottom)
    if not seps or abs(seps[0] - bottom) > 2.0:
        seps = [bottom, *seps]
    if table_bottom - seps[-1] > 2.0:
        seps.append(table_bottom)
    rows = _build_rows(page, cols, seps, v, x0, x1)
    caption = find_caption(page, spec, x0, x1, top)
    return RawTable(spec.table_type, page.page_no, Box(x0, top, x1, seps[-1]), Box(x0, top, x1, bottom), cols,
                    rows, caption, "rulings", anchor, page)  # fmt: skip


def find_caption(page: PageData, spec: TableSpec, x0: float, x1: float, top: float) -> str | None:
    """The closest text line above the table, inside its x-range (captions sit within ~4 line heights)."""
    lines = [ln for ln in group_lines([w for w in page.words if x0 - 5 <= w.cx <= x1 + 5 and w.cy < top])]
    lines = [ln for ln in lines if top - ln.y1 <= max(60.0, 4 * (ln.y1 - ln.y0))]
    if not lines:
        return None
    lines.sort(key=lambda ln: -ln.y1)
    if spec.caption:
        for ln in lines[:3]:
            if re.search(spec.caption, fold(ln.text)):
                return ln.text
        return None
    return lines[0].text


# ── aligned mode ──────────────────────────────────────────────────────────────────────────────────


def _header_lines(lines: list[TextLine], anchor_line: int, spec: TableSpec) -> tuple[int, int]:
    """Header = the anchor line plus adjacent lines (within 1.6 line heights) that hold header words."""
    lo = hi = anchor_line
    lh = lines[anchor_line].y1 - lines[anchor_line].y0
    while lo - 1 >= 0 and lines[lo].y0 - lines[lo - 1].y1 <= 1.6 * lh and _headerish(lines[lo - 1], spec):
        lo -= 1
    while (
        hi + 1 < len(lines)
        and lines[hi + 1].y0 - lines[hi].y1 <= 1.6 * lh
        and _headerish(lines[hi + 1], spec)
    ):
        hi += 1
    return lo, hi


def _headerish(line: TextLine, spec: TableSpec) -> bool:
    t = fold(line.text)
    if not t or re.fullmatch(r"[\d\s.,]+", t):
        return False
    return any(c.matches(t) for c in spec.columns) or all(
        len(w.text) <= 14 and not any(ch.isdigit() for ch in w.text) for w in line.words
    )


def _header_columns(spec: TableSpec, header_words: list[Word]) -> list[Column]:
    """Cluster header words into column groups by horizontal gaps, then classify each group."""
    ws = sorted(header_words, key=lambda w: w.x0)
    groups: list[list[Word]] = []
    for w in ws:
        em = max(w.h, 1.0)
        if groups and w.x0 - max(x.x1 for x in groups[-1]) <= 1.2 * em:
            groups[-1].append(w)
        else:
            groups.append([w])
    cols = []
    for g in groups:
        text = lines_text(g)
        cols.append(Column(min(w.x0 for w in g), max(w.x1 for w in g), spec.classify(text), text))
    return cols


def find_aligned(
    page: PageData,
    spec: TableSpec,
    anchor: Word,
    new_row: Callable[[dict[str, str]], bool],
    stop: Callable[[str], bool] | None = None,
) -> RawTable | None:
    lines = group_lines(page.words)
    ai = next((i for i, ln in enumerate(lines) if anchor in ln.words), None)
    if ai is None:
        return None
    lo, hi = _header_lines(lines, ai, spec)
    header_words = [w for ln in lines[lo : hi + 1] for w in ln.words]
    cols = _header_columns(spec, header_words)
    keys = {c.key for c in cols if c.key}
    if not spec.required <= keys:
        return None
    # column ranges: midpoints between adjacent header groups
    bounds = [cols[0].x0 - 0.5 * (cols[0].x1 - cols[0].x0) - 10]
    for a, b in itertools.pairwise(cols):
        bounds.append((a.x1 + b.x0) / 2)
    bounds.append(cols[-1].x1 + 0.5 * (cols[-1].x1 - cols[-1].x0) + 40)
    for c, a, b in zip(cols, bounds, bounds[1:], strict=False):
        c.x0, c.x1 = a, b
    x0, x1 = cols[0].x0, cols[-1].x1
    header_bottom = lines[hi].y1
    rows: list[RawRow] = []
    lh = max(1.0, lines[ai].y1 - lines[ai].y0)
    last_y = header_bottom
    for ln in lines[hi + 1 :]:
        inside = [w for w in ln.words if x0 <= w.cx <= x1]
        if not inside:
            continue
        if ln.y0 - last_y > 4.0 * lh:
            break
        text = " ".join(w.text for w in inside)
        if stop and stop(text):
            break
        cells_text: dict[str, list[Word]] = {}
        for w in inside:
            c = next((c for c in cols if c.x0 <= w.cx <= c.x1), None)
            if c and c.key:
                cells_text.setdefault(c.key, []).append(w)
        simple = {k: lines_text(v) for k, v in cells_text.items()}
        if not rows or new_row(simple):
            rows.append(
                RawRow(
                    ln.y0,
                    ln.y1,
                    {k: RawCell(lines_text(v), v, Box.of_words(v)) for k, v in cells_text.items()},
                )
            )
        else:
            row = rows[-1]
            row.y1 = ln.y1
            for k, v in cells_text.items():
                if k in row.cells:
                    row.cells[k].words.extend(v)
                    row.cells[k].text = lines_text(row.cells[k].words)
                    row.cells[k].box = Box.of_words(row.cells[k].words)
                else:
                    row.cells[k] = RawCell(lines_text(v), v, Box.of_words(v))
        last_y = ln.y1
    if not rows:
        return None
    caption = find_caption(page, spec, x0, x1, lines[lo].y0)
    return RawTable(spec.table_type, page.page_no, Box(x0, lines[lo].y0, x1, rows[-1].y1),
                    Box(x0, lines[lo].y0, x1, header_bottom), cols, rows, caption, "aligned", anchor, page)  # fmt: skip


# ── driver ────────────────────────────────────────────────────────────────────────────────────────


def anchors(page: PageData, spec: TableSpec) -> list[Word]:
    if spec.anchor_on_line:
        out = []
        for ln in group_lines(page.words):
            if re.search(spec.anchor, fold(ln.text)):
                out.append(ln.words[0])
        return out
    return [w for w in page.words if w.angle in (0, 180) and re.search(spec.anchor, fold(w.text))]


def find_tables(
    page: PageData,
    spec: TableSpec,
    new_row: Callable[[dict[str, str]], bool] | None = None,
    stop: Callable[[str], bool] | None = None,
    allow_aligned: bool = True,
) -> list[RawTable]:
    """Every table of ``spec`` on the page (ruled first; aligned when rulings do not frame the anchor)."""
    found: list[RawTable] = []
    for a in anchors(page, spec):
        if any(
            t.header_box.x0 - 1 <= a.cx <= t.header_box.x1 + 1
            and t.header_box.y0 - 1 <= a.cy <= t.header_box.y1 + 1
            for t in found
        ):
            continue
        if any(t.box.x0 <= a.cx <= t.box.x1 and t.box.y0 <= a.cy <= t.box.y1 for t in found):
            continue
        t = None
        for kind in page.ruling_sets():
            page.active = kind
            t = find_ruled(page, spec, a)
            if t is not None:
                t.method = "rulings" if kind == "vector" else "raster_rulings"
                break
        page.active = "vector"
        if t is None and allow_aligned and new_row is not None:
            t = find_aligned(page, spec, a, new_row, stop)
        if t is not None and t.rows:
            found.append(t)
    found.sort(key=lambda t: (round(t.box.y0 / 20), t.box.x0))
    return found


def find_continuation(
    page: PageData, prev: RawTable, below: float = 0.0, max_gap_pt: float = 400.0
) -> RawTable | None:
    """The same table continued without a repeated header — on the next page (``below`` = 0) or as the next
    ruled block on the same page (a registry section under its title): vertical rulings at the previous
    part's column borders (±2 pt) framing a block that starts within ``max_gap_pt`` below ``below``."""
    v, h = page.rulings()
    if not v or not h:
        return None
    xs = [prev.columns[0].x0, *[c.x1 for c in prev.columns]]
    spans = []
    for x in xs:
        segs = sorted(
            (r for r in v if abs(r.pos - x) <= 2.0 and r.length >= 8 and r.lo >= below - 1.0),
            key=lambda r: r.lo,
        )
        if not segs:
            return None
        lo, hi = segs[0].lo, segs[0].hi
        for r in segs[1:]:
            if r.lo <= hi + 3.0:
                hi = max(hi, r.hi)
        spans.append((lo, hi))
    top = min(lo for lo, _ in spans)
    bottom = min(hi for _, hi in spans)
    if top - below > max_gap_pt or bottom - top < 8:
        return None
    if max(lo for lo, _ in spans) - top > 6:  # the borders must start together: one block, not stray lines
        return None
    cols = [Column(c.x0, c.x1, c.key, c.header) for c in prev.columns]
    key_col = max(cols, key=lambda c: c.x1 - c.x0)
    seps = _row_separators(h, key_col, top, bottom)
    if not seps or abs(seps[0] - top) > 2.0:
        seps = [top, *seps]
    if bottom - seps[-1] > 2.0:
        seps.append(bottom)
    rows = _build_rows(page, cols, seps, v, cols[0].x0, cols[-1].x1)
    if not rows:
        return None
    title_words = [w for w in page.words if below < w.cy < top and cols[0].x0 - 5 <= w.cx <= cols[-1].x1 + 5]
    title = lines_text(title_words) or None
    return RawTable(prev.table_type, page.page_no, Box(cols[0].x0, top, cols[-1].x1, seps[-1]), Box(cols[0].x0, top, cols[-1].x1, top),
                    cols, rows, title, "continuation", None, page)  # fmt: skip
