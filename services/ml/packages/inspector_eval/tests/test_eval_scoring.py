"""Scoring components, variants, gate and hedges on synthetic data (no organizer data needed)."""

from __future__ import annotations

import copy

import pytest

from inspector_eval.config import CHOICES, DEFAULT_CONFIG, ScoreConfig
from inspector_eval.scoring import is_approved_checkpoint, pool, score_object, wilson


@pytest.fixture()
def gold_a(gold) -> list[dict]:
    return [g for g in gold if g["object_id"] == "OBJ-A"]


@pytest.fixture()
def perfect(gold, h) -> dict:
    return h.as_submission(gold, "OBJ-A")


def _score(gold_rows, doc, ctx, cfg: ScoreConfig = DEFAULT_CONFIG, extras: bool = False):
    return score_object(gold_rows, doc, ctx, cfg, object_id="OBJ-A", extras=extras)


def test_perfect_scores_100(gold_a, perfect, ctx) -> None:
    s = _score(gold_a, perfect, ctx, extras=True)
    assert s.total == pytest.approx(100.0)
    assert not s.gate_triggered
    assert s.counts["gold_positives"] == 4 and s.counts["critical_checkpoints"] == 3
    assert {r["outcome"] for r in s.per_check} == {"TP", "NEG_MATCH"}
    assert s.sensitivity and all(
        r["total"] == pytest.approx(100.0) for r in s.sensitivity if r["switch"] != "key"
    )


def test_empty_and_missing_prediction_score_zero(gold_a, ctx) -> None:
    empty = _score(gold_a, {"object_id": "OBJ-A", "checks": []}, ctx)
    missing = _score(gold_a, None, ctx)
    for s in (empty, missing):
        assert s.total == 0.0 and s.gate_triggered
        assert len(s.gate.missed) == 3
    assert missing.prediction_missing and not empty.prediction_missing


def test_schema_invalid_prediction_scores_zero(gold_a, perfect, ctx) -> None:
    bad = copy.deepcopy(perfect)
    bad["checks"][0]["violation_label"] = "CANDIDATE"
    s = _score(gold_a, bad, ctx)
    assert not s.schema.organizer_valid
    assert s.total == 0.0 and all(v == 0.0 for v in s.components.values())
    assert "R1" in s.integrity.failed


