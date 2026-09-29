"""Recommendation templates (packages/contracts/seed/recommendation_templates.json) and their renderer. Owner: AG-03.

Covers the M1 acceptance: 132 parameter templates plus the FREE topics, no number in a text that is not in a
HIGH-confidence verified norm record, every placeholder renderable (present or absent), the Приложение 2 sample
reproduced where the template claims it, and the grammar/edition rules of the renderer.
"""

from __future__ import annotations

import itertools
import json
import re

import pytest
from jsonschema import Draft202012Validator

from inspector_common import params
from inspector_common.contracts.enums import FreeTopic
from inspector_common.contracts.loader import enum_mappings, load_enums
from inspector_common.contracts.loader import registry as contracts_registry

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
SAMPLE_VALUE = {
    "pd_value": "1,4 м",
    "rd_value": "1,1 м",
    "id_value": "1,0 м",
    "actual_value": "1,0 м",
    "delta": "0,4 м",
    "location": "пом. 140, 142",
    "norm_value": "не менее 1,2 м",
    "norm_ref": "СП 1.13130.2020, п. 4.3.3",
    "element": "тёплый пол",
}


@pytest.fixture(scope="module")
def tpl() -> params.RecommendationTemplates:
    return params.load_recommendation_templates()


@pytest.fixture(scope="module")
def doc() -> dict:
    with open(params.seed_dir() / "recommendation_templates.json", encoding="utf-8") as fh:
        return json.load(fh)


def _texts(t: dict) -> list[tuple[str, str]]:
    out = [
        ("work_type", t["work_type"]),
        ("violation_kind", t["violation_kind"]),
        ("recommendation", t["recommendation"]),
    ]
    for fld in ("violation_kind_variants", "recommendation_variants", "deviation_phrases"):
        out += [(f"{fld}.{k}", v) for k, v in t[fld].items()]
    for k, v in (t.get("norm_fill") or {}).items():
        if v:
            out.append((f"norm_fill.{k}", v))
    for i, rule in enumerate(t.get("edition_rules") or ()):
        out += [(f"edition_rules[{i}].{k}", v) for k, v in rule.items() if k != "pd_approved_before"]
    for name, preset in (t.get("element_presets") or {}).items():
        out += [(f"element_presets.{name}.{k}", v) for k, v in preset.items() if v]
    return out


def _all_templates(doc: dict) -> list[dict]:
    return [*doc["templates"], *doc["free_topics"]]


# ───────────────────────────────────────────────────── Coverage ─────────────────────────────────────────────────────


def test_132_templates_in_catalog_order(doc: dict) -> None:
    reg = params.load_params()
    assert [t["code"] for t in doc["templates"]] == [p.code for p in reg]
    assert doc["counts"]["templates"] == 132
    for t in doc["templates"]:
        spec = reg.get(t["code"])
        assert t["param_id"] == spec.param_id and t["short_name"] == spec.short_name
        assert t["parameter_name"] == spec.parameter_name and t["criticality"] == spec.criticality
        assert t["criticality_level"] == spec.criticality_level.value
        critical = spec.criticality_level.value == "CRITICAL_SUSPEND"
        assert (t["protocol_section"], t["protocol_status"]) == (
            ("7.1", "CRITICAL") if critical else ("7.2", "WARNING")
        )
    assert doc["counts"]["protocol_section"] == {"7.1": 106, "7.2": 26}


def test_free_topics_cover_the_contract_enum(doc: dict, tpl: params.RecommendationTemplates) -> None:
    free = enum_mappings()["free_search"]
    assert [t["topic"] for t in doc["free_topics"]] == [t.value for t in FreeTopic]
    for t in doc["free_topics"]:
        assert (
            t["criticality"] == free["criticality_string"] and t["protocol_status"] == free["protocol_status"]
        )
        assert t["protocol_section"] == "7.2" and re.fullmatch(t["code_pattern"], f"FREE-{t['topic']}-001")
    assert (
        tpl.get("FREE-OTHER-004").template_id == "FREE-OTHER"
    )  # the staging «GENERIC» is the contract OTHER
    with pytest.raises(KeyError):
        tpl.get("FREE-GENERIC-001")


