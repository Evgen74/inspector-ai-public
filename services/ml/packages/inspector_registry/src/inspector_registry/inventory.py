"""Per-object inventory: manifest rows → local files → probes → archives → stages → twins → duplicates.

Output (written by ``batch.run_inventory``):
- ``runs/<run_id>/inventory/<object_id>.json`` — the report (draft schema:
  ``inspector_registry/schemas/inventory_report.schema.json``, proposed for packages/contracts);
- entries for ``runs/<run_id>/run_manifest.json`` (RunManifest objects/files, contract schema).

Hidden-test objects (split_policy TEST_HIDDEN) are inventoried like any other object — inventory is
input handling (97 §2.17) — but text snippets behind stage signals are redacted from their report.
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.contracts.enums import ArchiveMemberRole, LocalFileStatus, PageBasis
from inspector_common.contracts.loader import contract_version
from inspector_common.hashing import config_hash, sha256_json
from inspector_registry import __version__, filetypes
from inspector_registry.archives import (
    LISTING_VERSION,
    ArchiveLimits,
    ArchiveListing,
    ArchiveMember,
    list_archive,
)
from inspector_registry.cache import RegistryCache
from inspector_registry.duplicates import DupInput, find_duplicates
from inspector_registry.flags import IntegrityFlag, count_codes
from inspector_registry.manifest import ManifestFile, Registry
from inspector_registry.pdfprobe import PROBE_VERSION, PdfProbe, probe_pdf
from inspector_registry.resolver import PathResolver, ResolvedFile
from inspector_registry.stages import STAGE_RULES_VERSION, StageResolution, resolve_stage
from inspector_registry.twins import TWIN_VERSION, ArchiveTwins, link_archive, link_loose

INVENTORY_VERSION = "inventory-1"
REPORT_SCHEMA_VERSION = 1
MIB = 1024 * 1024
PARALLEL_PROBE_MIN = 16
UI_FILE_LIMIT = 50 * MIB  # ТЗ §9.1 HTTP upload limits; batch ingest bypasses them (97 §2.12)
UI_PACKAGE_LIMIT = 200 * MIB


@dataclass(frozen=True, slots=True)
class InventoryOptions:
    verify_sha256: bool = False
    limits: ArchiveLimits = field(default_factory=ArchiveLimits)
    large_document_pages: int = 300  # LARGE_DOCUMENT info threshold (≈10 min of OCR at ~2 s/page)
    hash_workers: int = 4
    probe_workers: int = 8

    def config(self) -> dict[str, Any]:
        return {
            "inventory_version": INVENTORY_VERSION,
            "listing_version": LISTING_VERSION,
            "probe_version": PROBE_VERSION,
            "stage_rules_version": STAGE_RULES_VERSION,
            "twin_version": TWIN_VERSION,
            "verify_sha256": self.verify_sha256,
            "limits": self.limits.as_config(),
            "large_document_pages": self.large_document_pages,
        }


@dataclass(slots=True)
class ObjectInventory:
    object_id: str
    report: dict[str, Any]
    run_object: dict[str, Any]
    run_files: list[dict[str, Any]]
    flags: list[IntegrityFlag]
    seconds: float


def engine_versions() -> dict[str, str]:
    out: dict[str, str] = {"inspector_registry": __version__}
    try:
        import pymupdf

        out["pymupdf"] = pymupdf.VersionBind
    except Exception:  # pragma: no cover
        pass
    try:
        from libarchive import ffi

        n = ffi.version_number()
        out["libarchive"] = f"{n // 1000000}.{n // 1000 % 1000}.{n % 1000}"
    except Exception:  # pragma: no cover
        pass
    return out


def _local_path(path: Path | None, anchor: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(anchor))
    except ValueError:
        return str(path)


def _read_head(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(filetypes.HEAD_BYTES)


class _Timer:
    def __init__(self) -> None:
        self.totals: dict[str, float] = Counter()

    def add(self, key: str, started: float) -> None:
        self.totals[key] += time.perf_counter() - started

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in sorted(self.totals.items())}


class Inventory:
    """Builds object inventories. One instance per run (shares the resolver and the cache)."""

    def __init__(
        self,
        registry: Registry,
        resolver: PathResolver,
        options: InventoryOptions | None = None,
        cache: RegistryCache | None = None,
    ) -> None:
        self.registry = registry
        self.resolver = resolver
        self.options = options or InventoryOptions()
        self.cache = cache or resolver.cache
        self.config = self.options.config()
        self.config_hash = config_hash(self.config)
        self._listing_version = f"{LISTING_VERSION}:{sha256_json(self.options.limits.as_config())[:12]}"
        self._manifest_sha_index = registry.by_sha256

    # ── probes (cached by path + size + mtime + version) ─────────────────────────────────────

    def _probe_pdfs(self, targets: list[ResolvedFile]) -> dict[str, PdfProbe]:
        """Cached probes first; the rest in a process pool (PyMuPDF is not thread-safe)."""
        out: dict[str, PdfProbe] = {}
        todo: list[ResolvedFile] = []
        for r in targets:
            assert r.path is not None and r.size_on_disk is not None and r.mtime_ns is not None
            cached = self.cache.get_probe("pdf", r.path, r.size_on_disk, r.mtime_ns, PROBE_VERSION)
            if cached is not None:
                out[r.file_id] = PdfProbe.from_json(cached)
            else:
                todo.append(r)
        workers = min(self.options.probe_workers, len(todo))
        if workers >= 2 and len(todo) >= PARALLEL_PROBE_MIN:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                probes = list(pool.map(probe_pdf, [r.path for r in todo], chunksize=4))
        else:
            probes = [probe_pdf(r.path) for r in todo if r.path is not None]
        for r, probe in zip(todo, probes, strict=True):
            assert r.path is not None and r.size_on_disk is not None and r.mtime_ns is not None
            self.cache.put_probe("pdf", r.path, r.size_on_disk, r.mtime_ns, PROBE_VERSION, probe.to_json())
            out[r.file_id] = probe
        return out

    def _list_archive(self, r: ResolvedFile) -> ArchiveListing:
        assert r.path is not None and r.size_on_disk is not None and r.mtime_ns is not None
        cached = self.cache.get_probe("archive", r.path, r.size_on_disk, r.mtime_ns, self._listing_version)
        if cached is not None:
            return ArchiveListing.from_json(cached)
        listing = list_archive(r.path, self.options.limits)
        self.cache.put_probe(
            "archive", r.path, r.size_on_disk, r.mtime_ns, self._listing_version, listing.to_json()
        )
        return listing

    # ── one object ───────────────────────────────────────────────────────────────────────────

    def run_object(self, object_id: str, *, run_id: str) -> ObjectInventory:
        started = time.perf_counter()
        timer = _Timer()
        registry = self.registry
        split = registry.split_of(object_id)
        hidden = registry.policy.is_hidden(object_id)
        files = registry.files(object_id)
        file_ids = {f.file_id for f in files}
        flags: list[IntegrityFlag] = [f for f in registry.flags if f.file_id in file_ids]
        if not files:
            flags.append(
                IntegrityFlag.make(
                    "MANIFEST_ROW_INVALID",
                    {"row": 0, "file_id": "-", "reason": f"в манифесте нет файлов объекта {object_id}"},
                )
            )

        t = time.perf_counter()
        resolved = {
            r.file_id: r for r in self.resolver.resolve_many(files, verify=self.options.verify_sha256)
        }
        timer.add("resolve_and_verify", t)
        for r in resolved.values():
            flags.extend(r.flags)

        records: dict[str, dict[str, Any]] = {}
        stage_results: dict[str, StageResolution] = {}
        anchor = self.resolver.paths.data_root.parent
        skip_content = "служебный файл разметки: содержимое не читается"

        # Pass 1: records and magic-byte sniffing (no content read for ground-truth files).
        t = time.perf_counter()
        for f in files:
            r = resolved[f.file_id]
            rec = self._base_record(f, r, anchor)
            records[f.file_id] = rec
            if not r.readable or f.annotation_status in registry.non_citable_annotations:
                continue
            assert r.path is not None
            head = _read_head(r.path)
            media = filetypes.sniff(head, f.extension)
            rec["media_type"] = media
            expected = filetypes.expected_types(f.extension)
            if expected is not None and media not in expected:
                flags.append(
                    IntegrityFlag.make(
                        "CONTENT_TYPE_MISMATCH",
                        {"file_name": f.name, "ext": f.extension.lstrip("."), "detected": media},
                        file_id=f.file_id,
                    )
                )
            if f.is_drawing:
                version = filetypes.dwg_version(head)
                if version:
                    rec["dwg_version"], rec["dwg_release"] = version.code, version.release
        timer.add("sniff", t)

        # Pass 2: PDF probes (cached; uncached ones in a process pool).
        t = time.perf_counter()
        probes = self._probe_pdfs(
            [
                resolved[f.file_id]
                for f in files
                if f.is_pdf and records[f.file_id]["media_type"] == filetypes.PDF
            ]
        )
        timer.add("pdf_probe", t)
        for f in files:
            probe = probes.get(f.file_id)
            if probe is None:
                continue
            rec = records[f.file_id]
            rec["pdf"] = {
                k: v for k, v in probe.to_json().items() if k not in ("stage_text", "probe_version")
            }
            rec["pdf_pages"] = probe.page_count if probe.page_count is not None else f.pdf_pages
            flags.extend(self._pdf_flags(f, probe))

        # Pass 3: stage resolution from folder, name and first-pages text.
        t = time.perf_counter()
        for f in files:
            if f.annotation_status in registry.non_citable_annotations:
                stage_results[f.file_id] = resolve_stage(
                    f.stage, f.relative_path, None, skip_reason=skip_content
                )
                continue
            probe = probes.get(f.file_id)
            text = probe.stage_text if probe is not None and probe.stage_text else None
            stage_results[f.file_id] = resolve_stage(f.stage, f.relative_path, text)
        timer.add("stages", t)

        # Stages → records, conflicts.
        for f in files:
            sr = stage_results[f.file_id]
            records[f.file_id]["stage"] = sr.to_json(redact=hidden)
            records[f.file_id]["stage_resolved"] = sr.stage_resolved
            if sr.conflict:
                flags.append(
                    IntegrityFlag.make(
                        "META_CONFLICT",
                        {
                            "file_name": f.name,
                            "field": "стадия",
                            "registry_value": f.stage,
                            "stamp_value": str(sr.signals_stage),
                        },
                        file_id=f.file_id,
                        note_ru="по признакам в пути и тексте первых страниц; стадия манифеста не меняется",
                    )
                )

        # Loose DWG/DXF/DOCX twins.
        t = time.perf_counter()
        for f in files:
            if f.is_drawing or f.is_docx:
                link = link_loose(f, files)
                records[f.file_id]["twin"] = link.to_json() if link else None
        timer.add("twins", t)

        # Archives.
        archives: list[dict[str, Any]] = []
        pdf_pages = {fid: rec.get("pdf_pages") for fid, rec in records.items()}
        seen_member_sha: dict[str, str] = {}
        t = time.perf_counter()
        for f in files:
            r = resolved[f.file_id]
            if (
                not f.is_archive
                or not r.readable
                or records[f.file_id].get("media_type") not in filetypes.ARCHIVE_TYPES
            ):
                continue
            listing = self._list_archive(r)
            summary, member_flags = self._archive_summary(f, listing, files, pdf_pages, seen_member_sha)
            archives.append(summary)
            records[f.file_id]["archive_members"] = summary["members_total"]
            records[f.file_id]["twin"] = summary["twin"]
            flags.extend(member_flags)
        timer.add("archives", t)

        # Duplicates.
        t = time.perf_counter()
        dups = find_duplicates(
            DupInput(
                file_id=f.file_id,
                sha256=f.sha256,
                pages=probes[f.file_id].page_count if f.file_id in probes else None,
                text_hash=probes[f.file_id].first_page_text_hash if f.file_id in probes else None,
                image_hash=probes[f.file_id].first_page_image_hash if f.file_id in probes else None,
            )
            for f in files
        )
        timer.add("duplicates", t)

        # Citability and per-file flag codes.
        codes_by_file: dict[str, list[str]] = {}
        for flag in flags:
            if flag.file_id:
                codes_by_file.setdefault(flag.file_id, []).append(flag.code)
        for f in files:
            rec = records[f.file_id]
            reasons = registry.not_citable_reasons(f.file_id)
            rec["citable"] = not reasons
            rec["not_citable_reasons"] = reasons
            rec["flags"] = sorted(set(codes_by_file.get(f.file_id, [])))

        seconds = time.perf_counter() - started
        timings = timer.as_dict()
        timings["total"] = round(seconds, 3)
        counts = self._counts(files, resolved, records, stage_results, archives, dups, flags)
        report = {
            "schema": "inventory_report",
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run_id,
            "object_id": object_id,
            "split": split,
            "hidden_test": hidden,
            "generated_at": _utc_now(),
            "input_manifest_hash": registry.input_manifest_hash(object_id),
            "config": self.config,
            "config_hash": self.config_hash,
            "versions": {
                "inventory_version": INVENTORY_VERSION,
                "contract_version": contract_version(),
                **engine_versions(),
            },
            "manifest": {
                "path": _local_path(registry.manifest_path, anchor),
                "sha256": registry.manifest_sha256,
                "checksum_ok": registry.manifest_checksum_ok,
                "rows_read": registry.rows_read,
                "rows_registered": len(registry),
                "excluded_file_ids": sorted(registry.policy.excluded_file_ids),
                "unknown_open_values": registry.unknown_open_values,
                # Package-level flags and flags of rows that were not registered (e.g. excluded ids).
                "flags": [
                    fl.to_json() for fl in registry.flags if fl.file_id is None or fl.file_id not in registry
                ],
            },
            "counts": counts,
            "files": [records[f.file_id] for f in files],
            "archives": archives,
            "duplicates": dups,
            "integrity_flags": [fl.to_json() for fl in flags],
            "timings_s": timings,
        }
        run_files = [self._run_file(f, resolved[f.file_id], records[f.file_id]) for f in files]
        run_object = {
            "object_id": object_id,
            "split": split or "TRAIN_PUBLIC",
            "input_manifest_hash": report["input_manifest_hash"],
            "files_total": len(files),
            "files_present": sum(1 for r in resolved.values() if r.readable),
            "missing_on_disk": sorted(r.file_id for r in resolved.values() if not r.readable),
        }
        return ObjectInventory(object_id, report, run_object, run_files, flags, seconds)

    # ── pieces ───────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _base_record(f: ManifestFile, r: ResolvedFile, anchor: Path) -> dict[str, Any]:
        return {
            "file_id": f.file_id,
            "relative_path": f.relative_path,
            "name": f.name,
            "folder": f.folder,
            "extension": f.extension,
            "size_bytes": f.size_bytes,
            "sha256": f.sha256,
            "manifest_stage": f.stage,
            "section": f.section,
            "annotation_status": f.annotation_status,
            "dataset_role": f.dataset_role,
            "duplicate_group": f.duplicate_group,
            "pdf_pages_manifest": f.pdf_pages,
            "pdf_pages": f.pdf_pages,
            "local_status": r.local_status.value,
            "found_via": r.found_via,
            "local_path": _local_path(r.path, anchor),
            "sha256_verified": r.sha256_verified,
            "media_type": None,
            "dwg_version": None,
            "dwg_release": None,
            "pdf": None,
            "twin": None,
            "archive_members": None,
        }

    def _pdf_flags(self, f: ManifestFile, probe: PdfProbe) -> list[IntegrityFlag]:
        out: list[IntegrityFlag] = []
        if probe.encrypted:
            out.append(IntegrityFlag.make("FILE_ENCRYPTED", {"file_name": f.name}, file_id=f.file_id))
        elif probe.error:
            out.append(
                IntegrityFlag.make(
                    "FILE_CORRUPTED", {"file_name": f.name, "reason": probe.error}, file_id=f.file_id
                )
            )
        if probe.repaired:
            out.append(IntegrityFlag.make("PDF_REPAIRED", {"file_name": f.name}, file_id=f.file_id))
        if probe.page_count is not None and f.pdf_pages is not None and probe.page_count != f.pdf_pages:
            out.append(
                IntegrityFlag.make(
                    "MANIFEST_ROW_INVALID",
                    {
                        "row": f.row_no,
                        "file_id": f.file_id,
                        "reason": f"pdf_pages = {f.pdf_pages}, а в файле {probe.page_count} стр.",
                    },
                    file_id=f.file_id,
                )
            )
        if probe.page_count is not None and probe.page_count >= self.options.large_document_pages:
            out.append(
                IntegrityFlag.make(
                    "LARGE_DOCUMENT", {"file_name": f.name, "pages": probe.page_count}, file_id=f.file_id
                )
            )
        return out

    def _archive_summary(
        self,
        archive: ManifestFile,
        listing: ArchiveListing,
        files: list[ManifestFile],
        pdf_pages: dict[str, int | None],
        seen_member_sha: dict[str, str],
    ) -> tuple[dict[str, Any], list[IntegrityFlag]]:
        flags: list[IntegrityFlag] = []
        fid = archive.file_id
        if listing.error:
            flags.append(
                IntegrityFlag.make(
                    "FILE_CORRUPTED", {"file_name": archive.name, "reason": listing.error}, file_id=fid
                )
            )
        if listing.encrypted:
            flags.append(IntegrityFlag.make("FILE_ENCRYPTED", {"file_name": archive.name}, file_id=fid))
        if listing.bomb_suspected:
            flags.append(
                IntegrityFlag.make(
                    "ARCHIVE_BOMB_SUSPECTED",
                    {"file_name": archive.name},
                    file_id=fid,
                    note_ru=listing.bomb_reason,
                )
            )
        if listing.too_many_members:
            count = listing.members_declared or len(listing.members)
            flags.append(
                IntegrityFlag.make(
                    "TOO_MANY_FILES",
                    {"count": count, "limit": self.options.limits.max_members},
                    file_id=fid,
                    note_ru="в архиве; перечень усечён",
                )
            )
        drawings = {
            m.index: m.path
            for m in listing.members
            if not m.is_dir
            and not m.problems
            and (
                m.extension in (".dwg", ".dxf")
                or (
                    m.media_type in (filetypes.DWG, filetypes.DXF)
                    and m.extension not in filetypes.IGNORED_EXTENSIONS
                )
            )
        }
        # Only archives of drawings have a PDF twin (97 §2.12); others are context or duplicates.
        twins = (
            link_archive(archive, drawings, files, pdf_pages) if drawings else ArchiveTwins(None, {}, 0, None)
        )
        member_pdfs = {
            m.path.rsplit(".", 1)[0].casefold(): m.path
            for m in listing.members
            if not m.is_dir and m.media_type == filetypes.PDF
        }
        members_json: list[dict[str, Any]] = []
        for m in listing.members:
            if m.is_dir:
                continue
            role, extra, mflags = self._member_role(archive, m, twins.members.get(m.index), seen_member_sha)
            flags.extend(mflags)
            record: dict[str, Any] = {
                "member_id": f"{fid}!{m.path}",
                "path": m.path,
                "name_encoding": m.name_encoding,
                "format_chars_removed": m.format_chars_removed,
                "size": m.size,
                "compressed_size": m.compressed_size,
                "extension": m.extension,
                "media_type": m.media_type,
                "dwg_version": m.dwg_version,
                "dwg_release": m.dwg_release,
                "sha256": m.sha256,
                "encrypted": m.encrypted,
                "role": role,
                "citable": False,
                "flags": sorted({fl.code for fl in mflags}),
                **extra,
            }
            if m.raw_name != m.path:
                record["raw_name"] = m.raw_name
            if m.index in drawings:
                twin_member = member_pdfs.get(m.path.rsplit(".", 1)[0].casefold())
                if twin_member:
                    record["twin_member"] = f"{fid}!{twin_member}"
            members_json.append(record)
        file_members = [m for m in listing.members if not m.is_dir]
        ratio = (
            round(listing.declared_uncompressed / listing.archive_size, 2)
            if listing.archive_size and listing.declared_uncompressed
            else None
        )
        summary = {
            "file_id": fid,
            "name": archive.name,
            "format": listing.format,
            "backend": listing.backend,
            "archive_size": listing.archive_size,
            "members_total": len(file_members),
            "dirs": sum(1 for m in listing.members if m.is_dir),
            "declared_uncompressed": listing.declared_uncompressed,
            "read_bytes": listing.read_bytes,
            "compression_ratio": ratio,
            "encrypted": listing.encrypted,
            "truncated": listing.truncated,
            "bomb_suspected": listing.bomb_suspected,
            "bomb_reason": listing.bomb_reason,
            "error": listing.error,
            "name_encodings": dict(sorted(Counter(m.name_encoding for m in file_members).items())),
            "names_with_format_chars": sum(1 for m in file_members if m.format_chars_removed),
            "media_types": dict(sorted(Counter(str(m.media_type) for m in file_members).items())),
            "dwg_versions": dict(
                sorted(Counter(m.dwg_version for m in file_members if m.dwg_version).items())
            ),
            "roles": dict(sorted(Counter(r["role"] for r in members_json).items())),
            "twin": twins.archive_link.to_json() if twins.archive_link else None,
            "dwg_members": twins.dwg_members,
            "page_offset": twins.page_offset,
            "members": members_json,
        }
        return summary, flags

    def _member_role(
        self,
        archive: ManifestFile,
        m: ArchiveMember,
        twin: Any,
        seen_member_sha: dict[str, str],
    ) -> tuple[str, dict[str, Any], list[IntegrityFlag]]:
        fid = archive.file_id
        member_id = f"{fid}!{m.path}"
        flags: list[IntegrityFlag] = []
        extra: dict[str, Any] = {
            "twin_file_id": None,
            "twin_confidence": None,
            "sheet_number": None,
            "twin_page_hint": None,
            "duplicate_of_file_id": None,
            "duplicate_of_member": None,
        }
        name = m.path.rsplit("/", 1)[-1]
        if m.problems or m.is_link:
            reasons = list(m.problems) + (["ссылка (symlink/hardlink)"] if m.is_link else [])
            flags.append(
                IntegrityFlag.make(
                    "FILENAME_INVALID", file_id=fid, member=member_id, note_ru="; ".join(reasons)
                )
            )
            return ArchiveMemberRole.IGNORED.value, extra, flags
        if filetypes.is_executable(m.media_type or "", m.extension):
            flags.append(
                IntegrityFlag.make(
                    "EMBEDDED_EXECUTABLE", {"file_name": archive.name}, file_id=fid, member=member_id
                )
            )
            return ArchiveMemberRole.IGNORED.value, extra, flags
        if m.read_error:
            flags.append(
                IntegrityFlag.make(
                    "FILE_CORRUPTED",
                    {"file_name": m.path, "reason": m.read_error},
                    file_id=fid,
                    member=member_id,
                )
            )
        if (
            name.casefold() in filetypes.IGNORED_NAMES
            or m.extension in filetypes.IGNORED_EXTENSIONS
            or m.path.startswith("__MACOSX/")
            or name.startswith("._")
        ):
            return ArchiveMemberRole.IGNORED.value, extra, flags
        if m.sha256:
            manifest_ids = self._manifest_sha_index.get(m.sha256)
            if manifest_ids:
                extra["duplicate_of_file_id"] = sorted(manifest_ids)[0]
                return ArchiveMemberRole.DUPLICATE.value, extra, flags
            first = seen_member_sha.get(m.sha256)
            if first is not None:
                extra["duplicate_of_member"] = first
                return ArchiveMemberRole.DUPLICATE.value, extra, flags
            seen_member_sha[m.sha256] = member_id
        if twin is not None:
            extra.update(
                twin_file_id=twin.twin_file_id,
                twin_confidence=twin.confidence,
                sheet_number=twin.sheet_number,
                twin_page_hint=twin.page_hint,
            )
            return ArchiveMemberRole.PDF_TWIN_SOURCE.value, extra, flags
        if m.media_type in (filetypes.PDF, filetypes.DOCX, filetypes.OLE) or m.extension in (
            ".pdf",
            ".docx",
            ".doc",
        ):
            flags.append(
                IntegrityFlag.make(
                    "REGISTRY_FILE_NOT_LISTED",
                    {"file_name": m.path},
                    file_id=fid,
                    member=member_id,
                    note_ru="документ внутри архива: не входит в манифест и не цитируется",
                )
            )
        return ArchiveMemberRole.CONTEXT_ONLY.value, extra, flags

    @staticmethod
    def _run_file(f: ManifestFile, r: ResolvedFile, rec: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "file_id": f.file_id,
            "object_id": f.object_id,
            "sha256": f.sha256,
            "manifest_stage": f.stage,
            "stage_resolved": rec.get("stage_resolved"),
            "local_status": r.local_status.value,
            "sha256_verified": r.sha256_verified,
            "extension": f.extension,
            "pdf_pages": rec.get("pdf_pages"),
            "page_basis": PageBasis.PDF_NATIVE.value if f.is_pdf else None,
            "warnings": rec.get("flags", []),
        }
        return out

    def _counts(
        self,
        files: list[ManifestFile],
        resolved: dict[str, ResolvedFile],
        records: dict[str, dict[str, Any]],
        stages: dict[str, StageResolution],
        archives: list[dict[str, Any]],
        dups: dict[str, list[dict[str, Any]]],
        flags: list[IntegrityFlag],
    ) -> dict[str, Any]:
        status = Counter(r.local_status.value for r in resolved.values())
        pdfs = [f for f in files if f.is_pdf]
        members = [m for a in archives for m in a["members"]]
        loose_dwg = [f for f in files if f.is_drawing]
        member_dwg = [
            m
            for m in members
            if m["role"] != ArchiveMemberRole.IGNORED.value
            and (m["media_type"] == filetypes.DWG or m["extension"] == ".dwg")
        ]
        dwg_versions = Counter(
            [records[f.file_id]["dwg_version"] for f in loose_dwg if records[f.file_id]["dwg_version"]]
            + [m["dwg_version"] for m in member_dwg if m["dwg_version"]]
        )
        docx = [f for f in files if f.is_docx]
        actual_pages = [records[f.file_id]["pdf"]["page_count"] for f in pdfs if records[f.file_id]["pdf"]]
        resolved_stage = Counter(str(records[f.file_id]["stage_resolved"]) for f in files)
        needs_resolution = [f for f in files if f.stage not in ("PD", "RD", "ID")]
        return {
            "files_total": len(files),
            "files_present": status.get(LocalFileStatus.PRESENT.value, 0),
            "files_recovered": status.get(LocalFileStatus.RECOVERED.value, 0),
            "files_missing_on_disk": status.get(LocalFileStatus.MISSING_ON_DISK.value, 0),
            "sha256_verified": sum(1 for r in resolved.values() if r.sha256_verified is True),
            "sha256_unverified": sum(
                1 for r in resolved.values() if r.readable and r.sha256_verified is None
            ),
            "sha256_mismatch": sum(1 for fl in flags if fl.code == "REGISTRY_HASH_MISMATCH"),
            "by_manifest_stage": dict(sorted(Counter(f.stage for f in files).items())),
            "by_stage_resolved": dict(sorted(resolved_stage.items())),
            "by_extension": dict(sorted(Counter(f.extension for f in files).items())),
            "by_section": dict(sorted(Counter(f.section for f in files).items())),
            "by_media_type": dict(
                sorted(Counter(str(records[f.file_id]["media_type"]) for f in files).items())
            ),
            "size_bytes_total": sum(f.size_bytes for f in files),
            "files_over_50mib": sum(1 for f in files if f.size_bytes > UI_FILE_LIMIT),
            "files_over_200mib": sum(1 for f in files if f.size_bytes > UI_PACKAGE_LIMIT),
            "pdf_files": len(pdfs),
            "pdf_pages_manifest_total": sum(f.pdf_pages or 0 for f in pdfs),
            "pdf_pages_actual_total": sum(p for p in actual_pages if p),
            "pdf_probed": len(actual_pages),
            "pdf_page_count_mismatches": sum(
                1
                for f in pdfs
                if records[f.file_id]["pdf"]
                and records[f.file_id]["pdf"]["page_count"] is not None
                and records[f.file_id]["pdf"]["page_count"] != f.pdf_pages
            ),
            "pdf_without_first_page_text": sum(
                1
                for f in pdfs
                if records[f.file_id]["pdf"] and records[f.file_id]["pdf"]["first_page_text_hash"] is None
            ),
            "citable_files": sum(1 for f in files if records[f.file_id]["citable"]),
            "archives": len(archives),
            "archive_members_total": len(members),
            "archive_members_by_role": dict(sorted(Counter(m["role"] for m in members).items())),
            "archive_members_by_extension": dict(
                sorted(Counter(m["extension"] or "(нет)" for m in members).items())
            ),
            "archive_uncompressed_bytes": sum(a["declared_uncompressed"] for a in archives),
            "archive_names_cp866": sum(1 for m in members if m["name_encoding"] == "cp866"),
            "archive_names_with_format_chars": sum(1 for m in members if m["format_chars_removed"]),
            "dwg_total": len(loose_dwg) + len(member_dwg),
            "dwg_loose": len(loose_dwg),
            "dwg_in_archives": len(member_dwg),
            "dwg_with_twin": sum(1 for f in loose_dwg if records[f.file_id]["twin"])
            + sum(1 for m in member_dwg if m.get("twin_file_id")),
            "dwg_versions": dict(sorted(dwg_versions.items())),
            "archives_with_twin": sum(1 for a in archives if a["twin"]),
            "docx_total": len(docx),
            "docx_with_twin": sum(1 for f in docx if records[f.file_id]["twin"]),
            "stage_resolution": {
                "needed": len(needs_resolution),
                "resolved": sum(1 for f in needs_resolution if stages[f.file_id].stage_resolved),
                "unresolved": sum(1 for f in needs_resolution if not stages[f.file_id].stage_resolved),
                "conflicts_with_manifest": sum(1 for s in stages.values() if s.conflict),
            },
            "exact_duplicate_groups": len(dups["exact"]),
            "near_duplicate_groups": len(dups["near"]),
            "first_page_matches": len(dups["first_page_matches"]),
            "integrity_flags": len(flags),
            "integrity_flags_by_code": count_codes(flags),
            "integrity_flags_by_severity": dict(sorted(Counter(fl.severity for fl in flags).items())),
        }


def _utc_now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
