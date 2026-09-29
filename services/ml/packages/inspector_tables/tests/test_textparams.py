"""Mix parameters read from prose (textparams): ODI-116/117/119/121, SPZU-030/031/038, AR-045/049/050, KR-066,
ZU-131 — synthetic snippets after real phrasings; norm statements and ambiguous readings never become facts."""

from __future__ import annotations

from typing import Any

import pytest

from inspector_tables import textparams as tx

ALL = frozenset()


def _get(text: str, code: str, flags: frozenset[str] = ALL) -> list[tx.TextFact]:
    return [f for f in tx.extract(text, flags) if f.code == code]


def test_corridor_width_mm_and_m_are_normalised() -> None:
    a = _get("Ширина коридоров на путях движения МГН составляет 1800 мм.", "ODI-116")
    b = _get("Для МГН ширина коридора 1,8 м, встречное движение.", "ODI-116")
    assert [f.value for f in a] == [1.8] and a[0].raw == "1,8 м" and a[0].unit == "м"
    assert [f.value for f in b] == [1.8]


@pytest.mark.parametrize(
    "text",
    [
        "Ширина коридора для МГН не менее 1,5 м.",  # a norm quote
        "ширина пути движения МГН — более 1,5 м",
        "Ширина коридора 1,8 м",  # no МГН context and not a «путь движения»
        "ширина коридора для МГН по нормам",
    ],
)
def test_corridor_no_guess(text: str) -> None:
    assert _get(text, "ODI-116") == []


def test_path_of_movement_needs_no_mgn_word() -> None:
    assert [f.value for f in _get("Ширина пути движения — 1,5 м", "ODI-116")] == [1.5]


def test_door_width_on_mgn_route_not_lift_door() -> None:
    ok = _get("Ширина дверного проёма в свету — 900 мм на путях МГН", "ODI-117")
    assert [f.value for f in ok] == [0.9]
    lift = _get("Лифт для инвалидов, ширина дверного проема 1,4 м", "ODI-117")
    assert lift == []
    assert _get("Ширина дверных проемов помещений доступных для МГН не менее 0,9м в свету", "ODI-117") == []


def test_cabin_dimensions_shorter_side() -> None:
    f = _get("Универсальная кабина для МГН 2200х2250 мм в плане", "ODI-119")
    assert [x.value for x in f] == [2.2]
    g = _get("универсальная кабина 1,7х2,2 м", "ODI-119")
    assert [x.value for x in g] == [1.7]
    assert _get("Универсальная кабина — размеры не менее 2,2х2,25 м", "ODI-119") == []


def test_parking_places_by_source() -> None:
    txt = "На стоянке предусмотрено 4 м/м для МГН, в том числе 2 расширенных."
    assert [f.value for f in _get(txt, "SPZU-038", frozenset({"GP"}))] == [4.0]
    assert _get(txt, "ODI-121", frozenset({"GP"})) == []
    assert [f.value for f in _get("Мест для инвалидов — 3 м/м", "ODI-121", frozenset({"ODI"}))] == [3.0]
    assert _get("Мест для МГН — не менее 3 м/м", "ODI-121", frozenset({"ODI"})) == []
    # a digit glued to a letter (legend «М3 Место для МГН») is not a count
    assert (
        _get("Условные обозначения МГН М3 Место для МГН с высотой стола 0,7 м", "ODI-121", frozenset({"ODI"}))
        == []
    )


def test_fire_passage_width_and_turning_radius() -> None:
    f = _get("Ширина пожарного проезда — 4,2 м; проезд шириной 6000 мм", "SPZU-030")
    assert sorted(x.value for x in f) == [4.2, 6.0]
    assert _get("Ширина проездов для пожарной техники составляет не менее 3,5 м", "SPZU-030") == []
    r = _get("Радиус закругления проезда 12 м", "SPZU-031")
    assert [x.value for x in r] == [12.0]
    assert _get("Радиус закругления от 6 до 23 м", "SPZU-031") == []  # a range


def test_roof_slope_units() -> None:
    assert [(f.value, f.raw) for f in _get("уклон кровли 1,7% в сторону воронок", "AR-045")] == [
        (1.7, "1,7 %")
    ]
    assert [f.value for f in _get("Уклон кровли i=0,01.", "AR-045")] == [1.0]
    assert [f.value for f in _get("Уклон кровли 10 ‰", "AR-045")] == [1.0]
    f = _get("уклон кровли 3 °", "AR-045")
    assert f and f[0].sub_id == "AR-045.a" and f[0].value == 5.24
    assert _get("уклон кровли 45 °", "AR-045") == []  # 100 %: not a roof
    assert _get("кровли с уклоном более 1,5%", "AR-045") == []
    assert _get("Уклон кровли выполнен разуклонкой", "AR-045") == []


def test_railing_height_bound_to_kind() -> None:
    f = _get("Лестничные марши имеют ограждение на высоте 1200 мм, непрерывное", "AR-049")
    assert [(x.location, x.value) for x in f] == [("Ограждение лестниц", 1.2)]
    g = _get("Ограждение кровли высотой 1,2 м", "AR-049")
    assert [(x.location, x.value) for x in g] == [("Ограждение кровли", 1.2)]
    assert _get("установка ограждения высотой 2,5 м по периметру участка", "AR-049") == []  # no railing kind
    assert _get("ограждения лестниц высотой не менее 1,2 м", "AR-049") == []