def test_params_texts_come_from_the_templates(doc: dict) -> None:
    reg = params.load_params()
    by_code = {t["code"]: t for t in doc["templates"]}
    for spec in reg:
        t = by_code[spec.code]
        assert spec["work_type"] == t["work_type"]
        assert spec["recommendation_template"] == t["recommendation"]
        assert spec["text_sources"]["recommendation_template"] == t["text_origin"]["recommendation"]
        assert spec["text_sources"]["work_type"] == t["text_origin"]["work_type"]
        for verb in spec["deviation_verb"].values():
            assert not verb.startswith(("⬇", "⬆", "❌", "🔄"))  # the renderer adds the marker (93 §5.4)


def test_template_lookup_by_any_code_style(tpl: params.RecommendationTemplates) -> None:
    assert tpl.get("КР-55").code == "KR-055"
    assert tpl.get("AR-14").code == "AR-040"  # the Приложение 2 typo, resolved to the corridors parameter
    assert tpl.get(79).code == "IOS4-079"
    assert tpl.get("FREE-HEATING-001").topic == "HEATING"
    assert len(tpl) == 132


# ───────────────────────────────────────────────── Placeholders ─────────────────────────────────────────────────────

BAD_OUTPUT = re.compile(
    r"\{|\}|\(\s*\)|\(\s|\s\)|\s{2,}|\s[.,;:]|;\s*\)|\(\s*;|(?<![а-яё])на\s*[.,;)]|:\s*[.,;)]|^\s|\s$"
)


@pytest.mark.parametrize("which", ["templates", "free_topics"])
def test_every_placeholder_is_renderable(doc: dict, which: str) -> None:
    """Every text renders cleanly for every subset of available placeholder values (rules R1–R3)."""
    checked = 0
    for t in doc[which]:
        for fld, text in _texts(t):
            names = sorted(set(PLACEHOLDER.findall(text)))
            assert set(names) <= set(SAMPLE_VALUE), (t["template_id"], fld, names)
            for r in range(len(names) + 1):
                for present in itertools.combinations(names, r):
                    values = {n: SAMPLE_VALUE[n] for n in present}
                    out = params.render_text(text, values)
                    assert out and not BAD_OUTPUT.search(out), (t["template_id"], fld, present, out)
                    for n in present:
                        # R2: a group part is dropped whole when another placeholder of the same part is missing.
                        parts = [
                            p
                            for g in re.findall(r"\(([^()]*)\)", text)
                            for p in g.split("; ")
                            if "{" + n + "}" in p
                        ]
                        if any(set(PLACEHOLDER.findall(p)) - set(present) for p in parts):
                            continue
                        assert SAMPLE_VALUE[n] in out, (t["template_id"], fld, n, out)
                    checked += 1
    assert checked > (1000 if which == "templates" else 100)


def test_render_text_rules() -> None:
    text = "Заменить двери ({location}) по ПД ({pd_value}), но не ниже ({norm_value}; {norm_ref}). Экономия {delta} без перерасчёта"
    full = params.render_text(text, SAMPLE_VALUE)
    assert full == (
        "Заменить двери (пом. 140, 142) по ПД (1,4 м), но не ниже (не менее 1,2 м; СП 1.13130.2020, п. 4.3.3). "
        "Экономия 0,4 м без перерасчёта"
    )
    assert params.render_text(text, {"norm_ref": "СП 1.13130.2020"}) == (
        "Заменить двери по ПД, но не ниже (СП 1.13130.2020). Экономия без перерасчёта"
    )
    assert params.render_text("Сужение на {delta}", {}) == "Сужение"
    assert params.render_text("Отклонение: {element}", {}) == "Отклонение"
    assert params.render_text("Отклонение: {element}", {"element": "тёплый пол"}) == "Отклонение: тёплый пол"
    assert (
        params.render_text("(СП 60.13330.2020) без плейсхолдеров", {})
        == "(СП 60.13330.2020) без плейсхолдеров"
    )


def test_norm_placeholders_always_have_a_fill(doc: dict) -> None:
    for t in _all_templates(doc):
        blob = json.dumps(
            [
                t["violation_kind"],
                t["violation_kind_variants"],
                t["recommendation"],
                t["recommendation_variants"],
            ],
            ensure_ascii=False,
        )
        for ph in ("norm_value", "norm_ref"):
            if "{" + ph + "}" in blob:
                assert (t.get("norm_fill") or {}).get(ph), (t["template_id"], ph)


