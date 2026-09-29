"""Unit tests: tag grammar, discipline marks, value templates, room comparators, recommendation texts."""

from __future__ import annotations

from collections import Counter

import pytest

from inspector_compare.comparators import compare_room
from inspector_compare.config import FamilyRule
from inspector_compare.disciplines import file_marks, marks_of_name, plan_mark, required_marks
from inspector_compare.recommendations import fill, render_texts
from inspector_compare.tags import (
    anchor_pattern,
    classify_tag,
    expand_mark,
    family_specs,
    fold_mark,
    system_prefix,
)
from inspector_compare.values import natural_key, render_template, rooms_phrase, ru_number

# ── tags ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("В2.4", ["В2.4"]),
        ("B2.1", ["В2.1"]),  # Latin look-alike from OCR
        ("В2.7,8,9 −950 м³/ч", ["В2.7", "В2.8", "В2.9"]),
        ("В2.3,4 −150 м³/ч", ["В2.3", "В2.4"]),
        ("П17.1, 17.2", ["П17.1", "П17.2"]),
        ("П17", ["П17"]),
        ("П2/ВЕ ±400 м³/ч", ["П2/ВЕ"]),  # an air terminal of system П2, not a unit label
        ("В3.1 −600 м³/ч (над 3D-принтером, поз.133)", ["В3.1"]),
        ("Пароувлажнитель (П2)", ["ПАРОУВЛАЖНИТЕЛЬ"]),
        ("", []),
    ],
)
def test_expand_mark(raw: str, expected: list[str]) -> None:
    assert expand_mark(raw) == expected


def test_fold_and_system_prefix() -> None:
    assert fold_mark(" b2 , 3 ") == "В2,3"
    assert system_prefix("В2.10") == "В2"
    assert system_prefix("П17") == "П17"


def test_anchor_pattern_tolerates_inflection() -> None:
    pattern = anchor_pattern("теплый пол")
    for text in (
        "теплый пол",
        "тёплые полы".replace("ё", "е"),
        "система теплого пола",
        "теплые полы (пом. 267)",
    ):
        assert pattern.search(text), text
    assert not pattern.search("тепловой пункт")


def test_classify_tag_respects_kinds_and_families() -> None:
    from inspector_common.params import load_change_map

    specs = family_specs(load_change_map().document["element_families"])
    specs = {k: v for k, v in specs.items() if k in ("VENT_SUPPLY_UNIT", "VENT_EXHAUST_BRANCH", "WARM_FLOOR")}
    kinds = {
        "VENT_SUPPLY_UNIT": ("EQUIPMENT",),
        "VENT_EXHAUST_BRANCH": ("VENT_SYSTEM", "AIR_TERMINAL"),
        "WARM_FLOOR": ("HEATING_SYSTEM",),
    }
    assert classify_tag("П17.1, 17.2", "EQUIPMENT", specs, kinds) == {"VENT_SUPPLY_UNIT": ["П17.1", "П17.2"]}
    assert classify_tag("П2", "VENT_SYSTEM", specs, kinds) == {}  # a system mark on a duct is not a unit
    assert classify_tag("В2.7,8", "VENT_SYSTEM", specs, kinds) == {"VENT_EXHAUST_BRANCH": ["В2.7", "В2.8"]}
    assert classify_tag("П2/ВЕ ±400", "AIR_TERMINAL", specs, kinds) == {}
    warm = classify_tag("Контур тёплого пола", "HEATING_SYSTEM", specs, kinds)
    assert list(warm) == ["WARM_FLOOR"]
    assert classify_tag("Контур тёплого пола", "EQUIPMENT", specs, kinds) == {}


# ── disciplines ───────────────────────────────────────────────────────────────────────────────


def test_plan_mark_and_marks() -> None:
    assert plan_mark("АНО/150321/1-РД-ОВ1") == "ОВ1"
    assert plan_mark("АНО/150321/1-РД-ОВ2.1") == "ОВ2.1"
    assert plan_mark("СГ-2404-КЖ2") == "КЖ2"
    assert plan_mark("12345") is None
    assert plan_mark(None) is None
    assert file_marks("x/Том 5.pdf", "OV") == ("ОВ",)
    assert file_marks("x/АНО-РД-ВК изм. 2.pdf", "OTHER") == ("ВК",)
    assert file_marks("x/y.pdf", "OTHER", ["АНО/1-РД-ОВ1"]) == ("ОВ",)
    assert "ОДИ" in marks_of_name("ПД/10 Мероприятия по обеспечению доступа инвалидов/Том 10.pdf")
    assert "ПЗ" in marks_of_name("ПД/1 Пояснительная записка/ИЗМ ПО ЗАМЕЧАНИЯМ АНО-П-ОПЗ.pdf")
    assert "ПЗ" not in marks_of_name("ПД/2 Схема/АНО-П-ПЗУ.pdf")
    assert "ГП" in marks_of_name("ПД/2 Схема планировочной организации ЗУ/АНО-П-ПЗУ.pdf")
    # ПД subsection codes (Постановление № 87): ИОС1 ЭОМ, ИОС2/3 ВК, ИОС4 ОВ, ИОС5 СС, ИОС7 ТХ.
    assert file_marks("пд/5.1. П-2025-04.266-ИОС1.1 от (27.4.2026).pdf", "OTHER") == ("ЭОМ",)
    assert file_marks("пд/5.4. П-2025-04.266-ИОС4.2 Корр. 4.pdf", "OTHER") == ("ОВ",)
    assert file_marks("пд/Раздел 5.3 ЖС-РД-270121-П-ИОС3.pdf", "OTHER") == ("ВК",)
    assert file_marks("пд/5.1. П-2025-04.266-ИОС5.5.1 (2).pdf", "OTHER") == ("СС",)
    assert file_marks("пд/133-0820-ОК-1-ИОС7.1 Корр. 2.pdf", "OTHER") == ("ТХ",)
    assert "ОВ" not in marks_of_name("пд/С-005-20-ИОС41.pdf")


