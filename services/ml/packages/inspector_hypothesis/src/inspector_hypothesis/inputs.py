"""What the hypothesis engine reads: object documents, page text, layout and table artifacts, extracted values.

Everything comes from contract artifacts of one run directory (``runs/<run_id>/``, paths from
``inspector_common.runlayout``): PageTokens (AG-02A), LayoutArtifacts (AG-02B), TableArtifacts and
ExtractedValue rows (AG-02C). Documents and their resolved stages come from the manifest registry (AG-01):
``RD_ID_MIXED``/``UNKNOWN`` files are resolved with ``inspector_registry.stages.resolve_stage`` on the
recognised text of page 1, or taken from an inventory report when the run has one.

A page counts as *read* (``PageText.usable``) only when its PageTokens exist and are not ABSTAIN: absence proofs
(07 §3.3.1 «exists → FALSE only with full coverage») rely on it. Tests build inputs in memory with
:class:`MemoryPageSource`.
"""

from __future__ import annotations

import gzip
import json
import logging
from collections import OrderedDict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from inspector_common.contracts.models import ExtractedValue, LayoutArtifacts, TableArtifacts
from inspector_common.runlayout import RunLayout
from inspector_hypothesis.textmatch import norm_word

log = logging.getLogger(__name__)

A4_AREA_PT2 = 595.0 * 842.0
LARGE_FORMAT_A4 = 2.2  # pages larger than ~A3 are drawings/schemes (A4 text, A3 tables are not)

_BAD_PAGE_WARNINGS = frozenset({"PAGE_UNREADABLE", "PROCESSING_TIMEOUT", "WORKER_CRASHED"})


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    """One manifest file of the object, as far as the hypothesis engine needs it."""

    file_id: str
    stage: str | None  # resolved DocStage (PD/RD/ID); None when unresolved (never cited)
    section: str | None  # ManifestSection code (OV, AR, KR, …)
    pages_total: int | None
    file_sha256: str | None = None
    name: str | None = None
    manifest_stage: str | None = None
    citable: bool = True
    document_code: str | None = None  # from title blocks (AG-02B) when available
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    norm: str
    bbox: tuple[float, float, float, float]  # normalised [0, 1], visible rotated page, origin top-left
    line: int
    source: str | None = None
    conf: float = 1.0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2.0, (self.bbox[1] + self.bbox[3]) / 2.0)


