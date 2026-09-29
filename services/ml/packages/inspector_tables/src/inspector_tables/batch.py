"""inspector-batch command `tables` — OWNED BY AG-02C.

``inspector-batch tables --object <train id> [--file F…] [--table-type T…] [--workers 3] [--tokens-from RUN]``

For every PDF of the object: find the pages that carry a typed table (keyword scan of the text layer /
PageTokens), parse them (EXPLICATION, TEP, SPEC_21110, CHANGE_LOG, ID_REGISTRY, AOSR; the air-exchange table
as room→system facts), extract PD element–room assertions, type ИД binder pages, then write

* ``tables/<file_id>.json`` (TableArtifacts, one per PDF, empty ``tables`` when none) and
* ``values/<object_id>.jsonl`` (ExtractedValue, one line per fact),

both validated against the contracts before writing. Words come from the run's PageTokens when present
(``tokens/<file_id>/``), then from ``--tokens-from`` runs, then from the token cache (latest recognition
version holding the page), else from the PDF text layer. Scanned pages without tokens are skipped and
counted (``pages_unread``): tables need text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inspector_common.batch import BatchContext

OWNER = "AG-02C"
TABLE_TYPES = ("EXPLICATION", "TEP", "SPEC_21110", "DEVIATION", "CHANGE_LOG", "ID_REGISTRY", "AOSR")
EXTRA_KINDS = ("AIR_EXCHANGE", "ASSERTIONS", "BINDER", "MATERIALS", "PZPARAMS", "ENERGY", "PPM", "TEXTPARAMS")


def add_tables_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--file", dest="files", action="append", default=[], metavar="FILE_ID",
        help="Ограничить обработку файлами (можно повторять)",
    )  # fmt: skip
    parser.add_argument(
        "--table-type",
        dest="table_types",
        action="append",
        default=[],
        metavar="TABLE_TYPE",
        help="Только эти типы таблиц (TableType из контрактов: EXPLICATION, TEP, SPEC_21110, …)",
    )
    parser.add_argument(
        "--workers", type=int, default=3, help="Число процессов (по умолчанию 3: общий 12-ядерный хост)"
    )
    parser.add_argument(
        "--tokens-from", dest="tokens_from", action="append", default=[], metavar="RUN_ID",
        help="Взять PageTokens из другого прогона (можно повторять; по умолчанию — текущий прогон и кэш)",
    )  # fmt: skip
    parser.add_argument(
        "--no-cache-tokens", dest="cache_tokens", action="store_false",
        help="Не брать PageTokens из общего кэша .cache/tokens",
    )  # fmt: skip
    parser.add_argument("--pages", default=None, help="Диапазон страниц, например «1-20,25» (для отладки)")


# ── token lookup ──────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TokenPlan:
    """Where the PageTokens of one file are: explicit run dirs first, then cache version dirs."""

    run_dirs: tuple[str, ...]
    cache_dirs: tuple[str, ...]  # <cache>/tokens/<pipeline_version>/<sha[:2]>/<sha>

    def lookup(self, page_no: int) -> Path | None:
        name = f"p{page_no:05d}.json.gz"
        for d in (*self.run_dirs, *self.cache_dirs):
            p = Path(d) / name
            if p.is_file():
                return p
        return None


def _version_key(name: str) -> tuple:
    m = re.match(r"docproc-(\d+)\.(\d+)\.(\d+)\+(\w+)", name)
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 1 if m.group(4) == "coreml" else 0)


def token_plan(run_dir: Path, tokens_from: list[Path], cache_root: Path | None, file_id: str, sha256: str,
               use_cache: bool) -> TokenPlan:  # fmt: skip
    runs = [str(d / "tokens" / file_id) for d in (run_dir, *tokens_from) if (d / "tokens" / file_id).is_dir()]
    caches: list[str] = []
    if use_cache and cache_root is not None and (cache_root / "tokens").is_dir():
        versions = sorted(
            (p for p in (cache_root / "tokens").iterdir() if p.is_dir()),
            key=lambda p: _version_key(p.name),
            reverse=True,
        )
        for v in versions:
            d = v / sha256[:2] / sha256
            if d.is_dir():
                caches.append(str(d))
    return TokenPlan(tuple(runs), tuple(caches))


# ── per-file worker ───────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class FileTask:
    file_id: str
    object_id: str
    path: str
    sha256: str
    manifest_stage: str
    relative_path: str
    stage: str | None
    tokens: TokenPlan
    types: tuple[str, ...]
    pages: str | None = None


_KW = {
    "EXPLICATION": re.compile(r"экспликаци|наименование\s+помещени"),
    "TEP": re.compile(r"технико[\s\-‑–]*экономическ|\bтэп\b"),
    "SPEC_21110": re.compile(r"наименование\s+и\s+техническ|завод[\s\-‑–]*изготовител|спецификаци"),
    "CHANGE_LOG": re.compile(r"содержание\s+изменени|регистрации\s+изменени|разрешение\s+на\s+внесение"),
    "ID_REGISTRY": re.compile(r"реестр"),
    "AOSR": re.compile(r"освидетельствования\s+скрытых\s+работ"),
    "AIR_EXCHANGE": re.compile(r"воздухообмен"),
    "DEVIATION": re.compile(r"фактическ\w*\s+(значени|отклонени|размер|отметк)|отклонени\w*\s+от\s+проект"),
}


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Source:
    """PageSource over a TokenPlan (several candidate token dirs per file)."""

    def __init__(self, doc: Any, file_id: str, plan: TokenPlan) -> None:
        from inspector_tables.pagesource import PageSource

        self.plan = plan
        self.inner = PageSource(doc, file_id, None)
        self.doc = doc
        self.file_id = file_id

    def has_tokens(self, page_no: int) -> bool:
        return self.plan.lookup(page_no) is not None

    def token_path(self, page_no: int) -> Path | None:
        return self.plan.lookup(page_no)

    def page(self, page_no: int):
        from inspector_tables.pagesource import load_tokens_json, page_from_pdf, page_from_tokens

        tp = self.plan.lookup(page_no)
        pdf_page = self.doc[page_no - 1]
        if tp is not None:
            dj = load_tokens_json(tp)
            if dj is not None:
                return page_from_tokens(dj, pdf_page)
        return page_from_pdf(pdf_page, self.file_id, page_no)

    def quick_text(self, page_no: int) -> str:
        tp = self.plan.lookup(page_no)
        if tp is not None:
            from inspector_tables.pagesource import load_tokens_json

            dj = load_tokens_json(tp)
            if dj is not None:
                return " ".join(t.get("text") or "" for t in dj.get("tokens", []))
        try:
            return self.doc[page_no - 1].get_text()
        except Exception:
            return ""


def _token_text_source(src: Any, page_no: int) -> str:
    """TextSource of a page: the PageTokens' own tag, else the PDF text layer."""
    tp = src.token_path(page_no)
    if tp is None:
        return "TEXT_LAYER"
    from inspector_tables.pagesource import load_tokens_json

    dj = load_tokens_json(tp) or {}
    ts = dj.get("text_source")
    return ts if ts in ("TEXT_LAYER", "TEXT_LAYER_REPAIRED", "OCR", "OCR_LAYER_ISOLATED") else "OCR"


