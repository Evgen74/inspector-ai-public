"""One PDF → the room/CAD part of its LayoutArtifacts: ``rooms``, ``tags``, ``cad_layers``, ``revision_clouds``.

Which pages: drawing sheets only — pages larger than A4 × 1.5 or pages that reference CAD layers (OCG).
Binders such as F0201 (676 pages: 159 drawings, ≈420 equipment printouts, 80 VRF pages) are filtered to their
drawings in milliseconds. Each page runs :func:`inspector_layout.rooms.page.process_page`; pages are spread
over at most ``workers`` processes (3 by default: the host is shared).

The fragment merges into the file's LayoutArtifacts next to the title blocks, sheet map and QR links of the
other AG-02B stage (:func:`merge_fragment`); :func:`build_layout_artifacts` makes a complete, schema-valid
document from the fragment alone (standalone runs and tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inspector_layout.cad.layers import layer_catalog
from inspector_layout.rooms.grammar import Vocabulary, parse_tags
from inspector_layout.rooms.inventory import inventories
from inspector_layout.rooms.page import PageResult, process_page
from inspector_layout.rooms.tokens import load_page_tokens

ROOMS_STAGE_VERSION = "rooms-1.0.0"
A4_AREA_PT2 = 595.0 * 842.0


@dataclass(frozen=True, slots=True)
class FileInput:
    file_id: str
    path: Path
    tokens_dir: Path | None  # runs/<run_id>/tokens/<file_id>/ (PageTokens), or None
    pages: tuple[int, ...] | None = None  # 1-based; None = every drawing page


def tokens_path(tokens_dir: Path | None, page_no: int) -> Path | None:
    if tokens_dir is None:
        return None
    return tokens_dir / f"p{page_no:05d}.json.gz"


def is_drawing_page(page, ocgs: dict | None = None) -> bool:
    """A drawing sheet: larger than 1.5 × A4, or a page whose resources reference CAD layers.

    ``ocgs``: ``doc.get_ocgs()`` computed once per document (40 ms per call on a 3 128-OCG binder).
    """
    if page.rect.width * page.rect.height >= 1.5 * A4_AREA_PT2:
        return True
    if ocgs is not None and not ocgs:
        return False
    try:
        from inspector_docproc.layers import page_layer_names

        return bool(page_layer_names(page, ocgs, limit=20))
    except Exception:
        return False


def select_pages(doc, pages: Iterable[int] | None) -> list[int]:
    from inspector_layout.cad.layers import document_ocgs

    ocgs = document_ocgs(doc)
    wanted = sorted(set(pages)) if pages else range(1, doc.page_count + 1)
    return [p for p in wanted if 1 <= p <= doc.page_count and is_drawing_page(doc[p - 1], ocgs)]


def vocabulary_from_tokens(tokens_dirs: Iterable[Path | None]) -> Vocabulary:
    """Vent tags printed in text layers (trusted) of the recognised pages: the closed vocabulary."""
    vocab = Vocabulary()
    for d in tokens_dirs:
        if d is None or not d.is_dir():
            continue
        for f in sorted(d.glob("p*.json.gz")):
            data = load_page_tokens(f)
            if not data:
                continue
            for t in data.get("tokens", []):
                if not str(t.get("source", "")).startswith("TEXT_LAYER"):
                    continue
                for m in parse_tags(str(t.get("text", "")), heating=False):
                    if m.tag_kind == "VENT_SYSTEM" and m.subkind in ("branch", "system"):
                        vocab.add([m.tag_norm])
    return vocab


def text_layer_vocabulary(pdf_paths: Iterable[Path]) -> Vocabulary:
    """Vent tags printed as text on the drawing pages of the given PDFs (the object's own trusted marks).

    PD schematics print every system and branch as text (F0171: «В2.1» … «В2.10», «П9»), while the RD plans
    draw them as curves; the union is the closed vocabulary that repairs the OCR of outlined marks. Text-layer
    words only (no OCR, no render): ≈ 2–3 ms per drawing page.
    """
    import pymupdf

    from inspector_layout.cad.layers import document_ocgs

    vocab = Vocabulary()
    pymupdf.TOOLS.mupdf_display_errors(False)
    for path in pdf_paths:
        try:
            doc = pymupdf.open(path)
        except Exception:
            continue
        with doc:
            ocgs = document_ocgs(doc)
            for p in range(doc.page_count):
                page = doc[p]
                if not is_drawing_page(page, ocgs):
                    continue
                lines: dict[tuple[int, int], list[str]] = {}
                for w in page.get_text("words"):
                    lines.setdefault((w[5], w[6]), []).append(w[4])
                for words in lines.values():
                    for m in parse_tags(" ".join(words), heating=False):
                        if m.tag_kind == "VENT_SYSTEM" and m.subkind in ("branch", "system"):
                            vocab.add([m.tag_norm])
    return vocab


VOCAB_VERSION = "vocab-1"
# Documents whose drawings carry vent/heating marks: ОВ (отопление и вентиляция), ИОС 5.4, АОВ, by name.
_VENT_DOCS = re.compile(
    r"(?:^|[^А-ЯЁа-яё])(?:ОВ\d*(?:\.\d)?|ОВиК|ИОС\s?4|АОВ)(?:[^А-ЯЁа-яё]|$)|отоплен|вентиляц|кондицион|(?:^|\D)5\.4(?:\D|$)",
    re.IGNORECASE,
)


def is_vent_document(relative_path: str) -> bool:
    return bool(_VENT_DOCS.search(relative_path))


def cached_file_vocabulary(path: Path, cache_dir: Path | None) -> set[str]:
    """:func:`text_layer_vocabulary` of one PDF, cached in ``cache_dir`` (key: path, size, mtime, version)."""
    try:
        st = path.stat()
    except OSError:
        return set()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{VOCAB_VERSION}".encode()).hexdigest()
    cfile = cache_dir / f"{key}.json" if cache_dir is not None else None
    if cfile is not None and cfile.is_file():
        try:
            return set(json.loads(cfile.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    tags = set(text_layer_vocabulary([path]).tags)
    if cfile is not None:
        try:
            cfile.parent.mkdir(parents=True, exist_ok=True)
            tmp = cfile.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(sorted(tags), ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, cfile)
        except OSError:
            pass
    return tags


def object_text_vocabulary(
    object_id: str | None, current: Path | None = None, cache_dir: Path | None = None
) -> Vocabulary:
    """Vent tags of the text layers of the object's vent/heating documents (plus ``current``)."""
    paths: list[Path] = []
    if object_id:
        try:
            from inspector_common.settings import get_settings
            from inspector_docproc.inputs import select_files

            jobs, _ = select_files(get_settings().paths, [object_id], None)
            paths = [j.path for j in jobs if is_vent_document(j.relative_path)]
        except Exception:  # no manifest (tests, ad-hoc files): the current file alone
            paths = []
    if current is not None and current not in paths:
        paths.append(current)
    vocab = Vocabulary()
    for p in paths:
        vocab.add(cached_file_vocabulary(Path(p), cache_dir))
    return vocab


def default_vocab_cache() -> Path | None:
    """``.cache/inspector_layout/vocab``; ``INSPECTOR_LAYOUT_VOCAB_CACHE`` = a directory, or «off» (no cache)."""
    env = os.environ.get("INSPECTOR_LAYOUT_VOCAB_CACHE")
    if env:
        return None if env.lower() == "off" else Path(env)
    try:
        from inspector_common.settings import get_settings

        return get_settings().paths.cache_root / "inspector_layout" / "vocab"
    except Exception:
        return None


# ── workers ──────────────────────────────────────────────────────────────────────────────────

_DOC = None
_DOC_PATH: str | None = None


def _open(path: str):
    global _DOC, _DOC_PATH
    if _DOC is None or path != _DOC_PATH:
        import pymupdf

        pymupdf.TOOLS.mupdf_display_errors(False)
        if _DOC is not None:
            _DOC.close()
        _DOC = pymupdf.open(path)
        _DOC_PATH = path
    return _DOC


def _run_pages(
    path: str, tokens_dir: str | None, pages: list[int], vocab: Vocabulary | None
) -> list[PageResult]:
    import cv2

    cv2.setNumThreads(1)  # one core per worker: the host is shared (CLAUDE.md CPU etiquette)
    from inspector_layout.cad.layers import document_ocgs

    doc = _open(path)
    ocgs = document_ocgs(doc)
    tdir = Path(tokens_dir) if tokens_dir else None
    out = []
    for p in pages:
        try:
            out.append(process_page(doc[p - 1], p, tokens_path(tdir, p), vocab, ocgs=ocgs))
        except Exception as exc:  # one broken page must not stop the file
            r = PageResult(p)
            r.warnings.append("PAGE_UNREADABLE")
            r.title = f"{type(exc).__name__}: {exc}"[:200]
            out.append(r)
    return out


def _chunks(pages: list[int], n: int) -> list[list[int]]:
    if n <= 1:
        return [pages] if pages else []
    size = max(1, min(4, (len(pages) + n * 3 - 1) // (n * 3)))
    return [pages[i : i + size] for i in range(0, len(pages), size)]


def process_file(
    fi: FileInput, vocab: Vocabulary | None = None, workers: int = 1
) -> tuple[dict[str, Any], list[PageResult]]:
    """Run the room/CAD stage on one PDF. Returns (fragment, page results)."""
    import pymupdf

    t0 = time.perf_counter()
    pymupdf.TOOLS.mupdf_display_errors(False)
    with pymupdf.open(fi.path) as doc:
        pages = select_pages(doc, fi.pages)
    t_sel = time.perf_counter() - t0
    results: list[PageResult] = []
    from inspector_common.resources import worker_budget

    workers = max(1, min(worker_budget(1, workers), len(pages) or 1))
    tdir = str(fi.tokens_dir) if fi.tokens_dir else None
    if workers == 1:
        results = _run_pages(str(fi.path), tdir, pages, vocab)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [
                ex.submit(_run_pages, str(fi.path), tdir, chunk, vocab) for chunk in _chunks(pages, workers)
            ]
            for f in futs:
                results.extend(f.result())
    results.sort(key=lambda r: r.page_no)
    with pymupdf.open(fi.path) as doc:
        catalog = layer_catalog(doc, {r.page_no: r.layers for r in results})
    fragment = assemble(results, catalog.cad_layers())
    fragment["timings_ms"]["select_pages"] = round(t_sel * 1000, 1)
    fragment["timings_ms"]["wall"] = round((time.perf_counter() - t0) * 1000, 1)
    fragment["ext"]["rooms_stage"]["workers"] = workers
    return fragment, results


def assemble(results: list[PageResult], cad_layers: list[dict[str, Any]]) -> dict[str, Any]:
    rooms, tags, clouds, warnings = [], [], [], []
    timings: Counter = Counter()
    pages_summary = []
    for r in results:
        rooms.extend(r.rooms)
        tags.extend(r.tags)
        clouds.extend(r.clouds)
        for w in r.warnings:
            if w not in warnings:
                warnings.append(w)
        for k, v in r.timings_ms.items():
            timings[k] += v
        pages_summary.append(
            {
                "page": r.page_no,
                "kind": r.kind,
                "floor": r.floor,
                "title": r.title,
                "zones": r.zone_method,
                "rooms": sum(1 for x in r.rooms if x["source"] != "EXPLICATION_TABLE"),
                "explication_rows": sum(1 for x in r.rooms if x["source"] == "EXPLICATION_TABLE"),
                "tags": len(r.tags),
                "clouds": len(r.clouds),
                "tokens": r.token_origin,
                "skipped": r.skipped,
                "ms": r.timings_ms.get("total"),
            }
        )
    stage_ext = {"version": ROOMS_STAGE_VERSION, "pages": pages_summary}
    stage_ext["inventories"] = inventory_rows(
        {"rooms": rooms, "tags": tags, "ext": {"rooms_stage": stage_ext}}
    )
    return {
        "rooms": rooms,
        "tags": tags,
        "cad_layers": cad_layers,
        "revision_clouds": clouds,
        "warnings": warnings,
        "timings_ms": {f"rooms_{k}": round(v, 1) for k, v in timings.items()},
        "ext": {"rooms_stage": stage_ext},
    }


def inventory_rows(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-room inventories of every plan/schematic label (``ext.rooms_stage.inventories``), so consumers
    without the grammar (the web viewer) read «147 on p18: В2.2, В2.3, В2.4» directly. Empty rooms are kept:
    absence is data when the page was fully read (``ocr_covered``)."""
    out = []
    for _, inv in sorted(inventories(layout).items(), key=lambda kv: kv[0]):
        row = inv.summary()
        row.pop("file_id", None)
        row["page"] = row.pop("pdf_page_number")
        out.append(row)
    return out


def merge_fragment(artifacts: dict[str, Any], fragment: dict[str, Any]) -> dict[str, Any]:
    """Put the room/CAD fragment into a LayoutArtifacts dict built by the title-block stage (in place)."""
    for key in ("rooms", "tags", "cad_layers", "revision_clouds"):
        artifacts[key] = fragment.get(key, [])
    warnings = list(artifacts.get("warnings") or [])
    for w in fragment.get("warnings", []):
        if w not in warnings:
            warnings.append(w)
    artifacts["warnings"] = warnings
    timings = dict(artifacts.get("timings_ms") or {})
    timings.update(fragment.get("timings_ms", {}))
    artifacts["timings_ms"] = timings
    ext = dict(artifacts.get("ext") or {})
    ext.update(fragment.get("ext", {}))
    artifacts["ext"] = ext
    # room entries carry the sheet number of the title-block stage when it is known
    sheets = {e["pdf_page_number"]: e.get("sheet_number") for e in artifacts.get("sheet_page_map") or []}
    for room in artifacts["rooms"]:
        if room.get("sheet_number") is None and sheets.get(room["pdf_page_number"]) is not None:
            room["sheet_number"] = sheets[room["pdf_page_number"]]
    return artifacts


def build_layout_artifacts(
    *,
    file_id: str,
    object_id: str,
    file_sha256: str,
    stage: str | None,
    pages_total: int,
    fragment: dict[str, Any],
    pipeline_version: str = ROOMS_STAGE_VERSION,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": 1,
        "file_id": file_id,
        "object_id": object_id,
        "file_sha256": file_sha256,
        "stage": stage,
        "pipeline_version": pipeline_version,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages_total": pages_total,
        "title_blocks": [],
        "sheet_page_map": [],
        "qr_links": [],
    }
    return merge_fragment(doc, fragment)


# ── provider hook of inspector_layout.pipeline (the title-block half of the package) ────────

_VOCAB_CACHE: dict[str, Vocabulary] = {}


def object_vocabulary(
    tokens_root: Path | None, object_id: str | None = None, current: Path | None = None
) -> Vocabulary:
    """Closed vocabulary of an object: text-layer vent tags of every file recognised in the run (PageTokens)
    and of the object's vent/heating drawings (PD schematics print what RD plans draw as curves); cached per
    run and object in the process, per file on disk (``.cache/inspector_layout/vocab``)."""
    key = f"{tokens_root.resolve() if tokens_root else ''}|{object_id or ''}"
    if key not in _VOCAB_CACHE:
        vocab = Vocabulary()
        if tokens_root is not None and tokens_root.is_dir():
            vocab.add(vocabulary_from_tokens(sorted(p for p in tokens_root.iterdir() if p.is_dir())).tags)
        vocab.add(object_text_vocabulary(object_id, None, default_vocab_cache()).tags)
        _VOCAB_CACHE[key] = vocab
    vocab = _VOCAB_CACHE[key]
    if current is not None:
        extra = cached_file_vocabulary(current, default_vocab_cache()) - vocab.tags
        if extra:
            vocab = Vocabulary(vocab.tags | extra)
    return vocab


def layout_sections(
    *,
    path: str,
    file_id: str,
    object_id: str | None = None,
    pages: Iterable[int] | None = None,
    tokens_dir: str | None = None,
    title_blocks: list[dict[str, Any]] | None = None,
    sheet_page_map: list[dict[str, Any]] | None = None,
    workers: int | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Room/CAD sections of one file for ``inspector-batch layout`` (``inspector_layout.pipeline.SECTION_PROVIDER``).

    ``tokens_dir`` is the run's ``tokens/`` root; pages outside the drawing filter are skipped. Room entries get
    the sheet number of the title-block stage and, when the page text gave no floor, the floor of the stamp's
    sheet title («План 1-го этажа …»).
    """
    from inspector_layout.rooms.grammar import floor_from_title

    root = Path(tokens_dir) if tokens_dir else None
    fdir = root / file_id if root is not None and (root / file_id).is_dir() else None
    n_workers = workers or int(os.environ.get("INSPECTOR_LAYOUT_ROOM_WORKERS", "3"))
    fi = FileInput(file_id, Path(path), fdir, tuple(pages) if pages else None)
    vocab = object_vocabulary(root, object_id, Path(path))
    fragment, _results = process_file(fi, vocab, workers=n_workers)
    fragment["ext"]["rooms_stage"]["vocabulary_size"] = len(vocab)
    sheets = {e["pdf_page_number"]: e.get("sheet_number") for e in sheet_page_map or []}
    floors = {}
    for tb in title_blocks or []:
        fl = floor_from_title(tb.get("sheet_title") or "") if tb.get("sheet_title") else None
        if fl:
            floors[tb["pdf_page_number"]] = fl
    for room in fragment["rooms"]:
        page = room["pdf_page_number"]
        if room.get("sheet_number") is None and sheets.get(page) is not None:
            room["sheet_number"] = sheets[page]
        if room.get("floor") is None and floors.get(page):
            room["floor"] = floors[page]
    fragment["ext"]["rooms_stage"]["inventories"] = inventory_rows(fragment)  # with the stamp floors
    return fragment
