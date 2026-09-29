"""inspector-batch command `layout` — owned by AG-02B.

Input: the object's PDFs from the manifest (and, when present, the PageTokens of a recognition run, AG-02A).
Output: one LayoutArtifacts file per PDF at ``RunLayout(ctx.run_dir).path("LAYOUT", file_id=…)``
(packages/contracts/schemas/layout_artifacts.schema.json): title blocks with Изм. rows, the sheet ↔ page map,
QR links (this module and :mod:`inspector_layout.pipeline`), plus rooms, tags, CAD layers and revision clouds
when the room/CAD provider is present. The CLI rebuilds artifacts.json afterwards.

    inspector-batch --run-id m1-layout layout --object OBJ-TYUMENSKAYA-5-GOLD-SEED
    inspector-batch layout --object OBJ-TYUMENSKAYA-5-GOLD-SEED --file F0201 --pages 14-48 --workers 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from inspector_common.batch import BatchContext

OWNER = "AG-02B"


def add_layout_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--file", dest="files", action="append", default=[], metavar="FILE_ID",
        help="Ограничить обработку файлами (можно повторять)",
    )  # fmt: skip
    parser.add_argument(
        "--pages",
        default=None,
        metavar="СПИСОК",
        help="Страницы каждого файла, например «14-48,120» (по умолчанию все)",
    )
    parser.add_argument(
        "--tokens-run",
        default=None,
        metavar="RUN_ID",
        help="Прогон с результатами распознавания (по умолчанию текущий прогон, если в нём есть tokens/)",
    )
    parser.add_argument(
        "--workers", type=int, default=3, help="Число процессов (по умолчанию 3: общий 12-ядерный хост)"
    )
    parser.add_argument(
        "--threads", type=int, default=2, help="Потоков ONNX Runtime на процесс (по умолчанию 2)"
    )
    parser.add_argument(
        "--providers",
        default="cpu",
        choices=("cpu", "coreml", "auto"),
        help="Исполнитель OCR штампов (по умолчанию cpu: без CoreML в нескольких процессах)",
    )
    parser.add_argument(
        "--ocr-dpi", type=int, default=300, help="Разрешение OCR штампа (по умолчанию 300 dpi)"
    )
    parser.add_argument("--no-ocr", action="store_true", help="Только текстовый слой, без OCR штампов")
    parser.add_argument("--ocr-scans", action="store_true", help="Распознавать штампы и на сканах")
    parser.add_argument("--no-qr-render", action="store_true", help="QR только из встроенных изображений")
    parser.add_argument(
        "--no-sections",
        action="store_true",
        help="Без помещений, марок, слоёв САПР и облаков изменений (только штампы, QR и карта листов)",
    )
    parser.add_argument(
        "--inventory-run",
        default=None,
        metavar="RUN_ID",
        help="Прогон инвентаризации со стадиями файлов RD_ID_MIXED (по умолчанию текущий прогон, если есть)",
    )


def run_layout(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_common.exitcodes import ExitCode
    from inspector_docproc.inputs import load_manifest, parse_pages, select_files
    from inspector_layout import __version__
    from inspector_layout.codes import CodeRegistry
    from inspector_layout.pagescan import ScanOptions
    from inspector_layout.pipeline import (
        FileTask,
        assemble_object,
        merge_sections,
        run_section_provider,
        scan_files,
        write_layout,
    )

    paths = ctx.settings.paths
    log = ctx.log
    jobs, problems = select_files(paths, ctx.objects, args.files or None)
    for p in problems:
        log.warning("layout.input.problem", extra={k: str(v) for k, v in p.items()})
    if not jobs:
        print("Нет PDF-файлов для разметки по заданным условиям.", file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    rows = load_manifest(paths)
    registries = {oid: CodeRegistry.from_manifest_rows(rows, oid) for oid in ctx.objects}
    tokens_dir = None
    if args.tokens_run:
        tokens_dir = str(paths.runs_root / args.tokens_run / "tokens")
    elif (ctx.run_dir / "tokens").is_dir():
        tokens_dir = str(ctx.run_dir / "tokens")
    opts = ScanOptions(
        ocr=not args.no_ocr,
        ocr_dpi=args.ocr_dpi,
        ocr_scans=args.ocr_scans,
        providers=args.providers,
        threads=max(1, args.threads),
        qr=True,
        qr_render=not args.no_qr_render,
        tokens_dir=tokens_dir,
    )
    tasks = []
    stages_by_object: dict[str, dict[str, str]] = {}
    for j in jobs:
        n = j.pdf_pages or _count_pages(j.path)
        try:
            pages = parse_pages(args.pages, n)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return int(ExitCode.USAGE)
        resolved = stages_by_object.setdefault(
            j.object_id, _resolved_stages(ctx, j.object_id, args.inventory_run)
        )
        tasks.append(
            FileTask(
                j.file_id, j.object_id, str(j.path), j.sha256, j.stage, tuple(pages), resolved.get(j.file_id)
            )
        )
    t0 = time.perf_counter()
    n_pages = sum(len(t.pages) for t in tasks)
    print(f"Разметка: {len(tasks)} файлов, {n_pages} страниц, процессов {args.workers}", flush=True)

    def progress(fid: str, i: int, n: int) -> None:
        if i == n or i % max(1, n // 10) == 0:
            print(f"  {i}/{n} частей ({fid})", flush=True)

    results = scan_files(tasks, registries, opts, workers=max(1, args.workers), progress=progress)
    pipeline_version = f"layout-{__version__}"
    written = 0
    failures = 0
    summary: dict[str, dict] = {}
    for oid in ctx.objects:
        stages = stages_by_object.get(oid) or _resolved_stages(ctx, oid, args.inventory_run)
        docs = assemble_object(oid, results, pipeline_version=pipeline_version, resolved_stages=stages)
        for fid, doc in docs.items():
            try:
                t_sec = time.perf_counter()
                sections = (
                    None
                    if args.no_sections
                    else run_section_provider(results[fid].task, doc, tokens_dir=tokens_dir)
                )
                if sections:
                    merge_sections(doc, sections)
                    doc["timings_ms"].setdefault(
                        "sections_ms", round((time.perf_counter() - t_sec) * 1000, 1)
                    )
            except Exception as exc:  # the other half must never cost us the title blocks
                log.warning(
                    "layout.sections.failed", extra={"file_id": fid, "detail": f"{type(exc).__name__}: {exc}"}
                )
            try:
                write_layout(ctx.run_dir, doc)
                written += 1
            except Exception as exc:
                failures += 1
                log.error(
                    "layout.write.failed",
                    extra={"file_id": fid, "detail": f"{type(exc).__name__}: {exc}"[:500]},
                )
                print(f"Ошибка записи разметки {fid}: {exc}", file=sys.stderr)
                continue
            tb = doc["ext"]["title_block"]
            summary[fid] = {
                "pages": doc["pages_total"],
                "scanned": tb["pages_scanned"],
                "title_blocks": tb["found"],
                "ocr_pages": tb["ocr_pages"],
                "sheet_map": len(doc["sheet_page_map"]),
                "qr_links": len(doc["qr_links"]),
                "rooms": len(doc["rooms"]),
                "warnings": doc["warnings"],
            }
    wall = time.perf_counter() - t0
    # Run-level summary next to run_context (not a contract artifact kind: the index leaves it out).
    (ctx.run_dir / "layout_summary.json").write_text(
        json.dumps(
            {"wall_s": round(wall, 2), "pages": n_pages, "files": summary}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    tbs = sum(s["title_blocks"] for s in summary.values())
    ocr = sum(s["ocr_pages"] for s in summary.values())
    qrs = sum(s["qr_links"] for s in summary.values())
    print(
        f"Готово: {written} файлов разметки, штампов {tbs} (OCR {ocr}), QR {qrs}, {wall:.1f} с",
        flush=True,
    )
    log.info(
        "layout.done",
        extra={"files": written, "title_blocks": tbs, "ocr_pages": ocr, "wall_s": round(wall, 2)},
    )
    if failures:
        return int(ExitCode.SCHEMA_INVALID)
    return int(ExitCode.OK)


def _resolved_stages(ctx: BatchContext, object_id: str, inventory_run: str | None) -> dict[str, str]:
    """Per-file DocStage resolved by AG-01 (inventory artifact), for RD_ID_MIXED/UNKNOWN manifest rows."""
    from inspector_common.runlayout import RunLayout

    run_dir = ctx.settings.paths.runs_root / inventory_run if inventory_run else ctx.run_dir
    path = RunLayout(run_dir).path("INVENTORY", object_id=object_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for f in doc.get("files") or []:
        st = f.get("stage_resolved") or (f.get("stage") or {}).get("stage_resolved")
        if f.get("file_id") and st in ("PD", "RD", "ID"):
            out[str(f["file_id"])] = str(st)
    return out


def _count_pages(path) -> int:
    import pymupdf

    with pymupdf.open(path) as doc:
        return len(doc)
