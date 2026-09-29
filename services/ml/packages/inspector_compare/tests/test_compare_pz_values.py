"""Labelled ПЗ values (fact ``pz.value``: PZ-013…018, 021…023) through the generic value comparator and the
precedence: directional triggers per the matrix rule, and a stage proven by its printed value is available."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from inspector_common.contracts.models import ExtractedValue
from inspector_common.params import load_params
from inspector_compare.precedence import evaluate_param
from inspector_compare.valuecmp import compare_values

FILES = {"PD": "F9004", "RD": "F9002", "ID": "F9005"}


def _pz(syn: Any, code: str, stage: str, value: Any, *, unit: str | None = None, rank: float | None = None,
        raw: str | None = None, n: int = 0) -> ExtractedValue:  # fmt: skip
    norm: dict[str, Any] = {"type": "enum" if rank is not None else "number", "value": value}
    if unit:
        norm["unit"] = unit
    if rank is not None:
        norm["rank"] = rank
    file_id = FILES[stage]
    return ExtractedValue.model_validate(
        {
            "value_id": f"pz-{code}-{stage}-{value}-{n}",
            "object_id": syn.OBJ,
            "file_id": file_id,
            "file_sha256": syn.sha(int(file_id[1:])),
            "stage": stage,
            "page_no": 3,
            "fact_key": "pz.value",
            "param_code": code,
            "location": "OBJECT",
            "location_type": "OBJECT",
            "value_raw": raw or str(value),
            "value_norm": norm,
            "method": "REGEX",
            "confidence": 0.85,
            "quality_flag": "OK",
            "pipeline_version": "test",
        }
    )


def _outcome(vals: list[ExtractedValue], code: str, axes: tuple[str, ...] = ("PD_RD",)) -> str:
    diffs = [d for d in compare_values(vals, load_params(), axes) if d.code == code]
    assert len(diffs) == 1, diffs
    return diffs[0].outcome


@pytest.mark.parametrize(
    ("code", "kw", "pd", "rd", "expected"),
    [
        # PZ-013 capacity: DECREASE only
        ("PZ-013", {}, 600, 550, "VIOLATION"),
        ("PZ-013", {}, 600, 650, "IMPROVEMENT"),
        ("PZ-013", {}, 600, 600, "EQUAL"),
        # PZ-014 (sub-check a): RD above ПД fires
        ("PZ-014", {"unit": "кВт"}, 462.5, 500.0, "VIOLATION"),
        ("PZ-014", {"unit": "кВт"}, 462.5, 450.0, "IMPROVEMENT"),
        # PZ-016 / 017 / 018: INCREASE only
        ("PZ-016", {"unit": "м³/сут"}, 107.5, 120.0, "VIOLATION"),
        ("PZ-016", {"unit": "м³/сут"}, 107.5, 100.0, "IMPROVEMENT"),
        ("PZ-017", {"unit": "Гкал/ч"}, 1.35, 1.5, "VIOLATION"),
        ("PZ-018", {"unit": "м³/ч"}, 45.6, 45.6, "EQUAL"),
    ],
)
def test_numeric_directional_triggers(
    syn: Any, code: str, kw: dict, pd: float, rd: float, expected: str
) -> None:
    vals = [_pz(syn, code, "PD", pd, **kw), _pz(syn, code, "RD", rd, **kw)]
    assert _outcome(vals, code) == expected


def test_unit_mismatch_abstains(syn: Any) -> None:
    vals = [_pz(syn, "PZ-017", "PD", 1.35, unit="Гкал/ч"), _pz(syn, "PZ-017", "RD", 1570.0, unit="кВт")]
    assert _outcome(vals, "PZ-017") == "ABSTAIN"  # no silent kW ↔ Gcal/h conversion


@pytest.mark.parametrize(
    ("code", "pd", "rd", "expected"),
    [
        ("PZ-022", ("I", 5), ("II", 4), "VIOLATION"),  # a lower degree of fire resistance is a downgrade
        ("PZ-022", ("II", 4), ("I", 5), "IMPROVEMENT"),
        ("PZ-022", ("II", 4), ("II", 4), "EQUAL"),
        ("PZ-023", ("C0", 4), ("C1", 3), "VIOLATION"),
        ("PZ-023", ("C0", 4), ("C0", 4), "EQUAL"),
        ("PZ-015", ("I", 3), ("II", 2), "VIOLATION"),  # II is a lower reliability category than I
        ("PZ-015", ("III", 1), ("II", 2), "IMPROVEMENT"),
        ("PZ-021", ("B+", 7), ("C", 4), "VIOLATION"),
        ("PZ-021", ("A", 8), ("A", 8), "EQUAL"),
    ],
)
def test_ordinal_downgrade_only(syn: Any, code: str, pd: tuple, rd: tuple, expected: str) -> None:
    vals = [_pz(syn, code, "PD", pd[0], rank=pd[1]), _pz(syn, code, "RD", rd[0], rank=rd[1])]
    assert _outcome(vals, code) == expected


def test_ambiguous_readings_are_never_compared(syn: Any) -> None:
    v = _pz(syn, "PZ-022", "PD", "I", rank=5)
    v = v.model_copy(update={"is_ambiguous": True})
    vals = [v, _pz(syn, "PZ-022", "RD", "II", rank=4)]
    assert [d for d in compare_values(vals, load_params(), ("PD_RD",)) if d.code == "PZ-022"] == []


def test_a_stage_proven_by_its_value_is_available(tmp_path: Path, syn: Any) -> None:
    ctx = syn.make_context(tmp_path, [], rows=syn.default_rows())
    spec = load_params().get("PZ-013")  # RD source is a ТХ sheet: no such file in the object
    bare = evaluate_param(ctx, spec, violated=False, verified=True)
    assert (bare.rule, bare.violation_label) == (1, "COMPARISON_IMPOSSIBLE")
    seen = evaluate_param(ctx, spec, violated=False, verified=True, value_stages=("PD", "RD", "ID"))
    assert (seen.rule, seen.violation_label, seen.protocol_status) == (5, "NO_VIOLATION", "OK")
    assert seen.available == ("PD", "RD", "ID") and seen.readable == ("PD", "RD", "ID")
    # two of three stages compared: ИД still missing → MISSING_DOCUMENT (97 §2.6 rule 3), not a silent OK
    two = evaluate_param(ctx, spec, violated=False, verified=True, value_stages=("PD", "RD"))
    assert (two.violation_label, two.protocol_status) == ("MISSING_DOCUMENT", "ID_MISSING")
