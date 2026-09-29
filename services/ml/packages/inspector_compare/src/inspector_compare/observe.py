"""Room-level observations from layout artifacts (the room index and tag instances of AG-02B).

For every (stage, element family) the comparator needs, per room token:

- ``elements[page]``: the element labels of that family attributed to the room on that page;
- ``drawn_on``: the family-relevant pages where the room itself is drawn (plan/schematic label, explication);
- geometry (room labels, tags) for the evidence cards.

A page is *relevant* to a family when its sheet title names the family's system (config
``topic_page_patterns`` or the family anchors) or when it carries at least one element of the family. Absence of
an element is only ever concluded on relevant pages where the room is drawn (95 §3.4: absence needs coverage).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from inspector_common.contracts.models import LayoutArtifacts, TableArtifacts, TableCell
from inspector_compare.config import CompareConfig
from inspector_compare.disciplines import plan_mark
from inspector_compare.objectctx import ObjectContext
from inspector_compare.tags import FamilySpec, classify_tag, fold_text

NON_DRAWING_ROOM_SOURCES = frozenset({"EXPLICATION_TABLE", "TEXT_MENTION"})
ROOM_TOKEN = re.compile(r"^-?[0-9]{1,4}(?:[.][0-9]{1,3})*[А-ЯЁа-яёA-Za-z]?$")


@dataclass(frozen=True, slots=True, order=True)
class PageRef:
    stage: str
    file_id: str
    page: int

    def as_evidence(self) -> dict[str, object]:
        return {"stage": self.stage, "file_id": self.file_id, "pdf_page_number": self.page}


@dataclass(slots=True)
class PageInfo:
    ref: PageRef
    sheet_number: str | int | None = None
    sheet_title: str | None = None
    document_code: str | None = None
    revision: str | None = None
    rooms_drawn: set[str] = field(default_factory=set)
    layers: set[str] = field(default_factory=set)  # CAD layers (OCG) used on the page
    topic_tags: set[str] = field(default_factory=set)  # topics of the element tags printed on the page
    revision_cloud_rooms: set[str] = field(default_factory=set)
    revision_labels: set[str] = field(default_factory=set)
    # Every element label of a family printed on the page, attributed to a room or not (mark stability check).
    family_labels: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def plan_mark(self) -> str | None:
        return plan_mark(self.document_code)


@dataclass(slots=True)
class RoomObservation:
    room: str
    elements: dict[PageRef, Counter[str]] = field(default_factory=dict)
    # The same elements without the ambiguous ones: a tag instance (page, box, labels) that the layout links to
    # two or more rooms proves nothing about either room.
    firm: dict[PageRef, Counter[str]] = field(default_factory=dict)
    ambiguous_labels: set[str] = field(default_factory=set)
    drawn_on: set[PageRef] = field(default_factory=set)
    boxes: dict[PageRef, list[list[float]]] = field(default_factory=lambda: defaultdict(list))
    names: set[str] = field(default_factory=set)
    min_confidence: float = 1.0
    text_sources: set[str] = field(default_factory=set)

    @staticmethod
    def _union(pages: Mapping[PageRef, Counter[str]]) -> Counter[str]:
        out: Counter[str] = Counter()
        for counts in pages.values():
            for label, n in counts.items():
                out[label] = max(out[label], n)
        return out

    def combined(self) -> Counter[str]:
        """Union over pages: per label the maximum count on one page (a unit drawn on a plan and on a
        schematic is one unit, not two)."""
        return self._union(self.elements)

    def combined_firm(self) -> Counter[str]:
        """``combined`` over the unambiguously attributed tag instances only."""
        return self._union(self.firm)

    @property
    def element_pages(self) -> list[PageRef]:
        return sorted(p for p, c in self.elements.items() if sum(c.values()) > 0)

    @property
    def covered(self) -> bool:
        """The room is drawn on (or carries elements on) at least one relevant page of this stage."""
        return bool(self.drawn_on or self.element_pages)

    def coverage_pages(self) -> list[PageRef]:
        return sorted(self.drawn_on | set(self.element_pages))


@dataclass(slots=True)
class StageFamilyView:
    stage: str
    family: str
    rooms: dict[str, RoomObservation] = field(default_factory=dict)
    relevant_pages: set[PageRef] = field(default_factory=set)

    def room(self, token: str) -> RoomObservation:
        obs = self.rooms.get(token)
        if obs is None:
            obs = self.rooms[token] = RoomObservation(token)
        return obs


def norm_room(token: str | None) -> str | None:
    """The room token exactly as printed (leading zeros kept), or None when it is not a room number."""
    if token is None:
        return None
    t = token.strip()
    return t if ROOM_TOKEN.match(t) else None


def _cell_text(cell: TableCell | None) -> str | None:
    """A table cell as printed: the raw text (keeps «012»), else the normalised value."""
    if cell is None:
        return None
    if cell.raw is not None and str(cell.raw).strip():
        return str(cell.raw).strip()
    return None if cell.value is None else str(cell.value).strip() or None


@dataclass(frozen=True, slots=True)
class _RoomHit:
    ref: PageRef
    room: str
    source: str
    name: str | None
    bbox: tuple[float, ...] | None


@dataclass(frozen=True, slots=True)
class _TagHit:
    ref: PageRef
    room: str
    family: str
    kind: str | None
    labels: tuple[str, ...]
    bbox: tuple[float, ...] | None
    confidence: float | None
    text_source: str | None


class Observations:
    """All room observations of one object (built once per compare run)."""

    def __init__(self, ctx: ObjectContext, cfg: CompareConfig, specs: Mapping[str, FamilySpec]):
        self.ctx = ctx
        self.cfg = cfg
        self.specs = {f: s for f, s in specs.items() if f in cfg.families}
        # Every family of the compared topics: their tags make a sheet relevant (a heating plan shows risers
        # and radiators even where no warm floor is drawn).
        topics = {s.topic for s in self.specs.values() if s.topic}
        self.topic_specs = {f: s for f, s in specs.items() if s.topic in topics}
        self.pages: dict[PageRef, PageInfo] = {}
        self.views: dict[tuple[str, str], StageFamilyView] = {}
        self._topic = {k: re.compile(v) for k, v in cfg.topic_page_patterns.items()}
        self._room_hits: list[_RoomHit] = []
        self._tag_hits: list[_TagHit] = []
        # (stage, family, room) → pages where a tag attributed to the room names the family by an anchor phrase
        # («М.О.» for local exhaust): the element is drawn there even when its mark is not printed.
        self._anchor_pages: dict[tuple[str, str, str], set[PageRef]] = defaultdict(set)
        self._file_marks: dict[str, tuple[str, ...]] = {}
        self._names: dict[tuple[str, str], set[str]] = defaultdict(set)  # (stage, room) → names
        self._name_votes: dict[str, Counter[str]] = defaultdict(Counter)  # room → name occurrences, any stage
        self._build()

    # ── public ────────────────────────────────────────────────────────────────────────────────

    def view(self, stage: str, family: str) -> StageFamilyView:
        key = (stage, family)
        if key not in self.views:
            self.views[key] = StageFamilyView(stage, family)
        return self.views[key]

    def page(self, ref: PageRef) -> PageInfo:
        info = self.pages.get(ref)
        if info is None:
            info = self.pages[ref] = PageInfo(ref)
        return info

    def title_score(self, ref: PageRef, family: str) -> int:
        """How well a page names the family's system: sheet title (topic +1, family anchor +2), CAD layers of the
        topic used on the page (+1)."""
        info = self.pages.get(ref)
        spec = self.specs.get(family)
        if info is None or spec is None:
            return 0
        score = 0
        pattern = self._topic.get(spec.topic or "")
        if info.sheet_title:
            title = fold_text(info.sheet_title)
            if pattern is not None and pattern.search(title):
                score += 1
            if any(p.search(title) for p in spec.anchor_patterns):
                score += 2
        if pattern is not None and any(pattern.search(fold_text(layer)) for layer in info.layers):
            score += 1
        return score

    def is_relevant(self, ref: PageRef, family: str) -> bool:
        """The sheet shows the family's system: title or layers name it, or it carries tags of that system."""
        spec = self.specs.get(family)
        info = self.pages.get(ref)
        if spec is None or info is None:
            return False
        return self.title_score(ref, family) > 0 or (spec.topic is not None and spec.topic in info.topic_tags)

    def title_topics(self, ref: PageRef) -> set[str]:
        """Configured topics the sheet title names (empty when the page has no title or a topic-neutral one)."""
        info = self.pages.get(ref)
        if info is None or not info.sheet_title:
            return set()
        title = fold_text(info.sheet_title)
        return {topic for topic, pattern in self._topic.items() if pattern.search(title)}

    def on_discipline(self, file_id: str, family: str) -> bool:
        """The file may carry the family's elements: its discipline marks meet the family's disciplines (config
        ``discipline_scoped_families``); a file without marks, or a family without disciplines, always may."""
        spec = self.specs.get(family) or self.topic_specs.get(family)
        marks = self._file_marks.get(file_id, ())
        if not self.cfg.discipline_scoped_families or spec is None or not spec.disciplines or not marks:
            return True
        return bool(set(spec.disciplines) & set(marks))

    def covers(self, ref: PageRef, family: str) -> bool:
        """The page may prove the *absence* of the family's elements in a room drawn on it: a relevant page whose
        title, when it names any configured topic, names the family's own topic (``title_authoritative_coverage``).
        A heating plan that also shows vent shafts, or a conditioning plan, never proves «no ventilation»."""
        spec = self.specs.get(family)
        if spec is None or not self.on_discipline(ref.file_id, family):
            return False
        if self.cfg.title_authoritative_coverage:
            topics = self.title_topics(ref)
            if topics:
                if spec.topic in topics:
                    return True
                info = self.pages.get(ref)
                title = fold_text(info.sheet_title) if info and info.sheet_title else ""
                return any(p.search(title) for p in spec.anchor_patterns)
        return self.is_relevant(ref, family)

    def sheet_labels(self, refs: Iterable[PageRef], family: str) -> set[str]:
        """Every label of the family printed on these pages, whichever room (if any) the layout linked it to."""
        out: set[str] = set()
        for ref in refs:
            info = self.pages.get(ref)
            if info is not None:
                out |= info.family_labels.get(family, set())
        return out

    def anchor_pages(self, stage: str, family: str, room: str) -> set[PageRef]:
        """Pages of ``stage`` where a tag linked to ``room`` names the (label) family by an anchor phrase."""
        return set(self._anchor_pages.get((stage, family, room), set()))

    def names_of(self, stage: str, room: str) -> set[str]:
        return set(self._names.get((stage, room), set()))

    # ── building ──────────────────────────────────────────────────────────────────────────────

    def room_name(self, room: str) -> str | None:
        """The room's name for display: the name printed most often for the token on any stage (room index and
        explications vote; a stray label near the room is outvoted). None when that name is a continuation line
        of a split explication cell (lower case, «моделирования и конструирования»)."""
        votes = self._name_votes.get(room)
        if not votes:
            return None
        name = min(votes, key=lambda n: (-votes[n], n))
        return name if name[:1].isupper() else None

    def room_names(self, room: str) -> set[str]:
        """Names of a room token on any stage (a vent chamber named in the RD explication is one in the PD too)."""
        out: set[str] = set()
        for (_stage, token), names in self._names.items():
            if token == room:
                out.update(names)
        return out

    def _build(self) -> None:
        kinds = {
            f: tuple(dict.fromkeys((*rule.tag_kinds, *rule.room_kinds)))
            for f, rule in self.cfg.families.items()
        }
        for file_id, layout in sorted(self.ctx.layouts.items()):
            info = self.ctx.files.get(file_id)
            if info is None or info.stage is None or not info.citable or not info.is_pdf:
                continue
            self._file_marks[file_id] = tuple(info.marks)
            self._read_layout(layout, info.stage, kinds)
        # Room names from the explications (AG-02C typed tables): the room-name rules (a unit mark counts only in
        # a vent chamber) and the rationale text use them; tables never prove that a room is drawn on a sheet.
        for file_id, tables in sorted(self.ctx.tables.items()):
            info = self.ctx.files.get(file_id)
            if info is None or info.stage is None or not info.citable or not info.is_pdf:
                continue
            self._read_explications(tables, info.stage)

        # A tag instance linked to several rooms (one leader read for two rooms) is ambiguous for all of them when
        # the family counts individual elements (a unit or a branch stands in one room); a presence anchor («тёплый
        # пол» with one callout for rooms 267–272) legitimately serves several rooms.
        rooms_of_instance: dict[tuple[Any, ...], set[str]] = defaultdict(set)
        for hit in self._tag_hits:
            if hit.bbox is not None and self.cfg.families[hit.family].mode != "PRESENCE":
                rooms_of_instance[(hit.ref, hit.family, hit.bbox, hit.labels)].add(hit.room)
        ambiguous = {key for key, rooms in rooms_of_instance.items() if len(rooms) > 1}

        # Element observations (tags attributed to rooms); kinds accepted only in named rooms are checked here.
        for hit in self._tag_hits:
            rule = self.cfg.families[hit.family]
            if rule.exclude_room_name_pattern and any(
                re.search(rule.exclude_room_name_pattern, fold_text(n)) for n in self.room_names(hit.room)
            ):
                continue
            if hit.kind is not None and hit.kind not in rule.tag_kinds:
                if not rule.room_name_pattern:
                    continue
                if not any(
                    re.search(rule.room_name_pattern, fold_text(n)) for n in self.room_names(hit.room)
                ):
                    continue
            view = self.view(hit.ref.stage, hit.family)
            view.relevant_pages.add(hit.ref)
            obs = view.room(hit.room)
            counts = obs.elements.setdefault(hit.ref, Counter())
            # One element per distinct label per page: a branch annotated twice («В2.3», «В2.3,4 −150 м³/ч») is
            # one branch; distinct units carry distinct labels (П17 → П17.1 + П17.2).
            for label in hit.labels:
                counts[label] = 1
            if (hit.ref, hit.family, hit.bbox, hit.labels) in ambiguous:
                obs.ambiguous_labels.update(hit.labels)
            else:
                firm = obs.firm.setdefault(hit.ref, Counter())
                for label in hit.labels:
                    firm[label] = 1
            if hit.bbox:
                obs.boxes[hit.ref].append(list(hit.bbox))
            if hit.confidence is not None:
                obs.min_confidence = min(obs.min_confidence, hit.confidence)
            if hit.text_source:
                obs.text_sources.add(hit.text_source)

        # Pages relevant by their title, CAD layers or system tags (plans and schematics of the family's system).
        for ref in list(self.pages):
            for family in self.specs:
                if self.is_relevant(ref, family):
                    self.view(ref.stage, family).relevant_pages.add(ref)

        # Rooms drawn on relevant pages (coverage for absence) and their label boxes and names.
        allowed = set(self.cfg.actual_room_sources)
        by_ref: dict[PageRef, list[_RoomHit]] = defaultdict(list)
        for hit in self._room_hits:
            by_ref[hit.ref].append(hit)
        for (stage, family), view in list(self.views.items()):
            for ref in sorted(view.relevant_pages):
                covers = self.covers(ref, family)
                for hit in by_ref.get(ref, []):
                    if hit.source not in allowed and hit.room not in view.rooms:
                        continue
                    if not covers and hit.room not in view.rooms:
                        continue
                    obs = view.room(hit.room)
                    if hit.source in allowed and covers:
                        obs.drawn_on.add(ref)
                    # Evidence geometry marks where the room is drawn: a row of the explication or a mention in
                    # the text lists the number elsewhere on the sheet and would stretch the card's region.
                    if (
                        hit.bbox
                        and hit.source not in NON_DRAWING_ROOM_SOURCES
                        and list(hit.bbox) not in obs.boxes[ref]
                    ):
                        obs.boxes[ref].append(list(hit.bbox))
            for room, obs in view.rooms.items():
                obs.names.update(self._names.get((stage, room), set()))

    def _read_explications(self, tables: TableArtifacts, stage: str) -> None:
        for table in tables.tables:
            if str(getattr(table.table_type, "value", table.table_type)) != "EXPLICATION":
                continue
            for row in table.rows:
                kind = str(getattr(row.kind, "value", row.kind)) if row.kind is not None else "DATA"
                if kind != "DATA":
                    continue
                number, name = row.cells.get("room_no"), row.cells.get("name")
                token = norm_room(_cell_text(number))
                text = _cell_text(name)
                if token is not None and text:
                    text = " ".join(text.split())
                    self._names[(stage, token)].add(text)
                    self._name_votes[token][text] += 1

    def _read_layout(self, layout: LayoutArtifacts, stage: str, kinds: Mapping[str, tuple[str, ...]]) -> None:
        file_id = layout.file_id
        for tb in layout.title_blocks or []:
            p = self.page(PageRef(stage, file_id, tb.pdf_page_number))
            if tb.sheet_number is not None:
                p.sheet_number = tb.sheet_number
            p.sheet_title = tb.sheet_title or p.sheet_title
            p.document_code = tb.document_code or p.document_code
            p.revision = tb.revision or p.revision
        for entry in layout.sheet_page_map or []:
            p = self.page(PageRef(stage, file_id, entry.pdf_page_number))
            if p.sheet_number is None and entry.sheet_number is not None:
                p.sheet_number = entry.sheet_number
            p.sheet_title = p.sheet_title or entry.sheet_title
            p.document_code = p.document_code or entry.document_code
        for layer in layout.cad_layers or []:
            for page_no in layer.pages or []:
                self.page(PageRef(stage, file_id, page_no)).layers.add(layer.name)
        for cloud in layout.revision_clouds or []:
            p = self.page(PageRef(stage, file_id, cloud.pdf_page_number))
            p.revision_cloud_rooms.update(r for r in (norm_room(x) for x in cloud.rooms_covered or []) if r)
            if cloud.revision_label:
                p.revision_labels.add(cloud.revision_label)
        for entry in layout.rooms or []:
            room = norm_room(entry.room_token)
            if room is None:
                continue
            ref = PageRef(stage, file_id, entry.pdf_page_number)
            source = str(entry.source.value if hasattr(entry.source, "value") else entry.source)
            if source in self.cfg.actual_room_sources:
                self.page(ref).rooms_drawn.add(room)
            else:
                self.page(ref)
            if entry.name:
                name = " ".join(entry.name.split())
                self._names[(stage, room)].add(name)
                self._name_votes[room][name] += 1
            self._room_hits.append(
                _RoomHit(ref, room, source, entry.name, tuple(entry.bbox) if entry.bbox else None)
            )
        open_kinds = {f: () for f in self.topic_specs}
        for tag in layout.tags or []:
            ref = PageRef(stage, file_id, tag.pdf_page_number)
            page = self.page(ref)
            kind = tag.tag_kind.value if hasattr(tag.tag_kind, "value") else str(tag.tag_kind)
            for family in classify_tag(tag.tag, kind, self.topic_specs, open_kinds):
                topic = self.topic_specs[family].topic
                if topic:
                    page.topic_tags.add(topic)
            for family, labels in classify_tag(tag.tag, kind, self.specs, kinds).items():
                if self.on_discipline(file_id, family):
                    page.family_labels[family].update(labels)
            room = norm_room(tag.room_token)
            if room is None:
                continue
            for family, spec in self.specs.items():
                if (
                    spec.patterns
                    and spec.anchor_patterns
                    and self.on_discipline(file_id, family)
                    and spec.matches_phrase(tag.tag)
                ):
                    self._anchor_pages[(stage, family, room)].add(ref)
            prov = tag.provenance
            for family, labels in classify_tag(tag.tag, kind, self.specs, kinds).items():
                if not self.on_discipline(file_id, family):
                    continue
                self._tag_hits.append(
                    _TagHit(
                        ref,
                        room,
                        family,
                        kind,
                        tuple(labels),
                        tuple(tag.bbox) if tag.bbox else None,
                        float(prov.confidence) if prov is not None and prov.confidence is not None else None,
                        (
                            str(
                                prov.text_source.value
                                if hasattr(prov.text_source, "value")
                                else prov.text_source
                            )
                            if prov is not None and prov.text_source is not None
                            else None
                        ),
                    )
                )
