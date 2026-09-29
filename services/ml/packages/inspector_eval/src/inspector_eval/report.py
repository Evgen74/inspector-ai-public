"""Outputs of inspector-score (93 §4.7): score.json, per_check.csv, gate.csv, summary.txt.

The text report is Russian (user-facing); JSON keys are English.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from inspector_common.paths import ensure_dir
from inspector_eval.config import ScoreConfig
from inspector_eval.data import ScoringContext
from inspector_eval.scoring import ObjectScore, PooledScore
from inspector_eval.validation import RULE_TITLES

COMPONENT_TITLES_RU: dict[str, str] = {
    "finding_detection_f1": "Выявление нарушений (F1)",
    "source_localization_exact_file_page": "Локализация (файл и страница)",
    "normalized_value_and_status_accuracy": "Значения и статусы",
    "document_integrity_and_split_handling": "Целостность и разбиение",
}
GATE_STATUS_RU = {
    "FOUND": "найдена",
    "FOUND_WRONG_EVIDENCE": "найдена, страницы не совпали",
    "MISSED": "ПРОПУЩЕНА",
}
SWITCH_TITLES_RU: dict[str, str] = {
    "key": "единица F1",
    "group_rule": "правило группы (k3)",
    "loc_metric": "метрика локализации",
    "loc_with_stage": "локализация со стадией",
    "value_norm": "нормализация значений",
    "location_norm": "нормализация места",
    "code_norm": "нормализация кода",
    "criticality_norm": "нормализация критичности",
    "gate": "вариант гейта",
    "integrity": "режим целостности",
    "integrity_rules": "набор правил целостности",
}


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fmt(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def build_report(
    objects: Sequence[ObjectScore],
    pooled: PooledScore | None,
    cfg: ScoreConfig,
    ctx: ScoringContext,
    *,
    gold_path: str | None = None,
    gold_sha256: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "report": "inspector-score",
        "generated_at": utc_now(),
        "config": cfg.describe(),
        "inputs": {
            "gold_path": gold_path,
            "gold_sha256": gold_sha256,
            **dict(ctx.input_hashes),
        },
        "weights": dict(ctx.weights),
        "gate_cap": ctx.gate_cap,
        "objects": [o.as_dict() for o in objects],
        "pooled": pooled.as_dict() if pooled is not None and len(objects) > 1 else None,
        **(dict(extra) if extra else {}),
    }


PER_CHECK_COLUMNS = (
    "object_id",
    "check_id",
    "finding_group_id",
    "parameter_code",
    "location",
    "gold_label",
    "pred_label",
    "outcome",
    "localisation",
    "status_score",
    "values_score",
    "value_status",
    "gate_checkpoint",
)
GATE_COLUMNS = (
    "object_id",
    "check_id",
    "finding_group_id",
    "parameter_code",
    "location",
    "gold_label",
    "status",
    "broad_ok",
)


def write_outputs(
    report: Mapping[str, Any], objects: Sequence[ObjectScore], out_dir: Path
) -> dict[str, Path]:
    out = ensure_dir(out_dir)
    paths = {
        "score": out / "score.json",
        "per_check": out / "per_check.csv",
        "gate": out / "gate.csv",
        "summary": out / "summary.txt",
    }
    paths["score"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with paths["per_check"].open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PER_CHECK_COLUMNS)
        writer.writeheader()
        for o in objects:
            writer.writerows(o.per_check)
    with paths["gate"].open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=GATE_COLUMNS)
        writer.writeheader()
        for o in objects:
            for cp in o.gate.checkpoints:
                writer.writerow({"object_id": o.object_id, **cp.as_dict()})
    paths["summary"].write_text(render_text(objects, report.get("pooled")) + "\n", encoding="utf-8")
    return paths


def render_object(o: ObjectScore) -> list[str]:
    lines: list[str] = []
    lines.append(f"Объект: {o.object_id}")
    if o.prediction_missing:
        lines.append("  Ответ по объекту не найден: все компоненты = 0.")
    schema = o.schema.as_dict()

    def verdict(name: str, hard: bool = False) -> str:
        entry = schema[name]
        if entry["valid"]:
            return "соответствует"
        text = f"не соответствует ({len(entry['errors'])} ошибок)"
        return text.upper() + " — все компоненты = 0" if hard else text

    lines.append(
        f"  Схема организаторов: {verdict('organizer', hard=True)}; строгая схема: {verdict('strict')}; "
        f"полная схема: {verdict('extended')}"
    )
    gate_note = " — СРАБОТАЛ ГЕЙТ (балл ограничен)" if o.gate_triggered else ""
    lines.append(
        f"  Итоговый балл: {_fmt(o.total)} из 100 (без ограничения: {_fmt(o.total_uncapped)}){gate_note}"
    )
    comps, points = o.components, o.points
    det = o.detection
    detail = {
        "finding_detection_f1": f"F1 {det.f1:.3f} (P {det.precision:.3f}, R {det.recall:.3f}; TP {det.tp}, FP {det.fp}, FN {det.fn}; вариант {det.variant})",
        "source_localization_exact_file_page": f"{comps['source_localization_exact_file_page']:.3f} ({o.config.loc_metric}, n={o.localisation_n})",
        "normalized_value_and_status_accuracy": f"{comps['normalized_value_and_status_accuracy']:.3f} (статусы {o.status_only:.3f}, значения {o.values_only:.3f}, n={o.value_status_n})",
        "document_integrity_and_split_handling": _integrity_line(o),
    }
    for name, title in COMPONENT_TITLES_RU.items():
        lines.append(f"    {title:<32} {_fmt(points[name]):>6} / {o.weights[name]:g}   {detail[name]}")
    gate = o.gate
    found = sum(1 for c in gate.checkpoints if c.status == "FOUND")
    lines.append(
        f"  Гейт критических точек ({gate.variant}): {len(gate.checkpoints)} точек, найдено {found}, "
        f"пропущено {sum(1 for c in gate.checkpoints if c.status == 'MISSED')}"
    )
    for cp in gate.checkpoints:
        if cp.status != "FOUND":
            lines.append(
                f"    {GATE_STATUS_RU[cp.status]}: {cp.parameter_code} · {cp.location} ({cp.check_id}, {cp.finding_group_id})"
            )
    failed = [r for r in o.integrity.rules.values() if r.status == "FAIL"]
    for rule in failed:
        lines.append(f"  Нарушено {rule.rule} «{RULE_TITLES[rule.rule]}»: {len(rule.violations)}")
        for v in rule.violations[:5]:
            lines.append(f"    — {v.detail_ru}")
    warn = o.integrity.rules.get("R15")
    if warn is not None and warn.status == "WARN":
        lines.append(f"  Предупреждение R15 (грамматика мест): {len(warn.violations)}")
    if o.hedges is not None and o.hedges.hedges:
        h = o.hedges
        lines.append(
            f"  Страховочные коды: {h.hedges} (доля {h.share:.0%} от {h.critical_emitted} критических, "
            f"бюджет {h.budget:.0%} — {'в пределах' if h.within_budget else 'ПРЕВЫШЕН'})"
        )
        if h.what_if:
            lines.append(
                f"    Без страховки: {_fmt(h.what_if['total'])} (без ограничения {_fmt(h.what_if['total_uncapped'])})"
            )
    fps = [r for r in o.per_check if r["outcome"] == "FP"]
    if fps:
        lines.append(f"  Лишние нарушения (FP): {len(fps)}")
        for r in fps[:10]:
            lines.append(f"    — {r['parameter_code']} · {r['location']}")
    fns = [r for r in o.per_check if r["outcome"] == "FN"]
    if fns:
        lines.append(f"  Пропущенные нарушения (FN): {len(fns)}")
        for r in fns[:10]:
            lines.append(f"    — {r['parameter_code']} · {r['location']} ({r['check_id']})")
    if o.sensitivity:
        changed = [r for r in o.sensitivity if abs(r["total"] - o.total) > 0.005]
        if not changed:
            lines.append("  Чувствительность к допущениям: итог не меняется ни при одном переключателе.")
        else:
            lines.append("  Чувствительность к допущениям (итог меняется при смене одного переключателя):")
            for row in changed:
                gate_mark = " (гейт)" if row["gate_triggered"] else ""
                lines.append(
                    f"    {SWITCH_TITLES_RU.get(row['switch'], row['switch'])} = {row['value']}: "
                    f"{_fmt(row['total'])}{gate_mark}"
                )
    return lines


def _integrity_line(o: ObjectScore) -> str:
    d = o.integrity.as_dict()
    mode = "доля правил" if o.config.integrity == "share" else "жёсткий"
    return (
        f"{d['share']:.3f} (правил выполнено {d['passed']} из {d['counted']}, {mode}, набор {d['rule_set']})"
    )


def render_text(objects: Sequence[ObjectScore], pooled: Mapping[str, Any] | None = None) -> str:
    lines = ["Оценка ответа (inspector-score, гипотеза H1 из отчёта 93)"]
    if objects:
        cfg = objects[0].config
        lines.append(
            f"Настройки: ключ {cfg.key}, локализация {cfg.loc_metric}{'' if cfg.loc_with_stage else ' без стадии'}, "
            f"гейт {cfg.gate}, место {cfg.location_norm}, код {cfg.code_norm}, значения {cfg.value_norm} "
            f"(порог {cfg.value_threshold:g}), целостность {cfg.integrity}/{cfg.integrity_rules}"
        )
    for o in objects:
        lines.append("")
        lines.extend(render_object(o))
    if pooled:
        lines.append("")
        lines.append(
            f"Сводно по {len(pooled['objects'])} объектам (микроусреднение): {_fmt(pooled['total'])} "
            f"(без ограничения {_fmt(pooled['total_uncapped'])}){' — СРАБОТАЛ ГЕЙТ' if pooled['gate_triggered'] else ''}"
        )
    return "\n".join(lines)


def render_validation(object_id: str, schema: Mapping[str, Any], integrity: Mapping[str, Any]) -> str:
    lines = [f"Проверка ответа: {object_id}"]
    for name, title in (
        ("organizer", "схема организаторов"),
        ("strict", "строгая схема"),
        ("extended", "полная схема"),
    ):
        entry = schema[name]
        lines.append(f"  {title}: {'соответствует' if entry['valid'] else 'НЕ СООТВЕТСТВУЕТ'}")
        for err in entry["errors"][:5]:
            lines.append(f"    — {err}")
    lines.append(f"  Правила целостности: выполнено {integrity['passed']} из {integrity['counted']}")
    for rule in integrity["rules"]:
        if rule["status"] in ("FAIL", "WARN"):
            lines.append(f"  {rule['status']} {rule['rule']} «{rule['title_ru']}»: {len(rule['violations'])}")
            for v in rule["violations"][:5]:
                lines.append(f"    — {v['detail_ru']}")
        elif rule["status"] == "NOT_EVALUATED":
            lines.append(f"  не проверено {rule['rule']} «{rule['title_ru']}»: {rule.get('note_ru', '')}")
    return "\n".join(lines)
