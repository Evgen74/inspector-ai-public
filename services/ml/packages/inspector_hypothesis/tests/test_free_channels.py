"""The FREE path's second assertion channel (AG-02C ``pd.element_room`` values, 97 §3.3) and RD removal statements.

AG-02C's values are taken through the same guards as our own PageTokens sentences: TEXT and TABLE assert rooms,
LABEL and SPEC only confirm; a negated or foreign room list is dropped. An RD sentence that names the element as
removed («исключены тёплые полы») is evidence of the absence, not a presence hit.
"""

from __future__ import annotations

import dataclasses

import pytest

from inspector_common.contracts.loader import validate
from inspector_hypothesis import FreeConfig, HypothesisConfig, run_hypotheses
from inspector_hypothesis.testing import (
    A4,
    PD_P11_TEXT,
    PD_SCHEME,
    element_room_values,
    page,
    tyumen_warm_floor,
)

ROOMS = ["267", "270", "271", "272"]
P11_SENTENCE = " ".join(PD_P11_TEXT[2:5])


def _run(scenario, **free):
    return run_hypotheses(scenario.inputs(), HypothesisConfig(enable_rules=False, free=FreeConfig(**free)))


def _anchors(g):
    return [(str(a.stage), a.file_id, a.pdf_page_number) for a in g.anchor_evidence]


def test_ag02c_text_assertion_alone_gives_the_gold_group():
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)  # the ПЗ page has no PageTokens; AG-02C read its text layer
    sc.values = element_room_values("F0171", 11, ROOMS, P11_SENTENCE)
    r = _run(sc)
    [g] = r.free_groups
    assert (g.parameter_code, g.locations) == ("FREE-HEATING-001", ROOMS)
    assert _anchors(g) == [("PD", "F0171", 99), ("RD", "F0202", 17)]
    cand = r.free_candidates[0]
    assert cand.sources == {"PAGE_TOKENS": 0, "AG02C_TEXT": 1}
    assert [a.source for a in cand.assertions] == ["AG02C_TEXT"]
    # the ПЗ page is supporting PD evidence, with AG-02C's box
    support = {(e.file_id, e.pdf_page_number): e for e in g.evidence or []}
    assert support[("F0171", 11)].geometry.boxes == [[0.1, 0.3, 0.9, 0.36]]
    assert g.confidence == pytest.approx(0.85)
    assert g.decision_trace["assertion_sources"] == {"PAGE_TOKENS": 0, "AG02C_TEXT": 1}
    validate("finding_group", g.dump())


def test_ag02c_twin_of_our_own_assertion_corroborates_without_inflating_confidence():
    sc = tyumen_warm_floor()
    sc.values = element_room_values("F0171", 11, ROOMS, P11_SENTENCE)
    r = _run(sc)
    cand = r.free_candidates[0]
    assert cand.sources == {"PAGE_TOKENS": 1, "corroborated": 1}
    assert len(cand.assertions) == 1 and cand.assertions[0].corroborated
    assert r.free_groups[0].confidence == pytest.approx(0.85)


def test_ag02c_negated_assertion_is_dropped():
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)
    sc.values = element_room_values(
        "F0171", 11, ["267", "270"], "В пом. 267, 270 теплые полы не предусмотрены."
    )
    assert _run(sc).free_candidates == []


def test_ag02c_room_list_of_another_element_is_left_out():
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)
    text = "В пом. 101, 102 предусмотрены радиаторы, а в пом. 267, 270, 271, 272 — теплые полы."
    sc.values = element_room_values("F0171", 11, ["101", "102", *ROOMS], text)  # AG-02C takes every list
    [g] = _run(sc).free_groups
    assert g.locations == ROOMS


def test_ag02c_text_naming_only_another_element_asserts_nothing():
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)
    sc.values = element_room_values("F0171", 11, ["101"], "В пом. 101 предусмотрены радиаторы.")
    assert _run(sc).free_candidates == []


def test_ag02c_label_only_confirms_and_never_asserts_rooms():
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)
    # a leader label with every room printed nearby, neighbours 266/268/277 included
    sc.values = element_room_values(
        "F0171",
        99,
        ["266", "267", "268", "270", "271", "272", "277"],
        "Регулятор для системы “теплый пол” Multibox C/RTL",
        channel="LABEL",
        anchor="теплый пол",
    )
    assert _run(sc).free_candidates == []


def test_ag02c_text_rooms_must_be_printed_in_the_sentence():
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)
    # a label mis-typed as TEXT: the rooms come from around the leader, not from the sentence
    sc.values = element_room_values(
        "F0171",
        99,
        ["266", "267", "268"],
        "Регулятор для системы “теплый пол” Multibox C/RTL",
        anchor="теплый пол",
    )
    assert _run(sc).free_candidates == []
    # a sentence without «пом.» but with the room tokens printed keeps just those
    sc.values = element_room_values("F0171", 11, ["267", "999"], "Теплые полы: раздевальная 267.")
    assert _run(sc).free_candidates[0].rooms == ["267"]


