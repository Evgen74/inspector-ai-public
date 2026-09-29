"""Leader lines (выноски): from a label on the drawing to the point it annotates (96 §12 (a), 95 §3.4).

On the gold RD vent plans the marks that tell which room is served are **not** inside the room: «В2.2»,
«В2.3», «В2.4» sit on shelves in room 141 with leaders down to the ducts of room 147; the air-exchange box
«В2.3,4 −150 м³/ч» stands outside the building with two leaders to the local exhausts in 147 (F0201 p18).
So a mark is attached to the room where its leader **ends**.

Leaders live on label layers (``ОВ-Вентиляция-Выноски``, ``ОВ-Воздухообмены``, ``DUCT-…-TEXT``,
``ОВ-Отопление-Выноски``). :class:`LeaderGraph` snaps segment end points into nodes; :meth:`LeaderGraph.follow`
starts from the segments that touch a label — the shelf under the text, the frame of a boxed label — walks
the connected segments and returns the loose ends away from the label.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass

from inspector_layout.cad.geometry import Box, Seg, box_expand, point_seg_dist


@dataclass(frozen=True, slots=True)
class LeaderHit:
    x: float
    y: float
    length: float  # path length from the label to the tip, pt
    n_segments: int


def drop_glyph_strokes(segments: list[Seg], text_boxes: list[Box], pad_ratio: float = 0.12) -> list[Seg]:
    """Outlined text is drawn with strokes on the same label layers as its leader: a segment whose two ends
    lie inside one text box (padded by ``pad_ratio`` of its height) is a glyph stroke, not a leader."""
    cell = 30.0
    grid: dict[tuple[int, int], list[Box]] = defaultdict(list)
    for b in text_boxes:
        pad = pad_ratio * max(b[3] - b[1], 1.0)
        pb = (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)
        for gx in range(int(pb[0] // cell), int(pb[2] // cell) + 1):
            for gy in range(int(pb[1] // cell), int(pb[3] // cell) + 1):
                grid[(gx, gy)].append(pb)
    out = []
    for s in segments:
        glyph = False
        for b in grid.get((int(s.x0 // cell), int(s.y0 // cell)), ()):
            if (
                b[0] <= s.x0 <= b[2]
                and b[1] <= s.y0 <= b[3]
                and b[0] <= s.x1 <= b[2]
                and b[1] <= s.y1 <= b[3]
            ):
                glyph = True
                break
        if not glyph:
            out.append(s)
    return out


class LeaderGraph:
    def __init__(self, segments: list[Seg], snap: float = 0.9, max_seg: float = 1e9) -> None:
        self.segs = [s for s in segments if 0.3 < s.length <= max_seg]
        self.snap = snap
        self._node_of: dict[tuple[int, int], int] = {}
        self.node_xy: list[tuple[float, float]] = []
        self.ends: list[tuple[int, int]] = []
        self.adj: dict[int, list[int]] = defaultdict(list)  # node → segment ids
        for si, s in enumerate(self.segs):
            a = self._node(s.x0, s.y0)
            b = self._node(s.x1, s.y1)
            self.ends.append((a, b))
            self.adj[a].append(si)
            self.adj[b].append(si)
        self.cell = 25.0
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for si, s in enumerate(self.segs):
            for gx in range(int(min(s.x0, s.x1) // self.cell), int(max(s.x0, s.x1) // self.cell) + 1):
                for gy in range(int(min(s.y0, s.y1) // self.cell), int(max(s.y0, s.y1) // self.cell) + 1):
                    self.grid[(gx, gy)].append(si)
        self._attach_t_junctions()

    def _node(self, x: float, y: float) -> int:
        key = (round(x / self.snap), round(y / self.snap))
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                n = self._node_of.get((key[0] + dx, key[1] + dy))
                if n is not None:
                    nx, ny = self.node_xy[n]
                    if abs(nx - x) <= self.snap and abs(ny - y) <= self.snap:
                        return n
        n = len(self.node_xy)
        self.node_xy.append((x, y))
        self._node_of[key] = n
        return n

    def _attach_t_junctions(self) -> None:
        """A leader that starts on the middle of a shelf is joined to the shelf (end point on a segment)."""
        for n, (x, y) in enumerate(self.node_xy):
            if len(self.adj[n]) != 1:
                continue
            own = self.adj[n][0]
            for si in self.near_segments((x - self.snap, y - self.snap, x + self.snap, y + self.snap)):
                if si == own or n in self.ends[si]:
                    continue
                if point_seg_dist(x, y, self.segs[si]) <= self.snap:
                    self.adj[n].append(si)

    def near_segments(self, box: Box) -> set[int]:
        out: set[int] = set()
        for gx in range(int(box[0] // self.cell), int(box[2] // self.cell) + 1):
            for gy in range(int(box[1] // self.cell), int(box[3] // self.cell) + 1):
                out.update(self.grid.get((gx, gy), ()))
        return out

    def start_segments(self, box: Box, text_h: float) -> tuple[list[int], list[int]]:
        """Segments that belong to a label at ``box``: (the shelf under it or a frame around it, leaders that
        start right at the label). The second list is the fallback for boxed labels whose frame is drawn on
        another layer (F0201 p18 «В2.3,4 −150 м³/ч»)."""
        th = max(text_h, 1.0)
        zone = box_expand(box, 0.8 * th)
        out: list[int] = []
        loose: list[int] = []
        for si in self.near_segments(zone):
            s = self.segs[si]
            horizontal = abs(s.y1 - s.y0) <= 0.15 * th
            vertical = abs(s.x1 - s.x0) <= 0.15 * th
            sx0, sx1 = min(s.x0, s.x1), max(s.x0, s.x1)
            sy0, sy1 = min(s.y0, s.y1), max(s.y0, s.y1)
            if horizontal:
                overlap = min(sx1, box[2]) - max(sx0, box[0])
                y = (s.y0 + s.y1) / 2
                below = box[3] - 0.35 * th <= y <= box[3] + 0.9 * th
                above = box[1] - 0.9 * th <= y <= box[1] + 0.2 * th
                if overlap >= 0.5 * min(box[2] - box[0], sx1 - sx0) and (below or above):
                    out.append(si)
                    continue
            if vertical:
                overlap = min(sy1, box[3]) - max(sy0, box[1])
                x = (s.x0 + s.x1) / 2
                side = (
                    box[0] - 0.9 * th <= x <= box[0] + 0.2 * th or box[2] - 0.2 * th <= x <= box[2] + 0.9 * th
                )
                if overlap >= 0.5 * min(box[3] - box[1], sy1 - sy0) and side:
                    out.append(si)
                    continue
            # a leader that starts right at the label (boxed labels whose frame is on another layer)
            if s.length >= 2.0 * th:
                in0 = zone[0] <= s.x0 <= zone[2] and zone[1] <= s.y0 <= zone[3]
                in1 = zone[0] <= s.x1 <= zone[2] and zone[1] <= s.y1 <= zone[3]
                if in0 != in1:
                    loose.append(si)
        return out, loose

    def follow(
        self, box: Box, text_h: float, max_segments: int = 120, max_depth: int = 16
    ) -> list[LeaderHit]:
        """Leader tips reachable from the label's shelf/frame, farther than 2 text heights from the label.

        A tip is a dead end of the walk or the entry into an arrowhead/dot (a cluster of tiny segments). A walk
        that spreads over more than ``max_segments`` segments is a dense network (dimension chains, hatches),
        not a leader, and gives no tips.
        """
        primary, loose = self.start_segments(box, text_h)
        for starts in (primary, loose):
            if starts:
                tips = self._walk(box, text_h, starts, max_segments, max_depth)
                if tips:
                    return tips
        return []

    def _walk(
        self, box: Box, text_h: float, starts: list[int], max_segments: int, max_depth: int
    ) -> list[LeaderHit]:
        th = max(text_h, 1.0)
        tiny = 0.2 * th
        far = box_expand(box, 2.0 * th)
        seen_seg: set[int] = set(starts)
        dist: dict[int, float] = {}
        q: deque[tuple[int, float, int]] = deque()
        for si in starts:
            for n in self.ends[si]:
                if n not in dist:
                    dist[n] = 0.0
                    q.append((n, 0.0, 0))
        tips: dict[int, LeaderHit] = {}
        visited = len(starts)
        while q:
            n, d, depth = q.popleft()
            x, y = self.node_xy[n]
            outside = not (far[0] <= x <= far[2] and far[1] <= y <= far[3])
            segs = self.adj[n]
            nxt = [si for si in segs if si not in seen_seg]
            real = [si for si in nxt if self.segs[si].length >= tiny]
            arrow = len(nxt) > len(real)  # tiny segments start here: an arrowhead or a dot
            if outside and depth > 0 and (len(segs) == 1 or arrow):
                tips.setdefault(n, LeaderHit(x, y, d, depth))  # a true dead end (not a closed frame corner)
            if depth >= max_depth:
                continue
            for si in real:
                seen_seg.add(si)
                visited += 1
                if visited > max_segments:
                    return []
                a, b = self.ends[si]
                s = self.segs[si]
                # a T-junction (n lies on the middle of si) continues to both ends of si
                others = [b if a == n else a] if n in (a, b) else [a, b]
                for other in others:
                    if other == n:
                        continue
                    ox, oy = self.node_xy[other]
                    nd = d + (s.length if n in (a, b) else math.hypot(ox - x, oy - y))
                    if other not in dist or nd < dist[other]:
                        dist[other] = nd
                        q.append((other, nd, depth + 1))
        return sorted(tips.values(), key=lambda h: -h.length)
