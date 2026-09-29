"""VALUE_CONFLICT: contradicting values of one stage become one suspicion, never a violation (ТЗ §9.5)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from inspector_common.contracts.models import ExtractedValue
from inspector_hypothesis import HypothesisConfig, compare_hook, run_hypotheses
from inspector_hypothesis.inputs import DocumentInfo, HypothesisInputs, MemoryPageSource
from inspector_hypothesis.suspicion import section6_rows
from inspector_hypothesis.valueconflict import ConflictConfig, detect, value_conflict_suspicions

OBJ = "OBJ-TEST-1"
SHA = "a" * 64


def val(
    param: str,
    raw: str,
    file_id: str,
    page: int,
    *,
    stage: str = "PD",
    norm: Any = None,
    rank: int | None = None,
    unit: str | None = None,
    kind: str = "enum",
    location: str = "OBJECT",
    ambiguous: bool | None = None,
    n: int = 1,
    fact: str | None = None,
) -> ExtractedValue:
    body: dict[str, Any] = {
        "value_id": f"{file_id}-p{page}-{param}-{n}",
        "object_id": OBJ,
        "file_id": file_id,
        "file_sha256": SHA,
        "stage": stage,
        "page_no": page,
        "page_basis": "PDF_NATIVE",
        "fact_key": fact or ("tep.value" if kind == "number" else "pz.value"),
        "value_raw": raw,
        "value_norm": {"type": kind, "value": norm if norm is not None else raw, "qualifiers": {}},
        "method": "REGEX",
        "confidence": 0.9,
        "quality_flag": "OK",
        "pipeline_version": "t-1",
        "location": location,
        "location_type": "OBJECT" if location == "OBJECT" else "ELEMENT",
        "param_code": param,
    }
    if rank is not None:
        body["value_norm"]["rank"] = rank
    if unit:
        body["value_norm"]["unit"] = unit
    if ambiguous is not None:
        body["is_ambiguous"] = ambiguous
    return ExtractedValue.model_validate(body)


def inputs(values: list[ExtractedValue]) -> HypothesisInputs:
    files = {v.file_id: v.stage for v in values}
    docs = {
        fid: DocumentInfo(fid, str(st), None, 40, file_sha256=SHA, name=f"{fid}.pdf")
        for fid, st in files.items()
    }
    return HypothesisInputs(OBJ, docs, MemoryPageSource(), values=values, run_id="t")


def fire_conflict() -> list[ExtractedValue]:
    return [
        val("PZ-022", "II", "F1", 17, ambiguous=True),
        val("PZ-022", "III", "F2", 6),
        val("PZ-022", "III", "F3", 9),
        val("PZ-022", "III", "R1", 3, stage="RD"),
    ]


def test_conflicting_values_of_two_files_make_one_suspicion_with_all_evidence():
    sus = value_conflict_suspicions(inputs(fire_conflict()), "t")
    assert len(sus) == 1
    s = sus[0]
    assert s.discovery_method == "LOGICAL_ANALYSIS" and s.finding_status == "SUSPICION"
    assert s.subject_key == "PZ-022:OBJECT"
    assert s.description.startswith("В ПД противоречивые значения параметра PZ-022 «Степень огнестойкости")
    assert "II — F1.pdf л.17" in s.description
    assert "III — F2.pdf л.6" in s.description
    assert "в РД — III (R1.pdf л.3)" in s.description
    assert s.description.endswith("Требуется уточнение, какое значение действующее.")
    assert {(e.stage, e.file_id, e.pdf_page_number) for e in s.evidence} == {
        ("PD", "F1", 17),
        ("PD", "F2", 6),
        ("PD", "F3", 9),
        ("RD", "R1", 3),
    }
    assert s.stage_cells["PD"] == "III (2 ф.); II (1 ф.)" and s.stage_cells["RD"] == "III"
    assert s.stage_cells["ID"] == "—"
    row = section6_rows([s], 5)[0]
    assert row.card_ref == "Б.5" and row.method_ru == "Логический анализ" and row.parameter_code is None


def test_element_bound_values_of_other_locations_are_no_conflict():
    values = [
        val("KR-055", "B7,5", "F1", 2, location="Бетонная подготовка"),
        val("KR-055", "B25", "F2", 3, location="Колонны"),
    ]
    assert detect(values) == []
    # even the same element differing between files is not raised by default (element keys are family names)
    same_element = [
        val("KR-055", "B25", "F1", 2, location="Колонны"),
        val("KR-055", "B30", "F2", 3, location="Колонны"),
    ]
    assert detect(same_element) == []
    found = detect(same_element, ConflictConfig(include_elements=True))
    assert [(c.code, c.location) for c in found] == [("KR-055", "Колонны")]


def test_two_mentions_in_one_file_are_no_conflict():
    values = [val("PZ-022", "II", "F1", 4), val("PZ-022", "III", "F1", 9), val("PZ-022", "II", "F2", 4)]
    assert detect(values) == []  # F2 agrees with F1's first mention; F1 alone contradicts itself
    assert detect([val("PZ-022", "II", "F1", 4), val("PZ-022", "III", "F1", 9)]) == []


def test_mentions_about_another_subject_are_ignored():
    def with_context(v: ExtractedValue, text: str) -> ExtractedValue:
        return v.model_copy(update={"context_text": text})

    values = [
        val("PZ-022", "II", "F1", 12),
        with_context(val("PZ-022", "I", "F2", 85), "встроенная автостоянка – I степени огнестойкости"),
        with_context(val("PZ-022", "IV", "F3", 14), "до зданий и сооружений IV степени огнестойкости"),
    ]
    assert detect(values) == []
    plain = [val("PZ-022", "II", "F1", 12), with_context(val("PZ-022", "I", "F2", 85), "здание I степени")]
    assert len(detect(plain)) == 1
    assert len(detect(values, ConflictConfig(skip_other_subjects=False))) == 1


def test_a_page_listing_several_values_is_a_norm_list_not_a_statement():
    values = [
        val("PZ-022", "III", "F1", 19),
        val("PZ-022", "IV", "F1", 19, n=2),
        val("PZ-022", "II", "F2", 4),
    ]
    assert detect(values) == []


def test_numeric_values_within_tolerance_are_no_conflict_and_beyond_it_are():
    within = [
        val("PZ-004", "60997,93", "F1", 3, kind="number", norm=60997.93, unit="м³"),
        val("PZ-004", "60997,9", "F2", 3, kind="number", norm=60997.9, unit="м³"),
    ]
    assert detect(within) == []
    beyond = [
        val("PZ-004", "60997,93", "F1", 3, kind="number", norm=60997.93, unit="м³"),
        val("PZ-004", "70000", "F2", 3, kind="number", norm=70000, unit="м³"),
    ]
    found = detect(beyond)
    assert len(found) == 1 and found[0].code == "PZ-004"
    other_unit = [
        val("PZ-004", "60997,93", "F1", 3, kind="number", norm=60997.93, unit="м³"),
        val("PZ-004", "70000", "F2", 3, kind="number", norm=70000, unit="м²"),
    ]
    assert detect(other_unit) == []  # units differ: not comparable, no claim


def test_numbers_printed_in_prose_and_the_reliability_category_are_not_compared():
    prose = [
        val("PZ-014", "2,4 кВт", "F1", 8, kind="number", norm=2.4, unit="кВт", fact="pz.value"),
        val("PZ-014", "8,86 кВт", "F2", 7, kind="number", norm=8.86, unit="кВт", fact="pz.value"),
    ]
    assert detect(prose) == []
    assert len(detect(prose, ConflictConfig(prose_numbers=True))) == 1
    assert detect([val("PZ-015", "II", "F1", 21), val("PZ-015", "I", "F2", 10)]) == []


def test_a_stage_with_many_distinct_values_is_a_list_of_mentions():
    values = [
        val("PZ-014", f"{i},5", f"F{i}", 3, kind="number", norm=float(i) + 0.5, unit="кВт")
        for i in range(1, 9)
    ]
    assert detect(values) == []


def test_untrusted_values_are_ignored():
    low = val("PZ-022", "II", "F1", 4).model_copy(update={"quality_flag": "LOW_QUALITY"})
    assert detect([low, val("PZ-022", "III", "F2", 4)]) == []


def test_energy_class_twin_parameters_are_one_suspicion():
    values = [
        val("PZ-021", "C", "F1", 5),
        val("PZ-021", "B+", "F2", 5),
        val("ZU-124", "C", "F1", 5),
        val("ZU-124", "B+", "F2", 5),
    ]
    sus = value_conflict_suspicions(inputs(values), "t")
    assert len(sus) == 1 and "PZ-021" in sus[0].description and "ZU-124" in sus[0].description
    assert sus[0].explanation["twin_parameter_codes"] == ["ZU-124"]


def test_engine_adds_the_suspicion_and_changes_nothing_else():
    inp = inputs(fire_conflict())
    with_conflicts = run_hypotheses(inp)
    without = run_hypotheses(inp, HypothesisConfig(enable_value_conflicts=False))
    assert len(with_conflicts.suspicions) == len(without.suspicions) + 1
    assert with_conflicts.free_groups == without.free_groups == []
    assert with_conflicts.free_findings == without.free_findings == []  # no finding, hence no violation/label
    assert with_conflicts.stats["detector_status"]["VALUE_CONFLICT"] == "OK"
    assert [s.subject_key for s in with_conflicts.suspicions] == ["PZ-022:OBJECT"]
    assert all(not s.exported and s.finding_group_id is None for s in with_conflicts.suspicions)


def test_a_parameter_that_already_has_a_violation_gets_no_duplicate_suspicion(tmp_path):
    ctx = SimpleNamespace(
        object_id=OBJ,
        files={},
        layouts={},
        tables={},
        values=fire_conflict(),
        run_dir=tmp_path,
    )
    compare_hook.clear_cache()
    plain = compare_hook.protocol_suspicions(ctx=ctx, rule_codes=[compare_hook.VALUE_CONFLICT_RULE])
    assert plain["error"] is None and len(plain["section6_rows"]) == 1
    covered = compare_hook.protocol_suspicions(
        ctx=ctx, matrix_keys={("PZ-022", "OBJECT")}, rule_codes=[compare_hook.VALUE_CONFLICT_RULE]
    )
    assert covered["section6_rows"] == []
    other_loc = compare_hook.protocol_suspicions(
        ctx=ctx, matrix_keys={("PZ-022", "Колонны")}, rule_codes=[compare_hook.VALUE_CONFLICT_RULE]
    )
    assert len(other_loc["section6_rows"]) == 1
    compare_hook.clear_cache()
