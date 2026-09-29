"""Batch inputs for recognition: manifest rows of the selected objects, page selection, code dictionary.

A minimal reader of ``document_manifest.jsonl`` (the registry proper is AG-01's ``inspector_registry``;
switch to it when it exposes a resolver). Only PDFs are recognised here; organizer-excluded file ids are
refused; files missing on disk are reported (``FILE_MISSING_ON_DISK``), never treated as absent documents.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from inspector_common.paths import DataPaths
from inspector_docproc.codefix import dictionary_from_names


@dataclass(frozen=True, slots=True)
class FileJob:
    file_id: str
    object_id: str
    stage: str
    relative_path: str
    path: Path
    sha256: str
    pdf_pages: int | None


REQUIRED_KEYS = ("file_id", "object_id", "relative_path", "extension", "sha256")


def load_manifest(paths: DataPaths, problems: list[dict[str, str]] | None = None) -> list[dict]:
    """Manifest rows that carry the keys recognition needs; malformed rows go to ``problems``."""
    rows = []
    for n, line in enumerate(paths.manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if not isinstance(row, dict) or any(not row.get(k) for k in REQUIRED_KEYS):
            if problems is not None:
                problems.append({"code": "MANIFEST_ROW_INVALID", "line": str(n), "detail": line[:120]})
            continue
        rows.append(row)
    return rows


def excluded_ids(paths: DataPaths) -> set[str]:
    policy = json.loads(paths.split_policy_path.read_text(encoding="utf-8"))
    return set(policy.get("excluded_file_ids", []))


def select_files(
    paths: DataPaths, objects: tuple[str, ...] | list[str], file_ids: list[str] | None = None
) -> tuple[list[FileJob], list[dict[str, str]]]:
    """PDF files of ``objects`` (optionally only ``file_ids``). Returns (jobs, problems)."""
    problems: list[dict[str, str]] = []
    rows = load_manifest(paths, problems)
    excluded = excluded_ids(paths)
    wanted = set(file_ids or [])
    known = {r["file_id"] for r in rows}
    for fid in sorted(wanted - known):
        problems.append({"code": "MANIFEST_ROW_INVALID", "file_id": fid, "detail": "нет в манифесте"})
    jobs: list[FileJob] = []
    for r in rows:
        fid = r["file_id"]
        if r["object_id"] not in objects or (wanted and fid not in wanted):
            continue
        if fid in excluded:
            if wanted:
                problems.append({"code": "EXCLUDED_FILE_REFERENCED", "file_id": fid})
            continue
        if str(r.get("extension", "")).lower() != ".pdf":
            continue
        path = paths.document_path(r["relative_path"])
        if not path.is_file():
            problems.append(
                {"code": "FILE_MISSING_ON_DISK", "file_id": fid, "relative_path": r["relative_path"]}
            )
            continue
        jobs.append(
            FileJob(
                fid,
                r["object_id"],
                str(r.get("stage", "")),
                r["relative_path"],
                path,
                r["sha256"],
                r.get("pdf_pages"),
            )
        )
    return jobs, problems


def object_code_extras(paths: DataPaths, objects: tuple[str, ...] | list[str]) -> frozenset[str]:
    names = [Path(r["relative_path"]).name for r in load_manifest(paths) if r["object_id"] in objects]
    return dictionary_from_names(names)


_RANGE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$")


def parse_pages(spec: str | None, n_pages: int) -> list[int]:
    """«1-20,25» → [1..20, 25] clipped to the document; None → every page."""
    if not spec:
        return list(range(1, n_pages + 1))
    out: set[int] = set()
    for part in spec.split(","):
        m = _RANGE.match(part)
        if not m:
            raise ValueError(f"неверный диапазон страниц: {part!r}")
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a < 1 or b < a:
            raise ValueError(f"неверный диапазон страниц: {part!r}")
        out.update(range(a, min(b, n_pages) + 1))
    return sorted(out)
