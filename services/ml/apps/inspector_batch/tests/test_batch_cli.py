from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspector_batch import cli
from inspector_batch.commands import COMMANDS
from inspector_common.exitcodes import ExitCode
from inspector_common.paths import PACKAGE_DIR_NAME


@pytest.fixture()
def fake_data_root(tmp_path: Path) -> Path:
    """A minimal organizer package with synthetic object ids (no real data needed)."""
    data = tmp_path / "data_utf8" / PACKAGE_DIR_NAME / "data"
    data.mkdir(parents=True)
    (data / "split_policy.json").write_text(
        json.dumps(
            {
                "TRAIN_PUBLIC": ["OBJ-TRAIN-A", "OBJ-TRAIN-B"],
                "TEST_HIDDEN": ["OBJ-HIDDEN-Z"],
                "excluded_file_ids": ["F0999"],
            }
        ),
        encoding="utf-8",
    )
    for name in ("document_manifest.jsonl", "parameter_catalog_132.jsonl", "submission_schema.json"):
        (data / name).write_text("{}\n", encoding="utf-8")
    return tmp_path / "data_utf8"


def _run(fake_data_root: Path, tmp_path: Path, *args: str) -> int:
    return cli.main(
        [
            "--data-root",
            str(fake_data_root),
            "--runs-root",
            str(tmp_path / "runs"),
            "--log-format",
            "console",
            *args,
        ]
    )


def test_help_lists_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    for name in ("inventory", "recognize", "layout", "tables", "compare", "export", "score", "bench", "run"):
        assert name in out


# Commands whose owners have not landed them yet (M1 start: AG-02B's layout, AG-02C's tables, AG-04's
# compare/export). Every other command is implemented and must never answer "not implemented" (exit 69).
# An owner who lands a command removes it from this tuple.
STUB_COMMANDS: tuple[str, ...] = ()  # compare/export (AG-04), layout (AG-02B), tables (AG-02C) landed in M1
IMPLEMENTED_COMMANDS = tuple(sorted(set(COMMANDS) - set(STUB_COMMANDS)))


