"""Context gates (В20 vs B20, «ИД» vs исходные данные, КМ) and change_matrix_map routing (97 §2.10). Owner: AG-03."""

from __future__ import annotations

import pytest

from inspector_common import params
from inspector_common.contracts.enums import FreeTopic, ParameterMappingStatus


def _span(text: str, token: str) -> tuple[int, int]:
    start = text.index(token)
    return start, start + len(token)


@pytest.mark.parametrize(
    ("text", "token", "discipline", "expected"),
    [
        ("Бетон тяжёлый класса В20 F150 W6", "В20", None, "CONCRETE_CLASS"),
        ("Плита перекрытия Пм1, В30", "В30", None, "CONCRETE_CLASS"),
        ("Система В20 — вытяжная, L=1200 м³/ч", "В20", None, "VENT_SYSTEM"),
        ("ветви В20.1 и В20.2 в помещении 140", "В20", None, "VENT_SYSTEM"),
        ("B20", "B20", "КЖ", "CONCRETE_CLASS"),
        ("B20", "B20", "ОВ1", "VENT_SYSTEM"),
        ("B20", "B20", None, "UNKNOWN"),
    ],
)
def test_b_token_classification(text: str, token: str, discipline: str | None, expected: str) -> None:
    start, end = _span(text, token)
    assert params.classify_b_token(text, start, end, discipline) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Раздел П-ИД «Исходные данные»", "SOURCE_DATA"),
        ("Том 1.2 ИД (исходно-разрешительная документация)", "SOURCE_DATA"),
        ("ИД — исходные данные для проектирования", "SOURCE_DATA"),
        ("Реестр ИД: акты освидетельствования скрытых работ", "AS_BUILT"),
        ("Комплект ПД, РД и ИД по объекту", "AS_BUILT"),
        ("ИД", "UNKNOWN"),
    ],
)
def test_id_abbreviation_classification(text: str, expected: str) -> None:
    start, end = _span(text, "ИД")
    assert params.classify_id_abbreviation(text, start, end) == expected


def test_km_gate_distinguishes_fire_class_from_steel_marking() -> None:
    reg = params.load_params()
    assert [h.value for h in reg.extract("AR-050", "Материалы отделки путей эвакуации класса КМ1")] == ["1"]
    assert reg.extract("AR-050", "Раздел КМ1 Конструкции металлические") == []
    assert reg.extract("AR-050", "шифр 2024-01-КМ1") == []


def test_gate_decision_reasons() -> None:
    reg = params.load_params()
    hit = reg.extract("KR-055", "Бетон класса В25 F150 W6")[0]
    assert hit.value == "25" and hit.gate == "CONCRETE_CLASS:require"
    assert reg.extract("KR-055", "класс бетона В 30")[0].gate == "CONCRETE_CLASS:group:v2"
    assert reg.extract("KR-055", "В25", discipline="КЖ")[0].gate == "CONCRETE_CLASS:discipline:КЖ"
    assert reg.extract("KR-055", "В25") == []  # no context → default reject
    assert [h.value for h in reg.extract("KR-055", "В25", apply_gates=False)] == ["25"]


@pytest.fixture(scope="module")
def cmap() -> params.ChangeMap:
    return params.load_change_map()


