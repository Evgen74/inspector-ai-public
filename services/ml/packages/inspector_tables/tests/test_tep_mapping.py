"""ТЭП indicator → catalog code (surface parking SPZU-037 vs building parking PZ-012) and the glued «в т.ч.»
total («11618,27 11114,27 504,0» → 11618,27)."""

from __future__ import annotations

from inspector_tables.tep import map_param
from inspector_tables.values import _incl_total


def test_parking_rows_map_to_their_own_codes() -> None:
    assert map_param("Количество машино-мест") == "PZ-012"
    assert map_param("Машино-места в подземной автостоянке") == "PZ-012"
    assert map_param("Количество машино-мест на открытых автостоянках") == "SPZU-037"
    assert map_param("Количество парковочных мест на участке") == "SPZU-037"
    assert map_param("Гостевые машино-места") == "SPZU-037"
    assert map_param("Площадь застройки") == "PZ-001"


def test_glued_incl_total_takes_the_first_number() -> None:
    ind = "Общая площадь здания, в т.ч.: - выше отм. 0,000 - ниже отм. 0,000"
    assert _incl_total(ind, "11618,27 11114,27 504,0") == ("11618,27", 11618.27)
    assert _incl_total("Общая площадь здания", "11618,27 11114,27") is None  # not a «в т.ч.» row
    assert _incl_total(ind, "17 140,2") is None  # thousands group, not components
    assert _incl_total(ind, "3+подвал") is None


def test_object_level_pz_rows_map_to_their_codes() -> None:
    assert map_param("Расчетная электрическая мощность") == "PZ-014"
    assert map_param("Суточное водопотребление") == "PZ-016"
    assert map_param("Суммарная тепловая нагрузка") == "PZ-017"
    assert map_param("Максимальный часовой расход газа") == "PZ-018"
    assert map_param("Класс энергетической эффективности здания") == "PZ-021"
    assert map_param("Степень огнестойкости") == "PZ-022"
    assert map_param("Класс конструктивной пожарной опасности") == "PZ-023"
    assert map_param("Вместимость") == "PZ-013"
    assert map_param("Вместимость автостоянки") is None  # parking is not the object's capacity


def _tep_table(rows: list[tuple[str, str, str]]) -> dict:
    out = []
    for i, (ind, unit, val) in enumerate(rows, 1):
        v = {"raw": val, "value": float(val.replace(",", ".")) if val.replace(",", "").isdigit() else val}
        out.append({"row_no": i, "kind": "DATA", "pdf_page_number": 3,
                    "cells": {"indicator": {"raw": ind, "value": ind}, "unit": {"raw": unit, "value": None}, "value": v}})  # fmt: skip
    return {"table_id": "T1", "table_type": "TEP", "pages": [3], "rows": out}


def test_tep_enum_rows_carry_rank_and_unknown_values_are_unbound() -> None:
    from inspector_tables.values import ValueSink, from_table

    sink = ValueSink("F1", "OBJ-X", "0" * 64, "PD")
    t = _tep_table([("Степень огнестойкости", "", "II"), ("Класс энергетической эффективности", "", "высокий"),
                    ("Расчетная электрическая мощность", "кВт", "462,5")])  # fmt: skip
    from_table(sink, t, {1: "PZ-022", 2: "PZ-021", 3: "PZ-014"})
    by_code = {v.get("param_code"): v for v in sink.values}
    assert by_code["PZ-022"]["value_norm"]["value"] == "II" and by_code["PZ-022"]["value_norm"]["rank"] == 4
    assert None in by_code  # «высокий» is not a class letter: the row stays a plain tep.value
    assert by_code["PZ-014"]["value_norm"]["unit"] == "кВт"
