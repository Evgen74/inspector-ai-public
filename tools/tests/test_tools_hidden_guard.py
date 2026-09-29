from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "hidden_test_guard", REPO / "tools" / "guards" / "hidden_test_guard.py"
)
guard = importlib.util.module_from_spec(_spec)
sys.modules["hidden_test_guard"] = guard
_spec.loader.exec_module(guard)

# Forbidden strings are assembled at runtime so that this test file stays clean for the guard.
NAME = "Реч" + "ников"
FILE_ID = "F0" + "301"


def _tree(tmp_path: Path, content: str, rel: str = "services/ml/x.py") -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "content",
    [
        f"OBJECT = '{NAME} 7-7'",
        f"ids = ['{FILE_ID}']",
        "code = '01-07/" + "22-14'",
        "name = 'ривер " + "парк'",
        NAME.upper(),
    ],
)
def test_guard_flags_hidden_object_mentions(tmp_path: Path, content: str) -> None:
    assert guard.scan(_tree(tmp_path, content))


@pytest.mark.parametrize(
    "content", ["ids = ['F0204', 'F0418', 'F0149', 'F0001']", "OBJ-TYUMENSKAYA-5-GOLD-SEED"]
)
def test_guard_ignores_train_and_excluded_ids(tmp_path: Path, content: str) -> None:
    assert guard.scan(_tree(tmp_path, content)) == []


def test_allow_marker_and_excluded_dirs(tmp_path: Path) -> None:
    assert guard.scan(_tree(tmp_path, f"x = '{NAME}'  # hidden-guard: allow (reason)")) == []
    assert guard.scan(_tree(tmp_path, NAME, rel="tools/prototypes/rech/a.py")) == []
    assert guard.scan(_tree(tmp_path, NAME, rel="docs/analysis/a.md")) == []


def test_manifest_derived_ids(tmp_path: Path) -> None:
    root = _tree(tmp_path, "x = 'F9999'")
    assert guard.scan(root, extra_ids={"F9999"})


def test_repository_is_clean() -> None:
    manifest = REPO / "data_utf8" / "ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0" / "data" / "document_manifest.jsonl"
    assert guard.scan(REPO, guard.hidden_file_ids_from_manifest(manifest)) == []
