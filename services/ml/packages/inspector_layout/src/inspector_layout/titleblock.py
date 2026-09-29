"""Title-block (основная надпись) reader for ГОСТ Р 21.101 forms 3, 4–5 and 6 (96 §7.3, R-07).

Input: words of the stamp window in millimetres of the displayed page (:mod:`inspector_layout.words`), from
the text layer or from OCR. The reader is anchor-based, not template-based:

1. **Labels.** «Изм. | Кол.уч. | Лист | № док. | Подп. | Дата» (the change-table header), «Стадия | Лист |
   Листов» (forms 3–5) and the lone «Лист» at the right edge of form 6 are found with homoglyph folding and a
   small edit tolerance (OCR: «Луст», «№gok.»); labels split over two lines in narrow cells («Лис|т»,
   «№До|к») are merged.
2. **Grid.** The canonical ГОСТ column centres (change table 10/10/10/10/15/10 mm, then 70 mm of titles and
   15/15/20 mm of Стадия/Лист/Листов, 185 mm in all) are fitted to the label centres (offset and scale, so a
   drawing printed at another scale still reads). Rows are 5 mm times the fitted scale.
3. **Cells.** Values are the words below their label within the fitted column; «Изм.» rows are the 5 mm
   rows above the header, split into the six columns; the шифр is the tallest code-shaped line of the
   right block; titles are graph 2 (between шифр and «Стадия»), graph 5 (under the Стадия block, left of it)
   and graph 9 (the organisation, under the Стадия block).

Nothing here reads gold data. Values keep the printed spelling; the document code goes through the code gate
(:class:`inspector_layout.codes.CodeRegistry`), the stage through :func:`inspector_layout.codes.fold_stage`.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from inspector_layout.codes import CodeRegistry, fold_stage, looks_like_code
from inspector_layout.words import Word, dedupe

# Stamp search window (bottom-right of the displayed page): 185×55 mm stamp + 5 mm frame + margins.
WINDOW_MM = (215.0, 85.0)
# Canonical centres (mm from the left edge of the stamp) of the ГОСТ Р 21.101 grid.
HEADER_CENTRES = {"CHANGE": 5.0, "COUNT": 15.0, "SHEET": 25.0, "DOCNO": 35.0, "SIGN": 47.5, "DATE": 60.0}
HEADER_EDGES = (0.0, 10.0, 20.0, 30.0, 40.0, 55.0, 65.0)
HEADER_COLUMNS = ("CHANGE", "COUNT", "SHEET", "DOCNO", "SIGN", "DATE")
RIGHT_CENTRES = {"STAGE": 142.5, "SHEET_R": 157.5, "SHEETS": 175.0}
RIGHT_HALF_WIDTH = {"STAGE": 7.5, "SHEET_R": 7.5, "SHEETS": 10.0}
FORM6_SHEET_CENTRE = 180.0  # form 6: «Лист» cell is the last 10 mm
ROW_MM = 5.0
STAMP_WIDTH_MM = 185.0

_LAT2CYR = str.maketrans(
    {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у", "k": "к", "m": "м", "t": "т",
     "h": "н", "b": "в", "u": "и", "n": "п", "r": "г", "g": "д", "3": "з", "0": "о", "6": "б"}
)  # fmt: skip


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    t = re.sub(r"[\s.,:;'\"«»()\-_]", "", t)
    return t


def _fold(t: str) -> str:
    return t.translate(_LAT2CYR)


def _lev(a: str, b: str) -> int:
    from rapidfuzz.distance import Levenshtein

    return Levenshtein.distance(a, b)


def label_kind(text: str) -> str | None:
    """Label kind of one stamp word, or None."""
    raw = _norm(text)
    if not raw or len(raw) > 12:
        return None
    t = _fold(raw)
    if t in ("стадия", "стадиа") or (
        len(t) in (5, 6, 7) and _lev(t, "стадия") <= 1 and t[0] in "сc" and t[-1] in "яa"  # not «стадии»
    ):
        return "STAGE"
    if t == "листов" or (
        len(t) in (5, 6, 7) and _lev(t, "листов") <= 1 and t.startswith("л") and t != "лист"
    ):
        return "SHEETS"
    if t == "лист" or (len(t) == 4 and _lev(t, "лист") <= 1 and t[0] == "л" and t[-1] in "тмm"):
        return "SHEET"
    if t in ("изм", "изм№", "изменение"):
        return "CHANGE"
    if t in ("кол", "колуч", "колвоуч", "кол-во", "колво", "колич"):
        return "COUNT"
    if t in ("подп", "подпись", "подпис", "подпсь", "подписъ") or (
        len(t) == 7 and t.startswith("подп") and _lev(t, "подпись") <= 1
    ):
        return "SIGN"
    if t in ("дата", "дaта") or (len(t) == 4 and _lev(t, "дата") <= 1 and (t[0] == "д" or t[1:] == "ата")):
        return "DATE"
    had_no = raw.startswith(("№", "n", "н", "no"))
    core = re.sub(r"^(№|no|n|н)", "", raw)
    core = _fold(core)
    if core in ("док", "документа", "докум", "дoк") or (had_no and len(core) == 3 and _lev(core, "док") <= 1):
        return "DOCNO"
    if t in ("разраб", "разработал", "разраб", "пров", "проверил", "гип", "гап", "нконтр", "нконтроль",
             "утв", "утвердил", "составил", "измвнес", "тконтр", "рукгр", "начотд", "исполн", "инж"):  # fmt: skip
        return "ROLE"
    return None


@dataclass(slots=True)
class Label:
    kind: str
    word: Word


def _merge_split_labels(words: list[Word]) -> list[Word]:
    """«Лис» over «т», «№До» over «к», «№» + «док.» side by side → one label word."""
    out = list(words)
    used: set[int] = set()
    merged: list[Word] = []
    for i, a in enumerate(words):
        if i in used or label_kind(a.text) is not None:
            continue
        for j, b in enumerate(words):
            if j == i or j in used:
                continue
            # vertical split in a narrow cell
            ox = min(a.x1, b.x1) - max(a.x0, b.x0)
            vertical = (
                ox > 0.3 * min(a.w, b.w)
                and -0.4 * min(a.h, b.h) <= b.y0 - a.y1 < max(1.8, 0.6 * a.h)
                and b.cy > a.cy
                and len(b.text) <= 3
            )
            # horizontal split («№» «док.», «Кол.» «уч.»)
            horizontal = abs(a.cy - b.cy) < 0.5 * max(a.h, b.h) and 0 <= b.x0 - a.x1 < max(2.0, 0.8 * a.h)
            if not (vertical or horizontal):
                continue
            joined = a.text + b.text
            if label_kind(joined) is None:
                continue
            merged.append(
                Word(joined, min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1), a.source,
                     min(a.conf, b.conf), None, a.angle, a.layer)
            )  # fmt: skip
            used.update((i, j))
            break
    if merged:
        out = [w for k, w in enumerate(words) if k not in used] + merged
    return out


@dataclass(slots=True)
class Grid:
    x0: float  # left edge of the stamp (mm)
    scale: float
    header_y: float | None  # centre of the change-table header row
    residual: float = 0.0

    def x(self, canonical: float) -> float:
        return self.x0 + self.scale * canonical

    @property
    def row(self) -> float:
        return ROW_MM * self.scale


def _fit(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Least-squares ``observed = x0 + s·canonical`` → (x0, s, max residual)."""
    if len(points) == 1:
        c, o = points[0]
        return o - c, 1.0, 0.0
    n = len(points)
    mc = sum(c for c, _ in points) / n
    mo = sum(o for _, o in points) / n
    var = sum((c - mc) ** 2 for c, _ in points)
    s = sum((c - mc) * (o - mo) for c, o in points) / var if var > 0 else 1.0
    if not 0.4 <= s <= 2.5:
        s = 1.0
    x0 = mo - s * mc
    res = max(abs(o - (x0 + s * c)) for c, o in points)
    return x0, s, res


