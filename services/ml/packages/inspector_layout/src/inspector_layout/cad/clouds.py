"""Revision clouds (облака изменений) as change zones (95 R4, 97 §2.13 F6).

Two sources:

- **OCG_LAYER** — paths on a revision layer («ОВ-Отопление-Изм. №3», «ОВ-Вентиляция-Изм. №2»), clustered by
  proximity. A cluster made of arcs is a cloud (confidence ≥ 0.8); a cluster of plain lines is changed
  geometry drawn on the revision layer (a weak change zone, confidence 0.45). On the gold heating plan
  F0202 p17 the layer holds two clouds; the one at [0.337, 0.687, 0.423, 0.730] covers rooms 270/272 (RT-04).
- **VECTOR_SHAPE** — a closed chain of ≥ 8 scalloped arcs of one style (layer, colour, width) on any other
  layer: clouds drawn without a dedicated layer.

The zone polygon is the convex hull of the arcs (the revision triangle and its leader are left out); the
rooms under a cloud are filled in by the page pipeline from the room labels and zones.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from shapely.geometry import MultiPoint

from inspector_layout.cad.geometry import Arc, Box, DrawingIndex, UnionFind, box_union, cluster_boxes
from inspector_layout.cad.layers import layer_classes, revision_label

MIN_CLOUD_ARCS = 6
MIN_SHAPE_ARCS = 8


@dataclass(slots=True)
class Cloud:
    bbox: Box  # displayed pt
    polygon: list[tuple[float, float]] | None
    source: str  # contract RevisionCloudSource
    layer: str | None
    revision_label: str | None
    confidence: float
    n_arcs: int
    n_lines: int
    rooms_covered: list[str] = field(default_factory=list)


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]] | None:
    if len(points) < 3:
        return None
    hull = MultiPoint(points).convex_hull
    if hull.geom_type != "Polygon":
        return None
    return [(float(x), float(y)) for x, y in list(hull.exterior.coords)[:-1]]


def _arc_points(arcs: list[Arc]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for a in arcs:
        pts.extend([(a.x0, a.y0), (a.mx, a.my), (a.x1, a.y1)])
    return pts


def clouds_from_revision_layers(idx: DrawingIndex) -> list[Cloud]:
    arcs_by_path: dict[int, list[Arc]] = defaultdict(list)
    rev_layers = [layer for layer in idx.paths if "REVISION" in layer_classes(layer)]
    if not rev_layers:
        return []
    wanted = {p.path_id for layer in rev_layers for p in idx.paths[layer]}
    for a in idx.arcs:
        if a.path_id in wanted:
            arcs_by_path[a.path_id].append(a)
    tol = max(3.0, 0.002 * idx.frame.diag)
    out: list[Cloud] = []
    for layer in sorted(rev_layers):
        paths = idx.paths[layer]
        for group in cluster_boxes([p.bbox for p in paths], tol):
            members = [paths[i] for i in group]
            n_c = sum(p.n_curves for p in members)
            n_l = sum(p.n_lines for p in members)
            arcs = [a for p in members for a in arcs_by_path.get(p.path_id, ())]
            bbox = box_union(p.bbox for p in members)
            if max(bbox[2] - bbox[0], bbox[3] - bbox[1]) < 2.0:
                continue
            if n_c >= MIN_CLOUD_ARCS and arcs:
                poly = _hull(_arc_points(arcs))
                bbox_arcs = box_union((min(a.x0, a.x1, a.mx), min(a.y0, a.y1, a.my), max(a.x0, a.x1, a.mx),
                                       max(a.y0, a.y1, a.my)) for a in arcs)  # fmt: skip
                conf = 0.95 if n_c >= 12 else 0.8
                out.append(Cloud(bbox_arcs, poly, "OCG_LAYER", layer, revision_label(layer), conf, n_c, n_l))
            else:
                bbox = (bbox[0] - 2.0, bbox[1] - 2.0, bbox[2] + 2.0, bbox[3] + 2.0)  # lines may be degenerate
                poly = [(bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[2], bbox[3]), (bbox[0], bbox[3])]
                out.append(Cloud(bbox, poly, "OCG_LAYER", layer, revision_label(layer), 0.45, n_c, n_l))
    return out


def clouds_from_shapes(
    idx: DrawingIndex, skip_layers: set[str] | None = None, snap: float = 0.8
) -> list[Cloud]:
    """Closed chains of scalloped arcs of one style, outside revision layers."""
    skip = skip_layers or set()
    by_style: dict[tuple, list[Arc]] = defaultdict(list)
    for a in idx.arcs:
        if a.layer in skip or "REVISION" in layer_classes(a.layer):
            continue
        chord = math.hypot(a.x1 - a.x0, a.y1 - a.y0)
        if chord < 1.0 or a.bulge < 0.18 * chord:
            continue
        by_style[a.style].append(a)
    out: list[Cloud] = []
    for arcs in by_style.values():
        if len(arcs) < MIN_SHAPE_ARCS:
            continue
        nodes: dict[tuple[int, int], int] = {}

        def node(x: float, y: float, nodes: dict[tuple[int, int], int] = nodes) -> int:
            key = (round(x / snap), round(y / snap))
            return nodes.setdefault(key, len(nodes))

        ends = [(node(a.x0, a.y0), node(a.x1, a.y1)) for a in arcs]
        uf = UnionFind(len(nodes))
        deg: dict[int, int] = defaultdict(int)
        for a, b in ends:
            uf.union(a, b)
            deg[a] += 1
            deg[b] += 1
        comps: dict[int, list[int]] = defaultdict(list)
        for i, (a, _) in enumerate(ends):
            comps[uf.find(a)].append(i)
        for members in comps.values():
            if len(members) < MIN_SHAPE_ARCS:
                continue
            node_ids = {n for i in members for n in ends[i]}
            loose = sum(1 for n in node_ids if deg[n] == 1)
            if loose > 2 or any(deg[n] > 2 for n in node_ids):
                continue  # open wavy line (insulation) or a mesh, not a cloud
            chords = [math.hypot(arcs[i].x1 - arcs[i].x0, arcs[i].y1 - arcs[i].y0) for i in members]
            mean = statistics.fmean(chords)
            if mean <= 0 or statistics.pstdev(chords) / mean > 0.6:
                continue
            sel = [arcs[i] for i in members]
            pts = _arc_points(sel)
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            if max(bbox[2] - bbox[0], bbox[3] - bbox[1]) < 4 * mean:
                continue  # a small rosette, not a cloud around content
            conf = 0.7 if loose == 0 else 0.55
            out.append(Cloud(bbox, _hull(pts), "VECTOR_SHAPE", sel[0].layer or None, None, conf, len(sel), 0))
    return out


def detect_clouds(idx: DrawingIndex) -> list[Cloud]:
    layer_clouds = clouds_from_revision_layers(idx)
    shape_clouds = clouds_from_shapes(idx)
    # a shape cloud that coincides with a layer cloud is the same change
    kept = []
    for c in shape_clouds:
        if any(_iou(c.bbox, lc.bbox) > 0.5 for lc in layer_clouds):
            continue
        kept.append(c)
    return layer_clouds + kept


def _iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