@pytest.fixture
def stub_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `layout` answer like a stub (exit 69, owner AG-02B): the run-chain tests need an unimplemented
    step and must not depend on which owners have landed their commands (layout landed in M1)."""
    import inspector_layout.batch
    from inspector_common.batch import CommandNotImplementedError

    def stub(args, ctx) -> int:
        raise CommandNotImplementedError("layout", "AG-02B")

    monkeypatch.setattr(inspector_layout.batch, "run_layout", stub)


def _context(tmp_path: Path, run_id: str, command: str) -> dict:
    path = tmp_path / "runs" / run_id / f"run_context.{command}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_stub_and_implemented_commands_cover_the_dispatch_table() -> None:
    assert set(STUB_COMMANDS) <= set(COMMANDS)
    assert set(STUB_COMMANDS) | set(IMPLEMENTED_COMMANDS) == set(COMMANDS)


@pytest.mark.parametrize("command", STUB_COMMANDS)
def test_stub_commands_exit_not_implemented_and_write_run_context(
    command: str, fake_data_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(fake_data_root, tmp_path, "--run-id", f"t-{command}", command)
    assert code == ExitCode.NOT_IMPLEMENTED
    assert "ещё не реализована" in capsys.readouterr().err
    context = _context(tmp_path, f"t-{command}", command)
    assert context["objects"] == ["OBJ-TRAIN-A", "OBJ-TRAIN-B"]  # default: TRAIN objects only, never hidden
    assert context["hidden_run"] is False
    assert len(context["inputs"]["manifest_sha256"]) == 64


@pytest.mark.parametrize("command", IMPLEMENTED_COMMANDS)
def test_implemented_commands_write_run_context_and_never_exit_69(
    command: str, fake_data_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The fake package has one empty manifest row and no documents: each command must answer with its own
    # exit code (OK or DATA_MISSING …), never with the stub answer.
    code = _run(fake_data_root, tmp_path, "--run-id", f"t-{command}", command)
    assert code != ExitCode.NOT_IMPLEMENTED
    assert "ещё не реализована" not in capsys.readouterr().err
    context = _context(tmp_path, f"t-{command}", command)
    assert context["objects"] == ["OBJ-TRAIN-A", "OBJ-TRAIN-B"]
    assert context["hidden_run"] is False
    assert len(context["inputs"]["manifest_sha256"]) == 64


def test_score_is_refused_on_hidden_objects(
    fake_data_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(fake_data_root, tmp_path, "score", "--object", "OBJ-HIDDEN-Z") == ExitCode.HIDDEN_TEST_REFUSED
    assert (
        _run(fake_data_root, tmp_path, "score", "--object", "OBJ-HIDDEN-Z", "--hidden-run")
        == ExitCode.HIDDEN_TEST_REFUSED
    )
    assert _run(fake_data_root, tmp_path, "score", "--all") == ExitCode.HIDDEN_TEST_REFUSED
    assert "скрытой" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_recognize_on_hidden_needs_the_frozen_run_flag(fake_data_root: Path, tmp_path: Path) -> None:
    assert (
        _run(fake_data_root, tmp_path, "recognize", "--object", "OBJ-HIDDEN-Z")
        == ExitCode.HIDDEN_TEST_REFUSED
    )
    assert _run(fake_data_root, tmp_path, "recognize", "--all") == ExitCode.HIDDEN_TEST_REFUSED
    assert not (tmp_path / "runs").exists()
    # With the flag the guard lets it through; the fake manifest row `{}` is invalid, so no PDF to recognise.
    code = _run(
        fake_data_root, tmp_path, "--run-id", "h", "recognize", "--object", "OBJ-HIDDEN-Z", "--hidden-run"
    )
    assert code == ExitCode.DATA_MISSING
    assert _context(tmp_path, "h", "recognize")["hidden_run"] is True


def test_stub_command_on_hidden_with_the_frozen_run_flag_reaches_the_owner(
    fake_data_root: Path, tmp_path: Path
) -> None:
    assert (
        _run(fake_data_root, tmp_path, "compare", "--object", "OBJ-HIDDEN-Z") == ExitCode.HIDDEN_TEST_REFUSED
    )
    # With the flag the guard lets the implemented command through to its owner (AG-04 compare).
    code = _run(fake_data_root, tmp_path, "compare", "--object", "OBJ-HIDDEN-Z", "--hidden-run")
    assert code not in (ExitCode.HIDDEN_TEST_REFUSED, ExitCode.NOT_IMPLEMENTED)


def test_inventory_is_allowed_on_hidden_objects(fake_data_root: Path, tmp_path: Path) -> None:
    assert _run(fake_data_root, tmp_path, "inventory", "--object", "OBJ-HIDDEN-Z") == ExitCode.OK


def test_all_selects_every_split_policy_object_and_is_recorded(fake_data_root: Path, tmp_path: Path) -> None:
    assert _run(fake_data_root, tmp_path, "--run-id", "all", "inventory", "--all") == ExitCode.OK
    context = _context(tmp_path, "all", "inventory")
    assert context["objects"] == ["OBJ-TRAIN-A", "OBJ-TRAIN-B", "OBJ-HIDDEN-Z"]
    assert context["hidden_run"] is False
    reports = sorted(p.stem for p in (tmp_path / "runs" / "all" / "inventory").glob("OBJ-*.json"))
    assert reports == ["OBJ-HIDDEN-Z", "OBJ-TRAIN-A", "OBJ-TRAIN-B"]


def test_all_conflicts_with_object(
    fake_data_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(fake_data_root, tmp_path, "inventory", "--all", "--object", "OBJ-TRAIN-A") == ExitCode.USAGE
    assert "--all" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_unknown_object_is_a_usage_error(fake_data_root: Path, tmp_path: Path) -> None:
    assert _run(fake_data_root, tmp_path, "inventory", "--object", "OBJ-NOPE") == ExitCode.USAGE


def test_missing_data_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tmp_path / "nowhere", tmp_path, "inventory") == ExitCode.DATA_MISSING
    assert "INSPECTOR_DATA_ROOT" in capsys.readouterr().err


def test_every_command_module_implements_the_protocol() -> None:
    import importlib

    for name, spec in COMMANDS.items():
        module = importlib.import_module(spec.module)
        assert callable(getattr(module, f"add_{name}_arguments"))
        assert callable(getattr(module, f"run_{name}"))
        assert spec.owner == module.OWNER


def test_console_entrypoint_keeps_the_exit_code_and_flushes_output(
    fake_data_root: Path, tmp_path: Path
) -> None:
    import subprocess
    import sys

    script = "from inspector_batch.cli import entrypoint; entrypoint()"
    common = [sys.executable, "-c", script, "--runs-root", str(tmp_path / "runs"), "--log-format", "console"]
    ok = subprocess.run(
        [*common, "--data-root", str(fake_data_root), "inventory", "--all"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert ok.returncode == ExitCode.OK
    assert "OBJ-HIDDEN-Z: файлов 0" in ok.stdout  # piped (block-buffered) stdout is flushed before os._exit
    missing = subprocess.run(
        [*common, "--data-root", str(tmp_path / "nowhere"), "inventory"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert missing.returncode == ExitCode.DATA_MISSING
    assert "INSPECTOR_DATA_ROOT" in missing.stderr


def test_every_command_writes_a_valid_artifacts_index(
    fake_data_root: Path, tmp_path: Path, stub_layout: None
) -> None:
    from inspector_common.runlayout import load_artifacts_index

    assert _run(fake_data_root, tmp_path, "--run-id", "idx", "layout") == ExitCode.NOT_IMPLEMENTED
    doc = load_artifacts_index(tmp_path / "runs" / "idx")
    assert doc["commands"] == ["layout"]
    assert {a["kind"] for a in doc["artifacts"]} == {"RUN_CONTEXT"}


def test_run_stops_at_the_first_unimplemented_step_and_names_its_owner(
    fake_data_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], stub_layout: None
) -> None:
    code = _run(fake_data_root, tmp_path, "--run-id", "chain", "run", "--steps", "tables,layout")
    assert code == ExitCode.NOT_IMPLEMENTED
    assert "AG-02B" in capsys.readouterr().err
    run_dir = tmp_path / "runs" / "chain"
    summary = json.loads((run_dir / "pipeline_summary.json").read_text(encoding="utf-8"))
    assert summary["steps"] == [{"step": "layout", "owner": "AG-02B", "status": "not_implemented"}]
    assert _context(tmp_path, "chain", "layout")["parent_command"] == "run"
    assert json.loads((run_dir / "artifacts.json").read_text(encoding="utf-8"))["commands"] == [
        "layout",
        "run",
    ]


def test_run_starts_with_inventory_so_the_run_dir_is_importable(
    fake_data_root: Path, tmp_path: Path, stub_layout: None
) -> None:
    from inspector_batch.pipeline import PIPELINE

    assert PIPELINE[0] == "inventory"  # the web import needs run_manifest.json in the run directory
    code = _run(
        fake_data_root,
        tmp_path,
        "--run-id",
        "imp",
        "run",
        "--object",
        "OBJ-TRAIN-A",
        "--steps",
        "inventory,layout",
    )
    assert code == ExitCode.NOT_IMPLEMENTED
    run_dir = tmp_path / "runs" / "imp"
    summary = json.loads((run_dir / "pipeline_summary.json").read_text(encoding="utf-8"))
    assert [(s["step"], s["status"]) for s in summary["steps"]] == [
        ("inventory", "ok"),
        ("layout", "not_implemented"),
    ]
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "imp"
    assert [o["object_id"] for o in manifest["objects"]] == ["OBJ-TRAIN-A"]
    kinds = {
        a["kind"] for a in json.loads((run_dir / "artifacts.json").read_text(encoding="utf-8"))["artifacts"]
    }
    assert "RUN_MANIFEST" in kinds


def test_run_keep_going_tries_every_step(fake_data_root: Path, tmp_path: Path, stub_layout: None) -> None:
    code = _run(fake_data_root, tmp_path, "--run-id", "kg", "run", "--steps", "layout,tables", "--keep-going")
    assert code == ExitCode.NOT_IMPLEMENTED
    summary = json.loads((tmp_path / "runs" / "kg" / "pipeline_summary.json").read_text(encoding="utf-8"))
    assert [s["step"] for s in summary["steps"]] == ["layout", "tables"]


def test_run_from_step_and_score_reads_this_runs_submission(
    fake_data_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspector_eval.batch

    seen: dict[str, object] = {}

    def fake_score(args, ctx) -> int:
        seen["pred"] = args.pred
        return 0

    monkeypatch.setattr(inspector_eval.batch, "run_score", fake_score)
    code = _run(fake_data_root, tmp_path, "--run-id", "sc", "run", "--from-step", "score")
    assert code == ExitCode.OK
    assert seen["pred"] == tmp_path / "runs" / "sc" / "submission"


def test_run_is_refused_on_hidden_objects(fake_data_root: Path, tmp_path: Path) -> None:
    for extra in ((), ("--hidden-run",)):
        code = _run(fake_data_root, tmp_path, "run", "--object", "OBJ-HIDDEN-Z", *extra)
        assert code == ExitCode.HIDDEN_TEST_REFUSED
    assert _run(fake_data_root, tmp_path, "run", "--all") == ExitCode.HIDDEN_TEST_REFUSED
    assert not (tmp_path / "runs").exists()


def test_run_rejects_unknown_steps(fake_data_root: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        _run(fake_data_root, tmp_path, "run", "--steps", "recognize,deploy")
    assert info.value.code == 2


def test_hidden_run_ignores_admin_matrix_overrides_and_records_it(
    fake_data_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frozen hidden run uses the seed matrix: an overrides file in place is disabled and the run says so;
    a train run reads and records it."""
    overrides = tmp_path / "matrix_overrides.json"
    overrides.write_text(
        json.dumps(
            {"matrix_version": "1.1.1+ovr.9", "overrides": [{"param_code": "AR-040", "min_value": 1.4}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("INSPECTOR_MATRIX_OVERRIDES", str(overrides))
    assert (
        _run(fake_data_root, tmp_path, "--run-id", "t", "inventory", "--object", "OBJ-TRAIN-A") == ExitCode.OK
    )
    train = _context(tmp_path, "t", "inventory")
    assert (
        train["matrix_overrides"]["applied"] is True and train["versions"]["matrix_version"] == "1.1.1+ovr.9"
    )

    _run(fake_data_root, tmp_path, "--run-id", "hh", "compare", "--object", "OBJ-HIDDEN-Z", "--hidden-run")
    hidden = _context(tmp_path, "hh", "compare")
    assert hidden["hidden_run"] is True
    assert hidden["matrix_overrides"]["applied"] is False
    assert hidden["matrix_overrides"]["reason"] == "disabled_by_env"
    assert "ovr" not in hidden["versions"]["matrix_version"]
