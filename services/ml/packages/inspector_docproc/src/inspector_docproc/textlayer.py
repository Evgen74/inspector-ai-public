"""Text-layer extraction (97 §2.13 F1): visible words with geometry, font and reading direction.

Visibility: a span is invisible when its opacity is 0, when it is neither filled nor stroked (text
render mode 3/7, scanner OCR layers) or when it is white. Invisible words are counted (they tell a
scanner-OCR layer apart) but never become TEXT_LAYER tokens.
Words: characters of one line are grouped at whitespace and at gaps wider than half the font size along
the line direction (CAD text often positions words without space characters).
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field

from inspector_common.geometry import clamp01

FILLED, STROKED = 16, 32
_WORD_GAP_EM = 0.5


@dataclass(slots=True)
class TextWord:
    text: str
    bbox: list[float]  # normalized, displayed page
    font: str
    size: float
    angle: int  # clockwise reading direction relative to the displayed page, multiple of 90
    block: int
    line: int
    visible: bool = True
    text_raw: str | None = None  # before garbled-layer repair
    repaired: bool = False
    garbled: bool = False


@dataclass(slots=True)
class TextLayer:
    words: list[TextWord] = field(default_factory=list)
    invisible_chars: int = 0
    white_chars: int = 0

    @property
    def visible_words(self) -> list[TextWord]:
        return [w for w in self.words if w.visible]

    @property
    def visible_chars(self) -> int:
        return sum(len(w.text) for w in self.words if w.visible)


def _angle(dir_xy: tuple[float, float], page_rotation: int) -> int:
    a = math.degrees(math.atan2(dir_xy[1], dir_xy[0]))  # MuPDF space: y down → clockwise positive
    return round((a + page_rotation) / 90.0) % 4 * 90


def extract_text_layer(page) -> TextLayer:
    import pymupdf

    # TEXT_CID_FOR_UNKNOWN_UNICODE keeps the raw glyph code of characters without a Unicode mapping
    # (instead of U+FFFD): garbled layers are then repairable by their constant glyph shift.
    flags = (
        pymupdf.TEXT_PRESERVE_WHITESPACE
        | pymupdf.TEXT_PRESERVE_LIGATURES
        | pymupdf.TEXT_MEDIABOX_CLIP
        | pymupdf.TEXT_CID_FOR_UNKNOWN_UNICODE
    )
    raw = page.get_text("rawdict", flags=flags)
    rm = page.rotation_matrix
    pw, ph = page.rect.width, page.rect.height
    layer = TextLayer()
    rotation = page.rotation
    for bi, block in enumerate(raw.get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        for li, line in enumerate(block.get("lines", [])):
            ldir = tuple(line.get("dir", (1.0, 0.0)))
            angle = _angle(ldir, rotation)
            cur: list[tuple[str, tuple[float, float, float, float], dict]] = []

            def flush(cur=cur, bi=bi, li=li, angle=angle) -> None:
                if not cur:
                    return
                text = unicodedata.normalize("NFC", "".join(c for c, _, _ in cur))
                x0 = min(b[0] for _, b, _ in cur)
                y0 = min(b[1] for _, b, _ in cur)
                x1 = max(b[2] for _, b, _ in cur)
                y1 = max(b[3] for _, b, _ in cur)
                span = cur[0][2]
                r = pymupdf.Rect(x0, y0, x1, y1) * rm
                box = [r.x0 / pw, r.y0 / ph, r.x1 / pw, r.y1 / ph]
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                if 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0 and text.strip():
                    layer.words.append(
                        TextWord(
                            text=text,
                            bbox=[round(clamp01(v), 5) for v in box],
                            font=str(span.get("font", "")),
                            size=float(span.get("size", 0.0)),
                            angle=angle,
                            block=bi,
                            line=li,
                            visible=span["_visible"],
                        )
                    )
                cur.clear()

            prev_end: float | None = None
            for span in line.get("spans", []):
                alpha = span.get("alpha", 255)
                cflags = span.get("char_flags", FILLED)
                color = span.get("color", 0)
                white = color == 0xFFFFFF
                visible = alpha != 0 and bool(cflags & (FILLED | STROKED)) and not white
                span["_visible"] = visible
                size = float(span.get("size", 0.0)) or 1.0
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    bbox = tuple(ch.get("bbox", (0, 0, 0, 0)))
                    if not visible and not c.isspace():
                        if white:
                            layer.white_chars += 1
                        else:
                            layer.invisible_chars += 1
                    if not c or c.isspace():
                        flush()
                        prev_end = None
                        continue
                    # position along the line direction
                    start = bbox[0] * ldir[0] + bbox[1] * ldir[1]
                    end = bbox[2] * ldir[0] + bbox[3] * ldir[1]
                    lo, hi = min(start, end), max(start, end)
                    if cur and (
                        cur[-1][2]["_visible"] != visible
                        or (prev_end is not None and lo - prev_end > _WORD_GAP_EM * size)
                    ):
                        flush()
                    cur.append((c, bbox, span))
                    prev_end = hi
            flush()
    return layer