# ─────────────────────────────────────────────── Verified numbers ───────────────────────────────────────────────────


def _corpus(t: dict) -> str:
    records = [t["code"]] if t.get("code") else []
    records += [r["record"] for r in t["norm_refs"]]
    extra = "\n".join(
        str(r[k])
        for r in t["norm_refs"]
        if r["confidence"] == "HIGH"
        for k in ("designation", "clause", "edition", "verified_value")
        if r.get(k)
    )
    return params.verified_corpus(records) + "\n" + extra


def test_no_unverified_numbers_in_the_texts(doc: dict) -> None:
    """Every number in a template text comes from a HIGH-confidence verified norm record (norm_policy)."""
    numbers = 0
    for t in _all_templates(doc):
        corpus = _corpus(t)
        for fld, text in _texts(t):
            assert params.unverified_numbers(text, corpus) == [], (t["template_id"], fld, text)
            numbers += len(params._BARE_NUMBER.findall(params._REF_TOKENS.sub(" ", text)))
    assert numbers >= 80  # the check is not vacuous (88 quantities at M1)


def test_the_number_check_catches_unverified_values(doc: dict) -> None:
    spzu030 = next(t for t in doc["templates"] if t["code"] == "SPZU-030")
    corpus = _corpus(spzu030)
    # The Приложение 2 sample asks for a turning radius «не менее 12 м»: not found in the norms (M-031 NOT_FOUND).
    assert params.unverified_numbers(spzu030["app2_sample"]["recommendation"], corpus) == ["12"]
    assert params.unverified_numbers("не менее 4,2 м (СП 4.13130.2013, п. 8.1.4)", corpus) == []
    assert params.unverified_numbers("не менее 4,3 м", corpus) == ["4,3"]
    # Designations, dates, clause lists, document numbers and system tags are not quantities.
    assert (
        params.unverified_numbers("ПП Москвы от 26.08.2020 № 1386-ПП, пп. 6.1.5, 6.2.4, В1/Т3, 1-го типа", "")
        == []
    )


def test_low_and_medium_references_are_never_the_source_of_a_number() -> None:
    reg = params.load_params()
    high = params.verified_corpus([p.code for p in reg])
    medium = params.verified_corpus([p.code for p in reg], min_confidence="MEDIUM")
    assert len(medium) > len(high)  # MEDIUM records exist and are excluded from the HIGH corpus


# ─────────────────────────────────────────────── Rendering rules ────────────────────────────────────────────────────


def test_appendix2_rows_render_from_the_stored_samples(
    doc: dict, tpl: params.RecommendationTemplates
) -> None:
    """Each template with an Приложение 2 sample reproduces the sample's «Отклонение» cell and, where the template
    claims APPENDIX2 origin, the sample's «Вид работ», «Вид нарушения» and recommendation verbatim."""
    kinds = {  # the discrepancy of each sample row
        "KR-055": "CLASS_DOWNGRADED",
        "AR-041": "VALUE_DECREASED",
        "AR-040": "VALUE_DECREASED",
        "SPZU-030": "VALUE_DECREASED",
        "IOS1-069": "VALUE_DECREASED",
        "PPM-103": "CLASS_DOWNGRADED",
        "SPZU-025": "VALUE_DECREASED",
        "KR-067": "TOTAL_CHANGED",
        "POS-082": "VALUE_INCREASED",
        "POD-093": "VALUE_CHANGED",
        "ODI-122": "ELEMENT_MISSING",
        "ZU-129": "COUNT_CHANGED",
    }
    seen = {"work_type": 0, "violation_kind": 0, "recommendation": 0}
    for t in doc["templates"]:
        sample = t["app2_sample"]
        if not sample:
            continue
        cells = [c.strip() for c in sample["row"].split(" | ")]
        delta = re.search(r"(\d+(?:,\d+)?(?:%| м| узла))$", cells[6])
        r = tpl.render(
            t["code"],
            discrepancy_type=kinds[t["code"]],
            element_key="бетон" if t["code"] == "KR-067" else None,
            pd_value=cells[3],
            rd_value=cells[4],
            id_value=cells[5],
            delta=delta.group(1) if delta else None,
            display_code="X",
            preliminary=False,
        )
        assert r.deviation_text == cells[6], t["code"]
        origin = t["text_origin"]
        if origin["work_type"] == "APPENDIX2":
            assert r.work_type.removesuffix(" (X)") == re.sub(r" \([^()]+\)$", "", sample["work_type"])
            seen["work_type"] += 1
        if origin["violation_kind"] == "APPENDIX2":
            assert r.violation_kind.removesuffix(" (X)") == re.sub(
                r" \([^()]+\)$", "", sample["violation_kind"]
            )
            seen["violation_kind"] += 1
        if origin["recommendation"] == "APPENDIX2":
            assert r.recommendation_text == sample["recommendation"], t["code"]
            seen["recommendation"] += 1
        else:
            assert sample["differences"] and not sample["differences"].lower().startswith("нет"), t["code"]
    assert seen == {"work_type": 6, "violation_kind": 3, "recommendation": 3}


