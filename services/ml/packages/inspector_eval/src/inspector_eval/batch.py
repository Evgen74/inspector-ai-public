"""inspector-batch commands implemented by inspector_eval — OWNED BY AG-10.

`inspector-batch score` scores the submissions of the selected TRAIN objects against the organizer gold
(or ``--gold``) with inspector-score, writes ``runs/<run_id>/score/`` (score.json, per_check.csv,
gate.csv, summary.txt) and prints the Russian summary. ``--selftest`` runs the T-GOLD fixture cases.

The CLI refuses `score` on TEST_HIDDEN objects before this module is called (93 §4.9); this module keeps
an independent refusal: the frozen hidden-final path exists only in the standalone `inspector-score`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspector_common.batch import BatchContext
from inspector_common.errors import InspectorError
from inspector_common.exitcodes import ExitCode
from inspector_eval.args import add_variant_arguments, config_from_args

OWNER = "AG-10"


def add_score_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pred",
        type=Path,
        default=None,
        help="Файл или каталог ответа (по умолчанию submission/ последнего прогона с ответом по объекту)",
    )
    parser.add_argument(
        "--gold", type=Path, default=None, help="Эталон (по умолчанию public_train_checks.jsonl)"
    )
    parser.add_argument(
        "--superseded", type=Path, default=None, help="JSON со списком устаревших file_id (R9)"
    )
    parser.add_argument(
        "--selftest", action="store_true", help="Самопроверка оценщика на T-GOLD (случаи отчёта 93 §2.3)"
    )
    add_variant_arguments(parser)


def latest_submission_dir(
    runs_root: Path, object_ids: tuple[str, ...], exclude: Path | None = None
) -> Path | None:
    """Newest ``runs/*/submission`` directory that holds a file for at least one of the objects."""
    if not runs_root.is_dir():
        return None
    candidates = []
    for sub in runs_root.glob("*/submission"):
        if exclude is not None and sub.parent.resolve() == exclude.resolve():
            continue
        if any((sub / f"{o}.json").is_file() for o in object_ids):
            candidates.append(sub)
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def _tgold_gate(pred: Path, gold_path: Path, sctx, ctx: BatchContext, scored: list[str]) -> None:
    """When this run's own submission of T-GOLD was scored, also write the must-pass gate report."""
    from inspector_eval.data import read_jsonl
    from inspector_eval.fixtures import T_GOLD_OBJECT
    from inspector_eval.tgold_gate import evaluate, write

    own = Path(pred).resolve() in {(ctx.run_dir / "submission").resolve(), ctx.run_dir.resolve()}
    if T_GOLD_OBJECT not in scored or not own:
        return
    result = evaluate(ctx.run_dir, sctx, read_jsonl(gold_path))
    path = write(result, ctx.run_dir)
    failed = [c.id for c in result.criteria.values() if c.status == "FAIL"]
    print(
        f"Приёмка T-GOLD: {result.status}"
        + (f" (не выполнено: {', '.join(failed)})" if failed else "")
        + f"; {path}"
    )
    ctx.log.info("score.tgold_gate", extra={"status": result.status, "failed": failed, "out": str(path)})


def run_score(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_eval.cli import exit_code_for, score_predictions
    from inspector_eval.data import InputError, load_context
    from inspector_eval.fixtures import T_GOLD_OBJECT, run_cases
    from inspector_eval.guard import HiddenAccessRefusedError
    from inspector_eval.report import build_report, render_text, write_outputs
    from inspector_eval.scoring import pool

    paths = ctx.settings.paths
    try:
        sctx = load_context(paths, superseded_path=args.superseded)
    except InputError as exc:
        print(exc.message_ru, file=sys.stderr)
        return int(ExitCode.DATA_MISSING)

    hidden = [o for o in ctx.objects if o in sctx.split_policy.hidden]
    if hidden or ctx.hidden_run:
        err = InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id=hidden[0] if hidden else "?")
        print(f"{err.title}: {err.detail}", file=sys.stderr)
        return int(ExitCode.HIDDEN_TEST_REFUSED)

    gold_path = args.gold or paths.train_checks_path
    cfg = config_from_args(args)

    if args.selftest:
        from inspector_eval.data import read_jsonl

        results = run_cases(read_jsonl(gold_path), sctx, object_id=T_GOLD_OBJECT)
        for r in results:
            d = r.as_dict()
            print(
                f"{d['case']:<10} итог {d['total']:7.2f} (без ограничения {d['total_uncapped']:7.2f}, "
                f"гейт {'да' if d['gate_triggered'] else 'нет'}) {'OK' if d['ok'] else 'РАСХОЖДЕНИЕ'}  {d['title_ru']}"
            )
        ctx.log.info("score.selftest", extra={"cases": len(results), "ok": sum(r.ok for r in results)})
        return int(ExitCode.OK if all(r.ok for r in results) else ExitCode.ERROR)

    pred = args.pred or latest_submission_dir(paths.runs_root, ctx.objects, exclude=ctx.run_dir)
    if pred is None or not Path(pred).exists():
        err = InspectorError("PREDICTION_NOT_FOUND", path=str(pred or f"{paths.runs_root}/*/submission"))
        print(f"{err.title}: {err.detail} {err.hint or ''}".strip(), file=sys.stderr)
        ctx.log.info("score.prediction_not_found", extra={"error_code": err.code, "path": str(pred)})
        return int(ExitCode.DATA_MISSING)
    try:
        scores, skipped, extras = score_predictions(
            pred_path=pred, gold_path=gold_path, ctx=sctx, cfg=cfg, objects=ctx.objects
        )
    except HiddenAccessRefusedError as exc:
        err = exc.error()
        print(f"{err.title}: {exc.reason_ru}.", file=sys.stderr)
        return int(ExitCode.HIDDEN_TEST_REFUSED)
    except InputError as exc:
        print(exc.message_ru, file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    for object_id in skipped:
        err = InspectorError("GOLD_NOT_FOUND", object_id=object_id)
        print(f"{err.title}: {err.detail}", file=sys.stderr)
    if not scores:
        print("Нечего оценивать: для выбранных объектов нет эталона.", file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    pooled = pool(scores, sctx, cfg)
    report = build_report(
        scores,
        pooled,
        cfg,
        sctx,
        gold_path=extras.pop("gold_path"),
        gold_sha256=extras.pop("gold_sha256"),
        extra={**extras, "run_id": ctx.run_id, "prediction_source": str(pred)},
    )
    written = write_outputs(report, scores, ctx.run_dir / "score")
    print(render_text(scores, report.get("pooled")))
    _tgold_gate(pred, gold_path, sctx, ctx, [s.object_id for s in scores])
    ctx.log.info(
        "score.finished",
        extra={
            "objects": [s.object_id for s in scores],
            "totals": {s.object_id: round(s.total, 4) for s in scores},
            "gate_triggered": [s.object_id for s in scores if s.gate_triggered],
            "out": str(written["score"].parent),
        },
    )
    return int(exit_code_for(scores))
