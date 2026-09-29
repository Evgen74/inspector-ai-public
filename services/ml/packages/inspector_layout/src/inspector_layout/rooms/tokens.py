"""Page tokens in displayed points: PageTokens of a recognition run (AG-02A), or the text layer as a fallback.

PageTokens (``runs/<run_id>/tokens/<file_id>/p00017.json.gz``) merge the text layer with OCR of the outlined
CAD text (65 % of the text lines of the gold RD vent plans are curves, 96 §4.1). When a page has no PageTokens
(not recognised yet), the text layer alone is used and the page is flagged ``OCR_PARTIAL``: rooms printed as
text are still found, outlined tags are not.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_layout.cad.geometry import PageFrame


@dataclass(slots=True)
class Tok:
    id: int
    text: str
    x0: float  # displayed pt
    y0: float
    x1: float
    y1: float
    conf: float
    source: str  # contract TextSource
    line_id: int | None = None
    font: str | None = None
    size: float | None = None
    angle: int = 0
    raw: str | None = None
    layer: str | None = None
    layer_share: float = 0.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1

    @property
    def text_h(self) -> float:
        """Glyph height regardless of the reading direction."""
        return self.h if self.angle % 180 == 0 else self.w


@dataclass(slots=True)
class Line:
    id: int
    token_ids: list[int]
    text: str
    source: str


@dataclass(slots=True)
class PageText:
    page_no: int
    frame: PageFrame
    tokens: list[Tok] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    origin: str = "PAGE_TOKENS"  # or TEXT_LAYER (fallback)
    page_class: str | None = None

    def by_id(self) -> dict[int, Tok]:
        return {t.id: t for t in self.tokens}


def load_page_tokens(path: Path) -> dict[str, Any] | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def from_page_tokens(data: dict[str, Any], frame: PageFrame) -> PageText:
    w, h = frame.width, frame.height
    toks: list[Tok] = []
    for t in data.get("tokens", []):
        text = str(t.get("text", "")).strip()
        if not text:
            continue
        b = t["bbox"]
        toks.append(
            Tok(
                id=int(t["id"]),
                text=text,
                x0=b[0] * w,
                y0=b[1] * h,
                x1=b[2] * w,
                y1=b[3] * h,
                conf=float(t.get("conf", 1.0)),
                source=str(t.get("source", "OCR")),
                line_id=t.get("line_id"),
                font=t.get("font"),
                size=t.get("font_size_pt"),
                angle=int(t.get("angle") or 0),
                raw=t.get("text_raw"),
                layer=t.get("layer"),
                layer_share=1.0 if t.get("layer") else 0.0,  # a layer named by the recogniser is certain
            )
        )
    known = {t.id for t in toks}
    lines: list[Line] = []
    for ln in data.get("lines", []):
        ids = [i for i in ln.get("token_ids", []) if i in known]
        if ids:
            lines.append(Line(int(ln["id"]), ids, "", str(ln.get("source", ""))))
    page = PageText(int(data.get("page_no", 0)), frame, toks, lines, "PAGE_TOKENS", data.get("page_class"))
    _fill_lines(page)
    return page


def from_text_layer(page, frame: PageFrame, page_no: int) -> PageText:
    """Visible text-layer words (AG-02A's extractor) grouped into their PDF lines."""
    from inspector_docproc.textlayer import extract_text_layer

    layer = extract_text_layer(page)
    w, h = frame.width, frame.height
    toks: list[Tok] = []
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, word in enumerate(layer.visible_words):
        b = word.bbox
        toks.append(
            Tok(
                i,
                word.text.strip(),
                b[0] * w,
                b[1] * h,
                b[2] * w,
                b[3] * h,
                1.0,
                "TEXT_LAYER",
                None,
                word.font,
                word.size,
                word.angle,
            )
        )
        groups[(word.block, word.line)].append(i)
    lines = []
    for n, key in enumerate(sorted(groups)):
        for i in groups[key]:
            toks[i].line_id = n
        lines.append(Line(n, groups[key], "", "TEXT_LAYER"))
    out = PageText(page_no, frame, [t for t in toks if t.text], lines, "TEXT_LAYER", None)
    _fill_lines(out)
    return out


def _reading_key(t: Tok) -> tuple[float, float]:
    if t.angle == 90:
        return t.cy, -t.cx
    if t.angle == 270:
        return -t.cy, t.cx
    if t.angle == 180:
        return -t.cx, -t.cy
    return t.cx, t.cy


def _fill_lines(page: PageText) -> None:
    byid = page.by_id()
    for ln in page.lines:
        ln.token_ids.sort(key=lambda i: _reading_key(byid[i]))
        ln.text = " ".join(byid[i].text for i in ln.token_ids)
    in_line = {i for ln in page.lines for i in ln.token_ids}
    next_id = max((ln.id for ln in page.lines), default=-1) + 1
    for t in page.tokens:  # tokens without a line become one-token lines
        if t.id not in in_line:
            page.lines.append(Line(next_id, [t.id], t.text, t.source))
            t.line_id = next_id
            next_id += 1


def page_text(page, page_no: int, tokens_path: Path | None) -> PageText:
    frame = PageFrame.of(page)
    if tokens_path is not None and tokens_path.is_file():
        data = load_page_tokens(tokens_path)
        if data is not None:
            return from_page_tokens(data, frame)
    return from_text_layer(page, frame, page_no)


# ── visual lines and blocks (geometry only) ──────────────────────────────────────────────────


@dataclass(slots=True)
class VisualLine:
    """Tokens on one baseline with word gaps (PageTokens lines split OCR labels: «П2,» | «/BE»)."""

    id: int
    token_ids: list[int]
    text: str
    box: tuple[float, float, float, float]
    angle: int
    block: int = -1


def visual_lines(page: PageText, gap_em: float = 0.9, baseline_em: float = 0.35) -> list[VisualLine]:
    """Greedy left-to-right line assembly per reading direction: a token joins the open line whose last
    token ends at most ``gap_em`` text heights before it and whose baseline is within ``baseline_em``."""
    byid = page.by_id()
    out: list[VisualLine] = []
    by_angle: dict[int, list[Tok]] = defaultdict(list)
    for t in page.tokens:
        by_angle[t.angle % 360].append(t)
    for angle, toks in sorted(by_angle.items()):

        def uv(t: Tok, angle: int = angle) -> tuple[float, float, float]:
            """(start along the line, end along the line, baseline)."""
            if angle == 90:
                return t.y0, t.y1, t.cx
            if angle == 270:
                return -t.y1, -t.y0, t.cx
            if angle == 180:
                return -t.x1, -t.x0, t.cy
            return t.x0, t.x1, t.cy

        cell = 8.0
        open_lines: dict[int, list[int]] = defaultdict(list)  # baseline bucket → line indices
        lines: list[dict] = []
        for t in sorted(toks, key=lambda t: uv(t)[0]):
            u0, u1, v = uv(t)
            h = max(t.text_h, 1.0)
            best, best_gap = None, None
            b = int(v // cell)
            for bb in (b - 1, b, b + 1):
                for li in open_lines.get(bb, ()):
                    ln = lines[li]
                    gap = u0 - ln["u1"]
                    hh = max(h, ln["h"])
                    near = -0.3 * hh <= gap <= gap_em * hh and abs(ln["v"] - v) <= baseline_em * hh
                    if near and (best_gap is None or gap < best_gap):
                        best, best_gap = li, gap
            if best is None:
                lines.append({"ids": [t.id], "u1": u1, "v": v, "h": h, "bucket": b})
                open_lines[b].append(len(lines) - 1)
            else:
                ln = lines[best]
                ln["ids"].append(t.id)
                ln["u1"] = max(ln["u1"], u1)
                n = len(ln["ids"])
                ln["v"] = (ln["v"] * (n - 1) + v) / n
                ln["h"] = max(ln["h"], h)
                nb = int(ln["v"] // cell)
                if nb != ln["bucket"]:
                    open_lines[ln["bucket"]].remove(best)
                    open_lines[nb].append(best)
                    ln["bucket"] = nb
        for ln in lines:
            out.append(_mk_line(len(out), [byid[i] for i in ln["ids"]], angle))
    _blocks(out, byid)
    return out


def _mk_line(i: int, toks: list[Tok], angle: int) -> VisualLine:
    box = (min(t.x0 for t in toks), min(t.y0 for t in toks), max(t.x1 for t in toks), max(t.y1 for t in toks))
    return VisualLine(i, [t.id for t in toks], " ".join(t.text for t in toks), box, angle)


def _blocks(lines: list[VisualLine], byid: dict[int, Tok]) -> None:
    """Stacked lines of one label (left-aligned, gap ≤ 0.8 em): «Регулятор для системы / “теплый пол” /
    Multibox C/RTL», «П2/ВЕ / +400 м³/ч / −400 м³/ч». Horizontal text only. Lines without a leader of their
    own inherit the block's leader targets."""
    horiz = sorted((ln for ln in lines if ln.angle == 0), key=lambda ln: (ln.box[1], ln.box[0]))
    next_block = 0
    for ln in horiz:
        if ln.block >= 0:
            continue
        ln.block = next_block
        cur = ln
        for other in horiz:
            if other.block >= 0 or other.box[1] <= cur.box[1]:
                continue
            h = max(cur.box[3] - cur.box[1], 1.0)
            gap = other.box[1] - cur.box[3]
            if gap < -0.3 * h or gap > 0.8 * h:
                continue
            if abs(other.box[0] - cur.box[0]) <= 1.0 * h:  # left-aligned (centred stacks are too loose)
                other.block = next_block
                cur = other
        next_block += 1
    for ln in lines:
        if ln.block < 0:
            ln.block = next_block
            next_block += 1
