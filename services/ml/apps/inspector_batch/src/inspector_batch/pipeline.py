"""`inspector-batch run`: the train end-to-end chain in one run directory (owner AG-00).

    inspector-batch run --object OBJ-TYUMENSKAYA-5-GOLD-SEED            # inventory → recognize → … → score
    inspector-batch run --steps recognize,layout                        # a prefix of the chain
    inspector-batch run --run-id m1-tyumen --from-step compare          # resume in an existing run

Each step is the owner's own ``run_<step>`` hook (commands.py), called with that step's default arguments,
the shared common options and the same run directory, so every step reads its inputs from the previous
steps' artifacts (run_layout.yaml). ``inventory`` comes first so that the run directory carries its own
``run_manifest.json`` and the web product can import it (POST /api/v1/admin/batch-runs/import). The chain stops at the first step that fails or is not implemented
yet, and names its owner. ``score`` reads this run's ``submission/``. Train objects only: the hidden object
never goes through ``run`` (the frozen hidden run calls recognize/compare/export with --hidden-run, M4).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from inspector_common.batch import BatchContext, CommandNotImplementedError
from inspector_common.exitcodes import ExitCode

OWNER = "AG-00"
PIPELINE: tuple[str, ...] = ("inventory", "recognize", "layout", "tables", "compare", "export", "score")


def _steps(value: str) -> list[str]:
    steps = [s.strip() for s in value.split(",") if s.strip()]
    unknown = [s for s in steps if s not in PIPELINE]
    if unknown or not steps:
        raise argparse.ArgumentTypeError(
            f"неизвестные шаги: {', '.join(unknown) or '(пусто)'}; допустимы: {', '.join(PIPELINE)}"
        )
    return [s for s in PIPELINE if s in steps]


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--steps",
        type=_steps,
        default=list(PIPELINE),
        metavar="ШАГ[,ШАГ…]",
        help=f"Шаги цепочки через запятую (по умолчанию все: {','.join(PIPELINE)})",
    )
    parser.add_argument(
        "--from-step",
        choices=PIPELINE,
        default=None,
        help="Начать с этого шага (для продолжения прогона с тем же --run-id)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Число процессов для шагов, у которых есть параметр --workers (recognize, layout, tables)",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Не останавливаться на нереализованном шаге (ошибки по-прежнему останавливают цепочку)",
    )


def _step_args(step: str) -> argparse.Namespace:
    """Defaults of a step's own options, plus the common options the CLI owns."""
    from inspector_batch.commands import COMMANDS

    parser = argparse.ArgumentParser(prog=f"inspector-batch run:{step}", add_help=False)
    module = importlib.import_module(COMMANDS[step].module)
    getattr(module, f"add_{step}_arguments")(parser)
    args = parser.parse_args([])
    args.objects = []
    args.all_objects = False
    args.hidden_run = False
    args.command = step
    return args


def _write_step_context(ctx: BatchContext, step: str) -> None:
    from inspector_batch.runinfo import run_context

    context = run_context(step, ["run", f"--step={step}"], ctx.run_id, ctx.objects, False, ctx.settings.paths)
    context["parent_command"] = "run"
    (ctx.run_dir / f"run_context.{step}.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_run(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_batch.commands import COMMANDS
    from inspector_common.runlayout import write_artifacts_index

    steps: list[str] = list(args.steps)
    if args.from_step:
        steps = [s for s in steps if PIPELINE.index(s) >= PIPELINE.index(args.from_step)]
    results: list[dict[str, object]] = []
    final = int(ExitCode.OK)
    for step in steps:
        spec = COMMANDS[step]
        step_args = _step_args(step)
        if getattr(args, "workers", None) and hasattr(step_args, "workers"):
            step_args.workers = int(args.workers)
        if step == "score" and getattr(step_args, "pred", None) is None:
            step_args.pred = Path(ctx.run_dir) / "submission"
        _write_step_context(ctx, step)
        ctx.log.info("pipeline.step.started", extra={"step": step, "owner": spec.owner})
        try:
            code = int(getattr(importlib.import_module(spec.module), f"run_{step}")(step_args, ctx))
        except CommandNotImplementedError as exc:
            results.append({"step": step, "owner": exc.owner, "status": "not_implemented"})
            print(f"Шаг «{step}» ещё не реализован (владелец {exc.owner}).", file=sys.stderr)
            ctx.log.info("pipeline.step.not_implemented", extra={"step": step, "owner": exc.owner})
            if args.keep_going:
                final = int(ExitCode.NOT_IMPLEMENTED)
                continue
            final = int(ExitCode.NOT_IMPLEMENTED)
            break
        finally:
            try:
                write_artifacts_index(ctx.run_dir, ctx.run_id, ctx.objects, command=step)
            except Exception as exc:  # the index must never hide the step's own result
                ctx.log.warning("pipeline.index_failed", extra={"step": step, "detail": str(exc)})
        results.append(
            {"step": step, "owner": spec.owner, "status": "ok" if code == 0 else "failed", "exit_code": code}
        )
        ctx.log.info("pipeline.step.finished", extra={"step": step, "exit_code": code})
        if code != 0:
            final = code
            print(f"Шаг «{step}» завершился с кодом {code}; цепочка остановлена.", file=sys.stderr)
            break
    (ctx.run_dir / "pipeline_summary.json").write_text(
        json.dumps(
            {"run_id": ctx.run_id, "objects": list(ctx.objects), "steps": results},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    done = [r["step"] for r in results if r["status"] == "ok"]
    print(f"Цепочка: выполнено {len(done)} из {len(steps)} шагов ({', '.join(map(str, done)) or '—'}).")
    return final
