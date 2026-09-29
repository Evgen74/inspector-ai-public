"""Seed build, M1 part — owner AG-03: web-verified norms, recommendation templates, value templates.

Called by build_seed.py (``build_all``). Inputs (read-only, sha256 recorded in ``sources``):
- src/norms/*.json — verbatim copies of docs/analysis/norms_staging (web verification, 2026-09-27);
- src/norms.yaml — AG-03 curation: edition registry, regime changes, threshold decisions, parameter patches,
  vocabularies of the templates;
- src/value_templates.yaml — submission-style value formats and templates.

Outputs: the norms merged into params.json (references, norm_verification, thresholds), recommendation_templates.json
and value_templates.json. Every change to a parameter is logged in params.json ``seed_changes``.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from inspector_common.contracts.loader import enum_mappings, load_enums
from inspector_common.hashing import sha256_file, sha256_json
from inspector_common.params import render_text, unverified_numbers

SRC = Path(__file__).resolve().parent
NORM_FILES = ("norms/norms_pz_spzu_ar_kr_pos_pod.json", "norms/norms_ios_oos_ppm_odi_zu_sm.json")
TEMPLATES_FILE = "norms/recommendation_templates.staging.json"
NORMS_YAML = "norms.yaml"
VALUES_YAML = "value_templates.yaml"
CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
EMPTY = ("", "—", "-", "–")
REF_FIELDS = ("designation", "clause", "edition", "condition", "value", "quote")


class TemplateBuildError(RuntimeError):
    pass


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return None if text in EMPTY else text


def load_inputs() -> dict[str, Any]:
    norms: dict[str, dict[str, Any]] = {}
    headers = []
    for name in NORM_FILES:
        with open(SRC / name, encoding="utf-8") as fh:
            doc = json.load(fh)
        headers.append({k: v for k, v in doc.items() if k != "params"})
        for rec in doc["params"]:
            if rec["catalog_code"] in norms:
                raise TemplateBuildError(f"norms: {rec['catalog_code']} verified twice")
            norms[rec["catalog_code"]] = rec
    with open(SRC / TEMPLATES_FILE, encoding="utf-8") as fh:
        staging = json.load(fh)
    with open(SRC / NORMS_YAML, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    with open(SRC / VALUES_YAML, encoding="utf-8") as fh:
        values = yaml.safe_load(fh)
    sources = [
        {"path": f"packages/contracts/seed/src/{name}", "sha256": sha256_file(SRC / name)}
        for name in (*NORM_FILES, TEMPLATES_FILE, NORMS_YAML)
    ]
    value_sources = [
        {"path": f"packages/contracts/seed/src/{VALUES_YAML}", "sha256": sha256_file(SRC / VALUES_YAML)}
    ]
    return {
        "norms": norms,
        "norm_headers": headers,
        "staging": staging,
        "cfg": cfg,
        "values": values,
        "sources": sources,
        "value_sources": value_sources,
    }


# ─────────────────────────────────────────────── References ─────────────────────────────────────────────────────────

_CLAUSE_TOKENS = re.compile(
    r"(?:Приложение|приложение|прил\.|разд\.|раздел|табл\.|пп?\.|ст\.|ч\.|гл\.)\s*[\dА-ЯA-Z][\w.()]*"
    r"(?:\s*[–-]\s*[\dА-ЯA-Z][\w.]*)?"
)
_FZ = re.compile(
    r"^(?:Федеральный закон|ФЗ\b|\d+-ФЗ|Градостроительный кодекс|ГрК|Воздушный кодекс|Земельный кодекс)"
)


def ref_bucket(designation: str) -> str:
    """sp / gost / fz / other — the four ТЗ §8.1 reference columns."""
    d = designation.strip()
    if d.startswith(("СП ", "СНиП")):
        return "sp"
    if d.startswith("ГОСТ"):
        return "gost"
    if _FZ.match(d) or re.match(r"^\d+-ФЗ", d):
        return "fz"
    return "other"


def short_designation(designation: str) -> str:
    """«СП 60.13330.2020 «СНиП 41-01-2003 …»» → «СП 60.13330.2020»; multi-document designations keep every part."""
    parts = []
    for part in designation.split("; "):
        part = part.split(" «")[0].split(" (")[0].split(" — ")[0]
        if part.startswith(("СП ", "ГОСТ")):
            part = part.split(",")[0]
        parts.append(part.strip().rstrip(",;"))
    return "; ".join(dict.fromkeys(p for p in parts if p))


_WHOLE_DOCUMENT = ("документ в целом", "в целом")


def clause_tokens(clause: str | None) -> list[str]:
    """Formal clause references of a clause text: «п. 4.3.3», «табл. 5.12», «разд. 6», «ст. 88»."""
    if not clause or clause.strip().lower() in _WHOLE_DOCUMENT:
        return []
    found = list(dict.fromkeys(m.group(0).rstrip(".,;") for m in _CLAUSE_TOKENS.finditer(clause)))
    if found:
        return found
    return [clause] if len(clause) <= 60 else []


def display_ref(designation: str, clause: str | None) -> str:
    """ТЗ §8.1 style «СП 1.13130.2020, п. 4.2.1»: short designation plus at most four clause references."""
    short = short_designation(designation)
    tokens = [t for t in clause_tokens(clause) if t not in short][:4]
    return f"{short}, {', '.join(tokens)}" if tokens else short


def _reference_item(raw: dict[str, Any], status: str, *, added: bool = False) -> dict[str, Any]:
    designation = _clean(raw.get("designation") if added else raw.get("correct_designation")) or _clean(
        raw.get("cited")
    )
    if not designation:
        raise TemplateBuildError(f"reference without a designation: {raw}")
    clause = _clean(raw.get("clause"))
    item: dict[str, Any] = {
        "ref": display_ref(designation, clause),
        "confidence": raw["confidence"],
        "status": status,
        "designation": designation,
        "clause": clause,
        "edition": _clean(raw.get("edition")),
        "matrix_cited": None if added else _clean(raw.get("cited")),
        "condition": _clean(raw.get("condition")),
        "value": _clean(raw.get("value")),
        "url": _clean(raw.get("url")),
        "quote": _clean(raw.get("quote")),
    }
    if added and _clean(raw.get("why")):
        item["note"] = _clean(raw.get("why"))
    return item


def build_references(
    rec: dict[str, Any], cfg: dict[str, Any]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    statuses = cfg["reference_status"]
    refs: dict[str, list[dict[str, Any]]] = {"sp": [], "gost": [], "fz": [], "other": []}
    not_found: list[dict[str, Any]] = []
    for raw in rec["references"]:
        status = raw["status"]
        if status not in statuses:
            raise TemplateBuildError(f"{rec['catalog_code']}: unknown reference status {status}")
        item = _reference_item(raw, status)
        if status == "NOT_FOUND":
            not_found.append(
                {
                    "cited": _clean(raw.get("cited")),
                    "designation": item["designation"],
                    "clause": item["clause"],
                    "confidence": raw["confidence"],
                    "note": item["value"] or item["condition"] or item["quote"],
                }
            )
            continue
        refs[ref_bucket(item["designation"])].append(item)
    for raw in rec.get("additional_references", ()):
        item = _reference_item(raw, "ADDED", added=True)
        refs[ref_bucket(item["designation"])].append(item)
    return refs, not_found


def reference_texts(refs: dict[str, list[dict[str, Any]]]) -> dict[str, str | None]:
    """ТЗ §8.1 text columns sp_reference … other_normative: «СП 1.13130.2020, п. 4.2.1; …»."""
    out = {}
    for short, column in (
        ("sp", "sp_reference"),
        ("gost", "gost_reference"),
        ("fz", "fz_reference"),
        ("other", "other_normative"),
    ):
        items = list(dict.fromkeys(r["ref"] for r in refs[short]))
        out[column] = "; ".join(items) if items else None
    return out


def edition_rules_for(text: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    rules = []
    for doc in cfg["documents"]:
        new, old = doc.get("replaced_by"), doc["designation"]
        if new and (new in text or old in text):
            rules.append(
                {
                    "designation": old,
                    "replaced_by": new,
                    "effective_from": doc["effective_from"],
                    "applies_by": doc["applies_by"],
                }
            )
        elif not new and old in text:
            rules.append(
                {"designation": old, "valid_until": doc["valid_until"], "applies_by": doc["applies_by"]}
            )
    return rules


# ─────────────────────────────────────────────── Params: merge ──────────────────────────────────────────────────────


def _atomic(rule: dict[str, Any]) -> list[dict[str, Any]]:
    return rule["sub_checks"] if rule["rule_type"] == "COMPOSITE" else [rule]


def _sub(rule: dict[str, Any], key: str, code: str) -> dict[str, Any]:
    for r in _atomic(rule):
        if (r.get("sub_id") or code) == key:
            return r
    raise TemplateBuildError(f"{code}: no sub-check {key}")


def apply_norms(params_doc: dict[str, Any], inputs: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    """Merge the verified norms into params.json in place (references, norm_verification, thresholds, patches)."""
    norms, cfg = inputs["norms"], inputs["cfg"]
    thr_map = cfg["threshold_status"]["staging_map"]
    decisions = cfg["threshold_decisions"]
    patches = cfg["param_patches"]
    regimes = cfg["regime_changes"]
    by_code = {p["code"]: p for p in params_doc["params"]}
    if set(norms) != set(by_code):
        raise TemplateBuildError(f"norms cover {len(norms)} parameters, expected the 132 catalog codes")
    for key in (*decisions, *patches):
        if key not in by_code:
            raise TemplateBuildError(f"norms.yaml: unknown parameter {key}")
    changes.append(
        {
            "code": "*",
            "field": "references/sp_reference/gost_reference/fz_reference/other_normative",
            "change": "заменены верифицированными ссылками (статус, редакция, пункт, цитата, уверенность)",
            "reason": f"веб-верификация норм {cfg['checked_at']} (src/norms, norms.yaml)",
        }
    )
    for code, p in by_code.items():
        rec = norms[code]
        if rec["code"] != p["alias_codes"][0] or rec["parameter_name"] != p["parameter_name"]:
            raise TemplateBuildError(f"{code}: norms record {rec['code']} does not match the catalog")
        refs, not_found = build_references(rec, cfg)
        p["references"] = refs
        p.update(reference_texts(refs))
        cited = [r for bucket in refs.values() for r in bucket]
        p["reference_confidence_min"] = (
            min((r["confidence"] for r in cited), key=lambda c: CONF_ORDER[c]) if cited else None
        )
        tv = rec["threshold_verdict"]
        if tv["status"] not in thr_map:
            raise TemplateBuildError(f"{code}: unknown threshold status {tv['status']}")
        text = " ".join(
            str(r.get(k) or "")
            for r in (*rec["references"], *rec.get("additional_references", ()))
            for k in ("cited", "correct_designation", "designation", "edition", "clause")
        )
        p["norm_verification"] = {
            "checked_at": cfg["checked_at"],
            "record": rec["code"],
            "threshold": {
                "status": thr_map[tv["status"]],
                "staging_status": tv["status"],
                "min_value": tv["min_value"],
                "max_value": tv["max_value"],
                "unit": _clean(tv.get("unit")),
                "condition": _clean(tv.get("condition")),
            },
            "notes": _clean(rec.get("notes")),
            "references_not_found": not_found,
            "edition_rules": edition_rules_for(text, cfg),
            "regime_changes": [r["id"] for r in regimes if code in r["params"]],
            "threshold_decision": None,
        }
    for code, dec in decisions.items():
        _apply_threshold_decision(by_code[code], dec, changes)
    for code, patch in patches.items():
        _apply_param_patch(by_code[code], patch, changes)


def _apply_threshold_decision(p: dict[str, Any], dec: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    code = p["code"]
    changed = []
    for fld in ("min_value", "max_value", "threshold_source", "matrix_trigger_value", "threshold_note"):
        if fld in dec and p.get(fld) != dec[fld]:
            changed.append(
                f"{fld}: {p.get(fld)!r} → {dec[fld]!r}" if fld != "threshold_note" else "threshold_note"
            )
            p[fld] = copy.deepcopy(dec[fld])
    for sub_id, conds in (dec.get("conditional") or {}).items():
        r = _sub(p["comparison_rule"], sub_id, code)
        if r["rule_type"] != "NORMATIVE_BOUND":
            raise TemplateBuildError(f"{sub_id}: conditional bounds on a {r['rule_type']} rule")
        existing = r.setdefault("bounds", {}).setdefault("conditional", [])
        for cond in conds:
            if cond not in existing:
                existing.append(copy.deepcopy(cond))
                changed.append(f"{sub_id}.bounds.conditional += {json.dumps(cond, ensure_ascii=False)}")
    for sub_id, note in (dec.get("sub_notes") or {}).items():
        r = _sub(p["comparison_rule"], sub_id, code)
        if r.get("note") != note:
            r["note"] = note
            changed.append(f"{sub_id}.note")
    for sub_id, title in (dec.get("sub_titles") or {}).items():
        r = _sub(p["comparison_rule"], sub_id, code)
        if r.get("title") != title:
            changed.append(f"{sub_id}.title: {r.get('title')!r} → {title!r}")
            r["title"] = title
    p["norm_verification"]["threshold_decision"] = dec["reason"]
    changes.append(
        {
            "code": code,
            "field": "thresholds",
            "change": "; ".join(changed) or "подтверждено",
            "reason": dec["reason"],
        }
    )


def _apply_param_patch(p: dict[str, Any], patch: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    code = p["code"]
    rule = p["comparison_rule"]
    if rule["rule_type"] == "COMPOSITE":
        raise TemplateBuildError(f"{code}: param_patches expect an atomic rule")
    done = []
    if patch.get("external_system"):
        rule["external_system"] = patch["external_system"]
        done.append("comparison_rule.external_system")
    if patch.get("rule_note"):
        rule["note"] = patch["rule_note"]
        done.append("comparison_rule.note")
    for fld in ("threshold_note", "feasibility_note"):
        if patch.get(fld):
            p[fld] = patch[fld]
            done.append(fld)
    for anchor in patch.get("anchors_add", ()):
        if anchor not in p["semantic_anchors"]:
            p["semantic_anchors"].append(anchor)
            done.append(f"semantic_anchors += {anchor}")
    if patch.get("notes_append"):
        p["notes"] = f"{p.get('notes') or ''} {patch['notes_append']}".strip()
        done.append("notes")
    changes.append(
        {"code": code, "field": "; ".join(done), "change": "верификация норм", "reason": patch["reason"]}
    )


# ─────────────────────────────────────────────── Recommendation templates ───────────────────────────────────────────


def _kinds(cfg: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    by_staging = {k["staging_key"]: k["code"] for k in cfg["deviation_kinds"]}
    return by_staging, cfg["deviation_kinds"]


def _kind_key(key: str, by_staging: dict[str, str], where: str) -> str:
    base, sep, elem = key.partition(":")
    if base not in by_staging:
        raise TemplateBuildError(f"{where}: unknown deviation key {key!r}")
    return by_staging[base] + (f":{elem}" if sep else "")


def _delta_format(raw: Any, cfg: dict[str, Any], by_staging: dict[str, str], where: str) -> dict[str, Any]:
    codes = cfg["delta_formats"]
    if isinstance(raw, str):
        return {"default": codes[raw], "by_kind": {}}
    by_kind = {_kind_key(k, by_staging, where): codes[v] for k, v in raw.items() if k != "default"}
    return {"default": codes[raw["default"]], "by_kind": by_kind}


def _norm_refs(
    raw_refs: list[dict[str, Any]], cfg: dict[str, Any], alias_to_code: dict[str, str], where: str
) -> list[dict[str, Any]]:
    out = []
    status_map = cfg["template_ref_status_map"]
    for r in raw_refs:
        src = r["source"]
        m = re.fullmatch(r"norms_staging:(M-\d{3})(?: \((additional_references)\))?", src)
        if not m or m.group(1) not in alias_to_code:
            raise TemplateBuildError(f"{where}: norm ref without a norms record: {src}")
        record = alias_to_code[m.group(1)]
        if r["verification_status"] not in status_map:
            raise TemplateBuildError(f"{where}: unknown verification status {r['verification_status']}")
        out.append(
            {
                "ref": display_ref(r["designation"], _clean(r.get("clause"))),
                "designation": r["designation"],
                "clause": _clean(r.get("clause")),
                "status": status_map[r["verification_status"]],
                "confidence": r["confidence"],
                "matrix_cited": _clean(r.get("matrix_cited")),
                "edition": _clean(r.get("edition")),
                "url": _clean(r.get("url")),
                "record": record,
                "verified_value": _clean(r.get("verified_value")),
                "used_for": _clean(r.get("used_for")),
            }
        )
    return out


def _texts_of(t: dict[str, Any]) -> list[tuple[str, str]]:
    """(field, text) of every renderable text of a built template."""
    out = [
        ("work_type", t["work_type"]),
        ("violation_kind", t["violation_kind"]),
        ("recommendation", t["recommendation"]),
    ]
    for fld in ("violation_kind_variants", "recommendation_variants", "deviation_phrases"):
        out += [(f"{fld}.{k}", v) for k, v in (t.get(fld) or {}).items()]
    for k, v in (t.get("norm_fill") or {}).items():
        if v:
            out.append((f"norm_fill.{k}", v))
    for i, rule in enumerate(t.get("edition_rules") or ()):
        out += [(f"edition_rules[{i}].{k}", v) for k, v in rule.items() if k != "pd_approved_before" and v]
    for name, preset in (t.get("element_presets") or {}).items():
        out += [(f"element_presets.{name}.{k}", v) for k, v in preset.items() if v]
    return out


def _corpus(
    record_codes: list[str], params_by_code: dict[str, dict[str, Any]], norm_refs: list[dict[str, Any]]
) -> str:
    parts: list[str] = []
    for code in dict.fromkeys(record_codes):
        p = params_by_code[code]
        for refs in p["references"].values():
            for r in refs:
                if r["confidence"] == "HIGH":
                    parts += [str(r[k]) for k in ("ref", *REF_FIELDS) if r.get(k)]
        thr = p["norm_verification"]["threshold"]
        if thr["status"] not in ("CUSTOMER_THRESHOLD", "NO_BASIS_FOUND") and thr.get("condition"):
            parts.append(thr["condition"])
    for r in norm_refs:
        if r["confidence"] == "HIGH":
            parts += [str(r[k]) for k in ("designation", "clause", "edition", "verified_value") if r.get(k)]
    return "\n".join(parts)


def template_corpus(t: dict[str, Any], params_by_code: dict[str, dict[str, Any]]) -> str:
    """The verified text a template's numbers must come from: its own record and every cited record."""
    codes = [t["code"]] if t.get("code") else []
    codes += [r["record"] for r in t.get("norm_refs", ())]
    return _corpus(codes, params_by_code, t.get("norm_refs", []))


