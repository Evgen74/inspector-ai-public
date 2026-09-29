"""Build the matrix seed (packages/contracts/seed/*.json) — owner AG-03.

Inputs (read-only):
- the organizer catalog ``parameter_catalog_132.jsonl`` (canonical codes, names, units, criticality: the catalog
  wins on code, name and criticality, 97 §2.8);
- ``docs/analysis/matrix_enriched.json`` (132 × B03 enrichment: DSL rules, stages, applicability, references…);
- the YAML sources next to this script: regexes.yaml, texts.yaml, rules.yaml, change_matrix_map.yaml,
  free_topics.yaml, norms.yaml, value_templates.yaml;
- the web-verified norms and recommendation templates adopted from docs/analysis/norms_staging (src/norms/, M1;
  merged by build_templates.py);
- optionally the Приложение 2 docx (only its sha256 is recorded).

Outputs: params.json, change_matrix_map.json, free_topics.json, recommendation_templates.json,
value_templates.json (deterministic: same inputs → same bytes).

Run from services/ml::

    uv run --locked python ../../packages/contracts/seed/src/build_seed.py            # write
    uv run --locked python ../../packages/contracts/seed/src/build_seed.py --check    # exit 1 on drift
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_templates as bt  # sibling module of this script

from inspector_common.contracts import codes
from inspector_common.contracts.enums import DiscrepancyType
from inspector_common.contracts.loader import enum_mappings, load_enums
from inspector_common.contracts.models import CatalogRow
from inspector_common.hashing import sha256_file, sha256_json
from inspector_common.params import MAX_AUX_PATTERN_CHARS, MAX_REGEX_PATTERN_CHARS, regex_safety_problems
from inspector_common.paths import repo_root
from inspector_common.settings import Settings

MATRIX_VERSION = (
    "1.1.1"  # 90 §3.3.2: "{edition}.{seq}"; 1.1.0 = M0 seed, 1.1.1 = M1 (verified norms, templates)
)
SCHEMA_VERSION = 1

SRC = Path(__file__).resolve().parent
SEED = SRC.parent
REGEX_FLAGS_TEXT = (
    "Python re (3.12) через inspector_common.params.compile_guarded: статическая проверка безопасности, окна "
    "≤ 20 000 символов, бюджет времени на окно; применяется к тексту после normalize_regex_input (NFC, NBSP→пробел, "
    "унификация дефисов, м2→м², м3→м³). Основное значение — первая непустая группа v, v2, v3; прочие группы — "
    "атрибуты. Контекстные гейты (regex_gates) отсеивают омонимы (В20 — класс бетона или система вентиляции)."
)
GENERIC_REGEX_REASON = (
    "усиление: русские окончания [а-яё]*+ (посессивно) вместо \\w*, числа с якорем (?<![\\d.,]), ограниченные "
    "фильтры; прошёл regex_safety_problems и нагрузочный тест"
)
RISK = {"высокий": "HIGH", "средний": "MEDIUM"}
REF_KEYS = {"sp": "sp_reference", "gost": "gost_reference", "fz": "fz_reference", "other": "other_normative"}
CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class BuildError(RuntimeError):
    pass


def _load_yaml(name: str) -> Any:
    with open(SRC / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _canonical_ref(code: str) -> str:
    """«M-003» → «PZ-003»; «M-003.b» → «PZ-003.b»."""
    m = re.fullmatch(r"M-(\d{3})((?:\.[a-z])?)", code)
    if not m:
        raise BuildError(f"not an M-code: {code!r}")
    return codes.canonical_code(int(m.group(1))) + m.group(2)


def _atomic_rules(rule: dict[str, Any]) -> list[dict[str, Any]]:
    return rule["sub_checks"] if rule["rule_type"] == "COMPOSITE" else [rule]


def _rule_key(code: str, rule: dict[str, Any]) -> str:
    return rule.get("sub_id") or code


# ─────────────────────────────────────────────── DSL patching ───────────────────────────────────────────────────────


def _derive_direction(r: dict[str, Any]) -> str:
    if r.get("direction"):
        return r["direction"]
    rt = r["rule_type"]
    if rt == "ORDINAL_COMPARE":
        return "DOWNGRADE"
    if rt == "ENUM_CHANGE":
        return "ANY" if r.get("vocabulary") in (None, "free_text") else "DOWNGRADE"
    if rt in ("PRESENCE", "LAYER_STACK", "RATIO_BOUND"):
        return "DECREASE"
    if rt == "NORMATIVE_BOUND":
        bounds = r.get("bounds") or {}
        has_min, has_max = "min" in bounds, "max" in bounds
        if has_min and not has_max:
            return "DECREASE"
        if has_max and not has_min:
            return "INCREASE"
        return "ANY"
    if rt == "SET_DIFF":
        return "DECREASE" if set(r.get("detect", [])) == {"MISSING"} else "ANY"
    return "ANY"


def _derive_candidate_policy(r: dict[str, Any]) -> str:
    rt = r["rule_type"]
    if rt in ("NORMATIVE_BOUND", "RATIO_BOUND", "TOLERANCE_CHECK", "GEOMETRY_OFFSET"):
        return "TRIGGER"
    if rt == "PAIRWISE_DELTA" and r.get("operator") == "REL_DELTA_GT":
        return "TRIGGER"
    return "DEVIATION"


def patch_rule(
    code: str, rule_in: dict[str, Any], rules_src: dict[str, Any], changes: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rule = copy.deepcopy(rule_in)
    moved_ids = {m["sub_id"]: m for m in rules_src["moved_to_logical_rules"]}
    moved: list[dict[str, Any]] = []
    if rule["rule_type"] == "COMPOSITE":
        kept = []
        for sub in rule["sub_checks"]:
            sub["sub_id"] = _canonical_ref(sub["sub_id"])
            if sub["rule_type"] == "INTERNAL_CONSISTENCY":
                spec = moved_ids.get(sub["sub_id"])
                if spec is None:
                    raise BuildError(
                        f"{sub['sub_id']}: INTERNAL_CONSISTENCY sub-check without a moved_to_logical_rules entry"
                    )
                moved.append(
                    {
                        "sub_id": sub["sub_id"],
                        "code": code,
                        "title": sub.get("title"),
                        "logical_rule": spec["logical_rule"],
                        "operator": sub.get("operator"),
                        "evaluate_on": sub.get("evaluate_on"),
                        "tolerance": sub.get("tolerance"),
                        "reason": spec["reason"],
                    }
                )
                changes.append(
                    {
                        "code": code,
                        "field": f"comparison_rule.{sub['sub_id']}",
                        "change": "moved to Logical_Rules",
                        "reason": spec["reason"],
                    }
                )
                continue
            kept.append(sub)
        if not kept:
            raise BuildError(f"{code}: every sub-check was moved")
        rule["sub_checks"] = kept
    low = rules_src["semantic_low_confidence"]
    for r in _atomic_rules(rule):
        key = _rule_key(code, r)
        if r["rule_type"] == "INTERNAL_CONSISTENCY":
            raise BuildError(f"{key}: INTERNAL_CONSISTENCY must not stay in comparison_rule (90 C-53)")
        if r.get("low_confidence_status") == "SUSPICION":
            r["low_confidence_status"] = low["low_confidence_status"]
            r["low_confidence_basis"] = low["low_confidence_basis"]
            changes.append(
                {
                    "code": code,
                    "field": f"comparison_rule.{key}.low_confidence_status",
                    "change": "SUSPICION → NOT_COMPARABLE (LOW_CONFIDENCE_SEMANTIC)",
                    "reason": low["reason"],
                }
            )
        if r.get("on_trigger") == "SUSPICION":
            raise BuildError(f"{key}: on_trigger SUSPICION is not allowed in comparison_rule (90 C-53)")
        if r.get("on_trigger_fallback") == "SUSPICION":
            # 90 C-53: without geometry the rule abstains (NOT_COMPARABLE); only B07 hypotheses emit SUSPICION.
            del r["on_trigger_fallback"]
            if "GEOMETRY_NOT_EXTRACTED" not in r.setdefault("abstain_if", []):
                r["abstain_if"].append("GEOMETRY_NOT_EXTRACTED")
            changes.append(
                {
                    "code": code,
                    "field": f"comparison_rule.{key}.on_trigger_fallback",
                    "change": "SUSPICION removed; abstain GEOMETRY_NOT_EXTRACTED",
                    "reason": low["reason"],
                }
            )
        sd = rules_src["set_diff_overrides"].get(key)
        if sd:
            if r["rule_type"] != "SET_DIFF":
                raise BuildError(f"{key}: set_diff_overrides on a {r['rule_type']} rule")
            for fld in ("detect", "context_detect", "element_key", "compare_attributes", "title", "note"):
                if fld in sd:
                    r[fld] = sd[fld]
            changes.append(
                {
                    "code": code,
                    "field": f"comparison_rule.{key}",
                    "change": f"detect={sd['detect']} context_detect={sd.get('context_detect', [])}",
                    "reason": sd["reason"],
                }
            )
        patch = rules_src["sub_check_patches"].get(key)
        if patch:
            for fld in ("title", "note"):
                if fld in patch:
                    r[fld] = patch[fld]
            changes.append(
                {
                    "code": code,
                    "field": f"comparison_rule.{key}",
                    "change": "title/note",
                    "reason": patch["reason"],
                }
            )
        override = rules_src["direction_overrides"].get(key)
        r["direction"] = override["direction"] if override else _derive_direction(r)
        if override:
            changes.append(
                {
                    "code": code,
                    "field": f"comparison_rule.{key}.direction",
                    "change": override["direction"],
                    "reason": override["reason"],
                }
            )
        r["candidate_policy"] = _derive_candidate_policy(r)
        if r.get("on_trigger") != "CANDIDATE" or r.get("on_pass") != "NEGATIVE_VERIFIED":
            raise BuildError(f"{key}: unexpected on_trigger/on_pass {r.get('on_trigger')}/{r.get('on_pass')}")
    for r in (rule, *(rule.get("sub_checks") or [])):
        for fld in ("note", "title"):
            text = r.get(fld) or ""
            if "SUSPICION" in text and "90 C-53" not in text:
                raise BuildError(f"{code}: {fld} still routes to SUSPICION (90 C-53): {text!r}")
    return rule, moved


# ─────────────────────────────────────────────── Texts ──────────────────────────────────────────────────────────────


def deviation_verbs(rec: dict[str, Any], overrides: dict[str, str]) -> dict[str, str]:
    name = rec["parameter_name"].lower()
    unit = (rec["unit"] or "").lower()

    def decrease() -> str:
        if "ширин" in name:
            return "Сужение на {delta}"
        if "сечени" in name and "кабел" in name:
            return "Занижение сечения"
        if "толщин" in name:
            return "Уменьшение толщины на {delta}"
        if "диаметр" in name:
            return "Уменьшение диаметра на {delta}"
        if "площад" in name or unit.startswith("м²"):
            return "Уменьшение на {delta_pct}"
        if "количеств" in name or unit.startswith("шт"):
            return "Сокращение на {delta}"
        return "Снижение на {delta}"

    def downgrade() -> str:
        if "огнестойкост" in name and ("предел" in name or "ei" in name):
            return "Снижение предела"
        if "категори" in name:
            return "Снижение категории"
        return "Понижение класса"

    verbs: dict[str, str] = {}
    for r in _atomic_rules(rec["comparison_rule"]):
        rt, d = r["rule_type"], r["direction"]
        if rt == "PAIRWISE_DELTA":
            if r.get("violation_type") == "COUNT_DECREASE":
                verbs.setdefault("COUNT_CHANGED", "Сокращение на {delta}")
            if d in ("DECREASE", "ANY"):
                verbs.setdefault("VALUE_DECREASED", decrease())
            if d in ("INCREASE", "ANY"):
                verbs.setdefault("VALUE_INCREASED", "Превышение {delta_pct}")
            if d == "ANY":
                verbs.setdefault("VALUE_CHANGED", "Расхождение {delta_pct}")
        elif rt == "ORDINAL_COMPARE":
            verbs.setdefault("CLASS_DOWNGRADED", downgrade())
        elif rt == "NORMATIVE_BOUND":
            if d in ("DECREASE", "ANY"):
                verbs.setdefault("THRESHOLD_BELOW_MIN", "Ниже нормы: {actual} при норме не менее {norm}")
            if d in ("INCREASE", "ANY"):
                verbs.setdefault("THRESHOLD_ABOVE_MAX", "Выше нормы: {actual} при норме не более {norm}")
        elif rt == "PRESENCE":
            verbs.setdefault("ELEMENT_MISSING", "Полное отсутствие")
        elif rt == "EXTERNAL_STATUS":
            verbs.setdefault("UNDOCUMENTED_WORK", "Нет подтверждения во внешней системе")
        elif rt == "SET_DIFF":
            if "ADDED" in r.get("detect", []):
                verbs.setdefault("ELEMENT_ADDED", "Не предусмотрено: {actual}")
            if "MISSING" in r.get("detect", []):
                verbs.setdefault("ELEMENT_MISSING", "Отсутствуют {missing}")
            if "CHANGED" in r.get("detect", []):
                verbs.setdefault("CONFIGURATION_CHANGED", "Изменена конфигурация")
            if r.get("violation_type") == "COUNT_DECREASE":
                verbs.setdefault("COUNT_CHANGED", "Сокращение на {delta}")
        elif rt == "ENUM_CHANGE":
            verbs.setdefault("MATERIAL_SUBSTITUTED", "Замена: {actual} вместо {expected}")
        elif rt == "LAYER_STACK":
            verbs.setdefault("LAYER_REMOVED", "Исключение слоя")
            verbs.setdefault("LAYER_CHANGED", "Изменение состава слоёв")
            verbs.setdefault("VALUE_DECREASED", "Уменьшение толщины слоя на {delta}")
        elif rt == "TOLERANCE_CHECK":
            verbs.setdefault("TOLERANCE_EXCEEDED", "Отклонение {delta} сверх допуска")
        elif rt == "GEOMETRY_OFFSET":
            verbs.setdefault("POSITION_SHIFTED", "Смещение на {delta}")
        elif rt in ("GEOMETRY_CONTAINMENT", "SEMANTIC_DIFF"):
            verbs.setdefault("CONFIGURATION_CHANGED", "Изменено проектное решение")
        elif rt == "RATIO_BOUND":
            verbs.setdefault("THRESHOLD_BELOW_MIN", "Доля ниже нормы: {actual}")
    verbs.update(overrides or {})
    for key in verbs:
        if key not in DiscrepancyType.__members__:
            raise BuildError(f"{rec['code']}: deviation key {key} is not a DiscrepancyType")
    return dict(sorted(verbs.items()))


# ─────────────────────────────────────────────── Params ─────────────────────────────────────────────────────────────


def _references(
    m: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str | None], str | None]:
    structured = {short: list(m[field]) for short, field in REF_KEYS.items()}
    texts = {field: m["references_text"].get(field) for field in REF_KEYS.values()}
    confs = [r["confidence"] for refs in structured.values() for r in refs]
    lowest = min(confs, key=lambda c: CONF_ORDER[c]) if confs else None
    return structured, texts, lowest


def _examples(spec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    pos = []
    for ex in spec.get("pos", []):
        item: dict[str, Any] = {"text": ex["text"]}
        if ex.get("discipline"):
            item["discipline"] = ex["discipline"]
        if "v" in ex:
            item["value"] = ex["v"]
        if ex.get("groups"):
            item["groups"] = dict(ex["groups"])
        pos.append(item)
    neg = []
    for ex in spec.get("neg", []):
        ex = ex if isinstance(ex, dict) else {"text": ex}
        item = {"text": ex["text"]}
        if ex.get("discipline"):
            item["discipline"] = ex["discipline"]
        neg.append(item)
    if not pos or not neg:
        raise BuildError("every parameter needs at least one positive and one negative regex example")
    return {"positive": pos, "negative": neg}


def build_params(
    catalog: list[CatalogRow], matrix: list[dict[str, Any]], srcs: dict[str, Any]
) -> dict[str, Any]:
    regexes, texts, rules_src = srcs["regexes"], srcs["texts"], srcs["rules"]
    enums = load_enums()
    crit_by_string = {
        v.attrs["catalog_string"]: v
        for v in enums["CriticalityLevel"].values
        if v.attrs.get("catalog_string")
    }
    by_id = {m["id"]: m for m in matrix}
    gates = regexes["gates"]
    gate_ids = {g["id"] for g in gates}
    hedge_groups = rules_src["hedge_groups"]
    hedge_of: dict[str, list[str]] = {}
    for g in hedge_groups:
        for c in g["codes"]:
            if c in hedge_of:
                raise BuildError(f"{c} is in two hedge groups")
            hedge_of[c] = list(g["codes"])
    changes: list[dict[str, Any]] = [
        {
            "code": "*",
            "field": "comparison_rule.*.sub_id",
            "change": "M-xxx.s → <catalog code>.s",
            "reason": "каноничен код каталога (97 §2.9)",
        },
        {
            "code": "*",
            "field": "comparison_rule.*.direction/candidate_policy",
            "change": "задаются для каждого атомарного правила",
            "reason": "направленные триггеры (97 §2.10), candidate_policy (90 C-56)",
        },
        {
            "code": "*",
            "field": "risk_level_default",
            "change": "высокий/средний → HIGH/MEDIUM",
            "reason": "enums.RiskLevel",
        },
        {"code": "*", "field": "linked_params", "change": "M-xxx → коды каталога", "reason": "97 §2.9"},
    ]
    moved_all: list[dict[str, Any]] = []
    params = []
    for row in sorted(catalog, key=lambda r: r.parameter_id):
        pid, code = row.parameter_id, row.parameter_code
        m = by_id[pid]
        if code != codes.canonical_code(pid):
            raise BuildError(f"catalog code {code} disagrees with id {pid}")
        for cat_field, m_field in (
            ("parameter_name", "parameter_name"),
            ("unit", "unit"),
            ("pd_section", "section_matrix_label"),
            ("source_pd", "source_pd"),
            ("source_rd", "source_rd"),
            ("source_id", "source_id"),
            ("trigger", "trigger_logic"),
        ):
            if getattr(row, cat_field) != m[m_field]:
                raise BuildError(
                    f"{code}: catalog {cat_field} differs from matrix_enriched (catalog wins; review)"
                )
        prefix = codes.prefix_for_id(pid)
        if m["section"] != prefix.cyrillic or row.pd_section != prefix.section:
            raise BuildError(f"{code}: section mismatch {m['section']} / {row.pd_section}")
        level = crit_by_string[row.criticality]
        if level.attrs["review_priority"] != m["review_priority"]:
            raise BuildError(
                f"{code}: review_priority {m['review_priority']} disagrees with criticality {row.criticality}"
            )
        rx = regexes["params"][code]
        tx = texts["params"][code]
        rule, moved = patch_rule(code, m["comparison_rule"], rules_src, changes)
        moved_all.extend(moved)
        atomic = [r["sub_id"] for r in rule["sub_checks"]] if rule["rule_type"] == "COMPOSITE" else []
        structured, ref_texts, lowest = _references(m)
        anchors = list(m["semantic_anchors"])
        removal = rules_src["anchor_removals"].get(code)
        if removal:
            missing = [a for a in removal["remove"] if a not in anchors]
            if missing:
                raise BuildError(f"{code}: anchors to remove not found: {missing}")
            anchors = [a for a in anchors if a not in removal["remove"]]
            changes.append(
                {
                    "code": code,
                    "field": "semantic_anchors",
                    "change": f"removed {removal['remove']}",
                    "reason": removal["reason"],
                }
            )
        notes = m["notes"] or ""
        extra = rules_src["notes_append"].get(code)
        if extra:
            notes = f"{notes} {extra}".strip()
        gates_used = list(rx.get("gates", []))
        for g in gates_used:
            if g not in gate_ids:
                raise BuildError(f"{code}: unknown gate {g}")
        regex_pattern, regex_aux = rx["regex"], list(rx.get("aux", []))
        if len(regex_pattern) > MAX_REGEX_PATTERN_CHARS:
            raise BuildError(
                f"{code}: regex_pattern longer than {MAX_REGEX_PATTERN_CHARS} (ТЗ §8.1 VARCHAR(255))"
            )
        for i, pat in enumerate([regex_pattern, *regex_aux]):
            if len(pat) > MAX_AUX_PATTERN_CHARS:
                raise BuildError(f"{code}#{i}: pattern longer than {MAX_AUX_PATTERN_CHARS}")
            problems = regex_safety_problems(pat)
            if problems:
                raise BuildError(f"{code}#{i}: unsafe regex: {problems}")
        if regex_pattern != m["regex_pattern"] or regex_aux != list(m["regex_aux"]):
            reason = rules_src["regex_change_reasons"].get(code, GENERIC_REGEX_REASON)
            changes.append(
                {"code": code, "field": "regex_pattern/regex_aux", "change": "rewritten", "reason": reason}
            )
        text_sources = {  # work_type / recommendation_template: set from the templates (build_templates)
            "short_name": "APPENDIX2" if tx.get("a2") else "AG03_DRAFT",
            "work_type": "AG03_DRAFT",
            "recommendation_template": "AG03_DRAFT",
        }
        linked = [_canonical_ref(c) for c in m["linked_params"]]
        rec: dict[str, Any] = {
            "param_id": pid,
            "code": code,
            "alias_codes": codes.alias_codes(pid),
            "matrix_row": row.matrix_row,
            "mapping_status": str(row.mapping_status),
            "section": prefix.cyrillic,
            "pd_section": row.pd_section,
            "matrix_section_no": m["matrix_section_no"],
            "pp87_section_no": m["pp87_section_no"],
            "parameter_name": row.parameter_name,
            "short_name": tx["short_name"],
            "name_variants": list(tx.get("name_variants", [])),
            "unit": row.unit,
            "unit_canonical": m["unit_canonical"],
            "data_type": m["data_type"],
            "source_pd": row.source_pd,
            "source_rd": row.source_rd,
            "source_id": row.source_id,
            "source_docs": m["source_docs"],
            "trigger_logic": row.trigger,
            "criticality": row.criticality,
            "criticality_level": level.code,
            "review_priority": m["review_priority"],
            "review_priority_matrix_text": m["review_priority_matrix_text"],
            "risk_level_default": RISK[m["risk_level_default"]],
            "min_value": m["min_value"],
            "max_value": m["max_value"],
            "threshold_source": m["threshold_source"],
            "threshold_note": m["threshold_note"],
            "matrix_trigger_value": m.get("matrix_trigger_value"),
            "comparison_rule": rule,
            "atomic_sub_checks": atomic,
            "stages_required": m["stages_required"],
            "applicability_conditions": m["applicability_conditions"],
            "element_key": m["element_key"],
            "extraction_method": m["extraction_method"],
            "extraction_methods_all": m["extraction_methods_all"],
            "feasibility_tier": m["feasibility_tier"],
            "feasibility_note": m["feasibility_note"],
            "regex_pattern": regex_pattern,
            "regex_aux": regex_aux,
            "regex_gates": gates_used,
            "regex_flags": REGEX_FLAGS_TEXT,
            "regex_examples": _examples(rx),
            "semantic_anchors": anchors,
            **ref_texts,
            "references": structured,
            "reference_confidence_min": lowest,
            "linked_params": linked,
            "hedge_group": hedge_of.get(code, []),
            "element_nouns": list(tx["nouns"]),
            "work_type": "",  # from recommendation_templates (build_templates.derive_param_texts)
            "deviation_verb": {},  # idem
            "recommendation_template": "",  # idem
            "text_sources": text_sources,
            "demo_priority": m["demo_priority"],
            "pilot_evidence": m["pilot_evidence"],
            "is_active": m["is_active"],
            "notes": notes,
        }
        params.append(rec)
    if len(params) != 132:
        raise BuildError(f"expected 132 parameters, built {len(params)}")
    expected_moved = {m["sub_id"] for m in rules_src["moved_to_logical_rules"]}
    if {m["sub_id"] for m in moved_all} != expected_moved:
        raise BuildError("moved_to_logical_rules does not match the INTERNAL_CONSISTENCY sub-checks found")
    for code in (*regexes["params"], *texts["params"]):
        if not codes.is_canonical_code(code):
            raise BuildError(f"source key {code} is not a catalog code")
    for key in (
        *rules_src["direction_overrides"],
        *rules_src["set_diff_overrides"],
        *rules_src["sub_check_patches"],
    ):
        base = key.split(".")[0]
        spec = next(p for p in params if p["code"] == base)
        ids = spec["atomic_sub_checks"] or [spec["code"]]
        if key not in ids:
            raise BuildError(f"rules.yaml key {key} does not name a sub-check of {base}")
    return {
        "seed": "params",
        "schema_version": SCHEMA_VERSION,
        "matrix_version": MATRIX_VERSION,
        "content_sha256": "",  # finalize_params
        "counts": {},  # finalize_params
        "review": {},  # finalize_params
        "sources": srcs["_sources"],
        "seed_changes": changes,
        "params": params,
        "context_gates": gates,
        "hedge_groups": hedge_groups,
        "moved_to_logical_rules": moved_all,
    }


def finalize_params(doc: dict[str, Any], extra_sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts, review block and content hash — after the norms merge and the template-derived texts."""
    params = doc["params"]
    doc["sources"] = [*doc["sources"], *extra_sources]
    content = {k: doc[k] for k in ("params", "context_gates", "hedge_groups", "moved_to_logical_rules")}
    counts = Counter(p["criticality_level"] for p in params)
    refs = [r for p in params for bucket in p["references"].values() for r in bucket]
    doc["content_sha256"] = sha256_json(content)
    doc["counts"] = {
        "params": len(params),
        "criticality": dict(sorted(counts.items())),
        "atomic_rules": sum(len(p["atomic_sub_checks"]) or 1 for p in params),
        "regex_patterns": sum(1 + len(p["regex_aux"]) for p in params),
        "regex_examples": sum(
            len(p["regex_examples"]["positive"]) + len(p["regex_examples"]["negative"]) for p in params
        ),
        "short_names_from_appendix2": sum(p["text_sources"]["short_name"] == "APPENDIX2" for p in params),
        "references": len(refs),
        "references_by_status": dict(sorted(Counter(r["status"] for r in refs).items())),
        "references_by_confidence": dict(sorted(Counter(r["confidence"] for r in refs).items())),
        "references_not_found": sum(len(p["norm_verification"]["references_not_found"]) for p in params),
        "threshold_status": dict(
            sorted(Counter(p["norm_verification"]["threshold"]["status"] for p in params).items())
        ),
        "threshold_decisions": sum(bool(p["norm_verification"]["threshold_decision"]) for p in params),
        "params_with_edition_rules": sum(bool(p["norm_verification"]["edition_rules"]) for p in params),
    }
    doc["review"] = {
        "status": "DRAFT (AG-03)",
        "fields_needing_expert_review": [
            "short_name (AG03_DRAFT)",
            "work_type",
            "recommendation_template",
            "deviation_verb",
            "change_matrix_map routes with basis ANALOGY",
        ],
        "note": (
            "Тексты с text_sources = APPENDIX2 воспроизводят Приложение 2; остальные — черновики (97 Q3). "
            "Нормативные ссылки и пороги верифицированы по действующим редакциям на 27.09.2026 "
            "(norm_verification); рекомендации — recommendation_templates.json."
        ),
    }
    return doc


