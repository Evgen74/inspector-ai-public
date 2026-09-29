"""inspector-batch commands implemented by inspector_compare — OWNED BY AG-04.

    inspector-batch compare --object OBJ-… [--fixture tyumen] [--layout-dir DIR] [--config FILE]
    inspector-batch export  --object OBJ-… [--emit-negatives all|none] [--no-protocol] [--no-thumbnails]
                            [--protocol-formats json,docx,pdf] [--pdf-engine auto|chromium|pymupdf|none]

``compare`` reads the layout/table/value artifacts of the run (run_layout.yaml paths; ``--fixture`` or the
``--*-dir`` options point elsewhere) and writes ``findings/<object_id>.groups.jsonl`` and
``findings/<object_id>.jsonl``. ``export`` reads them and writes the submission (full, strict, sidecar), gated by the
contract schemas and inspector-score's integrity rules, and the Приложение 2 protocol (JSON, DOCX, PDF).

Hidden object (97 §2.17): runs only with the CLI's ``--hidden-run``; fixtures are refused; per-object results are not
printed (only that the files were written).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from inspector_common.batch import BatchContext
from inspector_common.exitcodes import ExitCode

OWNER = "AG-04"


# ── compare ───────────────────────────────────────────────────────────────────────────────────


def add_compare_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default=None,
        help="Замороженная конфигурация сравнения (JSON/YAML: пороги, семейства, страховка кода)",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Отладочная разметка из пакета inspector_compare вместо артефактов прогона (например, tyumen)",
    )
    parser.add_argument(
        "--layout-dir",
        type=Path,
        default=None,
        help="Каталог layout/<file_id>.json (по умолчанию из прогона)",
    )
    parser.add_argument(
        "--tables-dir",
        type=Path,
        default=None,
        help="Каталог tables/<file_id>.json (по умолчанию из прогона)",
    )
    parser.add_argument(
        "--values", type=Path, default=None, help="Файл values/<object_id>.jsonl (по умолчанию из прогона)"
    )
    parser.add_argument(
        "--no-free-hook", action="store_true", help="Не вызывать свободный поиск AG-07 (inspector_hypothesis)"
    )


def _objects_or_error(ctx: BatchContext) -> tuple[str, ...]:
    return tuple(ctx.objects)


def _print(msg: str) -> None:
    print(msg, flush=True)


def run_compare(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_common.errors import InspectorError
    from inspector_common.runlayout import RunLayout
    from inspector_compare.artifacts import RunArtifacts
    from inspector_compare.config import ConfigError, load_config
    from inspector_compare.engine import compare_object
    from inspector_compare.fixtures import get_fixture
    from inspector_compare.objectctx import InputDirs, context_from_registry
    from inspector_compare.params_hashes import seed_hashes
    from inspector_registry.manifest import Registry

    try:
        cfg = load_config(getattr(args, "config", None))
    except (ConfigError, OSError, ValueError) as exc:
        print(f"Ошибка конфигурации сравнения: {exc}", file=sys.stderr)
        return int(ExitCode.USAGE)
    if getattr(args, "no_free_hook", False):
        import dataclasses

        cfg = dataclasses.replace(cfg, free_hook=False)
    description = cfg.describe(seed_hashes())
    try:
        registry = Registry.load(ctx.settings.paths)
    except InspectorError as exc:
        print(f"{exc.title}: {exc.detail}", file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    layout = RunLayout(ctx.run_dir)
    out = RunArtifacts(ctx.run_dir)
    fixture = get_fixture(args.fixture) if getattr(args, "fixture", None) else None
    worst = int(ExitCode.OK)
    for object_id in ctx.objects:
        hidden = registry.policy.is_hidden(object_id)
        if fixture is not None and (hidden or fixture.object_id != object_id):
            if hidden:
                print("Отладочная разметка не применяется к скрытой выборке.", file=sys.stderr)
                return int(ExitCode.USAGE)
            layout_dir, tables_dir, source = None, None, None
        elif fixture is not None:
            layout_dir, tables_dir, source = fixture.layout_dir, fixture.tables_dir, f"fixture:{fixture.name}"
        else:
            layout_dir = getattr(args, "layout_dir", None) or layout.path("LAYOUT", file_id="X").parent
            tables_dir = getattr(args, "tables_dir", None) or layout.path("TABLES", file_id="X").parent
            source = f"run:{ctx.run_id}" if getattr(args, "layout_dir", None) is None else f"dir:{layout_dir}"
        values = getattr(args, "values", None) or layout.path("EXTRACTED_VALUES", object_id=object_id)
        t0 = time.perf_counter()
        octx = context_from_registry(
            object_id, registry, InputDirs(layout_dir, tables_dir, values, ctx.run_dir, source)
        )
        result = compare_object(octx, cfg, run_id=ctx.run_id, config_hash=description["config_hash"])
        g_path, f_path = out.write_findings(object_id, result.groups, result.findings)
        elapsed = time.perf_counter() - t0
        stats = {
            "groups": len(result.groups),
            "violations": len(result.violation_findings),
            "rows": len(result.findings),
            "hedges": result.trace["hedges"],
            "free_groups": result.trace["free_groups"],
            "layout_files": len(octx.layouts),
            "seconds": round(elapsed, 3),
        }
        ctx.log.info(
            "compare.object_done",
            extra={
                "object_id": object_id,
                "config_hash": description["config_hash"],
                **({} if hidden else stats),
            },
        )
        if hidden:
            _print(
                f"Сравнение по объекту скрытой выборки выполнено; результаты записаны в {f_path.parent} и не выводятся (97 §2.17)."
            )
            continue
        _print(
            f"{object_id}: групп нарушений {stats['groups']}, атомарных нарушений {stats['violations']}, "
            f"строк всего {stats['rows']} (разметка: {len(octx.layouts)} файл., источник {source or '—'}; "
            f"{elapsed:.2f} с). Записано: {g_path.relative_to(ctx.run_dir)}, {f_path.relative_to(ctx.run_dir)}"
        )
        if not octx.layouts:
            _print(
                f"  Внимание: для {object_id} нет артефактов разметки (layout) — выданы только строки по 132 параметрам."
            )
    return worst


# ── export ────────────────────────────────────────────────────────────────────────────────────


def compare_inputs(groups: list[dict[str, Any]], run_dir: Path, object_id: str | None = None) -> Any:
    """The layout/table directories compare read, from ``decision_trace.inputs`` of its groups («fixture:<name>»,
    «run:<run_id>», «dir:<path>»); the run's own directories otherwise. The run's extracted values are read too:
    the value-conflict suspicions of the protocol (AG-07) are computed from them."""
    from inspector_common.runlayout import RunLayout
    from inspector_compare.fixtures import get_fixture
    from inspector_compare.objectctx import InputDirs

    layout = RunLayout(run_dir)
    layout_dir = layout.path("LAYOUT", file_id="X").parent
    tables_dir = layout.path("TABLES", file_id="X").parent
    values = layout.path("EXTRACTED_VALUES", object_id=object_id) if object_id else None
    source = next(
        (
            str(g["decision_trace"]["inputs"])
            for g in groups
            if isinstance(g.get("decision_trace"), dict) and g["decision_trace"].get("inputs")
        ),
        None,
    )
    if source and source.startswith("fixture:"):
        try:
            fx = get_fixture(source.split(":", 1)[1])
            return InputDirs(fx.layout_dir, fx.tables_dir, None, run_dir, source)
        except KeyError:
            pass
    elif source and source.startswith("dir:"):
        return InputDirs(Path(source.split(":", 1)[1]), tables_dir, values, run_dir, source)
    return InputDirs(layout_dir, tables_dir, values, run_dir, source or f"run:{run_dir.name}")


def add_export_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--emit-negatives",
        choices=["all", "none"],
        default="all",
        help="Выгружать строки по всем 132 параметрам (93 §2.5)",
    )
    parser.add_argument("--no-protocol", action="store_true", help="Не формировать протокол по Приложению 2")
    parser.add_argument(
        "--no-thumbnails",
        action="store_true",
        help="Не встраивать в карточки доказательств фрагменты страниц с рамками (DOCX/PDF)",
    )
    parser.add_argument(
        "--protocol-formats",
        default="json,docx,pdf",
        help="Форматы протокола через запятую: json, docx, pdf (по умолчанию все)",
    )
    parser.add_argument(
        "--pdf-engine",
        choices=["auto", "chromium", "pymupdf", "none"],
        default="auto",
        help="Движок PDF: auto (Chromium при наличии, иначе PyMuPDF), chromium, pymupdf, none",
    )
    parser.add_argument(
        "--freeze-tag",
        default=None,
        help="git-тег замороженной конфигурации (единственный прогон по скрытой выборке)",
    )


def run_export(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_common.errors import InspectorError
    from inspector_common.params import load_params
    from inspector_compare.artifacts import RunArtifacts, write_json
    from inspector_compare.config import ExportConfig
    from inspector_compare.export.sidecar import build_sidecar, utc_now
    from inspector_compare.export.submission import (
        build_submission,
        integrity_problems,
        local_problems,
        schema_problems,
    )
    from inspector_compare.objectctx import context_from_registry
    from inspector_registry.manifest import Registry

    formats = tuple(
        f.strip() for f in str(getattr(args, "protocol_formats", "json,docx,pdf")).split(",") if f.strip()
    )
    bad = sorted(set(formats) - {"json", "docx", "pdf"})
    if bad:
        print(f"Неизвестные форматы протокола: {', '.join(bad)}", file=sys.stderr)
        return int(ExitCode.USAGE)
    ecfg = ExportConfig(
        emit_negatives=getattr(args, "emit_negatives", "all"),
        protocol=not getattr(args, "no_protocol", False),
        protocol_formats=formats,
        pdf_engine=getattr(args, "pdf_engine", "auto"),
        thumbnails=not getattr(args, "no_thumbnails", False),
        freeze_tag=getattr(args, "freeze_tag", None),
    )
    try:
        registry = Registry.load(ctx.settings.paths)
    except InspectorError as exc:
        print(f"{exc.title}: {exc.detail}", file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    params = load_params()
    arts = RunArtifacts(ctx.run_dir)
    worst = int(ExitCode.OK)
    for object_id in ctx.objects:
        started = utc_now()
        t0 = time.perf_counter()
        hidden = registry.policy.is_hidden(object_id)
        if not arts.has_findings(object_id):
            print(
                f"Нет результатов сравнения для {object_id}: сначала выполните «inspector-batch --run-id {ctx.run_id} compare»"
                f" (ожидается {arts.relative('FINDINGS', object_id=object_id)}).",
                file=sys.stderr,
            )
            worst = max(worst, int(ExitCode.DATA_MISSING))
            continue
        groups, findings = arts.read_findings(object_id)
        # The same layout/table inputs as compare (stage resolution, title-block marks, protocol passport).
        octx = context_from_registry(object_id, registry, compare_inputs(groups, ctx.run_dir, object_id))
        sub = build_submission(object_id, findings, emit_negatives=ecfg.emit_negatives)
        problems = schema_problems(sub)
        problems += local_problems(
            sub, [p.code for p in params], expect_all_params=ecfg.emit_negatives == "all"
        )
        integrity, integrity_report = integrity_problems(sub, ctx.settings, octx.split)
        problems += integrity
        if problems:
            err = InspectorError(
                "SUBMISSION_SCHEMA_INVALID",
                object_id=object_id,
                schema="submission.*",
                reason="; ".join(problems[:3]),
            )
            print(f"{err.title}: {err.detail}", file=sys.stderr)
            for p in problems[:20]:
                print(f"  - {p}", file=sys.stderr)
            ctx.log.error("export.rejected", extra={"object_id": object_id, "problems": problems[:20]})
            worst = max(worst, int(ExitCode.SCHEMA_INVALID))
            continue
        t_sub = time.perf_counter() - t0
        written: dict[str, str] = {}
        write_json(arts.path("SUBMISSION", object_id=object_id), sub.extended, "submission.extended")
        write_json(arts.path("SUBMISSION_STRICT", object_id=object_id), sub.strict, "submission.strict")
        written["submission"] = arts.relative("SUBMISSION", object_id=object_id)
        written["submission_strict"] = arts.relative("SUBMISSION_STRICT", object_id=object_id)
        written["sidecar"] = arts.relative("SUBMISSION_SIDECAR", object_id=object_id)
        written["findings"] = arts.relative("FINDINGS", object_id=object_id)
        written["finding_groups"] = arts.relative("FINDING_GROUPS", object_id=object_id)
        timings = {"export.submission": t_sub}
        warnings: list[str] = []
        protocol_note = ""
        if ecfg.protocol:
            from inspector_compare.protocol.export import export_protocol

            t1 = time.perf_counter()
            result = export_protocol(
                octx,
                groups,
                findings,
                sub.extended,
                arts,
                run_id=ctx.run_id,
                formats=ecfg.protocol_formats,
                pdf_engine=ecfg.pdf_engine,
                settings=ctx.settings,
                thumbnails=ecfg.thumbnails,
            )
            timings["export.protocol"] = time.perf_counter() - t1
            timings.update({f"export.{k}": v for k, v in result.timings.items()})
            written.update(result.written)
            warnings.extend(result.warnings)
            protocol_note = "; протокол: " + ", ".join(sorted(result.written)) if result.written else ""
            for w in result.messages:
                print(f"  {w}", file=sys.stderr)
        compare_hashes = {
            (f.get("decision_trace") or {}).get("compare_config_hash")
            for f in findings
            if f.get("decision_trace")
        } - {None}
        sidecar = build_sidecar(
            ctx=octx,
            run_id=ctx.run_id,
            run_dir=ctx.run_dir,
            settings=ctx.settings,
            compare_config_hash=sorted(compare_hashes)[0] if len(compare_hashes) == 1 else None,
            export_config_hash=ecfg.config_hash(),
            artifacts=written,
            checks_total=len(sub.strict["checks"]),
            started_at=started,
            timings={**timings, "export": time.perf_counter() - t0},
            freeze_tag=ecfg.freeze_tag,
            warnings=warnings,
            matrix_version=params.matrix_version,
        )
        write_json(arts.path("SUBMISSION_SIDECAR", object_id=object_id), sidecar, "submission_sidecar")
        _update_run_manifest(ctx.run_dir, object_id, written)
        ctx.log.info(
            "export.object_done",
            extra={
                "object_id": object_id,
                **(
                    {}
                    if hidden
                    else {"checks": sub.stats, "integrity": (integrity_report or {}).get("share")}
                ),
            },
        )
        if hidden:
            _print(
                "Выгрузка по объекту скрытой выборки выполнена; ответ, sidecar и протокол записаны и не выводятся (97 §2.17)."
            )
            continue
        by_label = ", ".join(f"{k} {v}" for k, v in sub.stats["by_label"].items())
        _print(
            f"{object_id}: строк {sub.stats['checks']} ({by_label}); схемы и правила целостности R1–R14 пройдены. "
            f"Записано: {written['submission']}, {written['submission_strict']}, {written['sidecar']}{protocol_note}"
        )
    return worst


def _update_run_manifest(run_dir: Path, object_id: str, artifacts: dict[str, str]) -> None:
    """Point run_manifest.json objects[].artifacts at this object's files when an inventory manifest exists."""
    import json

    from inspector_common.contracts.loader import validation_errors
    from inspector_compare.artifacts import write_json

    path = run_dir / "run_manifest.json"
    try:
        doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    changed = False
    allowed = {
        "submission",
        "submission_strict",
        "sidecar",
        "findings",
        "finding_groups",
        "protocol_json",
        "protocol_docx",
        "protocol_pdf",
    }
    for obj in doc.get("objects", []):
        if obj.get("object_id") == object_id:
            obj.setdefault("artifacts", {}).update({k: v for k, v in artifacts.items() if k in allowed})
            changed = True
    if changed and not validation_errors("run_manifest", doc):
        write_json(path, doc, "run_manifest")
