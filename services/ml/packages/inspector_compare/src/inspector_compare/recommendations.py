"""Приложение 2 texts per parameter: «Вид работ», «Вид нарушения», «Отклонение», «Конкретная рекомендация».

Source (first found wins; the sha256 of the file is part of the compare config hash):

1. ``$INSPECTOR_RECOMMENDATION_TEMPLATES`` (a path);
2. ``packages/contracts/seed/recommendation_templates.json`` (AG-03 seed: DeviationKind codes, English keys);
3. ``docs/analysis/norms_staging/recommendation_templates.json`` (AG-03 staged draft: lower-case keys, Russian
   transliterated field names);
4. fallback: the params seed fields ``work_type`` / ``recommendation_template`` / ``deviation_verb``.

Both file formats are normalised to one internal shape (``_normalise``). Rendering follows the templates'
``rendering_rules``: R1–R2 placeholders inside parentheses drop their «; »-part (or the whole bracket group) when
the value is missing; R3 a missing placeholder outside brackets ({delta}, {element}, norms) drops with its lead-in
(«на », «: », « — », «, », space); R8 the code suffix « ({code})». Texts are AG-03 drafts (TextOrigin AG03_DRAFT
unless APPENDIX2) and are printed with the preliminary prefix until an inspector confirms (93 §5.4).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from inspector_common.hashing import sha256_file
from inspector_common.paths import contracts_dir, repo_root

PRELIMINARY_PREFIX = "Проект рекомендации (до подтверждения инспектором): "

# DiscrepancyType → DeviationKind (seed vocabularies.discrepancy_to_deviation_kind; used when the file lacks it).
DEVIATION_KIND: Mapping[str, str] = {
    "VALUE_DECREASED": "DECREASE",
    "VALUE_INCREASED": "INCREASE",
    "VALUE_CHANGED": "BY_SIGN",
    "THRESHOLD_BELOW_MIN": "NORM_VIOLATION",
    "THRESHOLD_ABOVE_MAX": "NORM_VIOLATION",
    "TOLERANCE_EXCEEDED": "TOLERANCE_EXCEEDED",
    "CLASS_DOWNGRADED": "CLASS_DOWNGRADE",
    "MATERIAL_SUBSTITUTED": "SUBSTITUTION",
    "ELEMENT_MISSING": "ABSENCE",
    "ELEMENT_ADDED": "CONFIGURATION_CHANGE",
    "FUNCTION_CHANGED": "CONFIGURATION_CHANGE",
    "LAYER_REMOVED": "ABSENCE",
    "LAYER_CHANGED": "CONFIGURATION_CHANGE",
    "POSITION_SHIFTED": "CONFIGURATION_CHANGE",
    "CONFIGURATION_CHANGED": "CONFIGURATION_CHANGE",
    "COUNT_CHANGED": "BY_SIGN",
    "TOTAL_CHANGED": "BY_SIGN",
    "UNDOCUMENTED_WORK": "ABSENCE",
}
KIND_DIRECTION: Mapping[str, str] = {
    "DECREASE": "DECREASE",
    "INCREASE": "INCREASE",
    "CLASS_DOWNGRADE": "DECREASE",
    "ABSENCE": "ABSENT",
    "SUBSTITUTION": "CHANGED",
    "CONFIGURATION_CHANGE": "CHANGED",
    "NORM_VIOLATION": "DECREASE",
    "TOLERANCE_EXCEEDED": "DECREASE",
    "ZONE_INTRUSION": "ABSENT",
}
DEFAULT_PHRASES: Mapping[str, str] = {
    "DECREASE": "⬇️ Уменьшение на {delta}",
    "INCREASE": "⬆️ Превышение {delta}",
    "CLASS_DOWNGRADE": "⬇️ Понижение класса",
    "ABSENCE": "❌ Полное отсутствие",
    "SUBSTITUTION": "🔄 Замена",
    "CONFIGURATION_CHANGE": "🔄 Изменена конфигурация",
    "NORM_VIOLATION": "⬇️ Не соответствует норме",
    "TOLERANCE_EXCEEDED": "⬇️ Отклонение сверх допуска",
    "ZONE_INTRUSION": "❌ Нарушение границ зоны",
}
_OUTSIDE = ("delta", "element", "norm_value", "norm_ref")


@dataclass(frozen=True, slots=True)
class TemplateSet:
    by_code: Mapping[str, Mapping[str, Any]]
    free_topics: Mapping[str, Mapping[str, Any]]
    default_phrases: Mapping[str, str]
    kind_of_discrepancy: Mapping[str, str]
    kind_direction: Mapping[str, str]
    source: str
    sha256: str | None
    status: str | None = None


def _upper_keys(d: Any) -> dict[str, Any]:
    return {str(k).upper(): v for k, v in (d or {}).items() if v}


def _delta_format(value: Any) -> dict[str, Any]:
    """«pct» | {"default": "pct", "absence": "count"} | {"default": "PCT", "by_kind": {...}} → {default, by_kind}."""
    if value is None:
        return {"default": "NONE", "by_kind": {}}
    if isinstance(value, str):
        return {"default": value.upper(), "by_kind": {}}
    by_kind = dict(value.get("by_kind") or {})
    by_kind.update({k: v for k, v in value.items() if k not in ("default", "by_kind")})
    return {
        "default": str(value.get("default") or "NONE").upper(),
        "by_kind": {k.upper(): str(v).upper() for k, v in by_kind.items()},
    }


def _normalise(t: Mapping[str, Any]) -> dict[str, Any]:
    """One template (matrix or FREE topic) in either file format → the internal shape."""
    presets = {}
    for name, p in (t.get("element_presets") or {}).items():
        presets[name] = {
            "violation_kind": p.get("violation_kind") or p.get("vid_narusheniya"),
            "recommendation": p.get("recommendation"),
            "pd_value": p.get("pd_value"),
            "rd_value": p.get("rd_value"),
        }
    origin = t.get("text_origin")
    return {
        "template_id": t.get("template_id")
        or t.get("code")
        or (f"FREE-{t['topic']}" if t.get("topic") else None),
        "short_name": t.get("short_name"),
        "work_type": t.get("work_type") or t.get("vid_rabot"),
        "violation_kind": t.get("violation_kind") or t.get("vid_narusheniya"),
        "violation_kind_variants": _upper_keys(
            t.get("violation_kind_variants") or t.get("vid_narusheniya_variants")
        ),
        "recommendation": t.get("recommendation"),
        "recommendation_variants": _upper_keys(t.get("recommendation_variants")),
        "deviation_phrases": _upper_keys(t.get("deviation_phrases")),
        "delta_format": _delta_format(t.get("delta_format")),
        "count_noun": t.get("count_noun"),
        "norm_fill": dict(t.get("norm_fill") or {}),
        "norm_refs": [
            str(r.get("designation"))
            for r in (t.get("norm_refs") or t.get("norm_refs_used") or [])
            if r.get("designation")
        ],
        "element_presets": presets,
        "text_origin": origin.get("recommendation") if isinstance(origin, Mapping) else origin,
    }


def _candidate_paths() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("INSPECTOR_RECOMMENDATION_TEMPLATES")
    if env:
        out.append(Path(env).expanduser())
    out.append(contracts_dir() / "seed" / "recommendation_templates.json")
    with contextlib.suppress(Exception):  # the repo root always exists in the workspace
        out.append(repo_root() / "docs" / "analysis" / "norms_staging" / "recommendation_templates.json")
    return out


@lru_cache(maxsize=4)
def _load(path_key: str | None) -> TemplateSet:
    paths = [Path(path_key)] if path_key else _candidate_paths()
    for path in paths:
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        vocab = doc.get("vocabularies") or {}
        phrases = dict(DEFAULT_PHRASES)
        phrases.update(_upper_keys(doc.get("default_deviation_phrases")))
        directions = dict(KIND_DIRECTION)
        for kind in vocab.get("deviation_kinds") or []:
            if kind.get("default_phrase"):
                phrases[str(kind["code"])] = str(kind["default_phrase"])
            if kind.get("direction"):
                directions[str(kind["code"])] = str(kind["direction"])
        return TemplateSet(
            by_code={t["code"]: _normalise(t) for t in doc.get("templates", []) if t.get("code")},
            free_topics={t["topic"]: _normalise(t) for t in doc.get("free_topics", []) if t.get("topic")},
            default_phrases=phrases,
            kind_of_discrepancy={**DEVIATION_KIND, **(vocab.get("discrepancy_to_deviation_kind") or {})},
            kind_direction=directions,
            source=str(path),
            sha256=sha256_file(path),
            status=doc.get("status"),
        )
    return TemplateSet(
        {}, {}, dict(DEFAULT_PHRASES), dict(DEVIATION_KIND), dict(KIND_DIRECTION), "params-seed", None
    )


def load_templates(path: str | Path | None = None) -> TemplateSet:
    return _load(str(path) if path else None)


def clear_cache() -> None:
    _load.cache_clear()


# ── rendering rules ───────────────────────────────────────────────────────────────────────────

_PH = re.compile(r"\{([a-z_]+)\}")
_GROUP = re.compile(r"\s?\(([^()]*)\)")


def _available(values: Mapping[str, Any], name: str) -> bool:
    v = values.get(name)
    return v is not None and str(v).strip() != ""


def fill(template: str | None, values: Mapping[str, Any]) -> str | None:
    """Apply R1–R3 and fill placeholders. Returns None for an empty template."""
    if not template:
        return None
    text = template

    def group(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not _PH.search(inner):
            return match.group(0)
        parts = [p for p in inner.split("; ") if all(_available(values, n) for n in _PH.findall(p))]
        if not parts:
            return ""
        lead = " " if match.group(0).startswith(" ") else ""
        return f"{lead}({'; '.join(parts)})"

    text = _GROUP.sub(group, text)
    for name in _OUTSIDE:
        if not _available(values, name):
            text = re.sub(r"(?:\s+на\s+|:\s+|\s+—\s+|,\s+|\s+)?\{" + name + r"\}", "", text)
    text = _PH.sub(lambda m: str(values.get(m.group(1), "")) if _available(values, m.group(1)) else "", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    text = re.sub(r"\(\s*\)", "", text).strip()
    return text or None


@dataclass(slots=True)
class RenderedTexts:
    """Everything the protocol and the finding carry for one violation group."""

    deviation_kind: str
    deviation_direction: str
    deviation_text: str
    work_type: str  # «{work_type} ({code})» (7.1)
    violation_kind: str  # «{violation_kind} ({code})» (7.2)
    recommendation: str  # without the preliminary prefix
    template_id: str | None
    text_origin: str
    normative_refs: list[str] = field(default_factory=list)
    work_type_plain: str | None = None
    delta_format: dict[str, Any] = field(default_factory=dict)


def _param_fallback(code: str) -> dict[str, Any]:
    from inspector_common.params import load_params

    try:
        spec = load_params().get(code)
    except Exception:
        return {}
    verbs = spec.data.get("deviation_verb") or {}
    return {
        "work_type": spec.data.get("work_type"),
        "recommendation": spec.data.get("recommendation_template"),
        "verbs": verbs,
    }


def _kind(ts: TemplateSet, discrepancy_type: str, sign: float | None) -> str:
    kind = ts.kind_of_discrepancy.get(discrepancy_type, "CONFIGURATION_CHANGE")
    if kind == "BY_SIGN":
        kind = "DECREASE" if (sign is None or sign < 0) else "INCREASE"
    return kind


def delta_format_for(tpl: Mapping[str, Any], kind: str) -> str:
    fmt = tpl.get("delta_format") or {}
    return str((fmt.get("by_kind") or {}).get(kind) or fmt.get("default") or "NONE")


def render_texts(
    code: str,
    discrepancy_type: str,
    values: Mapping[str, Any],
    *,
    free_topic: str | None = None,
    element_noun: str | None = None,
    templates: TemplateSet | None = None,
    sign: float | None = None,
) -> RenderedTexts:
    """Texts for one group. ``values``: location, pd_value, rd_value, id_value, actual_value, delta, element."""
    ts = templates or load_templates()
    kind = _kind(ts, discrepancy_type, sign)
    preset: Mapping[str, Any] = {}
    if free_topic is not None:
        tpl: Mapping[str, Any] = ts.free_topics.get(free_topic, {})
        if element_noun:
            wanted = element_noun.casefold().replace("ё", "е")
            for name, value in (tpl.get("element_presets") or {}).items():
                if name.casefold().replace("ё", "е") == wanted:
                    preset = value
                    break
    else:
        tpl = ts.by_code.get(code) or {}
    fallback = _param_fallback(code) if (not tpl and free_topic is None) else {}
    norm_fill = dict(tpl.get("norm_fill") or {})
    vals: dict[str, Any] = {"norm_value": norm_fill.get("norm_value"), "norm_ref": norm_fill.get("norm_ref")}
    vals.update({k: v for k, v in values.items() if v not in (None, "")})
    if element_noun and "element" not in vals:
        vals["element"] = element_noun[:1].lower() + element_noun[1:]

    phrase = (
        (tpl.get("deviation_phrases") or {}).get(kind)
        or ts.default_phrases.get(kind)
        or "🔄 Изменена конфигурация"
    )
    deviation = fill(phrase, vals) or ""
    work_type = tpl.get("work_type") or fallback.get("work_type") or "Работы по разделу"
    violation_kind = (
        preset.get("violation_kind")
        or (tpl.get("violation_kind_variants") or {}).get(kind)
        or tpl.get("violation_kind")
        or (fallback.get("verbs") or {}).get(discrepancy_type)
        or deviation.split(" ", 1)[-1]
    )
    recommendation = (
        preset.get("recommendation")
        or (tpl.get("recommendation_variants") or {}).get(kind)
        or tpl.get("recommendation")
        or fallback.get("recommendation")
        or "Представить обоснование расхождения либо привести документацию в соответствие с ПД."
    )
    suffix = f" ({code})"
    origin = tpl.get("text_origin")
    return RenderedTexts(
        deviation_kind=kind,
        deviation_direction=ts.kind_direction.get(kind, "CHANGED"),
        deviation_text=deviation,
        work_type=(fill(work_type, vals) or work_type) + suffix,
        violation_kind=(fill(violation_kind, vals) or violation_kind) + suffix,
        recommendation=fill(recommendation, vals) or recommendation,
        template_id=tpl.get("template_id") if tpl else None,
        text_origin=origin if origin in ("APPENDIX2", "AG03_DRAFT") else "AG03_DRAFT",
        normative_refs=list(tpl.get("norm_refs") or []),
        work_type_plain=work_type,
        delta_format=dict(tpl.get("delta_format") or {}),
    )
