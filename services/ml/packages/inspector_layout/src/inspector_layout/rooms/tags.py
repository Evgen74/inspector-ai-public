"""Tag instances of a drawing page and the room each belongs to (96 R-15, 95 §3.4).

Marks are parsed per text line (the grammar of :mod:`inspector_layout.rooms.grammar`), so OCR splits such as
«П2,» + «/BE» or «П17.1,» + «17.2» are read as one mark. OCR-only forms are recovered per token: «0200» → Ø200
(on duct label layers or next to a duct size), «950M» → a flow, and the closed vocabulary repairs one-slip
tags («B22» → «В2.2») that are known from trusted text layers; the weak heads «3» → «В» and «11» → «П»
(«32.1» → В2.1, «119» → П9) only with independent evidence (:func:`_mark_evidence`). The elements of one printed
list share their tokens; the page pipeline emits them as one TagInstance (:func:`inspector_layout.rooms.page.
printed_marks`).

Room attachment (contract ``TagRoomLink``), in order:

1. ``LEADER`` — the leader from the label ends inside a room zone (or next to a room label);
2. ``INSIDE`` — the label itself lies inside a room zone;
3. ``NEAREST`` — the nearest room label within ¾ of the typical label spacing.

Marks in explication tables and in the main stamp are skipped.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from inspector_layout.cad.geometry import Box, box_contains_pt
from inspector_layout.cad.layers import layer_classes
from inspector_layout.cad.leaders import LeaderGraph
from inspector_layout.rooms.grammar import (
    ROOM_RE,
    TagMatch,
    Vocabulary,
    fold,
    ocr_diameter,
    ocr_flow,
    parse_tags,
    system_of,
    vent_subkind,
)
from inspector_layout.rooms.labels import PageLabels, RoomLabel, in_stamp
from inspector_layout.rooms.tokens import PageText, Tok, visual_lines
from inspector_layout.rooms.zones import ZoneMap

# Subkinds kept as TagInstances (sizes, levels and positions are too many and carry no room semantics on
# their own; flows and sizes of vent sheets are kept because the comparators read branch flows).
KEEP_SUBKINDS = {
    "branch", "system", "natural", "terminal", "local_exhaust", "equipment", "radiator", "riser", "pipeline",
    "warm_floor", "flow", "size", "level", "heat", "temperature",
}  # fmt: skip


@dataclass(slots=True)
class TagHit:
    match: TagMatch
    token_ids: list[int]
    box: Box
    conf: float
    text_source: str
    layer: str | None
    room_token: str | None = None
    room_link: str | None = None
    label_index: int | None = None
    leader_tip: tuple[float, float] | None = None
    line_box: Box | None = None  # the visual line the mark was read from (shelves run under the whole line)
    block: int = -1  # stacked lines of one label share its leader
    extra_labels: list[int] | None = None  # further rooms reached by other leaders of the same label


def _line_offsets(page: PageText, token_ids: list[int]) -> list[tuple[int, int, int]]:
    byid = page.by_id()
    out, pos = [], 0
    for i in token_ids:
        t = byid[i].text
        out.append((pos, pos + len(t), i))
        pos += len(t) + 1
    return out


def _tokens_for_span(offsets: list[tuple[int, int, int]], span: tuple[int, int]) -> list[int]:
    return [i for a, b, i in offsets if a < span[1] and span[0] < b]


def page_context(page: PageText, layer_names: list[str]) -> tuple[bool, bool]:
    """(vent, heating): which system grammars are active on this page."""
    classes = set()
    for n in layer_names:
        classes |= layer_classes(n)
    text = fold(" ".join(ln.text for ln in page.lines[:4000])).lower()
    vent = "DUCT" in classes or bool(re.search(r"вентиляц|воздуховод|приточн|вытяжн|воздухообмен", text))
    heating = "HEATING" in classes or bool(re.search(r"отоплен|теплоснаб|радиатор|т[её]пл\w*\s+пол", text))
    return vent, heating


def spot_tags(
    page: PageText,
    labels: PageLabels,
    vocab: Vocabulary | None = None,
    *,
    vent: bool = True,
    heating: bool = True,
) -> list[TagHit]:
    """Every mark on the page (not yet attached to rooms)."""
    byid = page.by_id()
    W, H = page.frame.width, page.frame.height
    skip_ids = {i for lab in labels.explication for i in lab.token_ids}
    room_ids = {i for lab in labels.plan_labels for i in lab.token_ids}
    expl_boxes = labels.explication_boxes
    hits: list[TagHit] = []
    consumed: set[int] = set()
    for ln in visual_lines(page):
        ids = [i for i in ln.token_ids if i not in skip_ids and i not in room_ids]
        if not ids:
            continue
        if any(byid[i].layer and "CATEGORY" in layer_classes(byid[i].layer) for i in ids):
            continue  # «В2» on a room-category layer is a fire category, not a system
        toks = [byid[i] for i in ids]
        if all(in_stamp(t, W, H) for t in toks):
            continue
        if any(box_contains_pt(b, toks[0].cx, toks[0].cy) for b in expl_boxes):
            continue
        text = " ".join(
            t.text
            if t.source.startswith("TEXT_LAYER") or vocab is None or not len(vocab) or not vent
            else vocab.repair_confusables(t.text)
            for t in toks
        )
        offsets = _line_offsets(page, ids)
        for m in parse_tags(text, vent=vent, heating=heating):
            if m.subkind not in KEEP_SUBKINDS:
                continue
            tids = _tokens_for_span(offsets, m.span)
            if not tids:
                continue
            tt = [byid[i] for i in tids]
            box = (min(t.x0 for t in tt), min(t.y0 for t in tt), max(t.x1 for t in tt), max(t.y1 for t in tt))
            conf = min(t.conf for t in tt)
            src = "OCR_LAYER_ISOLATED" if any(t.source == "OCR_LAYER_ISOLATED" for t in tt) else tt[0].source
            layer = next((t.layer for t in tt if t.layer), None)
            if (
                m.tag_kind == "VENT_SYSTEM"
                and vocab is not None
                and len(vocab)
                and not src.startswith("TEXT_LAYER")
            ):
                if m.tag_norm in vocab:
                    conf = min(1.0, conf + 0.05)
                else:
                    fixed = vocab.repair(m.tag_norm)
                    if fixed:  # «B22» read without its dot → «В2.2» (known from a trusted text layer)
                        m = TagMatch(fixed, fixed, m.tag_kind, m.span, system_of(fixed), vent_subkind(fixed),
                                     repaired=True)  # fmt: skip
                        conf = min(conf, 0.7)
                    elif m.subkind == "branch" and conf < 0.9:
                        conf *= 0.85  # an OCR branch never seen in a trusted layer
            hits.append(TagHit(m, tids, box, round(conf, 3), src, layer, line_box=ln.box, block=ln.block))
            consumed.update(tids)
    # token-level OCR recoveries
    if vent:
        for t in page.tokens:
            if t.id in consumed or t.id in skip_ids or t.id in room_ids or t.source.startswith("TEXT_LAYER"):
                continue
            if in_stamp(t, W, H):
                continue
            txt = t.text.strip()
            d = ocr_diameter(txt)
            if d and ((t.layer and "DUCT" in layer_classes(t.layer)) or t.conf >= 0.95):
                m = TagMatch(txt, d, "OTHER", (0, len(txt)), subkind="size")
                hits.append(TagHit(m, [t.id], t.box, round(t.conf * 0.9, 3), t.source, t.layer))
                continue
            f = ocr_flow(txt)
            if f is not None:
                sign = "-" if f < 0 else ""
                m = TagMatch(txt, f"L={sign}{abs(int(f))}", "OTHER", (0, len(txt)), subkind="flow", value=f)
                hits.append(TagHit(m, [t.id], t.box, round(t.conf * 0.8, 3), t.source, t.layer))
                continue
            if vocab is not None and len(vocab):
                fixed = vocab.repair(txt, weak_heads=_mark_evidence(t))
                if (
                    fixed
                ):  # the print is «П9»; the misread «119» is not kept (confidence ≤ 0.7 marks the repair)
                    m = TagMatch(fixed, fixed, "VENT_SYSTEM", (0, len(txt)), system_code=system_of(fixed),
                                 subkind=vent_subkind(fixed), repaired=True)  # fmt: skip
                    hits.append(TagHit(m, [t.id], t.box, round(min(t.conf, 0.7), 3), t.source, t.layer))
    return hits


WEAK_REPAIR_MAX_CONF = 0.8


def _mark_evidence(t: Tok) -> bool:
    """Independent evidence that an OCR token is a mark, not a number: it is drawn on a vent label layer
    («ОВ-Вентиляция-Выноски», «DUCT-Приток-TEXT»: areas and dimensions live on other layers), or the recogniser
    itself was unsure of it («119» for «П9» at 0.69). Gates the weak-head repairs «3» → «В», «11» → «П»."""
    if t.conf < WEAK_REPAIR_MAX_CONF:
        return True
    if not t.layer or t.layer_share < 0.5:
        return False
    cls = layer_classes(t.layer)
    return "DUCT" in cls and bool(cls & {"LEADER", "TEXT"})


def _nearest_label(x: float, y: float, labels: list[RoomLabel], radius: float) -> int | None:
    best, best_d = None, radius
    for i, lab in enumerate(labels):
        sx, sy = lab.seed or (lab.cx, lab.cy)
        d = math.hypot(sx - x, sy - y)
        if d <= best_d:
            best, best_d = i, d
    return best


def _box_gap(a: Box, b: Box) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def _adjacent_label(box: Box, labels: list[RoomLabel]) -> int | None:
    """The one plan label whose number is within three of its own widths of the mark (None if none/ambiguous)."""
    found = []
    for i, lab in enumerate(labels):
        w = max(lab.box[2] - lab.box[0], lab.box[3] - lab.box[1])
        if w > 0 and _box_gap(box, lab.box) <= 3 * w:
            found.append(i)
    return found[0] if len(found) == 1 else None


def label_spacing(labels: list[RoomLabel]) -> float:
    seeds = [lab.seed or (lab.cx, lab.cy) for lab in labels]
    if len(seeds) < 2:
        return 0.0
    ds = []
    for i, (x, y) in enumerate(seeds):
        ds.append(min(math.hypot(x - a, y - b) for j, (a, b) in enumerate(seeds) if j != i))
    ds.sort()
    return ds[len(ds) // 2]


def assign_rooms(
    hits: list[TagHit],
    labels: PageLabels,
    zones: ZoneMap | None,
    leaders: LeaderGraph | None,
    tokens: dict[int, Tok],
) -> None:
    """Fill ``room_token``/``room_link`` of every hit (see the module docstring)."""
    plan = labels.plan_labels
    if not plan:
        return
    spacing = label_spacing(plan)
    near_r = 0.75 * spacing if spacing > 0 else 0.0

    def room_at(x: float, y: float) -> int | None:
        if zones is not None:
            li = zones.label_at(x, y)
            if li is not None:
                return li
        return None

    line_tips: dict[tuple, list] = {}
    block_tips: dict[int, list] = {}
    if leaders is not None:
        for h in hits:
            key = h.line_box or h.box
            if key not in line_tips:
                th = max((tokens[i].text_h for i in h.token_ids if i in tokens), default=1.0)
                line_tips[key] = leaders.follow(key, th) or (
                    leaders.follow(h.box, th) if key != h.box else []
                )
            if line_tips[key] and h.block >= 0:
                block_tips.setdefault(h.block, [])
                block_tips[h.block].extend(line_tips[key])
    for h in hits:
        li: int | None = None
        link: str | None = None
        if leaders is not None:
            tips = line_tips.get(h.line_box or h.box) or block_tips.get(h.block, [])
            rooms = []
            for tip in tips:
                r = room_at(tip.x, tip.y)
                if r is None and near_r:
                    r = _nearest_label(tip.x, tip.y, plan, 0.5 * near_r)
                if r is not None:
                    rooms.append((tip.length, r, tip))
            if rooms:
                rooms.sort(key=lambda x: -x[0])
                _, li, tip = rooms[0]  # the farthest tip is the annotated point
                link = "LEADER"
                h.leader_tip = (tip.x, tip.y)
                # a label with several leaders annotates several objects («Регулятор … Multibox» → 2 cells)
                others = []
                for length, r, _ in rooms[1:]:
                    if r != li and r not in others and length >= 0.3 * rooms[0][0] and len(others) < 3:
                        others.append(r)
                h.extra_labels = others or None
        if li is None:
            cx, cy = (h.box[0] + h.box[2]) / 2, (h.box[1] + h.box[3]) / 2
            li = room_at(cx, cy)
            if li is not None:
                link = "INSIDE"
            elif near_r:
                li = _nearest_label(cx, cy, plan, near_r)
                link = "NEAREST" if li is not None else None
        if li is not None and link == "LEADER":
            adj = _adjacent_label(h.box, plan)
            here = room_at((h.box[0] + h.box[2]) / 2, (h.box[1] + h.box[3]) / 2)
            if (
                adj is not None
                and adj != li
                # a mark that lies inside another room's zone is not named by a number that merely sits beside it
                and (here is None or here == adj)
                and _box_gap(h.box, plan[li].box) > 3 * _box_gap(h.box, plan[adj].box)
            ):
                # the mark sits right next to a room number while its leader runs off to a far room: the leader
                # is a stray line (walls, ducts), the number beside the mark names the room
                li, link = adj, "NEAREST"
                h.leader_tip = None
                h.extra_labels = None
        if li is not None:
            h.label_index = li
            h.room_token = plan[li].rooms[0] if len(plan[li].rooms) == 1 else ", ".join(plan[li].rooms)
            h.room_link = link


def is_room_like(text: str) -> bool:
    return bool(ROOM_RE.match(text.strip().rstrip(",")))
