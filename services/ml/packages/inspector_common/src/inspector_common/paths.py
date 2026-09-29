"""Repository and data-root discovery.

All data roots are read-only for agents (see CLAUDE.md). Nothing here creates, moves or deletes
anything under the organizer data; only `ensure_dir` creates our own cache/run directories.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Organizer package layout (decoded mirror in data_utf8/, see docs/PLAN.md §10).
PACKAGE_DIR_NAME = "ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0"
DOCUMENTS_DIR_PARTS = ("ХАКАТОН_УЧАСТНИКАМ_ГОТОВО_К_ПЕРЕДАЧЕ", "01_ДОКУМЕНТАЦИЯ")

_REPO_MARKERS = ("packages/contracts/enums.yaml", "services/ml/pyproject.toml")


class RepoRootNotFoundError(RuntimeError):
    """Raised when the monorepo root cannot be located."""


def _looks_like_repo_root(path: Path) -> bool:
    return all((path / marker).is_file() for marker in _REPO_MARKERS)


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the monorepo root.

    Order: ``INSPECTOR_REPO_ROOT`` env var, then the first parent of this file (editable install)
    or of the current working directory that contains the contract markers.
    """
    env = os.environ.get("INSPECTOR_REPO_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if not _looks_like_repo_root(root):
            raise RepoRootNotFoundError(f"INSPECTOR_REPO_ROOT={root} does not contain {_REPO_MARKERS}")
        return root
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if _looks_like_repo_root(candidate):
                return candidate
    raise RepoRootNotFoundError("cannot locate the repository root; set INSPECTOR_REPO_ROOT")


def contracts_dir() -> Path:
    """``packages/contracts`` (override with ``INSPECTOR_CONTRACTS_DIR``)."""
    env = os.environ.get("INSPECTOR_CONTRACTS_DIR")
    return Path(env).expanduser().resolve() if env else repo_root() / "packages" / "contracts"


@dataclass(frozen=True, slots=True)
class DataPaths:
    """Resolved locations of the organizer data (read-only) and of our own writable dirs."""

    data_root: Path
    models_root: Path
    cache_root: Path
    runs_root: Path

    @property
    def package_root(self) -> Path:
        """Organizer answer-free package: data/, evidence_pages/, ТЗ_И_ПРИЛОЖЕНИЯ/, sha256sums.txt."""
        return self.data_root / PACKAGE_DIR_NAME

    @property
    def package_data_dir(self) -> Path:
        return self.package_root / "data"

    @property
    def documents_root(self) -> Path:
        """Base of manifest ``relative_path`` values."""
        return self.data_root.joinpath(*DOCUMENTS_DIR_PARTS)

    @property
    def manifest_path(self) -> Path:
        return self.package_data_dir / "document_manifest.jsonl"

    @property
    def catalog_path(self) -> Path:
        return self.package_data_dir / "parameter_catalog_132.jsonl"

    @property
    def submission_schema_path(self) -> Path:
        return self.package_data_dir / "submission_schema.json"

    @property
    def split_policy_path(self) -> Path:
        return self.package_data_dir / "split_policy.json"

    @property
    def scoring_summary_path(self) -> Path:
        return self.package_data_dir / "scoring_summary_without_answers.json"

    @property
    def train_checks_path(self) -> Path:
        return self.package_data_dir / "public_train_checks.jsonl"

    @property
    def train_groups_path(self) -> Path:
        return self.package_data_dir / "public_train_finding_groups.jsonl"

    @property
    def package_sha256sums_path(self) -> Path:
        return self.package_root / "sha256sums.txt"

    def document_path(self, relative_path: str) -> Path:
        """Absolute path of a manifest ``relative_path`` (no existence check)."""
        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"manifest relative_path must stay inside the documents root: {relative_path!r}")
        return self.documents_root / rel

    def has_package(self) -> bool:
        return self.manifest_path.is_file()


def ensure_dir(path: Path) -> Path:
    """Create one of OUR writable directories (cache, runs). Refuses the organizer data roots."""
    resolved = path.resolve()
    root = repo_root()
    for protected in ("data", "data_utf8", "ТЗ"):
        protected_path = (root / protected).resolve()
        if resolved == protected_path or protected_path in resolved.parents:
            raise PermissionError(f"refusing to create a directory inside read-only data: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
