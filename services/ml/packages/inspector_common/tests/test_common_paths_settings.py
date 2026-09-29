from __future__ import annotations

from pathlib import Path

import pytest

from inspector_common.paths import contracts_dir, ensure_dir, repo_root
from inspector_common.settings import Settings


def test_repo_root_and_contracts_dir() -> None:
    root = repo_root()
    assert (root / "CLAUDE.md").is_file() or (root / "packages" / "contracts" / "enums.yaml").is_file()
    assert contracts_dir() == root / "packages" / "contracts"
    assert (contracts_dir() / "enums.yaml").is_file()


def test_settings_defaults_are_repo_relative() -> None:
    s = Settings()
    root = repo_root()
    assert s.data_root == root / "data_utf8"
    assert s.models_root == root / ".models"
    assert s.cache_root == root / ".cache"
    assert s.runs_root == root / "runs"
    assert s.ort_provider_list[0] == "CoreMLExecutionProvider"


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("INSPECTOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_LOG_FORMAT", "console")
    s = Settings()
    assert s.data_root == tmp_path.resolve()
    assert s.log_format == "console"
    assert (
        s.paths.manifest_path
        == tmp_path.resolve() / "ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0" / "data" / "document_manifest.jsonl"
    )
    assert not s.paths.has_package()


def test_document_path_rejects_traversal(tmp_path: Path) -> None:
    paths = Settings(data_root=tmp_path).paths
    assert paths.document_path("A/Б/в.pdf").name == "в.pdf"
    with pytest.raises(ValueError):
        paths.document_path("../secret.pdf")
    with pytest.raises(ValueError):
        paths.document_path("/etc/passwd")


def test_ensure_dir_refuses_organizer_data(tmp_path: Path) -> None:
    assert ensure_dir(tmp_path / "cache" / "x").is_dir()
    with pytest.raises(PermissionError):
        ensure_dir(repo_root() / "data_utf8" / "should-not-exist")
    with pytest.raises(PermissionError):
        ensure_dir(repo_root() / "data")
