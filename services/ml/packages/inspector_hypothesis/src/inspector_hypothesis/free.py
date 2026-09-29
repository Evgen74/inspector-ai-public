"""FREE-<TOPIC>-<NNN> findings: evidence-bound element changes outside the matrix (97 §2.10, 93 §3.7, 07 §3.3.2).

Detector HR-SEM-005 «element present in PD rooms, absent in RD» (method SEMANTIC_DISSONANCE), for every element
family whose ELEMENT_MISSING change routes to FREE-* in the seed change map (a matrix gap; warm floors →
FREE-HEATING, gold G-TR-002):

1. **PD assertion** — a sentence of the PD that names the element («тёплые полы», «Multibox») and lists rooms
   («(пом. 267, 270, 271, 272)»), not negated. The room list nearest to the family's anchor is taken; a list
   closer to another family's anchor is left to that family. Drawings only confirm: plan labels next to a
   drawing's leader are not trusted on their own (neighbouring rooms 266/268/277 sit as close as the asserted ones).
   Two channels feed it: the PageTokens themselves and AG-02C's ``pd.element_room`` values (97 §3.3); AG-02C's TEXT
   and TABLE assertions pass the same negation and nearest-family checks, its LABEL and SPEC values only confirm.
2. **RD absence** — the family's anchors are searched in every recognised RD page of the family's discipline
   (plus RD files of an unknown section). A room whose label has an anchor nearby keeps the element (no finding).
   Absence is DOCUMENT-level when no anchor is found and every page of the discipline RD was read; COUNTERPART-level
   when only the RD document holding the anchor page was read in full; ROOM-level when the element occurs elsewhere
   in the RD. Unread pages never prove absence. A mention inside a removal statement («исключены тёплые полы»,
   «не предусмотрен») is not presence: it supports the absence.
3. **Anchor pages** — one per stage for the whole group (97 §2.5, 93 §2.8): the page that shows the majority of the
   group's rooms, preferring large-format drawings, pages and documents of the family's topic (a heating plan,
   not a ventilation plan of the same floor) and pages with a CAD revision cloud over the rooms (AG-02B).
4. **Export** — only BOUND groups (PD and RD anchor pages, rooms located) with DOCUMENT or COUNTERPART absence and
   confidence ≥ the threshold; at most ``max_free_groups_per_object`` (seed policy, 5) groups, the most confident
   kept; numbered per topic in the order (PD file_id, PD page, first location) → one heating group is exactly
   FREE-HEATING-001. Everything else stays a SUSPICION for Раздел 6 (never counted as a violation).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any, Literal

from inspector_common.contracts.codes import free_code
from inspector_common.contracts.enums import (
    ComparisonAxis,
    CompletenessStatus,
    CriticalityLevel,
    DiscoveryMethod,
    DiscrepancyType,
    DocStage,
    EvidenceBindStatus,
    EvidenceRole,
    FindingStatus,
    LocationType,
    MatrixScope,
    PageBasis,
    ProtocolParamStatus,
    ReviewPriority,
    TextOrigin,
    ViolationLabel,
)
from inspector_common.contracts.loader import enum_mappings
from inspector_common.contracts.models import EvidenceRef, Finding, FindingGroup, Geometry, Recommendation
from inspector_common.params import Route, load_change_map
from inspector_hypothesis.elements import ElementFamily, ElementHit, ElementIndex, PageMeta, free_families
from inspector_hypothesis.inputs import DocumentInfo, HypothesisInputs, PageText
from inspector_hypothesis.textmatch import is_negated, is_prose, norm_word, room_lists, sentences

RULE_CODE = "HR-SEM-005"
RULE_VERSION = "2"
DETECTOR = "ELEMENT_INVENTORY"
DOCUMENT_STATUS_PAIRWISE = "PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK"
MAX_SENTENCE_CHARS = 700
# AG-02C element–room assertions (ExtractedValue fact_key, 97 §3.3): TEXT and TABLE channels assert rooms; LABEL
# (a plan label next to a leader) and SPEC (a specification item, no room) only confirm pages already asserted.
ELEMENT_ROOM_FACT = "pd.element_room"
ASSERTING_CHANNELS = frozenset({"TEXT", "TABLE"})
CONFIRMING_CHANNELS = frozenset({"LABEL", "SPEC"})
REMOVAL_WINDOW_CHARS = (
    60  # a negation this close to an RD mention (same sentence) makes it a removal statement
)
_WORD_SPAN = re.compile(r"[^\s/]+")

Absence = Literal["DOCUMENT", "COUNTERPART", "ROOM", "PRESENT", "UNKNOWN", "NO_RD"]
ABSENCE_FACTOR: dict[str, float] = {
    "DOCUMENT": 1.0,
    "COUNTERPART": 0.85,
    "ROOM": 0.7,
    "UNKNOWN": 0.0,
    "PRESENT": 0.0,
    "NO_RD": 0.0,
}
EXPORTABLE_ABSENCE = frozenset({"DOCUMENT", "COUNTERPART"})


@dataclass(frozen=True, slots=True)
class FreeConfig:
    min_confidence: float = 0.7
    max_groups: int | None = (
        None  # None → seed policy (change_matrix_map.json policy.max_free_groups_per_object)
    )
    room_radius_frac: float = (
        0.10  # an RD anchor this close (× min page side) to a room label = element present
    )
    min_anchor_room_share: float = 0.5  # majority rule for anchor pages


@dataclass(slots=True)
class RoomAssertion:
    family: str
    rooms: list[str]
    file_id: str
    page_no: int
    quote: str
    phrase: str
    bbox: tuple[float, float, float, float] | None
    source: str = "PAGE_TOKENS"  # or AG02C_TEXT / AG02C_TABLE (pd.element_room values)
    corroborated: bool = False  # the other channel asserted the same rooms on the same page


@dataclass(frozen=True, slots=True)
class RemovalStatement:
    """An RD sentence that mentions the element as removed or not provided («исключены тёплые полы»)."""

    file_id: str
    page_no: int
    quote: str
    rooms: tuple[str, ...]


@dataclass(slots=True)
class PageScore:
    stage: str
    file_id: str
    page_no: int
    rooms: list[str]
    share: float
    family_hit: bool
    topic_page: bool
    doc_topic_share: float
    large: bool
    cloud_rooms: list[str]
    score: float
    room_boxes: dict[str, list[tuple[float, float, float, float]]] = field(default_factory=dict)
    hit_boxes: list[tuple[float, float, float, float]] = field(default_factory=list)


@dataclass(slots=True)
class FreeCandidate:
    family: ElementFamily
    route: Route
    rooms: list[str]
    assertions: list[RoomAssertion]
    pd_anchor: PageScore | None
    rd_anchor: PageScore | None
    pd_support: list[PageScore]
    location_pages: dict[str, list[tuple[str, str, int]]]
    present_rooms: dict[str, str]
    absence: Absence
    rd_read: int
    rd_total: int
    confidence: float
    confidence_terms: dict[str, float]
    reasons: list[str]
    parameter_code: str | None = None
    exported: bool = False
    removals: list[RemovalStatement] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)  # assertions per channel, «corroborated» count

    @property
    def topic(self) -> str:
        return self.route.free_topic.value if self.route.free_topic else self.family.topic

    @property
    def bind_status(self) -> EvidenceBindStatus:
        if self.pd_anchor is not None and self.rd_anchor is not None and self.rooms:
            return EvidenceBindStatus.BOUND
        if self.pd_anchor is not None or self.rd_anchor is not None:
            return EvidenceBindStatus.PARTIAL
        return EvidenceBindStatus.UNBOUND

    @property
    def order_key(self) -> tuple[str, int, str]:
        pd = self.pd_anchor
        return (pd.file_id if pd else "~", pd.page_no if pd else 0, self.rooms[0] if self.rooms else "")


# ───────────────────────────────────────────── helpers ─────────────────────────────────────────────


def natural_key(token: str) -> tuple[float, str]:
    m = re.match(r"^-?\d+(?:\.\d+)?", token)
    return (float(m.group(0)) if m else float("inf"), token)


def _center(b: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _clouds(
    inputs: HypothesisInputs, file_id: str, page_no: int, room_boxes: Mapping[str, list[Any]]
) -> list[str]:
    """Group rooms under a CAD revision cloud of this page (AG-02B layout): named by the cloud or inside its bbox."""
    layout = inputs.layouts.get(file_id)
    if layout is None:
        return []
    covered: set[str] = set()
    for cloud in layout.revision_clouds or []:
        if cloud.pdf_page_number != page_no:
            continue
        covered.update(r for r in cloud.rooms_covered or [] if r in room_boxes)
        x0, y0, x1, y1 = cloud.bbox
        for room, boxes in room_boxes.items():
            if any(x0 <= _center(b)[0] <= x1 and y0 <= _center(b)[1] <= y1 for b in boxes):
                covered.add(room)
    return sorted(covered, key=natural_key)


@cache
def _free_recommendations() -> dict[str, Any]:
    text = (
        resources.files("inspector_hypothesis")
        .joinpath("data/free_recommendations.json")
        .read_text(encoding="utf-8")
    )
    doc = json.loads(text)
    return {"prefix": doc["preliminary_prefix"], "topics": {t["topic"]: t for t in doc["free_topics"]}}


def element_noun(route: Route) -> str | None:
    """«Тёплый пол» from the route's PD value template «Тёплый пол предусмотрен»."""
    tpl = (route.data.get("value_templates") or {}).get("pd")
    if not tpl:
        return None
    m = re.match(r"^(.*?)\s+(предусмотрен[аоы]?|отсутству\w*)\s*$", tpl)
    return m.group(1) if m else None