@pytest.mark.parametrize(
    ("family", "dt", "code", "status", "result", "pd", "rd"),
    [
        # Organizer train gold, OBJ-TYUMENSKAYA-5-GOLD-SEED (97 §2.10)
        (
            "VENT_SUPPLY_UNIT",
            "CONFIGURATION_CHANGED",
            "IOS4-079",
            "PROVISIONAL_DOMAIN_MAPPING",
            "CONFIGURATION_MISMATCH",
            "Конфигурация приточных установок по листу {pd_sheet} ПД",
            "Иная конфигурация на плане {rd_plan_mark}, помещение {location}",
        ),
        (
            "WARM_FLOOR",
            "ELEMENT_MISSING",
            "FREE-HEATING",
            "MATRIX_GAP_CONFIRMED",
            "MISSING_DESIGN_ELEMENT",
            "Тёплый пол предусмотрен",
            "Тёплый пол отсутствует",
        ),
        (
            "VENT_EXHAUST_BRANCH",
            "ELEMENT_MISSING",
            "IOS4-078",
            "PROVISIONAL_DOMAIN_MAPPING",
            "MISSING_DESIGN_ELEMENT",
            "Вытяжная вентиляция предусмотрена",
            "Вытяжная вентиляция отсутствует",
        ),
        (
            "VENT_EXHAUST_BRANCH",
            "CONFIGURATION_CHANGED",
            "IOS4-078",
            "PROVISIONAL_DOMAIN_MAPPING",
            "CONFIGURATION_MISMATCH",
            "Конфигурация вентиляции по листу {pd_sheet} ПД",
            "Конфигурация вентиляции изменена",
        ),
    ],
)
def test_gold_routes(cmap: params.ChangeMap, family, dt, code, status, result, pd, rd) -> None:
    route = cmap.route(family, dt)
    assert route.parameter_code == code and route.emit
    assert route.parameter_mapping_status is ParameterMappingStatus(status)
    assert route.comparison_result == result
    assert route.data["value_templates"]["pd"] == pd and route.data["value_templates"]["rd"] == rd
    assert route.basis.startswith("GOLD:G-TR-")


def test_warm_floor_is_a_free_heating_matrix_gap(cmap: params.ChangeMap) -> None:
    route = cmap.route("WARM_FLOOR", "ELEMENT_MISSING")
    assert route.is_free and route.free_topic is FreeTopic.HEATING
    assert params.load_free_topics()["HEATING"].code(1) == "FREE-HEATING-001"
    assert "WARM_FLOOR" in cmap.families_for_code("FREE-HEATING")


def test_ventilation_hedges(cmap: params.ChangeMap) -> None:
    assert cmap.route("VENT_SUPPLY_UNIT", "CONFIGURATION_CHANGED").hedge_codes == ("IOS4-078",)
    assert cmap.route("VENT_EXHAUST_BRANCH", "ELEMENT_MISSING").hedge_codes == ("IOS4-079",)


@pytest.mark.parametrize(
    ("family", "dt"),
    [
        ("VENT_EXHAUST_BRANCH", "ELEMENT_ADDED"),  # additions are context (97 §2.10)
        ("ROOM", "ELEMENT_ADDED"),
        ("ROOM", "POSITION_SHIFTED"),  # relocations are context
        ("CONCRETE_CLASS", "VALUE_INCREASED"),  # directional trigger
        ("FOUNDATION_SLAB", "VALUE_INCREASED"),  # user decision 97 Q4b (NS-C14)
        ("STRUCTURE_ELEVATION", "VALUE_INCREASED"),  # user decision 97 Q4c (NS-C09 over-pour)
    ],
)
def test_non_emitting_routes(cmap: params.ChangeMap, family: str, dt: str) -> None:
    route = cmap.route(family, dt)
    assert route.emit is False and route.data["reason"]


def test_concrete_fw_marks_route_to_free_structure(cmap: params.ChangeMap) -> None:
    """User decision on 97 Q4a: same class B, lower F/W → FREE-STRUCTURE, not KR-055."""
    route = cmap.route("CONCRETE_FW_MARK", "CLASS_DOWNGRADED")
    assert route.parameter_code == "FREE-STRUCTURE" and route.basis == "USER:Q4a"
    assert cmap.route("CONCRETE_CLASS", "CLASS_DOWNGRADED").parameter_code == "KR-055"


def test_route_lookup_errors(cmap: params.ChangeMap) -> None:
    with pytest.raises(KeyError, match="unknown element family"):
        cmap.route("NO_SUCH_FAMILY", "ELEMENT_MISSING")
    with pytest.raises(KeyError, match="no route"):
        cmap.route("WARM_FLOOR", "VALUE_DECREASED")


def test_every_emitting_matrix_route_points_to_a_parameter(cmap: params.ChangeMap) -> None:
    reg = params.load_params()
    for route in cmap.routes():
        if route.emit and not route.is_free:
            spec = reg.get(route.parameter_code)
            if route.data["sub_check"]:
                assert route.data["sub_check"] in (spec["atomic_sub_checks"] or [spec.code])
