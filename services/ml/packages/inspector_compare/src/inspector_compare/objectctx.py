"""Everything the comparison engine knows about one object: files (manifest + resolved stage + discipline marks +
citability), layout and table artifacts, extracted values.

Identity is by sha256 (97 §2.12): a layout or table artifact whose ``file_sha256`` differs from the manifest is
ignored with a warning. Artifacts of another object are ignored. Nothing here reads document content; the
recognition stages did that and wrote the artifacts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from inspector_common.contracts.models import ExtractedValue, LayoutArtifacts, TableArtifacts
from inspector_common.hashing import input_manifest_hash
from inspector_common.jsonlog import get_logger
from inspector_compare.disciplines import file_marks

log = get_logger(__name__)

DOC_STAGES = ("PD", "RD", "ID")


@dataclass(frozen=True, slots=True)
class FileInfo:
    file_id: str
    object_id: str
    relative_path: str
    extension: str
    manifest_stage: str
    stage: str | None  # resolved DocStage (PD/RD/ID) or None when unresolved
    stage_source: str  # MANIFEST | LAYOUT | INVENTORY | NAME_SIGNALS | UNRESOLVED
    section: str
    marks: tuple[str, ...]
    pdf_pages: int | None
    sha256: str
    size_bytes: int | None
    annotation_status: str
    duplicate_group: str | None
    citable: bool
    not_citable_reasons: tuple[str, ...] = ()
    local_status: str | None = None  # LocalFileStatus when an inventory ran

    @property
    def name(self) -> str:
        return PurePosixPath(self.relative_path).name

    @property
    def is_pdf(self) -> bool:
        return self.extension == ".pdf"


@dataclass(slots=True)
class ObjectContext:
    object_id: str
    split: str | None
    name: str | None
    files: dict[str, FileInfo]
    manifest_rows: list[dict[str, Any]]
    layouts: dict[str, LayoutArtifacts] = field(default_factory=dict)
    tables: dict[str, TableArtifacts] = field(default_factory=dict)
    values: list[ExtractedValue] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    layout_source: str | None = None
    excluded_file_ids: frozenset[str] = frozenset()
    run_dir: Path | None = None  # the run directory (PageTokens for AG-07's FREE search), when known

    @property
    def input_manifest_hash(self) -> str:
        return input_manifest_hash(self.manifest_rows)

    def files_of_stage(self, stage: str) -> list[FileInfo]:
        return [f for f in self.files.values() if f.stage == stage]

    def citable(self, file_id: str) -> bool:
        info = self.files.get(file_id)
        return bool(info and info.citable)

    def warn(self, code: str, **details: Any) -> None:
        self.warnings.append({"code": code, **details})
        log.warning("compare.input_warning", extra={"code": code, "detail": details})


# ── building from the registry ────────────────────────────────────────────────────────────────────


def _inventory_files(run_dir: Path | None, object_id: str) -> dict[str, Mapping[str, Any]]:
    """files[] of the AG-01 inventory report of this run (stage_resolved, local_status), when present."""
    if run_dir is None:
        return {}
    path = run_dir / "inventory" / f"{object_id}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(f["file_id"]): f for f in doc.get("files", []) if isinstance(f, Mapping) and f.get("file_id")}


def resolve_file_stage(
    manifest_stage: str,
    relative_path: str,
    *,
    layout_stage: str | None = None,
    inventory_stage: str | None = None,
) -> tuple[str | None, str]:
    """Resolved DocStage and its source. PD/RD/ID manifest stages are authoritative; RD_ID_MIXED/UNKNOWN are
    resolved by the title block (layout), then the inventory report, then the registry's name signals."""
    if manifest_stage in DOC_STAGES:
        return manifest_stage, "MANIFEST"
    candidates = ("RD", "ID") if manifest_stage == "RD_ID_MIXED" else DOC_STAGES
    if layout_stage in candidates:
        return layout_stage, "LAYOUT"
    if inventory_stage in candidates:
        return inventory_stage, "INVENTORY"
    from inspector_registry.stages import resolve_stage

    resolution = resolve_stage(manifest_stage, relative_path, None)
    if resolution.stage_resolved in candidates:
        return resolution.stage_resolved, "NAME_SIGNALS"
    return None, "UNRESOLVED"


def build_file_infos(
    rows: Iterable[Mapping[str, Any]],
    *,
    excluded: frozenset[str],
    layouts: Mapping[str, LayoutArtifacts] | None = None,
    inventory: Mapping[str, Mapping[str, Any]] | None = None,
    not_citable: Mapping[str, list[str]] | None = None,
) -> dict[str, FileInfo]:
    layouts = layouts or {}
    inventory = inventory or {}
    not_citable = not_citable or {}
    out: dict[str, FileInfo] = {}
    for row in rows:
        file_id = str(row["file_id"])
        layout = layouts.get(file_id)
        inv = inventory.get(file_id) or {}
        stage, source = resolve_file_stage(
            str(row.get("stage")),
            str(row.get("relative_path", "")),
            layout_stage=str(layout.stage) if layout and layout.stage else None,
            inventory_stage=inv.get("stage_resolved"),
        )
        codes = [tb.document_code for tb in (layout.title_blocks or [])] if layout else []
        reasons = list(not_citable.get(file_id, []))
        if file_id in excluded and not reasons:
            reasons.append("файл исключён организаторами (excluded_file_ids)")
        out[file_id] = FileInfo(
            file_id=file_id,
            object_id=str(row["object_id"]),
            relative_path=str(row.get("relative_path", "")),
            extension=str(row.get("extension", "")),
            manifest_stage=str(row.get("stage")),
            stage=stage,
            stage_source=source,
            section=str(row.get("section", "OTHER")),
            marks=file_marks(str(row.get("relative_path", "")), row.get("section"), codes),
            pdf_pages=row.get("pdf_pages"),
            sha256=str(row.get("sha256", "")),
            size_bytes=row.get("size_bytes"),
            annotation_status=str(row.get("annotation_status", "")),
            duplicate_group=row.get("duplicate_group"),
            citable=not reasons,
            not_citable_reasons=tuple(reasons),
            local_status=inv.get("local_status"),
        )
    return out


