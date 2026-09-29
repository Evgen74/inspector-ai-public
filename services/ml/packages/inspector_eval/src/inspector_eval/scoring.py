"""inspector-score core: the 60/15/15/10 components and the critical-miss gate (93 §2.2–2.4, §4).

H1 (primary hypothesis, 93 §2.2), per object:
- finding_detection_f1 (60): TP/FP/FN over keys (object_id, parameter_code, location) whose
  violation_label is VIOLATION_PRESENT; points = 60·F1. Variants: k3 group-level, k4 key+evidence,
  multi-label (diagnostic).
- source_localization_exact_file_page (15): mean over gold positives of |gold ∩ pred| / |gold| on
  (stage, file_id, pdf_page_number); the predicted check with the same key supplies the pages; an
  unmatched gold positive scores 0. Variants: jaccard, any-hit, without stage.
- normalized_value_and_status_accuracy (15): mean over all gold checks of
  0.5·status (label 0.5, protocol_status 0.25, criticality 0.25) + 0.5·values (pd/rd/id each 1 when both
  null, or numeric-equal, or normalised-text similarity ≥ 0.85); unmatched gold = 0.
- document_integrity_and_split_handling (10): share of passed integrity rules (R1–R14; R9 only with a
  revision list; R15 is a warning). Variant: hard (0 on any failure).
- Gate: an approved critical checkpoint (gold VIOLATION_PRESENT, criticality «Критическое…» without
  «требует утверждения», gold_status FINAL*, TEAM_LABEL_FROZEN or absent, score_eligible) with no predicted
  VIOLATION_PRESENT on its key caps the total at 59. Variants: strict (+ ≥ 1 correct page), broad
  (every approved critical gold check of any label must carry the right label).
- A prediction that fails the organizer schema scores 0 on every component (93 §4.2).
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from inspector_common.contracts.loader import load_codes
from inspector_eval.config import CHOICES, DEFAULT_CONFIG, ScoreConfig
from inspector_eval.data import ScoringContext
from inspector_eval.normalize import (
    is_approved_critical_string,
    normalize_code,
    normalize_criticality,
    normalize_location,
    value_match,
)
from inspector_eval.validation import IntegrityReport, SchemaReport, check_integrity, validate_schemas

POSITIVE = "VIOLATION_PRESENT"
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20260927
MIN_BOOTSTRAP_CLUSTERS = 5
STAGE_FIELDS = ("pd_value", "rd_value", "id_value")
Key = tuple[str, str]  # (normalised parameter code, normalised location); object_id is implicit
EvidenceItem = tuple[Any, ...]


# ── small helpers ────────────────────────────────────────────────────────────────────────────


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float] | None:
    """Wilson 95 % score interval for a proportion k/n (None when n = 0)."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def key_of(check: Mapping[str, Any], cfg: ScoreConfig) -> Key:
    return (
        normalize_code(check.get("parameter_code"), cfg.code_norm),
        normalize_location(check.get("location"), cfg.location_norm),
    )


def evidence_set(check: Mapping[str, Any] | None, with_stage: bool) -> set[EvidenceItem]:
    if check is None:
        return set()
    items = check.get("evidence")
    out: set[EvidenceItem] = set()
    for e in items if isinstance(items, list) else ():
        if isinstance(e, Mapping):
            item = (e.get("file_id"), e.get("pdf_page_number"))
            out.add((e.get("stage"), *item) if with_stage else item)
    return out


@dataclass(slots=True)
class Indexed:
    """Checks keyed by the scoring key; the first occurrence of a duplicate key wins."""

    by_key: OrderedDict[Key, Mapping[str, Any]]
    index_of: dict[Key, int]
    duplicates: int

    @classmethod
    def build(cls, checks: Iterable[Mapping[str, Any]], cfg: ScoreConfig) -> Indexed:
        by_key: OrderedDict[Key, Mapping[str, Any]] = OrderedDict()
        index_of: dict[Key, int] = {}
        duplicates = 0
        for index, check in enumerate(checks):
            key = key_of(check, cfg)
            if key in by_key:
                duplicates += 1
                continue
            by_key[key] = check
            index_of[key] = index
        return cls(by_key, index_of, duplicates)

    def positives(self) -> list[Key]:
        return [k for k, c in self.by_key.items() if c.get("violation_label") == POSITIVE]


