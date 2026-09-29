"""Room regions: geodesic watershed from the room labels over a wall render, or label Voronoi (96 R-15, 95 R2).

Plans and schematics keep their architecture on CAD layers (``ОВ-Архитектура``, ``S_перегородки``,
``A-DOORS``, ``ОВ-Архитектура-П`` on the principal schemes). The page is rendered with only those layers
visible (≈0.1 s for the 164k-path gold heating plan) and binarised into a barrier mask; every room label is a
seed, and OpenCV's marker watershed floods free space from all seeds at once in breadth-first order, so each
free pixel goes to the geodesically nearest label and door gaps are split where the fronts meet. A region is
then cut to the free-space component that holds its seed and to a radius around it, so a label never takes
over an unlabelled hall or the street. Without wall layers (scans, flattened PDFs) the same flood on an empty
mask gives the label Voronoi cells, with a lower confidence.

Room zones are polygons in displayed points; :func:`polygon_norm` gives the contract ``PolygonNorm``
(clockwise from the top-left vertex).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from inspector_layout.cad.geometry import PageFrame
from inspector_layout.cad.layers import keep_classes, render_layers
from inspector_layout.rooms.labels import RoomLabel

BARRIER_CLASSES = ("WALL", "DOOR", "WINDOW")
BARRIER_EXCLUDE = (
    "TEXT",
    "FURNITURE",
    "LEADER",
    "DUCT",
    "HEATING",
    "PLUMBING",
    "REVISION",
    "DIMENSION",
    "AXIS",
)
TARGET_PX = 2400  # longer side of the barrier raster


@dataclass(slots=True)
class Zone:
    label_index: int
    polygon: list[tuple[float, float]]  # displayed pt, clockwise from the top-left vertex
    area_pt2: float
    confidence: float
    method: str  # WALLS / VORONOI
    capped: bool = False


@dataclass(slots=True)
class ZoneMap:
    """Label regions as a raster (for point queries) plus their polygons."""

    labels: np.ndarray  # int32, 0 = no room, i+1 = label i
    scale: float  # px per pt
    zones: dict[int, Zone]
    method: str

    def label_at(self, x: float, y: float) -> int | None:
        h, w = self.labels.shape
        px, py = int(x * self.scale), int(y * self.scale)
        if 0 <= px < w and 0 <= py < h:
            v = int(self.labels[py, px])
            return v - 1 if v > 0 else None
        return None

    def labels_in_box(self, box: tuple[float, float, float, float]) -> dict[int, int]:
        h, w = self.labels.shape
        x0, y0 = max(0, int(box[0] * self.scale)), max(0, int(box[1] * self.scale))
        x1, y1 = min(w, math.ceil(box[2] * self.scale) + 1), min(h, math.ceil(box[3] * self.scale) + 1)
        if x1 <= x0 or y1 <= y0:
            return {}
        vals, counts = np.unique(self.labels[y0:y1, x0:x1], return_counts=True)
        return {int(v) - 1: int(c) for v, c in zip(vals, counts, strict=True) if v > 0}


def barrier_keep() -> Callable[[str], bool]:
    return keep_classes(*BARRIER_CLASSES, exclude=BARRIER_EXCLUDE)


def page_has_barriers(layer_names: list[str]) -> bool:
    keep = barrier_keep()
    return any(keep(n) for n in layer_names)


def barrier_mask(page, frame: PageFrame, labels: list[RoomLabel], scale: float) -> tuple[np.ndarray, int]:
    """Binary barrier mask (uint8 0/1) of the wall-like layers; label numbers and circles are cleared."""
    img, off = render_layers(page, barrier_keep(), scale)
    mask = (img < 215).astype(np.uint8)
    for lab in labels:
        # clear the label itself (room numbers are often on the architecture layer)
        x0, y0, x1, y1 = lab.box
        pad = 0.25 * max(y1 - y0, 1.0)
        cv2.rectangle(mask, (int((x0 - pad) * scale), int((y0 - pad) * scale)),
                      (int((x1 + pad) * scale), int((y1 + pad) * scale)), 0, -1)  # fmt: skip
        if lab.circle is not None:
            c = lab.circle
            cv2.circle(mask, (int(c.cx * scale), int(c.cy * scale)), int(c.r * scale) + 2, 0, -1)
    return mask, off


def _poly_from_mask(mask: np.ndarray, scale: float, eps_px: float = 1.2) -> list[tuple[float, float]] | None:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, eps_px, True).reshape(-1, 2)
    if len(c) < 3:
        return None
    pts = [(float(x) / scale, float(y) / scale) for x, y in c]
    return orient_clockwise(pts)


def orient_clockwise(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Clockwise as seen on the page (y down) and starting from the top-left vertex (contract PolygonNorm)."""
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True))
    if area2 < 0:  # y-down coordinates: a positive shoelace sum is clockwise on screen
        pts = pts[::-1]
    start = min(range(len(pts)), key=lambda i: (pts[i][0] + pts[i][1], pts[i][1]))
    return pts[start:] + pts[:start]


