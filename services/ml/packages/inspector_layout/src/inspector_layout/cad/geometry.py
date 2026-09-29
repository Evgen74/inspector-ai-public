"""Vector content of a drawing page in displayed points (contract space PDF_VISIBLE_ROTATED_TL_V1 × page size).

PyMuPDF returns path coordinates in the unrotated page space; :class:`PageFrame` maps them through
``page.rotation_matrix`` to the displayed page (origin top-left, y down), the space of PageTokens boxes once
multiplied by the page size. Everything in :mod:`inspector_layout` works in displayed points and converts to
normalized boxes only at the output (:meth:`PageFrame.norm_box`).

:func:`index_drawings` makes **one pass** over ``page.get_cdrawings()`` (≈0.6 s for the 164k paths of the gold
heating plan F0202 p17) and keeps only what the layout stages need:

- per-layer path counts;
- small closed curves (room-label circles, axis bubbles) — :class:`Circle`;
- cubic arcs outside hatch/furniture layers, for cloud-shaped chains — :class:`Arc`;
- flattened segments of the layers a caller asks for (leaders, revision layers) — :class:`Seg`;
- small-path centres per layer, for attributing OCR tokens of outlined text to their CAD layer.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np

Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PageFrame:
    width: float  # displayed page width, pt
    height: float
    m: tuple[float, float, float, float, float, float]  # rotation_matrix a, b, c, d, e, f

    @classmethod
    def of(cls, page) -> PageFrame:
        rm = page.rotation_matrix
        return cls(float(page.rect.width), float(page.rect.height), (rm.a, rm.b, rm.c, rm.d, rm.e, rm.f))

    @property
    def diag(self) -> float:
        return math.hypot(self.width, self.height)

    def pt(self, x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.m
        return a * x + c * y + e, b * x + d * y + f

    def pts(self, arr: np.ndarray) -> np.ndarray:
        a, b, c, d, e, f = self.m
        x, y = arr[..., 0], arr[..., 1]
        return np.stack([a * x + c * y + e, b * x + d * y + f], -1)

    def rect(self, r) -> Box:
        x0, y0 = self.pt(r[0], r[1])
        x1, y1 = self.pt(r[2], r[3])
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def norm_box(self, box: Box, decimals: int = 5) -> list[float]:
        w, h = self.width, self.height
        vals = (box[0] / w, box[1] / h, box[2] / w, box[3] / h)
        return [round(min(1.0, max(0.0, v)), decimals) for v in vals]

    def norm_pt(self, x: float, y: float, decimals: int = 5) -> list[float]:
        return [
            round(min(1.0, max(0.0, x / self.width)), decimals),
            round(min(1.0, max(0.0, y / self.height)), decimals),
        ]

    def from_norm_box(self, nb) -> Box:
        return nb[0] * self.width, nb[1] * self.height, nb[2] * self.width, nb[3] * self.height


@dataclass(frozen=True, slots=True)
class Circle:
    cx: float
    cy: float
    r: float
    layer: str


@dataclass(frozen=True, slots=True)
class Arc:
    """One cubic Bézier item: end points, the point at t = ½ and the chord bulge (displayed pt)."""

    x0: float
    y0: float
    x1: float
    y1: float
    mx: float
    my: float
    bulge: float
    layer: str
    style: tuple
    path_id: int


@dataclass(frozen=True, slots=True)
class Seg:
    x0: float
    y0: float
    x1: float
    y1: float
    layer: str
    path_id: int
    curved: bool = False

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)


@dataclass(slots=True)
class PathInfo:
    path_id: int
    layer: str
    bbox: Box
    n_lines: int
    n_curves: int
    kind: str  # 's' stroke, 'f' fill, 'fs' both
    color: tuple | None
    closed: bool


@dataclass(slots=True)
class DrawingIndex:
    frame: PageFrame
    n_paths: int = 0
    layer_counts: Counter = field(default_factory=Counter)
    circles: list[Circle] = field(default_factory=list)
    arcs: list[Arc] = field(default_factory=list)
    segments: dict[str, list[Seg]] = field(default_factory=lambda: defaultdict(list))
    paths: dict[str, list[PathInfo]] = field(default_factory=lambda: defaultdict(list))
    small_centres: dict[str, list[tuple[float, float]]] = field(default_factory=lambda: defaultdict(list))
    arcs_truncated: bool = False

    @property
    def layers(self) -> list[str]:
        return sorted(k for k in self.layer_counts if k)


def _bezier_mid(p0, c1, c2, p3) -> tuple[float, float]:
    return (p0[0] + 3 * c1[0] + 3 * c2[0] + p3[0]) / 8.0, (p0[1] + 3 * c1[1] + 3 * c2[1] + p3[1]) / 8.0


def _item_points(item) -> list[tuple[float, float]]:
    op = item[0]
    if op == "l":
        return [item[1], item[2]]
    if op == "c":
        return [item[1], item[4]]
    if op == "re":
        x0, y0, x1, y1 = item[1]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    if op == "qu":
        q = item[1]
        return [q[0], q[1], q[3], q[2], q[0]]
    return []


def index_drawings(
    page,
    frame: PageFrame | None = None,
    *,
    keep_segments: Callable[[str], bool] = lambda layer: False,
    keep_paths: Callable[[str], bool] = lambda layer: False,
    arc_layer_ok: Callable[[str], bool] = lambda layer: True,
    max_circle_r: float = 40.0,
    small_path_max: float = 30.0,
    max_arcs: int = 200_000,
    drawings: list | None = None,
) -> DrawingIndex:
    """One pass over the page's vector paths (see the module docstring). ``drawings``: a precomputed
    ``page.get_cdrawings()`` (tests pass synthetic lists)."""
    frame = frame or PageFrame.of(page)
    idx = DrawingIndex(frame=frame)
    raw = drawings if drawings is not None else page.get_cdrawings()
    idx.n_paths = len(raw)
    a, b, c, d, e, f = frame.m
    ident = (a, b, c, d, e, f) == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def tp(p) -> tuple[float, float]:
        if ident:
            return float(p[0]), float(p[1])
        return a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f

    for pid, dr in enumerate(raw):
        layer = dr.get("layer") or ""
        idx.layer_counts[layer] += 1
        items = dr.get("items") or ()
        if not items:
            continue
        rx0, ry0, rx1, ry1 = frame.rect(dr["rect"]) if not ident else dr["rect"]
        w, h = rx1 - rx0, ry1 - ry0
        if max(w, h) <= small_path_max:
            idx.small_centres[layer].append(((rx0 + rx1) / 2, (ry0 + ry1) / 2))
        n_c = 0
        n_l = 0
        for it in items:
            if it[0] == "c":
                n_c += 1
            else:
                n_l += 1
        first = items[0]
        last = items[-1]
        start = first[1] if first[0] in ("l", "c") else None
        end = last[-1] if last[0] == "c" else (last[2] if last[0] == "l" else None)
        closed = bool(dr.get("closePath")) or (
            start is not None
            and end is not None
            and abs(start[0] - end[0]) < 0.5
            and abs(start[1] - end[1]) < 0.5
        )
        # Room-label circles and axis bubbles: 4 (or 8) arcs, closed, round, small.
        if (
            n_l == 0
            and n_c in (4, 8)
            and closed
            and w > 1.0
            and 0.8 < w / max(h, 1e-6) < 1.25
            and w / 2 <= max_circle_r
        ):
            idx.circles.append(Circle((rx0 + rx1) / 2, (ry0 + ry1) / 2, (w + h) / 4, layer))
        elif n_c and arc_layer_ok(layer) and not idx.arcs_truncated:
            style = (layer, dr.get("color"), round(float(dr.get("width") or 0.0), 2))
            for it in items:
                if it[0] != "c":
                    continue
                p0, p3 = tp(it[1]), tp(it[4])
                mx, my = tp(_bezier_mid(it[1], it[2], it[3], it[4]))
                cx, cy = (p0[0] + p3[0]) / 2, (p0[1] + p3[1]) / 2
                idx.arcs.append(
                    Arc(p0[0], p0[1], p3[0], p3[1], mx, my, math.hypot(mx - cx, my - cy), layer, style, pid)
                )
            if len(idx.arcs) > max_arcs:
                idx.arcs_truncated = True
        if keep_paths(layer):
            idx.paths[layer].append(
                PathInfo(
                    pid,
                    layer,
                    (rx0, ry0, rx1, ry1),
                    n_l,
                    n_c,
                    str(dr.get("type") or "s"),
                    dr.get("color"),
                    closed,
                )
            )
        if keep_segments(layer):
            segs = idx.segments[layer]
            for it in items:
                if it[0] == "c":
                    p0, p3 = tp(it[1]), tp(it[4])
                    segs.append(Seg(p0[0], p0[1], p3[0], p3[1], layer, pid, True))
                    continue
                pts = [tp(p) for p in _item_points(it)]
                for (x0, y0), (x1, y1) in pairwise(pts):
                    segs.append(Seg(x0, y0, x1, y1, layer, pid))
    return idx


# ── small geometry helpers ───────────────────────────────────────────────────────────────────


def box_center(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def box_union(boxes) -> Box:
    boxes = list(boxes)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def box_expand(b: Box, dx: float, dy: float | None = None) -> Box:
    dy = dx if dy is None else dy
    return b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy


def box_contains_pt(b: Box, x: float, y: float) -> bool:
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def box_intersects(a: Box, b: Box) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def point_seg_dist(px: float, py: float, s: Seg) -> float:
    vx, vy = s.x1 - s.x0, s.y1 - s.y0
    ll = vx * vx + vy * vy
    if ll <= 1e-12:
        return math.hypot(px - s.x0, py - s.y0)
    t = max(0.0, min(1.0, ((px - s.x0) * vx + (py - s.y0) * vy) / ll))
    return math.hypot(px - (s.x0 + t * vx), py - (s.y0 + t * vy))


class UnionFind:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, i: int) -> int:
        p = self.p
        while p[i] != i:
            p[i] = p[p[i]]
            i = p[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.p[ri] = rj

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self.p)):
            out[self.find(i)].append(i)
        return out


def cluster_boxes(boxes: list[Box], tol: float) -> list[list[int]]:
    """Connected components of boxes that touch within ``tol`` (grid-bucketed, O(n) for sparse pages)."""
    n = len(boxes)
    uf = UnionFind(n)
    cell = max(tol * 4, 1.0)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, bx in enumerate(boxes):
        for gx in range(int((bx[0] - tol) // cell), int((bx[2] + tol) // cell) + 1):
            for gy in range(int((bx[1] - tol) // cell), int((bx[3] + tol) // cell) + 1):
                grid[(gx, gy)].append(i)
    for members in grid.values():
        for ii in range(len(members)):
            i = members[ii]
            bi = box_expand(boxes[i], tol)
            for jj in range(ii + 1, len(members)):
                j = members[jj]
                if box_intersects(bi, boxes[j]):
                    uf.union(i, j)
    return [sorted(g) for g in uf.groups().values()]
