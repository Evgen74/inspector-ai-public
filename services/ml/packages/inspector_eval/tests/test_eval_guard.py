"""Hidden-test guard: nothing about a TEST_HIDDEN object without --hidden-final AND a frozen run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspector_common.contracts.loader import contracts_dir
from inspector_eval.data import SplitPolicy
from inspector_eval.guard import HiddenAccessRefusedError, check_access, git_tag_exists, load_frozen_run


@pytest.fixture()
def policy(h) -> SplitPolicy:
    return SplitPolicy.from_dict(h.SPLIT_POLICY)


def _run_manifest(tmp_path: Path, *, freeze_tag: str | None, object_id: str = "OBJ-Z") -> Path:
    example = contracts_dir() / "examples" / "run_manifest" / "valid" / "tyumen_inventory.json"
    doc = json.loads(example.read_text(encoding="utf-8"))
    doc["run_id"] = "frozen-hidden-run"
    doc["freeze_tag"] = freeze_tag
    doc["objects"][0]["object_id"] = object_id
    doc["objects"][0]["split"] = "TEST_HIDDEN"
    doc["files"] = []
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_train_objects_pass_without_flags(policy) -> None:
    assert check_access(["OBJ-A", "OBJ-B", None], policy) is None


def test_hidden_object_refused_without_flag(policy, tmp_path) -> None:
    manifest = _run_manifest(tmp_path, freeze_tag="hidden-run-freeze")
    with pytest.raises(HiddenAccessRefusedError, match="--hidden-final"):
        check_access(["OBJ-A", "OBJ-Z"], policy, run_manifest=manifest, tag_exists=lambda _t: True)


def test_hidden_object_refused_without_frozen_run(policy) -> None:
    with pytest.raises(HiddenAccessRefusedError, match="--run-manifest"):
        check_access(["OBJ-Z"], policy, hidden_final=True)


def test_hidden_object_refused_when_run_not_frozen(policy, tmp_path) -> None:
    manifest = _run_manifest(tmp_path, freeze_tag=None)
    with pytest.raises(HiddenAccessRefusedError, match="не заморожен"):
        check_access(["OBJ-Z"], policy, hidden_final=True, run_manifest=manifest, tag_exists=lambda _t: True)


def test_hidden_object_refused_when_tag_missing_in_git(policy, tmp_path) -> None:
    manifest = _run_manifest(tmp_path, freeze_tag="hidden-run-freeze")
    with pytest.raises(HiddenAccessRefusedError, match="не найден"):
        check_access(["OBJ-Z"], policy, hidden_final=True, run_manifest=manifest, tag_exists=lambda _t: False)


def test_hidden_object_refused_when_not_in_frozen_run(policy, tmp_path) -> None:
    manifest = _run_manifest(tmp_path, freeze_tag="hidden-run-freeze", object_id="OBJ-A")
    with pytest.raises(HiddenAccessRefusedError, match="не входит"):
        check_access(["OBJ-Z"], policy, hidden_final=True, run_manifest=manifest, tag_exists=lambda _t: True)


def test_hidden_object_refused_on_invalid_manifest(policy, tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"run_id": "x", "freeze_tag": "hidden-run-freeze"}), encoding="utf-8")
    with pytest.raises(HiddenAccessRefusedError, match="контракту"):
        check_access(["OBJ-Z"], policy, hidden_final=True, run_manifest=bad, tag_exists=lambda _t: True)


def test_hidden_access_granted_with_both(policy, tmp_path) -> None:
    manifest = _run_manifest(tmp_path, freeze_tag="hidden-run-freeze")
    frozen = check_access(
        ["OBJ-Z"],
        policy,
        hidden_final=True,
        run_manifest=manifest,
        tag_exists=lambda t: t == "hidden-run-freeze",
    )
    assert frozen is not None and frozen.freeze_tag == "hidden-run-freeze" and "OBJ-Z" in frozen.object_ids
    assert load_frozen_run(manifest, lambda _t: True).run_id == "frozen-hidden-run"


def test_git_tag_lookup_for_a_missing_tag() -> None:
    assert git_tag_exists("definitely-not-a-tag-3f9c2e") is False


def test_hidden_ids_come_from_the_split_policy_only(h) -> None:
    other = SplitPolicy.from_dict({**h.SPLIT_POLICY, "TEST_HIDDEN": ["OBJ-B"]})
    assert check_access(["OBJ-Z"], other) is None
    with pytest.raises(HiddenAccessRefusedError):
        check_access(["OBJ-B"], other)


def test_refusals_carry_the_catalogue_code(policy, tmp_path) -> None:
    """M0 follow-up: no --hidden-final → HIDDEN_TEST_ACCESS_DENIED; no valid frozen run → HIDDEN_FINAL_NOT_FROZEN."""
    with pytest.raises(HiddenAccessRefusedError) as no_flag:
        check_access(["OBJ-Z"], policy)
    assert no_flag.value.code == "HIDDEN_TEST_ACCESS_DENIED"
    assert no_flag.value.error().code == "HIDDEN_TEST_ACCESS_DENIED"
    with pytest.raises(HiddenAccessRefusedError) as no_manifest:
        check_access(["OBJ-Z"], policy, hidden_final=True)
    err = no_manifest.value.error()
    assert err.code == "HIDDEN_FINAL_NOT_FROZEN" and "freeze_tag" in err.detail and err.hint
    manifest = _run_manifest(tmp_path, freeze_tag="hidden-run-freeze")
    with pytest.raises(HiddenAccessRefusedError) as no_tag:
        check_access(["OBJ-Z"], policy, hidden_final=True, run_manifest=manifest, tag_exists=lambda _t: False)
    assert no_tag.value.code == "HIDDEN_FINAL_NOT_FROZEN"


def test_cli_reports_hidden_final_not_frozen(fake_data_root, tmp_path, capsys) -> None:
    from inspector_common.exitcodes import ExitCode
    from inspector_eval import cli

    pred = tmp_path / "OBJ-Z.json"
    pred.write_text(json.dumps({"object_id": "OBJ-Z", "checks": []}), encoding="utf-8")
    code = cli.main(["validate", "--pred", str(pred), "--hidden-final", "--data-root", str(fake_data_root)])
    assert code == ExitCode.HIDDEN_TEST_REFUSED
    err = capsys.readouterr().err
    assert "Итоговая оценка скрытой выборки без замороженного прогона" in err and "OBJ-Z" not in err