def rooms_ru(rooms: Sequence[str]) -> str:
    return "пом. " + ", ".join(rooms)


def sentence_rooms(sentence: str, family_pos: Sequence[int], other_pos: Sequence[int]) -> list[str]:
    """Rooms of the sentence's room lists that belong to the family: a list closer to another family's anchor than
    to this family's is left to that family (positions are character offsets in ``sentence``)."""
    if not family_pos:
        return []
    rooms: list[str] = []
    for start, end, tokens in room_lists(sentence):
        d_fam = min(min(abs(p - start), abs(p - end)) for p in family_pos)
        if other_pos and min(min(abs(p - start), abs(p - end)) for p in other_pos) < d_fam:
            continue
        rooms.extend(t for t in tokens if t not in rooms)
    return rooms


# ───────────────────────────────────────────── detection ─────────────────────────────────────────────


class FreeDetector:
    def __init__(self, inputs: HypothesisInputs, index: ElementIndex, config: FreeConfig | None = None):
        self.inputs = inputs
        self.index = index
        self.config = config or FreeConfig()
        self.pages_examined = 0

    # PD --------------------------------------------------------------------------------------------
    def assertions(
        self, fam: ElementFamily, doc: DocumentInfo, page: PageText, hits: list[ElementHit]
    ) -> list[RoomAssertion]:
        """Sentences of this page that assert the family in listed rooms."""
        text, owners = page.full_text()
        if not text:
            return []
        hit_words = {i for h in hits for i in range(h.word_start, h.word_end)}
        other_words = {
            i
            for h in self.index.page_hits(doc, page)
            if h.key != fam.family and not h.key.startswith("topic:")
            for i in range(h.word_start, h.word_end)
        }
        char_of_word: dict[int, int] = {}
        for pos, wi in enumerate(owners):
            if wi >= 0 and wi not in char_of_word:
                char_of_word[wi] = pos
        fam_pos = sorted(char_of_word[i] for i in hit_words if i in char_of_word)
        other_pos = sorted(char_of_word[i] for i in other_words if i in char_of_word)
        out: list[RoomAssertion] = []
        for a, b in sentences(text):
            if b - a > MAX_SENTENCE_CHARS:
                continue  # a drawing's label soup, not a sentence
            in_sent = [p for p in fam_pos if a <= p < b]
            if not in_sent:
                continue
            sent = text[a:b]
            if is_negated(sent) or not is_prose(sent):
                continue  # a negated statement, or a table row / label soup rather than a sentence
            others = [p - a for p in other_pos if a <= p < b]
            rooms = sentence_rooms(sent, [p - a for p in in_sent], others)
            if not rooms:
                continue
            words = {owners[p] for p in range(a, b) if owners[p] >= 0}
            boxes = [page.words[i].bbox for i in words]
            bbox = (
                min(x[0] for x in boxes),
                min(x[1] for x in boxes),
                max(x[2] for x in boxes),
                max(x[3] for x in boxes),
            )
            phrase = next(
                (h.phrase for h in hits if a <= char_of_word.get(h.word_start, -1) < b), hits[0].phrase
            )
            out.append(
                RoomAssertion(fam.family, rooms, doc.file_id, page.page_no, sent.strip(), phrase, bbox)
            )
        return out

    def _anchor_positions(self, text: str, family: str) -> tuple[list[int], list[int], str | None]:
        """Character offsets of this family's anchors and of other families' anchors in a plain text, and the
        first matched phrase of the family."""
        spans: list[int] = []
        words: list[str] = []
        for m in _WORD_SPAN.finditer(text):
            w = norm_word(m.group(0))
            if w and w != ".":
                words.append(w)
                spans.append(m.start())
        fam_pos: list[int] = []
        other_pos: list[int] = []
        phrase: str | None = None
        for start, _end, ph, keys in self.index.matcher.find(words):
            if family in keys:
                fam_pos.append(spans[start])
                phrase = phrase or ph
            if any(k != family and not k.startswith("topic:") for k in keys):
                other_pos.append(spans[start])
        return fam_pos, other_pos, phrase

    def external_assertions(
        self, fam: ElementFamily
    ) -> tuple[list[RoomAssertion], list[tuple[str, int, str, list[str]]], list[str]]:
        """AG-02C's ``pd.element_room`` values of this family: (assertions, confirming pages (file, page, channel,
        rooms), notes). TEXT assertions pass our negation and nearest-family checks and keep only the rooms both
        channels agree on; TABLE rows are structured per room and are taken as they are."""
        grouped: dict[tuple[str, int, str, str], dict[str, Any]] = {}
        for v in self.inputs.values:
            if v.fact_key != ELEMENT_ROOM_FACT or str(v.stage) != "PD" or str(v.quality_flag) == "ABSTAIN":
                continue
            q = v.value_norm.qualifiers or {}
            if q.get("family") != fam.family or v.value_norm.value is not True:
                continue
            doc = self.inputs.documents.get(v.file_id)
            if doc is None or not doc.citable or doc.stage != "PD":
                continue
            channel = str(q.get("channel") or "")
            text = v.context_text or v.value_raw or ""
            g = grouped.setdefault(
                (v.file_id, v.page_no, channel, text),
                {
                    "rooms": [],
                    "bbox": None,
                    "anchor": (v.anchor.text if v.anchor else None) or q.get("anchor"),
                },
            )
            if v.location and v.location != "OBJECT" and v.location not in g["rooms"]:
                g["rooms"].append(str(v.location))
            if g["bbox"] is None and v.geometry is not None and v.geometry.boxes:
                b = v.geometry.boxes[0]
                g["bbox"] = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
        asserted: list[RoomAssertion] = []
        confirming: list[tuple[str, int, str, list[str]]] = []
        notes: list[str] = []
        for (file_id, page_no, channel, text), g in sorted(grouped.items(), key=lambda kv: kv[0][:3]):
            rooms: list[str] = list(g["rooms"])
            if channel in CONFIRMING_CHANNELS:
                confirming.append((file_id, page_no, channel, rooms))
                continue
            if channel not in ASSERTING_CHANNELS or not rooms:
                continue
            phrase = g["anchor"] or fam.label_ru
            if channel == "TEXT":
                if is_negated(text):
                    notes.append(f"{file_id} стр. {page_no}: отрицание в утверждении AG-02C")
                    continue
                if not is_prose(text):
                    notes.append(
                        f"{file_id} стр. {page_no}: утверждение AG-02C — строка таблицы, не предложение"
                    )
                    continue
                fam_pos, other_pos, ph = self._anchor_positions(text, fam.family)
                ours = sentence_rooms(text, fam_pos, other_pos) if fam_pos else []
                if ours:
                    rooms = [r for r in rooms if r in ours]  # the rooms both readings agree on
                elif other_pos:
                    rooms = []  # another element is named: an unparsed list is not ours to take
                else:
                    # no room list we can parse: keep only rooms printed in the sentence itself
                    printed = {w.strip("().,;:«»") for w in text.split()}
                    rooms = [r for r in rooms if r in printed]
                phrase = ph or phrase
                if not rooms:
                    notes.append(f"{file_id} стр. {page_no}: помещения утверждения AG-02C не подтверждены")
                    continue
            asserted.append(
                RoomAssertion(
                    fam.family,
                    rooms,
                    file_id,
                    page_no,
                    text.strip()[:MAX_SENTENCE_CHARS],
                    str(phrase),
                    g["bbox"],
                    source=f"AG02C_{channel}",
                )
            )
        return asserted, confirming, notes

    def _removal(self, hit: ElementHit) -> RemovalStatement | None:
        """The removal statement an RD mention belongs to («исключены тёплые полы в пом. 270»), or None when the
        mention is plain presence. Only a negation within the same sentence, close to the mention, counts."""
        page = self.inputs.pages.page(hit.file_id, hit.page_no)
        if page is None:
            return None
        text, owners = page.full_text()
        pos = next((i for i, w in enumerate(owners) if w == hit.word_start), None)
        if pos is None:
            return None
        for a, b in sentences(text):
            if not a <= pos < b:
                continue
            if b - a > MAX_SENTENCE_CHARS:
                return None  # a drawing's label soup: no sentence to read a negation from
            lo, hi = max(a, pos - REMOVAL_WINDOW_CHARS), min(b, pos + len(hit.phrase) + REMOVAL_WINDOW_CHARS)
            if not is_negated(text[lo:hi]):
                return None
            rooms = tuple(t for _, _, tokens in room_lists(text[a:b]) for t in tokens)
            return RemovalStatement(hit.file_id, hit.page_no, text[a:b].strip()[:300], rooms)
        return None

    def _score_page(
        self,
        stage: str,
        doc: DocumentInfo,
        meta: PageMeta,
        rooms: Sequence[str],
        fam: ElementFamily,
        family_hit: bool,
    ) -> PageScore:
        boxes = {r: list(meta.rooms[r]) for r in rooms if r in meta.rooms}
        present = [r for r in rooms if r in boxes]
        share = len(present) / len(rooms) if rooms else 0.0
        topic_page = self.index.page_has(f"topic:{fam.topic}", doc.file_id, meta.page_no)
        doc_share = self.index.topic_share(fam.topic, doc)
        clouds = _clouds(self.inputs, doc.file_id, meta.page_no, boxes) if stage == "RD" else []
        hit_boxes = [h.bbox for h in self.index.page_key_hits(fam.family, doc.file_id, meta.page_no)]
        if stage == "PD":
            score = 10 * share + 4 * family_hit + 3 * meta.large_format + 1 * topic_page
        else:
            score = 10 * share + 3 * topic_page + 2 * doc_share + 2 * bool(clouds) + 1 * meta.large_format
        return PageScore(
            stage,
            doc.file_id,
            meta.page_no,
            present,
            share,
            family_hit,
            topic_page,
            doc_share,
            meta.large_format,
            clouds,
            score,
            boxes,
            hit_boxes,
        )

    @staticmethod
    def _best(pages: Iterable[PageScore]) -> PageScore | None:
        return min(pages, key=lambda p: (-p.score, p.file_id, p.page_no), default=None)

    def detect_family(self, fam: ElementFamily) -> FreeCandidate | None:
        route = fam.free_route("ELEMENT_MISSING")
        if route is None:
            return None
        pd_docs = self.inputs.docs("PD", fam.manifest_sections)
        assertions: list[RoomAssertion] = []
        hit_pages: list[tuple[DocumentInfo, PageMeta]] = []
        for doc in pd_docs:
            for meta in self.index.pages(doc):
                self.pages_examined += 1
                hits = self.index.page_key_hits(fam.family, doc.file_id, meta.page_no)
                if not hits:
                    continue
                hit_pages.append((doc, meta))
                page = self.inputs.pages.page(doc.file_id, meta.page_no)
                if page is not None:
                    assertions.extend(self.assertions(fam, doc, page, hits))
        # second channel: AG-02C's pd.element_room values (same checks; a twin on the same page corroborates)
        ext_assertions, confirming, ext_notes = self.external_assertions(fam)
        sources: dict[str, int] = {"PAGE_TOKENS": len(assertions)}
        for a in ext_assertions:
            twin = next(
                (
                    b
                    for b in assertions
                    if b.source == "PAGE_TOKENS"
                    and (b.file_id, b.page_no) == (a.file_id, a.page_no)
                    and set(a.rooms) <= set(b.rooms)
                ),
                None,
            )
            if twin is not None:
                twin.corroborated = True
                sources["corroborated"] = sources.get("corroborated", 0) + 1
            else:
                assertions.append(a)
                sources[a.source] = sources.get(a.source, 0) + 1
        rooms: list[str] = []
        for a in assertions:
            rooms.extend(r for r in a.rooms if r not in rooms)
        if not rooms:
            return None
        rooms = sorted(rooms, key=natural_key)
        reasons: list[str] = list(ext_notes)

        # pages AG-02C names (asserting or confirming) compete as PD anchors when their PageTokens were read
        known = {(d.file_id, m.page_no) for d, m in hit_pages}
        named = [(a.file_id, a.page_no) for a in assertions if a.source != "PAGE_TOKENS"]
        named += [(f, p) for f, p, _, _ in confirming]
        for fid, pno in named:
            doc = self.inputs.documents.get(fid)
            if (fid, pno) in known or doc is None:
                continue
            self.index.pages(doc)  # scanned once, cached
            meta = self.index.meta(fid, pno)
            if meta is not None:
                known.add((fid, pno))
                hit_pages.append((doc, meta))
        label_rooms: dict[tuple[str, int], set[str]] = defaultdict(set)
        for f, p, channel, rs in confirming:
            if channel == "LABEL":
                label_rooms[(f, p)].update(rs)

        # PD anchor and support
        pd_scores = [self._score_page("PD", d, m, rooms, fam, True) for d, m in hit_pages]
        pd_anchor = self._best(s for s in pd_scores if s.rooms)
        pd_support = [
            s
            for s in pd_scores
            if pd_anchor is None or (s.file_id, s.page_no) != (pd_anchor.file_id, pd_anchor.page_no)
        ]
        location_pages: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for s in pd_scores:
            for r in s.rooms:
                location_pages[r].append(("PD", s.file_id, s.page_no))

        # RD side
        rd_docs = self.inputs.docs("RD", fam.manifest_sections)
        rd_other = [d for d in self.inputs.docs("RD", {"OTHER"}) if d not in rd_docs]
        if not rd_docs:
            return FreeCandidate(
                fam,
                route,
                rooms,
                assertions,
                pd_anchor,
                None,
                pd_support,
                dict(location_pages),
                {},
                "NO_RD",
                0,
                0,
                0.0,
                {},
                [*reasons, "в составе РД нет документов раздела"],
                sources=sources,
            )
        rd_read = rd_total = 0
        for d in rd_docs:
            r, t = self.index.coverage(d)
            rd_read, rd_total = rd_read + r, rd_total + t
        # a mention inside a removal statement («исключены тёплые полы») supports the absence, it is not presence
        rd_hits: list[ElementHit] = []
        removals: list[RemovalStatement] = []
        for h in self.index.hits(fam.family, rd_docs + rd_other):
            removal = self._removal(h)
            if removal is None:
                rd_hits.append(h)
            elif removal not in removals:
                removals.append(removal)
        hits_by_page: dict[tuple[str, int], list[ElementHit]] = defaultdict(list)
        for h in rd_hits:
            hits_by_page[(h.file_id, h.page_no)].append(h)
        present_rooms: dict[str, str] = {}
        room_pages: list[tuple[DocumentInfo, PageMeta]] = []
        for doc in rd_docs + rd_other:
            for meta in self.index.pages(doc):
                self.pages_examined += 1
                boxes = {r: meta.rooms[r] for r in rooms if r in meta.rooms}
                if not boxes:
                    continue
                for r in boxes:
                    location_pages[r].append(("RD", doc.file_id, meta.page_no))
                radius = self.config.room_radius_frac * min(meta.width_pt, meta.height_pt)
                for h in hits_by_page.get((doc.file_id, meta.page_no), []):
                    # an anchor belongs to the nearest room label of the group, if that one is close enough
                    dist, room = min(
                        (meta.distance_pt(h.center, _center(b)), r) for r, bxs in boxes.items() for b in bxs
                    )
                    if dist <= radius and room not in present_rooms:
                        present_rooms[room] = f"{doc.file_id} стр. {meta.page_no}: «{h.phrase}»"
                if doc in rd_docs:
                    room_pages.append((doc, meta))
        missing = [r for r in rooms if r not in present_rooms]
        if not missing:
            return FreeCandidate(
                fam,
                route,
                rooms,
                assertions,
                pd_anchor,
                None,
                pd_support,
                dict(location_pages),
                present_rooms,
                "PRESENT",
                rd_read,
                rd_total,
                0.0,
                {},
                [*reasons, "элемент найден в РД у всех помещений"],
                removals=removals,
                sources=sources,
            )
        rd_scores = [self._score_page("RD", d, m, missing, fam, False) for d, m in room_pages]
        rd_anchor = self._best(s for s in rd_scores if s.rooms)
        if present_rooms:
            reasons.append(
                "элемент найден в РД у помещений: " + ", ".join(sorted(present_rooms, key=natural_key))
            )
        # absence level
        if rd_hits:
            absence: Absence = "ROOM"
            reasons.append("элемент встречается в РД вне этих помещений")
        elif rd_total > 0 and rd_read == rd_total:
            absence = "DOCUMENT"
        elif rd_anchor is not None:
            r, t = self.index.coverage(self.inputs.documents[rd_anchor.file_id])
            absence = "COUNTERPART" if t > 0 and r == t else "UNKNOWN"
            if absence == "UNKNOWN":
                reasons.append(f"РД прочитана не полностью ({rd_read} из {rd_total} стр.)")
        else:
            absence = "UNKNOWN"
            reasons.append(f"помещения не найдены на прочитанных страницах РД ({rd_read} из {rd_total} стр.)")
        # confidence
        terms: dict[str, float] = {"base": 0.55, "pd_text_assertion": 0.15}
        min_share = self.config.min_anchor_room_share
        drawing_confirms = (
            pd_anchor is not None
            and pd_anchor.large
            and pd_anchor.family_hit
            and pd_anchor.share >= min_share
        )
        # or: AG-02C read a leader label naming the element next to most of the rooms on a large PD drawing
        drawing_confirms = drawing_confirms or any(
            s.large
            and len(label_rooms.get((s.file_id, s.page_no), set()) & set(missing)) >= min_share * len(missing)
            for s in pd_scores
            if (s.file_id, s.page_no) in label_rooms
        )
        if drawing_confirms:
            terms["pd_drawing_confirms"] = 0.10
        if len({(s.file_id, s.page_no) for s in pd_scores}) >= 2:
            terms["pd_several_pages"] = 0.05
        conf = sum(terms.values())
        terms["absence_factor"] = ABSENCE_FACTOR[absence]
        conf *= ABSENCE_FACTOR[absence]
        if rd_anchor is not None and rd_anchor.share < self.config.min_anchor_room_share:
            terms["rd_anchor_minority"] = 0.9
            conf *= 0.9
        if rd_anchor is not None and rd_anchor.cloud_rooms and conf > 0:
            terms["rd_revision_cloud"] = 0.10
            conf += 0.10
        if removals and conf > 0:
            terms["rd_removal_statement"] = 0.05
            conf += 0.05
        conf = round(min(conf, 0.95), 3)
        if pd_anchor is None:
            reasons.append("в ПД нет листа с помещениями группы")
        if rd_anchor is None:
            reasons.append("в РД нет листа с помещениями группы")
        return FreeCandidate(
            fam,
            route,
            missing,
            assertions,
            pd_anchor,
            rd_anchor,
            pd_support,
            dict(location_pages),
            present_rooms,
            absence,
            rd_read,
            rd_total,
            conf,
            terms,
            reasons,
            removals=removals,
            sources=sources,
        )

    def detect(self, families: Iterable[ElementFamily] | None = None) -> list[FreeCandidate]:
        out: list[FreeCandidate] = []
        for fam in families if families is not None else free_families("ELEMENT_MISSING"):
            cand = self.detect_family(fam)
            if cand is not None:
                out.append(cand)
        return out

    def select(self, candidates: list[FreeCandidate]) -> list[FreeCandidate]:
        """Mark the exported candidates (bound, proven absence, confident, capped) and number them per topic."""
        cap = self.config.max_groups
        if cap is None:
            cap = int(load_change_map().document["policy"]["max_free_groups_per_object"])
        eligible = []
        for c in candidates:
            if c.bind_status != EvidenceBindStatus.BOUND:
                c.reasons.append("доказательства не привязаны к ПД и РД")
            elif c.absence not in EXPORTABLE_ABSENCE:
                c.reasons.append(f"отсутствие в РД не доказано ({c.absence})")
            elif c.confidence < self.config.min_confidence:
                c.reasons.append(
                    f"уверенность {c.confidence:.2f} ниже порога {self.config.min_confidence:.2f}"
                )
            else:
                eligible.append(c)
        eligible.sort(key=lambda c: (-c.confidence, c.order_key))
        for c in eligible[cap:]:
            c.reasons.append(f"превышен лимит групп свободного поиска ({cap})")
        chosen = sorted(eligible[:cap], key=lambda c: c.order_key)
        counters: dict[str, int] = defaultdict(int)
        for c in chosen:
            counters[c.topic] += 1
            c.parameter_code = free_code(c.topic, counters[c.topic])
            c.exported = True
        return candidates


