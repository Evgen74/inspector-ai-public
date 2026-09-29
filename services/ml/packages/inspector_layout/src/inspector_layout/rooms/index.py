"""The cross-sheet room index and PD↔RD plan matching (96 R-15, 95 R8, 97 §2.13 F6).

A room is printed on many pages: plan labels, schematic captions, explication rows, text mentions. The index
answers «where is room 314 drawn?» (F0201 p20, although the gold cites p18 for its group), «which RD sheet shows
the same floor/plan as this PD sheet?» and, per room, «on which RD page do I compare this PD room?».

**Sheet overlap** is set-based and **floor-partitioned**. Two pages match when they label the same rooms: overlap
coefficient |A∩B| / min(|A|, |B|) ≥ ``min_overlap`` with ≥ ``min_shared`` shared rooms, computed for the whole
pages and for every floor subset of both (the floor of a room from its numbering: «142» → 1, «012» → basement,
«1.109» → 1; else the page floor). A principal scheme of all floors (PD F0171 p88: 54 rooms of floors 1–3) thus
matches each floor plan it covers (RD F0201 p18 for floor 1, p20 for floor 3), which whole-page overlap misses.

**Counterparts of a room** (:meth:`RoomIndex.counterparts`) rank the pages of the other stage that label the
room: the topic of the room on the source page (vent / heating, from its own marks: 012 on the PD heat-supply
scheme p104 carries supply units П2…П18, so vent), then the sheet overlap, then plans before details, then the
richness of the room there (a floor plan annotates it; its duplicate sheet or a heating plan does not).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from inspector_layout.rooms.grammar import floor_from_room_number, floor_from_title, fold
from inspector_layout.rooms.inventory import LABEL_SOURCES, ROOM_SEMANTIC, tag_elements, tag_subkind

VENT_SUBKINDS = {"branch", "system", "natural", "terminal", "local_exhaust", "flow"}
HEAT_SUBKINDS = {"riser", "pipeline", "radiator", "warm_floor", "heat", "temperature"}
_TITLE_VENT = re.compile(r"вентиляц|воздуховод|воздухообмен|дымоудал|противодым|кондицион", re.IGNORECASE)
_TITLE_HEAT = re.compile(r"отоплен|теплоснаб|т[её]пл\w*\s+пол|радиатор", re.IGNORECASE)


def topic_of(counts: Counter) -> str | None:
    """«vent» / «heating» when one side has at least twice the marks of the other, «mixed» otherwise."""
    v, h = counts.get("vent", 0), counts.get("heating", 0)
    if not v and not h:
        return None
    return "vent" if v >= 2 * h else "heating" if h >= 2 * v else "mixed"


def title_topic(title: str | None) -> str | None:
    if not title:
        return None
    t = fold(title)
    v, h = bool(_TITLE_VENT.search(t)), bool(_TITLE_HEAT.search(t))
    return "mixed" if v and h else "vent" if v else "heating" if h else None


@dataclass(frozen=True, slots=True)
class RoomOccurrence:
    room: str
    file_id: str
    stage: str | None
    pdf_page_number: int
    source: str
    bbox: tuple[float, ...] | None
    has_zone: bool
    floor: str | None
    sheet_number: Any
    name: str | None


@dataclass(slots=True)
class PageInfo:
    file_id: str
    stage: str | None
    pdf_page_number: int
    rooms: set[str] = field(default_factory=set)
    floor: str | None = None
    kind: str | None = None
    topic: str | None = None  # vent / heating / mixed / None
    sheet_number: Any = None
    title: str | None = None
    room_topics: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    room_marks: Counter = field(default_factory=Counter)  # room → room-semantic elements attached to it

    def floor_groups(self) -> dict[str, set[str]]:
        """Rooms of the page by floor: the room number's floor, else the page's floor, else «?»."""
        out: dict[str, set[str]] = defaultdict(set)
        for r in self.rooms:
            out[floor_from_room_number(r) or _norm_floor(self.floor) or "?"].add(r)
        return out

    def room_topic(self, room: str) -> str | None:
        return topic_of(self.room_topics.get(room, Counter())) or self.topic


def _norm_floor(floor: str | None) -> str | None:
    """Page floors in the room-number scheme: «подвал»/«техподполье» → «0» (rooms «012», «003»)."""
    if floor in ("подвал", "техподполье"):
        return "0"
    return floor


@dataclass(frozen=True, slots=True)
class SheetMatch:
    a_file: str
    a_page: int
    b_file: str
    b_page: int
    shared: tuple[str, ...]
    overlap: float
    jaccard: float
    a_floor: str | None
    b_floor: str | None
    a_topic: str | None
    b_topic: str | None
    basis_floor: str | None = None  # the floor subset that gave the overlap (None: whole pages)

    def as_dict(self) -> dict[str, Any]:
        return {
            "a": {
                "file_id": self.a_file,
                "pdf_page_number": self.a_page,
                "floor": self.a_floor,
                "topic": self.a_topic,
            },
            "b": {
                "file_id": self.b_file,
                "pdf_page_number": self.b_page,
                "floor": self.b_floor,
                "topic": self.b_topic,
            },
            "shared_rooms": len(self.shared),
            "overlap": round(self.overlap, 3),
            "jaccard": round(self.jaccard, 3),
            "basis_floor": self.basis_floor,
        }


@dataclass(frozen=True, slots=True)
class Counterpart:
    """A page of the other stage that labels the room, with the reasons of its rank."""

    room: str
    file_id: str
    pdf_page_number: int
    stage: str | None
    topic: str | None
    topic_match: float  # 1 same topic, 0.5 unknown / mixed, 0 other topic
    overlap: float  # floor-partitioned sheet overlap with the source page
    kind: str | None
    marks: int  # room-semantic elements attached to the room on that page
    has_zone: bool

    @property
    def rank_key(self) -> tuple:
        plan = 1 if self.kind == "PLAN" else 0
        return (-self.topic_match, -round(self.overlap, 2), -plan, -self.marks, -int(self.has_zone),
                self.file_id, self.pdf_page_number)  # fmt: skip

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "pdf_page_number": self.pdf_page_number,
            "stage": self.stage,
            "topic": self.topic,
            "topic_match": self.topic_match,
            "overlap": round(self.overlap, 3),
            "kind": self.kind,
            "marks": self.marks,
            "has_zone": self.has_zone,
        }


def sheet_overlap(a: PageInfo, b: PageInfo, min_shared: int = 3) -> tuple[float, set[str], str | None]:
    """(overlap, shared rooms, basis floor): the best of the whole-page and the per-floor overlaps."""
    shared = a.rooms & b.rooms
    best, basis = 0.0, None
    if len(shared) >= min_shared and a.rooms and b.rooms:
        best = len(shared) / min(len(a.rooms), len(b.rooms))
    ga, gb = a.floor_groups(), b.floor_groups()
    for fl in ga.keys() & gb.keys():
        if fl == "?":
            continue
        s = ga[fl] & gb[fl]
        if len(s) >= min_shared:
            ov = len(s) / min(len(ga[fl]), len(gb[fl]))
            if ov > best + 1e-9:
                best, basis = ov, fl
    return best, shared, basis


class RoomIndex:
    def __init__(self) -> None:
        self.by_room: dict[str, list[RoomOccurrence]] = defaultdict(list)
        self.pages: dict[tuple[str, int], PageInfo] = {}

    @classmethod
    def from_layouts(
        cls, layouts: Iterable[dict[str, Any]], stages: dict[str, str | None] | None = None
    ) -> RoomIndex:
        idx = cls()
        for lay in layouts:
            idx.add_layout(lay, (stages or {}).get(lay["file_id"]) or lay.get("stage"))
        return idx

    def add_layout(self, layout: dict[str, Any], stage: str | None = None) -> None:
        fid = layout["file_id"]
        stage = stage or layout.get("stage")
        meta = {p["page"]: p for p in ((layout.get("ext") or {}).get("rooms_stage") or {}).get("pages", [])}
        stamp_titles = {
            tb["pdf_page_number"]: tb.get("sheet_title")
            for tb in layout.get("title_blocks") or []
            if tb.get("sheet_title")
        }
        topics: dict[int, Counter] = defaultdict(Counter)
        room_topics: dict[int, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        room_marks: dict[int, Counter] = defaultdict(Counter)
        for t in layout.get("tags") or []:
            page, room = t["pdf_page_number"], t.get("room_token")
            for el in tag_elements(t):
                sk = tag_subkind(t, el)
                topic = "vent" if sk in VENT_SUBKINDS else "heating" if sk in HEAT_SUBKINDS else None
                if topic:
                    topics[page][topic] += 1
                    if room:
                        room_topics[page][room][topic] += 1
                if room and sk in ROOM_SEMANTIC:
                    room_marks[page][room] += 1
        for r in layout.get("rooms") or []:
            page = r["pdf_page_number"]
            occ = RoomOccurrence(r["room_token"], fid, stage, page, r["source"], tuple(r.get("bbox") or ()) or None,
                                 bool(r.get("zone")), r.get("floor"), r.get("sheet_number"), r.get("name"))  # fmt: skip
            self.by_room[r["room_token"]].append(occ)
            info = self.pages.get((fid, page))
            if info is None:
                m = meta.get(page, {})
                title = stamp_titles.get(page) or m.get("title")
                topic = topic_of(topics.get(page, Counter())) or title_topic(title)
                floor = r.get("floor") or m.get("floor") or floor_from_title(title or "")
                info = self.pages[(fid, page)] = PageInfo(fid, stage, page, set(), floor, m.get("kind"), topic,
                                                          r.get("sheet_number"), title)  # fmt: skip
                info.room_topics = room_topics.get(page, defaultdict(Counter))
                info.room_marks = room_marks.get(page, Counter())
            if r["source"] in LABEL_SOURCES:
                info.rooms.add(r["room_token"])

    def locate(
        self, room: str, stage: str | None = None, sources: Iterable[str] = LABEL_SOURCES
    ) -> list[RoomOccurrence]:
        want = set(sources)
        return [
            o for o in self.by_room.get(room, []) if o.source in want and (stage is None or o.stage == stage)
        ]

    def pages_of(self, room: str, stage: str | None = None) -> list[tuple[str, int]]:
        return sorted({(o.file_id, o.pdf_page_number) for o in self.locate(room, stage)})

    def match_sheets(
        self, a_stage: str = "PD", b_stage: str = "RD", *, min_shared: int = 3, min_overlap: float = 0.3
    ) -> list[SheetMatch]:
        a_pages = [p for p in self.pages.values() if p.stage == a_stage and len(p.rooms) >= min_shared]
        b_pages = [p for p in self.pages.values() if p.stage == b_stage and len(p.rooms) >= min_shared]
        out = []
        for a in a_pages:
            for b in b_pages:
                overlap, shared, basis = sheet_overlap(a, b, min_shared)
                if overlap < min_overlap:
                    continue
                jac = len(shared) / len(a.rooms | b.rooms)
                out.append(SheetMatch(a.file_id, a.pdf_page_number, b.file_id, b.pdf_page_number,
                                      tuple(sorted(shared)), overlap, jac, a.floor, b.floor, a.topic, b.topic,
                                      basis))  # fmt: skip
        out.sort(key=lambda m: (m.a_file, m.a_page, -m.overlap, -len(m.shared), m.b_file, m.b_page))
        return out

    def counterparts(
        self, room: str, file_id: str, page: int, b_stage: str = "RD", *, min_shared: int = 2
    ) -> list[Counterpart]:
        """Pages of ``b_stage`` that label ``room``, best first (see the module docstring)."""
        a = self.pages.get((file_id, page))
        if a is None:
            return []
        want = a.room_topic(room)
        out = []
        for fid, p in self.pages_of(room, b_stage):
            b = self.pages[(fid, p)]
            if want in ("vent", "heating") and b.topic in ("vent", "heating"):
                tm = 1.0 if b.topic == want else 0.0
            else:
                tm = 0.5
            ov, _, _ = sheet_overlap(a, b, min_shared)
            zone = any(o.has_zone for o in self.locate(room) if (o.file_id, o.pdf_page_number) == (fid, p))
            out.append(
                Counterpart(room, fid, p, b.stage, b.topic, tm, ov, b.kind, b.room_marks.get(room, 0), zone)
            )
        out.sort(key=lambda c: c.rank_key)
        return out

    def counterpart_pages(self, room: str, file_id: str, page: int, b_stage: str = "RD") -> list[SheetMatch]:
        """Sheets of ``b_stage`` that match the given page and label ``room`` too."""
        return [
            m for m in self.match_sheets(self.pages[(file_id, page)].stage or "PD", b_stage)
            if m.a_file == file_id and m.a_page == page and room in m.shared
        ]  # fmt: skip
