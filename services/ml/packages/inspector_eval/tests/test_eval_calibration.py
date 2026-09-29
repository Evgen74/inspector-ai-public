"""Leave-object-out calibration skeleton on synthetic dev objects."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from inspector_eval import calibration
from inspector_eval.config import DEFAULT_CONFIG
from inspector_eval.data import InputError
from inspector_eval.devset import DevSet, DevSetRows


def _devset(devset_id: str, object_id: str, rows: list[dict], folds=None) -> DevSetRows:
    d = DevSet(
        id=devset_id,
        object_id=object_id,
        split="TRAIN_PUBLIC",
        format="gold_checks_jsonl",
        path_base="repo",
        path="-",
        badge_ru="",
        positives_only=False,
        frozen=False,
        labels_sha256=None,
        folds=folds,
    )
    return DevSetRows(d, rows)


@pytest.fixture()
def devsets(gold) -> list[DevSetRows]:
    return [
        _devset("DEV-A", "OBJ-A", [g for g in gold if g["object_id"] == "OBJ-A"]),
        _devset("DEV-B", "OBJ-B", [g for g in gold if g["object_id"] == "OBJ-B"]),
    ]


@pytest.fixture()
def candidates(gold, h) -> list[calibration.Candidate]:
    a, b = h.as_submission(gold, "OBJ-A"), h.as_submission(gold, "OBJ-B")
    a_bad = copy.deepcopy(a)
    a_bad["checks"] = [c for c in a_bad["checks"] if c["location"] != "142"]  # misses a critical room
    b_bad = {"object_id": "OBJ-B", "checks": []}
    b_mid = copy.deepcopy(b)
    extra = copy.deepcopy(b_mid["checks"][0])
    extra["location"] = "2.200"
    b_mid["checks"].append(extra)  # one false positive
    a_mid = copy.deepcopy(a)
    a_mid["checks"][0]["pd_value"] = "Иное"  # value slip only
    return [
        calibration.Candidate("overfit-a", {"tau": 0.2}, {"OBJ-A": a, "OBJ-B": b_bad}),
        calibration.Candidate("overfit-b", {"tau": 0.8}, {"OBJ-A": a_bad, "OBJ-B": b}),
        calibration.Candidate("balanced", {"tau": 0.5}, {"OBJ-A": a_mid, "OBJ-B": b_mid}),
    ]


def test_leave_one_out_reports_held_out_not_seen(candidates, devsets, ctx) -> None:
    result = calibration.calibrate(candidates, devsets, ctx, DEFAULT_CONFIG)
    loo = result["loo"]
    assert loo["status"] == "OK" and loo["folds"] == ["DEV-A", "DEV-B"]
    held = {r["held_out_fold"]: r for r in loo["held_out"]}
    assert held["DEV-A"]["chosen_candidate"] == "overfit-b"  # best on B …
    assert held["DEV-A"]["gate_triggered"] is True  # … misses A's critical room
    assert held["DEV-B"]["chosen_candidate"] == "overfit-a"
    assert loo["final_candidate"] == "balanced"
    assert loo["final_params"] == {"tau": 0.5} and len(loo["final_params_hash"]) == 64
    assert loo["mean_held_out"] < loo["seen_mean"]
    matrix = result["matrix"]
    assert matrix["overfit-a"]["DEV-A"]["total"] == pytest.approx(100.0)
    assert matrix["overfit-a"]["DEV-B"]["total"] == 0.0


def test_single_fold_is_insufficient(candidates, devsets, ctx) -> None:
    result = calibration.calibrate(candidates, devsets[:1], ctx, DEFAULT_CONFIG)
    assert result["loo"]["status"] == "INSUFFICIENT_FOLDS"
    assert result["loo"]["held_out"] == [] and result["loo"]["mean_held_out"] is None
    assert result["loo"]["final_candidate"] == "overfit-a"


def test_empty_devsets_and_no_candidates(devsets, ctx) -> None:
    empty = _devset("N-GOLD", "OBJ-B", [])
    assert calibration.build_folds([empty], DEFAULT_CONFIG) == []
    assert calibration.calibrate([], devsets, ctx, DEFAULT_CONFIG)["loo"]["status"] == "NO_CANDIDATES"


def test_prefix_folds_split_one_object(gold, h, ctx) -> None:
    rows = [g for g in gold if g["object_id"] == "OBJ-A"]
    rows.append(h.gold_row("T-9", "G-9", "KR-055", "Корпус 1"))
    folds = calibration.build_folds(
        [_devset("N-GOLD", "OBJ-A", rows, folds={"A": ["KR"], "B": ["*"]})], DEFAULT_CONFIG
    )
    by_name = {f.name: f for f in folds}
    assert set(by_name) == {"N-GOLD:A", "N-GOLD:B"}
    assert {r["parameter_code"] for r in by_name["N-GOLD:A"].gold_rows} == {"KR-055"}
    assert "KR-055" not in {r["parameter_code"] for r in by_name["N-GOLD:B"].gold_rows}
    cand = calibration.Candidate("c", {}, {"OBJ-A": h.as_submission(rows, "OBJ-A")})
    assert calibration.score_fold(cand, by_name["N-GOLD:A"], ctx, DEFAULT_CONFIG).total == pytest.approx(
        100.0
    )
    assert calibration.score_fold(cand, by_name["N-GOLD:B"], ctx, DEFAULT_CONFIG).total == pytest.approx(
        100.0
    )


def test_candidates_with_a_hidden_object_are_refused(candidates, devsets, ctx) -> None:
    bad = calibration.Candidate("leaky", {}, {"OBJ-Z": {"object_id": "OBJ-Z", "checks": []}})
    with pytest.raises(InputError, match="скрытой"):
        calibration.calibrate([*candidates, bad], devsets, ctx, DEFAULT_CONFIG)


def test_load_candidates_from_directory(tmp_path: Path, gold, h) -> None:
    for name, tau in (("c1", 0.3), ("c2", 0.6)):
        sub = tmp_path / name / "submission"
        sub.mkdir(parents=True)
        (tmp_path / name / "params.json").write_text(json.dumps({"tau": tau}), encoding="utf-8")
        (sub / "OBJ-A.json").write_text(json.dumps(h.as_submission(gold, "OBJ-A")), encoding="utf-8")
        (sub / "OBJ-A.sidecar.json").write_text("{}", encoding="utf-8")
    loaded = calibration.load_candidates(tmp_path)
    assert [c.name for c in loaded] == ["c1", "c2"]
    assert loaded[0].params == {"tau": 0.3} and set(loaded[0].predictions) == {"OBJ-A"}
    with pytest.raises(InputError):
        calibration.load_candidates(tmp_path / "missing")


def test_objective_validation() -> None:
    with pytest.raises(ValueError):
        calibration.leave_one_out({}, [], objective="accuracy")
