"""Value templates (packages/contracts/seed/value_templates.json): pd_value / rd_value / id_value in submission style
(93 §3.5) and the ПД/РД/ИД cells of Приложение 2 sections 4–5. Owner: AG-03."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from inspector_common import params
from inspector_common.contracts.loader import load_enums

# Тюменская public train gold values (93 §1.2, verbatim), keyed by finding group.
GOLD = {
    "G-TR-001": (
        dict(
            family="VENT_SUPPLY_UNIT",
            discrepancy_type="CONFIGURATION_CHANGED",
            pd_sheet=26,
            rd_plan_mark="ОВ1",
            location="012",
        ),
        ("Конфигурация приточных установок по листу 26 ПД", "Иная конфигурация на плане ОВ1, помещение 012"),
    ),
    "G-TR-002": (
        dict(family="WARM_FLOOR", discrepancy_type="ELEMENT_MISSING", location="267"),
        ("Тёплый пол предусмотрен", "Тёплый пол отсутствует"),
    ),
    "G-TR-003": (
        dict(family="VENT_EXHAUST_BRANCH", discrepancy_type="ELEMENT_MISSING", location="140"),
        ("Вытяжная вентиляция предусмотрена", "Вытяжная вентиляция отсутствует"),
    ),
    "G-TR-004": (
        dict(
            family="VENT_EXHAUST_BRANCH",
            discrepancy_type="CONFIGURATION_CHANGED",
            pd_sheet="10",
            location="314",
        ),
        ("Конфигурация вентиляции по листу 10 ПД", "Конфигурация вентиляции изменена"),
    ),
}


@pytest.mark.parametrize("group", sorted(GOLD))
def test_gold_values_are_reproduced(group: str) -> None:
    kwargs, (pd, rd) = GOLD[group]
    assert params.stage_values(**kwargs) == {"pd_value": pd, "rd_value": rd, "id_value": None}


def test_stages_outside_the_check_are_null_and_fallbacks_apply() -> None:
    three = params.stage_values(
        "VALUE_MISMATCH", stages=("PD", "RD", "ID"), values={"PD": "1.4", "RD": 1.1, "ID": "1,1"}, unit="м"
    )
    assert three == {"pd_value": "1,4 м", "rd_value": "1,1 м", "id_value": "1,1 м"}
    assert (
        params.stage_values("VALUE_MISMATCH", stages=("RD", "ID"), values={"RD": 2, "ID": 1}, unit="шт")[
            "pd_value"
        ]
        is None
    )
    assert params.stage_values("VALUE_MISMATCH", values={"PD": 5})["rd_value"] is None  # missing value → null
    no_sheet = params.stage_values(family="VENT_EXHAUST_BRANCH", discrepancy_type="CONFIGURATION_CHANGED")
    assert no_sheet["pd_value"] == "Конфигурация вентиляции по ПД"
    no_mark = params.stage_values(
        family="VENT_SUPPLY_UNIT", discrepancy_type="CONFIGURATION_CHANGED", pd_sheet=26, location="012"
    )
    assert no_mark["rd_value"] == "Иная конфигурация в РД, помещение 012"
    with pytest.raises(ValueError):
        params.stage_values()


def test_generic_templates_agree_with_the_noun() -> None:
    cases = {
        "Лифт": ("Лифт предусмотрен", "Лифт отсутствует"),
        "Тактильные указатели": ("Тактильные указатели предусмотрены", "Тактильные указатели отсутствуют"),
        "внутренние сети связи": ("Внутренние сети связи предусмотрены", "Внутренние сети связи отсутствуют"),
        "Оборудование ИТП": ("Оборудование ИТП предусмотрено", "Оборудование ИТП отсутствует"),
        "Система вызова помощника": (
            "Система вызова помощника предусмотрена",
            "Система вызова помощника отсутствует",
        ),
        "тёплый пол": ("Тёплый пол предусмотрен", "Тёплый пол отсутствует"),  # lexicon hit keeps «ё»
    }
    for element, (pd, rd) in cases.items():
        out = params.stage_values("MISSING_DESIGN_ELEMENT", element=element)
        assert (out["pd_value"], out["rd_value"]) == (pd, rd), element
    extra = params.stage_values("EXTRA_ELEMENT", element="Вытяжная вентиляция")
    assert (
        extra["pd_value"] == "Вытяжная вентиляция не предусмотрена"
        and extra["rd_value"] == "Вытяжная вентиляция предусмотрена"
    )
    cfg = params.stage_values("CONFIGURATION_MISMATCH", family="FIRE_DOOR", pd_sheet=7)
    assert cfg == {
        "pd_value": "Конфигурация противопожарных дверей по листу 7 ПД",
        "rd_value": "Конфигурация противопожарных дверей изменена",
        "id_value": None,
    }


def test_the_lexicon_agrees_with_every_change_map_route() -> None:
    """Every «X предусмотрен(а/о/ы)» route template is reproduced by the generic template with the lexicon noun."""
    vt = params.load_value_templates()
    cmap = params.load_change_map()
    checked = 0
    for route in cmap.routes():
        templates = route.data.get("value_templates") or {}
        m = re.match(r"^(.+?) (предусмотрен[аоы]?)$", templates.get("pd") or "")
        if not m or "{" in m.group(1) or m.group(1).endswith(" не"):
            continue
        noun = vt.noun(m.group(1))
        assert noun is not None and noun.nom == m.group(1)
        assert vt.predicates["предусмотрен"][noun.agr] == m.group(2), m.group(1)
        if re.fullmatch(r".+ отсутству(?:ет|ют)", templates.get("rd") or ""):
            assert templates["rd"] == f"{noun.nom} {vt.predicates['отсутствует'][noun.agr]}"
        checked += 1
    assert checked >= 30
    assert set(vt.nouns_by_family) == set(cmap.families)


def test_value_formats() -> None:
    fv = params.format_value
    assert fv(1.0, "м") == "1,0 м" and fv("0.80", "м") == "0,80 м" and fv(Decimal("1560"), "м3") == "1560 м³"
    assert fv((4, 95), "мм2") == "4×95 мм²" and fv([500, 300]) == "500×300"
    assert fv("16", "%") == "16%" and fv(80, "‰") == "80 ‰" and fv(45, "дн") == "45 дн."
    assert fv("В35", kind="CONCRETE_CLASS") == "B35" and fv("B 22,5", kind="CONCRETE_CLASS") == "B22,5"
    assert fv("В35") == "В35"  # without the kind a «В» token may be a system tag: left as is
    assert (
        fv("EI 60") == "EI-60" and fv("REI150") == "REI-150" and fv("КМ 2") == "КМ2" and fv("F 150") == "F150"
    )
    assert fv("W8", kind="WATER_TIGHTNESS") == "W8"
    assert fv("  Тёплый   пол  предусмотрен ") == "Тёплый пол предусмотрен"
    assert fv(None) is None and fv("") is None and fv([]) is None
    assert (
        params.format_number_ru(12500) == "12500"
        and params.format_number_ru(12500, group_thousands=True) == "12 500"
    )
    assert params.format_number_ru("1 234,50") == "1234,50" and params.format_number_ru(-1.05) == "-1,05"
    assert params.format_number_ru(2.345, decimals=2) == "2,35"
    with pytest.raises(ValueError):
        params.format_number_ru("12а")


def test_deltas_and_plurals() -> None:
    assert params.format_delta("ABS", 4.5, 3.7, unit="м") == ("0,8 м", 0.8, "м")
    assert params.format_delta("ABS", "1,40", "1,1", unit="м")[0] == "0,30 м"
    assert (
        params.format_delta("PCT", 850, 715)[0] == "15,9%"
        and params.format_delta("PCT", 320, 280)[0] == "12,5%"
    )
    assert params.format_delta("PCT", 100, 90)[0] == "10%" and params.format_delta("PCT", 0, 5) is None
    nouns = {"one": "узел", "few": "узла", "many": "узлов"}
    assert [
        params.format_delta("COUNT", n + 3, 3, count_noun=nouns)[0] for n in (1, 2, 5, 11, 21, 22, 112)
    ] == [
        "1 узел",
        "2 узла",
        "5 узлов",
        "11 узлов",
        "21 узел",
        "22 узла",
        "112 узлов",
    ]
    assert params.format_delta("COUNT", 3.5, 1, count_noun=nouns) is None
    assert params.format_delta("NONE", 1, 2) is None and params.format_delta("ABS", None, 2) is None
    with pytest.raises(ValueError):
        params.format_delta("LOG", 1, 2)


def test_protocol_cells_and_locations() -> None:
    assert params.protocol_cell("B35") == "B35"
    assert params.protocol_cell(None) == "нет данных" and params.protocol_cell(None, applicable=False) == "—"
    assert params.location_display(["140", "142"]) == "пом. 140, 142"
    assert params.location_display("012", "ROOM") == "пом. 012"
    assert params.location_display(["OBJECT"]) is None and params.location_display(None) is None
    assert params.location_display(["Корпус 1, этаж 3"], "FLOOR") == "Корпус 1, этаж 3"


def test_generic_templates_cover_every_comparison_result() -> None:
    vt = params.load_value_templates()
    assert set(vt.by_comparison_result) == set(load_enums()["ComparisonResult"].codes)
    assert vt.cells == {"not_applicable": "—", "missing": "нет данных"}