@dataclass(slots=True)
class TitleBlockRead:
    """What the reader found on one page (``as_contract`` gives the contract TitleBlock)."""

    form: str  # "3" | "5" | "6" | "partial"
    labels: dict[str, list[Word]]
    grid: Grid | None
    sheet_raw: str | None = None
    sheet_number: int | str | None = None
    sheet_source: str | None = None  # TextSource of the words the sheet number was read from
    sheets_raw: str | None = None
    sheets_total: int | None = None
    stage_raw: str | None = None
    stage: str | None = None
    code_raw: str | None = None
    code: str | None = None
    code_basis: str | None = None
    code_word: Word | None = None
    sheet_title: str | None = None
    object_name: str | None = None
    organization: str | None = None
    change_rows: list[dict[str, str | None]] = field(default_factory=list)
    used: list[Word] = field(default_factory=list)
    confidences: dict[str, float] = field(default_factory=dict)
    anchors: dict[str, Word] = field(default_factory=dict)  # the STAGE/SHEET/SHEETS labels the values hang on
    title_cell: tuple[float, float, float, float] | None = None  # graph 4/5 cell (mm), forms 3 and 5
    cells_reread: list[str] = field(default_factory=list)

    def retry_cells(
        self, covers_mm: list[tuple[float, float, float, float]] = ()
    ) -> list[tuple[str, tuple[float, float, float, float]]]:
        """Cells worth a second OCR on a crop (mm boxes of the displayed page): a key value whose label was
        found but whose value was not read, and the sheet title when an image (the Exon QR) covers part of it.
        """
        out: list[tuple[str, tuple[float, float, float, float]]] = []
        g = self.grid
        s = g.scale if g else 1.0
        sheet = self.anchors.get("SHEET")
        if sheet is not None and self.sheet_number is None:
            if self.form == "6":
                half, depth = 5.0 * s, 9.0 * s
            else:
                half, depth = RIGHT_HALF_WIDTH["SHEET_R"] * s, 10.0 * s
            out.append(("sheet_number", (sheet.cx - half, sheet.y1 - 0.2, sheet.cx + half, sheet.y1 + depth)))
        stage = self.anchors.get("STAGE")
        if stage is not None and self.stage is None:
            half = RIGHT_HALF_WIDTH["STAGE"] * s
            out.append(("stage", (stage.cx - half, stage.y1 - 0.2, stage.cx + half, stage.y1 + 10.0 * s)))
        if self.title_cell is not None and covers_mm:
            x0, y0, x1, y1 = self.title_cell
            if any(
                min(x1, c[2]) - max(x0, c[0]) > 1.0 and min(y1, c[3]) - max(y0, c[1]) > 1.0 for c in covers_mm
            ):
                out.append(("sheet_title", self.title_cell))
        return out

    def apply_cell(self, name: str, words: list[Word], box: tuple[float, float, float, float]) -> bool:
        """Take the value of one re-OCR'd cell (words of the crop, displayed-page mm). True when it changed."""
        x0, y0, x1, y1 = box
        ws = [w for w in words if x0 <= w.cx <= x1 and y0 <= w.cy <= y1 and w.text.strip()]
        if not ws:
            return False
        text = _join(ws)
        changed = False
        if name == "sheet_number":
            num, f = parse_sheet(text)
            if num is not None:
                self.sheet_raw, self.sheet_number = text, num
                self.sheet_source = Counter(w.source for w in ws).most_common(1)[0][0]
                self.confidences["sheet_number"] = _conf(ws) * f * 0.95
                changed = True
        elif name == "stage":
            folded, stage = fold_stage(text)
            if stage is not None:
                self.stage_raw, self.stage = folded, stage
                self.confidences["stage"] = _conf(ws) * 0.95
                changed = True
        elif name == "sheet_title":
            title = _clean_title(text)
            if title and len(title) > len(self.sheet_title or ""):
                self.sheet_title = title
                changed = True
        if changed:
            self.used += ws
            self.cells_reread.append(name)
        return changed

    @property
    def revision(self) -> str | None:
        nums = [
            int(r["change_no"]) for r in self.change_rows if r.get("change_no") and r["change_no"].isdigit()
        ]
        return str(max(nums)) if nums else None

    @property
    def text_source(self) -> str | None:
        c = Counter(w.source for w in self.used)
        return c.most_common(1)[0][0] if c else None

    @property
    def confidence(self) -> float:
        keys = [k for k in ("sheet_number", "document_code", "stage") if k in self.confidences]
        vals = [self.confidences[k] for k in keys] or list(self.confidences.values())
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    def bbox_mm(self) -> tuple[float, float, float, float] | None:
        ws = self.used + [w for v in self.labels.values() for w in v]
        if not ws:
            return None
        return min(w.x0 for w in ws), min(w.y0 for w in ws), max(w.x1 for w in ws), max(w.y1 for w in ws)

    def as_contract(
        self, pdf_page_number: int, page_w_mm: float, page_h_mm: float, *, is_stamp_page: bool = False
    ) -> dict[str, Any]:
        out: dict[str, Any] = {"pdf_page_number": int(pdf_page_number)}
        box = self.bbox_mm()
        if box is not None:
            out["bbox"] = Word("", *box).norm_bbox(page_w_mm, page_h_mm)
        out.update(
            sheet_number=self.sheet_number,
            sheets_total=self.sheets_total,
            document_code_raw=self.code_raw,
            document_code=self.code,
            stage_raw=self.stage_raw,
            stage=self.stage,
            sheet_title=self.sheet_title,
            object_name=self.object_name,
            organization=self.organization,
            revision=self.revision,
            change_rows=self.change_rows,
            is_stamp_page=bool(is_stamp_page),
        )
        prov: dict[str, Any] = {"confidence": self.confidence}
        if self.text_source:
            prov["text_source"] = self.text_source
        layers = {w.layer for w in self.used if w.layer}
        prov["layer"] = sorted(layers)[0] if len(layers) == 1 else None
        out["provenance"] = prov
        out["fields_confidence"] = {k: round(min(1.0, max(0.0, v)), 4) for k, v in self.confidences.items()}
        return out

    @property
    def key_fields_found(self) -> int:
        return sum(x is not None for x in (self.sheet_number, self.code, self.stage))


