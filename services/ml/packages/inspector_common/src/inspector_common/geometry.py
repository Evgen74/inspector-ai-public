"""Normalized page geometry (02 §3.14, canonical space ``PDF_VISIBLE_ROTATED_TL_V1``).

The space is the visible area V = CropBox ∩ MediaBox **after** /Rotate, origin at the top-left of
the page as displayed, x to the right, y downward, values in [0, 1]. Every bbox and polygon in
the contracts (PageTokens, ExtractedValue, EvidenceRef) uses it. Golden vectors:
packages/contracts/vectors/geometry.json (also consumed by the TS viewer tests).

Conventions:
- ``Rect`` = (x0, y0, x1, y1). PDF user-space rects are bottom-left origin, y up.
- ``BBox`` = [x0, y0, x1, y1] normalized; ``Polygon`` = [[x, y], ...] normalized.
- Rotation is clockwise and a multiple of 90; -90 ≡ 270.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

GEOMETRY_SPACE = "PDF_VISIBLE_ROTATED_TL_V1"
DECIMALS = 4  # storage rounding for bbox_polygon_norm (90 §3.3.6)

Rect = tuple[float, float, float, float]
BBox = list[float]
Point = tuple[float, float]
Polygon = list[list[float]]


def normalize_rotation(rotate: int) -> int:
    """Map any multiple of 90 (including negatives) to 0, 90, 180 or 270."""
    if rotate % 90 != 0:
        raise ValueError(f"/Rotate must be a multiple of 90, got {rotate}")
    return rotate % 360


def visible_rect(mediabox: Sequence[float], cropbox: Sequence[float] | None = None) -> Rect:
    """CropBox ∩ MediaBox in PDF user space (CropBox defaults to MediaBox)."""
    mx0, my0, mx1, my1 = _ordered(mediabox)
    if cropbox is None:
        return (mx0, my0, mx1, my1)
    cx0, cy0, cx1, cy1 = _ordered(cropbox)
    vx0, vy0, vx1, vy1 = max(mx0, cx0), max(my0, cy0), min(mx1, cx1), min(my1, cy1)
    if vx1 <= vx0 or vy1 <= vy0:
        raise ValueError("CropBox does not intersect MediaBox")
    return (vx0, vy0, vx1, vy1)


def displayed_size(
    mediabox: Sequence[float], cropbox: Sequence[float] | None, rotate: int
) -> tuple[float, float]:
    """(width, height) of the page as displayed, in points."""
    vx0, vy0, vx1, vy1 = visible_rect(mediabox, cropbox)
    w0, h0 = vx1 - vx0, vy1 - vy0
    return (h0, w0) if normalize_rotation(rotate) in (90, 270) else (w0, h0)


def pdf_point_to_norm(
    x: float, y: float, mediabox: Sequence[float], cropbox: Sequence[float] | None, rotate: int
) -> Point:
    """PDF default user-space point (bottom-left origin) → normalized displayed point (unclamped)."""
    vx0, vy0, vx1, vy1 = visible_rect(mediabox, cropbox)
    u = (x - vx0) / (vx1 - vx0)
    v = (vy1 - y) / (vy1 - vy0)
    r = normalize_rotation(rotate)
    if r == 0:
        return (u, v)
    if r == 90:
        return (1.0 - v, u)
    if r == 180:
        return (1.0 - u, 1.0 - v)
    return (v, 1.0 - u)


def norm_point_to_pdf(
    x: float, y: float, mediabox: Sequence[float], cropbox: Sequence[float] | None, rotate: int
) -> Point:
    """Inverse of :func:`pdf_point_to_norm`."""
    vx0, vy0, vx1, vy1 = visible_rect(mediabox, cropbox)
    r = normalize_rotation(rotate)
    if r == 0:
        u, v = x, y
    elif r == 90:
        u, v = y, 1.0 - x
    elif r == 180:
        u, v = 1.0 - x, 1.0 - y
    else:
        u, v = 1.0 - y, x
    return (vx0 + u * (vx1 - vx0), vy1 - v * (vy1 - vy0))


def pdf_rect_to_norm_bbox(
    rect: Sequence[float],
    mediabox: Sequence[float],
    cropbox: Sequence[float] | None = None,
    rotate: int = 0,
    *,
    clamp: bool = True,
    decimals: int | None = DECIMALS,
) -> BBox:
    """PDF user-space rect → normalized bbox: transform the 4 corners, then min/max (02 §3.14)."""
    x0, y0, x1, y1 = _ordered(rect)
    corners = [
        pdf_point_to_norm(px, py, mediabox, cropbox, rotate)
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    return _finish_bbox(corners, clamp=clamp, decimals=decimals)


def pixel_bbox_to_norm(
    bbox_px: Sequence[float],
    width_px: float,
    height_px: float,
    *,
    clamp: bool = True,
    decimals: int | None = DECIMALS,
) -> BBox:
    """Pixel bbox on a render of the displayed page (get_pixmap applies CropBox and /Rotate) → normalized."""
    x0, y0, x1, y1 = _ordered(bbox_px)
    corners = [(x0 / width_px, y0 / height_px), (x1 / width_px, y1 / height_px)]
    return _finish_bbox(corners, clamp=clamp, decimals=decimals)


def rotate_norm_bbox(bbox: Sequence[float], k90: int, *, decimals: int | None = DECIMALS) -> BBox:
    """Rotate a normalized bbox by ``k90`` quarter turns clockwise about the page centre.

    Used to map boxes found on a content-rotated render back to the displayed page: a box found
    on an image rotated clockwise by ``k`` quarter turns maps back with ``-k``.
    """
    x0, y0, x1, y1 = bbox
    corners: list[Point] = [(x0, y0), (x1, y1)]
    for _ in range(k90 % 4):
        corners = [(1.0 - py, px) for px, py in corners]
    return _finish_bbox(corners, clamp=True, decimals=decimals)


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def round_bbox(bbox: Sequence[float], decimals: int = DECIMALS) -> BBox:
    return [round(float(v), decimals) for v in bbox]


def bbox_area(bbox: Sequence[float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def bbox_intersection(a: Sequence[float], b: Sequence[float]) -> BBox | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    inter = bbox_intersection(a, b)
    if inter is None:
        return 0.0
    ia = bbox_area(inter)
    union = bbox_area(a) + bbox_area(b) - ia
    return ia / union if union > 0 else 0.0


def bbox_union(boxes: Iterable[Sequence[float]]) -> BBox:
    items = list(boxes)
    if not items:
        raise ValueError("bbox_union of an empty sequence")
    return [
        min(b[0] for b in items),
        min(b[1] for b in items),
        max(b[2] for b in items),
        max(b[3] for b in items),
    ]


def bbox_contains_point(bbox: Sequence[float], x: float, y: float) -> bool:
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def bbox_to_polygon(bbox: Sequence[float]) -> Polygon:
    """Clockwise from the top-left vertex (displayed space)."""
    x0, y0, x1, y1 = bbox
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def polygon_to_bbox(polygon: Sequence[Sequence[float]]) -> BBox:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def polygon_iou(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    """IoU of two simple polygons (shapely)."""
    from shapely.geometry import Polygon as ShapelyPolygon

    pa, pb = ShapelyPolygon(a), ShapelyPolygon(b)
    if not pa.is_valid or not pb.is_valid:
        pa, pb = pa.buffer(0), pb.buffer(0)
    union = pa.union(pb).area
    return float(pa.intersection(pb).area / union) if union > 0 else 0.0


def is_valid_bbox(bbox: Sequence[float]) -> bool:
    if len(bbox) != 4:
        return False
    x0, y0, x1, y1 = bbox
    return 0.0 <= x0 <= x1 <= 1.0 and 0.0 <= y0 <= y1 <= 1.0


def _ordered(rect: Sequence[float]) -> Rect:
    x0, y0, x1, y1 = (float(v) for v in rect)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _finish_bbox(points: Sequence[Point], *, clamp: bool, decimals: int | None) -> BBox:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    box = [min(xs), min(ys), max(xs), max(ys)]
    if clamp:
        box = [clamp01(v) for v in box]
    if decimals is not None:
        box = [round(v, decimals) for v in box]
    return box
