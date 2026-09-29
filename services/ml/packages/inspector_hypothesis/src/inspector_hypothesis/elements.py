"""Element families (seed ``change_matrix_map.json``, AG-03) and where they occur in the object's documents.

- :class:`ElementFamily`: anchors, tag patterns, topic, disciplines and the manifest sections they live in, and the
  routes (discrepancy type → parameter code, emit flag, value templates).
- :class:`ElementIndex`: one pass over the recognised pages of a stage finds every anchor of every family
  (a prefix-indexed phrase matcher, so hundreds of anchors cost one dictionary lookup per word), caches the hits
  and answers three-valued presence questions (07 §3.3.1): an element is *present* when an anchor is found, *absent*
  only when every page of the discipline documents of that stage was read, and *unknown* otherwise.

Disciplines map to the coarse manifest ``section`` through the ManifestSection labels (ОВ → OV, …) plus the
sub-discipline abbreviations below (КЖ → KR, ЭО → EOM, …).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from inspector_common.contracts.loader import load_enums
from inspector_common.params import ChangeMap, Route, load_change_map, load_free_topics
from inspector_hypothesis.inputs import DocumentInfo, HypothesisInputs, PageText
from inspector_hypothesis.logic import UNKNOWN, Truth
from inspector_hypothesis.textmatch import Phrase, clean_room_token, compile_phrase, fold_latin

# Sub-discipline marks → the manifest section that carries them (the manifest vocabulary is coarse).
_SUBDISCIPLINE_SECTION: dict[str, str] = {
    "КЖ": "KR",
    "КМ": "KR",
    "КД": "KR",
    "ЭО": "EOM",
    "ЭС": "EOM",
    "ЭМ": "EOM",
    "НВК": "VK",
    "ТС": "OV",
    "ТМ": "OV",
    "АПС": "SS",
    "ЛО": "AR",
    "ПП": "GP",
}


@cache
def discipline_sections() -> dict[str, str]:
    """Discipline mark («ОВ», «КЖ») → ManifestSection code («OV», «KR»)."""
    out = {
        v.label_ru: v.code for v in load_enums()["ManifestSection"].values if v.label_ru and v.code != "OTHER"
    }
    out.update(_SUBDISCIPLINE_SECTION)
    return out


@dataclass(frozen=True, slots=True)
class ElementFamily:
    family: str
    label_ru: str
    topic: str
    section: str
    disciplines: tuple[str, ...]
    manifest_sections: frozenset[str]
    anchors: tuple[str, ...]
    tag_patterns: tuple[re.Pattern[str], ...]
    routes: tuple[Route, ...] = field(repr=False)

    def route(self, discrepancy_type: str) -> Route | None:
        for r in self.routes:
            if discrepancy_type in r.discrepancy_types:
                return r
        return None

    def free_route(self, discrepancy_type: str) -> Route | None:
        r = self.route(discrepancy_type)
        return r if r is not None and r.is_free and r.emit else None


@cache
def load_families() -> dict[str, ElementFamily]:
    cmap: ChangeMap = load_change_map()
    sections = discipline_sections()
    routes_by_family: dict[str, list[Route]] = defaultdict(list)
    for r in cmap.routes():
        routes_by_family[r.family].append(r)
    out: dict[str, ElementFamily] = {}
    for name, fam in cmap.families.items():
        disciplines = tuple(fam.get("disciplines", ()))
        out[name] = ElementFamily(
            family=name,
            label_ru=fam.get("label_ru", name),
            topic=fam.get("topic", "OTHER"),
            section=fam.get("section", ""),
            disciplines=disciplines,
            manifest_sections=frozenset(sections[d] for d in disciplines if d in sections),
            anchors=tuple(fam.get("anchors", ())),
            tag_patterns=tuple(re.compile(p) for p in fam.get("tag_patterns", ())),
            routes=tuple(routes_by_family.get(name, ())),
        )
    return out


def free_families(discrepancy_type: str = "ELEMENT_MISSING") -> list[ElementFamily]:
    """Families whose change of this type routes to FREE-<TOPIC> and emits (a matrix gap, 97 §2.10)."""
    return [f for f in load_families().values() if f.free_route(discrepancy_type) is not None]


@cache
def topic_anchor_phrases(topic: str) -> tuple[str, ...]:
    """Words that mark a page or document as belonging to a FREE topic: the topic label and the anchors of every
    family of that topic (HEATING: «Отопление», «радиатор», «ИТП», «тёплый пол», …)."""
    phrases: list[str] = []
    spec = load_free_topics().get(topic)
    if spec is not None:
        phrases.append(spec.label_ru)
    for fam in load_families().values():
        if fam.topic == topic:
            phrases.extend(fam.anchors)
    return tuple(dict.fromkeys(phrases))


# ───────────────────────────────────────────── Multi-phrase matching ─────────────────────────────────────────────


class MultiMatcher:
    """Many anchor phrases, each labelled with one or more keys; finds all of them in one pass."""

    def __init__(self, labelled: Mapping[str, Iterable[str]]):
        by_text: dict[str, set[str]] = defaultdict(set)
        for key, phrases in labelled.items():
            for p in phrases:
                by_text[p].add(key)
        self._phrases: list[tuple[Phrase, frozenset[str]]] = []
        self._index: dict[str, list[int]] = defaultdict(list)
        for text, keys in by_text.items():
            ph = compile_phrase(text)
            if ph is None:
                continue
            self._phrases.append((ph, frozenset(keys)))
        # longest phrases first within each bucket
        order = sorted(range(len(self._phrases)), key=lambda i: -self._phrases[i][0].size)
        for i in order:
            first = self._phrases[i][0].words[0].stem
            self._index[first[:3]].append(i)

    def find(self, words: list[str]) -> list[tuple[int, int, str, frozenset[str]]]:
        """(start, end, phrase text, keys) for every match; overlapping matches of different keys are kept."""
        out: list[tuple[int, int, str, frozenset[str]]] = []
        n = len(words)
        for i, w in enumerate(words):
            cands = self._index.get(w.rstrip(".")[:3])
            if not cands:
                continue
            for pi in cands:
                ph, keys = self._phrases[pi]
                if i + ph.size <= n and all(ph.words[k].matches(words[i + k]) for k in range(ph.size)):
                    out.append((i, i + ph.size, ph.text, keys))
        return out


@dataclass(frozen=True, slots=True)
class ElementHit:
    key: str  # family name, or «topic:<TOPIC>» for topic keywords
    file_id: str
    page_no: int
    stage: str | None
    phrase: str
    word_start: int  # indices into PageText.words (page reading order)
    word_end: int
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]


@dataclass(slots=True)
class Presence:
    """Three-valued presence of a family in one stage of the object."""

    value: Truth
    hits: list[ElementHit]
    pages_read: int
    pages_total: int
    files: list[str]

    @property
    def coverage(self) -> float:
        return self.pages_read / self.pages_total if self.pages_total else 0.0

    def as_fact(self) -> dict[str, Any]:
        return {
            "present": self.value,
            "hits": len(self.hits),
            "pages_read": self.pages_read,
            "pages_total": self.pages_total,
            "coverage": round(self.coverage, 4),
            "files": list(self.files),
            "evidence": [
                {"stage": h.stage, "file_id": h.file_id, "pdf_page_number": h.page_no} for h in self.hits[:3]
            ],
        }


def _page_words(page: PageText) -> list[str]:
    return [w.norm for w in page.words]


def _union_bbox(page: PageText, start: int, end: int) -> tuple[float, float, float, float]:
    boxes = [page.words[i].bbox for i in range(start, end)]
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


@dataclass(frozen=True, slots=True)
class PageMeta:
    """What the index keeps of a scanned page (the page text itself is not kept)."""

    file_id: str
    page_no: int
    width_pt: float
    height_pt: float
    large_format: bool
    usable: bool
    rooms: Mapping[str, tuple[tuple[float, float, float, float], ...]]  # room-like tokens → label boxes

    def distance_pt(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        dx = (a[0] - b[0]) * self.width_pt
        dy = (a[1] - b[1]) * self.height_pt
        return (dx * dx + dy * dy) ** 0.5


class ElementIndex:
    """Anchor hits of every family (and topic keywords) from one pass over the recognised pages of a document.

    Per page it keeps the hits, the room-like tokens with their boxes, the page size and whether the page was read,
    so later questions (presence, coverage, room localisation, topic affinity) never reload a page.
    """

    def __init__(self, inputs: HypothesisInputs, families: Mapping[str, ElementFamily] | None = None):
        self.inputs = inputs
        self.families = dict(families) if families is not None else load_families()
        labelled: dict[str, list[str]] = {name: list(f.anchors) for name, f in self.families.items()}
        for topic in {f.topic for f in self.families.values()}:
            labelled[f"topic:{topic}"] = list(topic_anchor_phrases(topic))
        self.matcher = MultiMatcher(labelled)
        self._tagged = [(name, fam) for name, fam in self.families.items() if fam.tag_patterns]
        # one combined pattern rejects most words with a single regex call before the per-family patterns run
        self._tag_union = (
            re.compile("|".join(f"(?:{p.pattern})" for _, fam in self._tagged for p in fam.tag_patterns))
            if self._tagged
            else None
        )
        self._topic_share: dict[tuple[str, str], float] = {}
        self._hits: dict[str, dict[int, list[ElementHit]]] = defaultdict(dict)  # file_id → page → hits
        self._meta: dict[str, dict[int, PageMeta]] = defaultdict(dict)
        self._scanned: set[str] = set()
        self.pages_scanned = 0

    # scanning ---------------------------------------------------------------------------------------
    def page_hits(self, doc: DocumentInfo, page: PageText) -> list[ElementHit]:
        cached = self._hits[doc.file_id].get(page.page_no)
        if cached is not None:
            return cached
        words = _page_words(page)
        hits: list[ElementHit] = []
        for start, end, phrase, keys in self.matcher.find(words):
            bbox = _union_bbox(page, start, end)
            center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
            for k in sorted(keys):
                hits.append(
                    ElementHit(k, doc.file_id, page.page_no, doc.stage, phrase, start, end, bbox, center)
                )
        rooms: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
        union = self._tag_union
        for i, w in enumerate(page.words):
            first = w.text[:1]
            if first.isdigit() or first in '-−«“"(':
                token = clean_room_token(w.text)
                if token is not None:
                    rooms[token].append(w.bbox)
            # tag patterns («Т11», «П2.1») of the families that have them; they also mark the family's topic
            if union is None or len(w.text) > 16:
                continue
            t = w.text.strip("«»“”\"'()[],;:")
            if not t or not t[0].isalpha():
                continue
            folded = fold_latin(t)
            if not union.match(t) and (folded == t or not union.match(folded)):
                continue
            for name, fam in self._tagged:
                if any(p.match(t) or p.match(folded) for p in fam.tag_patterns):
                    for key in (name, f"topic:{fam.topic}"):
                        hits.append(
                            ElementHit(
                                key, doc.file_id, page.page_no, doc.stage, t, i, i + 1, w.bbox, w.center
                            )
                        )
        self._hits[doc.file_id][page.page_no] = hits
        self._meta[doc.file_id][page.page_no] = PageMeta(
            doc.file_id,
            page.page_no,
            page.width_pt,
            page.height_pt,
            page.is_large_format,
            page.usable,
            {k: tuple(v) for k, v in rooms.items()},
        )
        self.pages_scanned += 1
        return hits

    def scan_document(self, doc: DocumentInfo) -> None:
        if doc.file_id in self._scanned:
            return
        for page in self.inputs.iter_pages(doc):
            self.page_hits(doc, page)
        self._scanned.add(doc.file_id)

    def hits(self, key: str, docs: Iterable[DocumentInfo]) -> list[ElementHit]:
        out: list[ElementHit] = []
        for doc in docs:
            self.scan_document(doc)
            for page_no in sorted(self._hits[doc.file_id]):
                out.extend(h for h in self._hits[doc.file_id][page_no] if h.key == key)
        return out

    def pages(self, doc: DocumentInfo) -> list[PageMeta]:
        """Scanned pages of a document in page order."""
        self.scan_document(doc)
        return [self._meta[doc.file_id][p] for p in sorted(self._meta[doc.file_id])]

    def meta(self, file_id: str, page_no: int) -> PageMeta | None:
        return self._meta.get(file_id, {}).get(page_no)

    def page_key_hits(self, key: str, file_id: str, page_no: int) -> list[ElementHit]:
        return [h for h in self._hits.get(file_id, {}).get(page_no, ()) if h.key == key]

    def coverage(self, doc: DocumentInfo) -> tuple[int, int]:
        """(pages read, pages total): read = recognised and usable (from the scan, no reload)."""
        self.scan_document(doc)
        read = sum(1 for m in self._meta[doc.file_id].values() if m.usable)
        return read, doc.pages_total or 0

    # questions --------------------------------------------------------------------------------------
    def scope(self, family: str, stage: str, *, include_other: bool = False) -> list[DocumentInfo]:
        fam = self.families[family]
        sections = set(fam.manifest_sections) | ({"OTHER"} if include_other else set())
        return self.inputs.docs(stage, sections) if sections else []

    def presence(self, family: str, stage: str) -> Presence:
        """TRUE if an anchor is found in the stage's discipline documents; FALSE only when every page of them was
        read; UNKNOWN otherwise (no discipline documents of that stage, or pages not recognised)."""
        docs = self.scope(family, stage)
        hits = self.hits(family, docs)
        read = total = 0
        for d in docs:
            r, t = self.coverage(d)
            read += r
            total += t
        if hits:
            value: Truth = True
        elif docs and total > 0 and read == total:
            value = False
        else:
            value = UNKNOWN
        return Presence(value, hits, read, total, [d.file_id for d in docs])

    def topic_share(self, topic: str, doc: DocumentInfo) -> float:
        """Share of the document's read pages that carry a keyword of the topic (document-level affinity)."""
        cached = self._topic_share.get((topic, doc.file_id))
        if cached is not None:
            return cached
        self.scan_document(doc)
        pages = self._hits[doc.file_id]
        key = f"topic:{topic}"
        share = (
            sum(1 for hs in pages.values() if any(h.key == key for h in hs)) / len(pages) if pages else 0.0
        )
        self._topic_share[(topic, doc.file_id)] = share
        return share

    def page_has(self, key: str, file_id: str, page_no: int) -> bool:
        return any(h.key == key for h in self._hits.get(file_id, {}).get(page_no, ()))