def _checks(document: Any) -> list[Mapping[str, Any]]:
    if isinstance(document, Mapping) and isinstance(document.get("checks"), list):
        return [c for c in document["checks"] if isinstance(c, Mapping)]
    return []


def is_approved_checkpoint(gold: Mapping[str, Any]) -> bool:
    """93 §2.4: approved critical checkpoint (label is checked by the gate variant)."""
    if gold.get("score_eligible", True) is False:
        return False
    status = gold.get("gold_status")
    # Organizer gold: FINAL*; our frozen team labels (N-GOLD): TEAM_LABEL_FROZEN; absent: labels in progress.
    if status is not None and not (str(status).startswith("FINAL") or status == "TEAM_LABEL_FROZEN"):
        return False
    return is_approved_critical_string(gold.get("criticality"))


# ── results ──────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Detection:
    variant: str
    tp: int
    fp: int
    fn: int
    tp_items: list[Any] = field(default_factory=list)
    fp_items: list[Any] = field(default_factory=list)
    fn_items: list[Any] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return prf(self.tp, self.fp, self.fn)[0]

    @property
    def recall(self) -> float:
        return prf(self.tp, self.fp, self.fn)[1]

    @property
    def f1(self) -> float:
        return prf(self.tp, self.fp, self.fn)[2]

    def as_dict(self, with_items: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "variant": self.variant,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "precision_ci95": wilson(self.tp, self.tp + self.fp),
            "recall_ci95": wilson(self.tp, self.tp + self.fn),
        }
        if with_items:
            out.update(
                tp_items=[_item(i) for i in self.tp_items],
                fp_items=[_item(i) for i in self.fp_items],
                fn_items=[_item(i) for i in self.fn_items],
            )
        return out


def _item(item: Any) -> Any:
    if isinstance(item, tuple) and len(item) == 2 and all(isinstance(x, str) for x in item):
        return {"parameter_code": item[0], "location": item[1]}
    if isinstance(item, tuple):
        return [_item(x) for x in item]
    return item


@dataclass(slots=True)
class GateCheckpoint:
    check_id: str | None
    finding_group_id: str | None
    parameter_code: str
    location: str
    gold_label: str
    status: str  # FOUND | FOUND_WRONG_EVIDENCE | MISSED (93 §4.5)
    broad_ok: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "finding_group_id": self.finding_group_id,
            "parameter_code": self.parameter_code,
            "location": self.location,
            "gold_label": self.gold_label,
            "status": self.status,
            "broad_ok": self.broad_ok,
        }


@dataclass(slots=True)
class GateReport:
    variant: str
    checkpoints: list[GateCheckpoint]  # approved critical gold checks with label VIOLATION_PRESENT
    broad_checkpoints: list[GateCheckpoint]  # approved critical gold checks of any label
    triggered_key: bool
    triggered_strict: bool
    triggered_broad: bool

    @property
    def triggered(self) -> bool:
        return {"key": self.triggered_key, "strict": self.triggered_strict, "broad": self.triggered_broad}[
            self.variant
        ]

    @property
    def missed(self) -> list[GateCheckpoint]:
        if self.variant == "broad":
            return [c for c in self.broad_checkpoints if not c.broad_ok]
        if self.variant == "strict":
            return [c for c in self.checkpoints if c.status != "FOUND"]
        return [c for c in self.checkpoints if c.status == "MISSED"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "triggered": self.triggered,
            "triggered_by_variant": {
                "key": self.triggered_key,
                "strict": self.triggered_strict,
                "broad": self.triggered_broad,
            },
            "checkpoints_total": len(self.checkpoints),
            "found": sum(1 for c in self.checkpoints if c.status == "FOUND"),
            "found_wrong_evidence": sum(1 for c in self.checkpoints if c.status == "FOUND_WRONG_EVIDENCE"),
            "missed_count": sum(1 for c in self.checkpoints if c.status == "MISSED"),
            "missed": [c.as_dict() for c in self.missed],
            "checkpoints": [c.as_dict() for c in self.checkpoints],
            "broad_checkpoints_total": len(self.broad_checkpoints),
        }


