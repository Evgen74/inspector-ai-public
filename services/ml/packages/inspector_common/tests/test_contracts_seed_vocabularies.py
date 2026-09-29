"""The matrix seed (AG-03, packages/contracts/seed) and the contracts (AG-00) use one vocabulary.

The seed JSON Schemas keep their own enum copies in ``$defs``; contracts are law, so every copy must
equal the enum in ``enums.yaml``, and ``codes.yaml`` hedge pairs must equal the seed's hedge groups.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from inspector_common.contracts.loader import load_codes, load_enums
from inspector_common.paths import contracts_dir


def _seed_schema(name: str) -> dict[str, Any]:
    return json.loads(
        (contracts_dir() / "seed" / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
    )


def _at(doc: dict[str, Any], pointer: str) -> list[str]:
    node: Any = doc
    for part in pointer.strip("/").split("/"):
        node = node[part]
    return list(node["enum"])


# (seed schema, JSON pointer to the enum-bearing node, contract enum)
SEED_ENUMS = [
    ("comparison_rule", "/$defs/RuleDirection", "RuleDirection"),
    ("comparison_rule", "/$defs/RuleOperator", "RuleOperator"),
    ("comparison_rule", "/$defs/DetectKind", "DetectKind"),
    ("comparison_rule", "/$defs/AbstainReason", "AbstainReason"),
    ("comparison_rule", "/$defs/OrdinalScale", "OrdinalScale"),
    ("params", "/$defs/ExtractionStrategy", "ParamExtractionStrategy"),
    ("params", "/$defs/TextOrigin", "TextOrigin"),
    ("params", "/$defs/Param/properties/threshold_source", "ThresholdSource"),
    ("params", "/$defs/Param/properties/feasibility_tier", "FeasibilityTier"),
    ("params", "/properties/hedge_groups/items/properties/kind", "HedgeKind"),
    ("params", "/$defs/Param/properties/criticality_level", "CriticalityLevel"),
]


@pytest.mark.parametrize(("schema", "pointer", "enum_name"), SEED_ENUMS, ids=[e[2] for e in SEED_ENUMS])
def test_seed_schema_enums_equal_contract_enums(schema: str, pointer: str, enum_name: str) -> None:
    seed_values = _at(_seed_schema(schema), pointer)
    contract_values = list(load_enums()[enum_name].codes)
    # The seed covers the two catalog criticality levels; INFORMATIONAL is display-only.
    if enum_name == "CriticalityLevel":
        assert set(seed_values) <= set(contract_values)
    else:
        assert seed_values == contract_values


def test_codes_yaml_hedge_pairs_equal_the_seed_hedge_groups() -> None:
    params = json.loads((contracts_dir() / "seed" / "params.json").read_text(encoding="utf-8"))
    seed_groups = [list(g["codes"]) for g in params["hedge_groups"]]
    assert [list(p) for p in load_codes()["hedge_pairs"]] == seed_groups
    kinds = {g["kind"] for g in params["hedge_groups"]}
    assert kinds <= set(load_enums()["HedgeKind"].codes)


def test_free_topics_seed_equals_the_contract_enum() -> None:
    seed = json.loads((contracts_dir() / "seed" / "free_topics.json").read_text(encoding="utf-8"))
    assert sorted(t["topic"] for t in seed["topics"]) == sorted(load_enums()["FreeTopic"].codes)
