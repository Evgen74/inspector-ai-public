"""Inventory report validation (draft schema shipped with this package) and RunManifest assembly.

The inventory report schema is a proposal for packages/contracts (owner AG-00); until it is adopted
it lives in ``inspector_registry/schemas/inventory_report.schema.json`` and a test keeps its enums in
sync with ``enums.yaml``. ``run_manifest.json`` follows the contract schema ``run_manifest``.
"""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

from inspector_common.contracts.loader import contract_version, validation_errors
from inspector_common.hashing import sha256_file
from inspector_common.paths import DataPaths, repo_root

if TYPE_CHECKING:
    from inspector_common.batch import BatchContext
    from inspector_registry.inventory import Inventory, ObjectInventory

PIPELINE_VERSION = "0.1.0+m0"


@lru_cache(maxsize=1)
def report_schema() -> dict[str, Any]:
    text = (
        resources.files("inspector_registry")
        .joinpath("schemas/inventory_report.schema.json")
        .read_text("utf-8")
    )
    return json.loads(text)


def validate_report(report: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(report_schema())
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '$'}: {err.message}"
        for err in sorted(validator.iter_errors(report), key=lambda e: list(e.absolute_path))
    ]


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def input_hashes(paths: DataPaths) -> dict[str, str]:
    out = {
        "manifest_sha256": sha256_file(paths.manifest_path),
        "catalog_sha256": sha256_file(paths.catalog_path),
        "submission_schema_sha256": sha256_file(paths.submission_schema_path),
    }
    if paths.split_policy_path.is_file():
        out["split_policy_sha256"] = sha256_file(paths.split_policy_path)
    models = repo_root() / "tools" / "models" / "manifest.json"
    if models.is_file():
        out["models_manifest_sha256"] = sha256_file(models)
    return out


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_run_manifest(
    ctx: BatchContext, results: list[ObjectInventory], inventory: Inventory, elapsed: float
) -> tuple[dict[str, Any], list[str]]:
    """RunManifest for this run directory; merges with an existing run_manifest.json (same run id)."""
    from inspector_registry.inventory import engine_versions

    context = _load_json(ctx.run_dir / "run_context.inventory.json") or {}
    existing = _load_json(ctx.run_dir / "run_manifest.json") or {}
    versions = dict(
        context.get("versions")
        or {"pipeline_version": PIPELINE_VERSION, "contract_version": contract_version()}
    )
    versions.setdefault("pipeline_version", PIPELINE_VERSION)
    versions["engine_versions"] = {**(versions.get("engine_versions") or {}), **engine_versions()}
    inputs = context.get("inputs") or input_hashes(ctx.settings.paths)
    ours = {r.object_id for r in results}
    objects = [o for o in existing.get("objects", []) if o.get("object_id") not in ours]
    objects += [r.run_object for r in results]
    files = [f for f in existing.get("files", []) if f.get("object_id") not in ours]
    files += [f for r in results for f in r.run_files]
    warnings = sorted({fl.code for r in results for fl in r.flags if fl.severity in ("warning", "error")})
    timings = dict(existing.get("timings_s") or {})
    timings["inventory"] = round(elapsed, 3)
    for r in results:
        timings[f"inventory.{r.object_id}"] = round(r.seconds, 3)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": ctx.run_id,
        "producer": "inspector-batch",
        "command": context.get("command") or existing.get("command") or "inspector-batch inventory",
        "started_at": existing.get("started_at") or context.get("started_at") or _utc_now(),
        "finished_at": _utc_now(),
        "status": "SUCCEEDED",
        "config_hash": inventory.config_hash,
        "freeze_tag": existing.get("freeze_tag"),
        "versions": versions,
        "inputs": inputs,
        "objects": objects,
        "files": files,
        "timings_s": timings,
        "warnings": sorted(set(existing.get("warnings") or []) | set(warnings)),
    }
    host = context.get("host")
    if host:
        manifest["host"] = host
    return manifest, validation_errors("run_manifest", manifest)
