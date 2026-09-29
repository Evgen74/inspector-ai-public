"""Leave-object-out calibration skeleton (93 §4.8, 95 §5.1–5.2, 97 §1.6).

A *candidate* is one configuration of the emission policy (thresholds, hedge rule, FREE limits, …) run
over the dev objects; its predictions live in a directory:

    <pred-dir>/<candidate>/params.json            # optional: the tunables of this candidate
    <pred-dir>/<candidate>/[submission/]<object_id>.json

A *fold* is one dev object (T-GOLD, N-GOLD, …) or, for a dev set with ``folds`` in the registry, one
code-prefix group inside it (N-GOLD 2-fold by discipline: A = КР, B = the rest).

Rules (93 §4.8):
1. For every held-out fold f, choose the candidate that is best on all other folds; report its score on f.
2. Scores of a candidate chosen on f itself are «seen» and are never reported as results.
3. The final choice is tuned on all folds, then frozen (config_hash of its params).
With fewer than two folds the held-out estimate is not available (status INSUFFICIENT_FOLDS).
TEST_HIDDEN objects are never folds (the registry refuses them).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from inspector_common.hashing import config_hash
from inspector_eval.config import ScoreConfig
from inspector_eval.data import InputError, ScoringContext, read_json
from inspector_eval.devset import DevSetRows
from inspector_eval.normalize import normalize_code
from inspector_eval.scoring import score_object

Objective = Literal["total", "total_uncapped", "f1"]
OBJECTIVES: tuple[str, ...] = ("total", "total_uncapped", "f1")


@dataclass(frozen=True, slots=True)
class Fold:
    name: str
    devset_id: str
    object_id: str
    gold_rows: tuple[Mapping[str, Any], ...]
    prefixes: tuple[str, ...] | None = None  # code prefixes of this fold; ("*",) = the rest
    other_prefixes: tuple[str, ...] = ()

    def keeps(self, code: Any, cfg: ScoreConfig) -> bool:
        if self.prefixes is None:
            return True
        prefix = normalize_code(code, cfg.code_norm).split("-", 1)[0]
        if "*" in self.prefixes:
            return prefix not in self.other_prefixes
        return prefix in self.prefixes


def build_folds(devsets: Sequence[DevSetRows], cfg: ScoreConfig) -> list[Fold]:
    folds: list[Fold] = []
    for rows in devsets:
        d = rows.devset
        if not rows.gold_rows:
            continue
        if d.folds:
            explicit = tuple(p for group in d.folds.values() for p in group if p != "*")
            for name, prefixes in d.folds.items():
                fold = Fold(f"{d.id}:{name}", d.id, d.object_id, (), tuple(prefixes), explicit)
                kept = tuple(r for r in rows.gold_rows if fold.keeps(r.get("parameter_code"), cfg))
                if kept:
                    folds.append(Fold(fold.name, d.id, d.object_id, kept, fold.prefixes, explicit))
        else:
            folds.append(Fold(d.id, d.id, d.object_id, tuple(rows.gold_rows)))
    return folds


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    params: Mapping[str, Any]
    predictions: Mapping[str, Any]  # object_id → submission document

    @property
    def params_hash(self) -> str:
        return config_hash(dict(self.params))


def load_candidates(pred_dir: Path) -> list[Candidate]:
    if not pred_dir.is_dir():
        raise InputError(f"Каталог кандидатов не найден: {pred_dir}")
    out: list[Candidate] = []
    for sub in sorted(p for p in pred_dir.iterdir() if p.is_dir()):
        base = sub / "submission" if (sub / "submission").is_dir() else sub
        predictions: dict[str, Any] = {}
        for file in sorted(base.glob("*.json")):
            if file.name == "params.json" or file.name.endswith(".sidecar.json"):
                continue
            doc = read_json(file)
            if isinstance(doc, dict) and isinstance(doc.get("object_id"), str):
                predictions[doc["object_id"]] = doc
        params = read_json(sub / "params.json") if (sub / "params.json").is_file() else {}
        out.append(Candidate(sub.name, params, predictions))
    return out


@dataclass(frozen=True, slots=True)
class FoldScore:
    total: float
    total_uncapped: float
    f1: float
    gate_triggered: bool

    def objective(self, name: str) -> float:
        return {"total": self.total, "total_uncapped": self.total_uncapped, "f1": self.f1}[name]


def score_fold(candidate: Candidate, fold: Fold, ctx: ScoringContext, cfg: ScoreConfig) -> FoldScore:
    doc = candidate.predictions.get(fold.object_id)
    if doc is not None and fold.prefixes is not None:
        doc = {
            **doc,
            "checks": [c for c in doc.get("checks", []) if fold.keeps(c.get("parameter_code"), cfg)],
        }
    s = score_object(list(fold.gold_rows), doc, ctx, cfg, object_id=fold.object_id, extras=False)
    return FoldScore(s.total, s.total_uncapped, s.detection.f1, s.gate_triggered)


def score_matrix(
    candidates: Sequence[Candidate], folds: Sequence[Fold], ctx: ScoringContext, cfg: ScoreConfig
) -> dict[str, dict[str, FoldScore]]:
    return {c.name: {f.name: score_fold(c, f, ctx, cfg) for f in folds} for c in candidates}


def _rank(
    matrix: Mapping[str, Mapping[str, FoldScore]], fold_names: Sequence[str], objective: str
) -> list[str]:
    """Candidates best-first by mean objective over ``fold_names`` (ties: uncapped total, F1, name)."""

    def mean(name: str, attr: str) -> float:
        values = [matrix[name][f].objective(attr) for f in fold_names]
        return sum(values) / len(values) if values else 0.0

    return sorted(
        matrix,
        key=lambda n: (-mean(n, objective), -mean(n, "total_uncapped"), -mean(n, "f1"), n),
    )


@dataclass(slots=True)
class LooResult:
    status: str  # OK | INSUFFICIENT_FOLDS | NO_CANDIDATES
    objective: str
    folds: list[str]
    held_out: list[dict[str, Any]] = field(default_factory=list)
    mean_held_out: float | None = None
    final_candidate: str | None = None
    final_params: Mapping[str, Any] | None = None
    final_params_hash: str | None = None
    seen_mean: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "objective": self.objective,
            "folds": self.folds,
            "held_out": self.held_out,
            "mean_held_out": self.mean_held_out,
            "final_candidate": self.final_candidate,
            "final_params": dict(self.final_params) if self.final_params is not None else None,
            "final_params_hash": self.final_params_hash,
            "seen_mean": self.seen_mean,
            "seen_note_ru": "«seen»: настроено и оценено на тех же данных — не результат (93 §4.8 п.2)",
        }


def leave_one_out(
    matrix: Mapping[str, Mapping[str, FoldScore]],
    candidates: Sequence[Candidate],
    objective: str = "total",
) -> LooResult:
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}")
    if not matrix:
        return LooResult("NO_CANDIDATES", objective, [])
    fold_names = sorted({f for row in matrix.values() for f in row})
    by_name = {c.name: c for c in candidates}
    result = LooResult("OK" if len(fold_names) >= 2 else "INSUFFICIENT_FOLDS", objective, fold_names)
    if len(fold_names) >= 2:
        for held in fold_names:
            train = [f for f in fold_names if f != held]
            chosen = _rank(matrix, train, objective)[0]
            result.held_out.append(
                {
                    "held_out_fold": held,
                    "chosen_candidate": chosen,
                    "tuned_on": train,
                    "score": matrix[chosen][held].objective(objective),
                    "total": matrix[chosen][held].total,
                    "gate_triggered": matrix[chosen][held].gate_triggered,
                }
            )
        result.mean_held_out = sum(r["score"] for r in result.held_out) / len(result.held_out)
    final = _rank(matrix, fold_names, objective)[0]
    result.final_candidate = final
    if final in by_name:
        result.final_params = by_name[final].params
        result.final_params_hash = by_name[final].params_hash
    result.seen_mean = sum(matrix[final][f].objective(objective) for f in fold_names) / len(fold_names)
    return result


def calibrate(
    candidates: Sequence[Candidate],
    devsets: Sequence[DevSetRows],
    ctx: ScoringContext,
    cfg: ScoreConfig,
    objective: str = "total",
) -> dict[str, Any]:
    """Full sweep: folds from the dev sets, the score matrix and the leave-one-out selection."""
    for c in candidates:
        hidden = sorted(set(c.predictions) & ctx.split_policy.hidden)
        if hidden:
            raise InputError(
                f"Кандидат {c.name} содержит ответ по скрытой выборке; калибровка по нему запрещена"
            )
    folds = build_folds(devsets, cfg)
    matrix = score_matrix(candidates, folds, ctx, cfg)
    loo = leave_one_out(matrix, candidates, objective)
    return {
        "devsets": [d.summary() for d in devsets],
        "folds": [
            {"name": f.name, "devset": f.devset_id, "object_id": f.object_id, "gold_rows": len(f.gold_rows)}
            for f in folds
        ],
        "candidates": [
            {"name": c.name, "params": dict(c.params), "params_hash": c.params_hash} for c in candidates
        ],
        "matrix": {
            c: {
                f: {
                    "total": s.total,
                    "total_uncapped": s.total_uncapped,
                    "f1": s.f1,
                    "gate_triggered": s.gate_triggered,
                }
                for f, s in row.items()
            }
            for c, row in matrix.items()
        },
        "loo": loo.as_dict(),
    }
