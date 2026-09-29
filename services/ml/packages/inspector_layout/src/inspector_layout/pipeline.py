"""`inspector-batch layout`: per-file page scans in worker processes, then object-level assembly.

1. Page scans (:mod:`pagescan`) run in a process pool on page chunks (≤ ``workers`` processes; the OCR engine
   loads only in workers that meet an outlined stamp).
2. Per object: QR targets are linked across its files (:func:`qr.link_targets`), then per file the title
   blocks, the QR links and the sheet ↔ page map (:func:`sheetmap.build_sheet_map`) are assembled.
3. Optional sections from the room/CAD half of the package (AG-02B-2): if ``inspector_layout.rooms.fileproc``
   exposes ``layout_sections(doc, file_ctx) -> dict``, its ``rooms``, ``tags``, ``cad_layers``,
   ``revision_clouds``, ``warnings``, ``timings_ms`` and ``ext`` are merged (see ``SECTION_PROVIDER``).
4. Each file's document is validated against ``layout_artifacts`` and written atomically to
   ``RunLayout(run_dir).path("LAYOUT", file_id=…)``.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import logging
import os
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inspector_layout.codes import CodeRegistry
from inspector_layout.pagescan import PageScanner, ScanOptions
from inspector_layout.qr import link_targets, parse_payload
from inspector_layout.sheetmap import PageSheet, build_sheet_map

log = logging.getLogger("inspector.layout")

SECTION_PROVIDER = ("inspector_layout.rooms.fileproc", "layout_sections")
SECTION_KEYS = ("rooms", "tags", "cad_layers", "revision_clouds")
DOC_STAGES = ("PD", "RD", "ID")


@dataclass(frozen=True, slots=True)
class FileTask:
    file_id: str
    object_id: str
    path: str
    sha256: str
    manifest_stage: str
    pages: tuple[int, ...]
    resolved_stage: str | None = None  # AG-01's per-file stage for RD_ID_MIXED/UNKNOWN rows (inventory)

    @property
    def stage_hint(self) -> str | None:
        if self.manifest_stage in DOC_STAGES:
            return self.manifest_stage
        return self.resolved_stage if self.resolved_stage in DOC_STAGES else None


@dataclass(slots=True)
class FileResult:
    task: FileTask
    pages_total: int = 0
    scans: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    wall_s: float = 0.0


# ── worker side ─────────────────────────────────────────────────────────────────────────────────

_W: dict[str, Any] = {}


def _init_worker(registries: dict[str, CodeRegistry], opts: ScanOptions) -> None:
    import cv2
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    cv2.setNumThreads(max(1, opts.threads))
    logging.getLogger().setLevel(logging.WARNING)
    _W["scanners"] = {oid: PageScanner(reg, opts) for oid, reg in registries.items()}


def _scan_chunk(task: FileTask) -> dict[str, Any]:
    import pymupdf

    t0 = time.perf_counter()
    scanner: PageScanner = _W["scanners"][task.object_id]
    scanner.new_document()
    out: dict[str, Any] = {"file_id": task.file_id, "pages_total": 0, "scans": [], "errors": []}
    try:
        doc = pymupdf.open(task.path)
    except Exception as exc:  # corrupt file
        out["errors"].append({"code": "FILE_CORRUPTED", "detail": f"{type(exc).__name__}: {exc}"[:300]})
        return out
    with doc:
        out["pages_total"] = len(doc)
        for p in task.pages:
            if p > len(doc):
                continue
            try:
                s = scanner.scan(doc, p, file_id=task.file_id, stage_hint=task.stage_hint)
                out["scans"].append(s.as_dict())
            except Exception as exc:
                out["errors"].append(
                    {
                        "code": "PAGE_UNREADABLE",
                        "page": str(p),
                        "detail": f"{type(exc).__name__}: {exc}"[:300],
                    }
                )
    out["wall_s"] = round(time.perf_counter() - t0, 3)
    return out


# ── orchestration ───────────────────────────────────────────────────────────────────────────────


def chunk_tasks(tasks: Iterable[FileTask], chunk_pages: int = 24) -> list[FileTask]:
    out: list[FileTask] = []
    for t in tasks:
        pages = list(t.pages)
        for i in range(0, len(pages), chunk_pages):
            out.append(dataclasses.replace(t, pages=tuple(pages[i : i + chunk_pages])))
    return out


def scan_files(
    tasks: list[FileTask],
    registries: dict[str, CodeRegistry],
    opts: ScanOptions,
    *,
    workers: int = 3,
    chunk_pages: int = 24,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, FileResult]:
    """Scan every page of ``tasks``; returns file_id → FileResult (scans sorted by page)."""
    results: dict[str, FileResult] = {t.file_id: FileResult(t) for t in tasks}
    chunks = chunk_tasks(tasks, chunk_pages)
    t_start = time.perf_counter()

    def collect(r: dict[str, Any]) -> None:
        fr = results[r["file_id"]]
        fr.pages_total = max(fr.pages_total, int(r.get("pages_total", 0)))
        fr.scans.extend(r["scans"])
        fr.errors.extend(r["errors"])
        fr.wall_s += float(r.get("wall_s", 0.0))

    if workers <= 1 or len(chunks) <= 1:
        _init_worker(registries, opts)
        for i, c in enumerate(chunks, 1):
            collect(_scan_chunk(c))
            if progress:
                progress(c.file_id, i, len(chunks))
    else:
        import multiprocessing as mp

        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(workers, len(chunks)),
            mp_context=ctx,
            initializer=_init_worker,
            initargs=(registries, opts),
        ) as ex:
            futs = {ex.submit(_scan_chunk, c): c for c in chunks}
            for i, fut in enumerate(as_completed(futs), 1):
                c = futs[fut]
                try:
                    collect(fut.result())
                except Exception as exc:  # a worker died: its pages are reported, the run goes on
                    for p in c.pages:
                        results[c.file_id].errors.append(
                            {
                                "code": "WORKER_CRASHED",
                                "page": str(p),
                                "detail": f"{type(exc).__name__}: {exc}"[:300],
                            }
                        )
                if progress:
                    progress(c.file_id, i, len(chunks))
    for fr in results.values():
        fr.scans.sort(key=lambda s: s["page"])
    log.info(
        "layout.scan.done",
        extra={"files": len(tasks), "chunks": len(chunks), "wall_s": round(time.perf_counter() - t_start, 2)},
    )
    return results


def _section_provider() -> Callable[..., dict[str, Any]] | None:
    mod_name, fn_name = SECTION_PROVIDER
    try:
        mod = importlib.import_module(mod_name)
    except ImportError:
        return None
    fn = getattr(mod, fn_name, None)
    return fn if callable(fn) else None


def assemble_object(
    object_id: str,
    results: dict[str, FileResult],
    *,
    pipeline_version: str,
    generated_at: str | None = None,
    resolved_stages: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """LayoutArtifacts documents (title blocks, sheet map, QR links) of every file of one object."""
    generated_at = generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = {fid: fr for fid, fr in results.items() if fr.task.object_id == object_id}
    hits = {fid: [(s["page"], q["payload"]) for s in fr.scans for q in s["qr"]] for fid, fr in files.items()}
    targets = link_targets(hits)
    # Exon page indices are 1-based on some documents (F0201 p17 → «wd/17») and 0-based on others (Новослободская
    # F0136 p1 → «wd/0»): a key seen with page 0 is 0-based and its pages are reported + 1, so ``doc_page`` is
    # always the 1-based page of the source document (contract minimum 1). Linking compares raw pages.
    zero_based = sorted(
        {
            pq.doc_key
            for items in hits.values()
            for _, pay in items
            if (pq := parse_payload(pay)).doc_page == 0
        }
        - {None}
    )

    def doc_page_of(pq) -> int | None:
        if pq.doc_page is None:
            return None
        page = pq.doc_page + 1 if pq.doc_key in zero_based else pq.doc_page
        return page if page >= 1 else None

    docs: dict[str, dict[str, Any]] = {}
    for fid, fr in sorted(files.items()):
        title_blocks = [s["title_block"] for s in fr.scans if s.get("title_block")]
        qr_links = []
        page_qr: dict[int, tuple[str | None, int | None]] = {}
        for s in fr.scans:
            for q in s["qr"]:
                pq = parse_payload(q["payload"])
                tgt = targets.get((fid, s["page"], q["payload"]))
                qr_links.append(
                    {
                        "pdf_page_number": s["page"],
                        "bbox": q["bbox"],
                        "payload": q["payload"],
                        "doc_key": pq.doc_key,
                        "doc_page": doc_page_of(pq),
                        "target_file_id": tgt.file_id if tgt else None,
                        "target_pdf_page_number": tgt.pdf_page_number if tgt else None,
                    }
                )
                if pq.kind == "EXON" and s["page"] not in page_qr:
                    page_qr[s["page"]] = (pq.doc_key, doc_page_of(pq))
        sheets = []
        tb_pages = {tb["pdf_page_number"]: tb for tb in title_blocks}
        for s in fr.scans:
            tb = tb_pages.get(s["page"])
            key, qpage = page_qr.get(s["page"], (None, None))
            if tb is None and key is None:
                continue
            fc = (tb or {}).get("fields_confidence", {})
            sheets.append(
                PageSheet(
                    page=s["page"],
                    sheet=(tb or {}).get("sheet_number"),
                    code=(tb or {}).get("document_code"),
                    confidence=float(fc.get("sheet_number", 0.0)),
                    title_block=tb is not None,
                    sheet_title=(tb or {}).get("sheet_title"),
                    qr_key=key,
                    qr_page=qpage,
                    trusted=str(s.get("sheet_source") or "").startswith("TEXT_LAYER"),
                    sheets_total=(tb or {}).get("sheets_total"),
                )
            )
        sheet_map = build_sheet_map(sheets)
        # File stage: the manifest when it says PD/RD/ID, else AG-01's resolution (inventory), never the stamps:
        # ИД extracts of RD sheets (F0197–F0200) print «РД» in their stamps.
        stage = fr.task.manifest_stage if fr.task.manifest_stage in DOC_STAGES else None
        if stage is None:
            stage = (resolved_stages or {}).get(fid) or fr.task.stage_hint
        stamp_stages = Counter(tb.get("stage") for tb in title_blocks if tb.get("stage"))
        conflicts = [
            {  # details of META_CONFLICT (errors.yaml): field, registry_value, stamp_value
                "pdf_page_number": tb["pdf_page_number"],
                "field": "stage",
                "registry_value": stage,
                "stamp_value": tb.get("stage_raw"),
                "stamp_stage": tb["stage"],
            }
            for tb in title_blocks
            if stage in ("PD", "RD") and tb.get("stage") in ("PD", "RD") and tb["stage"] != stage
        ]
        warnings = {e["code"] for e in fr.errors}
        if conflicts:
            warnings.add(
                "META_CONFLICT"
            )  # a stamp's «Стадия» contradicts the file stage (F0202 p14 prints «П»)
        warnings = sorted(warnings)
        ocr_pages = sum(1 for s in fr.scans if s.get("ocr_ms"))
        doc = {
            "schema_version": 1,
            "file_id": fid,
            "object_id": object_id,
            "file_sha256": fr.task.sha256,
            "stage": stage,
            "pipeline_version": pipeline_version,
            "generated_at": generated_at,
            "pages_total": fr.pages_total,
            "title_blocks": title_blocks,
            "sheet_page_map": sheet_map,
            "rooms": [],
            "tags": [],
            "cad_layers": [],
            "revision_clouds": [],
            "qr_links": qr_links,
            "warnings": warnings,
            "timings_ms": {
                "scan_wall_ms": round(fr.wall_s * 1000, 1),
                **{
                    k: round(sum(float(s.get(k) or 0.0) for s in fr.scans), 1)
                    for k in ("words_ms", "grid_ms", "ocr_ms", "cell_ms", "qr_ms")
                },
            },
            "ext": {
                "title_block": {
                    "pages_scanned": len(fr.scans),
                    "found": len(title_blocks),
                    "ocr_pages": ocr_pages,
                    "ocr_qr_hidden": sum(1 for s in fr.scans if s.get("ocr_hidden_images")),
                    "cells_reread": dict(Counter(c for s in fr.scans for c in s.get("cells_reread") or [])),
                    "forms": dict(Counter(s["form"] for s in fr.scans if s.get("form"))),
                    "sources": dict(Counter(s["words_source"] for s in fr.scans if s.get("title_block"))),
                    "code_basis": dict(Counter(s["code_basis"] for s in fr.scans if s.get("code_basis"))),
                    "stamp_stages": dict(stamp_stages),
                    "stage_conflicts": conflicts[:50],
                },
                "qr": {
                    "pages": len({q["pdf_page_number"] for q in qr_links}),
                    "zero_based_keys": [k for k in zero_based if any(q["doc_key"] == k for q in qr_links)],
                },
                "errors": fr.errors[:50],
            },
        }
        docs[fid] = doc
    return docs


def run_section_provider(
    task: FileTask, doc: dict[str, Any], *, tokens_dir: str | None
) -> dict[str, Any] | None:
    """Rooms, tags, CAD layers and revision clouds of one file from the room/CAD provider, if installed.

    Call convention (keyword-only): ``layout_sections(path=, file_id=, object_id=, pages=, tokens_dir=,
    title_blocks=, sheet_page_map=) -> {"rooms": [...], "tags": [...], "cad_layers": [...],
    "revision_clouds": [...], "warnings": [...], "timings_ms": {...}, "ext": {...}}`` (any subset).
    """
    fn = _section_provider()
    if fn is None:
        return None
    return fn(
        path=task.path,
        file_id=task.file_id,
        object_id=task.object_id,
        pages=list(task.pages),
        tokens_dir=tokens_dir,
        title_blocks=doc["title_blocks"],
        sheet_page_map=doc["sheet_page_map"],
    )


def merge_sections(doc: dict[str, Any], sections: dict[str, Any]) -> None:
    for k in SECTION_KEYS:
        if sections.get(k):
            doc[k] = list(sections[k])
    if sections.get("warnings"):
        doc["warnings"] = sorted(set(doc["warnings"]) | set(sections["warnings"]))
    for k, v in (sections.get("timings_ms") or {}).items():
        doc["timings_ms"][k] = v
    if sections.get("ext"):
        doc["ext"].update(sections["ext"])


SALVAGE_SECTIONS = (
    "title_blocks",
    "sheet_page_map",
    "qr_links",
    "rooms",
    "tags",
    "cad_layers",
    "revision_clouds",
)


def salvage_invalid_items(doc: dict[str, Any], max_rounds: int = 20) -> list[str]:
    """Drop the list items the schema rejects (one bad QR payload must not cost a file its whole layout on the
    hidden run); the file gets the warning CONTRACT_VALIDATION_FAILED and ``ext.dropped_invalid`` lists what
    went. Errors outside the per-item sections are left for :func:`write_layout` to refuse."""
    from inspector_common.contracts.loader import validation_errors

    dropped: list[str] = []
    for _ in range(max_rounds):
        errors = validation_errors("layout_artifacts", doc)
        items: dict[tuple[str, int], str] = {}
        for e in errors:
            parts = e.split(": ", 1)[0].split("/")
            if len(parts) >= 2 and parts[0] in SALVAGE_SECTIONS and parts[1].isdigit():
                items.setdefault((parts[0], int(parts[1])), e)
        if not items:
            break
        for (sec, idx), err in sorted(items.items(), key=lambda kv: -kv[0][1]):
            if idx < len(doc.get(sec) or []):
                del doc[sec][idx]
                dropped.append(err[:300])
    if dropped:
        doc["warnings"] = sorted(set(doc.get("warnings") or []) | {"CONTRACT_VALIDATION_FAILED"})
        doc.setdefault("ext", {})["dropped_invalid"] = dropped[:50]
    return dropped


def write_layout(run_dir: Path, doc: dict[str, Any]) -> Path:
    from inspector_common.contracts.loader import validate
    from inspector_common.runlayout import RunLayout

    dropped = salvage_invalid_items(doc)
    if dropped:
        log.warning("layout.salvaged", extra={"file_id": doc.get("file_id"), "items": len(dropped)})
    validate("layout_artifacts", doc)
    out = RunLayout(run_dir).path("LAYOUT", file_id=doc["file_id"])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)
    return out


def options_dict(opts: ScanOptions) -> dict[str, Any]:
    return asdict(opts)


def group_tasks_by_object(tasks: Iterable[FileTask]) -> dict[str, list[FileTask]]:
    out: dict[str, list[FileTask]] = defaultdict(list)
    for t in tasks:
        out[t.object_id].append(t)
    return out
