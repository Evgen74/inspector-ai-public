"""Run directory layout (run_layout.yaml) and the artifacts.json index."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from inspector_common.contracts import loader
from inspector_common.runlayout import (
    RunLayout,
    artifact_path,
    artifact_specs,
    build_artifacts_index,
    classify,
    load_artifacts_index,
    write_artifacts_index,
)

OBJ = "OBJ-TEST-1"


def test_every_artifact_kind_has_a_spec() -> None:
    assert set(artifact_specs()) == set(loader.load_enums()["ArtifactKind"].codes)


@pytest.mark.parametrize(
    ("kind", "fields", "expected"),
    [
        ("PAGE_TOKENS", {"file_id": "F0201", "page": 17}, "tokens/F0201/p00017.json.gz"),
        ("LAYOUT", {"file_id": "F0202"}, "layout/F0202.json"),
        ("TABLES", {"file_id": "F0201"}, "tables/F0201.json"),
        ("FINDINGS", {"object_id": OBJ}, f"findings/{OBJ}.jsonl"),
        ("FINDING_GROUPS", {"object_id": OBJ}, f"findings/{OBJ}.groups.jsonl"),
        ("PROTOCOL_JSON", {"object_id": OBJ}, f"protocol/{OBJ}.json"),
        ("SUBMISSION", {"object_id": OBJ}, f"submission/{OBJ}.json"),
        ("SUBMISSION_STRICT", {"object_id": OBJ}, f"submission-strict/{OBJ}.json"),
        ("SUBMISSION_SIDECAR", {"object_id": OBJ}, f"submission/{OBJ}.sidecar.json"),
        ("RUN_CONTEXT", {"command": "layout"}, "run_context.layout.json"),
    ],
)
def test_paths_render_and_classify_back(kind: str, fields: dict, expected: str) -> None:
    assert artifact_path(kind, **fields) == expected
    spec, values = classify(expected)
    assert spec.kind == kind
    for key, value in fields.items():
        assert values["page05" if key == "page" else key] == (f"{value:05d}" if key == "page" else value)


def test_most_specific_template_wins() -> None:
    assert classify(f"submission/{OBJ}.sidecar.json")[0].kind == "SUBMISSION_SIDECAR"
    assert classify(f"findings/{OBJ}.groups.jsonl")[0].kind == "FINDING_GROUPS"
    assert classify("inventory/index.json")[0].kind == "INVENTORY_INDEX"
    assert classify("notes/whatever.txt") is None


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".."])
def test_unsafe_values_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        artifact_path("LAYOUT", file_id=bad)


def test_missing_fields_and_page_zero() -> None:
    with pytest.raises(KeyError):
        artifact_path("LAYOUT")
    with pytest.raises(ValueError):
        artifact_path("PAGE_TOKENS", file_id="F0001", page=0)
    with pytest.raises(KeyError):
        artifact_path("NOT_A_KIND")


def _populate(run_dir: Path) -> None:
    layout = RunLayout(run_dir)
    for page in (1, 2, 3):
        with gzip.open(layout.ensure_parent("PAGE_TOKENS", file_id="F0001", page=page), "wt") as fh:
            fh.write("{}")
    layout.ensure_parent("LAYOUT", file_id="F0001").write_text("{}", encoding="utf-8")
    groups = layout.ensure_parent("FINDING_GROUPS", object_id=OBJ)
    groups.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    layout.ensure_parent("SUBMISSION", object_id=OBJ).write_text("{}", encoding="utf-8")
    layout.ensure_parent("SUBMISSION_SIDECAR", object_id=OBJ).write_text("{}", encoding="utf-8")
    (run_dir / "run_context.layout.json").write_text("{}", encoding="utf-8")
    (run_dir / "scratch.log").write_text("ignored", encoding="utf-8")


def test_index_describes_known_files_only(tmp_path: Path) -> None:
    _populate(tmp_path)
    doc = build_artifacts_index(tmp_path, "run-1", [OBJ], ["layout"], {"F0001": OBJ})
    assert loader.validation_errors("run_artifacts", doc) == []
    kinds = {a["kind"]: a for a in doc["artifacts"]}
    assert set(kinds) == {"LAYOUT", "FINDING_GROUPS", "SUBMISSION", "SUBMISSION_SIDECAR", "RUN_CONTEXT"}
    assert kinds["FINDING_GROUPS"]["records"] == 2
    assert kinds["LAYOUT"]["object_id"] == OBJ and kinds["LAYOUT"]["schema_name"] == "layout_artifacts"
    assert kinds["RUN_CONTEXT"]["producer"]["command"] == "layout"
    assert doc["page_tokens"] == [
        {
            "file_id": "F0001",
            "dir": "tokens/F0001",
            "pages": 3,
            "size_bytes": doc["page_tokens"][0]["size_bytes"],
            "object_id": OBJ,
        }
    ]


def test_write_is_atomic_valid_and_accumulates_commands(tmp_path: Path) -> None:
    _populate(tmp_path)
    write_artifacts_index(tmp_path, "run-1", [OBJ], command="layout")
    target = write_artifacts_index(tmp_path, "run-1", [OBJ], command="tables")
    doc = load_artifacts_index(tmp_path)
    assert doc["commands"] == ["layout", "tables"]
    assert not any(p.name.startswith(".artifacts.") for p in tmp_path.iterdir())
    assert "artifacts.json" not in {a["path"] for a in json.loads(target.read_text())["artifacts"]}
