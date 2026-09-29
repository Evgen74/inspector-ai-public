"""Page input for the table parsers: words (PageTokens of the run, else the PDF text layer) and rulings.

Words come from AG-02A's PageTokens when the run has them (text layer + OCR of outlined text and scans);
otherwise straight from the PDF text layer (``inspector_docproc.textlayer``), which is enough for the
vector tables of PD/RD volumes. Rulings (table lines) come from the PDF vector content; on scans without
vector lines a raster detector (morphological opening on a 100-dpi render) finds them.

Content rotation: when most words of a page read at 90/180/270° (a scan rotated inside the image, or a
drawing sheet stored sideways), words and rulings are turned upright for parsing; ``norm_bbox`` maps every
box back to the displayed page, so evidence stays in PDF_VISIBLE_ROTATED_TL_V1 space.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.geometry import clamp01
from inspector_tables.text import Box, Ruling, Word, squash

MIN_RULING_PT = 4.0  # shorter segments are glyph strokes or junction dots
THIN_PT = 2.6  # a filled rectangle thinner than this is a line
MERGE_GAP_PT = 1.6  # collinear pieces closer than this are one ruling
AXIS_TOL_PT = 0.7


@dataclass(slots=True)
class PageData:
    file_id: str
    page_no: int
    width: float  # upright working space, pt
    height: float
    words: list[Word]
    text_source: str = "TEXT_LAYER"
    page_class: str | None = None
    quality_flag: str | None = None
    from_tokens: bool = False
    rotation_k: int = 0  # quarter turns applied to make content upright (clockwise)
    disp_width: float = 0.0  # displayed page size, pt
    disp_height: float = 0.0
    _page: Any = None  # pymupdf.Page for lazy vector rulings
    _rulings: tuple[list[Ruling], list[Ruling]] | None = None
    _raster: tuple[list[Ruling], list[Ruling]] | None = None
    _raster_ok: bool = True
    notes: list[str] = field(default_factory=list)
    active: str = "vector"  # which ruling set rulings() returns: "vector" | "raster"
    _diagonals: list | None = None  # leader-line segments (assertions.diagonal_segments)
    _diag_index: dict | None = None  # their endpoint grid index
    _drawings: list | None = None  # page.get_cdrawings(), shared by rulings and leader lines

    def drawings(self) -> list:
        """The page's vector paths (``get_cdrawings``), read once: it costs ~1 s on a heavy CAD sheet."""
        if self._drawings is None:
            try:
                self._drawings = self._page.get_cdrawings() if self._page is not None else []
            except Exception:  # damaged content stream
                self._drawings = []
        return self._drawings

    # ── geometry ──
    def norm_bbox(self, box: Box | tuple[float, float, float, float]) -> list[float]:
        b = box if isinstance(box, Box) else Box(*box)
        nb = [clamp01(b.x0 / self.width), clamp01(b.y0 / self.height), clamp01(b.x1 / self.width),
              clamp01(b.y1 / self.height)]  # fmt: skip
        if self.rotation_k:
            from inspector_common.geometry import rotate_norm_bbox

            nb = rotate_norm_bbox(nb, -self.rotation_k, decimals=None)
        return [round(v, 5) for v in nb]

    def words_in(self, box: Box, *, by_center: bool = True) -> list[Word]:
        if by_center:
            return [w for w in self.words if box.x0 <= w.cx <= box.x1 and box.y0 <= w.cy <= box.y1]
        return [
            w for w in self.words if w.x0 >= box.x0 and w.x1 <= box.x1 and w.y0 >= box.y0 and w.y1 <= box.y1
        ]

    @property
    def text(self) -> str:
        from inspector_tables.text import group_lines

        return "\n".join(ln.text for ln in group_lines(self.words))

    # ── rulings ──
    def image_share(self) -> float:
        """Share of the page covered by embedded images (0 when unknown)."""
        if self._page is None:
            return 0.0
        try:
            area = 0.0
            for info in self._page.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
            return min(1.0, area / max(self.disp_width * self.disp_height, 1.0))
        except Exception:
            return 0.0

    def ruling_sets(self) -> list[str]:
        """Ruling sources worth trying: vector always; raster when images cover a large part of the page
        (a table pasted as a picture inside a vector sheet, F0171 p79–81) or when the page is a scan."""
        sets = ["vector"]
        if (
            self._page is not None
            and self._raster_ok
            and (self.image_share() > 0.2 or self.page_class in ("RASTER_SCAN", "RASTER_HIDDEN_OCR"))
        ):
            sets.append("raster")
        return sets

    def rulings(self) -> tuple[list[Ruling], list[Ruling]]:
        """(vertical, horizontal) rulings of the active set, in working space."""
        if self.active == "raster":
            if self._raster is None:
                self._raster = (
                    raster_rulings(self._page, self.rotation_k, dpi=150)
                    if self._page is not None
                    else ([], [])
                )
            return self._raster
        if self._rulings is None:
            v: list[Ruling] = []
            h: list[Ruling] = []
            if self._page is not None:
                v, h = vector_rulings(self._page, self.drawings())
                if self.rotation_k:
                    v, h = _rotate_rulings(v, h, self.rotation_k, self.disp_width, self.disp_height)
                if len(v) + len(h) < 4 and self._raster_ok and self.page_class not in ("VECTOR",):
                    v, h = raster_rulings(self._page, self.rotation_k)
                    if v or h:
                        self.notes.append("raster_rulings")
            self._rulings = (v, h)
        return self._rulings


