"""SUSPICION records (ТЗ §9.5), their dedup, numbering and protocol rows (Раздел 6, Приложение А.5)."""

from __future__ import annotations

from inspector_hypothesis import HypothesisConfig, run_hypotheses
from inspector_hypothesis.suspicion import (
    Suspicion,
    a5_rows,
    finalize,
    section6_rows,
    suspicion_schema,
    suspicion_schema_errors,
)
from inspector_hypothesis.testing import ALT79B_ROOMS, explication, table_artifacts, tyumen_warm_floor


def _mixed_run():
    """One exported FREE group plus one Logical_Rule suspicion (the ALT79B explication sum)."""
    sc = tyumen_warm_floor()
    t = explication("ALT79B-PD", ALT79B_ROOMS, ("Общий итог по этажу", "2797.27"))
    sc.tables["F0171"] = table_artifacts("F0171", "PD", [t])
    return run_hypotheses(sc.inputs())


def test_schema_properties_equal_the_model_fields():
    assert set(suspicion_schema()["properties"]) == set(Suspicion.model_fields)
    required = set(suspicion_schema()["required"])
    tz = {
        "suspicion_id",
        "discovery_method",
        "confidence",
        "description",
        "pd_reference",
        "rd_reference",
        "review_priority",
        "normative_base",
        "finding_status",
        "inspector_status",
    }
    assert tz <= required  # every ТЗ §9.5 field is mandatory


def test_every_produced_suspicion_validates_against_the_proposed_contract():
    r = _mixed_run()
    assert len(r.suspicions) == 2
    for s in r.suspicions:
        assert suspicion_schema_errors(s) == []
    bad = r.suspicions[0].model_dump(mode="json") | {"finding_status": "CANDIDATE"}
    assert suspicion_schema_errors(bad)


def test_ordering_numbering_and_counts():
    r = _mixed_run()
    first, second = r.suspicions
    assert (first.suspicion_id, first.exported, first.parameter_code) == (1, True, "FREE-HEATING-001")
    assert (second.suspicion_id, second.rule_code, second.exported) == (2, "HR-LOG-005", False)
    assert r.stats["suspicions"] == {
        "total": 2,
        "exported": 1,
        "by_method": {"LOGICAL_ANALYSIS": 1, "SEMANTIC_DISSONANCE": 1},
        "by_priority": {"MEDIUM": 2},
    }
    assert r.ai_suspicions_count == 2  # Раздел 2 «Подозрений ИИ»; never part of «Выявлено нарушений»


def test_dedup_merges_same_key_and_keeps_the_most_confident():
    r = _mixed_run()
    s = r.suspicions[1]
    weaker = s.model_copy(update={"confidence": 0.1, "evidence": []})
    merged = finalize([s, weaker])
    assert len(merged) == 1 and merged[0].confidence == s.confidence and merged[0].suspicion_id == 1
    other_revision = s.model_copy(update={"suspicion_key": "f" * 64})
    assert len(finalize([s, other_revision])) == 2  # different revisions are never merged


def test_section_6_and_a5_rows():
    r = _mixed_run()
    rows = section6_rows(r.suspicions, {s.suspicion_key: f"Б.{10 + s.suspicion_id}" for s in r.suspicions})
    assert [(x.no, x.card_ref, x.method_ru) for x in rows] == [
        (1, "Б.11", "Семантический диссонанс"),
        (2, "Б.12", "Логический анализ"),
    ]
    assert rows[1].pd == "Σ 2795,04 м² ≠ итог 2797,27 м²" and rows[1].rd == "—"
    assert rows[1].parameter_code is None and rows[1].inspector_decision_ru == "⏳ Ожидает"
    a5 = a5_rows(r.suspicions, 11)
    assert [x.card_ref for x in a5] == ["Б.11", "Б.12"]
    assert str(a5[0].evidence_bind_status) == "BOUND" and a5[1].normative_base.startswith("ГОСТ 21.501-2018")


def test_rules_can_be_switched_off():
    r = run_hypotheses(tyumen_warm_floor().inputs(), HypothesisConfig(enable_rules=False))
    assert r.rule_outcomes == [] and "LOGICAL_ANALYSIS" not in r.stats["detector_status"]
    assert len(r.versions["rules_sha256"]) == 64 and len(r.versions["config_hash"]) == 64
