"""Schemas and integrity rules R1–R15 (93 §4.6) on synthetic submissions."""

from __future__ import annotations

import copy
import dataclasses

import pytest

from inspector_eval.config import DEFAULT_CONFIG
from inspector_eval.data import ScoringContext
from inspector_eval.validation import (
    PROTO8_RULES,
    RULE_IDS,
    check_integrity,
    location_grammar_problem,
    validate_schemas,
)


@pytest.fixture()
def good(gold, h) -> dict:
    return h.as_submission(gold, "OBJ-A")


def _failed(doc, ctx, cfg=DEFAULT_CONFIG) -> list[str]:
    return check_integrity(doc, ctx, cfg).failed


def test_clean_submission_passes_every_counted_rule(good, ctx) -> None:
    report = check_integrity(good, ctx, DEFAULT_CONFIG)
    assert report.failed == []
    assert report.share == 1.0 and report.hard == 1.0
    assert report.rules["R9"].status == "NOT_EVALUATED"  # no revision list given
    assert report.rules["R15"].counted is False
    d = report.as_dict()
    assert d["counted"] == 13 and d["passed"] == 13  # R1–R14 without R9; R15 is a warning
    assert [r["rule"] for r in d["rules"]] == list(RULE_IDS)


def test_schema_reports_three_schemas(good) -> None:
    report = validate_schemas(good)
    assert report.organizer_valid
    assert report.as_dict()["strict"]["valid"] and report.as_dict()["extended"]["valid"]
    bad = copy.deepcopy(good)
    bad["checks"][0]["violation_label"] = "CANDIDATE"
    report = validate_schemas(bad)
    assert not report.organizer_valid
    assert report.errors["organizer"]


def test_strict_schema_is_stricter_than_organizer(good) -> None:
    doc = copy.deepcopy(good)
    del doc["checks"][0]["pd_value"]  # optional for the organizers, required by our strict variant
    doc["checks"][0]["confidence"] = 0.7  # extended extra, not allowed in strict
    report = validate_schemas(doc)
    assert report.organizer_valid
    assert not report.as_dict()["strict"]["valid"]
    assert report.as_dict()["extended"]["valid"]


def test_r1_schema_invalid(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["evidence"][0]["pdf_page_number"] = 0
    assert "R1" in _failed(doc, ctx)


def test_r2_object_not_in_expected_split(good, ctx) -> None:
    doc = {**copy.deepcopy(good), "object_id": "OBJ-UNKNOWN"}
    assert "R2" in _failed(doc, ctx)
    assert "R2" in _failed(good, ctx, DEFAULT_CONFIG.replace(expected_split="TEST_HIDDEN"))


@pytest.mark.parametrize(
    ("evidence", "rules"),
    [
        (
            {"stage": "PD", "file_id": "F0999", "pdf_page_number": 1},
            {"R3", "R4", "R5"},
        ),  # excluded, not in manifest
        ({"stage": "PD", "file_id": "F0005", "pdf_page_number": 1}, {"R4"}),  # other object, same split
        (
            {"stage": "PD", "file_id": "F0004", "pdf_page_number": 1},
            {"R5", "R6", "R7"},
        ),  # GT index .txt, UNKNOWN
        ({"stage": "PD", "file_id": "F0001", "pdf_page_number": 121}, {"R6"}),  # beyond pdf_pages
        ({"stage": "RD", "file_id": "F0001", "pdf_page_number": 1}, {"R7"}),  # PD file cited as RD
        (
            {"stage": "PD", "file_id": "F0008", "pdf_page_number": 1},
            {"R8"},
        ),  # duplicate, not the representative
        ({"stage": "PD", "file_id": "F0900", "pdf_page_number": 1}, {"R4", "R14"}),  # hidden-object file
    ],
)
def test_evidence_rules(good, ctx, evidence, rules) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][1]["evidence"].append(evidence)
    assert set(_failed(doc, ctx)) == rules