# ── vector rulings ────────────────────────────────────────────────────────────────────────────────


def _merge(rulings: list[Ruling]) -> list[Ruling]:
    """Collinear pieces → one ruling: cluster by position (chain within AXIS_TOL_PT, cluster span capped),
    then merge overlapping or near-touching intervals inside each cluster."""
    out: list[Ruling] = []
    ordered = sorted(rulings, key=lambda r: r.pos)
    i = 0
    while i < len(ordered):
        j = i + 1
        while (
            j < len(ordered)
            and ordered[j].pos - ordered[j - 1].pos <= AXIS_TOL_PT
            and ordered[j].pos - ordered[i].pos <= 2 * AXIS_TOL_PT
        ):
            j += 1
        cluster = sorted(ordered[i:j], key=lambda r: r.lo)
        cur: list[Ruling] = [cluster[0]]
        for r in cluster[1:]:
            lo = min(x.lo for x in cur)
            hi = max(x.hi for x in cur)
            if r.lo <= hi + MERGE_GAP_PT:
                cur.append(r)
            else:
                out.append(_fuse(cur, lo, hi))
                cur = [r]
        out.append(_fuse(cur, min(x.lo for x in cur), max(x.hi for x in cur)))
        i = j
    return [r for r in out if r.length >= MIN_RULING_PT]


def _fuse(parts: list[Ruling], lo: float, hi: float) -> Ruling:
    total = sum(max(p.length, 0.01) for p in parts)
    pos = sum(p.pos * max(p.length, 0.01) for p in parts) / total
    return Ruling(parts[0].vertical, pos, lo, hi, max(p.width for p in parts))


def _segment(
    x0: float, y0: float, x1: float, y1: float, width: float, v: list[Ruling], h: list[Ruling]
) -> None:
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    if dx <= AXIS_TOL_PT and dy >= MIN_RULING_PT:
        v.append(Ruling(True, (x0 + x1) / 2, min(y0, y1), max(y0, y1), width))
    elif dy <= AXIS_TOL_PT and dx >= MIN_RULING_PT:
        h.append(Ruling(False, (y0 + y1) / 2, min(x0, x1), max(x0, x1), width))


def _rect(x0: float, y0: float, x1: float, y1: float, stroked: bool, width: float, v: list[Ruling],
          h: list[Ruling]) -> None:  # fmt: skip
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    w, hh = x1 - x0, y1 - y0
    if w <= THIN_PT and hh >= MIN_RULING_PT:
        v.append(Ruling(True, (x0 + x1) / 2, y0, y1, w))
    elif hh <= THIN_PT and w >= MIN_RULING_PT:
        h.append(Ruling(False, (y0 + y1) / 2, x0, x1, hh))
    elif stroked and w >= MIN_RULING_PT and hh >= MIN_RULING_PT:
        v.extend([Ruling(True, x0, y0, y1, width), Ruling(True, x1, y0, y1, width)])
        h.extend([Ruling(False, y0, x0, x1, width), Ruling(False, y1, x0, x1, width)])


