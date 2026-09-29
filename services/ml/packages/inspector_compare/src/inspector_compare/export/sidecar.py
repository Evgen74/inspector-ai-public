"""``submission/<object_id>.sidecar.json``: a RunManifest scoped to one object (contract ``submission_sidecar``).

Never part of the answer (inspector-score skips ``*.sidecar.json``). It records what the answer was made from:
``input_manifest_hash`` (sha256 of the object's manifest rows), the frozen ``config_hash`` with per-stage hashes,
versions, per-file status and page basis, the files missing on disk, timings, and ``freeze_tag`` for the single
hidden run (the scorer's hidden-final guard reads it).
"""

from __future__ import annotations

import datetime as dt
import json
import platform
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from inspector_common.hashing import sha256_file, sha256_json
from inspector_compare.objectctx import ObjectContext
from inspector_compare.version import COMPARE_VERSION, PROTOCOL_VERSION, RULES_VERSION


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_context(run_dir: Path, command: str) -> dict[str, Any]:
    try:
        return json.loads((run_dir / f"run_context.{command}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def input_hashes(paths: Any) -> dict[str, str]:
    out = {
        "manifest_sha256": sha256_file(paths.manifest_path),
        "catalog_sha256": sha256_file(paths.catalog_path),
        "submission_schema_sha256": sha256_file(paths.submission_schema_path),
    }
    if paths.split_policy_path.is_file():
        out["split_policy_sha256"] = sha256_file(paths.split_policy_path)
    return out


def local_status_of(ctx: ObjectContext, settings: Any) -> dict[str, tuple[str, bool | None]]:
    """file_id → (LocalFileStatus, sha256_verified). Inventory report first; otherwise a stat-only check of the
    manifest path and the recovery ledger (no hashing: the export must stay fast)."""
    out: dict[str, tuple[str, bool | None]] = {}
    pending = []
    for f in ctx.files.values():
        if f.local_status:
            out[f.file_id] = (f.local_status, None)
        else:
            pending.append(f.file_id)
    if not pending:
        return out
    try:
        from inspector_registry.api import open_registry

        registry, resolver = open_registry(settings, use_cache=False)
    except Exception:
        for fid in pending:
            out[fid] = ("PRESENT", None)
        return out
    for fid in pending:
        try:
            mf = registry.get(fid)
        except Exception:
            out[fid] = ("MISSING_ON_DISK", None)
            continue
        if resolver.locate(mf) is not None:
            out[fid] = ("PRESENT", None)
        elif fid in resolver.ledger and resolver.ledger[fid].is_file():
            out[fid] = ("RECOVERED", None)
        else:
            out[fid] = ("MISSING_ON_DISK", None)
    return out


def scenario_of(ctx: ObjectContext) -> str:
    """LoadScenario from the stages present in the manifest (resolved per file)."""
    present = {f.stage for f in ctx.files.values() if f.stage and f.citable and f.is_pdf}
    base = {
        frozenset({"PD", "RD", "ID"}): "FULL",
        frozenset({"PD", "RD"}): "PD_RD_ONLY",
        frozenset({"PD", "ID"}): "PD_ID_ONLY",
        frozenset({"RD", "ID"}): "RD_ID_ONLY",
    }.get(frozenset(present))
    if base is None:
        return "SINGLE_ONLY"
    missing_any = any(f.local_status == "MISSING_ON_DISK" for f in ctx.files.values())
    return "PARTIALLY_LOADED" if missing_any else base


def build_sidecar(
    *,
    ctx: ObjectContext,
    run_id: str,
    run_dir: Path,
    settings: Any,
    compare_config_hash: str | None,
    export_config_hash: str,
    artifacts: Mapping[str, str],
    checks_total: int,
    started_at: str,
    timings: Mapping[str, float],
    freeze_tag: str | None,
    warnings: list[str],
    matrix_version: str | None,
) -> dict[str, Any]:
    context = _run_context(run_dir, "export")
    versions = dict(context.get("versions") or {"pipeline_version": COMPARE_VERSION})
    versions.setdefault("pipeline_version", COMPARE_VERSION)
    versions["matrix_version"] = matrix_version
    versions["model_version"] = RULES_VERSION
    engines = dict(versions.get("engine_versions") or {})
    engines.update(
        {"inspector_compare": COMPARE_VERSION, "compare_rules": RULES_VERSION, "protocol": PROTOCOL_VERSION}
    )
    versions["engine_versions"] = engines
    stage_hashes = {"export": export_config_hash}
    if compare_config_hash:
        stage_hashes["compare"] = compare_config_hash
    statuses = local_status_of(ctx, settings)
    files = []
    for f in sorted(ctx.files.values(), key=lambda x: x.file_id):
        status, verified = statuses.get(f.file_id, ("PRESENT", None))
        entry: dict[str, Any] = {
            "file_id": f.file_id,
            "object_id": f.object_id,
            "sha256": f.sha256,
            "manifest_stage": f.manifest_stage,
            "relative_path": f.relative_path,
            "section": f.section,
            "size_bytes": f.size_bytes,
            "stage_resolved": f.stage,
            "local_status": status,
            "sha256_verified": verified,
            "extension": f.extension,
            "pdf_pages": f.pdf_pages,
            "page_basis": "PDF_NATIVE" if f.is_pdf else None,
        }
        files.append(entry)
    missing = [e["file_id"] for e in files if e["local_status"] == "MISSING_ON_DISK"]
    inputs = context.get("inputs") or input_hashes(settings.paths)
    doc: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "producer": "inspector-batch",
        "command": context.get("command")
        or " ".join(["inspector-batch", *sys.argv[1:]])
        or "inspector-batch export",
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": "SUCCEEDED",
        "config_hash": sha256_json({"stage_config_hashes": stage_hashes, "freeze_tag": freeze_tag}),
        "stage_config_hashes": stage_hashes,
        "freeze_tag": freeze_tag,
        "versions": versions,
        "inputs": inputs,
        "host": context.get("host")
        or {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "objects": [
            {
                "object_id": ctx.object_id,
                "name": ctx.name,
                "split": ctx.split or "TRAIN_PUBLIC",
                "input_manifest_hash": ctx.input_manifest_hash,
                "files_total": len(files),
                "files_present": len(files) - len(missing),
                "missing_on_disk": missing,
                "scenario": scenario_of(ctx),
                "checks_total": checks_total,
                "artifacts": dict(artifacts),
            }
        ],
        "files": files,
        "timings_s": {k: round(float(v), 3) for k, v in timings.items()},
        "warnings": sorted(set(warnings)),
    }
    return doc