# ───────────────────────────────────────────── contract objects ─────────────────────────────────────────────


def _evidence_ref(
    inputs: HypothesisInputs,
    score: PageScore,
    role: EvidenceRole,
    *,
    anchor: bool,
    boxes: Sequence[tuple[float, float, float, float]] = (),
) -> EvidenceRef:
    doc = inputs.documents[score.file_id]
    fields: dict[str, Any] = {
        "stage": DocStage(score.stage),
        "file_id": score.file_id,
        "pdf_page_number": score.page_no,
        "document_sheet_number": inputs.sheet_number(score.file_id, score.page_no),
        "file_sha256": doc.file_sha256,
        "page_basis": PageBasis.PDF_NATIVE,
        "role": role,
        "is_anchor": anchor,
        "geometry": Geometry(boxes=[list(b) for b in boxes[:8]]) if boxes else None,
        "geometry_space": "PDF_VISIBLE_ROTATED_TL_V1" if boxes else None,
        "document_code": inputs.page_code(score.file_id, score.page_no),
        "revision": doc.revision,
    }
    return EvidenceRef(**{k: v for k, v in fields.items() if v is not None})


def stage_values(
    route: Route, cand: FreeCandidate, inputs: HypothesisInputs, room: str | None = None
) -> tuple[Any, Any, Any]:
    tpl = route.data.get("value_templates") or {}
    pd_sheet = inputs.sheet_number(cand.pd_anchor.file_id, cand.pd_anchor.page_no) if cand.pd_anchor else None
    fill = {
        "pd_sheet": pd_sheet if pd_sheet is not None else "—",
        "rd_plan_mark": "РД",
        "location": room or ", ".join(cand.rooms),
    }

    def render(t: str | None) -> str | None:
        return t.format_map(defaultdict(lambda: "—", fill)) if t else None

    return render(tpl.get("pd")), render(tpl.get("rd")), render(tpl.get("id"))