def test_rd_id_mixed_accepts_rd_and_id(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["evidence"][1]["stage"] = "ID"  # F0002 is RD_ID_MIXED
    assert _failed(doc, ctx) == []


def test_duplicate_representative_is_citable(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["evidence"].append({"stage": "PD", "file_id": "F0007", "pdf_page_number": 1})
    assert _failed(doc, ctx) == []


def test_r9_superseded_revision(good, ctx: ScoringContext) -> None:
    with_revisions = dataclasses.replace(ctx, superseded_file_ids=frozenset({"F0002"}))
    report = check_integrity(good, with_revisions, DEFAULT_CONFIG)
    assert report.rules["R9"].status == "FAIL"
    assert report.as_dict()["counted"] == 14


def test_r10_duplicate_keys_after_normalisation(good, ctx) -> None:
    doc = copy.deepcopy(good)
    dup = copy.deepcopy(doc["checks"][0])
    dup["location"] = "пом. 012"
    doc["checks"].append(dup)
    assert _failed(doc, ctx) == ["R10"]
    assert _failed(doc, ctx, DEFAULT_CONFIG.replace(location_norm="strict")) == []


def test_r11_unknown_codes(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["parameter_code"] = "IOS4-099"
    doc["checks"][1]["parameter_code"] = "FREE-KITCHEN-001"
    assert "R11" in _failed(doc, ctx)


def test_r11_alias_codes_depend_on_code_norm(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["parameter_code"] = "ИОС4-79"
    report = check_integrity(doc, ctx, DEFAULT_CONFIG)
    assert report.failed == []
    assert report.rules["R11"].note_ru
    assert "R11" in _failed(doc, ctx, DEFAULT_CONFIG.replace(code_norm="strict"))


def test_r12_criticality_against_catalog(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["criticality"] = "Существенное (предписание)"
    doc["checks"][0]["protocol_status"] = "WARNING"
    assert _failed(doc, ctx) == ["R12"]
    doc = copy.deepcopy(good)
    doc["checks"][3]["criticality"] = (
        "Существенное (предписание)"  # FREE needs the «требует утверждения» string
    )
    assert _failed(doc, ctx) == ["R12"]


def test_r13_status_consistency(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["protocol_status"] = "WARNING"  # critical parameter must be CRITICAL
    assert _failed(doc, ctx) == ["R13"]
    doc = copy.deepcopy(good)
    doc["checks"][4]["protocol_status"] = "CRITICAL"  # NO_VIOLATION must be OK
    assert _failed(doc, ctx) == ["R13"]
    doc = copy.deepcopy(good)
    del doc["checks"][0]["protocol_status"]
    assert _failed(doc, ctx) == ["R13"]


def test_r14_train_file_in_a_test_submission(ctx) -> None:
    doc = {
        "object_id": "OBJ-Z",
        "checks": [
            {
                "parameter_code": "KR-055",
                "location": "OBJECT",
                "violation_label": "NO_VIOLATION",
                "protocol_status": "OK",
                "criticality": "Критическое (приостановка работ)",
                "evidence": [{"stage": "PD", "file_id": "F0001", "pdf_page_number": 1}],
            }
        ],
    }
    failed = _failed(doc, ctx, DEFAULT_CONFIG.replace(expected_split="TEST_HIDDEN"))
    assert "R14" in failed and "R4" in failed and "R2" not in failed


def test_r15_is_a_warning_only(good, ctx) -> None:
    doc = copy.deepcopy(good)
    doc["checks"][0]["location"] = "пом. 012"
    report = check_integrity(doc, ctx, DEFAULT_CONFIG)
    assert report.rules["R15"].status == "WARN"
    assert report.failed == [] and report.share == 1.0


@pytest.mark.parametrize(
    ("location", "ok"),
    [
        ("012", True),
        ("1.109", True),
        ("-1.05", True),
        ("OBJECT", True),
        ("Корпус 1", True),
        ("Корпус 1, этаж 3", True),
        ("Корпус 1, этаж 5, оси 1-3/А-Б", True),
        ("Этаж -1", True),
        ("Подземная автостоянка", True),
        ("пом. 012", False),
        (" 012", False),
        ("Венткамера 012", False),
        ("", False),
    ],
)
def test_location_grammar(location: str, ok: bool) -> None:
    assert (location_grammar_problem(location) is None) is ok


def test_proto8_counts_only_the_prototype_rules(good, ctx) -> None:
    report = check_integrity(good, ctx, DEFAULT_CONFIG.replace(integrity_rules="proto8"))
    counted = {r for r, res in report.rules.items() if res.counted}
    assert counted == PROTO8_RULES
    assert report.as_dict()["counted"] == 8


def test_empty_submission_earns_no_integrity(ctx) -> None:
    report = check_integrity({"object_id": "OBJ-A", "checks": []}, ctx, DEFAULT_CONFIG)
    assert report.failed == [] and report.share == 0.0 and report.hard == 0.0


def test_garbage_document_does_not_crash(ctx) -> None:
    report = check_integrity(["not", "a", "submission"], ctx, DEFAULT_CONFIG)
    assert "R1" in report.failed and "R2" in report.failed


def test_load_gold_validates_rows(tmp_path, h) -> None:
    import json

    from inspector_eval.data import InputError, load_gold

    good = tmp_path / "gold.jsonl"
    good.write_text(json.dumps(h.gold_row("T-1", "G", "KR-055", "OBJECT")) + "\n", encoding="utf-8")
    assert len(load_gold(good)) == 1
    bad = tmp_path / "bad.jsonl"
    row = h.gold_row("T-1", "G", "KR-055", "OBJECT")
    row["location_type"] = "ROOMS"
    bad.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(InputError, match="gold_check"):
        load_gold(bad)
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(InputError, match="JSON"):
        load_gold(broken)
