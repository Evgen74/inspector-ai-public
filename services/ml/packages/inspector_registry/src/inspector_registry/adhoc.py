"""Ad-hoc package registry for user uploads («загрузка своего комплекта»).

The web product stores uploaded files under ``runs/uploads/<process_id>/incoming/`` and calls

    python -m inspector_registry.adhoc prepare --upload-dir runs/uploads/<pid> --object-name «…» [--registry file]

which (1) unpacks zip/7z/rar archives (libarchive, never ``unrar``), (2) builds a manifest compatible with the
organizers' ``document_manifest.jsonl`` (file_id ``U<8 hex>-0001``…, object_id ``OBJ-UPLOAD-<n>``), and (3) lays out a
self-contained *data root* in ``<upload-dir>/dataroot`` with the same layout as the organizer package
(manifest, split_policy with the single object as TRAIN_PUBLIC, parameter catalog, submission schema).
``inspector-batch --data-root <upload-dir>/dataroot …`` then runs the unchanged engine on it: the organizer
data and the split policy of the real corpora are never touched.

Stage: registry column first; else guessed from folder/file names (П/ПД → PD, РД → RD, ИД/АОСР/исполнит → ID)
and, when cheap, the text layer of the first page (``stages.resolve_stage``); otherwise UNKNOWN (the
inventory step resolves the rest from title-block text).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from inspector_common.hashing import sha256_file
from inspector_common.paths import DOCUMENTS_DIR_PARTS, PACKAGE_DIR_NAME, repo_root

ALLOWED_EXTENSIONS = (".pdf", ".docx", ".xml")
ARCHIVE_EXTENSIONS = (".zip", ".7z", ".rar")
MAX_FILE_BYTES = 500 * 1024 * 1024  # per document, also inside archives (API: the same limits)
MAX_PACKAGE_BYTES = 5 * 1024 * 1024 * 1024
_STAGE_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}
SCHEMA_VERSION = "0.1.0"
_OBJECT_ID_RE = re.compile(r"^OBJ-UPLOAD-[0-9a-f]{8}$")

# Column names accepted in a registry file (case-insensitive, Russian or English).
_NAME_COLUMNS = (
    "file",
    "filename",
    "file_name",
    "name",
    "path",
    "relative_path",
    "файл",
    "имя",
    "имя файла",
    "наименование файла",
    "путь",
)
_STAGE_COLUMNS = ("stage", "стадия", "тип", "раздел документации", "вид документации")
_SECTION_COLUMNS = ("section", "раздел")


def object_id_for(process_id: str) -> str:
    """``OBJ-UPLOAD-<n>``: n = the last 8 hex chars of the process id (the random part of a UUID v7) (unique enough, stable)."""
    n = (re.sub(r"[^0-9a-fA-F]", "", process_id)[-8:].lower()).rjust(8, "0")
    return f"OBJ-UPLOAD-{n}"


def normalize_stage(value: str | None) -> str | None:
    """Map a free-form stage label to PD/RD/ID (None when it says nothing)."""
    if not value:
        return None
    v = unicodedata.normalize("NFC", value).strip().lower()
    if not v:
        return None
    if v in {"pd", "пд", "п", "проект", "проектная документация", "проектная"}:
        return "PD"
    if v in {"rd", "рд", "р", "рабочая документация", "рабочая"}:
        return "RD"
    if v in {"id", "ид", "исполнительная документация", "исполнительная"}:
        return "ID"
    if "исполнит" in v or "аоср" in v:
        return "ID"
    if "рабоч" in v:
        return "RD"
    if "проект" in v:
        return "PD"
    return None


def guess_stage(relative_path: str) -> str | None:
    """Cheap stage guess from folder and file names only."""
    text = unicodedata.normalize("NFC", relative_path).lower()
    parts = [p for p in PurePosixPath(text).parts]
    name = parts[-1] if parts else ""
    folders = parts[:-1]

    def token(s: str, words: tuple[str, ...]) -> bool:
        return any(re.search(rf"(?:^|[\s_.\-()]){re.escape(w)}(?:$|[\s_.\-()0-9])", s) for w in words)

    for s in (*reversed(folders), name):
        if "исполнит" in s or "аоср" in s or token(s, ("ид",)):
            return "ID"
        if "рабоч" in s or token(s, ("рд",)):
            return "RD"
        if "проектн" in s or token(s, ("пд", "п")):
            return "PD"
    return None


def _first_page_text(path: Path) -> str | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pymupdf

        with pymupdf.open(path) as doc:
            if doc.page_count == 0:
                return None
            return doc[0].get_text()[:4000] or None
    except Exception:
        return None


def _pdf_pages(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pymupdf

        with pymupdf.open(path) as doc:
            return int(doc.page_count)
    except Exception:
        return None


@dataclass(slots=True)
class RegistryEntry:
    stage: str | None
    section: str | None


def load_registry(path: Path) -> dict[str, RegistryEntry]:
    """Read a registry CSV / XLSX / JSON into ``{normalized file name or path: entry}``.

    Keys are lower-cased NFC file names and, when the row carries a path, also the full path.
    """
    ext = path.suffix.lower()
    rows: list[dict[str, Any]] = []
    if ext == ".json":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            raw = raw.get("files") or raw.get("items") or [{"file": k, "stage": v} for k, v in raw.items()]
        rows = [r if isinstance(r, dict) else {} for r in raw]
    elif ext in {".xlsx", ".xlsm"}:
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(c or "").strip() for c in next(it, [])]
        for r in it:
            rows.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
    else:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t") if text.strip() else csv.excel
        rows = list(csv.DictReader(text.splitlines(), dialect=dialect))

    def pick(row: dict[str, Any], names: tuple[str, ...]) -> str | None:
        lowered = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
        for n in names:
            v = lowered.get(n)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None

    out: dict[str, RegistryEntry] = {}
    for row in rows:
        name = pick(row, _NAME_COLUMNS)
        if not name:
            continue
        entry = RegistryEntry(
            stage=normalize_stage(pick(row, _STAGE_COLUMNS)), section=pick(row, _SECTION_COLUMNS)
        )
        norm = unicodedata.normalize("NFC", name).replace("\\", "/").strip().lower()
        out[norm] = entry
        out.setdefault(PurePosixPath(norm).name, entry)
    return out


@dataclass(slots=True)
class FileRecord:
    file_id: str
    relative_path: str
    original_name: str
    extension: str
    size_bytes: int
    sha256: str
    stage: str
    stage_source: str
    pdf_pages: int | None
    section: str = "OTHER"
    from_archive: str | None = None
    problems: list[str] = field(default_factory=list)

    def manifest_row(self, object_id: str, corpus: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "file_id": self.file_id,
            "object_id": object_id,
            "corpus": corpus,
            "dataset_role": "UNLABELED_POOL",
            "split": "TRAIN_PUBLIC",
            "relative_path": self.relative_path,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "stage": self.stage,
            "section": self.section,
            "pdf_pages": self.pdf_pages,
            "annotation_status": "UNLABELED",
            "exclusion_reason": None,
            "duplicate_group": None,
            "distribution_status": "INCLUDE",
            "label_visibility": "PUBLIC_TRAIN",
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "name": self.original_name,
            "relative_path": self.relative_path,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "stage": self.stage,
            "stage_source": self.stage_source,
            "pdf_pages": self.pdf_pages,
            "from_archive": self.from_archive,
            "problems": self.problems,
        }


def _unpack_archives(incoming: Path, staging: Path, notes: list[str]) -> list[tuple[Path, str, str | None]]:
    """Return ``[(source_path, relative_path, archive_name)]`` for loose files and archive members."""
    from inspector_registry.archives import extract_member, list_archive

    found: list[tuple[Path, str, str | None]] = []
    for src in sorted(p for p in incoming.rglob("*") if p.is_file()):
        rel = unicodedata.normalize("NFC", src.relative_to(incoming).as_posix())
        ext = src.suffix.lower()
        if ext in ARCHIVE_EXTENSIONS:
            listing = list_archive(src)
            if listing.error:
                notes.append(f"Архив «{src.name}» не удалось прочитать: {listing.error}")
                continue
            # A stage folder with nothing inside (e.g. an empty «Исполнительная документация») is worth saying:
            # otherwise the missing stage looks like a recognition failure.
            file_paths = [m.path for m in listing.files]
            for folder in (m.path.rstrip("/") for m in listing.members if m.is_dir):
                stage = guess_stage(folder + "/x")
                if stage and not any(fp.startswith(folder + "/") for fp in file_paths):
                    notes.append(
                        f"Папка «{folder}» архива «{src.name}» пуста: документов стадии {_STAGE_RU[stage]} в ней нет."
                    )
            for member in listing.files:
                if member.problems or member.encrypted:
                    notes.append(
                        f"Элемент «{member.path}» архива «{src.name}» пропущен: небезопасный путь или шифрование."
                    )
                    continue
                if member.extension.lower() not in ALLOWED_EXTENSIONS:
                    notes.append(
                        f"Элемент «{member.path}» архива «{src.name}» пропущен: формат {member.extension or '—'} не поддерживается."
                    )
                    continue
                if member.size is not None and member.size > MAX_FILE_BYTES:
                    notes.append(
                        f"Элемент «{member.path}» архива «{src.name}» пропущен: больше 500 МБ ({member.size / 1024**2:.1f} МБ)."
                    )
                    continue
                try:
                    out = extract_member(src, member.path, staging / src.stem)
                except Exception as exc:
                    notes.append(f"Элемент «{member.path}» архива «{src.name}» не извлечён: {exc}")
                    continue
                found.append(
                    (out, f"{PurePosixPath(rel).with_suffix('').as_posix()}/{member.path}", src.name)
                )
        elif ext in ALLOWED_EXTENSIONS:
            found.append((src, rel, None))
        else:
            notes.append(f"Файл «{rel}» пропущен: формат {ext or '—'} не поддерживается.")
    return found


_SCORING_SUMMARY = {
    "weights_points": {
        "finding_detection_f1": 60,
        "source_localization_exact_file_page": 15,
        "normalized_value_and_status_accuracy": 15,
        "document_integrity_and_split_handling": 10,
    },
    "critical_miss_gate": "При пропуске любой утверждённой критической контрольной точки итоговый балл ограничивается 59 из 100.",
    "submission_schema": "submission_schema.json",
}


def _write_catalog_from_seed(target: Path) -> None:
    """``parameter_catalog_132.jsonl`` rebuilt from the params seed (``ParamSpec.to_catalog_row``)."""
    from inspector_common.params import load_params

    with target.open("w", encoding="utf-8") as fh:
        for spec in load_params():
            fh.write(json.dumps(spec.to_catalog_row().model_dump(mode="json"), ensure_ascii=False) + "\n")


def _place(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def prepare(
    upload_dir: Path,
    *,
    object_name: str,
    object_id: str,
    registry_path: Path | None = None,
    source_data_root: Path | None = None,
) -> dict[str, Any]:
    """Build manifest + data root for one upload; returns the summary that is also written to ``prepare.json``."""
    if not _OBJECT_ID_RE.match(object_id):
        raise ValueError(f"недопустимый идентификатор объекта: {object_id}")
    incoming = upload_dir / "incoming"
    staging = upload_dir / "unpacked"
    dataroot = upload_dir / "dataroot"
    docs_root = dataroot.joinpath(*DOCUMENTS_DIR_PARTS)
    data_dir = dataroot / PACKAGE_DIR_NAME / "data"
    notes: list[str] = []
    registry = load_registry(registry_path) if registry_path and registry_path.is_file() else {}
    # File ids must be unique across uploads (they are primary keys in the web database): U<8 hex>-<n>.
    file_prefix = "U" + (object_id.rsplit("-", 1)[-1].lower() + "0" * 8)[:8]

    entries = _unpack_archives(incoming, staging, notes)
    records: list[FileRecord] = []
    total = 0
    seen: set[str] = set()
    for src, rel, archive in entries:
        # The corpus folder keeps user-visible names and lets the stage guess use their folders.
        rel_in_corpus = f"{object_name}/{rel}"
        if rel_in_corpus in seen:
            notes.append(f"Файл «{rel}» повторяется и пропущен.")
            continue
        seen.add(rel_in_corpus)
        size = src.stat().st_size
        if size == 0:
            notes.append(f"Файл «{rel}» пустой и пропущен.")
            continue
        total += size
        digest = sha256_file(src)
        reg = registry.get(rel.lower()) or registry.get(PurePosixPath(rel).name.lower())
        stage, source = None, ""
        if reg and reg.stage:
            stage, source = reg.stage, "REGISTRY"
        if not stage:
            g = guess_stage(rel)
            if g:
                stage, source = g, "PATH"
        if not stage:
            text = _first_page_text(src)
            if text:
                from inspector_registry.stages import resolve_stage

                res = resolve_stage("UNKNOWN", rel, text)
                if res.stage_resolved:
                    stage, source = res.stage_resolved, "TITLE_TEXT"
        rec = FileRecord(
            file_id=f"{file_prefix}-{len(records) + 1:04d}",
            relative_path=rel_in_corpus,
            original_name=PurePosixPath(rel).name,
            extension=src.suffix.lower(),
            size_bytes=size,
            sha256=digest,
            stage=stage or "UNKNOWN",
            stage_source=source or "NONE",
            pdf_pages=_pdf_pages(src),
            section=(reg.section if reg and reg.section else "OTHER"),
            from_archive=archive,
        )
        if rec.section not in _sections():
            rec.section = "OTHER"
        if src.suffix.lower() == ".pdf" and rec.pdf_pages is None:
            rec.problems.append("PDF не открывается (повреждён или защищён паролем)")
        records.append(rec)
        _place(src, docs_root / rel_in_corpus)
    if total > MAX_PACKAGE_BYTES:
        notes.append("Суммарный размер распакованного пакета превышает 5 ГБ.")

    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "document_manifest.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.manifest_row(object_id, object_name), ensure_ascii=False) + "\n")
    (data_dir / "split_policy.json").write_text(
        json.dumps(
            {"TRAIN_PUBLIC": [object_id], "TEST_HIDDEN": [], "do_not_release": [], "excluded_file_ids": []},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # Static package files that engine steps read: copied from the organizer package (read-only source).
    src_data = (source_data_root or repo_root() / "data_utf8") / PACKAGE_DIR_NAME / "data"
    for name in (
        "parameter_catalog_132.jsonl",
        "submission_schema.json",
        "scoring_summary_without_answers.json",
    ):
        if (src_data / name).is_file():
            shutil.copy2(src_data / name, data_dir / name)
    # Without the organizer package (a fresh machine, the jury's box) the engine still needs the catalog and the
    # answer schema: both are reproduced from the repository — the catalog from the params seed (identical rows,
    # checked against the organizer file) and the schema from packages/contracts (a byte-identical copy).
    if not (data_dir / "parameter_catalog_132.jsonl").is_file():
        _write_catalog_from_seed(data_dir / "parameter_catalog_132.jsonl")
    if not (data_dir / "submission_schema.json").is_file():
        shutil.copy2(repo_root() / "packages" / "contracts" / "schemas" / "submission.organizer.schema.json",
                     data_dir / "submission_schema.json")  # fmt: skip
    if not (data_dir / "scoring_summary_without_answers.json").is_file():
        # The published scoring weights of the task (no answers): the export's integrity check reads them.
        (data_dir / "scoring_summary_without_answers.json").write_text(
            json.dumps(_SCORING_SUMMARY, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    for name in ("public_train_checks.jsonl", "public_train_finding_groups.jsonl"):
        (data_dir / name).touch()

    counts = {s: sum(1 for r in records if r.stage == s) for s in ("PD", "RD", "ID", "UNKNOWN")}
    for stage in ("PD", "RD", "ID"):
        if records and counts[stage] == 0:
            notes.append(
                f"В комплекте нет документов стадии {_STAGE_RU[stage]}: сравнения, которым она нужна, получат статус "
                f"«документ отсутствует» или «сравнение невозможно»."
            )
    summary = {
        "object_id": object_id,
        "object_name": object_name,
        "dataroot": str(dataroot),
        "files": [r.to_json() for r in records],
        "files_total": len(records),
        "pdf_pages_total": sum(r.pdf_pages or 0 for r in records),
        "bytes_total": total,
        "stages": counts,
        "notes": notes,
        "registry_used": bool(registry),
    }
    (upload_dir / "prepare.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return summary


def _sections() -> frozenset[str]:
    from inspector_common.contracts.loader import load_enums

    return frozenset(load_enums()["ManifestSection"].codes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m inspector_registry.adhoc")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="Распаковать архивы, построить манифест и каталог данных загрузки")
    p.add_argument("--upload-dir", required=True, type=Path)
    p.add_argument("--object-name", required=True)
    p.add_argument("--object-id", required=True)
    p.add_argument("--registry", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        summary = prepare(
            args.upload_dir.resolve(),
            object_name=args.object_name,
            object_id=args.object_id,
            registry_path=args.registry,
        )
    except Exception as exc:  # reported to the API as a failed preparation
        print(f"Ошибка подготовки пакета: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {k: summary[k] for k in ("object_id", "files_total", "pdf_pages_total", "stages", "notes")},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