def recommendation(cand: FreeCandidate) -> Recommendation | None:
    rec = _free_recommendations()["topics"].get(cand.topic) or _free_recommendations()["topics"].get(
        "GENERIC"
    )
    if rec is None:
        return None
    noun = element_noun(cand.route) or cand.family.label_ru
    preset = (rec.get("element_presets") or {}).get(noun, {})
    text = preset.get("recommendation") or rec.get("recommendation")
    if not text:
        return None
    location = rooms_ru(cand.rooms)
    text = text.replace("{location}", location).replace("{element}", noun[:1].lower() + noun[1:])
    refs = [r["designation"] for r in rec.get("norm_refs_used", []) if r.get("designation")]
    return Recommendation(
        text=text,
        template_id=f"FREE-{cand.topic}" + (f":{noun}" if preset else ""),
        text_origin=TextOrigin.AG03_DRAFT,
        work_type=rec.get("vid_rabot"),
        normative_refs=refs or None,
    )


def title_of(cand: FreeCandidate) -> str:
    rec = _free_recommendations()["topics"].get(cand.topic) or {}
    noun = element_noun(cand.route) or cand.family.label_ru
    preset = (rec.get("element_presets") or {}).get(noun, {})
    head = (
        preset.get("vid_narusheniya")
        or (rec.get("vid_narusheniya_variants") or {})
        .get("absence", "")
        .replace("{element}", noun[:1].lower() + noun[1:])
        or f"Отсутствует предусмотренный ПД элемент: {noun.lower()}"
    )
    return f"{head} ({rooms_ru(cand.rooms)})"