def process_file(task: FileTask) -> dict[str, Any]:
    """Parse one PDF → {"artifact": TableArtifacts dict, "values": [...], "stats": {...}}. A file that cannot be
    opened or parsed at all (damaged PDF, a worker-level failure) yields an empty artifact with FILE_CORRUPTED
    instead of failing the whole command (per-page failures are PAGE_UNREADABLE inside)."""
    try:
        return _process_file(task)
    except Exception as e:
        from inspector_tables import artifacts

        _log_error(task.file_id, 0, e)
        art = artifacts.table_artifacts(task.file_id, task.object_id, task.sha256, task.stage, [], generated_at=_now(),
                                        warnings=["FILE_CORRUPTED"], timings_ms={},
                                        ext={"pages": 0, "pages_read": 0, "pages_unread": 0, "error": repr(e)[:300]})  # fmt: skip
        return {"file_id": task.file_id, "object_id": task.object_id, "artifact": art, "values": [],
                "stats": {"file_errors": 1}}  # fmt: skip


def _process_file(task: FileTask) -> dict[str, Any]:
    import pymupdf

    from inspector_tables import (
        airx,
        aosr,
        artifacts,
        assertions,
        binder,
        changelog,
        deviation,
        energy,
        explication,
        igs,
        materials,
        ppmparams,
        pzparams,
        registry,
        spec21110,
        tep,
        textparams,
    )
    from inspector_tables.text import Box
    from inspector_tables.values import (
        ValueSink,
        from_aosr_refs,
        from_assertions,
        from_binder,
        from_energy,
        from_igs,
        from_materials,
        from_pz,
        from_room_systems,
        from_table,
        from_textparams,
    )

    pymupdf.TOOLS.mupdf_display_errors(False)
    t0 = time.perf_counter()
    stats: Counter[str] = Counter()
    timings: Counter[str] = Counter()
    warnings: list[str] = []
    tables: list[dict] = []
    tep_params: dict[str, dict[int, str]] = {}
    dev_evals: dict[str, dict[int, dict]] = {}
    doc = pymupdf.open(task.path)
    src = _Source(doc, task.file_id, task.tokens)
    stage = task.stage or "RD"
    sink = ValueSink(task.file_id, task.object_id, task.sha256, stage)
    pages_cache: dict[int, Any] = {}

    def page(pg: int):
        if pg not in pages_cache:
            pages_cache.clear()  # one page at a time: A0 sheets are heavy
            pages_cache[pg] = src.page(pg)
        return pages_cache[pg]

    def norm(pg: int, box: Box | None):
        if box is None:
            return None
        p = page(pg)
        return p.norm_bbox(box)

    counters: Counter[str] = Counter()
    open_registry = None
    open_spec = None
    acts: list[tuple[int, Any]] = []
    act_text: list[str] = []
    kinds: list[Any] = []
    air_rooms: list[Any] = []
    element_assertions: list[Any] = []
    want = set(task.types)
    is_id = task.stage == "ID"
    is_pd = task.stage == "PD"
    n_pages = doc.page_count
    mat_structural = (
        "MATERIALS" in want and task.stage in ("PD", "RD") and materials.is_structural(task.relative_path)
    )
    mat_acts = "MATERIALS" in want and is_id
    energy_on = "ENERGY" in want and task.stage in ("PD", "RD", "ID")
    energy_envelope = energy_on and not is_id and energy.is_envelope_source(task.relative_path)
    tx_on = "TEXTPARAMS" in want and task.stage in ("PD", "RD")
    tx_flags = textparams.source_flags(task.relative_path)
    act_family: str | None = None  # element family of the АОСР being read (binders hold many acts)
    act_no: str | None = None
    from inspector_docproc.inputs import parse_pages

    for pg in parse_pages(task.pages, n_pages):
        ts = time.perf_counter()
        raw_text = src.quick_text(pg)
        text = raw_text.lower().replace("ё", "е")
        has_text = len(text.strip()) > 5
        timings["scan"] += (time.perf_counter() - ts) * 1000
        if not has_text:
            stats["pages_unread"] += 0 if src.has_tokens(pg) else 1
            if is_id and "BINDER" in want:
                kinds.append(binder.classify_page(None, pg, False))
            open_spec = None
            continue
        stats["pages_read"] += 1
        hits = {k for k, rx in _KW.items() if rx.search(text)}
        try:
            if "EXPLICATION" in hits and "EXPLICATION" in want:
                ts = time.perf_counter()
                for le in explication.parse_page(page(pg)):
                    counters["EXPLICATION"] += 1
                    t = artifacts.explication_table(le, task.file_id, counters["EXPLICATION"])
                    tables.append(t)
                timings["EXPLICATION"] += (time.perf_counter() - ts) * 1000
            if "TEP" in hits and "TEP" in want:
                ts = time.perf_counter()
                for lt in tep.parse_page(page(pg)):
                    counters["TEP"] += 1
                    t = artifacts.tep_table(lt, task.file_id, counters["TEP"])
                    tep_params[t["table_id"]] = {
                        i + 1: r.param_code for i, r in enumerate(lt.rows) if r.param_code
                    }
                    tables.append(t)
                timings["TEP"] += (time.perf_counter() - ts) * 1000
            if "SPEC_21110" in hits and ("SPEC_21110" in want or "ASSERTIONS" in want):
                ts = time.perf_counter()
                found = spec21110.parse_page(page(pg))
                for ls in found:
                    prev = open_spec
                    if (
                        prev is not None
                        and [c.key for c in prev.parts[-1].columns] == [c.key for c in ls.parts[0].columns]
                        and prev.parts[-1].page_no == pg - 1
                    ):
                        prev.parts.extend(ls.parts)
                        prev.items.extend(ls.items)
                        prev.checks = [c for c in prev.checks if c["kind"] != "CONTINUATION_JOINED"] + [
                            {"kind": "CONTINUATION_JOINED", "passed": True, "expected": None, "actual": len(prev.parts),
                             "detail": f"Спецификация продолжена на {len(prev.parts)} листах"}]  # fmt: skip
                    else:
                        if prev is not None:
                            _emit_spec(prev, task, tables, counters, element_assertions, want)
                        open_spec = ls
                timings["SPEC_21110"] += (time.perf_counter() - ts) * 1000
                if not found and open_spec is not None and open_spec.parts[-1].page_no < pg - 1:
                    _emit_spec(open_spec, task, tables, counters, element_assertions, want)
                    open_spec = None
            if "DEVIATION" in hits and "DEVIATION" in want:
                for ld in deviation.parse_page(page(pg)):
                    counters["DEVIATION"] += 1
                    t, evals = artifacts.deviation_table(ld, task.file_id, counters["DEVIATION"])
                    dev_evals[t["table_id"]] = evals
                    tables.append(t)
            if is_id and "DEVIATION" in want and igs.SCHEME.search(text):
                ts = time.perf_counter()
                p_igs = page(pg)
                ig = igs.parse_page(p_igs)
                if ig is not None:
                    from_igs(sink, ig, norm, "OCR" if p_igs.from_tokens else "TEXT_LAYER")
                    stats["igs_pages"] += 1
                timings["IGS"] += (time.perf_counter() - ts) * 1000
            if "CHANGE_LOG" in hits and "CHANGE_LOG" in want:
                for lg in changelog.parse_page(page(pg)):
                    counters["CHANGE_LOG"] += 1
                    tables.append(artifacts.changelog_table(lg, task.file_id, counters["CHANGE_LOG"]))
            if "ID_REGISTRY" in want and ("ID_REGISTRY" in hits or open_registry is not None):
                ts = time.perf_counter()
                new = registry.parse_page(page(pg), open_registry)
                if open_registry is not None and not any(p.page_no == pg for p in open_registry.parts):
                    registry.finalize(open_registry)
                    counters["ID_REGISTRY"] += 1
                    tables.append(
                        artifacts.registry_table(open_registry, task.file_id, counters["ID_REGISTRY"])
                    )
                    open_registry = None
                for reg in new[:-1]:
                    registry.finalize(reg)
                    counters["ID_REGISTRY"] += 1
                    tables.append(artifacts.registry_table(reg, task.file_id, counters["ID_REGISTRY"]))
                if new:
                    if open_registry is not None:
                        registry.finalize(open_registry)
                        counters["ID_REGISTRY"] += 1
                        tables.append(
                            artifacts.registry_table(open_registry, task.file_id, counters["ID_REGISTRY"])
                        )
                    open_registry = new[-1]
                timings["ID_REGISTRY"] += (time.perf_counter() - ts) * 1000
            if "AOSR" in want and pg <= 3 and ("AOSR" in hits or act_text):
                act_text.append(raw_text)
            if "AIR_EXCHANGE" in hits and "ASSERTIONS" in want and src.has_tokens(pg):
                ts = time.perf_counter()
                _tables, rooms = airx.parse_page(page(pg))
                air_rooms.extend(rooms)
                timings["AIR_EXCHANGE"] += (time.perf_counter() - ts) * 1000
            if is_pd and "ASSERTIONS" in want and assertions.match_families(raw_text[:20000]):
                ts = time.perf_counter()
                p = page(pg)
                element_assertions.extend(assertions.text_assertions(p))
                element_assertions.extend(a for a in assertions.label_assertions(p) if a.extra.get("leaders"))
                timings["ASSERTIONS"] += (time.perf_counter() - ts) * 1000
            if mat_structural and materials.HINT.search(text):
                ts = time.perf_counter()
                from_materials(
                    sink,
                    pg,
                    [*materials.facts_from_text(raw_text), *materials.facts_from_kr_text(raw_text)],
                    "TEXT",
                )
                timings["MATERIALS"] += (time.perf_counter() - ts) * 1000
            if "PZPARAMS" in want:
                ts = time.perf_counter()
                pz_facts = pzparams.extract(raw_text)
                if pz_facts:
                    from_pz(sink, pg, pz_facts, _token_text_source(src, pg))
                    stats["pz_facts"] += len(pz_facts)
                timings["PZPARAMS"] += (time.perf_counter() - ts) * 1000
            if "PPM" in want and ppmparams.HINT.search(raw_text):
                ts = time.perf_counter()
                ppm_facts = ppmparams.extract(raw_text)
                if ppm_facts:
                    ppmparams.from_ppm(sink, pg, ppm_facts, _token_text_source(src, pg))
                    stats["ppm_facts"] += len(ppm_facts)
                timings["PPM"] += (time.perf_counter() - ts) * 1000
            if tx_on and textparams.HINT.search(raw_text):
                ts = time.perf_counter()
                tx_facts = textparams.extract(raw_text, tx_flags)
                if tx_facts:
                    from_textparams(sink, pg, tx_facts, _token_text_source(src, pg))
                    stats["tx_facts"] += len(tx_facts)
                timings["TEXTPARAMS"] += (time.perf_counter() - ts) * 1000
            if energy_on and energy.HINT.search(raw_text):
                ts = time.perf_counter()
                from_energy(
                    sink,
                    pg,
                    energy.facts_from_text(raw_text, envelope=energy_envelope or is_id, thickness=not is_id),
                    "TEXT" if not is_id else "ID_DOC",
                )
                timings["ENERGY"] += (time.perf_counter() - ts) * 1000
            if mat_acts:
                ts = time.perf_counter()
                if materials.is_act_page(raw_text):
                    nxt = src.quick_text(pg + 1) if pg < n_pages else ""
                    act_pg = aosr.parse_act_text(raw_text + "\n" + nxt)
                    cells = act_pg.cells if act_pg is not None else {}
                    act_family = materials.act_family(raw_text + "\n" + nxt, cells.get("work_name"))
                    act_no = cells.get("act_no")
                    stats["material_acts"] += 1
                if act_family is not None and materials.ID_HINT.search(raw_text):
                    from_materials(
                        sink, pg, materials.facts_from_id_page(raw_text, act_family, act_no), "ID_DOC"
                    )
                timings["MATERIALS"] += (time.perf_counter() - ts) * 1000
            if is_id and "BINDER" in want:
                pk = binder.classify_page(page(pg), pg, True, raw_text)
                # a page that continues an open registry is the registry, whatever its rows say
                if (
                    open_registry is not None
                    and any(p.page_no == pg for p in open_registry.parts)
                    and pk.kind != "ID_REGISTRY"
                ):
                    pk = binder.PageKind(pg, "ID_REGISTRY", open_registry.caption or "", pk.source, 0.8)
                kinds.append(pk)
        except Exception as e:  # one bad page never kills the file: report (PAGE_UNREADABLE) and continue
            warnings.append("PAGE_UNREADABLE")
            stats["page_errors"] += 1
            _log_error(task.file_id, pg, e)
    if open_spec is not None:
        _emit_spec(open_spec, task, tables, counters, element_assertions, want)
    if open_registry is not None:
        registry.finalize(open_registry)
        counters["ID_REGISTRY"] += 1
        tables.append(artifacts.registry_table(open_registry, task.file_id, counters["ID_REGISTRY"]))
    if act_text:
        act = aosr.parse_act_text("\n".join(act_text))
        if act is not None:
            acts.append((1, act))
            tables.append(artifacts.aosr_table(acts, task.file_id, 1))
            from_aosr_refs(sink, 1, act)
    # values
    for t in tables:
        from_table(sink, t, tep_params.get(t["table_id"]), dev_evals.get(t["table_id"]))
    if air_rooms:
        element_assertions.extend(assertions.table_assertions(air_rooms, task.file_id))
        from_room_systems(sink, air_rooms, norm)
    if element_assertions:
        from_assertions(sink, element_assertions, norm)
    if kinds:
        from_binder(sink, kinds, binder.segments(kinds))
        stats.update({f"binder_{k.kind}": 1 for k in kinds})
    doc.close()
    total_ms = (time.perf_counter() - t0) * 1000
    timings["total"] = total_ms
    stats["tables"] = len(tables)
    for t in tables:
        stats[f"tables_{t['table_type']}"] += 1
        stats[f"rows_{t['table_type']}"] += len(t["rows"])
        for c in t.get("checks", []):
            stats[f"check_{c['kind']}_{'ok' if c['passed'] else 'fail'}"] += 1
    stats["assertions"] = len(element_assertions)
    stats["air_rooms"] = len(air_rooms)
    stats["values"] = len(sink.values)
    if stats["pages_unread"]:
        warnings.append("NO_TEXT_LAYER" if stats["pages_unread"] == n_pages else "OCR_PARTIAL")
    art = artifacts.table_artifacts(task.file_id, task.object_id, task.sha256, task.stage, tables, generated_at=_now(),
                                    warnings=warnings, timings_ms=dict(timings),
                                    ext={"pages": n_pages, "pages_read": stats["pages_read"], "pages_unread": stats["pages_unread"],
                                         "token_sources": {"runs": len(task.tokens.run_dirs), "cache": len(task.tokens.cache_dirs)}})  # fmt: skip
    return {
        "file_id": task.file_id,
        "object_id": task.object_id,
        "artifact": art,
        "values": sink.values,
        "stats": dict(stats),
    }