def vector_rulings(page: Any, drawings: list | None = None) -> tuple[list[Ruling], list[Ruling]]:
    """Axis-aligned lines of the page in displayed points (lines, thin filled rects, stroked rects, quads).

    Hot path on CAD sheets (150k paths, 3.7M segments on F0201 p18): the filter runs on raw coordinates
    (a /Rotate of quarter turns keeps segments axis-aligned) and only survivors are transformed, with plain
    arithmetic instead of pymupdf.Point objects."""
    m = page.rotation_matrix
    a, b, c, d, e, f = m.a, m.b, m.c, m.d, m.e, m.f
    v: list[Ruling] = []
    h: list[Ruling] = []
    if drawings is None:
        try:
            drawings = page.get_cdrawings()
        except Exception:  # damaged content stream: no rulings, the row aligner still works
            return [], []
    tol = AXIS_TOL_PT
    min_len = MIN_RULING_PT

    def tr(x: float, y: float) -> tuple[float, float]:
        return a * x + c * y + e, b * x + d * y + f

    for dr in drawings:
        items = dr.get("items", ())
        if not items:
            continue
        stroked = "s" in (dr.get("type") or "")
        width = float(dr.get("width") or 0.0)
        for it in items:
            kind = it[0]
            if kind == "l":
                (x0, y0), (x1, y1) = it[1], it[2]
                dx = x1 - x0 if x1 > x0 else x0 - x1
                dy = y1 - y0 if y1 > y0 else y0 - y1
                if (dx <= tol and dy >= min_len) or (dy <= tol and dx >= min_len):
                    X0, Y0 = tr(x0, y0)
                    X1, Y1 = tr(x1, y1)
                    _segment(X0, Y0, X1, Y1, width, v, h)
            elif kind == "re":
                x0, y0, x1, y1 = it[1]
                if abs(x1 - x0) < min_len and abs(y1 - y0) < min_len:
                    continue
                X0, Y0 = tr(x0, y0)
                X1, Y1 = tr(x1, y1)
                _rect(X0, Y0, X1, Y1, stroked, width, v, h)
            elif kind == "qu":
                pts = it[1]
                xs = [q[0] for q in pts]
                ys = [q[1] for q in pts]
                if max(xs) - min(xs) < min_len and max(ys) - min(ys) < min_len:
                    continue
                # axis-aligned quads only (rectangles drawn as quads by CAD exporters)
                if len({round(x, 1) for x in xs}) <= 2 and len({round(y, 1) for y in ys}) <= 2:
                    X0, Y0 = tr(min(xs), min(ys))
                    X1, Y1 = tr(max(xs), max(ys))
                    _rect(X0, Y0, X1, Y1, stroked, width, v, h)
    return _merge(v), _merge(h)


def _rotate_rulings(
    v: list[Ruling], h: list[Ruling], k: int, w: float, hh: float
) -> tuple[list[Ruling], list[Ruling]]:
    """Displayed-space rulings → working space turned ``k`` quarter turns clockwise."""
    out_v: list[Ruling] = []
    out_h: list[Ruling] = []
    for r in v + h:
        box = (r.pos, r.lo, r.pos, r.hi) if r.vertical else (r.lo, r.pos, r.hi, r.pos)
        x0, y0, x1, y1 = _rotate_box(box, k, w, hh)
        _segment(x0, y0, x1, y1, r.width, out_v, out_h)
    return _merge(out_v), _merge(out_h)


def _rotate_box(
    box: tuple[float, float, float, float], k: int, w: float, h: float
) -> tuple[float, float, float, float]:
    """Rotate a box in a w×h page by k quarter turns clockwise (points)."""
    x0, y0, x1, y1 = box
    pts = [(x0, y0), (x1, y1)]
    cw, ch = w, h
    for _ in range(k % 4):
        pts = [(ch - py, px) for px, py in pts]
        cw, ch = ch, cw
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# ── raster rulings (scans) ────────────────────────────────────────────────────────────────────────


