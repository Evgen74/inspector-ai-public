"""Stage resolution from generic signals (97 §2.12: RD_ID_MIXED / UNKNOWN resolved per file).

Signals, in increasing weight:
- folder names of the manifest ``relative_path``;
- the file name;
- the text layer of the first pages (title pages, cover sheets and act headings), when present.

Rules are phrased on nominative forms on purpose: an act («АКТ освидетельствования…») cites
«рабочей документации» and «проектной документации» in the genitive, and an RD «Общие данные»
sheet lists «актов освидетельствования» in the plural genitive — neither must vote for its stage.
«Исходные данные» (and «П-ИД») are ПД appendices, never executive documentation (97 §2.12).

The result is recorded with MetaSource EXTRACTED_UNCONFIRMED; the manifest stage stays the raw
ManifestStage. For rows whose manifest stage is PD/RD/ID the manifest is authoritative (REGISTRY) and
the signals are only used to report a strong disagreement (META_CONFLICT, informational).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from inspector_common.contracts.enums import DocStage, ManifestStage, MetaSource
from inspector_registry.names import clean_name

STAGE_RULES_VERSION = "stage-signals-1"
STAGES = (DocStage.PD.value, DocStage.RD.value, DocStage.ID.value)

_TOKEN_SEP = r"(?:^|[\s/_.\-()])"
_TOKEN_END = r"(?:$|[\s/_.\-()])"


@dataclass(frozen=True, slots=True)
class StageRule:
    rule_id: str
    stage: str
    pattern: re.Pattern[str]
    folder: float
    name: float
    text: float


def _r(rule_id: str, stage: str, pattern: str, folder: float, name: float, text: float) -> StageRule:
    return StageRule(rule_id, stage, re.compile(pattern), folder, name, text)


RULES: tuple[StageRule, ...] = (
    # ── ИД ──
    _r(
        "id.act",
        "ID",
        r"(?<![а-я])акт\s+(?:освидетельствования|приемки|испытани|промывк|продувк|входного\s+контроля|гидравлическ)",
        1,
        3,
        3,
    ),
    _r("id.act_abbrev", "ID", r"(?<![а-я])(?:аоср|аоок|аоус)(?![а-я])", 2, 3, 2),
    _r("id.act_numbered", "ID", r"(?<![а-я])акт\s*№", 1, 3, 1),
    _r(
        "id.executive",
        "ID",
        r"исполнительн(?:ый|ая|ые|ое)\s+(?:чертеж|схем|геодезическ|съемк|документаци)",
        2,
        3,
        3,
    ),
    _r("id.registry", "ID", r"реестр\w*\s+исполнительн", 2, 3, 3),
    _r("id.journal", "ID", r"(?:общий|специальный)\s+журнал", 1, 2, 2),
    _r("id.igs", "ID", r"(?<![а-я])игс(?![а-я])", 1, 2, 1),
    # ── РД ──
    _r("rd.work_documentation", "RD", r"рабоч(?:ая|ие)\s+(?:и\s+\S+\s+)?документаци", 2, 2, 3),
    _r("rd.code_token", "RD", _TOKEN_SEP + r"рд" + _TOKEN_END, 2, 2, 1),
    _r("rd.stage_cell", "RD", r"стади[яи]\s*[:\-]?\s*рд?(?![а-я])", 2, 2, 2),
    _r("rd.for_construction", "RD", r"в\s+производство\s+работ", 0, 1, 2),
    # ── ПД ──
    _r("pd.project_documentation", "PD", r"проектн(?:ая|ые)\s+документаци", 2, 2, 3),
    _r("pd.code_token", "PD", _TOKEN_SEP + r"пд" + _TOKEN_END, 2, 2, 1),
    _r("pd.stage_cell", "PD", r"стади[яи]\s*[:\-]?\s*пд?(?![а-я])", 2, 2, 2),
    _r("pd.initial_data", "PD", r"исходн\w*\s+данн|" + _TOKEN_SEP + r"п-ид" + _TOKEN_END, 2, 2, 1),
    _r("pd.code_p", "PD", r"-п-", 0, 1, 0),
)

# Decision: the top stage needs a score ≥ MIN_SCORE, a margin ≥ MIN_MARGIN over the runner-up and
# ≥ DOMINANCE × the runner-up. Confidence = 1 − exp(−margin / CONFIDENCE_SCALE), so votes that cancel
# out (e.g. a folder named «Рабочая и исполнительная документация») neither help nor dilute.
MIN_SCORE = 2.0
MIN_MARGIN = 2.0
DOMINANCE = 1.5
CONFIDENCE_SCALE = 3.0
CONFLICT_MIN_MARGIN = 5.0  # a manifest PD/RD/ID stage is questioned only on a strong margin


@dataclass(slots=True)
class Signal:
    rule: str
    stage: str
    where: str  # "folder" | "name" | "text"
    weight: float
    match: str | None

    def to_json(self, *, redact: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "stage": self.stage,
            "where": self.where,
            "weight": self.weight,
        }
        if not redact and self.match is not None:
            out["match"] = self.match
        return out


@dataclass(slots=True)
class StageResolution:
    manifest_stage: str
    stage_resolved: str | None
    source: str | None  # MetaSource
    confidence: float | None
    candidates: tuple[str, ...]
    scores: dict[str, float] = field(default_factory=dict)
    signals: list[Signal] = field(default_factory=list)
    signals_stage: str | None = None  # what the signals alone say (all three stages)
    signals_confidence: float | None = None
    conflict: bool = False
    skipped_reason: str | None = None

    def to_json(self, *, redact: bool = False) -> dict[str, Any]:
        return {
            "manifest_stage": self.manifest_stage,
            "stage_resolved": self.stage_resolved,
            "source": self.source,
            "confidence": self.confidence,
            "candidates": list(self.candidates),
            "scores": self.scores,
            "signals": [s.to_json(redact=redact) for s in self.signals],
            "signals_stage": self.signals_stage,
            "signals_confidence": self.signals_confidence,
            "conflict": self.conflict,
            "skipped_reason": self.skipped_reason,
        }


def _prepare_name(text: str) -> str:
    cleaned, _ = clean_name(text)
    return " " + cleaned.casefold().replace("ё", "е") + " "


def collect_signals(relative_path: str, text: str | None) -> list[Signal]:
    """All rule hits for one file: folders, name, and (normalised) first-pages text."""
    path = PurePosixPath(relative_path)
    folder = _prepare_name(" / ".join(path.parts[:-1]))
    name = _prepare_name(path.stem)
    sources: list[tuple[str, str]] = [("folder", folder), ("name", name)]
    if text:
        sources.append(("text", text))
    signals: list[Signal] = []
    for where, haystack in sources:
        for rule in RULES:
            weight = getattr(rule, where)
            if weight <= 0:
                continue
            m = rule.pattern.search(haystack)
            if m:
                signals.append(
                    Signal(rule.rule_id, rule.stage, where, float(weight), m.group(0).strip()[:80])
                )
    return signals


def _decide(
    signals: list[Signal], candidates: tuple[str, ...]
) -> tuple[str | None, float | None, dict[str, float]]:
    scores = {stage: 0.0 for stage in candidates}
    for s in signals:
        if s.stage in scores:
            scores[s.stage] += s.weight
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top_stage, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top - second
    if top >= MIN_SCORE and margin >= MIN_MARGIN and top >= DOMINANCE * second:
        confidence = round(1.0 - math.exp(-margin / CONFIDENCE_SCALE), 3)
        return top_stage, confidence, scores
    return None, None, scores


def resolve_stage(
    manifest_stage: str,
    relative_path: str,
    text: str | None,
    *,
    skip_reason: str | None = None,
) -> StageResolution:
    """Resolve the document stage of one manifest file."""
    if manifest_stage in STAGES:
        candidates: tuple[str, ...] = (manifest_stage,)
    elif manifest_stage == ManifestStage.RD_ID_MIXED.value:
        candidates = ("RD", "ID")
    else:
        candidates = STAGES
    if skip_reason:
        return StageResolution(
            manifest_stage=manifest_stage,
            stage_resolved=manifest_stage if manifest_stage in STAGES else None,
            source=MetaSource.REGISTRY.value if manifest_stage in STAGES else None,
            confidence=1.0 if manifest_stage in STAGES else None,
            candidates=candidates,
            skipped_reason=skip_reason,
        )
    signals = collect_signals(relative_path, text)
    signals_stage, signals_conf, all_scores = _decide(signals, STAGES)
    if manifest_stage in STAGES:
        conflict = (
            signals_stage is not None
            and signals_stage != manifest_stage
            and all_scores[signals_stage] - max(v for k, v in all_scores.items() if k != signals_stage)
            >= CONFLICT_MIN_MARGIN
        )
        return StageResolution(
            manifest_stage=manifest_stage,
            stage_resolved=manifest_stage,
            source=MetaSource.REGISTRY.value,
            confidence=1.0,
            candidates=candidates,
            scores=all_scores,
            signals=signals,
            signals_stage=signals_stage,
            signals_confidence=signals_conf,
            conflict=conflict,
        )
    stage, confidence, scores = _decide(signals, candidates)
    return StageResolution(
        manifest_stage=manifest_stage,
        stage_resolved=stage,
        source=MetaSource.EXTRACTED_UNCONFIRMED.value if stage else None,
        confidence=confidence,
        candidates=candidates,
        scores=scores,
        signals=signals,
        signals_stage=signals_stage,
        signals_confidence=signals_conf,
    )