@dataclass(slots=True)
class HedgeReport:
    groups: list[dict[str, Any]]
    hedges: int
    critical_emitted: int
    budget: float
    what_if: dict[str, Any] | None = None

    @property
    def share(self) -> float:
        return self.hedges / self.critical_emitted if self.critical_emitted else 0.0

    @property
    def within_budget(self) -> bool:
        return self.share <= self.budget + 1e-12

    def as_dict(self) -> dict[str, Any]:
        return {
            "hedges": self.hedges,
            "critical_emitted": self.critical_emitted,
            "share": self.share,
            "budget": self.budget,
            "within_budget": self.within_budget,
            "groups": self.groups,
            "what_if_without_hedges": self.what_if,
        }


@dataclass(slots=True)
class ObjectScore:
    object_id: str
    config: ScoreConfig
    weights: Mapping[str, float]
    gate_cap: float
    schema: SchemaReport
    integrity: IntegrityReport
    detection: Detection
    detection_variants: dict[str, Detection]
    localisation: float
    localisation_sum: float
    localisation_n: int
    localisation_variants: dict[str, float]
    value_status: float
    value_status_sum: float
    value_status_n: int
    status_only: float
    values_only: float
    gate: GateReport
    counts: dict[str, int]
    per_check: list[dict[str, Any]]
    prediction_missing: bool = False
    prediction_path: str | None = None
    prediction_sha256: str | None = None
    hedges: HedgeReport | None = None
    breakdowns: dict[str, Any] = field(default_factory=dict)
    sensitivity: list[dict[str, Any]] = field(default_factory=list)

    @property
    def scored(self) -> bool:
        return self.schema.organizer_valid and not self.prediction_missing

    @property
    def components(self) -> dict[str, float]:
        """Component values in [0, 1] (0 everywhere for a schema-invalid or missing prediction)."""
        if not self.scored:
            return dict.fromkeys(self.weights, 0.0)
        return {
            "finding_detection_f1": self.detection.f1,
            "source_localization_exact_file_page": self.localisation,
            "normalized_value_and_status_accuracy": self.value_status,
            "document_integrity_and_split_handling": self.integrity.value(self.config.integrity),
        }

    @property
    def points(self) -> dict[str, float]:
        comps = self.components
        return {name: self.weights[name] * comps[name] for name in self.weights}

    @property
    def total_uncapped(self) -> float:
        return sum(self.points.values())

    @property
    def gate_triggered(self) -> bool:
        return self.gate.triggered

    @property
    def total(self) -> float:
        total = self.total_uncapped
        return min(total, self.gate_cap) if self.gate_triggered else total

    def summary(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "total": self.total,
            "total_uncapped": self.total_uncapped,
            "gate_triggered": self.gate_triggered,
            "components": self.components,
            "points": self.points,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "prediction": {
                "missing": self.prediction_missing,
                "path": self.prediction_path,
                "sha256": self.prediction_sha256,
            },
            "schema": self.schema.as_dict(),
            "counts": self.counts,
            "detection": self.detection.as_dict(),
            "detection_variants": {
                k: v.as_dict(with_items=False) for k, v in self.detection_variants.items()
            },
            "localisation": {
                "metric": self.config.loc_metric,
                "with_stage": self.config.loc_with_stage,
                "value": self.localisation,
                "n": self.localisation_n,
                "variants": self.localisation_variants,
            },
            "value_status": {
                "value": self.value_status,
                "status_only": self.status_only,
                "values_only": self.values_only,
                "n": self.value_status_n,
            },
            "integrity": self.integrity.as_dict(),
            "gate": self.gate.as_dict(),
            "hedges": self.hedges.as_dict() if self.hedges else None,
            "breakdowns": self.breakdowns,
            "sensitivity": self.sensitivity,
        }


