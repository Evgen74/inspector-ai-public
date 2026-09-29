"""Rendering and geometry of a PDF page in the displayed space (contract ``PDF_VISIBLE_ROTATED_TL_V1``).

- ``page.get_pixmap`` renders the visible area (CropBox ∩ MediaBox) after /Rotate with the origin at the
  top-left; a pixel (x, y) of a render with size (W, H) is the normalized point (x / W, y / H).
- PyMuPDF text and ``page.rect`` coordinates are unrotated and relative to the CropBox; multiplying by
  ``page.rotation_matrix`` gives displayed points, and dividing by ``page.rect`` normalizes them. This is
  verified against rendered ink for every /Rotate, offset CropBox and offset MediaBox in the tests
  (``tests/test_docproc_geometry.py``).
- Render policy (96 §5, 97 §2.16): scans at their native resolution clamped to [150, 300] dpi (never
  upsampled), vector outlines at 200 dpi, and a megapixel cap (``RENDER_CAPPED``). Renders live only in
  memory; nothing is persisted.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from inspector_common.geometry import clamp01
from inspector_docproc.config import RenderConfig


@dataclass(frozen=True, slots=True)
class ImageFacts:
    count: int
    max_share: float  # share of the page covered by the largest image
    total_share: float  # sum of image shares (may exceed 1 for stacked images)
    native_dpi: float | None  # effective dpi of the dominant image (None without one)
    largest_bbox_norm: tuple[float, float, float, float] | None  # largest image, normalized


def page_size_mm(page) -> tuple[float, float]:
    return page.rect.width * 25.4 / 72.0, page.rect.height * 25.4 / 72.0


def mupdf_rect_to_norm(page, rect: Sequence[float], *, clamp: bool = True) -> list[float]:
    """PyMuPDF (unrotated, CropBox-relative) rect → normalized bbox of the displayed page."""
    import pymupdf

    r = pymupdf.Rect(rect) * page.rotation_matrix
    w, h = page.rect.width, page.rect.height
    box = [min(r.x0, r.x1) / w, min(r.y0, r.y1) / h, max(r.x0, r.x1) / w, max(r.y0, r.y1) / h]
    return [clamp01(v) for v in box] if clamp else box


def pixel_to_norm(points: np.ndarray, width_px: int, height_px: int) -> np.ndarray:
    """Pixel points of a full-page render → normalized points (unclamped)."""
    p = np.asarray(points, dtype=np.float64)
    return np.stack([p[..., 0] / float(width_px), p[..., 1] / float(height_px)], -1)


def image_facts(page, dominant_share: float = 0.5) -> ImageFacts:
    """Images placed on the page, their coverage and the effective dpi of the dominant one.

    The dpi comes from the placement matrix (pixels per placed inch along each image axis), so it is
    correct for images placed rotated on /Rotate pages.
    """
    import pymupdf

    area = max(page.rect.width * page.rect.height, 1e-6)
    infos = page.get_image_info()
    best: tuple[float, float | None, tuple[float, float, float, float]] | None = None
    total = 0.0
    for info in infos:
        bbox = pymupdf.Rect(info["bbox"]) & pymupdf.Rect(0, 0, *_unrotated_size(page))
        if bbox.is_empty:
            continue
        share = min(1.0, bbox.width * bbox.height / area)
        total += share
        dpi = _placement_dpi(info)
        norm = tuple(mupdf_rect_to_norm(page, bbox))
        if best is None or share > best[0]:
            best = (share, dpi, norm)  # type: ignore[assignment]
    if best is None:
        return ImageFacts(len(infos), 0.0, 0.0, None, None)
    share, dpi, norm = best
    native = dpi if share >= dominant_share else None
    return ImageFacts(len(infos), round(share, 4), round(total, 4), native, norm)


def _unrotated_size(page) -> tuple[float, float]:
    r = page.rect
    return (r.height, r.width) if page.rotation % 180 else (r.width, r.height)


def _placement_dpi(info: dict) -> float | None:
    w_px, h_px = info.get("width") or 0, info.get("height") or 0
    tr = info.get("transform")
    if not w_px or not h_px or not tr:
        return None
    a, b, c, d = tr[0], tr[1], tr[2], tr[3]
    sx, sy = math.hypot(a, b), math.hypot(c, d)  # placed size in pt along the image x / y axes
    if sx <= 0 or sy <= 0:
        return None
    return (w_px * 72.0 / sx + h_px * 72.0 / sy) / 2.0


def choose_dpi(kind: str, native_dpi: float | None, cfg: RenderConfig) -> int:
    """``kind``: ``scan`` (raster content) or ``vector`` (outlined text / coverage check)."""
    if kind == "vector":
        return cfg.vector_dpi
    if native_dpi is None:
        return cfg.fallback_dpi
    return int(min(max(round(native_dpi), cfg.scan_dpi_min), cfg.scan_dpi_max))


def capped_dpi(page, dpi: int, cfg: RenderConfig) -> tuple[int, bool]:
    """Lower the dpi so that the render stays under ``max_megapixels``; returns (dpi, capped)."""
    w_in, h_in = page.rect.width / 72.0, page.rect.height / 72.0
    mp = w_in * h_in * dpi * dpi / 1e6
    if mp <= cfg.max_megapixels:
        return dpi, False
    new = math.floor(math.sqrt(cfg.max_megapixels * 1e6 / (w_in * h_in)))
    return max(new, 72), True


def render_page(page, dpi: int, clip=None) -> np.ndarray:
    """RGB render → BGR uint8 array (displayed orientation). ``clip`` is in ``page.rect`` coordinates."""
    import pymupdf

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return np.ascontiguousarray(arr[:, :, 2::-1])


def norm_polygon(
    points_px: np.ndarray, width_px: int, height_px: int, decimals: int = 4
) -> list[list[float]]:
    pts = pixel_to_norm(points_px, width_px, height_px)
    return [[round(clamp01(float(x)), decimals), round(clamp01(float(y)), decimals)] for x, y in pts]


def norm_bbox_from_points(
    points_px: np.ndarray, width_px: int, height_px: int, decimals: int = 4
) -> list[float]:
    pts = pixel_to_norm(points_px, width_px, height_px)
    xs, ys = pts[..., 0], pts[..., 1]
    return [
        round(clamp01(float(xs.min())), decimals),
        round(clamp01(float(ys.min())), decimals),
        round(clamp01(float(xs.max())), decimals),
        round(clamp01(float(ys.max())), decimals),
    ]
