"""Paths inside a run directory ``runs/<run_id>/`` and its artifact index (packages/contracts/run_layout.yaml).

Every producer resolves its output path here instead of hard-coding it, and every consumer (the next batch
command, the web import) reads ``artifacts.json`` instead of globbing:

    from inspector_common.runlayout import RunLayout, write_artifacts_index
    layout = RunLayout(ctx.run_dir)
    out = layout.path("LAYOUT", file_id="F0202")            # runs/<run_id>/layout/F0202.json
    out = layout.path("PAGE_TOKENS", file_id="F0201", page=17)  # …/tokens/F0201/p00017.json.gz
    write_artifacts_index(ctx.run_dir, ctx.run_id)          # the CLI does this after every command

The layout (templates, schema per kind, producer) is contract data owned by AG-00; never add a kind in code.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import load_run_layout, validate
from inspector_common.hashing import sha256_file

INDEX_FILE = "artifacts.json"
_FIELD = re.compile(r"\{([a-z_0-9]+)\}")
_FIELD_PATTERNS = {
    "object_id": r"(?P<object_id>[^/]+?)",
    "file_id": r"(?P<file_id>[^/]+?)",
    "page05": r"(?P<page05>[0-9]{5})",
    "command": r"(?P<command>[a-z_]+)",
}


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    kind: str
    template: str
    scope: str
    format: str
    schema: str | None
    agent: str
    command: str

    def render(self, **fields: Any) -> str:
        values = dict(fields)
        if "page" in values and "page05" not in values:
            page = int(values.pop("page"))
            if page < 1:
                raise ValueError(f"{self.kind}: page numbers are 1-based, got {page}")
            values["page05"] = f"{page:05d}"
        missing = set(_FIELD.findall(self.template)) - set(values)
        if missing:
            raise KeyError(f"{self.kind}: missing path fields {sorted(missing)}")
        for key, value in values.items():
            text = str(value)
            if not text or "/" in text or "\\" in text or text in {".", ".."}:
                raise ValueError(f"{self.kind}: unsafe value for {key}: {text!r}")
        return self.template.format(**{k: str(v) for k, v in values.items()})

    @property
    def regex(self) -> re.Pattern[str]:
        return _compiled(self.template)


@lru_cache(maxsize=64)
def _compiled(template: str) -> re.Pattern[str]:
    parts = _FIELD.split(template)
    out = []
    for i, part in enumerate(parts):
        out.append(_FIELD_PATTERNS[part] if i % 2 else re.escape(part))
    return re.compile("^" + "".join(out) + "$")


@lru_cache(maxsize=1)
def artifact_specs() -> dict[str, ArtifactSpec]:
    """ArtifactKind → spec, from run_layout.yaml (validated against enums by `inspector-contracts check`)."""
    raw = load_run_layout()
    specs: dict[str, ArtifactSpec] = {}
    for kind, entry in raw["artifacts"].items():
        producer = entry.get("producer") or {}
        specs[kind] = ArtifactSpec(
            kind=kind,
            template=str(entry["path"]),
            scope=str(entry["scope"]),
            format=str(entry["format"]),
            schema=entry.get("schema"),
            agent=str(producer.get("agent", "")),
            command=str(producer.get("command", "")),
        )
    return specs


def artifact_path(kind: str, **fields: Any) -> str:
    """Relative POSIX path of an artifact, e.g. ``artifact_path("FINDINGS", object_id="OBJ-…")``."""
    try:
        spec = artifact_specs()[kind]
    except KeyError:
        raise KeyError(f"unknown ArtifactKind {kind!r} (see packages/contracts/run_layout.yaml)") from None
    return spec.render(**fields)


@lru_cache(maxsize=1)
def _specs_most_specific_first() -> tuple[ArtifactSpec, ...]:
    # «submission/{object_id}.sidecar.json» must win over «submission/{object_id}.json», «inventory/index.json»
    # over «inventory/{object_id}.json»: try the templates with the longest literal text first.
    return tuple(sorted(artifact_specs().values(), key=lambda s: -len(_FIELD.sub("", s.template))))


def classify(relative_path: str) -> tuple[ArtifactSpec, dict[str, str]] | None:
    """Match a relative path against the layout; returns the spec and the placeholder values."""
    for spec in _specs_most_specific_first():
        match = spec.regex.match(relative_path)
        if match:
            return spec, {k: v for k, v in match.groupdict().items() if v is not None}
    return None


@dataclass(frozen=True, slots=True)
class RunLayout:
    """Absolute paths inside one run directory."""

    run_dir: Path

    def path(self, kind: str, **fields: Any) -> Path:
        return self.run_dir / artifact_path(kind, **fields)

    def ensure_parent(self, kind: str, **fields: Any) -> Path:
        target = self.path(kind, **fields)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    @property
    def index_path(self) -> Path:
        return self.run_dir / INDEX_FILE


def _count_records(path: Path, fmt: str) -> int | None:
    if fmt != "JSONL":
        return None
    with open(path, "rb") as fh:
        return sum(1 for line in fh if line.strip())


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_artifacts_index(
    run_dir: Path,
    run_id: str,
    objects: Iterable[str] = (),
    commands: Iterable[str] = (),
    object_of_file: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Scan ``run_dir`` and describe every file the layout knows. Page tokens are summarised per file;
    files the layout does not know (logs, scratch) are left out."""
    object_of_file = dict(object_of_file or {})
    artifacts: list[dict[str, Any]] = []
    token_dirs: dict[str, dict[str, Any]] = {}
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(run_dir).as_posix()
        if rel == INDEX_FILE or path.name.startswith("."):
            continue
        found = classify(rel)
        if found is None:
            continue
        spec, values = found
        if spec.kind == "PAGE_TOKENS":
            file_id = values["file_id"]
            entry = token_dirs.setdefault(
                file_id,
                {"file_id": file_id, "dir": f"tokens/{file_id}", "pages": 0, "size_bytes": 0},
            )
            if file_id in object_of_file:
                entry["object_id"] = object_of_file[file_id]
            entry["pages"] += 1
            entry["size_bytes"] += path.stat().st_size
            continue
        item: dict[str, Any] = {
            "kind": spec.kind,
            "path": rel,
            "format": spec.format,
            "schema_name": spec.schema,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "producer": {"agent": spec.agent, "command": values.get("command", spec.command)},
            "modified_at": _mtime(path),
        }
        if "object_id" in values:
            item["object_id"] = values["object_id"]
        if "file_id" in values:
            item["file_id"] = values["file_id"]
            if values["file_id"] in object_of_file:
                item["object_id"] = object_of_file[values["file_id"]]
        records = _count_records(path, spec.format)
        if records is not None:
            item["records"] = records
        artifacts.append(item)
    doc: dict[str, Any] = {
        "schema_version": 1,
        "layout_version": str(load_run_layout()["layout_version"]),
        "run_id": run_id,
        "generated_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "objects": list(dict.fromkeys(objects)),
        "commands": list(dict.fromkeys(commands)),
        "artifacts": artifacts,
        "page_tokens": [token_dirs[k] for k in sorted(token_dirs)],
    }
    return doc


def _previous_commands(run_dir: Path) -> list[str]:
    try:
        return list(json.loads((run_dir / INDEX_FILE).read_text(encoding="utf-8")).get("commands", []))
    except (OSError, ValueError):
        return []


def write_artifacts_index(
    run_dir: Path,
    run_id: str,
    objects: Iterable[str] = (),
    command: str | None = None,
    object_of_file: Mapping[str, str] | None = None,
) -> Path:
    """(Re)write ``artifacts.json`` atomically; validated against run_artifacts.schema.json first."""
    commands = _previous_commands(run_dir)
    if command:
        commands.append(command)
    doc = build_artifacts_index(run_dir, run_id, objects, commands, object_of_file)
    validate("run_artifacts", doc)
    target = run_dir / INDEX_FILE
    fd, tmp = tempfile.mkstemp(prefix=".artifacts.", suffix=".json", dir=run_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def load_artifacts_index(run_dir: Path) -> dict[str, Any]:
    """Read and validate ``artifacts.json`` of a run."""
    doc = json.loads((run_dir / INDEX_FILE).read_text(encoding="utf-8"))
    validate("run_artifacts", doc)
    return doc
