"""Logical_Rules (ТЗ §10 #9: id, rule_name, condition, expected, normative_base, is_active) and their evaluation.

A rule reads «if condition then expected» (ТЗ §9.5 approach 1). It is evaluated once per object, or once per item
of a fact collection (``scope.for_each``). Named sub-expressions (``let``) are evaluated first and are visible to
``applicability``, ``condition`` and ``expected`` as ``let.<name>`` and to the Russian message templates.

Outcome per subject: NOT_APPLICABLE (applicability FALSE), UNKNOWN (applicability, condition or expected UNKNOWN:
facts missing), SATISFIED (condition FALSE, or expected TRUE), EMITTED (condition TRUE and expected FALSE → one
SUSPICION). UNKNOWN never emits.

Seed rules: ``data/logical_rules.json`` (12 rules, IAI-Logic v1). The set is versioned: ``rules_set_version`` plus
the sha256 of the canonical JSON of the active rules (ТЗ §9.2 п.1: versions are fixed in every run).
"""

from __future__ import annotations

import hashlib
import json
import re
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from inspector_common.contracts.enums import DiscoveryMethod, ReviewPriority
from inspector_hypothesis.logic import (
    UNKNOWN,
    Evaluator,
    LogicError,
    Truth,
    truth,
    truth_label,
    validate_expression,
)
from inspector_hypothesis.textmatch import fmt_number

RULE_CODE_PATTERN = r"^HR-(LOG|SEM|NRM|MLP|GRA)-[0-9]{3}$"
Severity = Literal["HIGH", "MEDIUM", "LOW"]
SubjectType = Literal["OBJECT", "TABLE", "ROOM", "ELEMENT", "DOCUMENT", "ACT", "STAGE"]


class RuleScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    for_each: str | None = None  # dotted path to a list in the facts; each element is bound to «item»
    subject_type: SubjectType = "OBJECT"
    subject: str = "object"  # format template of the subject key («{item[block_id]}»)
    evidence: str | None = "item.evidence"  # dotted path to a list of evidence dicts
    stage: str | None = "item.stage"  # dotted path to the stage the item comes from
    # format template of the item's *content* (§9.5 dedup): outcomes with the same content are one suspicion even
    # when printed in several documents (the same explication on the floor plans of ОВ1 and ОВ2.1)
    dedup: str | None = None


class NormCheck(BaseModel):
    """How the rule's normative reference was checked against the review-phase norm verification (not the expert
    review: ``LogicalRule.verified`` stays false until then)."""

    model_config = ConfigDict(extra="forbid")

    # CONFIRMED: document and clause confirmed; DOCUMENT_CONFIRMED: the document is current, the clause was not
    # checked; CORRECTED: an outdated edition was replaced by the current one; NOT_IN_STAGING: not checked at all
    status: Literal["CONFIRMED", "DOCUMENT_CONFIRMED", "CORRECTED", "NOT_IN_STAGING"]
    source: str
    evidence: str | None = None
    note: str | None = None