# ── parsing helpers ─────────────────────────────────────────────────────────────────────────────

_DIGIT_FOLD = str.maketrans({"О": "0", "O": "0", "о": "0", "o": "0", "З": "3", "з": "3", "l": "1", "I": "1",
                             "|": "1", "б": "6", "Б": "6", "S": "5", "В": "8", "Ч": "4"})  # fmt: skip


def parse_sheet(text: str | None) -> tuple[int | str | None, float]:
    """Printed «Лист» value → (int, or string when not a plain number, confidence factor)."""
    if not text:
        return None, 0.0
    t = unicodedata.normalize("NFC", text).strip().strip(".,:;")
    t = re.sub(r"\s+", "", t)
    # a page field printed between dashes («- 4 -», «– 12 –») by text-document templates
    m = re.fullmatch(r"[-–—]+(\d{1,4})[-–—]+", t)
    if m:
        t = m.group(1)
    if not t:
        return None, 0.0
    if t.isdigit():
        return int(t), 1.0
    folded = t.translate(_DIGIT_FOLD)
    if folded.isdigit() and len(folded) <= 4:
        return int(folded), 0.8
    m = re.fullmatch(r"(\d{1,4})([а-яa-z]|\.\d{1,2})", t)
    if m:
        return t, 0.8
    return None, 0.0


