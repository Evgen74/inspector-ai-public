"""Absence proof (95 §3.4 G-TR-002; 97 §3.3): «the RD has no warm floor» must be a proven negative.

``prove_absence`` searches every page of a document set for an element family (AG-03 anchors, stemmed) in
the text layer **and** in the OCR tokens. Absence is claimed only when every page was actually read:

* a page with PageTokens (AG-02A ``recognize``: text layer + OCR of outlined text and rasters) is read;
* a page without tokens is read only if it is a text page (≤ A3 and without heavy vector drawing), whose
  text layer is its content; a drawing sheet without tokens is UNREAD — its text may be curves (65 % of the
  lines on the gold RD sheets are outlined, 96 §0.4).

Result: ``absent`` is True (proven), False (found, with the hits) or None (not provable: unread pages are
listed). Comparators must treat None as «cannot confirm», never as absent (fail-visible, 97 §1.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inspector_tables.assertions import A4_AREA_PT2, family, match_families
from inspector_tables.pagesource import PageSource
from inspector_tables.text import segments

TEXT_PAGE_MAX_AREA = 2.1 * A4_AREA_PT2  # up to A3
HEAVY_DRAWING_PATHS = 3000


@dataclass(slots=True)
class AbsenceHit:
    page_no: int
    text: str
    bbox: list[float]
    source: str


@dataclass(slots=True)
class AbsenceProof:
    family: str
    file_ids: list[str]
    absent: bool | None
    pages_total: int
    pages_read: int
    pages_by_source: dict[str, int] = field(default_factory=dict)
    unread: list[tuple[str, int]] = field(default_factory=list)
    hits: list[AbsenceHit] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.pages_read / self.pages_total if self.pages_total else 0.0

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "file_ids": self.file_ids,
            "absent": self.absent,
            "pages_total": self.pages_total,
            "pages_read": self.pages_read,
            "coverage": round(self.coverage, 4),
            "pages_by_source": self.pages_by_source,
            "unread": [{"file_id": f, "page": p} for f, p in self.unread],
            "hits": [
                {"page": h.page_no, "text": h.text, "bbox": h.bbox, "source": h.source} for h in self.hits
            ],
        }


MIN_TEXT_CHARS = 200


def _is_text_page(pdf_page) -> bool:
    """≤ A3, a real text layer (≥ 200 visible characters: an outlined sheet has a handful) and no heavy
    vector drawing. Anything else needs OCR tokens before it can support a negative."""
    r = pdf_page.rect
    if r.width * r.height > TEXT_PAGE_MAX_AREA:
        return False
    try:
        chars = len("".join(pdf_page.get_text().split()))
        return chars >= MIN_TEXT_CHARS and len(pdf_page.get_cdrawings()) < HEAVY_DRAWING_PATHS
    except Exception:
        return False


def prove_absence(
    sources: list[tuple[PageSource, list[int]]],
    family_code: str,
    *,
    extra_patterns: tuple[str, ...] = (),
) -> AbsenceProof:
    """Search ``family_code`` over the given pages (per file: a PageSource and its page numbers)."""
    import re

    family(family_code)  # KeyError on an unknown family: the vocabulary is AG-03's
    extra = [re.compile(p) for p in extra_patterns]
    proof = AbsenceProof(family_code, [s.file_id for s, _ in sources], None, 0, 0)
    for src, pages in sources:
        for pg in pages:
            proof.pages_total += 1
            has_tokens = src.has_tokens(pg)
            if not has_tokens and not _is_text_page(src.doc[pg - 1]):
                proof.unread.append((src.file_id, pg))
                continue
            page = src.page(pg)
            kind = "TOKENS" if has_tokens else "TEXT_LAYER"
            proof.pages_read += 1
            proof.pages_by_source[kind] = proof.pages_by_source.get(kind, 0) + 1
            for seg in segments(page.words, gap_em=4.0):
                from inspector_tables.text import fold

                hit = bool(match_families(seg.text, (family_code,))) or any(
                    p.search(fold(seg.text)) for p in extra
                )
                if hit:
                    src_kind = (
                        "OCR"
                        if any(not w.source.startswith("TEXT_LAYER") for w in seg.words)
                        else "TEXT_LAYER"
                    )
                    from inspector_tables.text import Box

                    proof.hits.append(
                        AbsenceHit(
                            pg, seg.text, page.norm_bbox(Box(seg.x0, seg.y0, seg.x1, seg.y1)), src_kind
                        )
                    )
    if proof.hits:
        proof.absent = False
    elif proof.unread:
        proof.absent = None
    else:
        proof.absent = True
    return proof