class LogicalRule(BaseModel):
    """One Logical_Rules row (ТЗ §10 #9 fields first, then ours; 90 §3.3 #9)."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    rule_name: str = Field(min_length=3)
    condition: Any
    expected: Any
    normative_base: str
    is_active: bool = True

    rule_code: str = Field(pattern=RULE_CODE_PATTERN)
    version: int = Field(ge=1)
    discovery_method: DiscoveryMethod = DiscoveryMethod.LOGICAL_ANALYSIS
    description: str
    scope: RuleScope = Field(default_factory=RuleScope)
    applicability: Any | None = None
    let: dict[str, Any] = Field(default_factory=dict)
    severity: Severity
    base_confidence: float = Field(ge=0.0, le=1.0)
    promotable: bool = False
    message_template: str
    expected_template: str | None = None
    actual_template: str | None = None
    cells: dict[str, str | None] = Field(default_factory=dict)  # «PD»/«RD»/«ID» or «*» (the item's stage)
    normative_refs: list[str] = Field(default_factory=list)
    verified: bool = False
    norm_check: NormCheck | None = None
    overlaps_matrix_codes: list[str] = Field(default_factory=list)
    example: str | None = None

    @field_validator("condition", "expected", "applicability")
    @classmethod
    def _valid_expression(cls, v: Any) -> Any:
        if v is None:
            return v
        problems = validate_expression(v)
        if problems:
            raise ValueError("; ".join(problems))
        return v

    @field_validator("let")
    @classmethod
    def _valid_lets(cls, v: dict[str, Any]) -> dict[str, Any]:
        for name, expr in v.items():
            if not name.isidentifier():
                raise ValueError(f"let name {name!r} is not an identifier")
            problems = validate_expression(expr)
            if problems:
                raise ValueError(f"let.{name}: " + "; ".join(problems))
        return v

    @field_validator("cells")
    @classmethod
    def _valid_cells(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        bad = set(v) - {"PD", "RD", "ID", "*"}
        if bad:
            raise ValueError(f"cells keys must be PD, RD, ID or *: {sorted(bad)}")
        return v

    @model_validator(mode="after")
    def _templates_parse(self) -> LogicalRule:
        for t in (
            self.message_template,
            self.expected_template,
            self.actual_template,
            self.scope.subject,
            self.scope.dedup,
            *self.cells.values(),
        ):
            if t:
                list(string.Formatter().parse(t))  # raises ValueError on a malformed template
        return self

    @property
    def rule_ref(self) -> str:
        return f"{self.rule_code}@{self.version}"

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class RuleSet:
    rules: tuple[LogicalRule, ...]
    rules_set_version: str
    language: str

    @property
    def active(self) -> tuple[LogicalRule, ...]:
        return tuple(r for r in self.rules if r.is_active)

    @property
    def sha256(self) -> str:
        blob = json.dumps(
            [r.canonical() for r in self.active], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, rule_code: str) -> LogicalRule:
        for r in self.rules:
            if r.rule_code == rule_code:
                return r
        raise KeyError(rule_code)


def parse_rule_set(document: Mapping[str, Any]) -> RuleSet:
    rules = tuple(LogicalRule.model_validate(r) for r in document["rules"])
    codes = [r.rule_code for r in rules]
    ids = [r.id for r in rules]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate rule_code in the rule set")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate id in the rule set")
    return RuleSet(rules, str(document["rules_set_version"]), str(document.get("language", "IAI-Logic v1")))


@cache
def load_seed_rules() -> RuleSet:
    """The 12 seed Logical_Rules shipped with the package (``data/logical_rules.json``)."""
    text = (
        resources.files("inspector_hypothesis")
        .joinpath("data/logical_rules.json")
        .read_text(encoding="utf-8")
    )
    return parse_rule_set(json.loads(text))


# ───────────────────────────────────────────── Evaluation ─────────────────────────────────────────────

OutcomeStatus = Literal["EMITTED", "SATISFIED", "NOT_APPLICABLE", "UNKNOWN", "ERROR"]


@dataclass(slots=True)
class RuleOutcome:
    rule: LogicalRule
    subject_key: str
    item: Mapping[str, Any] | None
    applicable: Truth
    condition: Truth
    expected: Truth
    values: dict[str, Any] = field(default_factory=dict)
    used_facts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def status(self) -> OutcomeStatus:
        if self.error:
            return "ERROR"
        if self.applicable is False:
            return "NOT_APPLICABLE"
        if self.condition is False or self.expected is True:
            return "SATISFIED" if self.applicable is True else "UNKNOWN"
        if self.applicable is True and self.condition is True and self.expected is False:
            return "EMITTED"
        return "UNKNOWN"

    @property
    def emitted(self) -> bool:
        return self.status == "EMITTED"

    @property
    def stage(self) -> str | None:
        if self.rule.scope.stage is None:
            return None
        v = _path(self._root(), self.rule.scope.stage)
        return None if v is UNKNOWN else str(v)

    @property
    def evidence(self) -> list[dict[str, Any]]:
        if self.rule.scope.evidence is None:
            return []
        v = _path(self._root(), self.rule.scope.evidence)
        return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []

    def _root(self) -> Mapping[str, Any]:
        root: dict[str, Any] = dict(self.values.get("_facts_ref", {}))
        root["item"] = self.item or {}
        root["let"] = {k: v for k, v in self.values.items() if not k.startswith("_")}
        return root

    def trace(self) -> dict[str, Any]:
        return {
            "rule": self.rule.rule_ref,
            "subject": self.subject_key,
            "status": self.status,
            "applicable": truth_label(self.applicable),
            "condition": truth_label(self.condition),
            "expected": truth_label(self.expected),
            "values": {k: _jsonable(v) for k, v in self.values.items() if not k.startswith("_")},
            "facts": {k: _jsonable(v) for k, v in self.used_facts.items()},
            **({"error": self.error} if self.error else {}),
        }

    # Russian texts ------------------------------------------------------------------------------------
    def render(self, template: str | None) -> str | None:
        """Fill a Russian template. «[[ … ]]» marks an optional fragment, dropped when a value in it is missing."""
        if not template:
            return None
        display = _Display(self._display_root())

        def optional(m: re.Match[str]) -> str:
            probe = _Probe(display)
            text = string.Formatter().vformat(m.group(1), (), probe)
            return "" if probe.missing else text

        filled = _OPTIONAL.sub(optional, template)
        return re.sub(r"\s{2,}", " ", string.Formatter().vformat(filled, (), display)).strip()

    def _display_root(self) -> dict[str, Any]:
        decimals = None
        if self.item and isinstance(self.item.get("decimals"), int):
            decimals = self.item["decimals"]
        root = {k: v for k, v in self.values.items() if not k.startswith("_")}
        stage = self.stage
        return {
            "item": self.item or {},
            "let": root,
            "_decimals": decimals,
            "stage_ru": _STAGE_RU.get(stage or "", "—"),
            **root,
        }


def _path(root: Mapping[str, Any], path: str) -> Any:
    cur: Any = root
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return UNKNOWN
    return cur


def _jsonable(v: Any) -> Any:
    if v is UNKNOWN:
        return "UNKNOWN"
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, list):
        return [_jsonable(x) for x in v[:20]]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in list(v.items())[:20]}
    return v


_OPTIONAL = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_STAGE_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}


class _Probe(dict[str, Any]):
    """Formats like _Display and remembers whether any value used was missing."""

    def __init__(self, display: _Display):
        super().__init__()
        self._display = display
        self.missing = False

    def __missing__(self, key: str) -> Any:
        value = self._display[key]
        return _ProbeValue(value, self)


class _ProbeValue:
    def __init__(self, value: Any, probe: _Probe):
        self.value, self.probe = value, probe
        if value in ("нет данных", "—"):
            probe.missing = True

    def __getitem__(self, key: str) -> Any:
        return _ProbeValue(self.value[key] if isinstance(self.value, Mapping) else "нет данных", self.probe)

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)


class _Display(dict[str, Any]):
    """Values for message templates: numbers in Russian format, UNKNOWN as «нет данных», None as «—»."""

    def __init__(self, root: Mapping[str, Any]):
        super().__init__(root)
        self._decimals = root.get("_decimals")

    def __getitem__(self, key: str) -> Any:
        return _display(super().__getitem__(key), self._decimals)

    def __missing__(self, key: str) -> Any:
        return "нет данных"


def _display(v: Any, decimals: int | None) -> Any:
    if v is UNKNOWN:
        return "нет данных"
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, float):
        return fmt_number(v, decimals if decimals is not None else (0 if v.is_integer() else None))
    if isinstance(v, str) and (m := _ISO_DATE.match(v)):
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    if isinstance(v, Mapping):
        return _Display({**v, "_decimals": decimals}) if not isinstance(v, _Display) else v
    return v


class RuleEngine:
    """Evaluates a rule set on one fact sheet."""

    def __init__(self, rules: RuleSet | Iterable[LogicalRule] | None = None):
        if rules is None:
            rules = load_seed_rules()
        self.rules: tuple[LogicalRule, ...] = (
            rules.active if isinstance(rules, RuleSet) else tuple(r for r in rules if r.is_active)
        )

    def evaluate(self, facts: Mapping[str, Any]) -> list[RuleOutcome]:
        out: list[RuleOutcome] = []
        for rule in self.rules:
            out.extend(self.evaluate_rule(rule, facts))
        return out

    def evaluate_rule(self, rule: LogicalRule, facts: Mapping[str, Any]) -> list[RuleOutcome]:
        if rule.scope.for_each is None:
            items: list[Mapping[str, Any] | None] = [None]
        else:
            coll = _path(facts, rule.scope.for_each)
            items = [x for x in coll if isinstance(x, Mapping)] if isinstance(coll, list) else []
        return [self._one(rule, facts, item) for item in items]

    def _one(
        self, rule: LogicalRule, facts: Mapping[str, Any], item: Mapping[str, Any] | None
    ) -> RuleOutcome:
        root: dict[str, Any] = dict(facts)
        root["item"] = item or {}
        ev = Evaluator(root)
        values: dict[str, Any] = {}
        try:
            lets: dict[str, Any] = {}
            root["let"] = lets
            for name, expr in rule.let.items():
                lets[name] = ev.evaluate(expr)
            values.update(lets)
            applicable: Truth = True if rule.applicability is None else ev.truth(rule.applicability)
            cond = ev.truth(rule.condition) if applicable is not False else UNKNOWN
            exp = ev.truth(rule.expected) if applicable is not False and cond is not False else UNKNOWN
            error = None
        except LogicError as exc:
            applicable, cond, exp, error = UNKNOWN, UNKNOWN, UNKNOWN, str(exc)
        subject = _subject(rule, item)
        values["_facts_ref"] = facts
        outcome = RuleOutcome(rule, subject, item, applicable, cond, exp, values, dict(ev.used), error)
        return outcome


def _subject(rule: LogicalRule, item: Mapping[str, Any] | None) -> str:
    try:
        return string.Formatter().vformat(rule.scope.subject, (), _Display({"item": item or {}}))
    except (KeyError, IndexError, ValueError, AttributeError):
        return rule.scope.subject


def outcome_counts(outcomes: Iterable[RuleOutcome]) -> dict[str, dict[str, int]]:
    """Per rule: how many subjects ended in each status (for the run statistics)."""
    out: dict[str, dict[str, int]] = {}
    for o in outcomes:
        d = out.setdefault(o.rule.rule_code, {})
        d[o.status] = d.get(o.status, 0) + 1
    return dict(sorted(out.items()))


def review_priority(severity: str, confidence: float) -> ReviewPriority:
    """07 §3.4: HIGH severity → HIGH (conf ≥ 0.6) / MEDIUM; MEDIUM → MEDIUM / LOW; LOW → LOW."""
    if severity == "HIGH":
        return ReviewPriority.HIGH if confidence >= 0.6 else ReviewPriority.MEDIUM
    if severity == "MEDIUM":
        return ReviewPriority.MEDIUM if confidence >= 0.6 else ReviewPriority.LOW
    return ReviewPriority.LOW


__all__ = [
    "LogicalRule",
    "RuleEngine",
    "RuleOutcome",
    "RuleScope",
    "RuleSet",
    "load_seed_rules",
    "outcome_counts",
    "parse_rule_set",
    "review_priority",
    "truth",
]