# ── component computations ───────────────────────────────────────────────────────────────────


def _detection_k1(gpos: Sequence[Key], ppos: Sequence[Key]) -> Detection:
    gset, pset = set(gpos), set(ppos)
    return Detection(
        "k1",
        tp=len(gset & pset),
        fp=len(pset - gset),
        fn=len(gset - pset),
        tp_items=[k for k in gpos if k in pset],
        fp_items=[k for k in ppos if k not in gset],
        fn_items=[k for k in gpos if k not in pset],
    )


def _detection_k4(
    gold: Indexed, pred: Indexed, gpos: Sequence[Key], ppos: Sequence[Key], cfg: ScoreConfig
) -> Detection:
    pset = set(ppos)
    good = {
        k
        for k in gpos
        if k in pset
        and evidence_set(gold.by_key[k], cfg.loc_with_stage)
        & evidence_set(pred.by_key[k], cfg.loc_with_stage)
    }
    return Detection(
        "k4",
        tp=len(good),
        fp=len(pset - good),
        fn=len(set(gpos) - good),
        tp_items=[k for k in gpos if k in good],
        fp_items=[k for k in ppos if k not in good],
        fn_items=[k for k in gpos if k not in good],
    )


def _detection_k3(
    gold: Indexed, pred: Indexed, gpos: Sequence[Key], ppos: Sequence[Key], cfg: ScoreConfig
) -> Detection:
    groups: OrderedDict[str, list[Key]] = OrderedDict()
    for k in gpos:
        row = gold.by_key[k]
        gid = str(row.get("finding_group_id") or row.get("check_id") or f"{k[0]}|{k[1]}")
        groups.setdefault(gid, []).append(k)
    pset = set(ppos)
    tp_items, fn_items = [], []
    for gid, keys in groups.items():
        hits = sum(1 for k in keys if k in pset)
        found = {
            "any": hits >= 1,
            "majority": hits * 2 > len(keys),
            "all": hits == len(keys),
        }[cfg.group_rule]
        (tp_items if found else fn_items).append(gid)
    gset = set(gpos)
    fp_clusters: OrderedDict[tuple[str, Any], None] = OrderedDict()
    for k in ppos:
        if k not in gset:
            fp_clusters[(k[0], pred.by_key[k].get("comparison_result"))] = None
    return Detection(
        f"k3:{cfg.group_rule}",
        tp=len(tp_items),
        fp=len(fp_clusters),
        fn=len(fn_items),
        tp_items=tp_items,
        fp_items=list(fp_clusters),
        fn_items=fn_items,
    )


def _detection_multilabel(gold: Indexed, pred: Indexed) -> Detection:
    g = {(k, c.get("violation_label")) for k, c in gold.by_key.items()}
    p = {(k, c.get("violation_label")) for k, c in pred.by_key.items()}
    return Detection("multilabel", tp=len(g & p), fp=len(p - g), fn=len(g - p))


def _loc_score(gold_ev: set[EvidenceItem], pred_ev: set[EvidenceItem], metric: str) -> float:
    if not gold_ev:
        return 1.0
    inter = len(gold_ev & pred_ev)
    if metric == "jaccard":
        return inter / len(gold_ev | pred_ev)
    if metric == "anyhit":
        return 1.0 if inter else 0.0
    return inter / len(gold_ev)


def _localisation(
    gold: Indexed, pred: Indexed, gpos: Sequence[Key], metric: str, with_stage: bool
) -> tuple[float, dict[Key, float]]:
    per_key = {
        k: _loc_score(
            evidence_set(gold.by_key[k], with_stage), evidence_set(pred.by_key.get(k), with_stage), metric
        )
        for k in gpos
    }
    total = sum(per_key.values())
    return total, per_key


