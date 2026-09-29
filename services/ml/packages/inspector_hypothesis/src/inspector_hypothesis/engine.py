"""One hypothesis run for one object: FREE element groups + Logical_Rules → SUSPICIONs (ТЗ §9.5, Module 5).

AG-04 calls this in-process from ``compare``/``export`` (FREE-* findings have no batch command of their own):

    from inspector_hypothesis import HypothesisInputs, run_hypotheses

    inputs = HypothesisInputs.from_run(ctx.run_dir, object_id)
    result = run_hypotheses(inputs)
    groups   += result.free_groups        # FindingGroup, matrix_scope FREE_SEARCH → findings/<object>.groups.jsonl
    findings += result.free_findings      # Finding (atomic, one per room)          → findings/<object>.jsonl
    section6  = result.section6_rows(first_card_no)   # Приложение 2 Раздел 6 (SuspicionRow)
    a5        = result.a5_rows(first_card_no)         # Приложение А.5 (HypothesisRow)

A detector failure never fails the run (CON-39): it is recorded in ``stats.detector_status`` and the other detector
still delivers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from inspector_common.contracts.models import Finding, FindingGroup, HypothesisRow, SuspicionRow
from inspector_common.params import load_params
from inspector_hypothesis import __version__
from inspector_hypothesis.elements import ElementIndex
from inspector_hypothesis.facts import FactBuilder, referenced_families
from inspector_hypothesis.free import FreeCandidate, FreeConfig, FreeDetector, to_contract
from inspector_hypothesis.inputs import HypothesisInputs
from inspector_hypothesis.logic import LANGUAGE
from inspector_hypothesis.rules import RuleEngine, RuleOutcome, RuleSet, load_seed_rules, outcome_counts
from inspector_hypothesis.suspicion import (
    Suspicion,
    a5_rows,
    finalize,
    from_free_candidate,
    from_rule_outcome,
    section6_rows,
)
from inspector_hypothesis.valueconflict import ConflictConfig, value_conflict_suspicions

log = logging.getLogger(__name__)

PIPELINE_VERSION = f"hypothesis-{__version__}"
# FREE candidates that become SUSPICIONs: RD read and the element absent (whole discipline, the plan's document, or
# at the rooms). PRESENT, NO_RD (a MISSING_DOCUMENT matter) and UNKNOWN (RD not read) stay in the statistics only.
SUSPICION_ABSENCE = frozenset({"DOCUMENT", "COUNTERPART", "ROOM"})


@dataclass(frozen=True, slots=True)
class HypothesisConfig:
    free: FreeConfig = field(default_factory=FreeConfig)
    enable_free: bool = True
    enable_rules: bool = True
    enable_value_conflicts: bool = True
    value_conflict: ConflictConfig = field(default_factory=ConflictConfig)

    def config_hash(self, rules: RuleSet) -> str:
        blob = json.dumps({"config": asdict(self), "rules_sha256": rules.sha256}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class HypothesisResult:
    object_id: str
    run_id: str | None
    free_candidates: list[FreeCandidate]
    free_groups: list[FindingGroup]
    free_findings: list[Finding]
    suspicions: list[Suspicion]
    rule_outcomes: list[RuleOutcome]
    stats: dict[str, Any]
    versions: dict[str, str]

    def section6_rows(self, first_card_no: int = 1) -> list[SuspicionRow]:
        """Rows of Приложение 2 Раздел 6, numbered 1…n; evidence cards Б.<first_card_no>… in the same order."""
        return section6_rows(self.suspicions, first_card_no)

    def a5_rows(self, first_card_no: int = 1) -> list[HypothesisRow]:
        return a5_rows(self.suspicions, first_card_no)

    @property
    def ai_suspicions_count(self) -> int:
        """Раздел 2 «Подозрений ИИ (свободный поиск)»: every suspicion of this version (93 §5.4)."""
        return len(self.suspicions)

    def to_json(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "run_id": self.run_id,
            "versions": self.versions,
            "stats": self.stats,
            "free_groups": [g.dump() for g in self.free_groups],
            "free_findings": [f.dump() for f in self.free_findings],
            "suspicions": [s.dump() for s in self.suspicions],
            "rule_outcomes": [o.trace() for o in self.rule_outcomes if o.status != "NOT_APPLICABLE"],
        }


def run_hypotheses(
    inputs: HypothesisInputs,
    config: HypothesisConfig | None = None,
    rules: RuleSet | None = None,
) -> HypothesisResult:
    config = config or HypothesisConfig()
    rules = rules or load_seed_rules()
    t0 = time.perf_counter()
    timings: dict[str, float] = {}
    detector_status: dict[str, str] = {}
    index = ElementIndex(inputs)

    candidates: list[FreeCandidate] = []
    groups: list[FindingGroup] = []
    findings: list[Finding] = []
    suspicions: list[Suspicion] = []
    if config.enable_free:
        t = time.perf_counter()
        try:
            detector = FreeDetector(inputs, index, config.free)
            candidates = detector.select(detector.detect())
            for cand in candidates:
                if cand.exported:
                    g, fs = to_contract(cand, inputs, inputs.run_id)
                    groups.append(g)
                    findings.extend(fs)
                # a suspicion needs a PD page showing the rooms and some proof of absence in RD; else statistics only
                if cand.absence in SUSPICION_ABSENCE and cand.pd_anchor is not None:
                    suspicions.append(from_free_candidate(cand, inputs, inputs.run_id))
            detector_status["SEMANTIC_DISSONANCE"] = "OK"
        except Exception as exc:  # a detector failure never fails the run (CON-39)
            detector_status["SEMANTIC_DISSONANCE"] = f"FAILED: {type(exc).__name__}: {exc}"
            log.exception("hyp.free_failed", extra={"object_id": inputs.object_id})
        timings["free_s"] = round(time.perf_counter() - t, 3)

    outcomes: list[RuleOutcome] = []
    if config.enable_rules:
        t = time.perf_counter()
        try:
            engine = RuleEngine(rules)
            exprs = [
                e for r in engine.rules for e in (r.condition, r.expected, r.applicability, *r.let.values())
            ]
            facts = FactBuilder(inputs, index).build(referenced_families(exprs))
            timings["facts_s"] = round(time.perf_counter() - t, 3)
            outcomes = engine.evaluate(facts)
            suspicions.extend(from_rule_outcome(o, inputs, inputs.run_id) for o in outcomes if o.emitted)
            detector_status["LOGICAL_ANALYSIS"] = "OK"
        except Exception as exc:
            detector_status["LOGICAL_ANALYSIS"] = f"FAILED: {type(exc).__name__}: {exc}"
            log.exception("hyp.rules_failed", extra={"object_id": inputs.object_id})
        timings["rules_s"] = round(time.perf_counter() - t, 3)

    if config.enable_value_conflicts:
        t = time.perf_counter()
        try:  # contradicting values of one stage (ТЗ §9.5): a suspicion, never a violation
            suspicions.extend(value_conflict_suspicions(inputs, inputs.run_id, config.value_conflict))
            detector_status["VALUE_CONFLICT"] = "OK"
        except Exception as exc:
            detector_status["VALUE_CONFLICT"] = f"FAILED: {type(exc).__name__}: {exc}"
            log.exception("hyp.value_conflict_failed", extra={"object_id": inputs.object_id})
        timings["value_conflict_s"] = round(time.perf_counter() - t, 3)

    suspicions = finalize(suspicions)
    timings["total_s"] = round(time.perf_counter() - t0, 3)
    versions = {
        "pipeline_version": PIPELINE_VERSION,
        "rules_language": LANGUAGE,
        "rules_set_version": rules.rules_set_version,
        "rules_sha256": rules.sha256,
        "matrix_version": load_params().matrix_version,
        "config_hash": config.config_hash(rules),
    }
    stats = {
        "detector_status": detector_status,
        "timings": timings,
        "pages_scanned": index.pages_scanned,
        "free": {
            "candidates": len(candidates),
            "exported_groups": len(groups),
            "exported_findings": len(findings),
            "by_absence": _count(c.absence for c in candidates),
            "not_exported": {c.family.family: c.reasons for c in candidates if not c.exported},
        },
        "rules": {
            "evaluated": len(rules.active),
            "outcomes": outcome_counts(outcomes),
            "emitted": sum(1 for o in outcomes if o.emitted),
        },
        "suspicions": {
            "total": len(suspicions),
            "exported": sum(1 for s in suspicions if s.exported),
            "by_method": _count(str(s.discovery_method) for s in suspicions),
            "by_priority": _count(str(s.review_priority) for s in suspicions),
        },
        "input_problems": list(inputs.problems),
    }
    log.info(
        "hyp.run_done",
        extra={
            "object_id": inputs.object_id,
            "free_groups": len(groups),
            "suspicions": len(suspicions),
            "total_s": timings["total_s"],
        },
    )
    return HypothesisResult(
        inputs.object_id, inputs.run_id, candidates, groups, findings, suspicions, outcomes, stats, versions
    )


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items()))
