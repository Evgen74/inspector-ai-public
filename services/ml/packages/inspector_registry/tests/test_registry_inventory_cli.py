"""End-to-end: ``inspector-batch inventory`` on a synthetic organizer data root."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from inspector_batch import cli
from inspector_common.contracts.loader import load_enums, validation_errors
from inspector_common.exitcodes import ExitCode
from inspector_registry.report import report_schema, validate_report


@pytest.fixture()
def run(fake, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INSPECTOR_CACHE_ROOT", str(tmp_path / "cache"))

    def _run(*args: str, run_id: str = "t-inv") -> tuple[int, Path]:
        code = cli.main(
            [
                "--data-root",
                str(fake.root),
                "--runs-root",
                str(tmp_path / "runs"),
                "--run-id",
                run_id,
                "--log-format",
                "console",
                "inventory",
                *args,
            ]
        )
        return code, tmp_path / "runs" / run_id

    return _run


def _report(run_dir: Path, object_id: str) -> dict[str, Any]:
    return json.loads((run_dir / "inventory" / f"{object_id}.json").read_text(encoding="utf-8"))


def _files(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["file_id"]: f for f in report["files"]}


def _members(report: dict[str, Any], file_id: str) -> dict[str, dict[str, Any]]:
    archive = next(a for a in report["archives"] if a["file_id"] == file_id)
    return {m["path"]: m for m in archive["members"]}


def test_full_inventory_report(run, build, capsys: pytest.CaptureFixture[str]) -> None:
    code, run_dir = run("--object", build.TRAIN)
    assert code == ExitCode.OK
    assert "файлов 17" in capsys.readouterr().out
    report = _report(run_dir, build.TRAIN)
    assert validate_report(report) == []
    c = report["counts"]
    assert (c["files_total"], c["files_present"], c["files_recovered"], c["files_missing_on_disk"]) == (
        17,
        15,
        1,
        1,
    )
    assert c["by_manifest_stage"] == {"ID": 3, "PD": 4, "RD": 7, "RD_ID_MIXED": 2, "UNKNOWN": 1}
    assert c["stage_resolution"] == {
        "needed": 3,
        "resolved": 2,
        "unresolved": 1,
        "conflicts_with_manifest": 0,
    }
    assert c["archives"] == 3 and c["archives_with_twin"] == 1
    assert (
        c["dwg_total"] == 5 and c["dwg_loose"] == 1 and c["dwg_in_archives"] == 4 and c["dwg_with_twin"] == 4
    )
    assert c["dwg_versions"] == {"AC1021": 1, "AC1024": 1, "AC1027": 1, "AC1032": 2}
    assert c["docx_total"] == 1 and c["docx_with_twin"] == 1
    assert c["archive_names_cp866"] >= 6 and c["archive_names_with_format_chars"] == 1
    assert c["exact_duplicate_groups"] == 1 and c["near_duplicate_groups"] == 1

    files = _files(report)
    assert (
        files["F0002"]["stage_resolved"] == "ID"
        and files["F0002"]["stage"]["source"] == "EXTRACTED_UNCONFIRMED"
    )
    assert files["F0003"]["stage_resolved"] == "RD"
    assert files["F0004"]["stage"]["skipped_reason"] and files["F0004"]["media_type"] is None
    assert files["F0004"]["citable"] is False and files["F0001"]["citable"] is True
    assert (
        files["F0012"]["local_status"] == "MISSING_ON_DISK"
        and "FILE_MISSING_ON_DISK" in files["F0012"]["flags"]
    )
    assert files["F0014"]["local_status"] == "RECOVERED" and files["F0014"]["found_via"] == "sha256_search"
    assert files["F0009"]["dwg_version"] == "AC1024"
    assert files["F0009"]["twin"]["file_id"] == "F0010" and files["F0009"]["twin"]["confidence"] == 0.98
    assert files["F0011"]["twin"]["file_id"] == "F0010"
    assert files["F0001"]["pdf"]["page_count"] == 3 and files["F0001"]["pdf_pages"] == 3

    kzh = _members(report, "F0006")
    sheets = {p: m for p, m in kzh.items() if p.endswith(".dwg")}
    assert [m["role"] for m in sheets.values()] == ["PDF_TWIN_SOURCE"] * 3
    assert sorted(m["twin_page_hint"] for m in sheets.values()) == [3, 4, 5]
    assert all(m["twin_file_id"] == "F0005" and m["member_id"].startswith("F0006!") for m in sheets.values())
    assert kzh["КЖ1/ОБЪ-РД-КЖ1 Лист 3.bak"]["role"] == "IGNORED"
    assert kzh["КЖ1/сАБ.txt"]["name_encoding"] == "cp866"
    archive = next(a for a in report["archives"] if a["file_id"] == "F0006")
    assert archive["twin"]["file_id"] == "F0005" and archive["page_offset"] == 2

    ar = _members(report, "F0007")
    assert (
        ar["АР/Копия АР.pdf"]["role"] == "DUPLICATE"
        and ar["АР/Копия АР.pdf"]["duplicate_of_file_id"] == "F0001"
    )
    assert ar["АР/Приложение.pdf"]["role"] == "CONTEXT_ONLY"
    assert "REGISTRY_FILE_NOT_LISTED" in ar["АР/Приложение.pdf"]["flags"]
    assert all(m["citable"] is False for m in ar.values())

    eom = _members(report, "F0008")
    assert eom["ЭОМ/Лист 1.dwg"]["role"] == "CONTEXT_ONLY"  # no PDF in the RAR's folder
    assert eom["ЭОМ/Лист 1.dwg"]["name_encoding"] == "cp866"

    codes = report["counts"]["integrity_flags_by_code"]
    assert codes["FILE_MISSING_ON_DISK"] == 1 and codes["DUPLICATE_IN_PACKAGE"] == 1
    assert codes["REGISTRY_FILE_NOT_LISTED"] == 2
    assert [f["code"] for f in report["manifest"]["flags"]] == ["EXCLUDED_FILE_REFERENCED"]
    assert report["duplicates"]["exact"][0]["file_ids"] == ["F0015", "F0016"]

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert validation_errors("run_manifest", manifest) == []
    assert manifest["objects"][0]["missing_on_disk"] == ["F0012"]
    assert {f["file_id"] for f in manifest["files"]} == set(files)
    index = json.loads((run_dir / "inventory" / "index.json").read_text(encoding="utf-8"))
    assert [o["object_id"] for o in index["objects"]] == [build.TRAIN]


def test_verify_sha256_turns_altered_file_into_missing(run, build) -> None:
    code, run_dir = run("--object", build.TRAIN, "--verify-sha256")
    assert code == ExitCode.OK
    report = _report(run_dir, build.TRAIN)
    c = report["counts"]
    assert (c["files_present"], c["files_missing_on_disk"], c["sha256_mismatch"]) == (14, 2, 1)
    assert c["sha256_verified"] == 15  # every readable file
    f13 = _files(report)["F0013"]
    assert f13["local_status"] == "MISSING_ON_DISK" and "REGISTRY_HASH_MISMATCH" in f13["flags"]


def test_second_run_uses_cache(run, build) -> None:
    run("--object", build.TRAIN, "--verify-sha256", run_id="first")
    code, run_dir = run("--object", build.TRAIN, run_id="second")
    assert code == ExitCode.OK
    index = json.loads((run_dir / "inventory" / "index.json").read_text(encoding="utf-8"))
    assert index["sha256_hashed_files"] == 0 and index["cache"]["sha256_hits"] > 0
    assert _report(run_dir, build.TRAIN)["counts"]["sha256_verified"] == 15


def test_default_objects_are_train_only_and_all_includes_hidden(run, build) -> None:
    code, run_dir = run(run_id="default")
    assert code == ExitCode.OK
    assert sorted(p.stem for p in (run_dir / "inventory").glob("OBJ-*.json")) == [build.TRAIN, build.TRAIN_B]
    empty = _report(run_dir, build.TRAIN_B)
    assert (
        empty["counts"]["files_total"] == 0 and empty["integrity_flags"][0]["code"] == "MANIFEST_ROW_INVALID"
    )

    code, run_dir = run("--all", run_id="all")
    assert code == ExitCode.OK
    hidden = _report(run_dir, build.HIDDEN)
    assert hidden["hidden_test"] is True and hidden["split"] == "TEST_HIDDEN"
    f = hidden["files"][0]
    assert f["stage_resolved"] == "ID"
    assert f["stage"]["signals"] and not any("match" in s for s in f["stage"]["signals"])  # redacted


def test_hidden_object_allowed_explicitly_and_all_conflicts_with_object(run, build, capsys) -> None:
    code, _ = run("--object", build.HIDDEN, run_id="h")
    assert code == ExitCode.OK
    code, _ = run("--all", "--object", build.TRAIN, run_id="bad")
    assert code == ExitCode.USAGE
    assert "--all" in capsys.readouterr().err


def test_missing_data_root_exits_data_missing(tmp_path: Path) -> None:
    code = cli.main(
        ["--data-root", str(tmp_path / "none"), "--runs-root", str(tmp_path / "runs"), "inventory"]
    )
    assert code == ExitCode.DATA_MISSING


def test_report_schema_enums_match_contracts() -> None:
    defs = report_schema()["$defs"]
    enums = load_enums()
    for name in ("LocalFileStatus", "ManifestStage", "DocStage", "MetaSource", "ArchiveMemberRole"):
        assert defs[name]["enum"] == list(enums[name].codes), name
