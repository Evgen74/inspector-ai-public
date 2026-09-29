"""T-GOLD fixture test (must-pass CI gate, 97 §3.2 M0/M1) and the 93 §2.3 / §4.10 regression cases.

Tolerances: measured totals must equal the analytic expectation within 1e-6 (float rounding only) and
the figure printed in 93 §2.3 within 0.05 (93 rounded to one or two decimals, e.g. 97.14 → «97.1»).
"""

from __future__ import annotations

import copy

import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_eval.config import DEFAULT_CONFIG
from inspector_eval.data import gold_for_object
from inspector_eval.fixtures import (
    CASES,
    T_GOLD_OBJECT,
    TOLERANCE,
    TOLERANCE_93,
    perfect_submission,
    run_cases,
)
from inspector_eval.scoring import score_object

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def t_gold(real_gold):
    return gold_for_object(real_gold, T_GOLD_OBJECT)


@pytest.fixture(scope="module")
def results(real_gold, real_ctx):
    return {r.case.case_id: r for r in run_cases(real_gold, real_ctx)}


def test_t_gold_shape(t_gold) -> None:
    assert len(t_gold) == 10
    assert sum(g["violation_label"] == "VIOLATION_PRESENT" for g in t_gold) == 10


def test_perfect_submission_is_schema_valid_and_scores_100(t_gold, real_ctx) -> None:
    doc = perfect_submission(t_gold, T_GOLD_OBJECT)
    for schema in ("submission.organizer", "submission.strict", "submission.extended"):
        assert validation_errors(schema, doc) == [], schema
    s = score_object(t_gold, doc, real_ctx, DEFAULT_CONFIG, object_id=T_GOLD_OBJECT)
    assert s.total == pytest.approx(100.0, abs=TOLERANCE)
    assert not s.gate_triggered
    assert len(s.gate.checkpoints) == 6  # IOS4-079 ×1, IOS4-078 ×5; FREE-HEATING is not approved
    assert s.integrity.failed == []
    assert all(r["total"] == pytest.approx(100.0) for r in s.sensitivity)  # robust to every assumption


@pytest.mark.parametrize("case", [c.case_id for c in CASES])
def test_regression_case(case: str, results) -> None:
    r = results[case]
    assert r.score.total == pytest.approx(r.case.expected_total, abs=TOLERANCE)
    assert r.score.total_uncapped == pytest.approx(r.case.expected_uncapped, abs=TOLERANCE)
    assert r.score.gate_triggered is r.case.expected_gate
    if r.case.report_93 is not None:
        assert abs(r.score.total - r.case.report_93) <= TOLERANCE_93
    assert r.ok


def test_named_regressions_from_the_brief(results) -> None:
    """The cases named in the AG-10 brief, with the gate outcome that matters."""
    assert results["B"].score.total == 59.0  # drop room 314 → capped
    assert [f"{c.parameter_code}/{c.location}" for c in results["B"].score.gate.missed] == ["IOS4-078/314"]
    assert results["E"].score.total == 59.0  # IOS4-078 instead of IOS4-079 → capped
    assert [f"{c.parameter_code}/{c.location}" for c in results["E"].score.gate.missed] == ["IOS4-079/012"]
    assert results["J"].score.total == 59.0  # «12» vs «012» → capped
    assert results["C"].score.total == pytest.approx(64.0)  # warm floor under IOS4-077
    assert results["F"].score.total == pytest.approx(97.142857, abs=1e-5)  # hedging both codes ≈ 97.1
    assert results["G"].score.total == pytest.approx(95.0)  # generic value text ≈ 95


def test_excluded_file_fails_r5(t_gold, real_ctx) -> None:
    doc = perfect_submission(t_gold, T_GOLD_OBJECT)
    doc["checks"][0]["evidence"].append({"stage": "PD", "file_id": "F0149", "pdf_page_number": 1})
    s = score_object(t_gold, doc, real_ctx, object_id=T_GOLD_OBJECT, extras=False)
    assert "R5" in s.integrity.failed


def test_ground_truth_index_is_not_citable(t_gold, real_ctx) -> None:
    doc = perfect_submission(t_gold, T_GOLD_OBJECT)
    doc["checks"][0]["evidence"].append({"stage": "PD", "file_id": "F0194", "pdf_page_number": 1})
    s = score_object(t_gold, doc, real_ctx, object_id=T_GOLD_OBJECT, extras=False)
    assert {"R5", "R6", "R7"} <= set(s.integrity.failed)


def test_rd_id_mixed_gold_files_accept_both_stages(t_gold, real_ctx) -> None:
    doc = perfect_submission(t_gold, T_GOLD_OBJECT)
    for check in doc["checks"]:
        for e in check["evidence"]:
            if e["stage"] == "RD":
                e["stage"] = "ID"
    s = score_object(t_gold, doc, real_ctx, object_id=T_GOLD_OBJECT, extras=False)
    assert s.integrity.failed == []
    assert s.localisation == 0.5  # the stage is part of the page key (H1)
    assert s.localisation_variants["recall:no_stage"] == 1.0


def test_every_catalog_code_and_alias_style(real_ctx) -> None:
    from inspector_eval.normalize import normalize_code

    for code, row in real_ctx.catalog.items():
        pid = row["parameter_id"]
        assert normalize_code(f"M-{pid:03d}", "light") == code
        assert normalize_code(code, "strict") == code


def test_value_threshold_sweep_is_monotonic(t_gold, real_ctx) -> None:
    doc = perfect_submission(t_gold, T_GOLD_OBJECT)
    for check in doc["checks"]:
        check["rd_value"] = str(check["rd_value"]).replace("отсутствует", "не предусмотрен")
    totals = [
        score_object(
            t_gold,
            copy.deepcopy(doc),
            real_ctx,
            DEFAULT_CONFIG.replace(value_threshold=t),
            object_id=T_GOLD_OBJECT,
            extras=False,
        ).total
        for t in (0.6, 0.7, 0.8, 0.85, 0.9, 0.95)
    ]
    assert totals == sorted(totals, reverse=True)