def _app2_sample(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    out = {"row": raw["row"]}
    if raw.get("vid_rabot"):
        out["work_type"] = raw["vid_rabot"]
    if raw.get("vid_narusheniya"):
        out["violation_kind"] = raw["vid_narusheniya"]
    out["recommendation"] = raw["recommendation"]
    out["differences"] = raw["differences"]
    return out


_CODE_SUFFIX = re.compile(r"\s*\([A-ZА-Я0-9]+-\d{1,3}\)$")
_SAMPLE_DELTA = re.compile(r"(\d+(?:,\d+)?(?:\s?%|\s(?:м|мм|м²|м³|узла|узлов|узел)))$")


def sample_values(row: str) -> dict[str, str | None]:
    """Values of a Приложение 2 Разделы 4–5 row «№ | Раздел | Параметр (код) | ПД | РД | ИД | Отклонение»."""
    cells = [c.strip() for c in row.split(" | ")]
    if len(cells) != 7:
        raise TemplateBuildError(f"app2_sample row with {len(cells)} cells: {row!r}")
    m = _SAMPLE_DELTA.search(cells[6])
    return {
        "pd_value": cells[3],
        "rd_value": cells[4],
        "id_value": cells[5],
        "actual_value": cells[5],
        "delta": m.group(1) if m else None,
        "deviation": cells[6],
    }


def _origin(t: dict[str, Any]) -> dict[str, str]:
    """APPENDIX2 when the template, filled with the sample row's values, reproduces the Приложение 2 text verbatim.

    The data test re-reads the docx and checks that every app2_sample is itself verbatim.
    """
    sample = t.get("app2_sample")
    out = {"work_type": "AG03_DRAFT", "violation_kind": "AG03_DRAFT", "recommendation": "AG03_DRAFT"}
    if not sample:
        return out
    values = sample_values(sample["row"])
    if sample.get("work_type") and _CODE_SUFFIX.sub("", sample["work_type"]) == t["work_type"]:
        out["work_type"] = "APPENDIX2"
    if sample.get("violation_kind"):
        wanted = _CODE_SUFFIX.sub("", sample["violation_kind"])
        candidates = [t["violation_kind"], *t["violation_kind_variants"].values()]
        if any(render_text(c, values) == wanted for c in candidates):
            out["violation_kind"] = "APPENDIX2"
    candidates = [t["recommendation"], *t["recommendation_variants"].values()]
    if any(render_text(c, values) == sample["recommendation"] for c in candidates):
        out["recommendation"] = "APPENDIX2"
    return out


def build_recommendation_templates(
    params_doc: dict[str, Any], inputs: dict[str, Any], matrix_version: str
) -> dict[str, Any]:
    staging, cfg = inputs["staging"], inputs["cfg"]
    params_by_code = {p["code"]: p for p in params_doc["params"]}
    alias_to_code = {p["alias_codes"][0]: p["code"] for p in params_doc["params"]}
    by_staging, kinds = _kinds(cfg)
    enums = load_enums()
    crit_level = {
        v.attrs["catalog_string"]: v.code
        for v in enums["CriticalityLevel"].values
        if v.attrs.get("catalog_string")
    }
    level_attrs = {v.code: v.attrs for v in enums["CriticalityLevel"].values}
    free_cfg = enum_mappings()["free_search"]
    defaults = staging["default_deviation_phrases"]
    for staging_key in defaults:
        if staging_key not in by_staging:
            raise TemplateBuildError(f"default phrase for unknown kind {staging_key}")
    _check_vocabularies(cfg)
    reg_dates = {d["effective_from"] for d in cfg["documents"] if d.get("effective_from")}
    patches = cfg["template_patches"]

    def common(t: dict[str, Any], where: str) -> dict[str, Any]:
        dev = {_kind_key(k, by_staging, where): v for k, v in t["deviation_phrases"].items() if v}
        vk = {_kind_key(k, by_staging, where): v for k, v in t["vid_narusheniya_variants"].items() if v}
        rv = {
            _kind_key(k, by_staging, where): v
            for k, v in (t.get("recommendation_variants") or {}).items()
            if v
        }
        return {
            "work_type": t["vid_rabot"],
            "violation_kind": t["vid_narusheniya"],
            "violation_kind_variants": vk,
            "recommendation": t["recommendation"],
            "recommendation_variants": rv,
            "deviation_phrases": dev,
            "delta_format": _delta_format(t["delta_format"], cfg, by_staging, where),
            "count_noun": t.get("count_noun"),
            "norm_refs": _norm_refs(t["norm_refs_used"], cfg, alias_to_code, where),
            "notes": _clean(t.get("notes")),
        }

    templates = []
    codes_seen = []
    for t in staging["templates"]:
        code = t["code"]
        codes_seen.append(code)
        p = params_by_code.get(code)
        if p is None:
            raise TemplateBuildError(f"template for unknown code {code}")
        if (
            t["parameter_id"] != p["param_id"]
            or t["parameter_name"] != p["parameter_name"]
            or t["section"] != p["section"]
        ):
            raise TemplateBuildError(f"{code}: template id/name/section disagree with the catalog")
        if t["criticality_level"] != p["criticality"]:
            raise TemplateBuildError(
                f"{code}: template criticality {t['criticality_level']} != catalog {p['criticality']}"
            )
        level = crit_level[p["criticality"]]
        section = "7.1" if level == "CRITICAL_SUSPEND" else "7.2"
        if t["protocol_section"] != section or t["protocol_status"] != level_attrs[level]["protocol_status"]:
            raise TemplateBuildError(f"{code}: protocol section/status disagree with the criticality")
        for alias in t["aliases"]:
            if alias not in p["alias_codes"] and not re.fullmatch(r"[A-ZА-Я0-9]+-\d{1,3}", alias):
                raise TemplateBuildError(f"{code}: odd alias {alias}")
        rules = [dict(r) for r in t.get("edition_rules") or ()]
        patch = patches.get(code) or {}
        rules += [dict(r) for r in patch.get("edition_rules_add", ())]
        for r in rules:
            if r["pd_approved_before"] not in reg_dates:
                raise TemplateBuildError(
                    f"{code}: edition rule date {r['pd_approved_before']} not in the registry"
                )
        out = {
            "template_id": code,
            "code": code,
            "param_id": p["param_id"],
            "section": p["section"],
            "short_name": p["short_name"],
            "parameter_name": p["parameter_name"],
            "criticality": p["criticality"],
            "criticality_level": level,
            "protocol_section": section,
            "protocol_status": level_attrs[level]["protocol_status"],
            **common(t, code),
            "norm_fill": t.get("norm_fill"),
            "edition_rules": rules,
            "app2_sample": _app2_sample(t.get("app2_sample")),
        }
        out["text_origin"] = _origin(out)
        templates.append(out)
    if codes_seen != [p["code"] for p in params_doc["params"]]:
        raise TemplateBuildError("templates must list the 132 catalog codes in catalog order")
    free = []
    topic_map = cfg["free_topic_map"]
    topics_enum = list(enums["FreeTopic"].codes)
    for t in staging["free_topics"]:
        topic = topic_map.get(t["topic"], t["topic"])
        if topic not in topics_enum:
            raise TemplateBuildError(f"FREE topic {t['topic']} → {topic} not in enums.FreeTopic")
        if (
            t["criticality_level"] != free_cfg["criticality_string"]
            or t["protocol_status"] != free_cfg["protocol_status"]
        ):
            raise TemplateBuildError(f"FREE {topic}: criticality/status differ from enums free_search")
        presets = {}
        for noun, pr in (t.get("element_presets") or {}).items():
            presets[noun] = {
                "violation_kind": pr["vid_narusheniya"],
                "recommendation": pr["recommendation"],
                "pd_value": pr.get("pd_value"),
                "rd_value": pr.get("rd_value"),
            }
        out = {
            "template_id": f"FREE-{topic}",
            "topic": topic,
            "code_pattern": f"^FREE-{topic}-\\d{{3}}$",
            "seen_in_train": bool(t["seen_in_train"]),
            "short_name": t["short_name"],
            "criticality": free_cfg["criticality_string"],
            "criticality_level": free_cfg["criticality_level"],
            "protocol_section": "7.2",
            "protocol_status": free_cfg["protocol_status"],
            **common(t, f"FREE-{topic}"),
            "element_presets": presets,
        }
        out["text_origin"] = {
            "work_type": "AG03_DRAFT",
            "violation_kind": "AG03_DRAFT",
            "recommendation": "AG03_DRAFT",
        }
        free.append(out)
    if [f["topic"] for f in free] != topics_enum:
        raise TemplateBuildError("free_topics must list enums.FreeTopic in order")
    # Checks: norm placeholders are fillable, COUNT has nouns, numbers come from verified records.
    problems = []
    for t in (*templates, *free):
        where = t["template_id"]
        blob = json.dumps(
            {
                k: t[k]
                for k in (
                    "violation_kind",
                    "violation_kind_variants",
                    "recommendation",
                    "recommendation_variants",
                    "deviation_phrases",
                )
            },
            ensure_ascii=False,
        )
        fill = t.get("norm_fill") or {}
        for ph in ("norm_value", "norm_ref"):
            if "{" + ph + "}" in blob and not fill.get(ph):
                problems.append(f"{where}: uses {{{ph}}} without norm_fill.{ph}")
        fmts = {t["delta_format"]["default"], *t["delta_format"]["by_kind"].values()}
        if "COUNT" in fmts and not (t.get("count_noun") and {"one", "few", "many"} <= set(t["count_noun"])):
            problems.append(f"{where}: COUNT delta without count_noun one/few/many")
        if "{delta}" in blob and fmts == {"NONE"}:
            problems.append(f"{where}: {{delta}} with delta format NONE")
        corpus = template_corpus(t, params_by_code)
        for fld, text in _texts_of(t):
            for num in unverified_numbers(text, corpus):
                problems.append(f"{where}.{fld}: number {num!r} not found in a HIGH verified record")
    if problems:
        raise TemplateBuildError("recommendation templates: " + "; ".join(problems[:20]))
    content = {"templates": templates, "free_topics": free, "documents": cfg["documents"]}
    kinds_out = []
    for k in kinds:
        item = dict(k)
        phrase = defaults.get(k["staging_key"])
        item["default_phrase"] = phrase
        kinds_out.append(item)
    origin_counts = Counter(t["text_origin"]["recommendation"] for t in templates)
    return {
        "seed": "recommendation_templates",
        "schema_version": 1,
        "matrix_version": matrix_version,
        "status": "DRAFT (AG-03): до экспертной проверки (U-18); печатается с префиксом «Проект рекомендации (до подтверждения инспектором): »",
        "checked_at": cfg["checked_at"],
        "content_sha256": sha256_json(content),
        "counts": {
            "templates": len(templates),
            "free_topics": len(free),
            "protocol_section": dict(sorted(Counter(t["protocol_section"] for t in templates).items())),
            "recommendation_origin": dict(sorted(origin_counts.items())),
            "norm_refs": sum(len(t["norm_refs"]) for t in (*templates, *free)),
            "edition_rules": sum(len(t["edition_rules"]) for t in templates),
            "documents": len(cfg["documents"]),
        },
        "review": {
            "status": "DRAFT",
            "note": "Нормы верифицированы по действующим редакциям на 27.09.2026 (src/norms); тексты требуют экспертной проверки (97 Q3, U-18).",
            "fields_needing_expert_review": [
                "work_type",
                "violation_kind",
                "recommendation",
                "deviation_phrases",
            ],
        },
        "sources": inputs["sources"],
        "conventions": cfg["template_conventions"],
        "vocabularies": {
            "deviation_kinds": kinds_out,
            "markers": cfg["markers"],
            "delta_formats": sorted(set(cfg["delta_formats"].values())),
            "discrepancy_to_deviation_kind": cfg["discrepancy_to_deviation_kind"],
            "comparison_result_to_deviation_kind": cfg["comparison_result_to_deviation_kind"],
            "violation_type_to_deviation_kind": cfg["violation_type_to_deviation_kind"],
            "reference_status": cfg["reference_status"],
            "threshold_status": cfg["threshold_status"]["vocabulary"],
        },
        "regime_changes": cfg["regime_changes"],
        **content,
    }


def _check_vocabularies(cfg: dict[str, Any]) -> None:
    enums = load_enums()
    kind_codes = {k["code"] for k in cfg["deviation_kinds"]} | {"BY_SIGN"}
    directions = set(enums["DeviationDirection"].codes)
    for k in cfg["deviation_kinds"]:
        if k["direction"] not in directions:
            raise TemplateBuildError(
                f"deviation kind {k['code']}: direction {k['direction']} not a DeviationDirection"
            )
    for mark, direction in cfg["markers"].items():
        if direction not in directions:
            raise TemplateBuildError(f"marker {mark}: {direction} not a DeviationDirection")
    for table, enum_name in (
        ("discrepancy_to_deviation_kind", "DiscrepancyType"),
        ("comparison_result_to_deviation_kind", "ComparisonResult"),
        ("violation_type_to_deviation_kind", "ViolationType"),
    ):
        mapping = cfg[table]
        if set(mapping) != set(enums[enum_name].codes):
            missing = set(enums[enum_name].codes) ^ set(mapping)
            raise TemplateBuildError(
                f"{table} must cover {enum_name} exactly (difference: {sorted(missing)})"
            )
        bad = {v for v in mapping.values() if v not in kind_codes}
        if bad:
            raise TemplateBuildError(f"{table}: unknown kinds {bad}")
    if set(cfg["threshold_status"]["staging_map"].values()) - set(cfg["threshold_status"]["vocabulary"]):
        raise TemplateBuildError("threshold_status.staging_map maps to codes outside the vocabulary")
    for doc in cfg["documents"]:
        if doc["applies_by"] not in ("PD_APPROVAL_DATE", "EVENT_DATE"):
            raise TemplateBuildError(f"{doc['designation']}: applies_by {doc['applies_by']}")
        if bool(doc.get("replaced_by")) == bool(doc.get("valid_until")):
            raise TemplateBuildError(f"{doc['designation']}: needs exactly one of replaced_by / valid_until")


# ─────────────────────────────────────────────── Params: texts from the templates ───────────────────────────────────

_MARK = re.compile(r"^(?:⬇️|⬆️|❌|🔄)\s*")


def derive_param_texts(
    params_doc: dict[str, Any],
    templates_doc: dict[str, Any],
    dt_keys: dict[str, list[str]],
    cfg: dict[str, Any],
) -> None:
    """params.json work_type, recommendation_template, deviation_verb and text_sources from the templates."""
    by_code = {t["code"]: t for t in templates_doc["templates"]}
    defaults = {k["code"]: k["default_phrase"] for k in templates_doc["vocabularies"]["deviation_kinds"]}
    dt_map = cfg["discrepancy_to_deviation_kind"]
    for p in params_doc["params"]:
        t = by_code[p["code"]]
        p["work_type"] = t["work_type"]
        p["recommendation_template"] = t["recommendation"]
        rule_dirs = {r.get("direction") for r in _atomic(p["comparison_rule"])}
        verbs = {}
        for dt in dt_keys[p["code"]]:
            kind = dt_map[dt]
            if kind == "BY_SIGN":
                kind = "INCREASE" if rule_dirs == {"INCREASE"} else "DECREASE"
            phrase = t["deviation_phrases"].get(kind) or defaults.get(kind)
            if phrase:
                verbs[dt] = _MARK.sub("", phrase)
        p["deviation_verb"] = dict(sorted(verbs.items()))
        p["text_sources"]["work_type"] = t["text_origin"]["work_type"]
        p["text_sources"]["recommendation_template"] = t["text_origin"]["recommendation"]


# ─────────────────────────────────────────────── Value templates ────────────────────────────────────────────────────

_PRED = re.compile(r"^(.+?) (предусмотрен|предусмотрена|предусмотрено|предусмотрены)$")
_AGR = {"предусмотрен": "m", "предусмотрена": "f", "предусмотрено": "n", "предусмотрены": "pl"}


def build_value_templates(
    inputs: dict[str, Any], cmap: dict[str, Any], templates_doc: dict[str, Any], matrix_version: str
) -> dict[str, Any]:
    src = inputs["values"]
    enums = load_enums()
    families = {f["family"]: f for f in cmap["element_families"]}
    for fam in src["nouns"]:
        if fam not in families:
            raise TemplateBuildError(f"value_templates.yaml: unknown family {fam}")
    missing = sorted(set(families) - set(src["nouns"]))
    if missing:
        raise TemplateBuildError(f"value_templates.yaml: families without a noun: {missing}")
    agr_ok = {"m", "f", "n", "pl"}
    for name, forms in src["predicates"].items():
        if set(forms) != agr_ok:
            raise TemplateBuildError(f"predicate {name}: needs m/f/n/pl forms")
    for cr, stages in src["by_comparison_result"].items():
        if cr not in enums["ComparisonResult"].codes:
            raise TemplateBuildError(f"by_comparison_result: {cr} is not a ComparisonResult")
        if set(stages) != {"PD", "RD", "ID"}:
            raise TemplateBuildError(f"by_comparison_result.{cr}: needs PD, RD and ID")
        for text in stages.values():
            for ph in re.findall(r"\{~([^{}]+)\}", text or ""):
                if ph not in src["predicates"]:
                    raise TemplateBuildError(f"by_comparison_result.{cr}: unknown predicate {ph}")
    if set(src["by_comparison_result"]) != set(enums["ComparisonResult"].codes):
        raise TemplateBuildError("by_comparison_result must cover every ComparisonResult")
    nouns = {}
    for fam, n in src["nouns"].items():
        if n["agr"] not in agr_ok:
            raise TemplateBuildError(f"noun {fam}: agr {n['agr']}")
        nouns[fam] = {"nom": n["nom"], "agr": n["agr"], "gen": n.get("gen")}
    lexicon: dict[str, dict[str, Any]] = {}

    def add(nom: str, agr: str, gen: str | None) -> None:
        key = " ".join(nom.split()).lower()
        if "{" in key:
            return
        lexicon.setdefault(key, {"nom": nom, "agr": agr, "gen": gen})

    # Route nouns first (gold wording), then the family nouns, then FREE element presets.
    for fam in cmap["element_families"]:
        for r in fam["routes"]:
            vt = r.get("value_templates") or {}
            m = _PRED.match(vt.get("pd") or "")
            if m and not m.group(1).endswith(" не"):  # «Работы не предусмотрены» is a negation, not a noun
                fam_noun = nouns[fam["family"]]
                gen = fam_noun["gen"] if fam_noun["nom"].lower() == m.group(1).lower() else None
                add(m.group(1), _AGR[m.group(2)], gen)
    for n in nouns.values():
        add(n["nom"], n["agr"], n["gen"])
    for t in templates_doc["free_topics"]:
        for noun, preset in t["element_presets"].items():
            m = _PRED.match(preset.get("pd_value") or "")
            if not m or m.group(1) != noun:
                raise TemplateBuildError(
                    f"FREE-{t['topic']} preset {noun}: pd_value must be «{noun} предусмотрен(а/о/ы)»"
                )
            add(noun, _AGR[m.group(2)], None)
    # Every route noun must agree with its own predicate.
    for key, n in lexicon.items():
        if n["agr"] not in agr_ok:
            raise TemplateBuildError(f"lexicon {key}: agr {n['agr']}")
    out = {
        "seed": "value_templates",
        "schema_version": 1,
        "matrix_version": matrix_version,
        "sources": inputs["value_sources"],
        "number_format": src["number_format"],
        "units": src["units"],
        "class_formats": src["class_formats"],
        "cells": src["cells"],
        "predicates": src["predicates"],
        "by_comparison_result": src["by_comparison_result"],
        "fallbacks": src["fallbacks"],
        "nouns": nouns,
        "lexicon": dict(sorted(lexicon.items())),
        "agreement_by_ending": src["agreement_by_ending"],
    }
    for c in out["class_formats"]:
        re.compile(c["pattern"])
    out["content_sha256"] = sha256_json({k: v for k, v in out.items() if k not in ("sources",)})
    return out


def norm_number_problems(params_doc: dict[str, Any], inputs: dict[str, Any]) -> list[str]:
    """Numbers in AG-03's own threshold notes must also come from the verified records of that parameter."""
    params_by_code = {p["code"]: p for p in params_doc["params"]}
    problems = []
    for code, dec in inputs["cfg"]["threshold_decisions"].items():
        corpus = _corpus([code], params_by_code, [])
        texts = [dec.get("threshold_note") or "", *(dec.get("sub_notes") or {}).values()]
        for text in texts:
            # Matrix literals quoted in a note («порог Матрицы 1,5 м») are the customer's values, not norms.
            text = re.sub(r"Матрицы\s+[<>≤≥]?\s*\d[\d,./–-]*\s*(?:мм|м|%)?", "Матрицы", text)
            for num in unverified_numbers(text, corpus):
                problems.append(f"{code}: threshold note number {num!r} not in a HIGH verified record")
    return problems
