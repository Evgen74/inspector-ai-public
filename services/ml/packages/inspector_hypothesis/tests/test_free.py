"""FREE-<TOPIC>-<NNN> path on the synthetic Тюменская warm-floor scenario (gold G-TR-002 shape) and its guards."""

from __future__ import annotations

import pytest

from inspector_common.contracts.loader import enum_mappings, validate
from inspector_hypothesis import FreeConfig, HypothesisConfig, run_hypotheses
from inspector_hypothesis.elements import free_families, load_families
from inspector_hypothesis.testing import (
    A4,
    OBJECT_ID,
    PD_P11_TEXT,
    doc,
    filler,
    page,
    rd_heating_p17,
    tyumen_warm_floor,
)

FREE_CRIT = "Существенное (предписание) — требует утверждения"


def _run(scenario, **free):
    return run_hypotheses(scenario.inputs(), HypothesisConfig(free=FreeConfig(**free)))


def test_warm_floor_becomes_free_heating_001_with_the_gold_shape():
    r = _run(tyumen_warm_floor())
    assert len(r.free_groups) == 1
    g = r.free_groups[0]
    assert g.parameter_code == "FREE-HEATING-001"
    assert g.finding_group_id == f"{OBJECT_ID}-G-FREE-HEATING-001"
    assert g.locations == ["267", "270", "271", "272"]
    assert str(g.matrix_scope) == "FREE_SEARCH" and g.parameter_id is None
    assert str(g.parameter_mapping_status) == "MATRIX_GAP_CONFIRMED"
    assert str(g.comparison_result) == "MISSING_DESIGN_ELEMENT"
    assert (g.pd_value, g.rd_value, g.id_value) == ("Тёплый пол предусмотрен", "Тёплый пол отсутствует", None)
    assert str(g.violation_label) == "VIOLATION_PRESENT" and str(g.protocol_status) == "WARNING"
    assert g.criticality == FREE_CRIT == enum_mappings()["free_search"]["criticality_string"]
    assert str(g.finding_status) == "SUSPICION" and str(g.evidence_bind_status) == "BOUND"
    assert g.element_noun == "Тёплый пол"
    # anchor rule: one page per stage for the group — the PD heating schematic (not the ПЗ text page) and the RD
    # heating plan (not the ventilation plan that shows the same rooms)
    assert [(str(a.stage), a.file_id, a.pdf_page_number, a.is_anchor) for a in g.anchor_evidence] == [
        ("PD", "F0171", 99, True),
        ("RD", "F0202", 17, True),
    ]
    assert {(e.file_id, e.pdf_page_number) for e in g.evidence or []} == {("F0171", 11), ("F0171", 136)}
    assert g.confidence == pytest.approx(0.85)
    assert g.recommendation is not None and "тёплых полов (пом. 267, 270, 271, 272)" in g.recommendation.text
    assert str(g.recommendation.text_origin) == "AG03_DRAFT"
    validate("finding_group", g.dump())


def test_atomic_findings_one_per_room_reuse_the_group_anchor_pages():
    r = _run(tyumen_warm_floor())
    fs = r.free_findings
    assert [f.location for f in fs] == ["267", "270", "271", "272"]
    assert [f.finding_id for f in fs] == [
        f"{OBJECT_ID}-FREE-HEATING-001-PDRD-{x}" for x in ("267", "270", "271", "272")
    ]
    for f in fs:
        assert f.finding_group_id == r.free_groups[0].finding_group_id
        assert [(str(e.stage), e.file_id, e.pdf_page_number) for e in f.evidence] == [
            ("PD", "F0171", 99),
            ("RD", "F0202", 17),
        ]
        assert f.document_status == "PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK"
        validate("finding", f.dump())


