"""Run directory and RunManifest skeleton (schemas/run_manifest.schema.json).

The CLI creates ``runs/<run_id>/`` and ``run_context.json`` (command, objects, input hashes,
versions, host). Commands fill the RunManifest objects/files as they run.
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import contract_version
from inspector_common.hashing import sha256_file
from inspector_common.paths import DataPaths, ensure_dir, repo_root

PIPELINE_VERSION = "0.1.0+m0"


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_run_id(command: str) -> str:
    return f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-{command}"


def git_version() -> str | None:
    try:
        root = repo_root()
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if commit.returncode != 0:
            return None
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=10
        )
        return commit.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return None


def host_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
    }
    try:
        import onnxruntime

        info["onnxruntime_providers"] = list(onnxruntime.get_available_providers())
    except ImportError:  # pragma: no cover - onnxruntime is a workspace dependency
        pass
    return info


def input_hashes(paths: DataPaths) -> dict[str, str]:
    """sha256 of the organizer inputs that define a run (RunManifest.inputs)."""
    out = {
        "manifest_sha256": sha256_file(paths.manifest_path),
        "catalog_sha256": sha256_file(paths.catalog_path),
        "submission_schema_sha256": sha256_file(paths.submission_schema_path),
        "split_policy_sha256": sha256_file(paths.split_policy_path),
    }
    models_manifest = repo_root() / "tools" / "models" / "manifest.json"
    if models_manifest.is_file():
        out["models_manifest_sha256"] = sha256_file(models_manifest)
    return out


def matrix_overrides_info() -> dict[str, Any]:
    """Admin overrides (module 8) the run reads: applied or not, file, sha256, changed parameters."""
    from inspector_common.params import load_params

    return load_params().overrides


def versions() -> dict[str, Any]:
    from inspector_common.params import load_params, overrides_summary

    registry = load_params()
    return {
        "pipeline_version": PIPELINE_VERSION,
        "matrix_version": registry.matrix_version,
        "code_version": git_version(),
        "contract_version": contract_version(),
        "engine_versions": {"matrix_overrides": overrides_summary(registry.overrides)},
    }


def make_run_dir(runs_root: Path, run_id: str) -> Path:
    return ensure_dir(runs_root / run_id)


def run_context(
    command: str, argv: list[str], run_id: str, objects: tuple[str, ...], hidden_run: bool, paths: DataPaths
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "producer": "inspector-batch",
        "command": " ".join(["inspector-batch", *argv]),
        "subcommand": command,
        "objects": list(objects),
        "hidden_run": hidden_run,
        "started_at": utc_now(),
        "versions": versions(),
        "matrix_overrides": matrix_overrides_info(),
        "inputs": input_hashes(paths),
        "host": host_info(),
        "python_executable": sys.executable,
    }
