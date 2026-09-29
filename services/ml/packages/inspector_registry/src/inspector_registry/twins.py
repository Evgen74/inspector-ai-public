"""DWG/DOCX ↔ PDF twin linking by name and sheet number (97 §2.12; the PDF is what gets cited).

Only PDFs of the same object in the same folder are candidates ("same-folder twin"). Loose DWG/DOCX
manifest files are linked to the best-matching PDF; an archive is linked as a whole (its DWG members
are the sheets of that PDF), and each DWG member gets a sheet number and, when the member count and
the PDF page count make it unambiguous, a page hint. Confidence is reported, never hidden; stamp and
text-Jaccard page maps come later (AG-02B).

Confidence ladder (frozen before any hidden-object run):
- 0.98 match keys equal; 0.90 similarity ≥ 90; 0.80 ≥ 80; 0.65 ≥ 65;
- 0.50 when the folder holds exactly one PDF and nothing matched better;
- × 0.8 when the runner-up is within 3 similarity points (ambiguous);
- archives: + 0.05 when 0 ≤ PDF pages − DWG members ≤ 4, − 0.10 when there are more DWG than pages.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from inspector_registry.manifest import ManifestFile
from inspector_registry.names import match_key, sheet_number, split_stem

TWIN_VERSION = "twins-1"
MIN_LINK_CONFIDENCE = 0.5
MAX_COVER_PAGES = 4


@dataclass(slots=True)
class TwinLink:
    file_id: str
    confidence: float
    basis: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"file_id": self.file_id, "confidence": self.confidence, "basis": self.basis}


def similarity(a: str, b: str) -> float:
    ka, kb = match_key(a), match_key(b)
    if not ka or not kb:
        return 0.0
    return round(0.5 * fuzz.ratio(ka, kb) + 0.5 * fuzz.token_set_ratio(ka, kb), 1)


def _ladder(score: float, keys_equal: bool) -> float:
    if keys_equal:
        return 0.98
    if score >= 90:
        return 0.90
    if score >= 80:
        return 0.80
    if score >= 65:
        return 0.65
    return 0.0


def _best(names: Sequence[str], pdfs: Sequence[ManifestFile]) -> TwinLink | None:
    """Best PDF for a set of names describing the source (file stem, archive stem, member prefix)."""
    if not pdfs:
        return None
    scored: list[tuple[float, bool, ManifestFile, str]] = []
    for pdf in pdfs:
        best_score, best_equal, best_name = 0.0, False, ""
        for name in names:
            if not name:
                continue
            equal = match_key(name) == match_key(pdf.name) and bool(match_key(name))
            score = 100.0 if equal else similarity(name, pdf.name)
            if (equal, score) > (best_equal, best_score):
                best_score, best_equal, best_name = score, equal, name
        scored.append((best_score, best_equal, pdf, best_name))
    scored.sort(key=lambda t: (t[1], t[0]), reverse=True)
    score, equal, pdf, via = scored[0]
    confidence = _ladder(score, equal)
    basis: dict[str, Any] = {"name_similarity": score, "keys_equal": equal, "matched_name": via}
    if confidence == 0.0 and len(pdfs) == 1:
        confidence = 0.5
        basis["only_pdf_in_folder"] = True
    if len(scored) > 1 and not equal and scored[0][0] - scored[1][0] < 3:
        confidence = round(confidence * 0.8, 3)
        basis["ambiguous_with"] = scored[1][2].file_id
    if confidence < MIN_LINK_CONFIDENCE:
        return None
    return TwinLink(file_id=pdf.file_id, confidence=round(confidence, 3), basis=basis)


def same_folder_pdfs(target: ManifestFile, files: Sequence[ManifestFile]) -> list[ManifestFile]:
    return [
        f
        for f in files
        if f.is_pdf
        and f.object_id == target.object_id
        and f.folder == target.folder
        and f.file_id != target.file_id
    ]


def link_loose(target: ManifestFile, files: Sequence[ManifestFile]) -> TwinLink | None:
    """Twin PDF of a loose DWG/DXF/DOCX manifest file."""
    link = _best([target.name], same_folder_pdfs(target, files))
    if link is not None:
        sheet = sheet_number(target.name)
        if sheet is not None:
            link.basis["sheet_number"] = sheet.number
    return link


def _common_prefix(stems: Sequence[str]) -> str:
    if len(stems) < 2:
        return stems[0] if stems else ""
    prefix = os.path.commonprefix([s.casefold() for s in stems])
    return prefix.strip(" _-.") if len(prefix.strip(" _-.")) >= 3 else ""


@dataclass(slots=True)
class MemberTwin:
    twin_file_id: str
    confidence: float
    sheet_number: int | None
    sheet_explicit: bool
    page_hint: int | None


@dataclass(slots=True)
class ArchiveTwins:
    archive_link: TwinLink | None
    members: dict[int, MemberTwin]  # by member index
    dwg_members: int
    page_offset: int | None  # PDF pages − DWG members, when used for page hints


def link_archive(
    archive: ManifestFile,
    member_paths: dict[int, str],  # index → member path, DWG/DXF members only
    files: Sequence[ManifestFile],
    pdf_pages: dict[str, int | None],
) -> ArchiveTwins:
    """Link an archive of drawings to its same-folder PDF twin, and each DWG member to a sheet."""
    pdfs = same_folder_pdfs(archive, files)
    stems = [split_stem(p.rsplit("/", 1)[-1])[0] for p in member_paths.values()]
    names = [archive.name, _common_prefix(stems)]
    link = _best(names, pdfs)
    n_dwg = len(member_paths)
    page_offset: int | None = None
    if link is not None:
        pages = pdf_pages.get(link.file_id)
        link.basis["dwg_members"] = n_dwg
        link.basis["pdf_pages"] = pages
        if pages is not None and n_dwg:
            delta = pages - n_dwg
            link.basis["pages_minus_dwg"] = delta
            if 0 <= delta <= MAX_COVER_PAGES:
                link.confidence = round(min(0.99, link.confidence + 0.05), 3)
                page_offset = delta
            elif delta < 0:
                link.confidence = round(max(0.0, link.confidence - 0.10), 3)
        if link.confidence < MIN_LINK_CONFIDENCE:
            link = None
            page_offset = None
    members: dict[int, MemberTwin] = {}
    if link is None:
        return ArchiveTwins(None, members, n_dwg, None)
    sheets = {i: sheet_number(p.rsplit("/", 1)[-1]) for i, p in member_paths.items()}
    numbers = [s.number for s in sheets.values() if s is not None]
    sheets_usable = (
        page_offset is not None
        and len(numbers) == n_dwg
        and len(set(numbers)) == n_dwg
        and min(numbers) >= 1
        and max(numbers) <= n_dwg
    )
    for index, sheet in sheets.items():
        factor = 0.9 if sheet is not None and sheet.explicit else 0.8 if sheet is not None else 0.7
        page_hint = (
            sheet.number + page_offset
            if sheets_usable and sheet is not None and page_offset is not None
            else None
        )
        members[index] = MemberTwin(
            twin_file_id=link.file_id,
            confidence=round(link.confidence * factor, 3),
            sheet_number=sheet.number if sheet else None,
            sheet_explicit=bool(sheet and sheet.explicit),
            page_hint=page_hint,
        )
    return ArchiveTwins(link, members, n_dwg, page_offset if sheets_usable else None)
