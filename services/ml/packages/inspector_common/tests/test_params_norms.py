"""Web-verified norms merged into params.json (M1): references, thresholds, editions, regime changes. Owner: AG-03."""

from __future__ import annotations

import json

import pytest

from inspector_common import params
from inspector_common.contracts.loader import load_enums


@pytest.fixture(scope="module")
def reg() -> params.ParamRegistry:
    return params.load_params()


@pytest.fixture(scope="module")
def doc() -> dict:
    with open(params.seed_dir() / "params.json", encoding="utf-8") as fh:
        return json.load(fh)


def _refs(spec: params.ParamSpec) -> list[dict]:
    return [r for bucket in spec["references"].values() for r in bucket]


def test_every_parameter_was_verified(reg: params.ParamRegistry, doc: dict) -> None:
    for spec in reg:
        nv = spec["norm_verification"]
        assert nv["checked_at"] == "2026-09-27" and nv["record"] == spec.alias_codes[0]
        refs = _refs(spec)
        assert refs, spec.code
        assert all(r["status"] != "NOT_FOUND" for r in refs)  # a NOT_FOUND reference is never cited
        assert spec["reference_confidence_min"] == min(
            (r["confidence"] for r in refs), key=lambda c: params.CONF_ORDER[c]
        )
    counts = doc["counts"]
    assert counts["references_by_status"]["CONFIRMED"] >= 200 and counts["references_not_found"] == 1
    assert doc["matrix_version"] == "1.1.1"


def test_reference_columns_follow_tz_8_1(reg: params.ParamRegistry) -> None:
    """sp/gost/fz/other text columns render «СП 1.13130.2020, п. 4.2.1» from the verified references."""
    ar041 = reg.get("AR-041")
    assert "СП 1.13130.2020, п. 4.2.19" in ar041["sp_reference"]
    assert "п. 4.2.5" not in ar041["sp_reference"]  # the matrix clause, corrected by the verification
    ios4078 = reg.get("IOS4-078")
    assert ios4078["sp_reference"] == "СП 60.13330.2020; СП 7.13130.2013, разд. 6, п. 6.13"
    for spec in reg:
        for short, column in (
            ("sp", "sp_reference"),
            ("gost", "gost_reference"),
            ("fz", "fz_reference"),
            ("other", "other_normative"),
        ):
            items = spec["references"][short]
            assert (spec[column] is None) == (not items), (spec.code, column)
            for r in items:
                assert r["ref"] in spec[column]
        for r in spec["references"]["sp"]:
            assert r["designation"].startswith(("СП", "СНиП"))
        for r in spec["references"]["gost"]:
            assert r["designation"].startswith("ГОСТ")


def test_outdated_matrix_references_cite_the_replacement(reg: params.ParamRegistry) -> None:
    ppm110 = reg.get("PPM-110")
    outdated = [r for r in _refs(ppm110) if r["status"] == "OUTDATED"]
    assert outdated and outdated[0]["matrix_cited"] == "СП 3.13130.2009"
    assert outdated[0]["designation"] == "СП 3.13130.2026"
    rules = ppm110["norm_verification"]["edition_rules"]
    assert {
        "designation": "СП 3.13130.2009",
        "replaced_by": "СП 3.13130.2026",
        "effective_from": "2026-06-01",
        "applies_by": "PD_APPROVAL_DATE",
    } in rules
    for code in ("PZ-019", "PZ-020", "SPZU-027", "SPZU-028", "SPZU-031", "SPZU-033", "SPZU-035", "SPZU-037"):
        assert any(
            r["replaced_by"] == "СП 42.13330.2026"
            for r in reg.get(code)["norm_verification"]["edition_rules"]
        ), code
    assert (
        reg.get("SPZU-031")["norm_verification"]["references_not_found"][0]["designation"]
        == "СП 4.13130.2013"
    )


def test_threshold_decisions(reg: params.ParamRegistry) -> None:
    odi121 = reg.get("ODI-121")
    assert odi121.min_value == 3.6 and odi121["matrix_trigger_value"] == {"min": 3.5}
    assert odi121["threshold_source"] == "NORMATIVE_OVERRIDE"
    odi119 = reg.get("ODI-119")
    assert odi119.min_value == 1.7 and odi119["matrix_trigger_value"] == {"min": 1.5}
    sub = next(r for r in odi119.comparison_rule["sub_checks"] if r["sub_id"] == "ODI-119.a")
    assert {"if": {"var": "object.is_reconstruction"}, "min": 1.5} in sub["bounds"]["conditional"]
    ppm104 = reg.get("PPM-104")
    sub = next(r for r in ppm104.comparison_rule["sub_checks"] if r["sub_id"] == "PPM-104.a")
    assert ppm104.min_value == 1.2 and sub["bounds"]["conditional"][0]["min"] == 1.0
    assert sub["title"] == "Ширина эвакуационного прохода ниже нормы"
    odi117 = reg.get("ODI-117")  # D-04 closed by the verification
    assert odi117.min_value == 0.9 and odi117["matrix_trigger_value"] == {"min": 1.5}
    assert "D-04 закрыт" in odi117["threshold_note"]
    # A softer or conditional literal stays the trigger; the verified norm is recorded next to it.
    odi116 = reg.get("ODI-116")
    assert odi116.min_value == 1.5 and odi116["norm_verification"]["threshold"]["min_value"] == 1.8
    ppm105 = reg.get("PPM-105")
    assert (
        ppm105.min_value == 0.9
        and ppm105["norm_verification"]["threshold"]["status"] == "MATRIX_STRICTER_THAN_NORM"
    )
    spzu030 = next(
        r for r in reg.get("SPZU-030").comparison_rule["sub_checks"] if r["sub_id"] == "SPZU-030.a"
    )
    assert "п. 8.1.4" in spzu030["note"]
    decided = [p.code for p in reg if p["norm_verification"]["threshold_decision"]]
    assert set(decided) == {
        "ODI-121",
        "ODI-119",
        "PPM-104",
        "ODI-117",
        "ODI-116",
        "SPZU-030",
        "AR-040",
        "PPM-105",
        "SPZU-033",
    }


