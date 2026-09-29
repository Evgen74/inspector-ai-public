"""Manifest file → local path, LocalFileStatus and lazy sha256 verification (97 §2.7, §2.12).

Resolution order for one manifest row:

1. ``<documents root>/<relative_path>`` (NFC), then the NFD spelling, then a per-component
   NFC + casefold match against the directory listing (names on disk may be decomposed, or a
   case-insensitive volume may have changed case).
2. When the file is absent or its bytes differ from the manifest, look for the same sha256
   elsewhere: the recovery ledger (``<data root>/_recovered_files.txt``, lines «F0015<TAB>path»),
   the recovery directories (``<repo>/data_recovered`` by default) and files under the documents
   root that no manifest row claims, restricted to files of the manifest size.

Status (LocalFileStatus, never MISSING_DOCUMENT):
- PRESENT: at the manifest path, size matches, sha256 matches when verified;
- RECOVERED: bytes identical to the manifest, but restored by us (ledger) or found elsewhere by sha256;
- MISSING_ON_DISK: nothing with the manifest bytes is available locally (absent, or altered —
  an altered file carries REGISTRY_HASH_MISMATCH next to it).

sha256 is computed lazily and cached by path + size + mtime (``RegistryCache``).
"""

from __future__ import annotations

import os
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from inspector_common.contracts.enums import LocalFileStatus
from inspector_common.hashing import sha256_file, short
from inspector_common.paths import DataPaths
from inspector_registry.cache import RegistryCache
from inspector_registry.flags import IntegrityFlag
from inspector_registry.manifest import ManifestFile, Registry
from inspector_registry.names import nfc

LEDGER_NAME = "_recovered_files.txt"


@dataclass(slots=True)
class ResolvedFile:
    file_id: str
    object_id: str
    manifest_path: Path  # where the manifest says the file is
    path: Path | None  # where the manifest bytes actually are (None when missing)
    local_status: LocalFileStatus
    found_via: str  # "manifest_path" | "normalized_name" | "recovery_ledger" | "sha256_search" | "not_found"
    size_on_disk: int | None = None
    mtime_ns: int | None = None
    sha256_verified: bool | None = None  # None = not checked yet (size matched)
    sha256_actual: str | None = None
    flags: list[IntegrityFlag] = field(default_factory=list)

    @property
    def readable(self) -> bool:
        return self.path is not None and self.local_status is not LocalFileStatus.MISSING_ON_DISK


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return st.st_size, st.st_mtime_ns


