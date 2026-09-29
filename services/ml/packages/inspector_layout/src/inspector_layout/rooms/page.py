"""One drawing page → room entries, tag instances and revision clouds (contract LayoutArtifacts fragments).

Order: page tokens → one pass over the vector paths → token layer attribution → room labels → room zones
(walls or Voronoi) → marks and their rooms (leaders first) → revision clouds and the rooms under them.
Timings per stage are returned for the run summary.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import Point, Polygon

from inspector_layout.cad.clouds import Cloud, detect_clouds
from inspector_layout.cad.geometry import DrawingIndex, PageFrame, index_drawings
from inspector_layout.cad.layers import attribute_tokens, layer_classes, text_span_layers
from inspector_layout.cad.leaders import LeaderGraph, drop_glyph_strokes
from inspector_layout.rooms.grammar import LIST_SEP, Vocabulary, is_room_token
from inspector_layout.rooms.labels import PageLabels, detect_labels
from inspector_layout.rooms.tags import TagHit, assign_rooms, page_context, spot_tags
from inspector_layout.rooms.tokens import PageText, page_text
from inspector_layout.rooms.zones import ZoneMap, orient_clockwise, polygon_norm, room_zones

LEADER_CLASSES = {"LEADER", "AIRFLOW", "TEXT"}
NO_ARC_CLASSES = {"FURNITURE", "AXIS", "DIMENSION", "PLUMBING", "FRAME"}


@dataclass(slots=True)
class PageResult:
    page_no: int
    rooms: list[dict[str, Any]] = field(default_factory=list)
    tags: list[dict[str, Any]] = field(default_factory=list)
    clouds: list[dict[str, Any]] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    kind: str = "UNKNOWN"
    floor: str | None = None
    title: str | None = None
    zone_method: str | None = None
    warnings: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    token_origin: str = "PAGE_TOKENS"
    skipped: str | None = None  # NO_ANCHORS: nothing on the page a room, a mark or a cloud could hang on


_GENERIC_LEADER_LAYERS = re.compile(r"^(?:0|defpoints)?$|тонк|thin", re.IGNORECASE)


def _is_leader_layer(layer: str) -> bool:
    """Label layers, plus the generic ones CAD users draw leaders on (layer «0», no layer, thin pens)."""
    cls = layer_classes(layer)
    if cls & LEADER_CLASSES:
        return True
    return bool(_GENERIC_LEADER_LAYERS.search(layer.strip())) and not (
        cls & {"WALL", "DOOR", "WINDOW", "DUCT"}
    )


def _keep_segments(layer: str) -> bool:
    return _is_leader_layer(layer) or "REVISION" in layer_classes(layer)


def _keep_paths(layer: str) -> bool:
    return "REVISION" in layer_classes(layer)


def _arc_ok(layer: str) -> bool:
    return not (layer_classes(layer) & NO_ARC_CLASSES)


def printed_marks(hits: list[TagHit]) -> list[list[TagHit]]:
    """Group the elements of one printed mark: «B2.7,8,9» is parsed into В2.7, В2.8, В2.9 (three hits on the
    same tokens) but is one TagInstance (contract: «one printed mark»), ``tag_norm`` «В2.7, В2.8, В2.9»."""
    groups: dict[tuple, list[TagHit]] = {}
    for h in hits:
        key = (tuple(h.token_ids), h.match.tag, h.match.span, h.match.tag_kind, h.label_index,
               tuple(h.extra_labels or ()))  # fmt: skip
        groups.setdefault(key, []).append(h)
    return list(groups.values())


def _prov(text_source: str, conf: float, layer: str | None) -> dict[str, Any]:
    return {"text_source": text_source, "confidence": round(max(0.0, min(1.0, conf)), 3), "layer": layer}


def worth_indexing(page, text: PageText, ocgs: dict | None = None) -> bool:
    """Whether the vector pass can find anything: a room-like token, vent/heating wording, or a revision, duct
    or heating layer. Text-less sheets (F0160 p63: 867 k paths, no word) cost 35 s for nothing otherwise."""
    if any(is_room_token(t.text.strip().rstrip(",;")) for t in text.tokens):
        return True
    vent, heating = page_context(text, [])
    if vent or heating:
        return True
    try:
        from inspector_docproc.layers import page_layer_names

        names = page_layer_names(page, ocgs)
    except Exception:
        return True
    return any(layer_classes(n) & {"REVISION", "DUCT", "HEATING"} for n in names)


def process_page(
    page,
    page_no: int,
    tokens_path: Path | None,
    vocab: Vocabulary | None = None,
    *,
    sheet_number: Any = None,
    ocgs: dict | None = None,
) -> PageResult:
    t0 = time.perf_counter()
    res = PageResult(page_no)
    frame = PageFrame.of(page)
    text: PageText = page_text(page, page_no, tokens_path)
    res.token_origin = text.origin
    if text.origin == "TEXT_LAYER":
        res.warnings.append("OCR_PARTIAL")
    t1 = time.perf_counter()
    if not worth_indexing(page, text, ocgs):
        res.skipped = "NO_ANCHORS"
        res.timings_ms = {
            "tokens": round((t1 - t0) * 1000, 1),
            "total": round((time.perf_counter() - t0) * 1000, 1),
        }
        return res
    idx: DrawingIndex = index_drawings(
        page, frame, keep_segments=_keep_segments, keep_paths=_keep_paths, arc_layer_ok=_arc_ok
    )
    res.layers = idx.layers
    t2 = time.perf_counter()
    spans = text_span_layers(page, frame)
    byid = text.by_id()
    for tid, (layer, share) in attribute_tokens(text.tokens, idx, spans).items():
        tok = byid.get(tid)
        if tok is not None and not tok.layer:
            tok.layer, tok.layer_share = layer, share
    t3 = time.perf_counter()
    labels: PageLabels = detect_labels(text, idx.circles)
    res.kind, res.floor, res.title = labels.kind, labels.floor, labels.title
    t4 = time.perf_counter()
    zones: ZoneMap | None = None
    if labels.plan_labels:
        zones = room_zones(page, frame, labels.plan_labels, idx.layers)
        res.zone_method = zones.method
    t5 = time.perf_counter()
    vent, heating = page_context(text, idx.layers)
    hits: list[TagHit] = spot_tags(text, labels, vocab, vent=vent, heating=heating)
    if hits and labels.plan_labels:  # leaders only matter when there are marks to attach to rooms
        leader_segs = [s for layer, segs in idx.segments.items() if _is_leader_layer(layer) for s in segs]
        leader_segs = drop_glyph_strokes(leader_segs, [t.box for t in text.tokens])
        leaders = LeaderGraph(leader_segs, max_seg=0.25 * frame.diag) if leader_segs else None
        assign_rooms(hits, labels, zones, leaders, text.by_id())
    t6 = time.perf_counter()
    clouds: list[Cloud] = detect_clouds(idx)
    _cover(clouds, labels, zones)
    t7 = time.perf_counter()

    # ── contract fragments ──
    for i, lab in enumerate(labels.plan_labels):
        zone = zones.zones.get(i) if zones is not None else None
        for room in lab.rooms:
            entry: dict[str, Any] = {
                "room_token": room,
                "pdf_page_number": page_no,
                "bbox": frame.norm_box(lab.box),
                "zone": polygon_norm(zone.polygon, frame) if zone is not None else None,
                "source": lab.source,
                "name": lab.name,
                "area_m2": lab.area_m2 if len(lab.rooms) == 1 else None,
                "floor": labels.floor,
                "sheet_number": sheet_number,
                "provenance": _prov(lab.text_source, lab.confidence * (zone.confidence if zone else 1.0) ** 0.25,
                                    lab.layer),
            }  # fmt: skip
            res.rooms.append(entry)
    for lab in labels.explication:
        res.rooms.append(
            {
                "room_token": lab.rooms[0],
                "pdf_page_number": page_no,
                "bbox": frame.norm_box(lab.box),
                "zone": None,
                "source": "EXPLICATION_TABLE",
                "name": lab.name,
                "area_m2": lab.area_m2,
                "floor": labels.floor,
                "sheet_number": sheet_number,
                "provenance": _prov(lab.text_source, lab.confidence, lab.layer),
            }
        )
    for group in printed_marks(hits):
        h = group[0]
        norms = list(dict.fromkeys(g.match.tag_norm for g in group))
        systems = {g.match.system_code for g in group}
        rooms: list[str | None] = [None]
        if h.label_index is not None:
            rooms = list(labels.plan_labels[h.label_index].rooms)
            for li in h.extra_labels or ():
                rooms.extend(r for r in labels.plan_labels[li].rooms if r not in rooms)
        for room in rooms:  # one instance per room: a label «267, 270» annotates both rooms
            res.tags.append(
                {
                    "tag": h.match.tag[:64],
                    "tag_norm": LIST_SEP.join(norms),
                    "tag_kind": h.match.tag_kind,
                    "system_code": systems.pop() if len(systems) == 1 else None,
                    "pdf_page_number": page_no,
                    "bbox": frame.norm_box(h.box),
                    "room_token": room,
                    "room_link": h.room_link if room is not None else None,
                    "provenance": _prov(h.text_source, min(g.conf for g in group), h.layer),
                }
            )
    for c in clouds:
        res.clouds.append(
            {
                "pdf_page_number": page_no,
                "bbox": frame.norm_box(c.bbox),
                "polygon": polygon_norm(orient_clockwise(c.polygon), frame) if c.polygon else None,
                "source": c.source,
                "layer": c.layer,
                "revision_label": c.revision_label,
                "rooms_covered": c.rooms_covered,
                "confidence": round(c.confidence, 3),
            }
        )
    res.timings_ms = {
        "tokens": round((t1 - t0) * 1000, 1),
        "drawings": round((t2 - t1) * 1000, 1),
        "attribution": round((t3 - t2) * 1000, 1),
        "labels": round((t4 - t3) * 1000, 1),
        "zones": round((t5 - t4) * 1000, 1),
        "tags": round((t6 - t5) * 1000, 1),
        "clouds": round((t7 - t6) * 1000, 1),
        "total": round((time.perf_counter() - t0) * 1000, 1),
    }
    return res


def _cover(clouds: list[Cloud], labels: PageLabels, zones: ZoneMap | None) -> None:
    """Rooms under a cloud: the room label lies inside the cloud, half of the room zone lies under the cloud,
    or half of the cloud lies inside the room zone (a change drawn inside one room)."""
    if not clouds or not labels.plan_labels:
        return
    for c in clouds:
        if c.polygon and len(c.polygon) >= 3:
            poly = Polygon(c.polygon).buffer(0)
        else:
            x0, y0, x1, y1 = c.bbox
            poly = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        covered: list[str] = []
        for i, lab in enumerate(labels.plan_labels):
            inside = poly.buffer(0.5).contains(Point(lab.cx, lab.cy))
            if not inside and zones is not None and i in zones.zones:
                zp = Polygon(zones.zones[i].polygon).buffer(0)
                inter = zp.intersection(poly).area if zp.area > 0 else 0.0
                if inter >= 0.5 * zp.area or (poly.area > 0 and inter >= 0.5 * poly.area):
                    inside = True
            if inside:
                covered.extend(r for r in lab.rooms if r not in covered)
        c.rooms_covered = covered