def _join(words: list[Word]) -> str:
    """Reading-order text of a cell (lines top to bottom, words left to right)."""
    if not words:
        return ""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.cy):
        if lines and abs(lines[-1][0].cy - w.cy) < 0.5 * max(w.h, lines[-1][0].h):
            lines[-1].append(w)
        else:
            lines.append([w])
    return " ".join(" ".join(x.text for x in sorted(ln, key=lambda w: w.x0)) for ln in lines).strip()


def _lines(words: list[Word]) -> list[list[Word]]:
    """Group words into text lines: rows of one baseline (clustered on the centre line, so words arriving out
    of x-order join, e.g. an OCR «АНО» a little lower than «/150321/1-П-ИОС»), then split at wide gaps.
    Text-layer runs of one code may overlap by a fraction of a glyph («АНО» «/150321/1-» «П» «-ПЗУ»)."""
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.cy):
        for row in rows:
            cy = sum(x.cy for x in row) / len(row)
            if abs(cy - w.cy) < 0.45 * max(w.h, max(x.h for x in row)):
                row.append(w)
                break
        else:
            rows.append([w])
    out: list[list[Word]] = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        cur = [row[0]]
        for w in row[1:]:
            last = cur[-1]
            gap = w.x0 - last.x1
            if -max(1.0, 0.4 * max(w.h, last.h)) < gap < max(3.0, 1.5 * w.h):
                cur.append(w)
            else:
                out.append(cur)
                cur = [w]
        out.append(cur)
    return out


_CODE_LABEL = re.compile(r"(?i)^(?:шифр|обозначение|код)\s*[:.]?\s*")


def _compact_code(ws: list[Word], raw: bool = False) -> str:
    """One code line from its words: separators squeeze their spaces, and words closer than 0.45 of the
    glyph height are one token (OCR splits «АНО/150321/1-П-ИОС5.1.4» into «…-ИОС» + «5.1.4»)."""
    ws = sorted(ws, key=lambda w: w.x0)
    s = ""
    for i, w in enumerate(ws):
        t = w.raw if raw and w.raw else w.text
        if i:
            gap = w.x0 - ws[i - 1].x1
            s += "" if gap < 0.45 * max(w.h, ws[i - 1].h) else " "
        s += t
    s = re.sub(r"\s*([-/.])\s*", r"\1", s)
    return _CODE_LABEL.sub("", s.strip())  # «Шифр:АНО/150321/1-П-ИОС5.4.1» (F0170)


def _conf(ws: list[Word]) -> float:
    return min((w.conf for w in ws), default=0.0)


_ORG = re.compile(r"(?i)\b(ООО|ОАО|ЗАО|ПАО|АО|ГУП|ГБУ|ГКУ|ФГУП|МУП|ИП|АНО|НКО)\b|«")