def test_required_marks() -> None:
    assert required_marks("ИОС4", [{"discipline": "ОВ"}]) == ("ОВ",)
    assert required_marks("КР", [{"discipline": "КЖ"}, {"discipline": "КР"}]) == ("КР",)
    assert required_marks("ППМ", None) == ("ПБ",)
    assert required_marks("ОДИ", [{"discipline": "ОДИ"}]) == ("ОДИ", "АР")


# ── values ────────────────────────────────────────────────────────────────────────────────────


def test_render_template_gold_phrasing_and_fallbacks() -> None:
    pd = "Конфигурация приточных установок по листу {pd_sheet} ПД"
    rd = "Иная конфигурация на плане {rd_plan_mark}, помещение {location}"
    assert render_template(pd, {"pd_sheet": 26}) == "Конфигурация приточных установок по листу 26 ПД"
    assert (
        render_template(rd, {"rd_plan_mark": "ОВ1", "location": "012"})
        == "Иная конфигурация на плане ОВ1, помещение 012"
    )
    assert render_template(pd, {}) == "Конфигурация приточных установок по ПД"
    assert render_template(rd, {"location": "012"}) == "Иная конфигурация на плане РД, помещение 012"
    assert render_template(rd, {"rd_plan_mark": "ОВ1"}) == "Иная конфигурация на плане ОВ1"
    assert render_template(None, {}) is None


def test_numbers_and_rooms() -> None:
    assert ru_number(1.0, 1) == "1,0"
    assert ru_number(6252.3) == "6252,3"  # seed value_templates.number_format: no thousands grouping
    assert ru_number(850) == "850"
    assert sorted(["140", "012", "98", "314"], key=natural_key) == ["012", "98", "140", "314"]
    assert rooms_phrase(["140", "142"]) == "пом. 140, 142"


# ── comparators ───────────────────────────────────────────────────────────────────────────────


def C(*labels: str) -> Counter[str]:
    return Counter({label: 1 for label in labels})


def test_compare_room_modes() -> None:
    units = FamilyRule("LABEL_MULTISET", ("EQUIPMENT",))
    branches = FamilyRule("SYSTEM_COUNT", ("VENT_SYSTEM",))
    presence = FamilyRule("PRESENCE", ("HEATING_SYSTEM",))
    assert compare_room(units, C("П2", "П17"), C("П2", "П17.1", "П17.2")) == "CONFIGURATION_CHANGED"
    assert compare_room(units, C("П2"), C("П2")) == "EQUAL"
    assert compare_room(branches, C("В2.7", "В2.8", "В2.9"), C()) == "ELEMENT_MISSING"
    assert compare_room(branches, C("В2.10"), C("В2.2", "В2.3", "В2.4")) == "CONFIGURATION_CHANGED"
    assert compare_room(branches, C("В2.1", "В2.2"), C("В2.5", "В2.6")) == "RENUMBERED"
    assert compare_room(branches, C(), C("В2.7")) == "ELEMENT_ADDED"
    assert compare_room(presence, C("теплый пол"), C()) == "ELEMENT_MISSING"
    assert compare_room(presence, C("теплый пол"), C("теплый пол")) == "EQUAL"


# ── recommendation texts ──────────────────────────────────────────────────────────────────────


def test_fill_rules_r1_to_r3() -> None:
    tpl = "Заменить блоки ({location}) на соответствующие проектной ({pd_value}) и нормативной ширине ({norm_value}; {norm_ref})."
    assert (
        fill(tpl, {"location": "пом. 101"})
        == "Заменить блоки (пом. 101) на соответствующие проектной и нормативной ширине."
    )
    assert (
        fill(tpl, {"norm_ref": "СП 1.13130.2020"})
        == "Заменить блоки на соответствующие проектной и нормативной ширине (СП 1.13130.2020)."
    )
    assert fill("Снижение ширины дверей на {delta}", {}) == "Снижение ширины дверей"
    assert fill("⬇️ Уменьшение на {delta}", {"delta": "16%"}) == "⬇️ Уменьшение на 16%"
    assert fill(None, {}) is None


def test_render_texts_matrix_and_free() -> None:
    t = render_texts("IOS4-078", "ELEMENT_MISSING", {"location": "пом. 140, 142"})
    assert t.deviation_text == "❌ Полное отсутствие"
    assert t.deviation_direction == "ABSENT"
    assert t.work_type.endswith("(IOS4-078)")
    assert "(пом. 140, 142)" in t.recommendation
    assert "{" not in t.recommendation
    c = render_texts("IOS4-079", "CONFIGURATION_CHANGED", {"location": "пом. 012"})
    assert c.deviation_text == "🔄 Изменена конфигурация"
    free = render_texts(
        "FREE-HEATING-001",
        "ELEMENT_MISSING",
        {"location": "пом. 267"},
        free_topic="HEATING",
        element_noun="Тёплый пол",
    )
    assert free.violation_kind == "Отсутствие системы тёплых полов, предусмотренной ПД (FREE-HEATING-001)"
    assert "(пом. 267)" in free.recommendation
    assert free.template_id == "FREE-HEATING"