def _status_values(
    g: Mapping[str, Any], p: Mapping[str, Any] | None, cfg: ScoreConfig
) -> tuple[float, float]:
    if p is None:
        return 0.0, 0.0
    status = (
        cfg.status_label_weight * (p.get("violation_label") == g.get("violation_label"))
        + cfg.status_protocol_weight * (p.get("protocol_status") == g.get("protocol_status"))
        + cfg.status_criticality_weight
        * (
            normalize_criticality(p.get("criticality"), cfg.criticality_norm)
            == normalize_criticality(g.get("criticality"), cfg.criticality_norm)
        )
    )
    values = sum(
        value_match(g.get(f), p.get(f), cfg.value_norm, cfg.value_threshold) for f in STAGE_FIELDS
    ) / len(STAGE_FIELDS)
    return float(status), float(values)


def _gate(gold: Indexed, pred: Indexed, ppos: Sequence[Key], cfg: ScoreConfig) -> GateReport:
    pset = set(ppos)
    checkpoints: list[GateCheckpoint] = []
    broad: list[GateCheckpoint] = []
    for k, g in gold.by_key.items():
        if not is_approved_checkpoint(g):
            continue
        p = pred.by_key.get(k)
        label = str(g.get("violation_label"))
        broad_ok = p is not None and p.get("violation_label") == label
        if label == POSITIVE:
            if k not in pset:
                status = "MISSED"
            elif evidence_set(g, cfg.loc_with_stage) & evidence_set(p, cfg.loc_with_stage):
                status = "FOUND"
            else:
                status = "FOUND_WRONG_EVIDENCE"
        else:
            status = "FOUND" if broad_ok else "MISSED"
        cp = GateCheckpoint(
            check_id=g.get("check_id"),
            finding_group_id=g.get("finding_group_id"),
            parameter_code=str(g.get("parameter_code")),
            location=str(g.get("location")),
            gold_label=label,
            status=status,
            broad_ok=broad_ok,
        )
        broad.append(cp)
        if label == POSITIVE:
            checkpoints.append(cp)
    return GateReport(
        variant=cfg.gate,
        checkpoints=checkpoints,
        broad_checkpoints=broad,
        triggered_key=any(c.status == "MISSED" for c in checkpoints),
        triggered_strict=any(c.status != "FOUND" for c in checkpoints),
        triggered_broad=any(not c.broad_ok for c in broad),
    )


def hedge_sets() -> list[frozenset[str]]:
    return [frozenset(pair) for pair in load_codes().get("hedge_pairs", [])]


def _hedges(
    pred: Indexed, ppos: Sequence[Key], ctx: ScoringContext
) -> tuple[list[dict[str, Any]], int, int, set[int]]:
    """Hedge groups (several codes of one hedge set at one location), hedge count, critical count, drop set."""
    by_location: dict[str, list[Key]] = defaultdict(list)
    for k in ppos:
        by_location[k[1]].append(k)
    groups: list[dict[str, Any]] = []
    hedges = 0
    drop: set[int] = set()
    for location, keys in by_location.items():
        for hset in hedge_sets():
            members = [k for k in keys if k[0] in hset]
            if len(members) < 2:
                continue

            def rank(k: Key) -> tuple[float, int]:
                conf = pred.by_key[k].get("confidence")
                return (-(float(conf) if isinstance(conf, int | float) else -1.0), pred.index_of[k])

            kept = min(members, key=rank)
            groups.append(
                {
                    "location": location,
                    "codes": [k[0] for k in members],
                    "kept_in_what_if": kept[0],
                }
            )
            hedges += len(members) - 1
            drop.update(pred.index_of[k] for k in members if k != kept)
    critical = 0
    for k in ppos:
        crit = pred.by_key[k].get("criticality") or ctx.catalog_criticality(k[0])
        if is_approved_critical_string(crit):
            critical += 1
    return groups, hedges, critical, drop