def _emit_spec(
    ls, task: FileTask, tables: list, counters: Counter, element_assertions: list, want: set
) -> None:
    from inspector_tables import artifacts, assertions

    if "SPEC_21110" in want:
        counters["SPEC_21110"] += 1
        tables.append(artifacts.spec_table(ls, task.file_id, counters["SPEC_21110"]))
    if task.stage == "PD" and "ASSERTIONS" in want:
        element_assertions.extend(assertions.spec_assertions(ls.items, task.file_id))


def _log_error(file_id: str, page: int, e: Exception) -> None:
    import logging

    logging.getLogger("inspector_tables").warning(
        "tables.page_failed", extra={"file_id": file_id, "page": page, "detail": repr(e)[:300]}
    )


# ── stage resolution ──────────────────────────────────────────────────────────────────────────────


def _inventory_stages(run_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    inv = run_dir / "inventory"
    if not inv.is_dir():
        return out
    for p in inv.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for f in doc.get("files", []) if isinstance(doc, dict) else []:
            if f.get("file_id") and f.get("stage_resolved"):
                out[f["file_id"]] = f["stage_resolved"]
    return out


def resolve_file_stage(manifest_stage: str, relative_path: str, path: Path) -> str | None:
    """PD/RD/ID from the manifest; RD_ID_MIXED/UNKNOWN resolved from folder, name and first-pages text
    (AG-01's rules, inspector_registry.stages) — never guessed."""
    if manifest_stage in ("PD", "RD", "ID"):
        return manifest_stage
    try:
        from inspector_registry.pdfprobe import probe_pdf
        from inspector_registry.stages import resolve_stage
    except ImportError:  # pragma: no cover - inspector-registry is part of the batch environment
        return None
    probe = probe_pdf(path)
    return resolve_stage(manifest_stage, relative_path, probe.stage_text).stage_resolved


# ── command ───────────────────────────────────────────────────────────────────────────────────────


def run_tables(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_common.contracts.loader import validate
    from inspector_common.runlayout import RunLayout
    from inspector_docproc.inputs import select_files

    t0 = time.perf_counter()
    paths = ctx.settings.paths
    types = tuple(t.upper() for t in args.table_types) or (*TABLE_TYPES, *EXTRA_KINDS)
    unknown = [t for t in types if t not in (*TABLE_TYPES, *EXTRA_KINDS)]
    if unknown:
        print(
            f"Неизвестный тип таблицы: {', '.join(unknown)}. Допустимо: {', '.join((*TABLE_TYPES, *EXTRA_KINDS))}"
        )
        return 2
    jobs, problems = select_files(paths, ctx.objects, args.files or None)
    layout = RunLayout(ctx.run_dir)
    inv_stages = _inventory_stages(ctx.run_dir)
    runs_root = ctx.settings.runs_root or ctx.run_dir.parent
    tokens_from = [Path(runs_root) / r for r in args.tokens_from]
    tasks = []
    for j in jobs:
        stage = inv_stages.get(j.file_id) or resolve_file_stage(j.stage, j.relative_path, j.path)
        plan = token_plan(
            ctx.run_dir, tokens_from, ctx.settings.cache_root, j.file_id, j.sha256, args.cache_tokens
        )
        tasks.append(FileTask(j.file_id, j.object_id, str(j.path), j.sha256, j.stage, j.relative_path, stage, plan, types,
                              args.pages))  # fmt: skip
    ctx.log.info("tables.start", extra={"files": len(tasks), "workers": args.workers, "types": list(types),
                                         "problems": len(problems)})  # fmt: skip
    results: list[dict] = []
    workers = max(1, int(args.workers))
    if workers == 1 or len(tasks) <= 1:
        results = [process_file(t) for t in tasks]
    else:
        # the heaviest files first so the pool does not end on one straggler
        order = sorted(tasks, key=lambda t: -os.path.getsize(t.path))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(process_file, order))
    values_by_object: dict[str, list[dict]] = {}
    totals: Counter[str] = Counter()
    invalid = 0
    for res in sorted(results, key=lambda r: r["file_id"]):
        art = res["artifact"]
        validate("table_artifacts", art)
        out = layout.ensure_parent("TABLES", file_id=res["file_id"])
        out.write_text(json.dumps(art, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        for v in res["values"]:
            try:
                validate("extracted_value", v)
            except Exception:
                invalid += 1
                continue
            values_by_object.setdefault(res["object_id"], []).append(v)
        totals.update({k: v for k, v in res["stats"].items() if isinstance(v, int)})
    from inspector_tables import ppmparams
    from inspector_tables.pzparams import resolve_ambiguity
    from inspector_tables.textparams import resolve_ambiguity as resolve_tx_ambiguity

    for obj in ctx.objects:
        vals = values_by_object.get(obj, [])
        pz_stats = resolve_ambiguity(vals)
        for k, n in pz_stats.items():
            totals[f"pz_{k}"] += n
        for k, n in ppmparams.resolve_ambiguity(vals).items():
            totals[f"ppm_{k}"] += n
        for k, n in resolve_tx_ambiguity(vals).items():
            totals[f"tx_{k}"] += n
        out = layout.ensure_parent("EXTRACTED_VALUES", object_id=obj)
        with out.open("w", encoding="utf-8") as fh:
            for v in vals:
                fh.write(json.dumps(v, ensure_ascii=False) + "\n")
    wall = time.perf_counter() - t0
    summary = {"files": len(tasks), "wall_s": round(wall, 2), "values_invalid": invalid, "problems": problems[:20],
               **{k: v for k, v in sorted(totals.items())}}  # fmt: skip
    ctx.log.info("tables.done", extra={"summary": summary})
    print(
        f"Таблицы: файлов {len(tasks)}, таблиц {totals['tables']} (экспликаций {totals['tables_EXPLICATION']}, "
        f"ТЭП {totals['tables_TEP']}, спецификаций {totals['tables_SPEC_21110']}, реестров {totals['tables_ID_REGISTRY']}, "
        f"АОСР {totals['tables_AOSR']}, изменений {totals['tables_CHANGE_LOG']}); утверждений ПД {totals['assertions']}; "
        f"значений {sum(len(v) for v in values_by_object.values())}; страниц без текста {totals['pages_unread']}; "
        f"время {wall:.1f} с. Результат: {layout.path('TABLES', file_id='X').parent}"
    )
    return 0


def _asdict(x: Any) -> Any:  # pragma: no cover - debugging helper
    return asdict(x)