def read_title_block(
    words: list[Word],
    page_w_mm: float,
    page_h_mm: float,
    *,
    registry: CodeRegistry | None = None,
    stage_hint: str | None = None,
) -> TitleBlockRead | None:
    """Read the stamp from the words of the page (only the bottom-right window is looked at)."""
    wx0, wy0 = page_w_mm - WINDOW_MM[0], page_h_mm - WINDOW_MM[1]
    # Upright words only; OCR returns 1–3 character tokens (a lone «2» in the «Лист» cell) as vertical
    # (angle 90, flattened box) because their detection box is taller than wide: those are kept.
    ws = [
        w for w in words
        if w.cx >= wx0 and w.cy >= wy0 and w.text.strip() and (w.angle % 360 == 0 or len(w.text.strip()) <= 3)
    ]  # fmt: skip
    if not ws:
        return None
    ws = _merge_split_labels(dedupe(ws))
    labels: dict[str, list[Word]] = {}
    for w in ws:
        k = label_kind(w.text)
        if k:
            labels.setdefault(k, []).append(w)
    label_ids = {id(w) for v in labels.values() for w in v}

    # ── header row of the change table: the row with the most distinct header kinds (lowest on a tie) ──
    header: list[Label] = []
    cands = [Label(k, w) for k in HEADER_COLUMNS for w in labels.get(k, [])]
    best_key: tuple[int, float] = (0, 0.0)
    for c in cands:
        row = [d for d in cands if abs(d.word.cy - c.word.cy) < max(1.5, 0.6 * c.word.h)]
        by_kind: dict[str, Label] = {}
        for d in sorted(row, key=lambda d: d.word.x0):
            by_kind.setdefault(d.kind, d)
        key = (len(by_kind), c.word.cy)
        if key > best_key:
            best_key, header = key, list(by_kind.values())
    if best_key[0] < 3:
        header = []
    header_ids = {id(d.word) for d in header}

    right = {
        k: [w for w in labels.get(k, []) if id(w) not in header_ids] for k in ("STAGE", "SHEET", "SHEETS")
    }
    grid: Grid | None = None
    if header:
        x0, s, res = _fit([(HEADER_CENTRES[d.kind], d.word.cx) for d in header])
        grid = Grid(x0, s, sum(d.word.cy for d in header) / len(header), res)
    # Стадия/Лист/Листов row (forms 3–5): with the change-table header known, «Стадия» is the row right under
    # it (header + 5 mm on every measured stamp), which keeps a «стадия» of the notes above out
    stage_cands = right["STAGE"]
    if grid is not None and grid.header_y is not None:
        stage_cands = [
            w for w in stage_cands if abs(w.cy - (grid.header_y + 5.0 * grid.scale)) <= 4.0 * grid.scale
        ]
    stage_lab = max(stage_cands, key=lambda w: w.cy, default=None)
    sheet_lab: Word | None = None
    sheets_lab: Word | None = None
    if stage_lab is not None:
        same = lambda w: abs(w.cy - stage_lab.cy) < max(2.0, 0.8 * stage_lab.h)  # noqa: E731
        sheet_lab = min(
            (w for w in right["SHEET"] if same(w) and w.cx > stage_lab.cx), key=lambda w: w.cx, default=None
        )
        sheets_lab = min(
            (w for w in right["SHEETS"] if same(w) and w.cx > stage_lab.cx), key=lambda w: w.cx, default=None
        )
    else:
        # «Лист Листов» without «Стадия» (title/cover forms) or the lone «Лист» of form 6
        if right["SHEETS"]:
            sheets_lab = max(right["SHEETS"], key=lambda w: w.cy)
            sheet_lab = min(
                (w for w in right["SHEET"] if abs(w.cy - sheets_lab.cy) < max(2.0, 0.8 * sheets_lab.h) and w.cx < sheets_lab.cx),
                key=lambda w: sheets_lab.cx - w.cx,
                default=None,
            )  # fmt: skip
        elif right["SHEET"]:
            sheet_lab = max(right["SHEET"], key=lambda w: w.cx)
    # Grid from the right block when the header is missing (or to cross-check the scale)
    if grid is None:
        pts = []
        if stage_lab is not None:
            pts.append((RIGHT_CENTRES["STAGE"], stage_lab.cx))
        if sheet_lab is not None and stage_lab is not None:
            pts.append((RIGHT_CENTRES["SHEET_R"], sheet_lab.cx))
        if sheets_lab is not None and stage_lab is not None:
            pts.append((RIGHT_CENTRES["SHEETS"], sheets_lab.cx))
        if len(pts) >= 2:
            x0, s, res = _fit(pts)
            grid = Grid(x0, s, None, res)
        elif len(pts) == 1:
            grid = Grid(pts[0][1] - pts[0][0], 1.0, None, 0.0)
    # «Лист» label unread in the «Стадия | Лист | Листов» row (OCR «Лисm» with a stray glyph, a label lost in
    # a seal): its cell is placed from the fitted grid, between «Стадия» and «Листов».
    virtual_sheet = False
    if stage_lab is not None and sheet_lab is None and grid is not None and grid.residual < 3:
        if (
            sheets_lab is not None
        ):  # the ГОСТ ratio between the two labels (right blocks are often compressed)
            t = (RIGHT_CENTRES["SHEET_R"] - RIGHT_CENTRES["STAGE"]) / (
                RIGHT_CENTRES["SHEETS"] - RIGHT_CENTRES["STAGE"]
            )
            cx = stage_lab.cx + t * (sheets_lab.cx - stage_lab.cx)
        else:
            cx = stage_lab.cx + (RIGHT_CENTRES["SHEET_R"] - RIGHT_CENTRES["STAGE"]) * grid.scale
        if cx > stage_lab.x1 and (sheets_lab is None or cx < sheets_lab.x0):
            hw = 3.0 * grid.scale
            sheet_lab = Word("Лист", cx - hw, stage_lab.y0, cx + hw, stage_lab.y1, stage_lab.source, 0.5)
            virtual_sheet = True

    form = "partial"
    if stage_lab is not None:
        form = "3"
    elif sheet_lab is not None and header and sheets_lab is None:
        form = "6"
    elif sheets_lab is not None:
        form = "5"
    n_anchor = len(header) + sum(x is not None for x in (stage_lab, sheet_lab, sheets_lab)) - virtual_sheet
    tb = TitleBlockRead(form=form, labels={k: v for k, v in labels.items()}, grid=grid)
    tb.anchors = {
        k: v for k, v in (("STAGE", stage_lab), ("SHEET", sheet_lab), ("SHEETS", sheets_lab)) if v is not None
    }

    scale = grid.scale if grid else 1.0
    free = [w for w in ws if id(w) not in label_ids]

    def below(lab: Word, half_w: float, depth: float, cx: float | None = None) -> list[Word]:
        c = lab.cx if cx is None else cx
        return [
            w for w in free
            if lab.y1 - 0.3 < w.cy < lab.y1 + depth and abs(w.cx - c) <= half_w and w.y0 > lab.cy
        ]  # fmt: skip

    # ── Стадия / Лист / Листов values ──
    # Values sit under their labels (labels are centred in their cells). The header-fitted grid is not used
    # here: non-standard stamps widen the change table and compress the right block (Новослободская F0104 p8:
    # change-table scale 1.13, «Стадия» 6 mm left of its ГОСТ place). A cell is at most half-way to the next label.
    row = sorted((w for w in (stage_lab, sheet_lab, sheets_lab) if w is not None), key=lambda w: w.cx)

    def half_width(lab: Word, canonical: float) -> float:
        gaps = [abs(o.cx - lab.cx) for o in row if o is not lab]
        return min([canonical * scale] + [0.5 * g for g in gaps if g > 1.0])

    if stage_lab is not None:
        vals = below(stage_lab, half_width(stage_lab, RIGHT_HALF_WIDTH["STAGE"]), 11.0 * scale)
        if vals:
            # stored homoglyph-folded: OCR's Latin «P» for a printed «Р» is an OCR artefact (F0138 p3)
            folded, stage = fold_stage(_join(vals))
            if stage is not None or (folded and len(folded) <= 3):  # not a line of notes («НЕ МЕНЕЕ»)
                tb.stage_raw = folded
                tb.stage = stage
                tb.used += vals
                tb.confidences["stage"] = _conf(vals) * (1.0 if stage else 0.5)
    if sheet_lab is not None:
        if form == "6":
            half, depth = 5.0 * scale, 10.0 * scale
        else:
            half, depth = half_width(sheet_lab, RIGHT_HALF_WIDTH["SHEET_R"]), 11.0 * scale
        vals = below(sheet_lab, half, depth)
        if vals:
            tb.sheet_raw = _join(vals)
            num, f = parse_sheet(tb.sheet_raw)
            if num is not None:
                tb.sheet_number = num
                tb.sheet_source = Counter(w.source for w in vals).most_common(1)[0][0]
                tb.used += vals
                tb.confidences["sheet_number"] = _conf(vals) * f * (0.9 if virtual_sheet else 1.0)
    if sheets_lab is not None:
        vals = below(sheets_lab, half_width(sheets_lab, RIGHT_HALF_WIDTH["SHEETS"]), 11.0 * scale)
        if vals:
            tb.sheets_raw = _join(vals)
            num, f = parse_sheet(tb.sheets_raw)
            if isinstance(num, int) and num >= 1:
                tb.sheets_total = num
                tb.used += vals
                tb.confidences["sheets_total"] = _conf(vals) * f

    # ── Изм. rows above the header ──
    if grid is not None and grid.header_y is not None:
        max_rows = 2 if form == "6" else 5
        for k in range(1, max_rows + 1):
            yc = grid.header_y - k * grid.row
            band = [w for w in free if abs(w.cy - yc) < 0.5 * grid.row and grid.x(-1) <= w.cx <= grid.x(66)]
            if not band:
                continue
            cells: dict[str, list[Word]] = {c: [] for c in HEADER_COLUMNS}
            for w in band:
                rel = (w.cx - grid.x0) / grid.scale
                for ci, name in enumerate(HEADER_COLUMNS):
                    if HEADER_EDGES[ci] - 0.5 <= rel < HEADER_EDGES[ci + 1] + (0.5 if ci == 5 else 0):
                        cells[name].append(w)
                        break
            txt = {c: (_join(v) or None) for c, v in cells.items()}
            change_no = txt["CHANGE"]
            if change_no:
                change_no = change_no.translate(_DIGIT_FOLD) if len(change_no) <= 3 else change_no
            if txt["SHEET"] and not all(w.source.startswith("TEXT_LAYER") for w in cells["SHEET"]):
                txt["SHEET"] = fold_change_kind(txt["SHEET"])
            doc_no, date = txt["DOCNO"], txt["DATE"]
            plausible = bool(change_no and re.fullmatch(r"\d{1,2}", change_no)) or bool(
                (doc_no and re.search(r"\d", doc_no)) and (date and re.search(r"\d", date))
            )
            if not plausible:
                continue
            tb.change_rows.append(
                {"change_no": change_no, "count": txt["COUNT"], "sheet": txt["SHEET"], "doc_no": doc_no,
                 "date": date, "note": None}
            )  # fmt: skip
            tb.used += [w for c in HEADER_COLUMNS if c != "SIGN" for w in cells[c]]
        tb.change_rows.reverse()  # rows were collected upwards from the header: print order is top to bottom
        if tb.change_rows:
            row_words = [w for w in tb.used if w.source != "TEXT_LAYER"]
            tb.confidences["change_rows"] = (
                sum(w.conf for w in row_words) / len(row_words) if row_words else 1.0
            )

    # ── document code (graph 1) ──
    left_limit = grid.x(64) if grid is not None else wx0
    code_zone = [w for w in free if w.cx > left_limit]
    if stage_lab is not None:
        code_zone = [w for w in code_zone if w.cy < stage_lab.y0 + 1.0 or form != "3"]
    # the шифр is inside the stamp: drawing text above it (a topographic plan's own «A-XVI-16-02» sheet
    # nomenclature, F0148 p371) is not a candidate. Forms 3/5: ≤ 28 mm above the «Стадия» labels; form 6:
    # the 15 mm band of the change-table header.
    stamp_top = None
    if stage_lab is not None:
        stamp_top = stage_lab.y0 - 28.0 * scale
    elif grid is not None and grid.header_y is not None:
        stamp_top = grid.header_y - 17.0 * scale
    if stamp_top is not None:
        code_zone = [w for w in code_zone if w.cy >= stamp_top]
    code_zone = [w for w in code_zone if not _garbled(w.text)]
    cand: list[tuple[float, list[Word]]] = []
    for ln in _lines(code_zone):
        text = _compact_code(ln)
        if looks_like_code(text):
            cand.append((max(w.h for w in ln), ln))
        else:
            for w in ln:
                if looks_like_code(_CODE_LABEL.sub("", w.text)):
                    cand.append((w.h, [w]))
    if cand:
        cand.sort(key=lambda c: (-round(c[0], 1), c[1][0].cy))
        _, ln = cand[0]
        tb.code_raw = _compact_code(ln, raw=True)
        if all(w.source.startswith("TEXT_LAYER") for w in ln):
            # a text layer is what the document says: no correction (as AG-02A's post-correction, OCR only)
            tb.code, tb.code_basis, conf_factor = unicodedata.normalize("NFC", tb.code_raw), "text_layer", 1.0
        else:
            # the file stage decides the stage-letter fold; the stamp's own «Стадия» only when it is unknown
            res = (registry or CodeRegistry()).resolve(tb.code_raw, stage=stage_hint or tb.stage)
            tb.code, tb.code_basis, conf_factor = res.code, res.basis, res.confidence
        tb.code_word = Word(tb.code, min(w.x0 for w in ln), min(w.y0 for w in ln), max(w.x1 for w in ln),
                            max(w.y1 for w in ln), ln[0].source, _conf(ln))  # fmt: skip
        tb.used += ln
        tb.confidences["document_code"] = _conf(ln) * conf_factor

    # ── titles ──
    code_ids = {id(w) for w in (tb.used or [])}
    rest = [w for w in free if id(w) not in code_ids and not re.match(r"(?i)^формат", w.text)]
    if stage_lab is not None and grid is not None:
        mid_l, mid_r = grid.x(65) - 1.0, stage_lab.x0 - 0.5
        bottom = page_h_mm - 4.0  # «Формат: A1» sits under the frame
        # Form 3 has graph 2 (object) between the шифр and the Стадия row and graph 3 (15 mm) left of the
        # Стадия block; form 5 has the title (graph 5) right under the шифр, left of the Стадия block.
        form3 = tb.code_word is None or stage_lab.y0 - tb.code_word.y1 > 10.0 * scale
        tb.form = "3" if form3 else "5"
        split = (
            stage_lab.y0 - 0.8 + 15.0 * scale if form3 else (tb.code_word.y1 + 0.3 if tb.code_word else 0.0)
        )
        g5 = [w for w in rest if mid_l <= w.cx <= mid_r and split < w.cy < bottom]
        tb.title_cell = (mid_l, split, mid_r, bottom)
        if g5 and not any(_garbled(w.text) for w in g5):  # unmapped glyphs: no title rather than a torso
            tb.sheet_title = _clean_title(_join(g5))
            tb.used += g5
        org_split = stage_lab.y0 + 12.0 * scale
        g9 = [w for w in rest if w.cx > stage_lab.x0 - 0.5 and org_split < w.cy < bottom]
        if g9 and not any(_garbled(w.text) for w in g9):
            lines = [
                _org_fold(" ".join(w.text for w in ln)) for ln in sorted(_lines(g9), key=lambda ln: ln[0].cy)
            ]
            marked = [i for i, ln in enumerate(lines) if _ORG.search(ln)]
            keep = lines[: marked[0] + 1] if marked else lines
            tb.organization = _clean_title(" ".join(keep))
            if tb.organization and not all(w.source.startswith("TEXT_LAYER") for w in g9):
                tb.organization = balance_org_quotes(tb.organization)
        if tb.code_word is not None and form3:
            g2 = [w for w in rest if w.cx > grid.x(64) and tb.code_word.y1 - 0.5 < w.cy < stage_lab.y0 - 0.5]
            if g2 and not any(_garbled(w.text) for w in g2):
                tb.object_name = _clean_title(_join(g2))
    # A stamp has labels: a code-shaped footer alone («Предложение No KR22-031295/1», F0201 p173+) is not one.
    if n_anchor == 0:
        return None
    if n_anchor < 2 and tb.code is None and tb.sheet_number is None:
        return None
    if tb.key_fields_found == 0 and n_anchor < 3:
        return None
    return tb


