"""Scorer configuration: the H1 defaults of 93 §2.2 plus every variant switch of 93 §4.1/§4.3.

The organizers' formulas are unknown (the package gives only weights and the gate sentence), so every
assumption is a switch and every run reports the sensitivity of the total to each switch.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Literal

from inspector_common.hashing import config_hash

SCORER_VERSION = "0.1.0"
HYPOTHESIS = "H1"
NORMALIZATION_VERSION = "1"  # bump on any change of inspector_eval.normalize (93 §4.3: versioned)

Mode = Literal["strict", "light", "relaxed"]
MODES: tuple[Mode, ...] = ("strict", "light", "relaxed")

KeyVariant = Literal["k1", "k3", "k4"]
GroupRule = Literal["any", "majority", "all"]
LocMetric = Literal["recall", "jaccard", "anyhit"]
GateVariant = Literal["key", "strict", "broad"]
IntegrityMode = Literal["share", "hard"]
IntegrityRuleSet = Literal["r1_r15", "proto8"]

# Allowed values per switch (CLI choices and the sensitivity table).
CHOICES: dict[str, tuple[Any, ...]] = {
    "key": ("k1", "k3", "k4"),
    "group_rule": ("any", "majority", "all"),
    "loc_metric": ("recall", "jaccard", "anyhit"),
    "loc_with_stage": (True, False),
    "value_norm": ("strict", "light", "relaxed"),
    "location_norm": ("strict", "light", "relaxed"),
    "code_norm": ("strict", "light", "relaxed"),
    "criticality_norm": ("strict", "light", "relaxed"),
    "gate": ("key", "strict", "broad"),
    "integrity": ("share", "hard"),
    "integrity_rules": ("r1_r15", "proto8"),
}


@dataclass(frozen=True, slots=True)
class ScoreConfig:
    """H1 defaults (93 §2.2). ``key``:
    - k1: a check is (object_id, parameter_code, location); F1 over VIOLATION_PRESENT (primary);
    - k3: group-level F1 (a gold finding group counts as found per ``group_rule``);
    - k4: k1 plus at least one correct evidence page for a TP (a key hit with wrong pages is FP + FN).
    """

    key: KeyVariant = "k1"
    group_rule: GroupRule = "any"
    loc_metric: LocMetric = "recall"
    loc_with_stage: bool = True
    value_threshold: float = 0.85
    value_norm: Mode = "light"
    location_norm: Mode = "light"
    code_norm: Mode = "light"
    criticality_norm: Mode = "light"
    gate: GateVariant = "key"
    integrity: IntegrityMode = "share"
    integrity_rules: IntegrityRuleSet = "r1_r15"
    # value+status component: 0.5·status + 0.5·values; status = 0.5 label + 0.25 protocol + 0.25 criticality.
    status_share: float = 0.5
    status_label_weight: float = 0.5
    status_protocol_weight: float = 0.25
    status_criticality_weight: float = 0.25
    expected_split: str = "TRAIN_PUBLIC"
    hedge_budget: float = 0.20  # 97 §1.6: hedges ≤ 20 % of emitted critical checks

    def __post_init__(self) -> None:
        for name, allowed in CHOICES.items():
            if getattr(self, name) not in allowed:
                raise ValueError(f"{name}={getattr(self, name)!r}: expected one of {allowed}")
        if not 0.0 < self.value_threshold <= 1.0:
            raise ValueError("value_threshold must be in (0, 1]")

    def replace(self, **changes: Any) -> ScoreConfig:
        return dataclasses.replace(self, **changes)

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def describe(self) -> dict[str, Any]:
        """Config plus versions and its hash (recorded in score.json)."""
        body = {
            "scorer_version": SCORER_VERSION,
            "hypothesis": HYPOTHESIS,
            "normalization_version": NORMALIZATION_VERSION,
            **self.as_dict(),
        }
        return {**body, "config_hash": config_hash(body)}


DEFAULT_CONFIG = ScoreConfig()