def raster_rulings(page: Any, rotation_k: int = 0, dpi: int = 100) -> tuple[list[Ruling], list[Ruling]]:
    """Table lines of a scanned page: morphological opening with long kernels on a binarized render."""
    import cv2
    import numpy as np

    pix = page.get_pixmap(dpi=dpi, colorspace="gray")
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    if rotation_k % 4:
        img = np.ascontiguousarray(np.rot90(img, k=-(rotation_k % 4)))
    bw = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 12)
    scale = 72.0 / dpi
    out_v: list[Ruling] = []
    out_h: list[Ruling] = []
    hk = max(30, img.shape[1] // 40)
    vk = max(30, img.shape[0] // 60)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (hk, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk)))
    for mask, vertical in ((horiz, False), (vert, True)):
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            x, y, w, h, _area = stats[i]
            if vertical and h >= vk and w <= 8:
                out_v.append(Ruling(True, (x + w / 2) * scale, y * scale, (y + h) * scale, w * scale))
            elif not vertical and w >= hk and h <= 8:
                out_h.append(Ruling(False, (y + h / 2) * scale, x * scale, (x + w) * scale, h * scale))
    return _merge(out_v), _merge(out_h)


# ── loading ───────────────────────────────────────────────────────────────────────────────────────


def _dominant_rotation(words: list[Word]) -> int:
    """Quarter turns (clockwise) that make most of the text horizontal; 0 when already upright."""
    weights: Counter[int] = Counter()
    for w in words:
        weights[w.angle % 360] += max(len(w.text), 1)
    total = sum(weights.values())
    if not total:
        return 0
    angle, mass = weights.most_common(1)[0]
    if angle == 0 or mass < 0.6 * total:
        return 0
    return {90: 3, 180: 2, 270: 1}.get(angle, 0)


def _rotate_words(words: list[Word], k: int, w: float, h: float) -> list[Word]:
    out = []
    for wd in words:
        x0, y0, x1, y1 = _rotate_box((wd.x0, wd.y0, wd.x1, wd.y1), k, w, h)
        out.append(Word(wd.text, x0, y0, x1, y1, wd.source, wd.conf, (wd.angle + 90 * k) % 360, wd.size))
    return out


def _dedupe_ocr_pairs(words: list[Word]) -> list[Word]:
    """Two OCR reads of one box (full-page OCR and the layer-isolated re-read): keep the more confident.
    Duplicates share their text, so only tokens with equal text are compared (linear in practice)."""
    by_text: dict[str, list[Word]] = {}
    for w in words:
        if not w.source.startswith("TEXT_LAYER"):
            by_text.setdefault(w.text, []).append(w)
    drop: set[int] = set()
    for group in by_text.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda w: -w.conf)
        kept: list[Word] = []
        for w in group:
            if any(
                min(k.x1, w.x1) - max(k.x0, w.x0) > 0
                and min(k.y1, w.y1) - max(k.y0, w.y0) > 0
                and (min(k.x1, w.x1) - max(k.x0, w.x0)) * (min(k.y1, w.y1) - max(k.y0, w.y0))
                > 0.5 * min(k.w * k.h, w.w * w.h)
                for k in kept
            ):
                drop.add(id(w))
            else:
                kept.append(w)
    return [w for w in words if id(w) not in drop]


def dedupe_ocr(words: list[Word]) -> list[Word]:
    """Drop OCR tokens that re-read a text-layer word (the text layer is exact; OCR only fills its gaps).

    An OCR token is a duplicate when its centre lies inside a text-layer word box (grown by 30 % of its
    height) or when the two boxes overlap by more than half of the smaller one. Identical OCR reads of the
    same box are collapsed too."""
    words = _dedupe_ocr_pairs(words)
    tl = [w for w in words if w.source.startswith("TEXT_LAYER")]
    if not tl:
        return words
    import numpy as np

    arr = np.array([[w.x0, w.y0, w.x1, w.y1] for w in tl])
    pad = (arr[:, 3] - arr[:, 1]) * 0.3
    out = []
    for w in words:
        if w.source.startswith("TEXT_LAYER"):
            out.append(w)
            continue
        cx, cy = w.cx, w.cy
        inside = (
            (arr[:, 0] - pad <= cx)
            & (cx <= arr[:, 2] + pad)
            & (arr[:, 1] - pad <= cy)
            & (cy <= arr[:, 3] + pad)
        )
        if inside.any():
            continue
        ix = np.clip(np.minimum(arr[:, 2], w.x1) - np.maximum(arr[:, 0], w.x0), 0, None)
        iy = np.clip(np.minimum(arr[:, 3], w.y1) - np.maximum(arr[:, 1], w.y0), 0, None)
        inter = ix * iy
        small = np.minimum((arr[:, 2] - arr[:, 0]) * (arr[:, 3] - arr[:, 1]), max(w.w * w.h, 1e-6))
        if (inter > 0.5 * small).any():
            continue
        out.append(w)
    return out


def page_from_tokens(doc_json: dict[str, Any], page: Any = None) -> PageData:
    """PageData from a PageTokens document (contract page_tokens)."""
    pg = doc_json["page"]
    width, height = float(pg["width_pt"]), float(pg["height_pt"])
    words: list[Word] = []
    for t in doc_json.get("tokens", []):
        text = squash(t.get("text") or "")
        if not text or t.get("quality_flag") == "ABSTAIN":
            continue
        x0, y0, x1, y1 = t["bbox"]
        words.append(
            Word(
                text,
                x0 * width,
                y0 * height,
                x1 * width,
                y1 * height,
                t.get("source") or "OCR",
                float(t.get("conf") or 0.0),
                int(t.get("angle") or 0),
                float(t.get("font_size_pt") or 0.0),
            )
        )
    words = dedupe_ocr(words)
    return _finish(
        PageData(
            file_id=doc_json["file_id"],
            page_no=int(doc_json["page_no"]),
            width=width,
            height=height,
            words=words,
            text_source=doc_json.get("text_source") or "TEXT_LAYER",
            page_class=doc_json.get("page_class"),
            quality_flag=doc_json.get("quality_flag"),
            from_tokens=True,
            disp_width=width,
            disp_height=height,
            _page=page,
        )
    )


def page_from_pdf(page: Any, file_id: str, page_no: int) -> PageData:
    """PageData from the PDF text layer (visible words only; garbled layers are the router's business)."""
    from inspector_docproc.textlayer import extract_text_layer

    width, height = float(page.rect.width), float(page.rect.height)
    layer = extract_text_layer(page)
    words = [
        Word(
            squash(w.text),
            w.bbox[0] * width,
            w.bbox[1] * height,
            w.bbox[2] * width,
            w.bbox[3] * height,
            "TEXT_LAYER",
            1.0,
            w.angle,
            w.size,
        )
        for w in layer.visible_words
        if squash(w.text)
    ]
    pd = PageData(
        file_id=file_id,
        page_no=page_no,
        width=width,
        height=height,
        words=words,
        text_source="TEXT_LAYER",
        page_class="VECTOR" if words else None,
        disp_width=width,
        disp_height=height,
        _page=page,
    )
    return _finish(pd)


def _finish(pd: PageData) -> PageData:
    k = _dominant_rotation(pd.words)
    if k:
        pd.words = _rotate_words(pd.words, k, pd.disp_width, pd.disp_height)
        pd.rotation_k = k
        if k % 2:
            pd.width, pd.height = pd.disp_height, pd.disp_width
    return pd


def load_tokens_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError):
        return None