def rationale_of(cand: FreeCandidate, inputs: HypothesisInputs) -> str:
    parts: list[str] = []
    if cand.assertions:
        a = cand.assertions[0]
        quote = a.quote if len(a.quote) <= 220 else a.quote[:217] + "…"
        parts.append(f"ПД ({a.file_id}, стр. {a.page_no}): «{quote}»")
    if cand.rd_anchor is not None:
        noun = (element_noun(cand.route) or cand.family.label_ru).lower()
        parts.append(
            f"на плане РД ({cand.rd_anchor.file_id}, стр. {cand.rd_anchor.page_no}) {noun} в этих помещениях не показан"
        )
    if cand.absence == "DOCUMENT":
        parts.append(f"РД раздела прочитана полностью ({cand.rd_read} стр.), упоминаний элемента нет")
    elif cand.absence == "COUNTERPART":
        parts.append("документ РД с планом помещений прочитан полностью, упоминаний элемента нет")
    if cand.removals:
        r = cand.removals[0]
        quote = r.quote if len(r.quote) <= 160 else r.quote[:157] + "…"
        parts.append(f"в РД ({r.file_id}, стр. {r.page_no}) элемент упомянут как исключённый: «{quote}»")
    if cand.rd_anchor is not None and cand.rd_anchor.cloud_rooms:
        parts.append("облако изменения в РД над пом. " + ", ".join(cand.rd_anchor.cloud_rooms))
    _ = inputs
    return "; ".join(parts) + "."