def polygon_norm(pts: list[tuple[float, float]], frame: PageFrame, decimals: int = 4) -> list[list[float]]:
    return [frame.norm_pt(x, y, decimals) for x, y in pts]


def polygon_area(pts: list[tuple[float, float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True))) / 2


def _nn_distance(seeds: list[tuple[float, float]]) -> float:
    if len(seeds) < 2:
        return 0.0
    arr = np.asarray(seeds, float)
    d = np.sqrt(((arr[:, None, :] - arr[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    return float(np.median(d.min(1)))


def room_zones(page, frame: PageFrame, labels: list[RoomLabel], layer_names: list[str]) -> ZoneMap:
    """Regions of ``labels`` (plan/schematic labels with seeds) on ``page``."""
    scale = TARGET_PX / max(frame.width, frame.height)
    h, w = math.ceil(frame.height * scale) + 1, math.ceil(frame.width * scale) + 1
    use_walls = page_has_barriers(layer_names)
    method = "WALLS" if use_walls else "VORONOI"
    if use_walls:
        mask, off = barrier_mask(page, frame, labels, scale)
        if off == 0 or mask.mean() < 0.002:
            use_walls, method = False, "VORONOI"
    if not use_walls:
        mask = np.zeros((h, w), np.uint8)
    mask = mask[:h, :w]
    if mask.shape != (h, w):
        pad = np.zeros((h, w), np.uint8)
        pad[: mask.shape[0], : mask.shape[1]] = mask
        mask = pad
    free = (mask == 0).astype(np.uint8)
    _, comp = cv2.connectedComponents(free, connectivity=4)
    markers = np.zeros((h, w), np.int32)
    seeds_px: list[tuple[int, int] | None] = []
    for i, lab in enumerate(labels):
        sx, sy = lab.seed or (lab.cx, lab.cy)
        px, py = min(w - 1, max(0, int(sx * scale))), min(h - 1, max(0, int(sy * scale)))
        if not free[py, px]:  # seed on a barrier pixel: nearest free pixel in a small window
            win = free[max(0, py - 6) : py + 7, max(0, px - 6) : px + 7]
            ys, xs = np.nonzero(win)
            if len(xs) == 0:
                seeds_px.append(None)
                continue
            k = int(np.argmin((xs - min(px, 6)) ** 2 + (ys - min(py, 6)) ** 2))
            px, py = max(0, px - 6) + int(xs[k]), max(0, py - 6) + int(ys[k])
        seeds_px.append((px, py))
        cv2.circle(markers, (px, py), 2, i + 1, -1)
    img = np.dstack([free * 255] * 3).astype(np.uint8)
    cv2.watershed(img, markers)
    seeds = [lab.seed or (lab.cx, lab.cy) for lab in labels]
    nn = _nn_distance(seeds) * scale
    radius = max(3.0 * nn, 0.02 * max(h, w)) if nn > 0 else 0.25 * max(h, w)
    out = np.zeros((h, w), np.int32)
    zones: dict[int, Zone] = {}
    # pixel lists per label, sorted once (a full-image comparison per label is too slow for 100+ rooms)
    flat = markers.ravel()
    idx = np.flatnonzero(flat > 0)
    vals = flat[idx]
    order = np.argsort(vals, kind="stable")
    idx, vals = idx[order], vals[order]
    bounds = np.searchsorted(vals, np.arange(1, len(labels) + 2))
    for i, sp in enumerate(seeds_px):
        if sp is None:
            continue
        pix = idx[bounds[i] : bounds[i + 1]]
        if len(pix) == 0:
            continue
        px, py = sp
        ys, xs = pix // w, pix % w
        x0, x1 = max(int(xs.min()), int(px - radius)), min(int(xs.max()) + 1, int(px + radius) + 1)
        y0, y1 = max(int(ys.min()), int(py - radius)), min(int(ys.max()) + 1, int(py + radius) + 1)
        capped = bool(xs.min() < x0 or xs.max() >= x1 or ys.min() < y0 or ys.max() >= y1)
        region = markers[y0:y1, x0:x1] == (i + 1)
        comp_id = comp[py, px]
        if use_walls and comp_id > 0:
            region &= comp[y0:y1, x0:x1] == comp_id
        # keep the connected piece that holds the seed
        n_r, lab_r = cv2.connectedComponents(region.astype(np.uint8), connectivity=4)
        if n_r > 2 and lab_r[py - y0, px - x0] > 0:
            region = lab_r == lab_r[py - y0, px - x0]
        if not region.any():
            continue
        out[y0:y1, x0:x1][region] = i + 1
        poly = _poly_from_mask(region.astype(np.uint8), scale)
        if poly is None:
            continue
        poly = [(x + x0 / scale, y + y0 / scale) for x, y in poly]
        conf = 0.85 if method == "WALLS" else 0.4
        if capped:
            conf = min(conf, 0.5)
        zones[i] = Zone(i, poly, polygon_area(poly), conf, method, capped)
    return ZoneMap(out, scale, zones, method)
