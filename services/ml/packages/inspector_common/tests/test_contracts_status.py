from __future__ import annotations

import itertools

import pytest

from inspector_common.contracts import loader, status

LABELS = loader.load_enums()["ViolationLabel"].codes
STATUSES = [v.code for v in loader.load_enums()["ProtocolParamStatus"].values if v.attrs.get("in_submission")]
CRIT = "Критическое (приостановка работ)"


@pytest.mark.parametrize(("label", "protocol_status"), list(itertools.product(LABELS, STATUSES)))
def test_strict_schema_encodes_the_same_consistency_rule(label: str, protocol_status: str) -> None:
    row = {
        "parameter_code": "KR-055",
        "location": "OBJECT",
        "pd_value": None,
        "rd_value": None,
        "id_value": None,
        "violation_label": label,
        "protocol_status": protocol_status,
        "criticality": CRIT,
        "evidence": [],
    }
    doc = {"object_id": "OBJ-X", "checks": [row]}
    assert loader.is_valid("submission.strict", doc) == status.is_consistent(label, protocol_status)


def test_expected_protocol_status() -> None:
    assert status.expected_protocol_status("VIOLATION_PRESENT", "CRITICAL_SUSPEND") == "CRITICAL"
    assert status.expected_protocol_status("VIOLATION_PRESENT", "SUBSTANTIAL_ORDER") == "WARNING"
    assert status.expected_protocol_status("NO_VIOLATION") == "OK"
    assert status.expected_protocol_status("MISSING_DOCUMENT", missing_stages=["ID"]) == "ID_MISSING"
    assert status.expected_protocol_status("MISSING_DOCUMENT", missing_stages=["ID", "PD"]) == "PD_MISSING"
    assert (
        status.expected_protocol_status("MISSING_DOCUMENT", missing_stages=["ID", "RD", "PD"]) == "RD_MISSING"
    )
    assert status.expected_protocol_status("COMPARISON_IMPOSSIBLE") == "COMPARISON_IMPOSSIBLE"
    with pytest.raises(ValueError):
        status.expected_protocol_status("VIOLATION_PRESENT")


def test_criticality_strings() -> None:
    assert status.criticality_level_for_string(CRIT) == "CRITICAL_SUSPEND"
    assert status.criticality_level_for_string("Существенное (предписание)") == "SUBSTANTIAL_ORDER"
    assert (
        status.criticality_level_for_string("Существенное (предписание) — требует утверждения")
        == "SUBSTANTIAL_ORDER"
    )
    assert status.criticality_level_for_string(None) is None
    with pytest.raises(ValueError):
        status.criticality_level_for_string("Критическое")