def to_contract(
    cand: FreeCandidate, inputs: HypothesisInputs, run_id: str | None
) -> tuple[FindingGroup, list[Finding]]:
    """FindingGroup + atomic Findings of an exported candidate (AG-04's exporter projects them to the submission)."""
    if not cand.exported or cand.parameter_code is None or cand.pd_anchor is None or cand.rd_anchor is None:
        raise ValueError("only exported, bound candidates become findings")
    free = enum_mappings()["free_search"]
    code = cand.parameter_code
    object_id = inputs.object_id
    pd_boxes = cand.pd_anchor.hit_boxes + [
        b for r in cand.rooms for b in cand.pd_anchor.room_boxes.get(r, [])
    ]
    rd_boxes = [b for r in cand.rooms for b in cand.rd_anchor.room_boxes.get(r, [])]
    anchors = [
        _evidence_ref(inputs, cand.pd_anchor, EvidenceRole.EXPECTED, anchor=True, boxes=pd_boxes),
        _evidence_ref(inputs, cand.rd_anchor, EvidenceRole.ACTUAL, anchor=True, boxes=rd_boxes),
    ]
    support: list[EvidenceRef] = []
    seen = {(a.file_id, a.pdf_page_number) for a in anchors}
    for a in cand.assertions:
        if (a.file_id, a.page_no) not in seen:
            seen.add((a.file_id, a.page_no))
            support.append(
                _evidence_ref(
                    inputs,
                    PageScore("PD", a.file_id, a.page_no, a.rooms, 1.0, True, False, 0.0, False, [], 0.0),
                    EvidenceRole.SUPPORTING_EXPECTED,
                    anchor=False,
                    boxes=[a.bbox] if a.bbox else (),
                )
            )
    for s in cand.pd_support:
        if (s.file_id, s.page_no) not in seen and len(support) < 6:
            seen.add((s.file_id, s.page_no))
            support.append(
                _evidence_ref(inputs, s, EvidenceRole.SUPPORTING_EXPECTED, anchor=False, boxes=s.hit_boxes)
            )
    location_pages = {
        room: [
            EvidenceRef(stage=DocStage(st), file_id=fid, pdf_page_number=p)
            for st, fid, p in list(dict.fromkeys(cand.location_pages.get(room, [])))[:6]
        ]
        for room in cand.rooms
    }
    pd_value, rd_value, id_value = stage_values(cand.route, cand, inputs)
    rec = recommendation(cand)
    group_id = f"{object_id}-G-{code}"
    finding_ids = [f"{object_id}-{code}-PDRD-{room}" for room in cand.rooms]
    trace = {
        "detector": DETECTOR,
        "family": cand.family.family,
        "absence": cand.absence,
        "rd_pages_read": cand.rd_read,
        "rd_pages_total": cand.rd_total,
        "confidence_terms": cand.confidence_terms,
        "present_rooms": cand.present_rooms,
        "assertions": [
            {
                "file_id": a.file_id,
                "page": a.page_no,
                "rooms": a.rooms,
                "phrase": a.phrase,
                "source": a.source,
                "corroborated": a.corroborated,
            }
            for a in cand.assertions[:5]
        ],
        "assertion_sources": dict(cand.sources),
        "removal_statements": [
            {"file_id": r.file_id, "page": r.page_no, "quote": r.quote, "rooms": list(r.rooms)}
            for r in cand.removals[:3]
        ],
        "promoted_by": None,
    }
    group = FindingGroup(
        finding_group_id=group_id,
        object_id=object_id,
        run_id=run_id,
        matrix_scope=MatrixScope.FREE_SEARCH,
        parameter_code=code,
        parameter_id=None,
        parameter_mapping_status=cand.route.parameter_mapping_status,
        title=title_of(cand),
        element_noun=element_noun(cand.route),
        axis=ComparisonAxis.PD_RD,
        comparison_result=cand.route.comparison_result,
        discrepancy_type=DiscrepancyType.ELEMENT_MISSING,
        location_type=LocationType.ROOM,
        locations=list(cand.rooms),
        pd_value=pd_value,
        rd_value=rd_value,
        id_value=id_value,
        violation_label=ViolationLabel.VIOLATION_PRESENT,
        protocol_status=ProtocolParamStatus(free["protocol_status"]),
        criticality=free["criticality_string"],
        criticality_level=CriticalityLevel(free["criticality_level"]),
        finding_status=FindingStatus.SUSPICION,
        confidence=cand.confidence,
        anchor_evidence=anchors,
        evidence=support or None,
        location_pages=location_pages,
        finding_ids=finding_ids,
        discovery_method=DiscoveryMethod.SEMANTIC_DISSONANCE,
        evidence_bind_status=EvidenceBindStatus.BOUND,
        rule_code=RULE_CODE,
        rule_version=RULE_VERSION,
        rationale=rationale_of(cand, inputs),
        recommendation=rec,
        decision_trace=trace,
    )
    findings: list[Finding] = []
    for room, fid in zip(cand.rooms, finding_ids, strict=True):
        findings.append(
            Finding(
                finding_id=fid,
                finding_group_id=group_id,
                object_id=object_id,
                run_id=run_id,
                matrix_scope=MatrixScope.FREE_SEARCH,
                parameter_code=code,
                parameter_id=None,
                parameter_mapping_status=cand.route.parameter_mapping_status,
                location=room,
                location_type=LocationType.ROOM,
                pd_value=pd_value,
                rd_value=rd_value,
                id_value=id_value,
                axis=ComparisonAxis.PD_RD,
                comparison_result=cand.route.comparison_result,
                discrepancy_type=DiscrepancyType.ELEMENT_MISSING,
                completeness_status=CompletenessStatus.COMPLETE,
                finding_status=FindingStatus.SUSPICION,
                violation_label=ViolationLabel.VIOLATION_PRESENT,
                protocol_status=ProtocolParamStatus(free["protocol_status"]),
                criticality=free["criticality_string"],
                criticality_level=CriticalityLevel(free["criticality_level"]),
                review_priority=ReviewPriority.MEDIUM,
                document_status=DOCUMENT_STATUS_PAIRWISE,
                confidence=cand.confidence,
                evidence=[a.model_copy() for a in anchors],
                element_noun=element_noun(cand.route),
                discovery_method=DiscoveryMethod.SEMANTIC_DISSONANCE,
                evidence_bind_status=EvidenceBindStatus.BOUND,
                recommendation=rec,
                rule_code=RULE_CODE,
                rule_version=RULE_VERSION,
                rationale=group.rationale,
            )
        )
    return group, findings
