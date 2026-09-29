"""Per-room inventories of a sheet: the multiset of marks and elements attached to each room (95 §3.4).

Built from a LayoutArtifacts document (``rooms`` + ``tags``), so any consumer (AG-04 comparators, AG-07 FREE
search, the web viewer) gets the same answer from the published artifact. Every plan/schematic room label
of the page gets an inventory, **also when it is empty**: «no local exhaust in 140» is itself the finding of
G-TR-003, so an empty inventory is data, provided the page was fully read (``ocr_covered``).

Subkinds refine the contract ``tag_kind`` for comparisons (derived from ``tag_norm`` by the grammar):
``branch`` «В2.4», ``system`` «П2», ``natural`` «ВЕ», ``terminal`` «АМН-К 400×150», ``local_exhaust`` «М.О.»,
``equipment``, ``radiator``, ``riser``, ``pipeline``, ``warm_floor``, ``flow`` «L=-950», ``size``, ``heat``,
``temperature``, ``level``, ``position``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from inspector_layout.rooms.grammar import LIST_SEP, mark_elements, vent_subkind

LABEL_SOURCES = ("PLAN_LABEL", "SCHEMATIC_LABEL")
ROOM_SEMANTIC = ("branch", "system", "natural", "terminal", "local_exhaust", "equipment", "radiator", "riser",
                 "warm_floor", "pipeline")  # fmt: skip


def tag_elements(tag: dict[str, Any]) -> list[str]:
    """Elements of one TagInstance: «В2.7, В2.8, В2.9» (a printed vent list) → three branches."""
    return mark_elements(str(tag.get("tag_norm") or tag.get("tag") or ""), tag.get("tag_kind"))


def tag_subkind(tag: dict[str, Any], element: str | None = None) -> str:
    """Subkind of a TagInstance (or of one of its ``element``s)."""
    kind = tag.get("tag_kind")
    norm = element if element is not None else str(tag.get("tag_norm") or tag.get("tag") or "")
    if kind == "VENT_SYSTEM":
        norm = norm.split(LIST_SEP, 1)[0]
        return vent_subkind(norm)
    if kind == "AIR_TERMINAL":
        return "terminal"
    if kind == "PIPE_RISER":
        return "riser"
    if kind == "HEATING_SYSTEM":
        return "warm_floor" if ("пол" in norm or norm.startswith("ТП")) else "pipeline"
    if kind == "EQUIPMENT":
        if norm.startswith("М.О.") or norm.lower() == "зонт":
            return "local_exhaust"
        if re.match(r"^(?:[A-Za-zА-Яа-я]+\s+)*\d{2}-\d{3}-\d{3,4}$", norm):
            return "radiator"
        if norm.lower() == "multibox":
            return "warm_floor"
        return "equipment"
    if kind == "LEVEL_MARK":
        return "level"
    if norm.startswith("L="):
        return "flow"
    if norm.startswith("Q="):
        return "heat"
    if norm.startswith("t="):
        return "temperature"
    if norm.startswith("поз."):
        return "position"
    if re.match(r"^(?:Ø\d|\d{2,4}×\d)", norm):
        return "size"
    return "other"


@dataclass(slots=True)
class RoomInventory:
    file_id: str | None
    pdf_page_number: int
    room_token: str
    label_source: str | None = None
    name: str | None = None
    floor: str | None = None
    sheet_number: Any = None
    ocr_covered: bool = True
    items: list[dict[str, Any]] = field(default_factory=list)

    def multiset(self, subkinds: Iterable[str] | None = ROOM_SEMANTIC, min_conf: float = 0.0) -> Counter:
        want = set(subkinds) if subkinds is not None else None
        c: Counter = Counter()
        for t in self.items:
            conf = (t.get("provenance") or {}).get("confidence", 1.0)
            if conf < min_conf:
                continue
            for element in tag_elements(t):
                if want is None or tag_subkind(t, element) in want:
                    c[element] += 1
        return c

    def tags_of(self, *subkinds: str, min_conf: float = 0.0) -> list[str]:
        """Distinct tags of the given subkinds, in a stable order («В2.2», «В2.3», «В2.10»)."""
        return sorted(self.multiset(subkinds, min_conf), key=_natural)

    @property
    def branches(self) -> list[str]:
        return self.tags_of("branch")

    @property
    def systems(self) -> list[str]:
        return self.tags_of("system", "natural")

    @property
    def local_exhausts(self) -> int:
        return sum(self.multiset(("local_exhaust",)).values())

    def summary(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "pdf_page_number": self.pdf_page_number,
            "room": self.room_token,
            "name": self.name,
            "floor": self.floor,
            "ocr_covered": self.ocr_covered,
            "branches": self.branches,
            "systems": self.systems,
            "terminals": self.tags_of("terminal"),
            "local_exhausts": self.local_exhausts,
            "equipment": self.tags_of("equipment", "radiator", "warm_floor"),
            "heating": self.tags_of("riser", "pipeline", "warm_floor"),
            "flows": self.tags_of("flow"),
            "links": dict(Counter(t.get("room_link") for t in self.items)),
        }


def _natural(tag: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", tag)]


def inventories(layout: dict[str, Any]) -> dict[tuple[int, str], RoomInventory]:
    """(page, room) → inventory for every plan/schematic room label of the document."""
    file_id = layout.get("file_id")
    covered = {
        p["page"]: p.get("tokens") == "PAGE_TOKENS"
        for p in ((layout.get("ext") or {}).get("rooms_stage") or {}).get("pages", [])
    }
    out: dict[tuple[int, str], RoomInventory] = {}
    for r in layout.get("rooms") or []:
        if r.get("source") not in LABEL_SOURCES:
            continue
        key = (r["pdf_page_number"], r["room_token"])
        if key not in out:
            out[key] = RoomInventory(file_id, key[0], key[1], r.get("source"), r.get("name"), r.get("floor"),
                                     r.get("sheet_number"), covered.get(key[0], True))  # fmt: skip
    for t in layout.get("tags") or []:
        room = t.get("room_token")
        if not room:
            continue
        key = (t["pdf_page_number"], room)
        inv = out.get(key)
        if inv is None:
            inv = out[key] = RoomInventory(file_id, key[0], room)
        inv.items.append(t)
    return out


def room_inventories(layouts: Iterable[dict[str, Any]], room: str) -> list[RoomInventory]:
    """Every inventory of ``room`` across documents and pages (plans, schematics)."""
    out = []
    for lay in layouts:
        for (_, token), inv in inventories(lay).items():
            if token == room:
                out.append(inv)
    return sorted(out, key=lambda i: (i.file_id or "", i.pdf_page_number))


def page_inventories(layout: dict[str, Any], page: int) -> dict[str, RoomInventory]:
    return {room: inv for (p, room), inv in inventories(layout).items() if p == page}


def by_room(layouts: Iterable[dict[str, Any]]) -> dict[str, list[RoomInventory]]:
    out: dict[str, list[RoomInventory]] = defaultdict(list)
    for lay in layouts:
        for (_, room), inv in inventories(lay).items():
            out[room].append(inv)
    return out
