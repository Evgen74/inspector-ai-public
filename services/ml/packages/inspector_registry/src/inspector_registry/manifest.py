"""The organizers' document_manifest.jsonl as the registry of the batch mode (97 §2.12).

- Rows are validated against ``manifest_row.schema.json``; organizer vocabularies are open
  (unknown values are kept raw and reported, never rejected).
- ``excluded_file_ids`` from split_policy.json are enforced: such rows are dropped at load time and
  every lookup of an excluded id raises ``EXCLUDED_FILE_REFERENCED``.
- Identity is by sha256; ``relative_path`` is NFC-normalised and must stay inside the documents root.
- Hidden-test object ids are read from split_policy.json, never written in code.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import Any

from inspector_common.contracts.loader import load_enums, validation_errors
from inspector_common.errors import InspectorError
from inspector_common.hashing import input_manifest_hash, sha256_file
from inspector_common.paths import DataPaths
from inspector_registry.flags import IntegrityFlag
from inspector_registry.names import nfc

ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar"})
DRAWING_EXTENSIONS = frozenset({".dwg", ".dxf"})
CITABLE_EXTENSIONS = frozenset({".pdf"})  # 97 §2.5: evidence only from manifest PDF pages
# DOCX becomes citable only with page_basis RENDERED_LIBREOFFICE (97 §2.5) — decided by the exporter.

TRAIN_SPLIT = "TRAIN_PUBLIC"
HIDDEN_SPLIT = "TEST_HIDDEN"


class UnknownFileError(KeyError):
    """A file id that is not in the manifest."""


@dataclass(frozen=True, slots=True)
class SplitPolicy:
    train: tuple[str, ...]
    hidden: tuple[str, ...]
    excluded_file_ids: frozenset[str]
    sha256: str | None = None

    @classmethod
    def load(cls, path: Path) -> SplitPolicy:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            train=tuple(raw.get(TRAIN_SPLIT, [])),
            hidden=tuple(raw.get(HIDDEN_SPLIT, [])),
            excluded_file_ids=frozenset(raw.get("excluded_file_ids", [])),
            sha256=sha256_file(path),
        )

    @property
    def objects(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.train, *self.hidden)))

    def split_of(self, object_id: str) -> str | None:
        if object_id in self.train:
            return TRAIN_SPLIT
        if object_id in self.hidden:
            return HIDDEN_SPLIT
        return None

    def is_hidden(self, object_id: str) -> bool:
        return object_id in self.hidden


@dataclass(frozen=True, slots=True)
class ManifestFile:
    """One manifest row (raw row kept for input_manifest_hash)."""

    row_no: int
    file_id: str
    object_id: str
    corpus: str
    dataset_role: str
    split: str
    relative_path: str  # NFC, POSIX separators
    extension: str
    size_bytes: int
    sha256: str
    stage: str  # ManifestStage (raw)
    section: str
    pdf_pages: int | None
    annotation_status: str
    exclusion_reason: str | None
    duplicate_group: str | None
    distribution_status: str
    label_visibility: str
    raw: dict[str, Any] = field(repr=False, compare=False)

    @property
    def name(self) -> str:
        return PurePosixPath(self.relative_path).name

    @property
    def folder(self) -> str:
        return str(PurePosixPath(self.relative_path).parent)

    @property
    def is_pdf(self) -> bool:
        return self.extension == ".pdf"

    @property
    def is_archive(self) -> bool:
        return self.extension in ARCHIVE_EXTENSIONS

    @property
    def is_drawing(self) -> bool:
        return self.extension in DRAWING_EXTENSIONS

    @property
    def is_docx(self) -> bool:
        return self.extension == ".docx"


def _annotation_non_citable() -> frozenset[str]:
    spec = load_enums()["AnnotationStatus"]
    return frozenset(v.code for v in spec.values if v.attrs.get("citable") is False)


def _open_vocabularies() -> dict[str, frozenset[str]]:
    enums = load_enums()
    fields = {
        "section": "ManifestSection",
        "dataset_role": "DatasetRole",
        "annotation_status": "AnnotationStatus",
        "distribution_status": "DistributionStatus",
        "label_visibility": "LabelVisibility",
    }
    return {f: frozenset(enums[e].codes) for f, e in fields.items()}


def _safe_relative_path(value: str) -> str | None:
    unified = nfc(value).replace("\\", "/")
    path = PurePosixPath(unified)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    return str(path)


def _invalid(row_no: int, file_id: str, reason: str) -> IntegrityFlag:
    return IntegrityFlag.make(
        "MANIFEST_ROW_INVALID",
        {"row": row_no, "file_id": file_id or "?", "reason": reason},
        file_id=file_id or None,
    )


class Registry:
    """Manifest + split policy: objects, files, stages, sections; excluded ids enforced."""

    def __init__(
        self,
        files: Iterable[ManifestFile],
        policy: SplitPolicy,
        *,
        flags: Iterable[IntegrityFlag] = (),
        manifest_path: Path | None = None,
        manifest_sha256: str | None = None,
        manifest_checksum_ok: bool | None = None,
        unknown_open_values: dict[str, list[str]] | None = None,
        rows_read: int = 0,
    ) -> None:
        self.policy = policy
        self._files: dict[str, ManifestFile] = {}
        for f in files:
            self._files.setdefault(f.file_id, f)
        self.flags: list[IntegrityFlag] = list(flags)
        self.manifest_path = manifest_path
        self.manifest_sha256 = manifest_sha256
        self.manifest_checksum_ok = manifest_checksum_ok
        self.unknown_open_values = unknown_open_values or {}
        self.rows_read = rows_read
        self.non_citable_annotations = _annotation_non_citable()

    # ── loading ──────────────────────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, paths: DataPaths) -> Registry:
        if not paths.split_policy_path.is_file():
            raise InspectorError("DATA_ROOT_NOT_FOUND", path=str(paths.data_root))
        policy = SplitPolicy.load(paths.split_policy_path)
        return cls.from_manifest(paths.manifest_path, policy, sha256sums_path=paths.package_sha256sums_path)

    @classmethod
    def from_manifest(
        cls, manifest_path: Path, policy: SplitPolicy, *, sha256sums_path: Path | None = None
    ) -> Registry:
        try:
            text = manifest_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InspectorError("MANIFEST_UNREADABLE", path=str(manifest_path), reason=str(exc)) from exc
        manifest_sha = sha256_file(manifest_path)
        checksum_ok = _check_package_sum(sha256sums_path, "data/" + manifest_path.name, manifest_sha)
        flags: list[IntegrityFlag] = []
        if checksum_ok is False:
            flags.append(IntegrityFlag.make("CHECKSUM_MISMATCH", {"file_name": manifest_path.name}))
        files, row_flags, unknown, rows_read = _parse_rows(text, policy)
        flags.extend(row_flags)
        return cls(
            files,
            policy,
            flags=flags,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
            manifest_checksum_ok=checksum_ok,
            unknown_open_values=unknown,
            rows_read=rows_read,
        )

    # ── lookups ──────────────────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._files)

    def __iter__(self) -> Iterator[ManifestFile]:
        return iter(self._files.values())

    def __contains__(self, file_id: object) -> bool:
        return file_id in self._files

    def is_excluded(self, file_id: str) -> bool:
        return file_id in self.policy.excluded_file_ids

    def get(self, file_id: str) -> ManifestFile:
        """The manifest row; excluded ids raise EXCLUDED_FILE_REFERENCED, unknown ids UnknownFileError."""
        if self.is_excluded(file_id):
            raise InspectorError("EXCLUDED_FILE_REFERENCED", file_id=file_id)
        try:
            return self._files[file_id]
        except KeyError:
            raise UnknownFileError(file_id) from None

    def objects(self) -> list[str]:
        """Objects in manifest order (then policy objects without files)."""
        seen = dict.fromkeys(f.object_id for f in self._files.values())
        for obj in self.policy.objects:
            seen.setdefault(obj, None)
        return list(seen)

    def files(self, object_id: str) -> list[ManifestFile]:
        return [f for f in self._files.values() if f.object_id == object_id]

    def stages(self, object_id: str) -> dict[str, int]:
        return dict(Counter(f.stage for f in self.files(object_id)))

    def sections(self, object_id: str) -> dict[str, int]:
        return dict(Counter(f.section for f in self.files(object_id)))

    def split_of(self, object_id: str) -> str | None:
        return self.policy.split_of(object_id)

    def input_manifest_hash(self, object_id: str) -> str:
        return input_manifest_hash(f.raw for f in self.files(object_id))

    @cached_property
    def by_sha256(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for f in self._files.values():
            out[f.sha256].append(f.file_id)
        return dict(out)

    @cached_property
    def duplicate_group_representatives(self) -> dict[str, str]:
        """duplicate_group → kept representative (the lowest non-excluded file id in the group).

        In package v2.0 the non-representative members were removed before distribution
        (F0149 excluded), so a group normally has exactly one row left.
        """
        groups: dict[str, list[str]] = defaultdict(list)
        for f in self._files.values():
            if f.duplicate_group:
                groups[f.duplicate_group].append(f.file_id)
        return {g: sorted(ids)[0] for g, ids in groups.items()}

    # ── citability (organizer rules, independent of what is on our disk) ─────────────────────

    def not_citable_reasons(self, file_id: str) -> list[str]:
        """Why a manifest file may never be cited as evidence (Russian, user-facing); empty = citable.

        Rules (97 §2.5, 93 §2.6): only manifest PDFs; never excluded ids; never GROUND_TRUTH_INDEX;
        only duplicate-group representatives; never rows the organizers excluded from distribution.
        Revision currency (R9) is decided later by the revision resolver.
        """
        if self.is_excluded(file_id):
            return ["файл исключён организаторами (excluded_file_ids)"]
        f = self.get(file_id)
        reasons: list[str] = []
        if f.extension not in CITABLE_EXTENSIONS:
            reasons.append(f"не PDF ({f.extension}): доказательства только по страницам PDF из манифеста")
        if f.annotation_status in self.non_citable_annotations:
            reasons.append(f"служебный файл разметки ({f.annotation_status})")
        if f.exclusion_reason:
            reasons.append(f"исключён организаторами: {f.exclusion_reason}")
        if f.distribution_status != "INCLUDE":
            reasons.append(f"статус распространения {f.distribution_status}")
        if f.duplicate_group and self.duplicate_group_representatives.get(f.duplicate_group) != file_id:
            reasons.append(f"дубликат группы {f.duplicate_group}, цитируется только представитель")
        return reasons

    def is_citable(self, file_id: str) -> bool:
        return not self.not_citable_reasons(file_id)

    def page_in_range(self, file_id: str, page: int) -> bool:
        """R6: 1 ≤ page ≤ manifest pdf_pages for a PDF row."""
        f = self.get(file_id)
        return f.is_pdf and f.pdf_pages is not None and 1 <= page <= f.pdf_pages

    def stage_accepts(self, file_id: str, stage: str, resolved: str | None = None) -> bool:
        """R7: evidence stage vs manifest stage. RD_ID_MIXED accepts RD/ID (or exactly the resolved
        stage when one is known); UNKNOWN never."""
        f = self.get(file_id)
        if f.stage in ("PD", "RD", "ID"):
            return stage == f.stage
        if f.stage == "RD_ID_MIXED":
            return stage == resolved if resolved else stage in ("RD", "ID")
        return False


def _check_package_sum(sums_path: Path | None, rel: str, digest: str) -> bool | None:
    if sums_path is None or not sums_path.is_file():
        return None
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) == 2 and parts[1].strip() == rel:
            return parts[0].strip() == digest
    return None


def _parse_rows(
    text: str, policy: SplitPolicy
) -> tuple[list[ManifestFile], list[IntegrityFlag], dict[str, list[str]], int]:
    flags: list[IntegrityFlag] = []
    files: list[ManifestFile] = []
    vocab = _open_vocabularies()
    unknown: dict[str, set[str]] = defaultdict(set)
    seen_ids: dict[str, int] = {}
    seen_sha: dict[str, ManifestFile] = {}
    rows_read = 0
    for row_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows_read += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            flags.append(_invalid(row_no, "", f"строка не является JSON ({exc.msg})"))
            continue
        if not isinstance(row, dict):
            flags.append(_invalid(row_no, "", "строка не является объектом JSON"))
            continue
        file_id = str(row.get("file_id") or "")
        errors = validation_errors("manifest_row", row)
        if errors:
            flags.append(_invalid(row_no, file_id, "; ".join(errors[:3])))
            continue
        if file_id in policy.excluded_file_ids:
            flags.append(
                IntegrityFlag.make(
                    "EXCLUDED_FILE_REFERENCED",
                    {"file_id": file_id},
                    file_id=file_id,
                    note_ru="строка манифеста с исключённым идентификатором пропущена",
                )
            )
            continue
        if file_id in seen_ids:
            flags.append(
                IntegrityFlag.make(
                    "REGISTRY_DUPLICATE_FILE_ID",
                    {"file_id": file_id, "rows": f"{seen_ids[file_id]}, {row_no}"},
                    file_id=file_id,
                )
            )
            continue
        rel = _safe_relative_path(str(row["relative_path"]))
        if rel is None:
            flags.append(_invalid(row_no, file_id, "relative_path выходит за пределы каталога документов"))
            continue
        seen_ids[file_id] = row_no
        ext = str(row["extension"])
        actual_suffix = PurePosixPath(rel).suffix.lower()
        if actual_suffix != ext:
            flags.append(
                _invalid(row_no, file_id, f"extension {ext} не совпадает с именем файла ({actual_suffix})")
            )
        if (ext == ".pdf") != (row["pdf_pages"] is not None):
            flags.append(_invalid(row_no, file_id, "pdf_pages должен быть задан ровно для PDF"))
        split = policy.split_of(str(row["object_id"]))
        if split is None:
            flags.append(
                _invalid(row_no, file_id, f"объект {row['object_id']} отсутствует в split_policy.json")
            )
        elif split != row["split"]:
            flags.append(
                _invalid(row_no, file_id, f"split {row['split']} противоречит split_policy.json ({split})")
            )
        for fld, known in vocab.items():
            value = str(row[fld])
            if value not in known:
                unknown[fld].add(value)
        mf = ManifestFile(
            row_no=row_no,
            file_id=file_id,
            object_id=str(row["object_id"]),
            corpus=str(row["corpus"]),
            dataset_role=str(row["dataset_role"]),
            split=str(row["split"]),
            relative_path=rel,
            extension=ext,
            size_bytes=int(row["size_bytes"]),
            sha256=str(row["sha256"]),
            stage=str(row["stage"]),
            section=str(row["section"]),
            pdf_pages=row["pdf_pages"],
            annotation_status=str(row["annotation_status"]),
            exclusion_reason=row["exclusion_reason"],
            duplicate_group=row["duplicate_group"],
            distribution_status=str(row["distribution_status"]),
            label_visibility=str(row["label_visibility"]),
            raw=row,
        )
        first = seen_sha.get(mf.sha256)
        if first is not None and not (mf.duplicate_group and mf.duplicate_group == first.duplicate_group):
            flags.append(
                IntegrityFlag.make(
                    "DUPLICATE_IN_PACKAGE",
                    {"file_name": f"{file_id} {mf.name}", "other_name": f"{first.file_id} {first.name}"},
                    file_id=file_id,
                    note_ru=(
                        "совпадает SHA-256 с файлом другого объекта"
                        if first.object_id != mf.object_id
                        else "совпадает SHA-256 внутри объекта"
                    ),
                )
            )
        else:
            seen_sha.setdefault(mf.sha256, mf)
        files.append(mf)
    return files, flags, {k: sorted(v) for k, v in unknown.items()}, rows_read