def test_missed_critical_room_caps_at_59(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    doc["checks"] = [c for c in doc["checks"] if c["location"] != "142"]
    s = _score(gold_a, doc, ctx)
    assert s.gate_triggered and s.total == 59.0
    assert s.total_uncapped == pytest.approx(60 * (2 * 0.75 / 1.75) + 15 * 0.75 + 15 * 0.8 + 10)
    assert [c.location for c in s.gate.missed] == ["142"]


def test_free_finding_is_never_a_checkpoint(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    doc["checks"] = [c for c in doc["checks"] if not c["parameter_code"].startswith("FREE-")]
    s = _score(gold_a, doc, ctx)
    assert not s.gate_triggered
    assert s.detection.fn == 1


def test_checkpoint_predicate(h) -> None:
    assert is_approved_checkpoint(h.gold_row("x", "g", "KR-055", "OBJECT"))
    assert not is_approved_checkpoint(h.gold_row("x", "g", "FREE-HEATING-001", "1"))
    assert not is_approved_checkpoint(h.gold_row("x", "g", "SPZU-025", "OBJECT"))
    assert not is_approved_checkpoint(h.gold_row("x", "g", "KR-055", "OBJECT", gold_status="REVIEW_QUEUE"))
    assert not is_approved_checkpoint(h.gold_row("x", "g", "KR-055", "OBJECT", score_eligible=False))
    row = h.gold_row("x", "g", "KR-055", "OBJECT")
    del row["gold_status"]  # team labels carry no gold_status: treated as final
    assert is_approved_checkpoint(row)


def test_gate_variants(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    doc["checks"][0]["evidence"] = [
        {"stage": "PD", "file_id": "F0001", "pdf_page_number": 99}
    ]  # 012: wrong page
    doc["checks"][4]["violation_label"] = "COMPARISON_IMPOSSIBLE"  # KR-055 negative with the wrong label
    doc["checks"][4]["protocol_status"] = "COMPARISON_IMPOSSIBLE"
    key = _score(gold_a, doc, ctx)
    strict = _score(gold_a, doc, ctx, DEFAULT_CONFIG.replace(gate="strict"))
    broad = _score(gold_a, doc, ctx, DEFAULT_CONFIG.replace(gate="broad"))
    assert not key.gate_triggered
    assert strict.gate_triggered and [c.status for c in strict.gate.missed] == ["FOUND_WRONG_EVIDENCE"]
    assert broad.gate_triggered and [c.parameter_code for c in broad.gate.missed] == ["KR-055"]
    assert key.gate.as_dict()["triggered_by_variant"] == {"key": False, "strict": True, "broad": True}


def test_detection_variants(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    doc["checks"] = [c for c in doc["checks"] if c["location"] != "142"]  # group G-2 half found
    extra = copy.deepcopy(doc["checks"][0])
    extra.update(parameter_code="IOS4-078", location="300")
    doc["checks"].append(extra)
    doc["checks"][0]["evidence"] = [{"stage": "PD", "file_id": "F0001", "pdf_page_number": 99}]
    s = _score(gold_a, doc, ctx)
    k1, k3, k4, ml = (s.detection_variants[k] for k in ("k1", "k3", "k4", "multilabel"))
    assert (k1.tp, k1.fp, k1.fn) == (3, 1, 1)
    assert (k3.tp, k3.fp, k3.fn) == (3, 1, 0)  # 3 groups found (any), 1 FP cluster
    assert (k4.tp, k4.fp, k4.fn) == (2, 2, 2)  # 012 key hit without a correct page → FP + FN
    assert (ml.tp, ml.fp, ml.fn) == (4, 1, 1)
    maj = _score(gold_a, doc, ctx, DEFAULT_CONFIG.replace(key="k3", group_rule="all"))
    assert (maj.detection.tp, maj.detection.fn) == (2, 1)


def test_localisation_variants(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    doc["checks"][0]["evidence"].append({"stage": "PD", "file_id": "F0001", "pdf_page_number": 11})
    doc["checks"][1]["evidence"] = [{"stage": "ID", "file_id": "F0002", "pdf_page_number": 3}]
    s = _score(gold_a, doc, ctx)
    v = s.localisation_variants
    assert v["recall"] == pytest.approx((1 + 0 + 1 + 1) / 4)
    assert v["jaccard"] == pytest.approx((2 / 3 + 0 + 1 + 1) / 4)
    assert v["anyhit"] == pytest.approx(3 / 4)
    assert v["recall:no_stage"] == pytest.approx((1 + 0.5 + 1 + 1) / 4)


def test_value_and_status_component(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    doc["checks"][0]["pd_value"] = "Что-то другое"
    doc["checks"][1]["criticality"] = "Существенное (предписание)"
    s = _score(gold_a, doc, ctx)
    # check 0: status 1, values 2/3 → 0.8333; check 1: status 0.75, values 1 → 0.875; others 1
    assert s.value_status == pytest.approx((0.5 + 0.5 * 2 / 3 + 0.5 * 0.75 + 0.5 + 3) / 5)
    assert s.status_only == pytest.approx((1 + 0.75 + 3) / 5)
    assert s.values_only == pytest.approx((2 / 3 + 1 + 3) / 5)


def test_duplicate_keys_first_wins_and_fail_r10(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    dup = copy.deepcopy(doc["checks"][0])
    dup["violation_label"] = "NO_VIOLATION"
    dup["protocol_status"] = "OK"
    doc["checks"].append(dup)
    s = _score(gold_a, doc, ctx)
    assert s.counts["pred_duplicate_keys"] == 1
    assert s.detection.tp == 4
    assert "R10" in s.integrity.failed


def test_hedges_and_what_if(gold_a, perfect, ctx) -> None:
    doc = copy.deepcopy(perfect)
    hedge = copy.deepcopy(doc["checks"][0])  # 012 IOS4-079 (gold) …
    hedge["parameter_code"] = "IOS4-078"  # … plus the runner-up code of the hedge pair
    doc["checks"][0]["confidence"] = 0.4
    hedge["confidence"] = 0.6
    doc["checks"].append(hedge)
    s = _score(gold_a, doc, ctx, extras=True)
    assert s.hedges is not None and s.hedges.hedges == 1
    assert s.hedges.critical_emitted == 4 and s.hedges.within_budget is False  # 1/4 > 20 %
    assert s.hedges.groups[0]["kept_in_what_if"] == "IOS4-078"  # higher confidence is kept
    assert s.hedges.what_if["gate_triggered"] is True and s.hedges.what_if["total"] == 59.0
    assert not s.gate_triggered


def test_breakdowns(gold_a, perfect, ctx) -> None:
    s = _score(gold_a, perfect, ctx, extras=True)
    sections = s.breakdowns["by_section"]
    assert sections["Раздел 5. ИОС4"]["tp"] == 3
    assert sections["СВОБОДНЫЙ ПОИСК"]["tp"] == 1


def test_sensitivity_covers_every_switch(gold_a, perfect, ctx) -> None:
    s = _score(gold_a, perfect, ctx, extras=True)
    switches = {r["switch"] for r in s.sensitivity}
    assert switches == set(CHOICES) - {"group_rule"}


def test_pooled_micro_over_objects(gold, perfect, ctx, h) -> None:
    a = score_object([g for g in gold if g["object_id"] == "OBJ-A"], perfect, ctx, object_id="OBJ-A")
    b = score_object([g for g in gold if g["object_id"] == "OBJ-B"], None, ctx, object_id="OBJ-B")
    pooled = pool([a, b], ctx, DEFAULT_CONFIG)
    assert pooled.detection.tp == 4 and pooled.detection.fn == 1
    assert pooled.gate_triggered  # OBJ-B missed its critical AR-040
    assert pooled.total == 59.0
    comps = pooled.components
    assert comps["source_localization_exact_file_page"] == pytest.approx(4 / 5)
    assert comps["document_integrity_and_split_handling"] == pytest.approx(0.5)
    assert pooled.as_dict()["bootstrap_f1"]["status"] == "INSUFFICIENT_CLUSTERS"


def test_bootstrap_with_enough_clusters(gold_a, perfect, ctx) -> None:
    scores = [score_object(gold_a, perfect, ctx, object_id="OBJ-A", extras=False) for _ in range(5)]
    boot = pool(scores, ctx, DEFAULT_CONFIG).bootstrap_f1(n_boot=200)
    assert boot["status"] == "OK" and boot["f1_ci95"] == (1.0, 1.0)


def test_wilson() -> None:
    assert wilson(0, 0) is None
    lo, hi = wilson(9, 10)
    assert 0.59 < lo < 0.6 and 0.98 < hi <= 1.0


def test_config_rejects_unknown_switch_values() -> None:
    with pytest.raises(ValueError):
        ScoreConfig(key="k2")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ScoreConfig(value_threshold=0)
    described = DEFAULT_CONFIG.describe()
    assert len(described["config_hash"]) == 64 and described["hypothesis"] == "H1"