def test_finishing_class_needs_one_zone_and_no_norm() -> None:
    f = _get("Отделка стен лестничных клеток – класс КМ1", "AR-050")
    assert [(x.value, x.location, x.rank) for x in f] == [("КМ1", "Лестничные клетки: стены", 5.0)]
    assert (
        _get("Материалы отделки лестничных клеток, вестибюлей и холлов – КМ3", "AR-050") == []
    )  # several zones
    assert _get("не более, чем: класс КМ1 для отделки стен путей эвакуации", "AR-050") == []
    assert _get("Шифр проекта 2024-01-КМ1, отделка лестничных клеток", "AR-050") == []


def test_fire_protection_limit_thickness_and_composition() -> None:
    txt = "Огнезащита стальных колонн вспучивающейся краской до предела огнестойкости R 90."
    got = {(f.sub_id, f.value, f.location) for f in _get(txt, "KR-066")}
    assert ("KR-066.a", "R90", "Колонны") in got
    assert ("KR-066.c", "вспучивающийся состав", "Колонны") in got
    assert _get("Огнезащита воздуховодов R 60", "KR-066") == []
    assert _get("огнезащита по отдельному проекту", "KR-066") == []
    t = _get("Антикоррозионное покрытие металлоконструкций, толщина сухого слоя 120 мкм", "KR-066")
    assert [(f.sub_id, f.value, f.unit, f.location) for f in t] == [
        ("KR-066.b", 120.0, "мкм", "Антикоррозионное покрытие")
    ]


def test_specific_heat_consumption() -> None:
    a = _get(
        "Удельный годовой расход тепловой энергии на отопление и вентиляцию здания — 95,4 кВт·ч/м²", "ZU-131"
    )
    assert [(f.value, f.unit) for f in a] == [(95.4, "кВт·ч/м²")]
    b = _get("Расчетная удельная характеристика расхода тепловой энергии на отопление и вентиляцию здания, Вт/(м3·°С) 0,178", "ZU-131")  # fmt: skip
    assert [(f.value, f.unit) for f in b] == [(0.178, "Вт/(м³·°С)")]
    # normative value and two numbers side by side are never taken
    assert _get("Нормируемая удельная характеристика расхода тепловой энергии на отопление и вентиляцию здания, Вт/(м3·°С) 0,212", "ZU-131") == []  # fmt: skip
    assert _get("Расчетная удельная характеристика расхода тепловой энергии на отопление здания, Вт/(м3·°С) 0,178 0,212", "ZU-131") == []  # fmt: skip


def test_specific_heat_required_limit_is_not_a_design_value() -> None:
    limit = "на 20 процентов по отношению к удельной характеристике расхода тепловой энергии на отопление и вентиляцию и составляет: qот тр = 0,417 Вт/(м3·°С)"  # fmt: skip
    assert _get(limit, "ZU-131") == []


def test_source_flags() -> None:
    assert "GP" in tx.source_flags("02_ПД/АНО1503211-П-ПЗУ.pdf")
    assert "ODI" in tx.source_flags("10. П-2025-04.266-ОДИ.pdf")
    assert "AR" in tx.source_flags("РД-2025-04-266-АР1.pdf")
    assert "KR" in tx.source_flags("НСЛ-17-КЖ1.1.1.pdf")


def _val(code: str, stage: str, value: Any, *, location: str | None = None, sub: str | None = None, ambiguous: bool = False) -> dict[str, Any]:  # fmt: skip
    q: dict[str, Any] = {}
    if sub:
        q["sub_id"] = sub
    return {
        "fact_key": tx.FACT_KEY,
        "param_code": code,
        "stage": stage,
        "location": location or "OBJECT",
        "value_norm": {"type": "number", "value": value, "unit": "м", "qualifiers": q},
        "is_ambiguous": ambiguous,
    }


def test_resolve_ambiguity_marks_conflicts_and_keeps_agreed() -> None:
    vals = [
        _val("AR-045", "PD", 1.7, sub="AR-045.a"),
        _val("AR-045", "PD", 1.0, sub="AR-045.a"),
        _val("AR-045", "RD", 1.7, sub="AR-045.a"),
        _val("SPZU-030", "PD", 4.2),
        _val("SPZU-030", "PD", 6.0),
        _val("SPZU-030", "RD", 3.5),
        _val("SPZU-031", "PD", 12.0),
    ]
    stats = tx.resolve_ambiguity(vals)
    by = {(v["param_code"], v["stage"], v["value_norm"]["value"]): v["is_ambiguous"] for v in vals}
    # PD prints 1,7 and 1,0; RD prints 1,7: the reading both stages agree on stays comparable
    assert by[("AR-045", "PD", 1.7)] is False and by[("AR-045", "PD", 1.0)] is True
    # PD prints 4,2 and 6,0, no other stage agrees, none dominates: both are set aside
    assert by[("SPZU-030", "PD", 4.2)] is True and by[("SPZU-030", "PD", 6.0)] is True
    assert by[("SPZU-031", "PD", 12.0)] is False
    assert stats["agreed_groups"] == 1 and stats["ambiguous_groups"] == 1
