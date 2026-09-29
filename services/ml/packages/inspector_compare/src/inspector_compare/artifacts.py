"""Reading and writing the run artifacts owned by AG-04 (paths from packages/contracts/run_layout.yaml).

Every write is validated against its contract schema first and is atomic (temporary file + rename), so a
failed command never leaves a half-written artifact behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import ContractValidationError, validation_errors
from inspector_common.runlayout import RunLayout


def _atomic_write(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; run artifacts are shared (web import, other agents)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def dumps(doc: Any) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def write_json(target: Path, doc: Any, schema: str | None) -> Path:
    if schema is not None:
        errors = validation_errors(schema, doc)
        if errors:
            raise ContractValidationError(schema, errors)
    return _atomic_write(target, dumps(doc).encode("utf-8"))


def write_jsonl(target: Path, rows: Iterable[Mapping[str, Any]], schema: str | None) -> Path:
    lines = []
    for n, row in enumerate(rows, start=1):
        if schema is not None:
            errors = validation_errors(schema, row)
            if errors:
                raise ContractValidationError(schema, [f"строка {n}: {e}" for e in errors])
        lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    return _atomic_write(target, ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


class RunArtifacts:
    """The AG-04 artifacts of one run directory."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.layout = RunLayout(run_dir)

    def path(self, kind: str, **fields: Any) -> Path:
        return self.layout.path(kind, **fields)

    def write_findings(
        self, object_id: str, groups: list[dict[str, Any]], findings: list[dict[str, Any]]
    ) -> tuple[Path, Path]:
        g = write_jsonl(self.path("FINDING_GROUPS", object_id=object_id), groups, "finding_group")
        f = write_jsonl(self.path("FINDINGS", object_id=object_id), findings, "finding")
        return g, f

    def read_findings(self, object_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        groups_path = self.path("FINDING_GROUPS", object_id=object_id)
        findings_path = self.path("FINDINGS", object_id=object_id)
        if not findings_path.is_file():
            raise FileNotFoundError(str(findings_path))
        groups = read_jsonl(groups_path) if groups_path.is_file() else []
        return groups, read_jsonl(findings_path)

    def has_findings(self, object_id: str) -> bool:
        return self.path("FINDINGS", object_id=object_id).is_file()

    def relative(self, kind: str, **fields: Any) -> str:
        return self.path(kind, **fields).relative_to(self.run_dir).as_posix()
