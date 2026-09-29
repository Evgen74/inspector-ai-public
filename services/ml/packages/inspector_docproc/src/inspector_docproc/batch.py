"""inspector-batch commands implemented by inspector_docproc — OWNED BY AG-02A (recognition lead).

    inspector-batch recognize --object OBJ… [--file F0001 …] [--pages 1-20] [--workers N] [--providers auto]
    inspector-batch bench --suite ocr|vector|scans|orientation [--providers auto|cpu|coreml|cuda] [--baseline]

Heavy imports happen inside ``run_*`` so that ``inspector-batch --help`` stays fast.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from typing import Any

from inspector_common.batch import BatchContext
from inspector_common.exitcodes import ExitCode

OWNER = "AG-02A"


def _exec_args(parser: argparse.ArgumentParser, default_threads: int) -> None:
    parser.add_argument(
        "--providers",
        choices=["auto", "cpu", "coreml", "cuda"],
        default="auto",
        help="Исполнитель ONNX: auto — сам выбирает самый быстрый: CoreML (macOS) → CUDA (видеокарта NVIDIA, "
        "проверяется реальной сессией) → CPU; cuda — принудительно GPU NVIDIA (по умолчанию auto)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=default_threads,
        help=f"Потоков ONNX на процесс (по умолчанию {default_threads})",
    )


def _load_config(path: str | None):
    from inspector_docproc.config import RecognitionConfig

    cfg = RecognitionConfig()
    if path:
        from pathlib import Path

        overrides = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = cfg.replace(**overrides)
    return cfg


def _report_fatal(exc: Exception) -> int:
    """Print a run-stopping error (models missing, workers cannot start) in Russian; returns the exit code."""
    from inspector_common.errors import InspectorError

    code = getattr(exc, "code", None)
    if not isinstance(exc, InspectorError) and code:
        with contextlib.suppress(KeyError, TypeError):
            exc = InspectorError(code, **getattr(exc, "details", {}))
    if isinstance(exc, InspectorError):
        print(f"{exc.title}: {exc.detail}" + (f" {exc.hint}" if exc.hint else ""), file=sys.stderr)
        missing = exc.code in ("OCR_MODEL_MISSING", "MODEL_ARTIFACT_INTEGRITY_FAILED")
        return int(ExitCode.DATA_MISSING if missing else ExitCode.ERROR)
    print(f"Распознавание остановлено: {exc}", file=sys.stderr)
    return int(ExitCode.ERROR)


# ── recognize ────────────────────────────────────────────────────────────────────────────────


def add_recognize_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--file", dest="files", action="append", default=[], metavar="FILE_ID",
        help="Ограничить обработку файлами (можно повторять)",
    )  # fmt: skip
    parser.add_argument(
        "--files",
        dest="files",
        action="extend",
        nargs="+",
        metavar="FILE_ID",
        help="Список файлов через пробел",
    )
    parser.add_argument("--pages", default=None, help="Диапазон страниц в каждом файле, например 1-20,25")
    parser.add_argument(
        "--workers", type=int, default=None, help="Число процессов (по умолчанию INSPECTOR_WORKERS или ЦП−2)"
    )
    _exec_args(parser, default_threads=1)
    parser.add_argument(
        "--no-cache", action="store_true", help="Не использовать кэш PageTokens (пересчитать)"
    )
    parser.add_argument(
        "--chunk-pages",
        type=int,
        default=None,
        help="Страниц в одном задании (по умолчанию авто: до 8, не меньше трёх заданий на процесс)",
    )
    parser.add_argument(
        "--allow-sleep",
        action="store_true",
        help="Не удерживать машину от сна на время прогона (по умолчанию сон блокируется: caffeinate на macOS, systemd-inhibit на Linux)",
    )
    parser.add_argument("--config", default=None, help="JSON с переопределениями конфигурации распознавания")
    parser.add_argument(
        "--strict-providers",
        action="store_true",
        help="Исполнитель ONNX строго как указан в --providers (cpu, coreml или cuda), без автоматической подмены; "
        "в замороженном прогоне (--hidden-run) включено всегда",
    )
    parser.add_argument(
        "--page-timeout",
        type=float,
        default=None,
        help="Предел времени на страницу, с (по умолчанию 900); более долгая страница — PROCESSING_TIMEOUT",
    )


def frozen_providers_problem(providers: str, *, strict: bool) -> str | None:
    """Why ``--providers`` cannot be used for a strict (frozen) run, in Russian; None when it can.

    The execution provider changes PageTokens (CoreML and CPU differ in the last float digits) and is part of
    the pipeline version, i.e. of the frozen configuration: ``auto`` may resolve differently on another
    machine or after a CoreML failure, so a frozen run names ``cpu``, ``coreml`` or ``cuda`` explicitly.
    """
    if strict and providers not in ("cpu", "coreml", "cuda"):
        return (
            f"Замороженный прогон: укажите исполнителя явно (--providers coreml, --providers cuda или --providers cpu), а не «{providers}»: "
            "«auto» выбирает исполнителя по машине, и результат распознавания может измениться."
        )
    return None


def run_recognize(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_common.errors import InspectorError
    from inspector_docproc.config import ExecutionConfig
    from inspector_docproc.inputs import object_code_extras, select_files
    from inspector_docproc.runner import WorkerInitError, run_recognition

    paths = ctx.settings.paths
    jobs, problems = select_files(paths, ctx.objects, args.files or None)
    for p in problems:
        ctx.log.warning("recognize.input_problem", extra=p)
    if not jobs:
        print("Нет PDF-файлов для распознавания по заданным условиям.", file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    # before any page is read: a frozen run never resolves «auto» (checked after input resolution so that a
    # missing input is still reported as DATA_MISSING)
    problem = frozen_providers_problem(args.providers, strict=ctx.hidden_run or args.strict_providers)
    if problem:
        print(problem, file=sys.stderr)
        return int(ExitCode.USAGE)
    workers = args.workers if args.workers is not None else ctx.settings.workers
    exec_cfg = ExecutionConfig(
        providers=args.providers,
        strict_providers=ctx.hidden_run or args.strict_providers,
        threads=max(1, args.threads),
        workers=max(0, workers or 0),
        keep_awake=not args.allow_sleep,
        **({"page_timeout_s": args.page_timeout} if args.page_timeout else {}),
    )
    cfg = _load_config(args.config)
    try:
        from inspector_docproc.models import describe_provider_decision, resolve_provider_mode

        chosen = resolve_provider_mode(exec_cfg.providers, exec_cfg.strict_providers)
        print(describe_provider_decision(exec_cfg.providers, chosen))
        result = run_recognition(
            jobs,
            pages_spec=args.pages,
            cfg=cfg,
            exec_cfg=exec_cfg,
            run_dir=ctx.run_dir,
            cache_root=paths.cache_root,
            code_extras=object_code_extras(paths, ctx.objects),
            use_cache=not args.no_cache,
            chunk_pages=max(1, args.chunk_pages) if args.chunk_pages else None,
        )
    except ValueError as exc:
        print(f"Ошибка аргументов: {exc}", file=sys.stderr)
        return int(ExitCode.USAGE)
    except (InspectorError, WorkerInitError) as exc:
        return _report_fatal(exc)
    s = result.summary
    ctx.log.info("recognize.done", extra={k: v for k, v in s.items() if k != "errors"})
    print(
        f"Распознано страниц: {s['pages_processed']} (из кэша: {s['pages_cached']}, ошибок: {s['pages_failed']}), "
        f"с OCR: {s['pages_with_ocr']}; время {s['wall_s']} с, {s['pages_per_min'] or 0} стр/мин "
        f"({s['workers']} проц., детектор: {s['provider_mode']}). Результат: {ctx.run_dir / 'tokens'}"
    )
    if s.get("suspended_s", 0) > 5:
        print(
            f"Внимание: компьютер спал {s['suspended_s']} с во время прогона "
            f"(время по часам {s['wall_clock_s']} с); скорость посчитана без учёта сна."
        )
    for fe in s.get("file_errors", []):
        print(f"Файл {fe['file_id']} не открыт: {fe['error']} ({fe['detail']})", file=sys.stderr)
    if s["pages_failed"]:
        codes = ", ".join(f"{k}: {v}" for k, v in (s.get("error_codes") or {}).items())
        print(f"Страницы с ошибками ({codes}) перечислены в tokens/index.jsonl.", file=sys.stderr)
    sup = s.get("supervision") or {}
    if sup.get("worker_restarts") or sup.get("server_restarts"):
        print(
            f"Перезапусков процессов обработки: {sup['worker_restarts']}, сервера детекции: "
            f"{sup['server_restarts']} (прогон продолжен).",
            file=sys.stderr,
        )
    return int(ExitCode.OK if not (s["pages_failed"] or s["file_errors"]) else ExitCode.ERROR)


# ── bench ────────────────────────────────────────────────────────────────────────────────────


def add_bench_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--suite",
        default="ocr",
        choices=["ocr", "vector", "scans", "orientation", "drawings"],
        help="Набор: ocr (все), vector (группа A), scans (группы B/D), orientation, drawings (чертежи, штампы, маршрутизация)",
    )
    parser.add_argument("--config", default=None, help="JSON с переопределениями конфигурации распознавания")
    parser.add_argument("--dpi", type=int, default=300, help="DPI рендера для группы A (по умолчанию 300)")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Дополнительно прогнать конфигурацию отчёта 96 (только v6-small, без второго детектора) для сравнения",
    )
    parser.add_argument("--bench-file", default=None, help="Путь к recognition_benchmark.json")
    _exec_args(parser, default_threads=4)


def _bench_once(suite: str, cfg, exec_cfg, bench: dict[str, Any], paths, dpi: int, log) -> dict[str, Any]:
    from inspector_docproc.bench.suites import (
        BenchContext,
        suite_drawings,
        suite_orientation,
        suite_scans,
        suite_scans_v2,
        suite_vector,
    )
    from inspector_docproc.inputs import object_code_extras
    from inspector_docproc.recognize import PageRecognizer

    objects = sorted({p["object_id"] for p in bench["pages"]})
    rec = PageRecognizer(cfg, exec_cfg, code_extras=object_code_extras(paths, objects))
    ctx = BenchContext(paths.documents_root, cfg, exec_cfg, rec.engine, rec)
    out: dict[str, Any] = {
        "pipeline_version": rec.pipeline_version(),
        "engine": rec.engine.versions(),
        "threads": exec_cfg.threads,
    }
    try:
        if suite in ("ocr", "vector"):
            out["vector"] = suite_vector(ctx, bench, dpi=dpi, log=log)
        if suite in ("ocr", "scans"):
            out["scans"] = suite_scans(ctx, bench, log=log)  # GT v1 (history, 6 pages)
            v2 = suite_scans_v2(ctx, bench, log=log)  # GT v2 (current, 14 pages)
            if v2 is not None:
                out["scans_v2"] = v2
        if suite in ("ocr", "orientation"):
            out["orientation"] = suite_orientation(ctx, bench, log=log)
        if suite in ("ocr", "drawings"):
            out["drawings"] = suite_drawings(ctx, bench, paths.train_checks_path, log=log)
    finally:
        rec.close()  # release the ONNX Runtime sessions before the report is written
    return out


def _print_bench(title: str, r: dict[str, Any]) -> None:
    print(f"\n== {title} | {r['pipeline_version']} | детектор/распознаватель: {r['engine'].get('provider')}")
    if "vector" in r:
        v = r["vector"]
        s = v["ca"]["strict"]
        print(
            f"Группа A (векторные, {v['dpi']} dpi): CA строгая {s['ca']:.3f} [{s['ci_low']:.3f}–{s['ci_high']:.3f}], "
            f"мягкая {v['ca']['relaxed']['ca']:.3f}, без регистра {v['ca']['relaxed_ci']['ca']:.3f}; "
            f"{s['n_units']} обл., {s['n_chars']} симв.; {v['cpu_s_per_mp']} CPU-с/Мп, {v['wall_s_per_region']} с/обл."
        )
        kf = v["key_fields"]
        print(
            f"  Шифры (n={kf['CODE']['n']}): EM сырой {kf['CODE']['em_raw']:.3f}, после корректора "
            f"{kf['CODE']['em_corrected']:.3f}; номера помещений/чисел (n={kf['ROOM_OR_NUM']['n']}): "
            f"EM {kf['ROOM_OR_NUM']['em_corrected']:.3f}"
        )
    if "scans" in r:
        sc = r["scans"]
        s = sc["ca_raw"]["strict"]
        print(
            f"Сканы и текст в кривых (рукописная разметка): CA строгая {s['ca']:.3f} [{s['ci_low']:.3f}–{s['ci_high']:.3f}], "
            f"мягкая {sc['ca_raw']['relaxed']['ca']:.3f}, без регистра {sc['ca_raw']['relaxed_ci']['ca']:.3f}; "
            f"{s['n_units']} стр., {s['n_chars']} симв.; после корректора {sc['ca_corrected']['strict']['ca']:.3f}"
        )
        kf = sc["key_fields"]
        print(
            f"  Ключевые поля (n={kf['n']}): EM строгий {kf['em_strict']:.3f}, мягкий {kf['em_relaxed']:.3f}; "
            f"{sc['wall_s_per_page']} с/стр, {sc['cpu_s_per_page']} CPU-с/стр"
        )
        for p in sc["pages"]:
            print(
                f"    {p['id']}: {p['ca_raw']['strict']:.3f} ({p['page_class']}, {p['render_dpi']} dpi, "
                f"поворот {p['content_rotation']}, резерв {p['fallback_used']}, {p['wall_s']} с)"
            )
    if "scans_v2" in r:
        v2 = r["scans_v2"]
        c, s = v2["ca_corrected"]["strict"], v2["ca_raw"]["strict"]
        print(
            f"Разметка v2 ({v2['gt']['pages']} стр., две независимые расшифровки + арбитраж), выход конвейера: "
            f"CA строгая {c['ca']:.3f} [{c['ci_low']:.3f}–{c['ci_high']:.3f}], мягкая "
            f"{v2['ca_corrected']['relaxed']['ca']:.3f}, без регистра {v2['ca_corrected']['relaxed_ci']['ca']:.3f}; "
            f"{c['n_chars']} симв., вставки {c['ins_rate']:.3f}; до постобработки {s['ca']:.3f} "
            f"[{s['ci_low']:.3f}–{s['ci_high']:.3f}]"
        )
        sub = {
            k: v2.get(f"ca_corrected_{k}", v2[f"ca_raw_{k}"])["strict"]
            for k in ("scans", "outlined", "v1_pages")
        }
        print(
            f"  сканы {sub['scans']['ca']:.3f} ({sub['scans']['n_chars']} симв.), текст в кривых "
            f"{sub['outlined']['ca']:.3f} ({sub['outlined']['n_chars']} симв.); те же 6 страниц, что в v1: "
            f"{sub['v1_pages']['ca']:.3f} ({sub['v1_pages']['n_chars']} симв.)"
        )
        kf = v2["key_fields"]
        print(
            f"  Ключевые поля v2 (n={kf['n']}): EM строгий {kf['em_strict']:.3f}, мягкий {kf['em_relaxed']:.3f}"
        )
        z = v2["zones"]
        print(
            "  Зоны (попадание IoU ≥ 0,3 / покрыто / ложные): "
            + "; ".join(
                f"{f} {c.get('hit', 0)}/{c.get('n_gt', 0)} / {c.get('covered', 0)} / {c.get('false_alarm', 0)}"
                for f, c in z.items()
            )
        )
        for p in v2["pages"]:
            print(
                f"    {p['id']}: {p['ca_corrected']['strict']:.3f} (до постобработки {p['ca_raw']['strict']:.3f}; "
                f"N={p['n_gt']}, вставки {p['ins_rate']:.3f}, {p['page_class']}, {p['wall_s']} с)"
            )
    if "drawings" in r:
        d = r["drawings"]
        g, tb, rt = d["text_gaps"], d["title_block"], d["routes"]
        print(
            f"Чертежи РД (эталон): найдено {g['captured']}/{g['gap_lines']} строк в пропусках текстового слоя "
            f"({g['recall']:.3f}); помещения эталона {d['gold_rooms']['found']}/{d['gold_rooms']['n']}"
        )
        for p in d["pages"]:
            if "text_gaps" in p:
                rooms = ", ".join(f"{k}{'' if v else ' (нет)'}" for k, v in p["gold_rooms"].items())
                print(
                    f"    {p['id']}: {p['text_gaps']['recall']:.3f} строк; помещения: {rooms}; {p['wall_s']} с"
                )
        print(
            f"  Штампы (n={tb['n']}): EM строгий {tb['em_strict']:.3f}, мягкий {tb['em_relaxed']:.3f}"
            + (f"; промахи: {', '.join(tb['misses_strict'])}" if tb["misses_strict"] else "")
        )
        bad = [f"{c['id']}: {c['got']} вместо {c['expected']}" for c in rt["cases"] if not c["ok"]]
        print(f"  Маршрутизация: {rt['ok']}/{rt['n']}" + (f"; ошибки: {'; '.join(bad)}" if bad else ""))
    if "orientation" in r:
        o = r["orientation"]
        print(
            f"Ориентация: {o['accuracy']:.3f} ({o['n']} случаев, из них исходных {o['natural_n']}: "
            f"{o['natural_accuracy']:.3f}); мин. отрыв {o.get('min_margin')}, методы {o.get('methods')}; "
            f"{o['seconds_per_case']} с/случай"
        )


def run_bench(args: argparse.Namespace, ctx: BatchContext) -> int:
    import pymupdf

    from inspector_docproc.bench.suites import load_benchmark
    from inspector_docproc.config import ExecutionConfig

    pymupdf.TOOLS.mupdf_display_errors(False)
    from pathlib import Path

    bench = load_benchmark(Path(args.bench_file) if args.bench_file else None)
    paths = ctx.settings.paths
    if not paths.documents_root.is_dir():
        print("Каталог документов не найден (INSPECTOR_DATA_ROOT).", file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    exec_cfg = ExecutionConfig(providers=args.providers, threads=max(1, args.threads))
    cfg = _load_config(args.config)
    from inspector_docproc.models import describe_provider_decision, resolve_provider_mode

    print(describe_provider_decision(args.providers, resolve_provider_mode(args.providers)))

    def log(msg: str) -> None:
        ctx.log.info("bench.step", extra={"step": msg})

    from inspector_docproc.runner import keep_awake

    report: dict[str, Any] = {"suite": args.suite, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    t0 = time.perf_counter()
    with keep_awake():
        report["production"] = _bench_once(args.suite, cfg, exec_cfg, bench, paths, args.dpi, log)
        if args.baseline:
            base = cfg.replace(ocr={"medium_mode": "off"})
            report["baseline_96"] = _bench_once(args.suite, base, exec_cfg, bench, paths, args.dpi, log)
    report["wall_s"] = round(time.perf_counter() - t0, 1)
    out = ctx.run_dir / f"bench_{args.suite}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _print_bench("Рабочая конфигурация", report["production"])
    if "baseline_96" in report:
        _print_bench("Конфигурация отчёта 96 (только v6-small)", report["baseline_96"])
    print(f"\nОтчёт: {out} ({report['wall_s']} с)")
    return int(ExitCode.OK)
