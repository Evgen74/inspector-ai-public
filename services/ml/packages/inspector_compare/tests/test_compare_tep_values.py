"""ТЭП PD↔RD value checks (PZ-001…PZ-012, SPZU-037): the literal matrix triggers (Δ > 0 over the printed
precision, Δ > 1 % for PZ-002, DECREASE-only for parking) over conservative candidate sets — any agreeing reading
makes the pair EQUAL, a ГПЗУ limit is never a design value, a violation is reported on the closest pair."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import ExtractedValue
from inspector_common.params import load_params
from inspector_compare.engine import compare_object
from inspector_compare.valuecmp import compare_values

STAGE_FILE = {"PD": "F9004", "RD": "F9002"}


def _tep(syn: Any, code: str, stage: str, raw: str, *, unit: str | None = "м²", basis: str = "ПД", page: int = 3,
         n: int = 0) -> dict[str, Any]:  # fmt: skip
    value = float(raw.replace(" ", "").replace(",", "."))
    file_id = STAGE_FILE[stage]
    norm: dict[str, Any] = {
        "type": "number",
        "value": value,
        "qualifiers": {"basis": basis, "indicator": code},
    }
    if unit:
        norm["unit"] = unit
    return {
        "value_id": f"tep-{code}-{stage}-{raw}-{basis}-{n}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": stage,
        "page_no": page,
        "fact_key": "tep.value",
        "param_code": code,
        "location": "OBJECT",
        "location_type": "OBJECT",
        "value_raw": raw,
        "value_norm": norm,
        "method": "TABLE",
        "confidence": 1.0,
        "quality_flag": "OK",
        "pipeline_version": "test",
    }


def _outcomes(values: list[dict[str, Any]]) -> dict[str, tuple[str, str | None, str | None]]:
    diffs = compare_values([ExtractedValue.model_validate(v) for v in values], load_params(), ("PD_RD",))
    return {
        d.code: (
            d.outcome,
            d.expected.value_raw if d.expected else None,
            d.actual.value_raw if d.actual else None,
        )
        for d in diffs
    }


def test_any_agreeing_reading_is_equal(syn: Any) -> None:
    # PD states the building area twice (ПЗ 4650,91 and ПЗУ 4629,70); RD repeats one of them → EQUAL
    vals = [_tep(syn, "PZ-001", "PD", "4650,91"), _tep(syn, "PZ-001", "PD", "4629,70", n=1),
            _tep(syn, "PZ-001", "RD", "4629,7")]  # fmt: skip
    assert _outcomes(vals)["PZ-001"][0] == "EQUAL"
    # RD differs from both → VIOLATION on the closest pair
    vals[-1] = _tep(syn, "PZ-001", "RD", "4700,00")
    assert _outcomes(vals)["PZ-001"] == ("VIOLATION", "4650,91", "4700,00")


def test_literal_triggers_and_directions(syn: Any) -> None:
    # PZ-002: Δ > 1 %
    assert (
        _outcomes([_tep(syn, "PZ-002", "PD", "11618,27"), _tep(syn, "PZ-002", "RD", "11700,0")])["PZ-002"][0]
        == "EQUAL"
    )
    assert (
        _outcomes([_tep(syn, "PZ-002", "PD", "11618,27"), _tep(syn, "PZ-002", "RD", "12000,0")])["PZ-002"][0]
        == "VIOLATION"
    )
    # PZ-012 / SPZU-037: only a decrease; counts compare without units («шт.» vs none)
    for code in ("PZ-012", "SPZU-037"):
        up = [_tep(syn, code, "PD", "120", unit="шт."), _tep(syn, code, "RD", "130", unit=None)]
        down = [_tep(syn, code, "PD", "120", unit="шт."), _tep(syn, code, "RD", "110", unit=None)]
        assert _outcomes(up)[code][0] == "IMPROVEMENT"
        assert _outcomes(down)[code][0] == "VIOLATION"
    # PZ-004: a sub-row without a printed unit is read in the catalog unit; another unit abstains
    assert (
        _outcomes(
            [
                _tep(syn, "PZ-004", "PD", "60997,93", unit=None),
                _tep(syn, "PZ-004", "RD", "61500,00", unit="м³"),
            ]
        )["PZ-004"][0]
        == "VIOLATION"
    )
    assert (
        _outcomes(
            [
                _tep(syn, "PZ-004", "PD", "69201,0", unit="м²"),
                _tep(syn, "PZ-004", "RD", "61500,00", unit="м³"),
            ]
        )["PZ-004"][0]
        == "ABSTAIN"
    )


def test_gpzu_limit_is_not_a_design_value(syn: Any) -> None:
    vals = [
        _tep(syn, "PZ-008", "PD", "74,5", unit="м", basis="ГПЗУ"),
        _tep(syn, "PZ-008", "RD", "70,0", unit="м"),
    ]
    assert "PZ-008" not in _outcomes(vals)


def test_engine_emits_object_level_pd_rd_finding(tmp_path: Path, cfg: Any, syn: Any) -> None:
    values = [_tep(syn, "PZ-001", "PD", "4650,91", page=4), _tep(syn, "PZ-001", "RD", "4700,00", page=2),
              _tep(syn, "PZ-004", "PD", "60997,93", unit="м³"), _tep(syn, "PZ-004", "RD", "60997,9", unit="м³")]  # fmt: skip
    result = compare_object(syn.make_context(tmp_path, [], values=values), cfg)
    viol = [f for f in result.findings if f["violation_label"] == "VIOLATION_PRESENT"]
    assert [(f["parameter_code"], f["location"]) for f in viol] == [("PZ-001", "OBJECT")]
    f = viol[0]
    assert (f["pd_value"], f["rd_value"], f["id_value"]) == ("4650,91 м²", "4700,00 м²", None)
    assert {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in f["evidence"]} == {
        ("PD", "F9004", 4),
        ("RD", "F9002", 2),
    }
    assert f["protocol_status"] == "CRITICAL"
    pz004 = next(r for r in result.findings if r["parameter_code"] == "PZ-004")
    assert pz004["violation_label"] != "VIOLATION_PRESENT"
    for doc in result.findings:
        assert not validation_errors("finding", doc)
