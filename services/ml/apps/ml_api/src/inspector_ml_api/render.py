"""PDF page rendering for the evidence viewer: whole pages, crops and a Deep Zoom tile pyramid.

Coordinates follow the contract space ``PDF_VISIBLE_ROTATED_TL_V1`` (the displayed page after /Rotate, origin
top-left), the same space as ``bbox_polygon_norm`` of evidence fragments: a normalized bbox of a fragment is a crop
of the displayed page, and a tile pixel maps back to it by dividing by the level size.

Tile pyramid (OpenSeadragon / Deep Zoom convention): the full-resolution image is the displayed page at
``max_dpi`` (default 288 = 4 × 72, W × H pixels); ``max_level = ceil(log2(max(W, H)))``; level ``L`` is the image
scaled by ``2 ** (L - max_level)``; tiles are ``tile_size`` pixels, without overlap, the last row/column cropped.

MuPDF interprets the page content once per page: display lists are cached (LRU) and every tile or crop is
rasterized from the cached list. MuPDF objects are not thread-safe, so a single lock serializes their use; run
more uvicorn workers for parallelism.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_MAX_DPI = 288
DEFAULT_TILE_SIZE = 512
MIN_DPI = 9
MAX_DPI = 600
#: Cap for one rendered image (whole page or crop); larger requests are scaled down (``capped``).
MAX_IMAGE_PIXELS = 25_000_000


class RenderRequestError(ValueError):
    """A request outside the page or the pyramid (page number, level, tile index, bbox, dpi)."""

    def __init__(self, code: str, **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(f"{code}: {details}")


@dataclass(frozen=True, slots=True)
class PageInfo:
    page_no: int
    pdf_pages: int
    width_pt: float
    height_pt: float
    rotation: int
    max_dpi: int
    width_px: int
    height_px: int
    tile_size: int
    tile_overlap: int
    min_level: int
    max_level: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def pyramid(width_pt: float, height_pt: float, max_dpi: int, tile_size: int) -> tuple[int, int, int]:
    """(width_px, height_px, max_level) of the full-resolution image."""
    width_px = max(1, math.ceil(width_pt * max_dpi / 72.0))
    height_px = max(1, math.ceil(height_pt * max_dpi / 72.0))
    max_level = max(0, math.ceil(math.log2(max(width_px, height_px))))
    return width_px, height_px, max_level


def level_size(width_px: int, height_px: int, max_level: int, level: int) -> tuple[int, int]:
    factor = 2.0 ** (level - max_level)
    return max(1, math.ceil(width_px * factor)), max(1, math.ceil(height_px * factor))


def _to_png(pix: Any, width: int, height: int) -> bytes:
    """PNG of a pixmap, cropped or padded (white) to exactly width × height (MuPDF rounds clip edges outward)."""
    import pymupdf

    if pix.width == width and pix.height == height:
        return pix.tobytes("png")
    src = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    out = np.full((height, width, 3), 255, dtype=np.uint8)
    h, w = min(height, src.shape[0]), min(width, src.shape[1])
    out[:h, :w] = src[:h, :w]
    return pymupdf.Pixmap(pymupdf.csRGB, width, height, out.tobytes(), False).tobytes("png")


class PageRenderer:
    """Renders pages of local PDF files. Thread-safe; caches open documents and page display lists."""

    def __init__(
        self,
        *,
        max_dpi: int = DEFAULT_MAX_DPI,
        tile_size: int = DEFAULT_TILE_SIZE,
        max_documents: int = 8,
        max_display_lists: int = 24,
    ) -> None:
        self.max_dpi = max_dpi
        self.tile_size = tile_size
        self._lock = threading.Lock()
        self._docs: OrderedDict[tuple[str, int], Any] = OrderedDict()
        self._lists: OrderedDict[tuple[str, int, int], tuple[Any, Any, int]] = OrderedDict()
        self._max_docs = max_documents
        self._max_lists = max_display_lists
        self.stats = {"documents_opened": 0, "display_lists_built": 0, "renders": 0}

    # ── caches (call with the lock held) ─────────────────────────────────────────────────────────

    def _document(self, path: Path) -> Any:
        import pymupdf

        key = (str(path), path.stat().st_mtime_ns)
        doc = self._docs.get(key)
        if doc is not None:
            self._docs.move_to_end(key)
            return doc
        doc = pymupdf.open(str(path))
        if doc.needs_pass:
            doc.close()
            raise RenderRequestError("FILE_NOT_RENDERABLE", reason="файл защищён паролем")
        self.stats["documents_opened"] += 1
        self._docs[key] = doc
        while len(self._docs) > self._max_docs:
            old_key, old = self._docs.popitem(last=False)
            for list_key in [k for k in self._lists if k[0] == old_key[0] and k[1] == old_key[1]]:
                del self._lists[list_key]
            old.close()
        return doc

    def _page(self, path: Path, page_no: int) -> tuple[Any, Any, int]:
        """(display list, displayed rect, rotation) of a 1-based page."""
        doc = self._document(path)
        if page_no < 1 or page_no > doc.page_count:
            raise RenderRequestError("PAGE_NOT_FOUND", page_no=page_no, pdf_pages=doc.page_count)
        key = (str(path), path.stat().st_mtime_ns, page_no)
        hit = self._lists.get(key)
        if hit is not None:
            self._lists.move_to_end(key)
            return hit
        page = doc[page_no - 1]
        entry = (page.get_displaylist(), page.rect, page.rotation)
        self.stats["display_lists_built"] += 1
        self._lists[key] = entry
        while len(self._lists) > self._max_lists:
            self._lists.popitem(last=False)
        return entry

    # ── public API ───────────────────────────────────────────────────────────────────────────────

    def page_count(self, path: Path) -> int:
        with self._lock:
            return self._document(path).page_count

    def info(self, path: Path, page_no: int) -> PageInfo:
        with self._lock:
            doc = self._document(path)
            _, rect, rotation = self._page(path, page_no)
            pages = doc.page_count
        width_px, height_px, max_level = pyramid(rect.width, rect.height, self.max_dpi, self.tile_size)
        return PageInfo(
            page_no=page_no,
            pdf_pages=pages,
            width_pt=round(rect.width, 3),
            height_pt=round(rect.height, 3),
            rotation=rotation,
            max_dpi=self.max_dpi,
            width_px=width_px,
            height_px=height_px,
            tile_size=self.tile_size,
            tile_overlap=0,
            min_level=0,
            max_level=max_level,
        )

    def render_tile(self, path: Path, page_no: int, level: int, x: int, y: int) -> bytes:
        import pymupdf

        with self._lock:
            dl, rect, _ = self._page(path, page_no)
            width_px, height_px, max_level = pyramid(rect.width, rect.height, self.max_dpi, self.tile_size)
            if level < 0 or level > max_level:
                raise RenderRequestError(
                    "VALIDATION_ERROR", summary=f"уровень {level} вне диапазона 0…{max_level}"
                )
            lw, lh = level_size(width_px, height_px, max_level, level)
            cols, rows = math.ceil(lw / self.tile_size), math.ceil(lh / self.tile_size)
            if x < 0 or y < 0 or x >= cols or y >= rows:
                raise RenderRequestError(
                    "VALIDATION_ERROR", summary=f"плитка {x},{y} вне сетки {cols}×{rows} уровня {level}"
                )
            x0, y0 = x * self.tile_size, y * self.tile_size
            x1, y1 = min(x0 + self.tile_size, lw), min(y0 + self.tile_size, lh)
            # Pixels per point of this level (exact level size, so the last tile ends on the page edge).
            sx, sy = lw / rect.width, lh / rect.height
            clip = pymupdf.Rect(x0 / sx, y0 / sy, x1 / sx, y1 / sy)
            pix = dl.get_pixmap(matrix=pymupdf.Matrix(sx, sy), clip=clip, alpha=False)
            self.stats["renders"] += 1
            return _to_png(pix, x1 - x0, y1 - y0)

    def render_image(
        self,
        path: Path,
        page_no: int,
        *,
        dpi: float | None = None,
        width: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Whole page or a normalized crop (bbox in the displayed space), by dpi or by output width."""
        import pymupdf

        if bbox is not None:
            x0, y0, x1, y1 = bbox
            if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
                raise RenderRequestError(
                    "VALIDATION_ERROR", summary="bbox: ожидается 0 ≤ x0 < x1 ≤ 1 и 0 ≤ y0 < y1 ≤ 1"
                )
        with self._lock:
            dl, rect, _ = self._page(path, page_no)
            nx0, ny0, nx1, ny1 = bbox or (0.0, 0.0, 1.0, 1.0)
            clip = pymupdf.Rect(nx0 * rect.width, ny0 * rect.height, nx1 * rect.width, ny1 * rect.height)
            if width is not None:
                dpi = width / clip.width * 72.0
            dpi = float(dpi if dpi is not None else 72.0)
            if not (MIN_DPI <= dpi <= MAX_DPI):
                raise RenderRequestError(
                    "VALIDATION_ERROR", summary=f"разрешение {dpi:.0f} dpi вне {MIN_DPI}…{MAX_DPI}"
                )
            scale = dpi / 72.0
            capped = False
            pixels = clip.width * scale * clip.height * scale
            if pixels > MAX_IMAGE_PIXELS:
                scale *= math.sqrt(MAX_IMAGE_PIXELS / pixels)
                capped = True
            out_w = max(1, round(clip.width * scale))
            out_h = max(1, round(clip.height * scale))
            pix = dl.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
            self.stats["renders"] += 1
            png = _to_png(pix, out_w, out_h)
        return png, {"width_px": out_w, "height_px": out_h, "dpi": round(scale * 72.0, 2), "capped": capped}

    def close(self) -> None:
        with self._lock:
            self._lists.clear()
            for doc in self._docs.values():
                doc.close()
            self._docs.clear()
