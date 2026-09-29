"""The T-GOLD must-pass gate (95 §3.8, 97 §3.2 M1): acceptance of one run on OBJ-TYUMENSKAYA-5-GOLD-SEED.

A run passes when its exported answer (``runs/<run_id>/submission/<object_id>.json``) meets every criterion:

| Id | Criterion (95 §3.8 / 97 M1) | Hard |
|---|---|---|
| G1 | the answer exists and validates against the organizer and extended schemas | yes |
| G2 | all gold keys (code, location) are found with VIOLATION_PRESENT | yes |
| G3 | each gold key cites the gold PD and RD pages (anchor-page rule; localisation recall 1.0 with stage) | yes |
| G4 | the critical-miss gate does not trip (key variant, and the strict variant: ≥ 1 correct page) | yes |
| G5 | statuses equal the gold (label, protocol_status, criticality); values are reported (WARN below 1.0) | yes |
| G6 | at most 5 extra VIOLATION_PRESENT keys (a volume metric, not precision) | yes |
| G7 | integrity R1–R15 all pass and the packaging rules P1–P6 pass with a sidecar and a strict variant | yes |
| G8 | RT-01…RT-10 (``rtcheck``) have no FAIL; a check whose producing step ran but left no artifact fails | yes |
| G9 | the runtime is logged (pipeline summary, stage timings, the measured wall time) | no (WARN) |

Overall: FAIL if a criterion fails; INCOMPLETE if a hard criterion is NOT_EVALUATED (e.g. RT checks whose
producer is still a stub); PASS otherwise. The total score (H1 defaults) is reported alongside, never gated on
directly: 10/10 keys, the gold pages, the gate and the statuses already pin it near 100.

``pipeline_stubs()`` tells whether ``inspector-batch run`` can go end to end at all (a stub ``run_<step>`` hook
only raises CommandNotImplementedError), so the slow E2E test skips instead of running recognition for nothing.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.runlayout import RunLayout
from inspector_eval import integrity, rtcheck
from inspector_eval.config import DEFAULT_CONFIG, ScoreConfig
from inspector_eval.data import ScoringContext, gold_for_object, read_json
from inspector_eval.fixtures import T_GOLD_OBJECT
from inspector_eval.normalize import normalize_code, normalize_location
from inspector_eval.scoring import POSITIVE, ObjectScore, score_object

MAX_EXTRA_POSITIVES = 5
GATE_FILE = "tgold_gate.json"  # written next to score/score.json (run_layout kind requested from AG-00)
PIPELINE_STEPS = ("recognize", "layout", "tables", "compare", "export", "score")
# RT check owner → the pipeline step that produces its artifacts.
RT_STEP = {"AG-02A": "recognize", "AG-02B": "layout", "AG-02C": "tables"}

TITLES: dict[str, str] = {
    "G1": "Ответ существует и соответствует схемам (организаторов и расширенной)",
    "G2": "Все эталонные ключи найдены как VIOLATION_PRESENT",
    "G3": "Для каждого ключа указаны эталонные страницы ПД и РД (правило опорной страницы)",
    "G4": "Гейт критических нарушений не срабатывает (ключ и строгий вариант)",
    "G5": "Статусы совпадают с эталоном; значения по шаблонам",
    "G6": f"Не более {MAX_EXTRA_POSITIVES} лишних ключей VIOLATION_PRESENT",
    "G7": "Целостность R1–R15 и упаковка P1–P6 (sidecar и строгий вариант)",
    "G8": "Регрессионные проверки распознавания RT-01…RT-10",
    "G9": "Время прогона записано",
}
HARD = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


@dataclass(slots=True)
class Criterion:
    id: str
    status: str = "PASS"  # PASS | FAIL | WARN | NOT_EVALUATED
    details: list[str] = field(default_factory=list)
    measured: dict[str, Any] = field(default_factory=dict)

    def fail(self, detail: str) -> None:
        self.status = "FAIL"
        self.details.append(detail)

    def warn(self, detail: str) -> None:
        if self.status == "PASS":
            self.status = "WARN"
        self.details.append(detail)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title_ru": TITLES[self.id],
            "hard": self.id in HARD,
            "status": self.status,
            "details": self.details,
            "measured": self.measured,
        }


@dataclass(slots=True)
class GateResult:
    run_dir: str
    object_id: str
    criteria: dict[str, Criterion]
    score: dict[str, Any] | None
    rt: dict[str, Any] | None

    @property
    def status(self) -> str:
        hard = [self.criteria[c] for c in HARD]
        if any(c.status == "FAIL" for c in hard):
            return "FAIL"
        if any(c.status == "NOT_EVALUATED" for c in hard):
            return "INCOMPLETE"
        return "PASS"

    def hard_ok(self, ids: Sequence[str] = HARD) -> bool:
        return all(self.criteria[c].status in ("PASS", "WARN") for c in ids)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": "T-GOLD",
            "run_dir": self.run_dir,
            "object_id": self.object_id,
            "status": self.status,
            "criteria": [c.as_dict() for c in self.criteria.values()],
            "score": self.score,
            "rt": self.rt,
        }


# ── pipeline readiness ───────────────────────────────────────────────────────────────────────


def _is_stub(function: Any) -> bool:
    """True when the function body (docstring aside) is a single ``raise CommandNotImplementedError(...)``."""
    try:
        tree = ast.parse(inspect.getsource(function).lstrip())
    except (OSError, TypeError, SyntaxError):
        return False
    body = tree.body[0].body if tree.body and isinstance(tree.body[0], ast.FunctionDef) else []
    body = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    if len(body) != 1 or not isinstance(body[0], ast.Raise) or body[0].exc is None:
        return False
    call = body[0].exc
    name = call.func if isinstance(call, ast.Call) else call
    return isinstance(name, ast.Name | ast.Attribute) and (
        getattr(name, "id", None) == "CommandNotImplementedError"
        or getattr(name, "attr", None) == "CommandNotImplementedError"
    )


def pipeline_stubs() -> dict[str, str]:
    """Steps of ``inspector-batch run`` whose hook is still a stub: step → owner."""
    from inspector_batch.commands import COMMANDS

    stubs = {}
    for step in PIPELINE_STEPS:
        spec = COMMANDS[step]
        module = importlib.import_module(spec.module)
        if _is_stub(getattr(module, f"run_{step}")):
            stubs[step] = spec.owner
    return stubs


# ── evaluation ───────────────────────────────────────────────────────────────────────────────


def _key(check: Mapping[str, Any], cfg: ScoreConfig) -> tuple[str, str]:
    return normalize_code(check.get("parameter_code"), cfg.code_norm), normalize_location(
        check.get("location"), cfg.location_norm
    )


def _steps_ok(run_dir: Path) -> dict[str, str]:
    path = run_dir / "pipeline_summary.json"
    if not path.is_file():
        return {}
    raw = read_json(path)
    return {str(s.get("step")): str(s.get("status")) for s in raw.get("steps", []) if isinstance(s, Mapping)}


def _runtime(run_dir: Path, runtime_s: float | None, object_id: str = T_GOLD_OBJECT) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if runtime_s is not None:
        out["wall_s"] = round(runtime_s, 1)
    sidecar = RunLayout(run_dir).path("SUBMISSION_SIDECAR", object_id=object_id)
    if sidecar.is_file():
        raw = read_json(sidecar)
        timings = raw.get("timings_s") if isinstance(raw, Mapping) else None
        if isinstance(timings, Mapping) and timings:
            out["sidecar_timings_s"] = dict(timings)
            out["sidecar_span"] = [raw.get("started_at"), raw.get("finished_at")]
    manifest = run_dir / "run_manifest.json"
    if manifest.is_file():
        timings = read_json(manifest).get("timings_s")
        if isinstance(timings, Mapping) and timings:
            out["run_manifest_timings_s"] = dict(timings)
    recognize = run_dir / "recognize_summary.json"
    if recognize.is_file():
        raw = read_json(recognize)
        out["recognize"] = {
            k: raw.get(k) for k in ("wall_s", "pages_total", "pages_processed", "pages_cached")
        }
    steps = _steps_ok(run_dir)
    if steps:
        out["pipeline_steps"] = steps
    return out


def evaluate(
    run_dir: Path,
    ctx: ScoringContext,
    gold_rows: Sequence[Mapping[str, Any]],
    *,
    object_id: str = T_GOLD_OBJECT,
    cfg: ScoreConfig = DEFAULT_CONFIG,
    max_extra: int = MAX_EXTRA_POSITIVES,
    runtime_s: float | None = None,
    with_rt: bool | None = None,
) -> GateResult:
    """Evaluate one run directory against the gold rows of ``object_id``."""
    layout = RunLayout(run_dir)
    criteria = {cid: Criterion(cid) for cid in TITLES}
    gold = gold_for_object(gold_rows, object_id)
    answer_path = layout.path("SUBMISSION", object_id=object_id)
    score_summary: dict[str, Any] | None = None

    if not answer_path.is_file():
        for cid in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
            criteria[cid].status = "FAIL"
        criteria["G1"].details.append(f"нет ответа {answer_path}")
        document = None
    else:
        document = read_json(answer_path)
        result: ObjectScore = score_object(gold, document, ctx, cfg, object_id=object_id, extras=False)
        score_summary = {
            "total": round(result.total, 4),
            "total_uncapped": round(result.total_uncapped, 4),
            "components": {k: round(v, 4) for k, v in result.components.items()},
            "gate_triggered": result.gate_triggered,
            "counts": result.counts,
        }
        # G1 schemas
        g1 = criteria["G1"]
        for name in ("organizer", "extended"):
            errors = result.schema.errors[name]
            if errors:
                g1.fail(f"схема {name}: {errors[0]}")
        # G2 keys
        g2 = criteria["G2"]
        missed = [f"{k[0]} · {k[1]}" for k in result.detection_variants["k1"].fn_items]
        g2.measured.update(
            gold_positives=result.counts["gold_positives"], found=result.detection_variants["k1"].tp
        )
        if missed:
            g2.fail("не найдены: " + ", ".join(missed))
        # G3 pages (recall with stage == 1 per key)
        g3 = criteria["G3"]
        partial = [
            f"{row['parameter_code']} · {row['location']} ({row['localisation']:.2f})"
            for row in result.per_check
            if row["gold_label"] == POSITIVE and row["outcome"] == "TP" and (row["localisation"] or 0.0) < 1.0
        ]
        g3.measured["localisation"] = round(result.localisation, 4)
        if partial:
            g3.fail("не все эталонные страницы: " + ", ".join(partial))
        if missed:
            g3.fail("ключи не найдены — страницы не проверены")
        # G4 gate: key variant and strict variant
        g4 = criteria["G4"]
        strict = score_object(
            gold, document, ctx, cfg.replace(gate="strict"), object_id=object_id, extras=False
        )
        g4.measured.update(
            checkpoints=len(result.gate.checkpoints),
            triggered=result.gate_triggered,
            strict_triggered=strict.gate_triggered,
        )
        if result.gate_triggered:
            g4.fail(
                "пропущены: " + ", ".join(f"{c.parameter_code} · {c.location}" for c in result.gate.missed)
            )
        elif strict.gate_triggered:
            g4.fail(
                "строгий вариант: "
                + ", ".join(f"{c.parameter_code} · {c.location}" for c in strict.gate.missed)
            )
        # G5 statuses and values
        g5 = criteria["G5"]
        g5.measured.update(status_only=round(result.status_only, 4), values_only=round(result.values_only, 4))
        wrong_status = [
            f"{row['parameter_code']} · {row['location']}"
            for row in result.per_check
            if row["check_id"] is not None and (row["status_score"] or 0.0) < 1.0
        ]
        if wrong_status:
            g5.fail("статусы расходятся: " + ", ".join(wrong_status))
        if result.values_only < 1.0:
            g5.warn(f"значения совпадают на {result.values_only:.3f} (шаблоны 93 §3.5)")
        # G6 extras
        g6 = criteria["G6"]
        gold_keys = {_key(g, cfg) for g in gold if g.get("violation_label") == POSITIVE}
        checks = document.get("checks", []) if isinstance(document, Mapping) else []
        predicted = {
            _key(c, cfg) for c in checks if isinstance(c, Mapping) and c.get("violation_label") == POSITIVE
        }
        extras = sorted(predicted - gold_keys)
        g6.measured.update(
            extra_positive_keys=len(extras), examples=[f"{k[0]} · {k[1]}" for k in extras[:10]]
        )
        if len(extras) > max_extra:
            g6.fail(f"лишних ключей {len(extras)} > {max_extra}")
        # G7 integrity + packaging
        g7 = criteria["G7"]
        answers = integrity.discover(answer_path)
        report = integrity.check_files(answers, ctx, require_packaging=True, cfg=cfg)[0]
        g7.measured.update(
            integrity_share=round(report.integrity.share, 4),
            failed_rules=report.failed_rules,
            r9=report.integrity.rules["R9"].status,
        )
        if report.failed_rules or not report.schema.organizer_valid:
            g7.fail("нарушены правила: " + ", ".join(report.failed_rules or ["R1"]))
        if report.integrity.rules["R9"].status == "NOT_EVALUATED":
            g7.details.append("R9 не проверялось: нет списка устаревших редакций (AG-01)")

    # G8 RT checks
    g8 = criteria["G8"]
    rt_summary = None
    if with_rt is None:
        with_rt = object_id == T_GOLD_OBJECT
    if not with_rt:
        g8.status = "NOT_EVALUATED"
        g8.details.append("проверки RT определены только для T-GOLD")
    else:
        results = rtcheck.run_checks(run_dir)
        steps = _steps_ok(run_dir)
        for r in results:
            step = RT_STEP.get(r.owner)
            if r.status == "NOT_EVALUATED" and step and steps.get(step) == "ok":
                r.fail(f"шаг «{step}» выполнен, но артефакта нет")
        rt_summary = rtcheck.summary(results)
        g8.measured.update({k: rt_summary[k] for k in ("pass", "fail", "not_evaluated")})
        failed = [r for r in results if r.status == "FAIL"]
        missing = [r for r in results if r.status == "NOT_EVALUATED"]
        for r in failed:
            g8.fail(f"{r.rt_id} [{r.owner}]: {'; '.join(r.details[:2])}")
        if missing and not failed:
            g8.status = "NOT_EVALUATED"
            g8.details.append("нет артефактов: " + ", ".join(f"{r.rt_id} [{r.owner}]" for r in missing))

    # G9 runtime logged
    g9 = criteria["G9"]
    runtime = _runtime(run_dir, runtime_s, object_id)
    g9.measured.update(runtime)
    timed = {"wall_s", "run_manifest_timings_s", "recognize", "sidecar_timings_s"} & set(runtime)
    if not runtime:
        g9.warn("нет данных о времени прогона (pipeline_summary, timings, wall time)")
    elif not timed:
        g9.warn("есть только сводка шагов, без времени")

    return GateResult(str(run_dir), object_id, criteria, score_summary, rt_summary)


def write(result: GateResult, run_dir: Path) -> Path:
    out = run_dir / "score"
    out.mkdir(parents=True, exist_ok=True)
    path = out / GATE_FILE
    path.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render(result: GateResult) -> str:
    mark = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "NOT_EVALUATED": "—"}
    status_ru = {"PASS": "ПРОЙДЕН", "FAIL": "НЕ ПРОЙДЕН", "INCOMPLETE": "НЕ ЗАВЕРШЁН (нет части артефактов)"}
    lines = [f"Приёмка T-GOLD ({result.object_id}): {status_ru[result.status]}"]
    if result.score:
        comps = result.score["components"]
        lines.append(
            f"  итог {result.score['total']:.2f} (F1 {comps.get('finding_detection_f1', 0):.3f}, "
            f"лок. {comps.get('source_localization_exact_file_page', 0):.3f}, "
            f"знач. {comps.get('normalized_value_and_status_accuracy', 0):.3f}, "
            f"цел. {comps.get('document_integrity_and_split_handling', 0):.3f})"
        )
    for c in result.criteria.values():
        lines.append(f"  {mark[c.status]} {c.id} {TITLES[c.id]}: {c.status}")
        lines.extend(f"        {d}" for d in c.details[:4])
    if result.rt:
        lines.append(rtcheck.render([_rt_from_dict(d) for d in result.rt["checks"]]))
    return "\n".join(lines)


def _rt_from_dict(d: Mapping[str, Any]) -> rtcheck.RTResult:
    return rtcheck.RTResult(
        d["id"], d["owner"], d["title_ru"], d["status"], list(d["details"]), dict(d["measured"])
    )
