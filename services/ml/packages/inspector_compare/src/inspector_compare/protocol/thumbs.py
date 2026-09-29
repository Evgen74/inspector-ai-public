"""Evidence-card thumbnails (93 §5.5 item 3, 04 §3.10): a crop of each cited page around the card's regions, with a
blue frame for the expected side (the design, usually ПД) and a red frame for the actual side (РД / ИД).

Thumbnails are views, like DOCX and PDF: they are embedded into the protocol documents and never written as separate
run files (run_layout.yaml has no kind for them, so ``CardSource.thumbnail`` stays null). Each cited page is
rendered once per export with PyMuPDF; the crop is taken from the rendered (visible, rotation-applied) page, where
the card geometry lives (``PDF_VISIBLE_ROTATED_TL_V1``: normalised [0, 1], origin top-left). A page that cannot be
opened or rendered is skipped: thumbnails never fail an export.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inspector_common.jsonlog import get_logger

log = get_logger(__name__)

EXPECTED_ROLES = frozenset({"EXPECTED", "SUPPORTING_EXPECTED"})
BLUE = (0, 92, 230)
RED = (222, 28, 36)
RENDER_LONG_SIDE = 2400  # px of the longer side of the rendered page (A0 sheet ≈ 60 dpi; frames stay sharp)
OUT_WIDTH = 900  # px of a thumbnail
MIN_CROP = 0.30  # smallest crop as a share of the page side (context around a tight box)
MARGIN = 0.06  # margin around the regions, share of the page side
MAX_PER_CARD = 4
PALETTE_COLOURS = 62  # + 2 reserved entries: BLUE (index 62) and RED (index 63)
STAGE_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}


@dataclass(frozen=True, slots=True)
class Thumbnail:
    card_no: str
    source_index: int
    stage: str
    role: str
    file_id: str
    pdf_page_number: int
    png: bytes
    width: int
    height: int
    caption: str


PdfLocator = Callable[[str], Path | None]


def registry_locator(settings: Any) -> PdfLocator:
    """file_id → the PDF on disk (manifest location, any Unicode normalisation, or the recovery ledger)."""
    from inspector_registry.api import open_registry

    registry, resolver = open_registry(settings, use_cache=False)

    def locate(file_id: str) -> Path | None:
        try:
            mf = registry.get(file_id)
        except Exception:
            return None
        found = resolver.locate(mf)
        if found is not None:
            return found[0]
        recovered = getattr(resolver, "ledger", {}).get(file_id)
        return recovered if recovered is not None and Path(recovered).is_file() else None

    return locate


def _crop_box(boxes: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    if not boxes:
        return (0.0, 0.0, 1.0, 1.0)
    x0 = min(b[0] for b in boxes) - MARGIN
    y0 = min(b[1] for b in boxes) - MARGIN
    x1 = max(b[2] for b in boxes) + MARGIN
    y1 = max(b[3] for b in boxes) + MARGIN
    for lo, hi, axis in ((x0, x1, "x"), (y0, y1, "y")):
        if hi - lo < MIN_CROP:
            pad = (MIN_CROP - (hi - lo)) / 2
            if axis == "x":
                x0, x1 = lo - pad, hi + pad
            else:
                y0, y1 = lo - pad, hi + pad
    # shift inside the page, then clip
    if x0 < 0:
        x1, x0 = min(1.0, x1 - x0), 0.0
    if y0 < 0:
        y1, y0 = min(1.0, y1 - y0), 0.0
    if x1 > 1:
        x0, x1 = max(0.0, x0 - (x1 - 1)), 1.0
    if y1 > 1:
        y0, y1 = max(0.0, y0 - (y1 - 1)), 1.0
    return (x0, y0, x1, y1)


def _caption(source: Mapping[str, Any]) -> str:
    stage = STAGE_RU.get(str(source.get("stage")), str(source.get("stage")))
    where = f"с. {source.get('pdf_page_number')}"
    if source.get("sheet_number") is not None:
        where += f", лист {source['sheet_number']}"
    colour = (
        "синяя рамка — ожидаемое (проект)"
        if source.get("role") in EXPECTED_ROLES
        else "красная рамка — фактическое"
    )
    return f"{stage} · {source.get('file_id')} · {where} — {colour}"


class _PageCache:
    def __init__(self, locate: PdfLocator):
        self.locate = locate
        self.images: dict[tuple[str, int], Any] = {}
        self.failed: set[tuple[str, int]] = set()

    def get(self, file_id: str, page: int) -> Any | None:
        key = (file_id, page)
        if key in self.images:
            return self.images[key]
        if key in self.failed:
            return None
        try:
            import pymupdf
            from PIL import Image

            path = self.locate(file_id)
            if path is None:
                raise FileNotFoundError(file_id)
            with pymupdf.open(path) as doc:
                pg = doc[page - 1]
                zoom = RENDER_LONG_SIDE / max(pg.rect.width, pg.rect.height)
                pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception as exc:  # a missing or broken page never fails the export
            log.warning(
                "protocol.thumbnail_skipped", extra={"file_id": file_id, "page": page, "detail": str(exc)}
            )
            self.failed.add(key)
            return None
        self.images[key] = image
        return image


def _thumbnail(image: Any, source: Mapping[str, Any]) -> tuple[bytes, int, int]:
    """Crop, scale to OUT_WIDTH, quantise to a 62-colour palette (drawings compress ~3×) and draw the frames with
    two reserved palette entries, so blue and red stay exact."""
    from PIL import Image, ImageDraw

    boxes = [list(b) for b in ((source.get("geometry") or {}).get("boxes") or []) if len(b) == 4]
    cx0, cy0, cx1, cy1 = _crop_box(boxes)
    w, h = image.size
    crop = image.crop((round(cx0 * w), round(cy0 * h), round(cx1 * w), round(cy1 * h)))
    scale = OUT_WIDTH / max(1, crop.width)
    rgb = crop.resize((OUT_WIDTH, max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
    out = rgb.quantize(colors=PALETTE_COLOURS, method=Image.Quantize.MEDIANCUT)
    palette = (out.getpalette() or [])[: PALETTE_COLOURS * 3]
    palette += [0] * (PALETTE_COLOURS * 3 - len(palette)) + list(BLUE) + list(RED)
    out.putpalette(palette + [0] * (768 - len(palette)))
    draw = ImageDraw.Draw(out)
    colour = PALETTE_COLOURS if source.get("role") in EXPECTED_ROLES else PALETTE_COLOURS + 1
    for b in boxes:
        x0 = (b[0] - cx0) * w * scale
        y0 = (b[1] - cy0) * h * scale
        x1 = (b[2] - cx0) * w * scale
        y1 = (b[3] - cy0) * h * scale
        pad = 3
        draw.rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), outline=colour, width=3)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), out.width, out.height


def card_thumbnails(
    protocol: Mapping[str, Any], locate: PdfLocator, *, max_per_card: int = MAX_PER_CARD
) -> dict[str, list[Thumbnail]]:
    """card_no → thumbnails of its sources (anchors first, as listed), each page rendered once."""
    pages = _PageCache(locate)
    out: dict[str, list[Thumbnail]] = {}
    for card in protocol.get("evidence_cards") or []:
        thumbs: list[Thumbnail] = []
        for index, source in enumerate(card.get("sources") or []):
            if len(thumbs) >= max_per_card:
                break
            image = pages.get(str(source["file_id"]), int(source["pdf_page_number"]))
            if image is None:
                continue
            png, width, height = _thumbnail(image, source)
            thumbs.append(
                Thumbnail(
                    card_no=str(card["card_no"]),
                    source_index=index,
                    stage=str(source.get("stage")),
                    role=str(source.get("role")),
                    file_id=str(source["file_id"]),
                    pdf_page_number=int(source["pdf_page_number"]),
                    png=png,
                    width=width,
                    height=height,
                    caption=_caption(source),
                )
            )
        if thumbs:
            out[str(card["card_no"])] = thumbs
    return out
