"""file_id → local PDF, through the manifest registry (inspector_registry), train objects only.

Refusals (error codes of packages/contracts/errors.yaml):
- unknown file id → FILE_NOT_FOUND;
- excluded by the organizers → EXCLUDED_FILE_REFERENCED (from the registry);
- an object outside TRAIN_PUBLIC (split_policy.json; hidden-test integrity, 97 §2.17) → HIDDEN_TEST_ACCESS_DENIED;
- not a PDF, or missing on disk → FILE_NOT_RENDERABLE.
The bytes are the manifest's (the resolver finds them by path, recovery ledger or sha256); files are never written.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from inspector_common.errors import InspectorError
from inspector_common.paths import DataPaths
from inspector_common.settings import Settings, get_settings


@dataclass(frozen=True, slots=True)
class ResolvedPdf:
    file_id: str
    object_id: str
    path: Path
    sha256: str
    pdf_pages: int | None


class FileResolver(Protocol):
    def resolve(self, file_id: str) -> ResolvedPdf: ...


TRAIN_SPLIT = "TRAIN_PUBLIC"

# Uploaded objects (apps/api module upload): file ids `U<8hex>-<n>`, object `OBJ-UPLOAD-<8hex>`, data root
# `<runs root>/uploads/<process id ending in the 8 hex>/dataroot` with its own manifest and split policy.
UPLOAD_FILE_ID = re.compile(r"^U([0-9a-f]{8})-\d+$")


class RegistryFileResolver:
    """Loads the registry once (lazily) and resolves file ids; results are cached per process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._registry = None
        self._resolver = None
        self._cache: dict[str, ResolvedPdf] = {}
        self._uploads: dict[str, tuple] = {}

    def _upload_context(self, suffix: str):
        """(registry, resolver, allowed root) of an uploaded object, or None; never leaves runs/uploads."""
        hit = self._uploads.get(suffix)
        if hit is not None:
            return hit
        from inspector_registry.cache import RegistryCache
        from inspector_registry.manifest import Registry
        from inspector_registry.resolver import PathResolver

        settings = self._settings or get_settings()
        uploads = (settings.paths.runs_root / "uploads").resolve()
        if not uploads.is_dir():
            return None
        for proc in sorted(uploads.glob(f"*{suffix}")):
            proc = proc.resolve()
            if proc.parent != uploads or not (proc / "dataroot").is_dir():
                continue
            paths = DataPaths(
                data_root=proc / "dataroot",
                models_root=settings.paths.models_root,
                cache_root=settings.paths.cache_root,
                runs_root=settings.paths.runs_root,
            )
            if not paths.manifest_path.is_file() or not paths.split_policy_path.is_file():
                continue
            registry = Registry.load(paths)
            cache = RegistryCache.at(settings.cache_root) if settings.cache_root else RegistryCache(None)
            ctx = (registry, PathResolver(registry, paths, cache), proc)
            self._uploads[suffix] = ctx
            return ctx
        return None

    def _open(self) -> None:
        if self._registry is None:
            from inspector_registry.api import open_registry

            self._registry, self._resolver = open_registry(self._settings)

    def resolve(self, file_id: str) -> ResolvedPdf:
        from inspector_registry.manifest import UnknownFileError

        with self._lock:
            hit = self._cache.get(file_id)
            if hit is not None and hit.path.is_file():
                return hit
            registry, resolver, allowed = None, None, None
            upload = UPLOAD_FILE_ID.match(file_id)
            if upload:
                ctx = self._upload_context(upload.group(1))
                if ctx is not None:
                    registry, resolver, allowed = ctx
            if registry is None:
                self._open()
                assert self._registry is not None and self._resolver is not None
                registry, resolver = self._registry, self._resolver
            try:
                row = registry.get(file_id)
            except UnknownFileError:
                raise InspectorError("FILE_NOT_FOUND", file_id=file_id) from None
            if registry.split_of(row.object_id) != TRAIN_SPLIT:
                raise InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id=row.object_id)
            if not row.is_pdf:
                raise InspectorError(
                    "FILE_NOT_RENDERABLE",
                    file_id=file_id,
                    reason=f"это не PDF ({row.extension or 'без расширения'})",
                )
            resolved = resolver.resolve(row, verify=False)
            if resolved.path is not None and allowed is not None:
                real = resolved.path.resolve()
                if allowed != real and allowed not in real.parents:
                    raise InspectorError(
                        "FILE_NOT_RENDERABLE", file_id=file_id, reason="файл вне каталога загрузки"
                    )
            if not resolved.readable or resolved.path is None:
                raise InspectorError(
                    "FILE_NOT_RENDERABLE", file_id=file_id, reason="файл отсутствует на диске"
                )
            result = ResolvedPdf(file_id, row.object_id, resolved.path, row.sha256, row.pdf_pages)
            self._cache[file_id] = result
            return result