class PathResolver:
    """Resolves manifest rows to local files. Never writes under the data roots."""

    def __init__(
        self,
        registry: Registry,
        paths: DataPaths,
        cache: RegistryCache | None = None,
        *,
        recovery_dirs: Iterable[Path] | None = None,
        hash_workers: int = 4,
    ) -> None:
        self.registry = registry
        self.paths = paths
        self.cache = cache or RegistryCache(None)
        root = paths.data_root.parent
        self.recovery_dirs = (
            [Path(p) for p in recovery_dirs] if recovery_dirs is not None else [root / "data_recovered"]
        )
        self.hash_workers = max(1, hash_workers)
        self._ledger: dict[str, Path] | None = None
        self._listing_cache: dict[Path, dict[str, str]] = {}
        self._unclaimed_by_size: dict[int, list[Path]] | None = None
        self.hashed_bytes = 0
        self.hashed_files = 0

    # ── ledger and listings ──────────────────────────────────────────────────────────────────

    @property
    def ledger(self) -> dict[str, Path]:
        """file_id → path from the recovery ledger (empty when there is none)."""
        if self._ledger is None:
            self._ledger = {}
            ledger = self.paths.data_root / LEDGER_NAME
            if ledger.is_file():
                for line in ledger.read_text(encoding="utf-8").splitlines():
                    parts = line.split("\t")
                    if (
                        len(parts) >= 2
                        and len(parts[0]) == 5
                        and parts[0].startswith("F")
                        and parts[0][1:].isdigit()
                    ):
                        self._ledger[parts[0]] = self._ledger_path(parts[1].strip())
        return self._ledger

    def _ledger_path(self, value: str) -> Path:
        p = Path(nfc(value))
        if p.is_absolute():
            return p
        for base in (self.paths.data_root.parent, self.paths.data_root, self.paths.documents_root):
            candidate = base / p
            if candidate.exists():
                return candidate
        return self.paths.data_root.parent / p

    def _listing(self, directory: Path) -> dict[str, str]:
        """NFC-casefolded name → real name for one directory (cached)."""
        cached = self._listing_cache.get(directory)
        if cached is None:
            try:
                names = os.listdir(directory)
            except OSError:
                names = []
            cached = {}
            for name in names:
                cached.setdefault(nfc(name).casefold(), name)
            self._listing_cache[directory] = cached
        return cached

    def _find_normalized(self, relative_path: str) -> Path | None:
        current = self.paths.documents_root
        for part in relative_path.split("/"):
            real = self._listing(current).get(nfc(part).casefold())
            if real is None:
                return None
            current = current / real
        return current if current.is_file() else None

    def locate(self, f: ManifestFile) -> tuple[Path, str] | None:
        """The on-disk path at the manifest location (any Unicode normalisation or case)."""
        direct = self.paths.documents_root / f.relative_path
        if direct.is_file():
            return direct, "manifest_path"
        nfd = self.paths.documents_root / unicodedata.normalize("NFD", f.relative_path)
        if nfd.is_file():
            return nfd, "normalized_name"
        found = self._find_normalized(f.relative_path)
        if found is not None:
            return found, "normalized_name"
        return None

    # ── hashing ──────────────────────────────────────────────────────────────────────────────

    def sha256_of(self, path: Path, size: int, mtime_ns: int) -> str:
        cached = self.cache.get_sha256(path, size, mtime_ns)
        if cached is not None:
            return cached
        digest = sha256_file(path)
        self.hashed_bytes += size
        self.hashed_files += 1
        self.cache.put_sha256(path, size, mtime_ns, digest)
        return digest

    def cached_sha256(self, path: Path, size: int, mtime_ns: int) -> str | None:
        return self.cache.get_sha256(path, size, mtime_ns)

    def _unclaimed_files(self) -> dict[int, list[Path]]:
        """Files under the documents root and the recovery dirs that no manifest row points to."""
        if self._unclaimed_by_size is None:
            claimed: set[str] = set()
            for f in self.registry:
                located = self.locate(f)
                if located is not None:
                    claimed.add(nfc(str(located[0])).casefold())
            by_size: dict[int, list[Path]] = defaultdict(list)
            roots = [self.paths.documents_root, *self.recovery_dirs]
            for root in roots:
                if not root.is_dir():
                    continue
                for dirpath, _dirs, files in os.walk(root):
                    for name in files:
                        p = Path(dirpath) / name
                        if nfc(str(p)).casefold() in claimed:
                            continue
                        st = _stat(p)
                        if st is not None:
                            by_size[st[0]].append(p)
            self._unclaimed_by_size = dict(by_size)
        return self._unclaimed_by_size

    def _search_by_sha256(self, f: ManifestFile) -> Path | None:
        candidates: list[Path] = []
        ledger_path = self.ledger.get(f.file_id)
        if ledger_path is not None:
            candidates.append(ledger_path)
        candidates.extend(self._unclaimed_files().get(f.size_bytes, []))
        for candidate in candidates:
            st = _stat(candidate)
            if st is None or st[0] != f.size_bytes:
                continue
            if self.sha256_of(candidate, *st) == f.sha256:
                return candidate
        return None

    # ── resolution ───────────────────────────────────────────────────────────────────────────

    def resolve(self, f: ManifestFile, *, verify: bool = False) -> ResolvedFile:
        """Resolve one row. ``verify`` computes sha256 when the cache has no digest for the file."""
        manifest_path = self.paths.documents_root / f.relative_path
        located = self.locate(f)
        altered_flag: IntegrityFlag | None = None
        if located is not None:
            path, via = located
            st = _stat(path)
            assert st is not None
            size, mtime_ns = st
            digest: str | None = None
            if size != f.size_bytes or verify:
                digest = self.sha256_of(path, size, mtime_ns)
            else:
                digest = self.cached_sha256(path, size, mtime_ns)
            if digest is None or digest == f.sha256:
                status = LocalFileStatus.RECOVERED if f.file_id in self.ledger else LocalFileStatus.PRESENT
                return ResolvedFile(
                    file_id=f.file_id,
                    object_id=f.object_id,
                    manifest_path=manifest_path,
                    path=path,
                    local_status=status,
                    found_via="recovery_ledger" if status is LocalFileStatus.RECOVERED else via,
                    size_on_disk=size,
                    mtime_ns=mtime_ns,
                    sha256_verified=None if digest is None else True,
                    sha256_actual=digest,
                )
            altered_flag = IntegrityFlag.make(
                "REGISTRY_HASH_MISMATCH",
                {"file_name": f.name, "expected_short": short(f.sha256), "actual_short": short(digest)},
                file_id=f.file_id,
                note_ru=f"размер на диске {size} байт, в манифесте {f.size_bytes}"
                if size != f.size_bytes
                else "размер совпадает, содержимое отличается",
            )
        recovered = self._search_by_sha256(f)
        if recovered is not None:
            st = _stat(recovered)
            assert st is not None
            flags = [altered_flag] if altered_flag else []
            return ResolvedFile(
                file_id=f.file_id,
                object_id=f.object_id,
                manifest_path=manifest_path,
                path=recovered,
                local_status=LocalFileStatus.RECOVERED,
                found_via="recovery_ledger" if recovered == self.ledger.get(f.file_id) else "sha256_search",
                size_on_disk=st[0],
                mtime_ns=st[1],
                sha256_verified=True,
                sha256_actual=f.sha256,
                flags=flags,
            )
        flags = [altered_flag] if altered_flag else []
        flags.append(
            IntegrityFlag.make(
                "FILE_MISSING_ON_DISK",
                {"file_id": f.file_id, "relative_path": f.relative_path},
                file_id=f.file_id,
            )
        )
        return ResolvedFile(
            file_id=f.file_id,
            object_id=f.object_id,
            manifest_path=manifest_path,
            path=None,
            local_status=LocalFileStatus.MISSING_ON_DISK,
            found_via="not_found",
            flags=flags,
        )

    def resolve_many(self, files: Iterable[ManifestFile], *, verify: bool = False) -> list[ResolvedFile]:
        """Resolve rows; with ``verify`` the uncached digests are computed in a thread pool first."""
        files = list(files)
        if verify:
            todo: list[tuple[Path, int, int]] = []
            for f in files:
                located = self.locate(f)
                if located is None:
                    continue
                st = _stat(located[0])
                if st is not None and self.cached_sha256(located[0], *st) is None:
                    todo.append((located[0], *st))
            if todo:
                with ThreadPoolExecutor(max_workers=self.hash_workers) as pool:
                    digests = list(pool.map(lambda t: sha256_file(t[0]), todo))
                for (path, size, mtime_ns), digest in zip(todo, digests, strict=True):
                    self.hashed_bytes += size
                    self.hashed_files += 1
                    self.cache.put_sha256(path, size, mtime_ns, digest)
        resolved = [self.resolve(f, verify=verify) for f in files]
        _flag_shared_inodes(files, resolved)
        return resolved


def _flag_shared_inodes(files: list[ManifestFile], resolved: list[ResolvedFile]) -> None:
    """Two rows with different manifest sha256 resolving to the same file (e.g. names merged by a
    case-insensitive volume) — at most one of them can be right."""
    by_inode: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, r in enumerate(resolved):
        if r.path is None:
            continue
        try:
            st = r.path.stat()
        except OSError:
            continue
        by_inode[(st.st_dev, st.st_ino)].append(index)
    for indexes in by_inode.values():
        if len({files[i].sha256 for i in indexes}) < 2:
            continue
        ids = ", ".join(files[i].file_id for i in indexes)
        for i in indexes:
            resolved[i].flags.append(
                IntegrityFlag.make(
                    "REGISTRY_AMBIGUOUS_MATCH",
                    {"row": files[i].row_no, "files": ids},
                    file_id=files[i].file_id,
                    note_ru="несколько строк манифеста с разными SHA-256 указывают на один файл на диске",
                )
            )