# ─────────────────────────────────────────────── Change map and FREE topics ─────────────────────────────────────────


def build_change_map(
    params_doc: dict[str, Any],
    cmap_src: dict[str, Any],
    free_src: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    by_code = {p["code"]: p for p in params_doc["params"]}
    to_result = enum_mappings()["discrepancy_to_comparison_result"]
    topics = {t["topic"] for t in free_src["topics"]}
    seen_families: set[str] = set()
    families = []
    for fam in cmap_src["families"]:
        name = fam["family"]
        if name in seen_families:
            raise BuildError(f"duplicate family {name}")
        seen_families.add(name)
        if fam["topic"] not in topics:
            raise BuildError(f"{name}: unknown topic {fam['topic']}")
        keys: set[str] = set()
        routes = []
        for r in fam["routes"]:
            for dt in r["discrepancy_types"]:
                if dt not in DiscrepancyType.__members__:
                    raise BuildError(f"{name}: unknown discrepancy type {dt}")
                if dt in keys:
                    raise BuildError(f"{name}: two routes for {dt}")
                keys.add(dt)
                if to_result[dt] != r["comparison_result"]:
                    raise BuildError(
                        f"{name}: {dt} maps to {to_result[dt]}, route says {r['comparison_result']}"
                    )
            code = r.get("parameter_code")
            status = r.get("parameter_mapping_status")
            if code and code.startswith("FREE-"):
                if code.removeprefix("FREE-") not in topics or status != "MATRIX_GAP_CONFIRMED":
                    raise BuildError(
                        f"{name}: FREE route {code} must use a known topic and MATRIX_GAP_CONFIRMED"
                    )
            elif code:
                if code not in by_code:
                    raise BuildError(f"{name}: unknown code {code}")
                if status not in ("SOURCE_MATRIX", "PROVISIONAL_DOMAIN_MAPPING"):
                    raise BuildError(f"{name}: matrix route {code} with status {status}")
                spec = by_code[code]
                sub = r.get("sub_check")
                if sub and sub not in (spec["atomic_sub_checks"] or [code]):
                    raise BuildError(f"{name}: sub_check {sub} is not a sub-check of {code}")
                allowed = set(spec["hedge_group"]) - {code}
                if not set(r.get("hedge_codes", [])) <= allowed:
                    raise BuildError(
                        f"{name}: hedge_codes {r.get('hedge_codes')} not in the hedge group of {code}"
                    )
            elif r["emit"]:
                raise BuildError(f"{name}: emitting route without a parameter code")
            if r["emit"] and not r.get("value_templates"):
                raise BuildError(f"{name}: emitting route without value_templates")
            if not r["emit"] and not r.get("reason"):
                raise BuildError(f"{name}: non-emitting route needs a reason")
            route = {
                "discrepancy_types": list(r["discrepancy_types"]),
                "comparison_result": r["comparison_result"],
                "parameter_code": code,
                "parameter_mapping_status": status,
                "emit": bool(r["emit"]),
                "sub_check": r.get("sub_check"),
                "hedge_codes": list(r.get("hedge_codes", [])),
                "basis": r["basis"],
                "reason": r.get("reason"),
                "value_templates": r.get("value_templates"),
            }
            routes.append(route)
        families.append(
            {
                "family": name,
                "label_ru": fam["label_ru"],
                "section": fam["section"],
                "disciplines": list(fam["disciplines"]),
                "topic": fam["topic"],
                "tag_patterns": list(fam.get("tag_patterns", [])),
                "anchors": list(fam.get("anchors", [])),
                "routes": routes,
            }
        )
    for fam in families:
        for pat in fam["tag_patterns"]:
            problems = regex_safety_problems(pat)
            if problems:
                raise BuildError(f"{fam['family']}: unsafe tag pattern {pat}: {problems}")
    all_routes = [r for f in families for r in f["routes"]]
    return {
        "seed": "change_matrix_map",
        "schema_version": SCHEMA_VERSION,
        "matrix_version": MATRIX_VERSION,
        "policy": cmap_src["policy"],
        "free_search": enum_mappings()["free_search"],
        "counts": {
            "families": len(families),
            "routes": len(all_routes),
            "emitting_routes": sum(r["emit"] for r in all_routes),
            "free_routes": sum(
                bool(r["parameter_code"] and r["parameter_code"].startswith("FREE-")) for r in all_routes
            ),
            "by_mapping_status": dict(
                sorted(Counter(r["parameter_mapping_status"] or "NONE" for r in all_routes).items())
            ),
            "by_basis": dict(sorted(Counter(r["basis"].split(":")[0] for r in all_routes).items())),
        },
        "sources": sources,
        "element_families": families,
    }


def build_free_topics(
    cmap: dict[str, Any], free_src: dict[str, Any], sources: list[dict[str, Any]]
) -> dict[str, Any]:
    enum = load_enums()["FreeTopic"]
    src_topics = [t["topic"] for t in free_src["topics"]]
    if src_topics != list(enum.codes):
        raise BuildError(
            f"free_topics.yaml topics {src_topics} differ from enums.FreeTopic {list(enum.codes)}"
        )
    labels = {v.code: v.label_ru for v in enum.values}
    families_by_topic: dict[str, list[str]] = {}
    for fam in cmap["element_families"]:
        for r in fam["routes"]:
            code = r["parameter_code"]
            if code and code.startswith("FREE-"):
                families_by_topic.setdefault(code.removeprefix("FREE-"), [])
                if fam["family"] not in families_by_topic[code.removeprefix("FREE-")]:
                    families_by_topic[code.removeprefix("FREE-")].append(fam["family"])
    topics = []
    for t in free_src["topics"]:
        if t["label_ru"] != labels[t["topic"]]:
            raise BuildError(f"{t['topic']}: label_ru differs from enums.FreeTopic")
        topics.append(
            {
                "topic": t["topic"],
                "label_ru": t["label_ru"],
                "code_example": codes.free_code(t["topic"], 1),
                "disciplines": list(t["disciplines"]),
                "sections": list(t["sections"]),
                "description": t["description"],
                "change_map_families": families_by_topic.get(t["topic"], []),
            }
        )
    fs = enum_mappings()["free_search"]
    return {
        "seed": "free_topics",
        "schema_version": SCHEMA_VERSION,
        "matrix_version": MATRIX_VERSION,
        "numbering": free_src["numbering"],
        "export_policy": free_src["export_policy"],
        "criticality": fs["criticality_string"],
        "criticality_level": fs["criticality_level"],
        "protocol_status": fs["protocol_status"],
        "sources": sources,
        "topics": topics,
    }


# ─────────────────────────────────────────────── Main ───────────────────────────────────────────────────────────────


def _dump(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def build_all(catalog_path: Path) -> dict[str, str]:
    root = repo_root()
    matrix_path = root / "docs" / "analysis" / "matrix_enriched.json"
    catalog = []
    with open(catalog_path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                catalog.append(CatalogRow.model_validate(json.loads(line)))
    with open(matrix_path, encoding="utf-8") as fh:
        matrix = json.load(fh)
    package_root = catalog_path.parent.parent
    appendix2 = package_root / "ТЗ_И_ПРИЛОЖЕНИЯ" / "ПРИЛОЖЕНИЕ 2. ПРИМЕР ПРОТОКОЛА СРАВНЕНИЯ.docx"
    sources = [
        {"path": f"{package_root.name}/data/{catalog_path.name}", "sha256": sha256_file(catalog_path)},
        {"path": "docs/analysis/matrix_enriched.json", "sha256": sha256_file(matrix_path)},
    ]
    if appendix2.is_file():
        sources.append(
            {
                "path": f"{package_root.name}/ТЗ_И_ПРИЛОЖЕНИЯ/{appendix2.name}",
                "sha256": sha256_file(appendix2),
            }
        )
    srcs: dict[str, Any] = {}
    for key, name in (("regexes", "regexes.yaml"), ("texts", "texts.yaml"), ("rules", "rules.yaml")):
        srcs[key] = _load_yaml(name)
        sources.append({"path": f"packages/contracts/seed/src/{name}", "sha256": sha256_file(SRC / name)})
    srcs["_sources"] = sources
    cmap_src, free_src = _load_yaml("change_matrix_map.yaml"), _load_yaml("free_topics.yaml")
    map_sources = [
        {
            "path": "packages/contracts/seed/src/change_matrix_map.yaml",
            "sha256": sha256_file(SRC / "change_matrix_map.yaml"),
        },
        {
            "path": "packages/contracts/seed/src/free_topics.yaml",
            "sha256": sha256_file(SRC / "free_topics.yaml"),
        },
    ]
    params_doc = build_params(catalog, matrix, srcs)
    # M1: web-verified norms, recommendation templates (Раздел 7) and value templates (build_templates.py).
    inputs = bt.load_inputs()
    try:
        bt.apply_norms(params_doc, inputs, params_doc["seed_changes"])
        problems = bt.norm_number_problems(params_doc, inputs)
        if problems:
            raise BuildError("; ".join(problems))
        templates_doc = bt.build_recommendation_templates(params_doc, inputs, MATRIX_VERSION)
        dt_keys = {p["code"]: list(deviation_verbs(p, {})) for p in params_doc["params"]}
        bt.derive_param_texts(params_doc, templates_doc, dt_keys, inputs["cfg"])
    except bt.TemplateBuildError as exc:
        raise BuildError(str(exc)) from exc
    finalize_params(params_doc, inputs["sources"])
    cmap = build_change_map(params_doc, cmap_src, free_src, map_sources)
    free = build_free_topics(cmap, free_src, map_sources)
    try:
        values_doc = bt.build_value_templates(inputs, cmap, templates_doc, MATRIX_VERSION)
    except bt.TemplateBuildError as exc:
        raise BuildError(str(exc)) from exc
    return {
        "params.json": _dump(params_doc),
        "change_matrix_map.json": _dump(cmap),
        "free_topics.json": _dump(free),
        "recommendation_templates.json": _dump(templates_doc),
        "value_templates.json": _dump(values_doc),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build packages/contracts/seed/*.json (AG-03)")
    parser.add_argument(
        "--catalog", type=Path, help="parameter_catalog_132.jsonl (default: from INSPECTOR_DATA_ROOT)"
    )
    parser.add_argument(
        "--check", action="store_true", help="do not write; exit 1 when a committed file differs"
    )
    args = parser.parse_args(argv)
    catalog_path = args.catalog or Settings().paths.catalog_path
    if not catalog_path.is_file():
        print(f"каталог параметров не найден: {catalog_path}", file=sys.stderr)
        return 2
    try:
        outputs = build_all(catalog_path)
    except BuildError as exc:
        print(f"ошибка сборки сида: {exc}", file=sys.stderr)
        return 1
    drift = []
    for name, text in outputs.items():
        path = SEED / name
        if args.check:
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != text:
                drift.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if args.check:
        if drift:
            print(f"сид устарел, пересоберите: {', '.join(drift)}", file=sys.stderr)
            return 1
        print("сид актуален")
        return 0
    doc = json.loads(outputs["params.json"])
    print(
        f"записано: {', '.join(outputs)}; параметров {doc['counts']['params']}, content_sha256 {doc['content_sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
