"""Matrix seed (packages/contracts/seed): structure, contracts and internal consistency. Owner: AG-03."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from inspector_common import params
from inspector_common.contracts import codes
from inspector_common.contracts.enums import (
    CriticalityLevel,
    FreeTopic,
    ParameterMappingStatus,
    ReviewPriority,
)
from inspector_common.contracts.loader import enum_mappings, load_codes, load_enums
from inspector_common.hashing import sha256_json


@pytest.fixture(scope="module")
def reg() -> params.ParamRegistry:
    return params.load_params()


@pytest.fixture(scope="module")
def doc() -> dict:
    with open(params.seed_dir() / "params.json", encoding="utf-8") as fh:
        return json.load(fh)


def _atomic(rule: dict) -> list[dict]:
    return rule["sub_checks"] if rule["rule_type"] == "COMPOSITE" else [rule]


@pytest.mark.parametrize("name", sorted(params.SEED_FILES))
def test_seed_files_match_their_schemas(name: str) -> None:
    assert params.seed_validation_errors(name) == []


def test_cross_file_consistency() -> None:
    assert params.seed_consistency_problems() == []


def test_132_parameters_with_unique_catalog_codes(reg: params.ParamRegistry) -> None:
    assert len(reg) == 132
    assert [p.param_id for p in reg] == list(range(1, 133))
    all_codes = [p.code for p in reg]
    assert len(set(all_codes)) == 132
    assert all_codes[0] == "PZ-001" and all_codes[-1] == "SM-132"
    assert all(p.code == codes.canonical_code(p.param_id) for p in reg)
    assert all(len(p.code) <= 20 for p in reg)  # ТЗ §8.1 code VARCHAR(20)


def test_aliases_are_unique_across_parameters(reg: params.ParamRegistry) -> None:
    seen: Counter[str] = Counter()
    for p in reg:
        assert p.alias_codes[0] == f"M-{p.param_id:03d}"
        seen.update(
            {a.upper() for a in (p.code, *p.alias_codes)}
        )  # «OOS-100»: the short form equals the code
    assert [a for a, n in seen.items() if n > 1] == []


def test_criticality_counts_and_mapping(reg: params.ParamRegistry, doc: dict) -> None:
    levels = Counter(p.criticality_level for p in reg)
    assert levels == {CriticalityLevel.CRITICAL_SUSPEND: 106, CriticalityLevel.SUBSTANTIAL_ORDER: 26}
    strings = Counter(p.criticality for p in reg)
    assert strings == {"Критическое (приостановка работ)": 106, "Существенное (предписание)": 26}
    for p in reg:  # the exact catalog string, the level and the review priority agree (97 §2.8)
        attrs = load_enums()["CriticalityLevel"].value(p.criticality_level).attrs
        assert attrs["catalog_string"] == p.criticality
        assert ReviewPriority(attrs["review_priority"]) is p.review_priority
    assert doc["counts"]["criticality"] == {"CRITICAL_SUSPEND": 106, "SUBSTANTIAL_ORDER": 26}


def test_criticality_level_helper(reg: params.ParamRegistry) -> None:
    assert params.criticality_level(55) is CriticalityLevel.CRITICAL_SUSPEND
    assert params.criticality_level("СПЗУ-25") is CriticalityLevel.SUBSTANTIAL_ORDER
    assert params.criticality_level("M-003") is CriticalityLevel.SUBSTANTIAL_ORDER


def test_sections_short_and_catalog(reg: params.ParamRegistry) -> None:
    for p in reg:
        prefix = codes.prefix_for_id(p.param_id)
        assert p.section == prefix.cyrillic and p.pd_section == prefix.section
        assert len(p.section) <= 50 and (p.unit is None or len(p.unit) <= 20)  # ТЗ §8.1 lengths
        assert len(p.parameter_name) <= 255


def test_catalog_row_projection(reg: params.ParamRegistry) -> None:
    row = reg.get("IOS4-079").to_catalog_row()
    assert row.parameter_code == "IOS4-079" and row.criticality == "Критическое (приостановка работ)"
    assert row.mapping_status is ParameterMappingStatus.SOURCE_MATRIX
    assert params.get_param(79).display == f"{reg.get(79).short_name} (IOS4-079)"


def test_dsl_every_atomic_rule_has_direction_and_policy(reg: params.ParamRegistry) -> None:
    n = 0
    for p in reg:
        for r in _atomic(p.comparison_rule):
            n += 1
            assert r["direction"] in {"ANY", "DECREASE", "INCREASE", "DOWNGRADE"}
            assert r["candidate_policy"] in {"TRIGGER", "DEVIATION"}
            assert r["on_trigger"] == "CANDIDATE" and r["on_pass"] == "NEGATIVE_VERIFIED"
            assert r["rule_type"] != "INTERNAL_CONSISTENCY"
            assert "on_trigger_fallback" not in r
            if r["rule_type"] == "ORDINAL_COMPARE":
                assert r["direction"] == "DOWNGRADE"
            if (
                r["rule_type"] in ("NORMATIVE_BOUND", "TOLERANCE_CHECK")
                or r.get("operator") == "REL_DELTA_GT"
            ):
                assert r["candidate_policy"] == "TRIGGER"
    assert n == 214  # 218 atomic sub-checks of 03 §3.4 minus the 4 INTERNAL_CONSISTENCY moved out (90 C-53)


def test_internal_consistency_moved_to_logical_rules(doc: dict, reg: params.ParamRegistry) -> None:
    moved = {m["sub_id"]: m for m in doc["moved_to_logical_rules"]}
    assert set(moved) == {"PZ-002.b", "PZ-003.c", "PZ-010.b", "PZ-019.c"}
    assert moved["PZ-003.c"]["logical_rule"] == "HR-LOG-005"
    for sub_id in moved:
        assert sub_id not in reg.get(sub_id.split(".")[0])["atomic_sub_checks"]


def test_directional_triggers(reg: params.ParamRegistry) -> None:
    """97 §2.10 + user decision on 97 Q4: a thicker slab / higher class is not a violation."""
    rules = {r.get("sub_id", p.code): r for p in reg for r in _atomic(p.comparison_rule)}
    assert rules["KR-058.a"]["direction"] == "DECREASE" and rules["KR-058.b"]["direction"] == "DECREASE"
    assert rules["KR-055"]["direction"] == "DOWNGRADE"
    assert rules["KR-054.b"]["direction"] == "ANY"
    assert rules["PZ-002.a"]["candidate_policy"] == "TRIGGER"  # «> 1 %»
    assert rules["PZ-003.a"]["candidate_policy"] == "DEVIATION"  # qualitative «сокращение»


def test_ventilation_rules_follow_organizer_routing(reg: params.ParamRegistry) -> None:
    rules = {r.get("sub_id"): r for p in reg for r in _atomic(p.comparison_rule)}
    b = rules["IOS4-078.b"]
    assert (
        b["element_key"] == "room_number"
        and b["detect"] == ["MISSING", "CHANGED"]
        and b["context_detect"] == ["ADDED"]
    )
    assert rules["IOS4-079.b"]["element_key"] == "room_number"
    assert "тёплый пол" not in reg.get("IOS4-077").semantic_anchors  # warm floors → FREE-HEATING (97 §2.10)
    assert "тепл" not in reg.get("IOS4-077").regex_pattern


def test_linked_and_hedge_groups(reg: params.ParamRegistry) -> None:
    assert reg.get("AR-040").linked_params == ("PPM-104",)
    assert reg.hedge_codes("AR-040") == ("PPM-104", "ODI-116")
    assert reg.hedge_codes("IOS4-079") == ("IOS4-078",)
    assert reg.hedge_codes("PZ-001") == ()
    for pair in load_codes()["hedge_pairs"]:  # AG-00's codes.yaml list is covered
        assert any(set(pair) <= set(g) for g in reg.hedge_groups)
    for group in reg.hedge_groups:
        for code in group:
            assert reg.get(code).hedge_group == group


def test_text_fields(reg: params.ParamRegistry, doc: dict) -> None:
    assert doc["counts"]["short_names_from_appendix2"] == 27
    assert reg.get("KR-055").short_name == "Класс бетона"
    assert reg.get("AR-040").short_name == "Ширина эвакуационных коридоров"
    assert reg.get("KR-067").name_variants == ("Расход бетона (общий объём)",)
    for p in reg:
        assert p["work_type"] and p["recommendation_template"] and p["element_nouns"]
        assert set(p["deviation_verb"]) <= set(load_enums()["DiscrepancyType"].codes)
    assert reg.get("KR-055")["deviation_verb"]["CLASS_DOWNGRADED"] == "Понижение класса"
    assert reg.get("PPM-103")["deviation_verb"]["CLASS_DOWNGRADED"] == "Снижение предела"


def test_content_hash_is_reproducible(doc: dict) -> None:
    content = {k: doc[k] for k in ("params", "context_gates", "hedge_groups", "moved_to_logical_rules")}
    assert sha256_json(content) == doc["content_sha256"]
    assert params.load_params().content_sha256 == doc["content_sha256"]
    assert doc["matrix_version"] == "1.1.1"  # M1: verified norms and templates (1.1.0 = M0 seed)


def test_free_topics_match_the_enum() -> None:
    topics = params.load_free_topics()
    assert sorted(topics) == sorted(t.value for t in FreeTopic)
    assert topics["HEATING"].code(1) == "FREE-HEATING-001"
    with open(params.seed_dir() / "free_topics.json", encoding="utf-8") as fh:
        free = json.load(fh)
    assert free["criticality"] == enum_mappings()["free_search"]["criticality_string"]
    assert free["protocol_status"] == "WARNING"


def test_seed_changes_are_documented(doc: dict) -> None:
    changed = {c["code"] for c in doc["seed_changes"]}
    assert {"AR-044", "PPM-109", "KR-055", "IOS4-077", "PZ-002"} <= changed
    assert all(c["reason"] for c in doc["seed_changes"])


def test_loader_errors(tmp_path) -> None:
    with pytest.raises(params.SeedError):
        params.load_params(tmp_path)
    (tmp_path / "params.json").write_text("{", encoding="utf-8")
    with pytest.raises(params.SeedError):
        params.load_params(tmp_path)