def test_free_rows_project_to_a_valid_organizer_submission():
    r = _run(tyumen_warm_floor())
    checks = [
        {
            "parameter_code": f.parameter_code,
            "location": f.location,
            "pd_value": f.pd_value,
            "rd_value": f.rd_value,
            "id_value": f.id_value,
            "violation_label": str(f.violation_label),
            "protocol_status": str(f.protocol_status),
            "criticality": f.criticality,
            "evidence": [
                {"stage": str(e.stage), "file_id": e.file_id, "pdf_page_number": e.pdf_page_number}
                for e in f.evidence
            ],
        }
        for f in r.free_findings
    ]
    validate("submission.organizer", {"object_id": OBJECT_ID, "checks": checks})
    validate("submission.strict", {"object_id": OBJECT_ID, "checks": checks})


def test_the_suspicion_goes_to_section_6_and_is_not_a_violation():
    r = _run(tyumen_warm_floor())
    assert r.ai_suspicions_count == 1
    s = r.suspicions[0]
    assert s.finding_status == "SUSPICION" and str(s.inspector_status) == "PENDING"
    assert s.exported and s.parameter_code == "FREE-HEATING-001"
    assert s.pd_reference == "F0171, стр.99" and s.rd_reference == "F0202, стр.17"
    row = r.section6_rows(first_card_no=4)[0]
    assert (row.no, row.card_ref, row.method_ru, row.pd, row.rd, row.id) == (
        1,
        "Б.4",
        "Семантический диссонанс",
        "Тёплый пол предусмотрен",
        "Тёплый пол отсутствует",
        "—",
    )
    assert row.inspector_decision_ru == "⏳ Ожидает"


def test_element_shown_next_to_a_room_in_rd_removes_that_room():
    sc = tyumen_warm_floor()
    sc.replace(rd_heating_p17(extra=[("теплый", 0.356, 0.705), ("пол", 0.366, 0.705)]))  # next to room 270
    r = _run(sc)
    assert r.free_groups == []  # the element exists in RD → room-level absence only, not exported
    cand = r.free_candidates[0]
    assert cand.absence == "ROOM" and "270" in cand.present_rooms
    assert cand.rooms == ["267", "271", "272"]
    s = r.suspicions[0]
    assert not s.exported and s.parameter_code is None and s.not_exported_reasons


def test_unread_rd_pages_never_prove_absence():
    sc = tyumen_warm_floor()
    sc.drop_page("F0202", 5)  # the heating RD is not fully read
    sc.drop_page("F0201", 3)
    r = _run(sc)
    assert r.free_groups == []
    assert r.free_candidates[0].absence == "UNKNOWN"
    assert r.suspicions == []  # an unverifiable hypothesis stays in the statistics, not in Раздел 6
    assert r.stats["free"]["not_exported"]["WARM_FLOOR"]


def test_counterpart_document_fully_read_is_enough_with_lower_confidence():
    sc = tyumen_warm_floor()
    sc.drop_page("F0201", 3)  # ventilation RD incomplete, heating RD (the anchor document) complete
    r = _run(sc)
    assert [g.parameter_code for g in r.free_groups] == ["FREE-HEATING-001"]
    assert r.free_candidates[0].absence == "COUNTERPART"
    assert r.free_groups[0].confidence == pytest.approx(0.85 * 0.85, abs=1e-3)
    assert _run(sc, min_confidence=0.8).free_groups == []  # the threshold is honoured


def test_negated_pd_sentence_is_not_an_assertion():
    sc = tyumen_warm_floor()
    text = [
        line.replace("предусмотрена система подогрева полов", "не предусмотрена система подогрева полов")
        for line in PD_P11_TEXT
    ]
    sc.replace(page("F0171", 11, A4, text))
    sc.drop_page("F0171", 99)  # the drawing alone never makes an assertion
    assert _run(sc).free_candidates == []


def test_room_list_of_another_element_in_the_same_sentence_is_left_out():
    sc = tyumen_warm_floor()
    sc.replace(
        page(
            "F0171",
            11,
            A4,
            ["В пом. 101, 102 предусмотрены радиаторы, а в пом. 267, 270, 271, 272 — теплые полы."],
        )
    )
    r = _run(sc)
    assert r.free_groups[0].locations == ["267", "270", "271", "272"]