# ── artifacts ─────────────────────────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_layouts(
    directory: Path | None, object_id: str, manifest_sha: Mapping[str, str], ctx_warn: Any
) -> dict[str, LayoutArtifacts]:
    """layout/<file_id>.json of this object; invalid, foreign or sha-mismatched artifacts are skipped."""
    out: dict[str, LayoutArtifacts] = {}
    if directory is None or not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            art = LayoutArtifacts.model_validate(_read_json(path))
        except (ValueError, OSError) as exc:
            ctx_warn(
                "CONTRACT_VALIDATION_FAILED",
                artifact=str(path.name),
                schema="layout_artifacts",
                reason=str(exc)[:300],
            )
            continue
        if art.object_id != object_id:
            continue
        expected = manifest_sha.get(art.file_id)
        if expected is None:
            ctx_warn("FILE_NOT_FOUND", artifact=path.name, file_id=art.file_id)
            continue
        if art.file_sha256 != expected:
            ctx_warn("CHECKSUM_MISMATCH", artifact=path.name, file_id=art.file_id)
            continue
        out[art.file_id] = art
    return out


def load_tables(
    directory: Path | None, object_id: str, manifest_sha: Mapping[str, str], ctx_warn: Any
) -> dict[str, TableArtifacts]:
    out: dict[str, TableArtifacts] = {}
    if directory is None or not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            art = TableArtifacts.model_validate(_read_json(path))
        except (ValueError, OSError) as exc:
            ctx_warn(
                "CONTRACT_VALIDATION_FAILED",
                artifact=str(path.name),
                schema="table_artifacts",
                reason=str(exc)[:300],
            )
            continue
        if art.object_id != object_id:
            continue
        if manifest_sha.get(art.file_id) != art.file_sha256:
            ctx_warn("CHECKSUM_MISMATCH", artifact=path.name, file_id=art.file_id)
            continue
        out[art.file_id] = art
    return out


def load_values(path: Path | None, object_id: str, ctx_warn: Any) -> list[ExtractedValue]:
    out: list[ExtractedValue] = []
    if path is None or not path.is_file():
        return out
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                value = ExtractedValue.model_validate(json.loads(line))
            except ValueError as exc:
                ctx_warn(
                    "CONTRACT_VALIDATION_FAILED",
                    artifact=f"{path.name}:{n}",
                    schema="extracted_value",
                    reason=str(exc)[:300],
                )
                continue
            if value.object_id in (None, object_id):
                out.append(value)
    return out


@dataclass(frozen=True, slots=True)
class InputDirs:
    """Where compare reads its inputs (defaults: the run directory, run_layout.yaml paths)."""

    layout_dir: Path | None
    tables_dir: Path | None
    values_path: Path | None
    run_dir: Path | None = None
    layout_source: str | None = None


def build_context(
    object_id: str,
    manifest_rows: list[dict[str, Any]],
    *,
    split: str | None,
    name: str | None,
    excluded: frozenset[str],
    inputs: InputDirs,
    not_citable: Mapping[str, list[str]] | None = None,
) -> ObjectContext:
    rows = [r for r in manifest_rows if r.get("object_id") == object_id]
    ctx = ObjectContext(
        object_id=object_id,
        split=split,
        name=name,
        files={},
        manifest_rows=rows,
        layout_source=inputs.layout_source,
        run_dir=inputs.run_dir,
        excluded_file_ids=excluded,
    )
    sha = {str(r["file_id"]): str(r.get("sha256", "")) for r in rows}
    ctx.layouts = load_layouts(inputs.layout_dir, object_id, sha, ctx.warn)
    ctx.tables = load_tables(inputs.tables_dir, object_id, sha, ctx.warn)
    ctx.values = load_values(inputs.values_path, object_id, ctx.warn)
    ctx.files = build_file_infos(
        rows,
        excluded=excluded,
        layouts=ctx.layouts,
        inventory=_inventory_files(inputs.run_dir, object_id),
        not_citable=not_citable,
    )
    return ctx


def context_from_registry(object_id: str, registry: Any, inputs: InputDirs) -> ObjectContext:
    """Build the context from inspector_registry's :class:`Registry` (manifest + split policy)."""
    files = registry.files(object_id)
    rows = [dict(f.raw) for f in files]
    not_citable = {}
    for f in files:
        try:
            reasons = registry.not_citable_reasons(f.file_id)
        except Exception as exc:  # excluded ids raise; they are not in the manifest of v2.0 anyway
            reasons = [str(exc)]
        if reasons:
            not_citable[f.file_id] = reasons
    corpus = next((f.corpus for f in files), None)
    return build_context(
        object_id,
        rows,
        split=registry.split_of(object_id),
        name=corpus,
        excluded=frozenset(registry.policy.excluded_file_ids),
        inputs=inputs,
        not_citable=not_citable,
    )
