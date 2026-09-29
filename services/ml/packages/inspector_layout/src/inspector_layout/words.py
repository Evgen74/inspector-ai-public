"""Words in millimetres of the displayed page: the common input of the title-block reader.

Sources: the PDF text layer (:func:`inspector_docproc.textlayer.extract_text_layer`), PageTokens of a
recognition run (AG-02A) and OCR of a region (``PageRecognizer.ocr_region``). All use normalized boxes of the
displayed page (contract space ``PDF_VISIBLE_ROTATED_TL_V1``); the reader works in millimetres because the
ГОСТ Р 21.101 stamp is specified in millimetres (185 × 55 mm, 5 mm rows).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PT_PER_MM = 72.0 / 25.4


@dataclass(slots=True)
class Word:
    text: str
    x0: float  # mm from the left edge of the displayed page
    y0: float  # mm from the top edge
    x1: float
    y1: float
    source: str = "TEXT_LAYER"  # contract TextSource
    conf: float = 1.0
    raw: str | None = None  # text before post-correction (OCR), when different
    angle: int = 0
    layer: str | None = None

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    def norm_bbox(self, page_w_mm: float, page_h_mm: float) -> list[float]:
        return [
            round(min(1.0, max(0.0, self.x0 / page_w_mm)), 5),
            round(min(1.0, max(0.0, self.y0 / page_h_mm)), 5),
            round(min(1.0, max(0.0, self.x1 / page_w_mm)), 5),
            round(min(1.0, max(0.0, self.y1 / page_h_mm)), 5),
        ]


def page_size_mm(page) -> tuple[float, float]:
    """Displayed page size in mm (``page.rect`` is the rotated visible rectangle)."""
    return page.rect.width / PT_PER_MM, page.rect.height / PT_PER_MM


def from_norm(text: str, bbox: Iterable[float], page_w_mm: float, page_h_mm: float, **kw: Any) -> Word:
    x0, y0, x1, y1 = (float(v) for v in bbox)
    return Word(text, x0 * page_w_mm, y0 * page_h_mm, x1 * page_w_mm, y1 * page_h_mm, **kw)


GARBLED_CONF = 0.5  # a text-layer word still garbled after repair («Л̛ст» for «Лист»)


def from_text_layer(layer, page_w_mm: float, page_h_mm: float, *, keep_garbled: bool = False) -> list[Word]:
    """Visible text-layer words (``TextLayer`` of docproc). Garbled words are dropped unless ``keep_garbled``:
    the stamp reader keeps them at confidence 0.5 because a label with one unmapped glyph still matches
    («Л̛» «ст» → «Лист»), and never takes a value (шифр, title) from them."""
    out = []
    for w in layer.words:
        if not w.visible or not w.text.strip() or (w.garbled and not keep_garbled):
            continue
        src = "TEXT_LAYER_REPAIRED" if w.repaired else "TEXT_LAYER"
        conf = GARBLED_CONF if w.garbled else 1.0
        out.append(from_norm(w.text, w.bbox, page_w_mm, page_h_mm, source=src, conf=conf, angle=w.angle))
    return out


def from_tokens(tokens: Iterable[Mapping[str, Any]], page_w_mm: float, page_h_mm: float) -> list[Word]:
    """PageTokens ``tokens`` (or ``ocr_region`` tokens) → words."""
    out = []
    for t in tokens:
        text = str(t.get("text") or "")
        if not text.strip() or not t.get("bbox"):
            continue
        out.append(
            from_norm(
                text,
                t["bbox"],
                page_w_mm,
                page_h_mm,
                source=str(t.get("source") or "OCR"),
                conf=float(t.get("conf", 1.0)),
                raw=t.get("text_raw"),
                angle=int(t.get("angle", 0) or 0),
                layer=t.get("layer"),
            )
        )
    return out


def in_window(words: Iterable[Word], window_mm: tuple[float, float, float, float]) -> list[Word]:
    x0, y0, x1, y1 = window_mm
    return [w for w in words if x0 <= w.cx <= x1 and y0 <= w.cy <= y1]


def dedupe(words: list[Word]) -> list[Word]:
    """Drop words that repeat another word of the same place (overlapping OCR passes: «04.23» and «23»)."""

    def inter(a: Word, b: Word) -> float:
        ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
        iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
        return ix * iy

    order = sorted(range(len(words)), key=lambda i: (-(words[i].w * words[i].h), -words[i].conf))
    kept: list[Word] = []
    for i in order:
        w = words[i]
        area = max(w.w * w.h, 1e-6)
        dup = False
        for k in kept:
            ov = inter(w, k) / area
            if ov > 0.6 and (w.text.strip() in k.text or ov > 0.9):
                dup = True
                break
        if not dup:
            kept.append(w)
    kept.sort(key=lambda w: (round(w.cy, 1), w.x0))
    return kept
