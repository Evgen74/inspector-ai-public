"""`inspector-batch compare` / `export` through the CLI (run directory, artifacts index, sidecar, guards)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from inspector_batch import cli
from inspector_common.contracts.loader import validation_errors
from inspector_common.exitcodes import ExitCode
from inspector_compare import batch

TYUMEN = "OBJ-TYUMENSKAYA-5-GOLD-SEED"


def _run(runs: Path, *args: str, data_root: Path | None = None) -> int:
    argv = ["--runs-root", str(runs), "--log-format", "console", "--log-level", "WARNING"]
    if data_root is not None:
        argv += ["--data-root", str(data_root)]
    return cli.main([*argv, *args])


def test_owner_and_hooks() -> None:
    assert batch.OWNER == "AG-04"
    for name in ("compare", "export"):
        assert callable(getattr(batch, f"add_{name}_arguments"))
        assert callable(getattr(batch, f"run_{name}"))


@pytest.mark.data
def test_compare_export_on_the_fixture(
    tmp_path: Path, data_paths: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    run = ["--run-id", "ag04-t"]
    assert _run(runs, *run, "compare", "--object", TYUMEN, "--fixture", "tyumen") == ExitCode.OK
    assert _run(runs, *run, "export", "--object", TYUMEN, "--protocol-formats", "json,docx") == ExitCode.OK
    out = capsys.readouterr().out
    assert "VIOLATION_PRESENT 10" in out and "R1–R14 пройдены" in out
    run_dir = runs / "ag04-t"
    index = json.loads((run_dir / "artifacts.json").read_text(encoding="utf-8"))
    kinds = {a["kind"] for a in index["artifacts"]}
    assert {
        "FINDING_GROUPS",
        "FINDINGS",
        "SUBMISSION",
        "SUBMISSION_STRICT",
        "SUBMISSION_SIDECAR",
        "PROTOCOL_JSON",
        "PROTOCOL_DOCX",
    } <= kinds
    assert index["commands"] == ["compare", "export"]
    sidecar = json.loads((run_dir / "submission" / f"{TYUMEN}.sidecar.json").read_text(encoding="utf-8"))
    assert validation_errors("submission_sidecar", sidecar) == []
    assert set(sidecar["stage_config_hashes"]) == {"compare", "export"}
    assert sidecar["objects"][0]["checks_total"] == 140
    protocol = json.loads((run_dir / "protocol" / f"{TYUMEN}.json").read_text(encoding="utf-8"))
    assert validation_errors("protocol", protocol) == []
    assert protocol["appendix2"]["section4_critical"]["count"] == 3
    assert protocol["appendix2"]["section6_ai_suspicions"]["count"] == 1
    # negatives off → the 10 gold rows only
    assert (
        _run(runs, *run, "export", "--object", TYUMEN, "--emit-negatives", "none", "--no-protocol")
        == ExitCode.OK
    )
    strict = json.loads((run_dir / "submission-strict" / f"{TYUMEN}.json").read_text(encoding="utf-8"))
    assert len(strict["checks"]) == 10


@pytest.mark.data
def test_export_without_compare_is_data_missing(
    tmp_path: Path, data_paths: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path / "runs", "--run-id", "x", "export", "--object", TYUMEN) == ExitCode.DATA_MISSING
    assert "сначала выполните" in capsys.readouterr().err


@pytest.mark.data
def test_fixture_is_refused_on_the_hidden_object(tmp_path: Path, data_paths: Any) -> None:
    policy = json.loads(data_paths.split_policy_path.read_text(encoding="utf-8"))
    hidden = policy["TEST_HIDDEN"][0]
    runs = tmp_path / "runs"
    assert _run(runs, "compare", "--object", hidden, "--fixture", "tyumen") == ExitCode.HIDDEN_TEST_REFUSED
    code = _run(runs, "--run-id", "h", "compare", "--object", hidden, "--hidden-run", "--fixture", "tyumen")
    assert code == ExitCode.USAGE
    assert not list((runs / "h").glob("findings/*"))


@pytest.mark.data
def test_bad_config_is_a_usage_error(tmp_path: Path, data_paths: Any) -> None:
    bad = tmp_path / "cfg.json"
    bad.write_text(json.dumps({"hedge": {"budget_share": 3}}), encoding="utf-8")
    assert _run(tmp_path / "runs", "compare", "--object", TYUMEN, "--config", str(bad)) == ExitCode.USAGE