def test_threshold_notes_carry_only_verified_numbers(reg: params.ParamRegistry) -> None:
    import re

    for code in (
        "ODI-121",
        "ODI-119",
        "PPM-104",
        "ODI-117",
        "ODI-116",
        "SPZU-030",
        "AR-040",
        "PPM-105",
        "SPZU-033",
    ):
        spec = reg.get(code)
        note = re.sub(r"Матрицы\s+[<>≤≥]?\s*\d[\d,./–-]*\s*(?:мм|м|%)?", "Матрицы", spec["threshold_note"])
        assert params.unverified_numbers(note, params.verified_corpus([code])) == [], code


def test_threshold_status_vocabulary(reg: params.ParamRegistry) -> None:
    with open(params.seed_dir() / "schemas" / "params.schema.json", encoding="utf-8") as fh:
        schema = json.load(fh)
    vocabulary = set(schema["$defs"]["NormThresholdStatus"]["enum"])
    statuses = {p["norm_verification"]["threshold"]["status"] for p in reg}
    assert statuses <= vocabulary and len(statuses) == 9
    assert reg.get("SM-132")["norm_verification"]["threshold"]["status"] == "CUSTOMER_THRESHOLD"
    assert reg.get("SPZU-031")["norm_verification"]["threshold"]["status"] == "NO_BASIS_FOUND"


def test_moscow_waste_parameters_follow_the_2026_07_change(reg: params.ParamRegistry) -> None:
    oos098, oos100 = reg.get("OOS-098"), reg.get("OOS-100")
    assert oos098.parameter_name == 'Регистрация лимитов в АИС "ОСИГ"'  # the catalog wins on names
    assert oos098.comparison_rule["external_system"].startswith("АИС «ОССиГ»")
    assert "АИС «ОССиГ»" in oos098.semantic_anchors
    assert "1386-ПП" in oos098["other_normative"]
    assert oos100.comparison_rule["external_system"].startswith("Мобильный КПТС (рейсы до 01.07.2026)")
    assert "КПТС и smart.mos.ru не применяются" in oos100.comparison_rule["note"]
    assert [r["status"] for r in _refs(oos100)] == ["OUTDATED"]


def test_seed_schemas_reference_the_contract_enums() -> None:
    """M0 open issue closed: the seed schema vocabularies $ref the contract enums (the local copies stay for the
    AG-00 drift test), so a value outside the contract enum fails the seed schema."""
    with open(params.seed_dir() / "schemas" / "comparison_rule.schema.json", encoding="utf-8") as fh:
        cr = json.load(fh)
    with open(params.seed_dir() / "schemas" / "params.schema.json", encoding="utf-8") as fh:
        ps = json.load(fh)
    refs = {
        name: cr["$defs"][name]["$ref"]
        for name in ("RuleDirection", "RuleOperator", "DetectKind", "OrdinalScale", "AbstainReason")
    }
    refs["ParamExtractionStrategy"] = ps["$defs"]["ExtractionStrategy"]["$ref"]
    refs["TextOrigin"] = ps["$defs"]["TextOrigin"]["$ref"]
    refs["ThresholdSource"] = ps["$defs"]["Param"]["properties"]["threshold_source"]["$ref"]
    refs["FeasibilityTier"] = ps["$defs"]["Param"]["properties"]["feasibility_tier"]["$ref"]
    refs["CriticalityLevel"] = ps["$defs"]["Param"]["properties"]["criticality_level"]["$ref"]
    refs["HedgeKind"] = ps["properties"]["hedge_groups"]["items"]["properties"]["kind"]["$ref"]
    enums = load_enums()
    for name, ref in refs.items():
        assert ref == f"../schemas/enums.schema.json#/$defs/{name}" and name in enums
    with open(params.seed_dir() / "params.json", encoding="utf-8") as fh:
        bad = json.load(fh)
    bad["params"][0]["threshold_source"] = "NOT_A_SOURCE"
    bad["params"][1]["references"]["sp"].append(
        {"ref": "x", "confidence": "HIGH", "status": "GUESSED", "designation": "x"}
    )
    errors = params.seed_validation_errors("params", bad)
    assert any("threshold_source" in e for e in errors) and any("GUESSED" in e for e in errors)