def _garbled(text: str) -> bool:
    """A word with a glyph the text layer could not map (mojibake, control or combining characters)."""
    from inspector_docproc.repair import is_suspicious

    return any(is_suspicious(c) for c in text)


def _org_fold(text: str) -> str:
    """OCR reads the legal-form letters as digits («000 «ТСП»» for «ООО «ТСП»»)."""
    return re.sub(r"^(000|0A0|3A0|0АО|ЗАО|ПA0|A0)(?=\s|«|$)", lambda m: m.group(1).translate(_ORG_FOLD), text)


_ORG_FOLD = str.maketrans({"0": "О", "A": "А", "3": "З"})
_LEGAL_FORM = re.compile(r"^(ООО|ОАО|ЗАО|ПАО|АО|ГУП|ГБУ|ГКУ|ФГУП|МУП|АНО|НКО)\s+(\S.*)$")


def balance_org_quotes(text: str) -> str:
    """«ООО ТСП»», «ООО «ТСП», «ООО ТСП» (OCR drops thin guillemets) → «ООО «ТСП»». OCR text only: a text layer
    is what the stamp prints. A name that already has balanced quotes, or no legal form, is returned as is."""
    m = _LEGAL_FORM.match(text.strip())
    if not m:
        return text
    form, name = m.group(1), m.group(2).strip()
    if name.count("«") == name.count("»") and name.count("«") > 0:
        return text
    core = name.strip("«»\"'“”„ ").strip()
    if not core or "«" in core or "»" in core:
        return text
    return f"{form} «{core}»"


# Kind of an «Изм.» row as printed in its «Лист» column (ГОСТ Р 21.101 §7): OCR reads «Зам.» as «3ам.».
_CHANGE_KINDS = {"зам": "Зам", "нов": "Нов", "аннул": "Аннул", "изм": "Изм"}


def fold_change_kind(text: str) -> str:
    """«3ам.» → «Зам.», «Hов.» → «Нов.»; anything else (a sheet number «2», «-») is returned unchanged."""
    t = text.strip()
    core = _fold(_norm(t))
    kind = _CHANGE_KINDS.get(core)
    if kind is None:
        return text
    return kind + ("." if t.endswith(".") else "")


def _clean_title(text: str) -> str | None:
    t = re.sub(r"\s+", " ", text).strip()
    return t or None
