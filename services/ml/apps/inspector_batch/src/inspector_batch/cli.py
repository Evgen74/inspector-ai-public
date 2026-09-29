"""`inspector-batch`: the native, DB-free batch engine CLI (97: two run modes, one engine).

    inspector-batch inventory --object OBJ-TYUMENSKAYA-5-GOLD-SEED
    inspector-batch recognize --object … | layout | tables | compare | export | score | bench
    inspector-batch run --object OBJ-TYUMENSKAYA-5-GOLD-SEED     # recognize → … → score (train only)

Common options are defined here; command options by the owner packages (see commands.py).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import logging
import multiprocessing
import os
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

from inspector_batch.commands import COMMANDS, CommandSpec
from inspector_batch.guards import HiddenTestRefusedError, SplitPolicy, check_hidden_policy, resolve_objects
from inspector_batch.runinfo import make_run_dir, new_run_id, run_context
from inspector_common.batch import BatchContext, CommandNotImplementedError
from inspector_common.errors import InspectorError
from inspector_common.exitcodes import ExitCode
from inspector_common.jsonlog import configure_logging, get_logger, log_context
from inspector_common.settings import Settings


def _load(spec: CommandSpec) -> ModuleType:
    return importlib.import_module(spec.module)


def _hook(module: ModuleType, prefix: str, name: str) -> Callable[..., Any]:
    fn = getattr(module, f"{prefix}_{name}", None)
    if fn is None:
        raise AttributeError(f"{module.__name__} must define {prefix}_{name}() (see inspector_common.batch)")
    return fn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inspector-batch",
        description="Инспектор ИИ: пакетный прогон без БД и очередей (инвентаризация → распознавание → разметка → таблицы → сравнение → выгрузка → оценка).",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="Каталог данных организаторов (по умолчанию INSPECTOR_DATA_ROOT или data_utf8/)",
    )
    parser.add_argument("--runs-root", default=None, help="Каталог прогонов (по умолчанию runs/)")
    parser.add_argument(
        "--run-id", default=None, help="Идентификатор прогона (по умолчанию время UTC и команда)"
    )
    parser.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-format", default=None, choices=["json", "console"])
    sub = parser.add_subparsers(dest="command", required=True, metavar="КОМАНДА")
    for name, spec in COMMANDS.items():
        p = sub.add_parser(name, help=f"{spec.help_ru} [владелец {spec.owner}]", description=spec.help_ru)
        p.add_argument(
            "--object",
            "-o",
            dest="objects",
            action="append",
            default=[],
            metavar="OBJECT_ID",
            help="Объект из split_policy.json (можно повторять); по умолчанию — объекты TRAIN_PUBLIC",
        )
        p.add_argument(
            "--all",
            dest="all_objects",
            action="store_true",
            help="Все объекты из split_policy.json, включая скрытую выборку (для неё действуют те же "
            "ограничения: recognize/compare/export — только с --hidden-run, score — запрещена)",
        )
        p.add_argument(
            "--hidden-run",
            action="store_true",
            help="Единственный замороженный прогон по скрытой выборке (только команды recognize/compare/export)",
        )
        _hook(_load(spec), "add", f"{name}_arguments")(p)
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    if args.data_root:
        overrides["data_root"] = args.data_root
    if args.runs_root:
        overrides["runs_root"] = args.runs_root
    if args.log_level:
        overrides["log_level"] = args.log_level
    if args.log_format:
        overrides["log_format"] = args.log_format
    return Settings(**overrides)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    settings = _settings(args)
    configure_logging(settings.log_level, settings.log_format)
    log = get_logger("inspector_batch")
    spec = COMMANDS[args.command]
    paths = settings.paths

    if not paths.split_policy_path.is_file():
        err = InspectorError("DATA_ROOT_NOT_FOUND", path=str(paths.data_root))
        print(f"{err.title}: {err.detail} {err.hint}", file=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    policy = SplitPolicy.load(paths.split_policy_path)
    try:
        objects = resolve_objects(args.objects, policy, all_objects=args.all_objects)
        touches_hidden = check_hidden_policy(spec, objects, policy, args.hidden_run)
    except HiddenTestRefusedError as exc:
        err = InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id=exc.object_id)
        print(f"{err.title}: {exc.reason}.", file=sys.stderr)
        return int(ExitCode.HIDDEN_TEST_REFUSED)
    except ValueError as exc:
        print(f"Ошибка аргументов: {exc}", file=sys.stderr)
        return int(ExitCode.USAGE)

    if touches_hidden:
        # Frozen hidden run: the matrix is the seed, never the admin overrides (recorded as disabled_by_env).
        os.environ["INSPECTOR_MATRIX_OVERRIDES"] = "off"

    run_id = args.run_id or new_run_id(spec.name)
    with log_context(run_id=run_id, command=spec.name):
        if touches_hidden:
            log.warning("hidden_run.started", extra={"objects": list(objects)})
        run_dir = make_run_dir(paths.runs_root, run_id)
        context = run_context(spec.name, argv, run_id, objects, args.hidden_run, paths)
        (run_dir / f"run_context.{spec.name}.json").write_text(
            json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        ctx = BatchContext(
            settings=settings,
            run_id=run_id,
            run_dir=run_dir,
            objects=objects,
            hidden_run=touches_hidden,
            log=log,
        )
        try:
            code = int(_hook(_load(spec), "run", spec.name)(args, ctx))
        except CommandNotImplementedError as exc:
            err = InspectorError("COMMAND_NOT_IMPLEMENTED", command=exc.command, owner=exc.owner)
            print(f"{err.detail} {err.hint}", file=sys.stderr)
            log.info("command.not_implemented", extra={"owner": exc.owner})
            code = int(ExitCode.NOT_IMPLEMENTED)
        finally:
            _write_index(ctx, spec.name)
        log.info("command.finished", extra={"exit_code": code, "run_dir": str(run_dir)})
        return code


def _write_index(ctx: BatchContext, command: str) -> None:
    """Rebuild runs/<run_id>/artifacts.json (run_layout.yaml) after every command; never fails the command."""
    from inspector_common.runlayout import write_artifacts_index

    try:
        write_artifacts_index(ctx.run_dir, ctx.run_id, ctx.objects, command=command)
    except Exception as exc:
        ctx.log.warning("artifacts_index.failed", extra={"detail": f"{type(exc).__name__}: {exc}"})


def entrypoint() -> None:
    """Console-script entry point (``inspector-batch``): run :func:`main`, then exit without native teardown.

    ONNX Runtime with the CoreML provider can abort during interpreter finalization, after the command has
    finished and written its outputs: a C++ static destructor races a background thread («recursive_mutex lock
    failed», exit 134; seen once in two full `bench --suite ocr` runs at M0). Every artifact is written and
    closed before ``main`` returns, so after flushing the logs and standard streams the process leaves with
    ``os._exit`` and never reaches those destructors. When child processes are still alive, the normal exit
    path runs instead, so multiprocessing can still join them (workers are never orphaned).
    """
    code = main()
    if multiprocessing.active_children():
        raise SystemExit(code)
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    os._exit(code)


if __name__ == "__main__":
    entrypoint()