def test_ag02c_label_page_competes_as_the_pd_anchor_and_confirms_the_drawing():
    sc = tyumen_warm_floor()
    # the schematic's element label is drawn as curves: our tokens show the rooms but not «тёплый пол»
    sc.replace(
        page(
            "F0171",
            99,
            PD_SCHEME,
            [
                [("267,", 0.293, 0.42), ("270", 0.298, 0.42)],
                [("271,", 0.313, 0.42), ("272", 0.317, 0.42)],
                ("Принципиальная схема системы отопления", 0.80, 0.93),
            ],
        )
    )
    without = _run(sc).free_candidates[0]
    assert (without.pd_anchor.file_id, without.pd_anchor.page_no) == ("F0171", 11)
    assert "pd_drawing_confirms" not in without.confidence_terms

    sc.values = element_room_values(
        "F0171", 99, ROOMS, "Регулятор для системы “теплый пол” Multibox C/RTL", channel="LABEL"
    )
    r = _run(sc)
    cand = r.free_candidates[0]
    assert (cand.pd_anchor.file_id, cand.pd_anchor.page_no) == ("F0171", 99)
    assert cand.confidence_terms["pd_drawing_confirms"] == 0.10
    assert _anchors(r.free_groups[0]) == [("PD", "F0171", 99), ("RD", "F0202", 17)]


def test_values_of_another_family_stage_or_uncitable_file_are_ignored():
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)
    sc.values = [
        *element_room_values("F0171", 11, ROOMS, P11_SENTENCE, family="HEATING_DEVICE"),
        *[
            v.model_copy(update={"stage": "RD", "file_id": "F0202"})
            for v in element_room_values("F0202", 3, ROOMS, P11_SENTENCE)
        ],
    ]
    assert _run(sc).free_candidates == []
    sc.values = element_room_values("F0171", 11, ROOMS, P11_SENTENCE)
    sc.documents["F0171"] = dataclasses.replace(sc.documents["F0171"], citable=False)
    assert _run(sc).free_candidates == []


def test_rd_removal_statement_supports_the_absence():
    sc = tyumen_warm_floor()
    sc.replace(
        page(
            "F0202",
            5,
            A4,
            ["Изменение 3. Исключены теплые полы в пом. 267, 270, 271, 272 по решению заказчика."],
        )
    )
    r = _run(sc)
    cand = r.free_candidates[0]
    assert cand.absence == "DOCUMENT" and cand.present_rooms == {}
    assert [(x.file_id, x.page_no, x.rooms) for x in cand.removals] == [("F0202", 5, tuple(ROOMS))]
    assert cand.confidence_terms["rd_removal_statement"] == 0.05
    g = r.free_groups[0]
    assert g.confidence == pytest.approx(0.90)
    assert "элемент упомянут как исключённый" in (g.rationale or "")
    assert g.decision_trace["removal_statements"][0]["page"] == 5
    [s] = r.suspicions
    assert s.explanation["removal_statements"][0]["file_id"] == "F0202"


def test_rd_plain_mention_elsewhere_is_presence_not_removal():
    sc = tyumen_warm_floor()
    sc.replace(page("F0202", 5, A4, ["Теплые полы предусмотрены в пом. 101, 102."]))
    cand = _run(sc).free_candidates[0]
    assert cand.absence == "ROOM" and cand.removals == []
    assert "rd_removal_statement" not in cand.confidence_terms
    assert not cand.exported


def test_negation_far_from_the_mention_does_not_make_a_removal():
    sc = tyumen_warm_floor()
    far = " ".join(["слово"] * 20)
    sc.replace(
        page(
            "F0202", 5, A4, [f"Радиаторы исключены из спецификации, {far}, теплые полы в пом. 101 сохранены."]
        )
    )
    cand = _run(sc).free_candidates[0]
    assert cand.removals == [] and cand.absence == "ROOM"


def test_a_table_row_is_not_an_assertion_in_either_channel():
    soup = (
        "Подвесная канальная -50/40R.2D WNP 100 6000 6600 (480) 1245 2850 U=3x380 B 4,0 2850 WWN.3 теплый пол "
        "(пом. 167, 254) FLO.3 N=5,0 (+ККБ, 1 +26 +20 (15948) 18548 164,4 16,44 EU3+EU7 2 П19"
    )
    sc = tyumen_warm_floor()
    sc.drop_page("F0171", 11)
    sc.values = element_room_values(
        "F0171", 83, ["167", "254"], soup
    )  # AG-02C typed an equipment row as TEXT
    r = _run(sc)
    assert r.free_candidates == []
    sc.values = []
    sc.replace(page("F0171", 83, A4, [soup]))  # the same row in our own PageTokens
    assert _run(sc).free_candidates == []


def test_prose_measure():
    from inspector_hypothesis.textmatch import is_prose

    assert is_prose(P11_SENTENCE)
    assert is_prose("Теплые полы предусмотрены в пом. 101, 102.")
    assert not is_prose("П1 100 6000 6600 2850 приток")
    assert not is_prose("267, 270 271, 272 Т11 Т21 Multibox C/RTL")