def test_deltas_and_count_grammar(tpl: params.RecommendationTemplates) -> None:
    r = tpl.render("AR-041", discrepancy_type="VALUE_DECREASED", expected="1,0", actual="0,8", unit="м")
    assert (
        r.deviation_text == "⬇️ Снижение на 0,2 м" and r.deviation_magnitude == 0.2 and r.deviation_unit == "м"
    )
    r = tpl.render("POD-093", discrepancy_type="VALUE_CHANGED", expected=320, actual=280)
    assert r.deviation_text == "⬇️ Расхождение 12,5%" and r.deviation_direction == "DECREASE"
    r = tpl.render("POS-082", discrepancy_type="VALUE_CHANGED", expected=45, actual=58)
    assert r.deviation_kind == "INCREASE" and r.deviation_text == "⬆️ Превышение 28,9%"
    # R6: «Отсутствуют 2 узла» / «Отсутствует 1 узел»; the marker gives the direction.
    r = tpl.render("ZU-129", discrepancy_type="COUNT_CHANGED", expected=3, actual=1)
    assert r.deviation_text == "❌ Отсутствуют 2 узла" and r.deviation_direction == "ABSENT"
    assert (
        tpl.render("ZU-129", discrepancy_type="COUNT_CHANGED", expected=22, actual=1).deviation_text
        == "❌ Отсутствует 21 узел"
    )
    # R7: accusative after «на» («на 1 квартиру»).
    r = tpl.render("PZ-010", discrepancy_type="COUNT_CHANGED", expected=120, actual=119)
    assert "на 1 квартиру" in r.violation_kind and "квартира" not in r.violation_kind
    # No numbers → no delta, the connector goes away.
    r = tpl.render("AR-041", discrepancy_type="VALUE_DECREASED")
    assert r.deviation_text == "⬇️ Снижение" and r.violation_kind.startswith(
        "Снижение ширины эвакуационных дверей ("
    )


def test_resolution_rows_and_deviation_cells_follow_the_protocol_contract(
    tpl: params.RecommendationTemplates,
) -> None:
    reg = contracts_registry()

    def validator(name: str) -> Draft202012Validator:
        ref = f"https://contracts.inspector-ai.local/schemas/protocol.schema.json#/$defs/{name}"
        return Draft202012Validator({"$ref": ref}, registry=reg)

    critical = tpl.render(
        "IOS4-078", discrepancy_type="ELEMENT_MISSING", location=params.location_display(["140", "142"])
    )
    assert critical.protocol_section == "7.1"
    row = critical.resolution_row(1, source_row_no=3)
    assert list(validator("ResolutionCriticalRow").iter_errors(row)) == []
    assert row["work_type"] == "Монтаж систем общеобменной вентиляции (IOS4-078)"
    assert row["recommendation"].startswith(
        params.PRELIMINARY_PREFIX + "Восстановить в РД системы вентиляции"
    )
    assert "(пом. 140, 142)" in row["recommendation"]
    assert list(validator("Deviation").iter_errors(critical.deviation_cell())) == []
    free = tpl.render(
        "FREE-HEATING-001",
        discrepancy_type="ELEMENT_MISSING",
        element="Тёплый пол",
        location=params.location_display(["267", "270", "271", "272"]),
    )
    row = free.resolution_row(1)
    assert list(validator("ResolutionSubstantialRow").iter_errors(row)) == []
    assert row["violation_kind"] == "Отсутствие системы тёплых полов, предусмотренной ПД (FREE-HEATING-001)"
    assert "(пом. 267, 270, 271, 272)" in row["recommendation"]
    assert free.recommendation_text.startswith("Выполнить систему тёплых полов")