def _breakdown(rows: Iterable[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    """rows: (bucket, outcome ∈ TP/FP/FN) → per-bucket counts and P/R/F1."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for bucket, outcome in rows:
        counts[bucket][outcome.lower()] += 1
    out: dict[str, dict[str, Any]] = {}
    for bucket in sorted(counts):
        c = counts[bucket]
        p, r, f = prf(c["tp"], c["fp"], c["fn"])
        out[bucket] = {**c, "precision": p, "recall": r, "f1": f}
    return out


# ── public API ───────────────────────────────────────────────────────────────────────────────


def score_object(
    gold_rows: Sequence[Mapping[str, Any]],
    document: Any,
    ctx: ScoringContext,
    cfg: ScoreConfig = DEFAULT_CONFIG,
    *,
    object_id: str | None = None,
    prediction_path: str | None = None,
    prediction_sha256: str | None = None,
    extras: bool = True,
) -> ObjectScore:
    """Score one object's prediction against its gold rows (already filtered to that object).

    ``document`` None means that no prediction file exists for the object: it scores 0 everywhere.
    ``extras`` adds hedges, breakdowns and the per-switch sensitivity table.
    """
    missing = document is None
    if object_id is None:
        object_id = str(document.get("object_id")) if isinstance(document, Mapping) else "?"
    doc: Any = document if not missing else {"object_id": object_id, "checks": []}
    schema = validate_schemas(doc)
    integrity = check_integrity(doc, ctx, cfg, schema=schema)
    scored = schema.organizer_valid and not missing

    gold = Indexed.build(gold_rows, cfg)
    pred = Indexed.build(_checks(doc) if scored else [], cfg)
    gpos = gold.positives()
    ppos = pred.positives()

    detections = {
        "k1": _detection_k1(gpos, ppos),
        "k3": _detection_k3(gold, pred, gpos, ppos, cfg),
        "k4": _detection_k4(gold, pred, gpos, ppos, cfg),
        "multilabel": _detection_multilabel(gold, pred),
    }
    headline = detections[cfg.key]

    loc_sum, loc_per_key = _localisation(gold, pred, gpos, cfg.loc_metric, cfg.loc_with_stage)
    loc_n = len(gpos)
    loc_value = loc_sum / loc_n if loc_n else 0.0
    loc_variants: dict[str, float] = {}
    for metric in CHOICES["loc_metric"]:
        for with_stage in (True, False):
            s, _ = _localisation(gold, pred, gpos, metric, with_stage)
            loc_variants[f"{metric}{'' if with_stage else ':no_stage'}"] = s / loc_n if loc_n else 0.0

    vs_rows: dict[Key, tuple[float, float]] = {
        k: _status_values(g, pred.by_key.get(k), cfg) for k, g in gold.by_key.items()
    }
    vs_n = len(vs_rows)
    combined = {k: cfg.status_share * s + (1 - cfg.status_share) * v for k, (s, v) in vs_rows.items()}
    vs_sum = sum(combined.values())
    vs_value = vs_sum / vs_n if vs_n else 0.0
    status_only = sum(s for s, _ in vs_rows.values()) / vs_n if vs_n else 0.0
    values_only = sum(v for _, v in vs_rows.values()) / vs_n if vs_n else 0.0

    gate = _gate(gold, pred, ppos, cfg)
    gate_by_key = {
        (
            normalize_code(c.parameter_code, cfg.code_norm),
            normalize_location(c.location, cfg.location_norm),
        ): c
        for c in gate.broad_checkpoints
    }

    pset, gset = set(ppos), set(gpos)
    per_check: list[dict[str, Any]] = []
    for k, g in gold.by_key.items():
        p = pred.by_key.get(k)
        label = g.get("violation_label")
        if label == POSITIVE:
            outcome = "TP" if k in pset else "FN"
        elif p is None:
            outcome = "NEG_MISSING"
        else:
            outcome = "NEG_MATCH" if p.get("violation_label") == label else "NEG_MISMATCH"
        status_score, values_score = vs_rows[k]
        cp = gate_by_key.get(k)
        per_check.append(
            {
                "object_id": object_id,
                "check_id": g.get("check_id"),
                "finding_group_id": g.get("finding_group_id"),
                "parameter_code": g.get("parameter_code"),
                "location": g.get("location"),
                "gold_label": label,
                "pred_label": p.get("violation_label") if p else None,
                "outcome": outcome,
                "localisation": loc_per_key.get(k),
                "status_score": status_score,
                "values_score": values_score,
                "value_status": combined[k],
                "gate_checkpoint": cp.status if cp else None,
            }
        )
    for k in ppos:
        if k in gset:
            continue
        p = pred.by_key[k]
        per_check.append(
            {
                "object_id": object_id,
                "check_id": None,
                "finding_group_id": None,
                "parameter_code": p.get("parameter_code"),
                "location": p.get("location"),
                "gold_label": gold.by_key[k].get("violation_label") if k in gold.by_key else None,
                "pred_label": POSITIVE,
                "outcome": "FP",
                "localisation": None,
                "status_score": None,
                "values_score": None,
                "value_status": None,
                "gate_checkpoint": None,
            }
        )

    counts = {
        "gold_checks": len(gold.by_key),
        "gold_positives": len(gpos),
        "gold_duplicate_keys": gold.duplicates,
        "pred_checks": len(_checks(doc)),
        "pred_unique_keys": len(pred.by_key),
        "pred_positives": len(ppos),
        "pred_duplicate_keys": pred.duplicates,
        "critical_checkpoints": len(gate.checkpoints),
    }

    result = ObjectScore(
        object_id=object_id,
        config=cfg,
        weights=ctx.weights,
        gate_cap=ctx.gate_cap,
        schema=schema,
        integrity=integrity,
        detection=headline,
        detection_variants=detections,
        localisation=loc_value,
        localisation_sum=loc_sum,
        localisation_n=loc_n,
        localisation_variants=loc_variants,
        value_status=vs_value,
        value_status_sum=vs_sum,
        value_status_n=vs_n,
        status_only=status_only,
        values_only=values_only,
        gate=gate,
        counts=counts,
        per_check=per_check,
        prediction_missing=missing,
        prediction_path=prediction_path,
        prediction_sha256=prediction_sha256,
    )
    if not extras:
        return result

    # hedges and the what-if without them (93 §4.5)
    groups, n_hedges, critical, drop = _hedges(pred, ppos, ctx)
    what_if = None
    if drop and isinstance(doc, Mapping):
        trimmed = {**doc, "checks": [c for i, c in enumerate(_checks(doc)) if i not in drop]}
        alt = score_object(gold_rows, trimmed, ctx, cfg, object_id=object_id, extras=False)
        what_if = {
            "total": alt.total,
            "total_uncapped": alt.total_uncapped,
            "gate_triggered": alt.gate_triggered,
            "removed_checks": len(drop),
        }
    result.hedges = HedgeReport(groups, n_hedges, critical, cfg.hedge_budget, what_if)

    # breakdowns by section, criticality and comparison result (93 §4.4)
    def bucket_rows(attr: str) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for k in gpos:
            rows.append((_bucket(attr, gold.by_key[k], k, ctx), "TP" if k in pset else "FN"))
        for k in ppos:
            if k not in gset:
                rows.append((_bucket(attr, pred.by_key[k], k, ctx), "FP"))
        return rows

    result.breakdowns = {
        "by_section": _breakdown(bucket_rows("section")),
        "by_criticality": _breakdown(bucket_rows("criticality")),
        "by_comparison_result": _breakdown(bucket_rows("comparison_result")),
    }
    result.sensitivity = sensitivity(gold_rows, document, ctx, cfg, object_id=object_id)
    return result


def _bucket(attr: str, row: Mapping[str, Any], key: Key, ctx: ScoringContext) -> str:
    if attr == "section":
        return ctx.section_of(key[0])
    value = row.get(attr)
    return "—" if value is None else str(value)


def sensitivity(
    gold_rows: Sequence[Mapping[str, Any]],
    document: Any,
    ctx: ScoringContext,
    cfg: ScoreConfig,
    *,
    object_id: str | None = None,
) -> list[dict[str, Any]]:
    """Total under every single-switch deviation from ``cfg`` («assumptions instead of answers», 97 §2.3)."""
    rows: list[dict[str, Any]] = []
    for switch, values in CHOICES.items():
        for value in values:
            if getattr(cfg, switch) == value:
                continue
            if switch == "group_rule" and cfg.key != "k3":
                continue
            alt = score_object(
                gold_rows, document, ctx, cfg.replace(**{switch: value}), object_id=object_id, extras=False
            )
            rows.append(
                {
                    "switch": switch,
                    "value": value,
                    "total": alt.total,
                    "total_uncapped": alt.total_uncapped,
                    "gate_triggered": alt.gate_triggered,
                }
            )
    return rows


@dataclass(slots=True)
class PooledScore:
    """Micro-pooled result over several objects (93 §2.2: pooled micro if several objects)."""

    objects: list[ObjectScore]
    weights: Mapping[str, float]
    gate_cap: float
    integrity_mode: str

    @property
    def detection(self) -> Detection:
        return Detection(
            "pooled",
            tp=sum(o.detection.tp for o in self.objects),
            fp=sum(o.detection.fp for o in self.objects),
            fn=sum(o.detection.fn for o in self.objects),
        )

    def bootstrap_f1(self, n_boot: int = BOOTSTRAP_SAMPLES, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
        """Object-cluster bootstrap 95 % CI of the pooled F1 (06 §3.10 item 9); needs ≥ 5 objects."""
        k = len(self.objects)
        if k < MIN_BOOTSTRAP_CLUSTERS:
            return {"status": "INSUFFICIENT_CLUSTERS", "clusters": k, "min_clusters": MIN_BOOTSTRAP_CLUSTERS}
        rng = random.Random(seed)
        counts = [(o.detection.tp, o.detection.fp, o.detection.fn) for o in self.objects]
        samples = []
        for _ in range(n_boot):
            pick = [counts[rng.randrange(k)] for _ in range(k)]
            samples.append(prf(sum(c[0] for c in pick), sum(c[1] for c in pick), sum(c[2] for c in pick))[2])
        samples.sort()
        return {
            "status": "OK",
            "clusters": k,
            "samples": n_boot,
            "seed": seed,
            "f1_ci95": (samples[int(0.025 * (n_boot - 1))], samples[int(0.975 * (n_boot - 1))]),
        }

    @property
    def components(self) -> dict[str, float]:
        if not self.objects:
            return dict.fromkeys(self.weights, 0.0)
        loc_n = sum(o.localisation_n for o in self.objects)
        vs_n = sum(o.value_status_n for o in self.objects)
        loc = sum(o.localisation_sum if o.scored else 0.0 for o in self.objects)
        vs = sum(o.value_status_sum if o.scored else 0.0 for o in self.objects)
        det = Detection(
            "pooled",
            tp=sum(o.detection.tp for o in self.objects),
            fp=sum(o.detection.fp for o in self.objects),
            fn=sum(o.detection.fn for o in self.objects),
        )
        return {
            "finding_detection_f1": det.f1,
            "source_localization_exact_file_page": loc / loc_n if loc_n else 0.0,
            "normalized_value_and_status_accuracy": vs / vs_n if vs_n else 0.0,
            "document_integrity_and_split_handling": sum(
                o.components["document_integrity_and_split_handling"] for o in self.objects
            )
            / len(self.objects),
        }

    @property
    def gate_triggered(self) -> bool:
        return any(o.gate_triggered for o in self.objects)

    @property
    def total_uncapped(self) -> float:
        comps = self.components
        return sum(self.weights[k] * comps[k] for k in self.weights)

    @property
    def total(self) -> float:
        return min(self.total_uncapped, self.gate_cap) if self.gate_triggered else self.total_uncapped

    def as_dict(self) -> dict[str, Any]:
        comps = self.components
        return {
            "objects": [o.object_id for o in self.objects],
            "total": self.total,
            "total_uncapped": self.total_uncapped,
            "gate_triggered": self.gate_triggered,
            "components": comps,
            "points": {k: self.weights[k] * comps[k] for k in self.weights},
            "detection": self.detection.as_dict(with_items=False),
            "bootstrap_f1": self.bootstrap_f1(),
        }


def pool(objects: Sequence[ObjectScore], ctx: ScoringContext, cfg: ScoreConfig) -> PooledScore:
    return PooledScore(list(objects), ctx.weights, ctx.gate_cap, cfg.integrity)
