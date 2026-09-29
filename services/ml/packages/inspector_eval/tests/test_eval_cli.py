"""`inspector-score` and `inspector-batch score` end to end on a synthetic organizer package."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from inspector_common.exitcodes import ExitCode
from inspector_eval import cli


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def perfect_dir(tmp_path, gold, h) -> Path:
    d = tmp_path / "pred"
    _write(d / "OBJ-A.json", h.as_submission(gold, "OBJ-A"))
    _write(d / "OBJ-B.json", h.as_submission(gold, "OBJ-B"))
    return d


def _run(fake_data_root: Path, *args: str) -> int:
    return cli.main([*args, "--data-root", str(fake_data_root)])


def test_run_perfect_text_and_outputs(fake_data_root, perfect_dir, tmp_path, capsys) -> None:
    out = tmp_path / "out"
    assert _run(fake_data_root, "run", "--pred", str(perfect_dir), "--out", str(out)) == ExitCode.OK
    text = capsys.readouterr().out
    assert "Итоговый балл: 100.00 из 100" in text and "Сводно по 2 объектам" in text
    assert sorted(p.name for p in out.iterdir()) == ["gate.csv", "per_check.csv", "score.json", "summary.txt"]
    report = json.loads((out / "score.json").read_text(encoding="utf-8"))
    assert [o["object_id"] for o in report["objects"]] == ["OBJ-A", "OBJ-B"]
    assert report["pooled"]["total"] == pytest.approx(100.0)
    assert len(report["config"]["config_hash"]) == 64 and len(report["inputs"]["gold_sha256"]) == 64
    assert (out / "gate.csv").read_text(encoding="utf-8").count("\n") == 1 + 4  # header + 4 checkpoints


def test_run_json_single_file(fake_data_root, perfect_dir, capsys) -> None:
    code = _run(fake_data_root, "run", "--pred", str(perfect_dir / "OBJ-A.json"), "--json", "--key", "k3")
    assert code == ExitCode.OK
    report = json.loads(capsys.readouterr().out)
    assert [o["object_id"] for o in report["objects"]] == ["OBJ-A"]
    assert report["config"]["key"] == "k3" and report["pooled"] is None


def test_run_gate_triggered_exit_code(fake_data_root, gold, h, tmp_path, capsys) -> None:
    doc = h.as_submission(gold, "OBJ-A")
    doc["checks"] = [c for c in doc["checks"] if c["location"] != "142"]
    pred = _write(tmp_path / "p" / "OBJ-A.json", doc)
    assert _run(fake_data_root, "run", "--pred", str(pred)) == ExitCode.GATE_TRIGGERED
    assert "СРАБОТАЛ ГЕЙТ" in capsys.readouterr().out


def test_run_schema_invalid_exit_code(fake_data_root, gold, h, tmp_path) -> None:
    doc = h.as_submission(gold, "OBJ-A")
    doc["checks"][0]["evidence"][0]["pdf_page_number"] = 0
    pred = _write(tmp_path / "p" / "OBJ-A.json", doc)
    assert _run(fake_data_root, "run", "--pred", str(pred)) == ExitCode.SCHEMA_INVALID


def test_run_refuses_hidden_object_and_prints_nothing(fake_data_root, tmp_path, capsys) -> None:
    pred = _write(tmp_path / "p" / "hidden.json", {"object_id": "OBJ-Z", "checks": []})
    assert _run(fake_data_root, "run", "--pred", str(pred)) == ExitCode.HIDDEN_TEST_REFUSED
    captured = capsys.readouterr()
    assert captured.out == "" and "скрытой" in captured.err
    assert _run(fake_data_root, "run", "--pred", str(pred), "--hidden-final") == ExitCode.HIDDEN_TEST_REFUSED
    assert _run(fake_data_root, "validate", "--pred", str(pred)) == ExitCode.HIDDEN_TEST_REFUSED
    assert (
        _run(fake_data_root, "run", "--pred", str(tmp_path / "p"), "--objects", "OBJ-Z")
        == ExitCode.HIDDEN_TEST_REFUSED
    )


def test_run_refuses_hidden_rows_in_gold(fake_data_root, perfect_dir, h, tmp_path) -> None:
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps(h.gold_row("Z-1", "G", "KR-055", "OBJECT", object_id="OBJ-Z")) + "\n", encoding="utf-8"
    )
    assert (
        _run(fake_data_root, "run", "--pred", str(perfect_dir), "--gold", str(gold_path))
        == ExitCode.HIDDEN_TEST_REFUSED
    )


def test_run_without_gold_or_prediction(fake_data_root, gold, h, tmp_path, capsys) -> None:
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        "\n".join(json.dumps(g) for g in gold if g["object_id"] == "OBJ-A") + "\n", encoding="utf-8"
    )
    pred = _write(tmp_path / "p" / "OBJ-B.json", h.as_submission(gold, "OBJ-B"))
    assert _run(fake_data_root, "run", "--pred", str(pred), "--gold", str(gold_path)) == ExitCode.DATA_MISSING
    assert "нет эталонной разметки" in capsys.readouterr().err
    assert _run(fake_data_root, "run", "--pred", str(tmp_path / "nope")) == ExitCode.DATA_MISSING


def test_run_missing_prediction_for_a_gold_object_scores_zero(
    fake_data_root, gold, h, tmp_path, capsys
) -> None:
    d = tmp_path / "only_a"
    _write(d / "OBJ-A.json", h.as_submission(gold, "OBJ-A"))
    assert _run(fake_data_root, "run", "--pred", str(d), "--json") == ExitCode.GATE_TRIGGERED
    report = json.loads(capsys.readouterr().out)
    b = next(o for o in report["objects"] if o["object_id"] == "OBJ-B")
    assert b["prediction"]["missing"] is True and b["total"] == 0.0


def test_validate(fake_data_root, perfect_dir, gold, h, tmp_path, capsys) -> None:
    assert _run(fake_data_root, "validate", "--pred", str(perfect_dir)) == ExitCode.OK
    assert "выполнено 13 из 13" in capsys.readouterr().out
    doc = h.as_submission(gold, "OBJ-A")
    doc["checks"][0]["evidence"].append({"stage": "PD", "file_id": "F0999", "pdf_page_number": 1})
    pred = _write(tmp_path / "v" / "OBJ-A.json", doc)
    assert _run(fake_data_root, "validate", "--pred", str(pred), "--json") == ExitCode.SCHEMA_INVALID
    out = json.loads(capsys.readouterr().out)
    assert set(out[0]["integrity"]["failed"]) == {"R3", "R4", "R5"}


def test_devset_list_and_show(fake_data_root, tmp_path, capsys) -> None:
    from inspector_eval import devset

    raw = json.loads(devset.REGISTRY_PATH.read_text(encoding="utf-8"))
    labels = _write(tmp_path / "n_gold.json", {"meta": {}, "candidates": []})
    for entry in raw["devsets"]:
        if entry["id"] == "T-GOLD":
            entry.update(frozen=False, labels_sha256=None)  # the fake package's gold has another hash
        else:
            entry.update(object_id="OBJ-B", path={"base": "repo", "relative": str(labels)}, frozen=False)
    registry = _write(tmp_path / "registry.json", raw)
    assert _run(fake_data_root, "devset", "list", "--registry", str(registry)) == ExitCode.OK
    text = capsys.readouterr().out
    assert "T-GOLD" in text and "N-GOLD" in text
    assert _run(fake_data_root, "devset", "show", "N-GOLD", "--registry", str(registry)) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)["rows"] == 0


def test_devset_list_reports_a_broken_set_instead_of_failing(fake_data_root, capsys) -> None:
    # The package registry's N-GOLD cites catalog codes the synthetic catalog lacks: listed with its error.
    assert _run(fake_data_root, "devset", "list") == ExitCode.OK
    text = capsys.readouterr().out
    assert "N-GOLD" in text and "ошибка" in text
    with pytest.raises(SystemExit):
        _run(fake_data_root, "devset", "show")


def test_sweep(fake_data_root, gold, h, tmp_path, capsys) -> None:
    registry = tmp_path / "registry.json"
    entries = [
        {
            "id": f"DEV-{o[-1]}",
            "object_id": o,
            "format": "gold_checks_jsonl",
            "path": {"base": "package_data", "relative": "public_train_checks.jsonl"},
            "frozen": False,
            "labels_sha256": None,
        }
        for o in ("OBJ-A", "OBJ-B")
    ]
    registry.write_text(json.dumps({"devsets": entries}), encoding="utf-8")
    runs = tmp_path / "cands"
    for name, drop in (("good", None), ("lossy", "142")):
        doc = h.as_submission(gold, "OBJ-A")
        if drop:
            doc["checks"] = [c for c in doc["checks"] if c["location"] != drop]
        _write(runs / name / "OBJ-A.json", doc)
        _write(runs / name / "OBJ-B.json", h.as_submission(gold, "OBJ-B"))
        _write(runs / name / "params.json", {"name": name})
    out = tmp_path / "sweep_out"
    code = _run(
        fake_data_root, "sweep", "--pred-dir", str(runs), "--registry", str(registry), "--out", str(out)
    )
    assert code == ExitCode.OK
    assert "итоговый выбор" in capsys.readouterr().out
    result = json.loads((out / "sweep.json").read_text(encoding="utf-8"))
    assert result["loo"]["status"] == "OK" and result["loo"]["final_candidate"] == "good"


@pytest.mark.data
def test_selftest_on_real_t_gold(real_paths, capsys) -> None:
    assert cli.main(["selftest"]) == ExitCode.OK
    assert "Все случаи совпали с ожидаемыми." in capsys.readouterr().out


# ── inspector-batch score ────────────────────────────────────────────────────────────────────


def _batch(fake_data_root: Path, tmp_path: Path, *args: str) -> int:
    from inspector_batch import cli as batch_cli

    return batch_cli.main(
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


def test_batch_score_writes_the_run_directory(fake_data_root, perfect_dir, tmp_path, capsys) -> None:
    assert (
        _batch(fake_data_root, tmp_path, "--run-id", "t-score", "score", "--pred", str(perfect_dir))
        == ExitCode.OK
    )
    out = tmp_path / "runs" / "t-score" / "score"
    assert (out / "score.json").is_file() and (out / "summary.txt").is_file()
    report = json.loads((out / "score.json").read_text(encoding="utf-8"))
    assert report["run_id"] == "t-score" and report["pooled"]["total"] == pytest.approx(100.0)
    assert "Итоговый балл: 100.00" in capsys.readouterr().out


def test_batch_score_finds_the_latest_submission(fake_data_root, gold, h, tmp_path) -> None:
    runs = tmp_path / "runs"
    _write(runs / "older" / "submission" / "OBJ-A.json", {"object_id": "OBJ-A", "checks": []})
    newer = _write(runs / "newer" / "submission" / "OBJ-A.json", h.as_submission(gold, "OBJ-A"))
    import os

    os.utime(runs / "older" / "submission", (1, 1))
    os.utime(newer.parent, None)
    code = _batch(fake_data_root, tmp_path, "--run-id", "t2", "score", "--object", "OBJ-A")
    assert code == ExitCode.OK
    report = json.loads((runs / "t2" / "score" / "score.json").read_text(encoding="utf-8"))
    assert report["prediction_source"].endswith("newer/submission")


def test_batch_score_without_submission(fake_data_root, tmp_path, capsys) -> None:
    assert _batch(fake_data_root, tmp_path, "score") == ExitCode.DATA_MISSING
    assert "Ответ для оценки не найден" in capsys.readouterr().err


def test_batch_score_gate_and_variants(fake_data_root, gold, h, tmp_path) -> None:
    doc = h.as_submission(gold, "OBJ-A")
    doc["checks"] = [c for c in doc["checks"] if c["location"] != "012"]
    pred = _write(tmp_path / "p" / "OBJ-A.json", doc)
    code = _batch(
        fake_data_root,
        tmp_path,
        "--run-id",
        "t3",
        "score",
        "--object",
        "OBJ-A",
        "--pred",
        str(pred),
        "--gate",
        "broad",
    )
    assert code == ExitCode.GATE_TRIGGERED
    report = json.loads((tmp_path / "runs" / "t3" / "score" / "score.json").read_text(encoding="utf-8"))
    assert report["config"]["gate"] == "broad" and report["objects"][0]["total"] == 59.0


def test_batch_score_is_refused_on_hidden_objects_by_the_cli(fake_data_root, tmp_path) -> None:
    assert _batch(fake_data_root, tmp_path, "score", "--object", "OBJ-Z") == ExitCode.HIDDEN_TEST_REFUSED


def test_batch_module_refuses_hidden_objects_independently(fake_data_root, tmp_path) -> None:
    import argparse
    import logging

    from inspector_common.batch import BatchContext
    from inspector_common.settings import Settings
    from inspector_eval import batch

    parser = argparse.ArgumentParser()
    batch.add_score_arguments(parser)
    args = parser.parse_args([])
    ctx = BatchContext(
        settings=Settings(data_root=fake_data_root, runs_root=tmp_path / "runs"),
        run_id="x",
        run_dir=tmp_path / "runs" / "x",
        objects=("OBJ-Z",),
        hidden_run=True,
        log=logging.getLogger("t"),
    )
    assert batch.run_score(args, ctx) == ExitCode.HIDDEN_TEST_REFUSED


@pytest.mark.data
def test_batch_selftest_on_real_t_gold(real_paths, tmp_path, capsys) -> None:
    from inspector_batch import cli as batch_cli

    code = batch_cli.main(
        ["--runs-root", str(tmp_path / "runs"), "--log-format", "console", "score", "--selftest"]
    )
    assert code == ExitCode.OK
    out = capsys.readouterr().out
    assert out.count(" OK ") == 16


def test_argument_helpers_round_trip() -> None:
    import argparse

    from inspector_eval.args import add_variant_arguments, config_from_args, parse_bool

    parser = argparse.ArgumentParser()
    add_variant_arguments(parser)
    cfg = config_from_args(parser.parse_args(["--with-stage", "false", "--location-norm", "relaxed"]))
    assert cfg.loc_with_stage is False and cfg.location_norm == "relaxed"
    assert parse_bool("да") is True
    with pytest.raises(argparse.ArgumentTypeError):
        parse_bool("maybe")
    assert copy.copy(cfg) == cfg