class PageSource:
    """Opens pages of one PDF, preferring the run's PageTokens (``tokens/<file_id>/p00017.json.gz``)."""

    def __init__(self, doc: Any, file_id: str, tokens_dir: Path | None = None) -> None:
        self.doc = doc
        self.file_id = file_id
        self.tokens_dir = tokens_dir

    def token_path(self, page_no: int) -> Path | None:
        if self.tokens_dir is None:
            return None
        p = self.tokens_dir / f"p{page_no:05d}.json.gz"
        return p if p.is_file() else None

    def has_tokens(self, page_no: int) -> bool:
        return self.token_path(page_no) is not None

    def page(self, page_no: int) -> PageData:
        tp = self.token_path(page_no)
        pdf_page = self.doc[page_no - 1]
        if tp is not None:
            doc_json = load_tokens_json(tp)
            if doc_json is not None:
                return page_from_tokens(doc_json, pdf_page)
        return page_from_pdf(pdf_page, self.file_id, page_no)

    def quick_text(self, page_no: int) -> str:
        """Cheap text for anchor search: the PDF text layer (plus token text when tokens exist)."""
        tp = self.token_path(page_no)
        if tp is not None:
            doc_json = load_tokens_json(tp)
            if doc_json is not None:
                return " ".join(t.get("text") or "" for t in doc_json.get("tokens", []))
        try:
            return self.doc[page_no - 1].get_text()
        except Exception:
            return ""