def test_gold_codes_have_draft_texts_for_the_demo(tpl: params.RecommendationTemplates) -> None:
    """The Тюменская hero case: IOS4-079 room 012, IOS4-078 rooms 140/142 and 147/198/314, FREE-HEATING-001."""
    r079 = tpl.render("IOS4-079", comparison_result="CONFIGURATION_MISMATCH", location="пом. 012")
    assert r079.deviation_text == "🔄 Изменена конфигурация" and r079.deviation_direction == "CHANGED"
    r078 = tpl.render("IOS4-078", comparison_result="CONFIGURATION_MISMATCH", location="пом. 147, 198, 314")
    assert "(пом. 147, 198, 314)" in r078.recommendation_text
    assert (
        tpl.render("IOS4-078", comparison_result="MISSING_DESIGN_ELEMENT").deviation_text
        == "❌ Полное отсутствие"
    )
    assert r078.normative_refs[0].startswith("СП 60.13330.2020")


def test_deviation_kind_mapping_covers_the_contract_enums(tpl: params.RecommendationTemplates) -> None:
    enums = load_enums()
    assert set(tpl.by_discrepancy) == set(enums["DiscrepancyType"].codes)
    assert set(tpl.by_comparison_result) == set(enums["ComparisonResult"].codes)
    assert set(tpl.by_violation_type) == set(enums["ViolationType"].codes)
    assert set(tpl.markers.values()) == set(enums["DeviationDirection"].codes)
    assert tpl.deviation_kind(discrepancy_type="VALUE_CHANGED", expected=10, actual=12) == "INCREASE"
    assert tpl.deviation_kind(discrepancy_type="VALUE_CHANGED") == "DECREASE"
    assert tpl.deviation_kind(comparison_result="MISSING_DESIGN_ELEMENT") == "ABSENCE"
    assert tpl.deviation_kind(violation_type="CLASS_DOWNGRADE") == "CLASS_DOWNGRADE"
    for kind in tpl.deviation_kinds:
        assert tpl.default_phrases[kind][:1] in "⬇⬆❌🔄"


# ─────────────────────────────────────────────── Editions and regimes ───────────────────────────────────────────────


def test_edition_rules_select_the_norm_by_pd_approval_date(tpl: params.RecommendationTemplates) -> None:
    old = tpl.render(
        "PPM-110", discrepancy_type="COUNT_CHANGED", expected=10, actual=8, pd_approved_on="2025-03-01"
    )
    new = tpl.render(
        "PPM-110", discrepancy_type="COUNT_CHANGED", expected=10, actual=8, pd_approved_on="2026-08-01"
    )
    assert old.norm_ref == "СП 3.13130.2009" and "(СП 3.13130.2009)" in old.recommendation_text
    assert new.norm_ref == "СП 3.13130.2026, п. 6.8.2"
    assert (
        tpl.render("PPM-110", discrepancy_type="COUNT_CHANGED").norm_ref == new.norm_ref
    )  # no date → in force
    zu125 = tpl.render("ZU-125", discrepancy_type="VALUE_DECREASED", pd_approved_on="2023-12-01")
    assert zu125.norm_ref == "СП 50.13330.2012"
    ar051 = tpl.render("AR-051", discrepancy_type="VALUE_DECREASED", pd_approved_on="2025-12-31")
    assert ar051.norm_ref == "СП 367.1325800.2017"  # norms.yaml template patch
    # Inline citations of a replaced design norm lose their clause numbers (numbering differs between editions).
    odi = tpl.render(
        "ODI-117", discrepancy_type="THRESHOLD_BELOW_MIN", pd_value="0,9 м", pd_approved_on="2020-06-01"
    )
    assert "СП 59.13330.2016" in odi.recommendation_text and "СП 59.13330.2020" not in odi.recommendation_text
    assert "6.2.4" not in odi.recommendation_text
    assert (
        tpl.apply_editions("по СП 59.13330.2020, п. 6.3.3. Далее", pd_approved_on="2020-01-01")
        == "по СП 59.13330.2016. Далее"
    )