def test_no_rd_of_the_discipline_means_no_free_finding():
    sc = tyumen_warm_floor()
    for fid in ("F0201", "F0202"):
        sc.documents.pop(fid)
    r = _run(sc)
    assert r.free_groups == [] and r.free_candidates[0].absence == "NO_RD"


def _two_heating_groups():
    """Warm floors (PD anchor F0171 p99) and ИТП equipment (F0171 p120) both missing in RD: two HEATING groups."""
    sc = tyumen_warm_floor()
    sc.replace(
        page("F0171", 120, A4, ["В помещении ИТП (пом. 012) предусмотрен тепловой пункт с теплообменником."])
    )
    sc.replace(filler("F0202", 3, text="Отопление. План подвала 012"))
    return sc


def test_numbering_is_per_finding_group_within_topic_in_pd_page_order():
    r = _run(_two_heating_groups())
    by_family = {c.family.family: c.parameter_code for c in r.free_candidates}
    # order (PD file_id, PD anchor page, first location): p99 before p120
    assert by_family == {"WARM_FLOOR": "FREE-HEATING-001", "HEAT_POINT": "FREE-HEATING-002"}
    assert [g.locations for g in r.free_groups] == [["267", "270", "271", "272"], ["012"]]


def test_numbering_follows_the_pd_anchor_page_not_the_family():
    sc = _two_heating_groups()
    sc.pages._pages.pop(("F0171", 120))
    sc.replace(
        page("F0171", 20, A4, ["В помещении ИТП (пом. 012) предусмотрен тепловой пункт с теплообменником."])
    )
    r = _run(sc)
    by_family = {c.family.family: c.parameter_code for c in r.free_candidates}
    assert by_family == {"HEAT_POINT": "FREE-HEATING-001", "WARM_FLOOR": "FREE-HEATING-002"}  # p20 before p99


def test_group_cap_keeps_the_most_confident_and_renumbers():
    r = _run(_two_heating_groups(), max_groups=1)
    assert [g.parameter_code for g in r.free_groups] == ["FREE-HEATING-001"]
    assert r.free_groups[0].locations == ["267", "270", "271", "272"]  # 0.85 beats the single-page ИТП group
    assert any("лимит" in reason for c in r.free_candidates if not c.exported for reason in c.reasons)


def test_seed_policy_caps_free_groups_at_five():
    from inspector_common.params import load_change_map

    assert load_change_map().document["policy"]["max_free_groups_per_object"] == 5


def test_only_matrix_gap_families_route_to_free():
    fams = {f.family for f in free_families()}
    assert "WARM_FLOOR" in fams
    assert "HEATING_DEVICE" not in fams  # radiators are IOS4-077 (matrix), never FREE
    assert all(
        f.free_route("ELEMENT_MISSING").parameter_mapping_status == "MATRIX_GAP_CONFIRMED"
        for f in free_families()
    )
    assert load_families()["WARM_FLOOR"].manifest_sections == frozenset({"OV"})


def test_detector_failure_does_not_fail_the_run(monkeypatch):
    from inspector_hypothesis import free

    def boom(self, families=None):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(free.FreeDetector, "detect", boom)
    r = _run(tyumen_warm_floor())
    assert r.stats["detector_status"]["SEMANTIC_DISSONANCE"].startswith("FAILED")
    assert r.stats["detector_status"]["LOGICAL_ANALYSIS"] == "OK"
    assert r.free_groups == []


def test_uncitable_documents_are_never_evidence():
    sc = tyumen_warm_floor()
    sc.documents["F0202"] = doc("F0202", "RD", "OV", 20, citable=False)
    r = _run(sc)
    for g in r.free_groups:
        assert all(a.file_id != "F0202" for a in g.anchor_evidence)
