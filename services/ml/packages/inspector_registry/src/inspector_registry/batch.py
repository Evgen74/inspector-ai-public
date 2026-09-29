"""inspector-batch commands implemented by inspector_registry — OWNED BY AG-01.

``inspector-batch inventory --object <id> | --all [--verify-sha256] [--no-cache]``

Writes ``runs/<run_id>/inventory/<object_id>.json`` (one per object), ``inventory/index.json`` and
``run_manifest.json`` (RunManifest contract). Inventory is input handling, so it is allowed on the
hidden-test object (97 §2.17); ``--all`` therefore includes it, and says so in the log.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from inspector_common.batch import BatchContext
from inspector_common.exitcodes import ExitCode

OWNER = "AG-01"


def add_inventory_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--verify-sha256",
        action="store_true",
        help="Проверить sha256 каждого файла по манифесту (результат кешируется в .cache/ по пути, размеру и времени изменения)",
    )
    # `--all` (dest all_objects) is a common inspector-batch option since M0 integration (AG-00 cli.py).
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Не использовать кеш .cache/registry (sha256, проверки PDF, списки архивов)",
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def _human(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def run_inventory(args: argparse.Namespace, ctx: BatchContext) -> int:
    from inspector_common.errors import InspectorError
    from inspector_common.jsonlog import log_context
    from inspector_registry.cache import RegistryCache
    from inspector_registry.inventory import Inventory, InventoryOptions
    from inspector_registry.manifest import Registry
    from inspector_registry.report import build_run_manifest, validate_report
    from inspector_registry.resolver import PathResolver

    started = time.perf_counter()
    paths = ctx.settings.paths
    try:
        registry = Registry.load(paths)
    except InspectorError as err:
        print(f"{err.title}: {err.detail} {err.hint or ''}".strip(), file=sys.stderr)
        return int(ExitCode.DATA_MISSING)

    if getattr(args, "all_objects", False):
        if args.objects:
            print("Ошибка аргументов: укажите либо --object, либо --all.", file=sys.stderr)
            return int(ExitCode.USAGE)
        objects = registry.policy.objects
    else:
        objects = ctx.objects
    if not objects:
        print("Нет объектов для инвентаризации.", file=sys.stderr)
        return int(ExitCode.USAGE)

    cache = RegistryCache(None) if args.no_cache else RegistryCache.at(ctx.settings.cache_root)
    from inspector_common.resources import worker_budget

    workers = worker_budget(
        1, ctx.settings.workers or None
    )  # capped at INSPECTOR_RESOURCE_CAP of the machine
    resolver = PathResolver(registry, paths, cache, hash_workers=min(8, workers))
    options = InventoryOptions(
        verify_sha256=bool(args.verify_sha256), hash_workers=min(8, workers), probe_workers=min(8, workers)
    )
    inventory = Inventory(registry, resolver, options, cache)
    out_dir = ctx.run_dir / "inventory"
    results = []
    exit_code = int(ExitCode.OK)
    try:
        for object_id in objects:
            with log_context(object_id=object_id):
                if registry.policy.is_hidden(object_id):
                    ctx.log.warning(
                        "inventory.hidden_object", extra={"note": "input handling only (97 §2.17)"}
                    )
                result = inventory.run_object(object_id, run_id=ctx.run_id)
                problems = validate_report(result.report)
                if problems:
                    ctx.log.error("inventory.report_invalid", extra={"errors": problems[:5]})
                    exit_code = int(ExitCode.SCHEMA_INVALID)
                _write_json(out_dir / f"{object_id}.json", result.report)
                c = result.report["counts"]
                ctx.log.info(
                    "inventory.object_done",
                    extra={
                        "files": c["files_total"],
                        "missing_on_disk": c["files_missing_on_disk"],
                        "pdf_pages": c["pdf_pages_actual_total"],
                        "archive_members": c["archive_members_total"],
                        "flags": c["integrity_flags"],
                        "seconds": round(result.seconds, 3),
                    },
                )
                print(
                    f"{object_id}: файлов {c['files_total']} (на диске {c['files_present']}, "
                    f"восстановлено {c['files_recovered']}, нет {c['files_missing_on_disk']}; "
                    f"sha256 проверено {c['sha256_verified']}), страниц PDF {_human(c['pdf_pages_actual_total'])}, "
                    f"архивов {c['archives']} (элементов {c['archive_members_total']}), "
                    f"флагов {c['integrity_flags']} — {result.seconds:.1f} с"
                )
                results.append(result)
    finally:
        cache.close()

    elapsed = time.perf_counter() - started
    index = {
        "run_id": ctx.run_id,
        "objects": [
            {
                "object_id": r.object_id,
                "split": r.report["split"],
                "report": f"inventory/{r.object_id}.json",
                "counts": r.report["counts"],
                "timings_s": r.report["timings_s"],
            }
            for r in results
        ],
        "sha256_hashed_files": resolver.hashed_files,
        "sha256_hashed_bytes": resolver.hashed_bytes,
        "cache": {
            "sha256_hits": cache.hits,
            "sha256_misses": cache.misses,
            "path": str(cache.db_path) if cache.db_path else None,
        },
        "seconds_total": round(elapsed, 3),
    }
    _write_json(out_dir / "index.json", index)
    manifest, errors = build_run_manifest(ctx, results, inventory, elapsed)
    if errors:
        ctx.log.error("run_manifest.invalid", extra={"errors": errors[:5]})
        exit_code = int(ExitCode.SCHEMA_INVALID)
    _write_json(ctx.run_dir / "run_manifest.json", manifest)
    print(f"Отчёты: {out_dir} (всего {elapsed:.1f} с)")
    return exit_code