def test_norm_edition_walks_successive_replacements() -> None:
    assert params.norm_edition("ГОСТ Р 51261-2025", on="2022-01-01") == "ГОСТ Р 51261-2017"
    assert params.norm_edition("ГОСТ Р 51261-2025", on="2024-01-01") == "ГОСТ Р 51261-2022"
    assert params.norm_edition("ГОСТ Р 51261-2025", on="2026-08-01") == "ГОСТ Р 51261-2025"
    assert params.norm_edition("СП 42.13330.2026", on="2025-05-01") == "СП 42.13330.2016"
    assert params.norm_edition("СП 42.13330.2026", on=None) == "СП 42.13330.2026"


def test_template_edition_rules_match_the_registry(doc: dict) -> None:
    for t in doc["templates"]:
        for rule in t["edition_rules"]:
            docs = [
                d
                for d in doc["documents"]
                if d.get("effective_from") == rule["pd_approved_before"]
                and rule["norm_ref"].startswith(d["designation"])
            ]
            assert len(docs) == 1 and docs[0]["applies_by"] == "PD_APPROVAL_DATE", (t["code"], rule)
            assert any(
                r["designation"] == docs[0]["designation"]
                for r in params.load_params().get(t["code"])["norm_verification"]["edition_rules"]
            )
    assert doc["counts"]["edition_rules"] == 11


def test_moscow_waste_regime_of_2026_07(doc: dict) -> None:
    regime = next(r for r in doc["regime_changes"] if r["id"] == "MOSCOW_OSSIG_2026_07")
    assert regime["effective_from"] == "2026-07-01" and regime["applies_by"] == "EVENT_DATE"
    assert regime["params"] == ["OOS-098", "OOS-099", "OOS-100"]
    by_code = {t["code"]: t for t in doc["templates"]}
    assert (
        "с 01.07.2026" in by_code["OOS-100"]["recommendation"]
        and "КПТС" in by_code["OOS-100"]["recommendation"]
    )
    assert (
        "АИС «ОССиГ»" in by_code["OOS-098"]["recommendation"]
        and "ОСИГ»" not in by_code["OOS-098"]["recommendation"]
    )
    reg = params.load_params()
    for code in regime["params"]:
        assert reg.get(code)["norm_verification"]["regime_changes"] == ["MOSCOW_OSSIG_2026_07"]
    assert "01.07.2026" in reg.get("OOS-100").comparison_rule["note"]
    assert reg.get("OOS-098").short_name == "Регистрация в АИС «ОССиГ»"
    hits = reg.extract("OOS-098", params.normalize_regex_input("Объект включён в реестр АИС «ОССиГ»"))
    assert hits, "the «ОССиГ» spelling must be recognised"
    assert reg.extract("OOS-100", "Разрешение на рейс сформировано автоматически")


def test_schemas_reject_malformed_templates(doc: dict) -> None:
    import copy

    def errors(mutate) -> list[str]:
        bad = copy.deepcopy(doc)
        mutate(bad)
        return params.seed_validation_errors("recommendation_templates", bad)

    assert params.seed_validation_errors("recommendation_templates", doc) == []
    assert errors(lambda d: d["templates"][0].update(extra_field=1))  # unevaluatedProperties
    assert errors(
        lambda d: d["templates"][0].update(recommendation="Сделать ({expected}) по ПД")
    )  # unknown placeholder
    assert errors(
        lambda d: d["templates"][0]["deviation_phrases"].update(DECREASE="Уменьшение на {delta}")
    )  # no marker
    assert errors(lambda d: d["templates"][0]["deviation_phrases"].update(SHRINK="⬇️ Сужение"))  # unknown kind
    assert errors(
        lambda d: d["templates"][0].update(work_type="Бетонирование (KR-055)")
    )  # R8: no code in work_type
    assert errors(lambda d: d["templates"].pop())  # 132 templates
    assert errors(lambda d: d["templates"][0].update(protocol_section="7.2"))  # criticality ↔ section
    assert errors(lambda d: d["free_topics"][0].update(criticality="Существенное (предписание)"))
    assert errors(lambda d: d["documents"][0].pop("effective_from"))
    vt = json.loads((params.seed_dir() / "value_templates.json").read_text(encoding="utf-8"))
    assert params.seed_validation_errors("value_templates", vt) == []
    vt["nouns"]["WARM_FLOOR"]["agr"] = "x"
    vt["by_comparison_result"]["NOT_A_RESULT"] = {"PD": None, "RD": None, "ID": None}
    assert len(params.seed_validation_errors("value_templates", vt)) >= 2