@dataclass(slots=True)
class PageText:
    """The recognised words of one page in reading order (lines as word-index lists)."""

    file_id: str
    page_no: int
    width_pt: float
    height_pt: float
    words: list[Word]
    lines: list[list[int]]
    page_class: str | None = None
    usable: bool = True
    layers: tuple[str, ...] = ()

    @property
    def format_a4(self) -> float:
        return (self.width_pt * self.height_pt) / A4_AREA_PT2

    @property
    def is_large_format(self) -> bool:
        return self.format_a4 > LARGE_FORMAT_A4

    def line_text(self, line_idx: int) -> str:
        return " ".join(self.words[i].text for i in self.lines[line_idx])

    def full_text(self) -> tuple[str, list[int]]:
        """Running text (lines joined by spaces) and, per character, the index of its word (−1 for spaces)."""
        chunks: list[str] = []
        owners: list[int] = []
        for idxs in self.lines:
            for wi in idxs:
                if chunks:
                    chunks.append(" ")
                    owners.append(-1)
                text = self.words[wi].text
                chunks.append(text)
                owners.extend([wi] * len(text))
        return "".join(chunks), owners

    def distance_pt(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        dx = (a[0] - b[0]) * self.width_pt
        dy = (a[1] - b[1]) * self.height_pt
        return (dx * dx + dy * dy) ** 0.5


def page_text_from_tokens(doc: Mapping[str, Any], file_id: str | None = None) -> PageText:
    """PageText from a PageTokens document (contract dict); ABSTAIN tokens are dropped."""
    page = doc.get("page") or {}
    tokens = [
        t
        for t in doc.get("tokens", [])
        if t.get("quality_flag") != "ABSTAIN" and str(t.get("text", "")).strip()
    ]
    by_id = {int(t["id"]): t for t in tokens}
    order: list[list[int]] = []
    seen: set[int] = set()
    for line in doc.get("lines") or []:
        ids = [i for i in line.get("token_ids", []) if i in by_id and i not in seen]
        if ids:
            order.append(ids)
            seen.update(ids)
    rest = [t for t in tokens if int(t["id"]) not in seen]
    if rest:
        groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for t in rest:
            key = (
                (int(t.get("block_id") or 0), int(t["line_id"]))
                if t.get("line_id") is not None
                else (-1, int(t["id"]))
            )
            groups.setdefault(key, []).append(t)
        for grp in sorted(
            groups.values(), key=lambda g: (min(x["bbox"][1] for x in g), min(x["bbox"][0] for x in g))
        ):
            order.append([int(x["id"]) for x in sorted(grp, key=lambda x: x["bbox"][0])])
    words: list[Word] = []
    lines: list[list[int]] = []
    for li, ids in enumerate(order):
        idxs = []
        for tid in ids:
            t = by_id[tid]
            b = t["bbox"]
            words.append(
                Word(
                    text=str(t["text"]),
                    norm=norm_word(str(t["text"])),
                    bbox=(float(b[0]), float(b[1]), float(b[2]), float(b[3])),
                    line=li,
                    source=t.get("source"),
                    conf=float(t.get("conf", 1.0)),
                )
            )
            idxs.append(len(words) - 1)
        lines.append(idxs)
    warnings = set(doc.get("warnings") or [])
    usable = doc.get("quality_flag") != "ABSTAIN" and not (warnings & _BAD_PAGE_WARNINGS)
    return PageText(
        file_id=str(file_id or doc.get("file_id")),
        page_no=int(doc["page_no"]),
        width_pt=float(page.get("width_pt") or 595.0),
        height_pt=float(page.get("height_pt") or 842.0),
        words=words,
        lines=lines,
        page_class=doc.get("page_class"),
        usable=usable,
        layers=tuple(doc.get("layers") or ()),
    )


class PageSource(Protocol):
    def page(self, file_id: str, page_no: int) -> PageText | None: ...

    def has_page(self, file_id: str, page_no: int) -> bool: ...


class MemoryPageSource:
    """Pages held in memory (tests, synthetic fixtures)."""

    def __init__(self, pages: Iterable[PageText] = ()):
        self._pages: dict[tuple[str, int], PageText] = {}
        for p in pages:
            self.add(p)

    def add(self, page: PageText) -> None:
        self._pages[(page.file_id, page.page_no)] = page

    def page(self, file_id: str, page_no: int) -> PageText | None:
        return self._pages.get((file_id, page_no))

    def has_page(self, file_id: str, page_no: int) -> bool:
        return (file_id, page_no) in self._pages


class RunPageSource:
    """PageTokens of a run directory (``tokens/<file_id>/p<NNNNN>.json.gz``), with a small LRU cache."""

    def __init__(self, run_dir: Path, cache_size: int = 64):
        self.layout = RunLayout(Path(run_dir))
        self._cache: OrderedDict[tuple[str, int], PageText | None] = OrderedDict()
        self._cache_size = cache_size
        self.loaded = 0
        self.failed: list[tuple[str, int, str]] = []

    def _path(self, file_id: str, page_no: int) -> Path:
        return self.layout.path("PAGE_TOKENS", file_id=file_id, page=page_no)

    def has_page(self, file_id: str, page_no: int) -> bool:
        return self._path(file_id, page_no).is_file()

    def page(self, file_id: str, page_no: int) -> PageText | None:
        key = (file_id, page_no)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        path = self._path(file_id, page_no)
        result: PageText | None = None
        if path.is_file():
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    result = page_text_from_tokens(json.load(fh), file_id)
                self.loaded += 1
            except (OSError, ValueError, KeyError) as exc:
                self.failed.append((file_id, page_no, f"{type(exc).__name__}: {exc}"))
                log.warning(
                    "hyp.page_unreadable", extra={"file_id": file_id, "page": page_no, "detail": str(exc)}
                )
        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result


@dataclass
class HypothesisInputs:
    """Everything one object's hypothesis run reads. Build with :meth:`from_run` or directly in tests."""

    object_id: str
    documents: dict[str, DocumentInfo]
    pages: PageSource
    layouts: dict[str, LayoutArtifacts] = field(default_factory=dict)
    tables: dict[str, TableArtifacts] = field(default_factory=dict)
    values: list[ExtractedValue] = field(default_factory=list)
    run_id: str | None = None
    problems: list[str] = field(default_factory=list)

    # convenience ------------------------------------------------------------------------------------
    def docs(self, stage: str | None = None, sections: Iterable[str] | None = None) -> list[DocumentInfo]:
        wanted = set(sections) if sections is not None else None
        out = [
            d
            for d in self.documents.values()
            if d.citable and (stage is None or d.stage == stage) and (wanted is None or (d.section in wanted))
        ]
        return sorted(out, key=lambda d: d.file_id)

    def iter_pages(self, doc: DocumentInfo) -> Iterator[PageText]:
        for p in range(1, (doc.pages_total or 0) + 1):
            page = self.pages.page(doc.file_id, p)
            if page is not None:
                yield page

    def coverage(self, doc: DocumentInfo) -> tuple[int, int]:
        """(pages read, pages total) of a document; a page is read when its PageTokens exist and are usable."""
        total = doc.pages_total or 0
        read = 0
        for p in range(1, total + 1):
            if not self.pages.has_page(doc.file_id, p):
                continue
            page = self.pages.page(doc.file_id, p)
            if page is not None and page.usable:
                read += 1
        return read, total

    def page_code(self, file_id: str, page_no: int) -> str | None:
        """The document code (шифр) of one page: its own title block's, else that of the nearest preceding page with
        a code (a PDF may bundle documents over contiguous page ranges: F0201 «…-РД-ОВ1» and «…-РД-ОВ1.С»), else the
        first code of the file, else the file's code."""
        layout = self.layouts.get(file_id)
        coded = sorted(
            ((tb.pdf_page_number, tb.document_code) for tb in (layout.title_blocks or []) if tb.document_code)
            if layout is not None
            else []
        )
        before = [code for p, code in coded if p <= page_no]
        if before:
            return before[-1]
        if coded:
            return coded[0][1]
        doc = self.documents.get(file_id)
        return doc.document_code if doc is not None else None

    def sheet_number(self, file_id: str, page_no: int) -> str | int | None:
        layout = self.layouts.get(file_id)
        if layout is None:
            return None
        for entry in layout.sheet_page_map or []:
            if entry.pdf_page_number == page_no:
                return entry.sheet_number
        for tb in layout.title_blocks or []:
            if tb.pdf_page_number == page_no:
                return tb.sheet_number
        return None

    # loading ----------------------------------------------------------------------------------------
    @classmethod
    def from_run(
        cls,
        run_dir: Path | str,
        object_id: str,
        *,
        registry: Any | None = None,
        documents: Mapping[str, DocumentInfo] | None = None,
    ) -> HypothesisInputs:
        """Inputs of one object from a run directory. ``registry``: an ``inspector_registry`` Registry (loaded
        from the configured data root when omitted); ``documents`` overrides the document list (tests)."""
        run_dir = Path(run_dir)
        layout = RunLayout(run_dir)
        pages = RunPageSource(run_dir)
        problems: list[str] = []
        docs = (
            dict(documents)
            if documents is not None
            else _documents_from_registry(object_id, registry, pages, layout)
        )
        layouts: dict[str, LayoutArtifacts] = {}
        tables: dict[str, TableArtifacts] = {}
        for fid in sorted(docs):
            lp = layout.path("LAYOUT", file_id=fid)
            if lp.is_file():
                try:
                    layouts[fid] = LayoutArtifacts.model_validate_json(lp.read_text(encoding="utf-8"))
                except ValueError as exc:
                    problems.append(f"layout {fid}: {exc.__class__.__name__}")
            tp = layout.path("TABLES", file_id=fid)
            if tp.is_file():
                try:
                    tables[fid] = TableArtifacts.model_validate_json(tp.read_text(encoding="utf-8"))
                except ValueError as exc:
                    problems.append(f"tables {fid}: {exc.__class__.__name__}")
        values: list[ExtractedValue] = []
        vp = layout.path("EXTRACTED_VALUES", object_id=object_id)
        if vp.is_file():
            with open(vp, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if line.strip():
                        try:
                            values.append(ExtractedValue.model_validate_json(line))
                        except ValueError:
                            problems.append(f"values line {n}: invalid ExtractedValue")
        docs = enrich_with_layouts(docs, layouts)
        return cls(
            object_id=object_id,
            documents=docs,
            pages=pages,
            layouts=layouts,
            tables=tables,
            values=values,
            run_id=run_dir.name,
            problems=problems,
        )


def enrich_with_layouts(
    documents: Mapping[str, DocumentInfo], layouts: Mapping[str, LayoutArtifacts]
) -> dict[str, DocumentInfo]:
    """Documents with the title-block code and revision (majority per file, AG-02B) where a layout exists."""
    return {
        fid: (_with_title_block(d, layouts[fid]) if fid in layouts else d) for fid, d in documents.items()
    }


def _with_title_block(doc: DocumentInfo, la: LayoutArtifacts) -> DocumentInfo:
    from collections import Counter

    codes = Counter(tb.document_code for tb in la.title_blocks or [] if tb.document_code)
    revs = Counter(tb.revision for tb in la.title_blocks or [] if tb.revision)
    if not codes and not revs:
        return doc
    return DocumentInfo(
        file_id=doc.file_id,
        stage=doc.stage or (la.stage.value if la.stage is not None else None),
        section=doc.section,
        pages_total=doc.pages_total,
        file_sha256=doc.file_sha256,
        name=doc.name,
        manifest_stage=doc.manifest_stage,
        citable=doc.citable,
        document_code=codes.most_common(1)[0][0] if codes else doc.document_code,
        revision=revs.most_common(1)[0][0] if revs else doc.revision,
    )


def _documents_from_registry(
    object_id: str, registry: Any | None, pages: PageSource, layout: RunLayout
) -> dict[str, DocumentInfo]:
    from inspector_registry.stages import resolve_stage

    if registry is None:
        from inspector_registry.api import open_registry

        registry, _ = open_registry()
    inventory = _inventory_stages(layout, object_id)
    docs: dict[str, DocumentInfo] = {}
    for f in registry.files(object_id):
        if not f.is_pdf:
            continue
        stage = inventory.get(f.file_id)
        if stage is None:
            if f.stage in ("PD", "RD", "ID"):
                stage = f.stage
            else:
                first = pages.page(f.file_id, 1)
                text = " ".join(w.text for w in first.words[:400]) if first is not None else None
                stage = resolve_stage(f.stage, f.relative_path, text).stage_resolved
        docs[f.file_id] = DocumentInfo(
            file_id=f.file_id,
            stage=stage,
            section=f.section,
            pages_total=f.pdf_pages,
            file_sha256=f.sha256,
            name=f.name,
            manifest_stage=f.stage,
            citable=registry.is_citable(f.file_id),
        )
    return docs


def _inventory_stages(layout: RunLayout, object_id: str) -> dict[str, str]:
    """Resolved stages from an inventory report in this run directory, when there is one."""
    path = layout.path("INVENTORY", object_id=object_id)
    if not path.is_file():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for f in report.get("files", []):
        st = (f.get("stage") or {}).get("stage_resolved")
        if st:
            out[f["file_id"]] = st
    return out
