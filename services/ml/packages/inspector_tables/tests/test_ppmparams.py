"""Fire-safety (ППМ) facts from prose and labels (PPM-102…114): labelled values only, element binding, ambiguity."""

from __future__ import annotations

from typing import Any

from inspector_tables.ppmparams import extract, from_ppm, norm_ei, resolve_ambiguity
from inspector_tables.values import ValueSink


def _facts(text: str) -> set[tuple[str, str | None, Any]]:
    return {(f.code, f.location, f.value) for f in extract(text)}


def test_norm_ei_variants() -> None:
    assert norm_ei("EI 60") == ("EI 60", 60.0)
    assert norm_ei("EI-30") == ("EI 30", 30.0)
    assert norm_ei("ЕI60") == ("EI 60", 60.0)  # Cyrillic Е
    assert norm_ei("EIS 45") == ("EI 45", 45.0)
    assert norm_ei("REI 150") is None
    assert norm_ei("EI 77") is None


def test_smoke_system_air_flow_is_bound_to_the_tag() -> None:
    got = _facts(
        "ВД1 (L=13000 м3/ч, Pc=500 Па) Оборудование ПД10 (L=35 600 м³/ч, Pc=250 Па) ДУ1: L=25 000 м³/ч, P=650 Па"
    )
    assert ("PPM-112", "ВД1", 13000.0) in got
    assert ("PPM-112", "ПД10", 35600.0) in got
    assert ("PPM-112", "ДУ1", 25000.0) in got
    # a tag list shares one value between several fans: not bound; a plain supply system is not smoke control
    assert not any(
        loc in ("ПД15.2", "ПД14.2", "ПД16.2") for _, loc, _ in _facts("ПД14.2, ПД15.2, ПД16.2 (L=630 м3/ч)")
    )
    assert not _facts("П1 (L=8140 м3/ч, Pc=320 Па)")
    assert not _facts("ДУ1 по проекту")


def test_vpv_jets_and_flow_per_jet() -> None:
    got = _facts(
        "Проектом предусматриваются пожарные краны Ду50 с расчетом 2 струи на 2,6л/с. Расход 1 струя по 3,7 л/сек"
    )
    assert ("PPM-113", "число струй", 2.0) in got and ("PPM-113", "расход на струю", 2.6) in got
    assert ("PPM-113", "расход на струю", 3.7) in got
    assert ("PPM-113", "расход на струю", 2.9) in _facts("В2 АУВП 30 5,8 2 струи, 2,9л/с")
    # «n x q = Σ л/с» counts only near a ВПВ context and never as a per-section norm list
    assert ("PPM-113", "расход на струю", 2.5) in _facts(
        "предусматривается ВПВ с расходом воды не менее 2 х 2,5 = 5 л/ с совмещенный"
    )
    assert not _facts("2x2,5 л/с – для каждой жилой секции высотой не более 75 м")
    assert not _facts("Размеры 2 х 2,5 л/с")


def test_external_fire_water_flow_is_object_level_and_skips_network_capacity() -> None:
    assert ("PPM-114", None, 110.0) in _facts(
        "Наружное пожаротушение — 110 л/с Расход бытовых стоков — 13,4 л/с"
    )
    assert ("PPM-114", None, 30.0) in _facts(
        "Расход воды на нужды наружного пожаротушения – 30 л/сек (СП 8.13130.2009 таблица 2)"
    )
    assert ("PPM-114", None, 20.0) in _facts(
        "Расход воды на наружное пожаротушение составляет 20 л/с согласно табл. 3"
    )
    # network capacity is not the design flow; an internal flow after the label is not an external one
    assert not _facts(
        "сети, обеспечивающие расход воды на наружное пожаротушение в г. Москве не менее 110 л/с"
    )
    assert not _facts("наружное пожаротушение от гидрантов")


def test_damper_ei_per_system_tag() -> None:
    got = _facts(
        "Противопожарные клапаны для систем ПД1, ВД1 приняты с пределом огнестойкости EI60 с электромеханическим приводом. "
        "Для системы подпора в шахту лифта (ПД18) применяется нормально закрытый (н.з.) клапан с пределом огнестойкости EI 120."
    )
    assert {("PPM-111", "ПД1", "EI 60"), ("PPM-111", "ВД1", "EI 60"), ("PPM-111", "ПД18", "EI 120")} <= got
    # a duct-coating class and a generic damper statement without a system tag are not bound
    assert not any(
        c == "PPM-111"
        for c, _, _ in _facts("воздуховоды огнезащитой классом EI 30. клапан с пределом огнестойкости EI 60")
    )


def test_door_ei_needs_the_mark_right_before_it() -> None:
    got = _facts("Д-6 EI30 Д-6 EI30 Д-1 EI 60 Д-7 Д-7 Вр-4 EI30")
    assert ("PPM-103", "Д-6", "EI 30") in got and ("PPM-103", "Д-1", "EI 60") in got
    assert not any(loc in ("Д-7", "Вр-4") for _, loc, _ in got)
    assert not any(c == "PPM-103" for c, _, _ in _facts("двери противопожарные предел огнестойкости EI 60"))


def test_cable_index_is_bound_to_family_and_section() -> None:
    got = _facts("Кабель ВВГнг(А)-FRLS 3х1,5 и BBГнг(A)-LS 5x16,0, КПСнг(А)-FRHF 1х2х0,75, ВВГ 3х1,5")
    assert ("PPM-109", "ВВГ 3х1.5", "FRLS") in got
    assert ("PPM-109", "ВВГ 5х16", "LS") in got  # Latin look-alikes and «16,0» normalised
    assert not any(loc == "ВВГ 3х1.5" and v is None for _, loc, v in got)


def test_finishing_class_per_surface_and_room_group_skips_bounds() -> None:
    got = _facts(
        "Класс пожарной опасности материалов на путях эвакуации: для стен и потолков лестничных клеток, вестибюля "
        "и лифтовых холлов – КМ2, для коридоров и холлов – КМ3; для покрытий полов лестничных клеток – КМ3."
    )
    assert ("PPM-107", "стены и потолки: лестничные клетки", "КМ2") in got
    assert ("PPM-107", "стены и потолки: вестибюли", "КМ2") in got
    assert ("PPM-107", "стены и потолки: коридоры", "КМ3") in got
    assert ("PPM-107", "полы: лестничные клетки", "КМ3") in got
    assert not _facts("покрытия полов должны иметь класс пожарной опасности не выше чем КМ1")


def test_compartment_area_and_design_widths_skip_normative_bounds() -> None:
    assert ("PPM-102", "Пожарный отсек", 2400.0) in _facts("Площадь пожарного отсека — 2 400 м²")
    assert ("PPM-102", "Пожарный отсек 2", 3150.5) in _facts(
        "площадь пожарного отсека № 2 составляет 3150,5 м²"
    )
    assert not _facts("площадь пожарного отсека не более 2 400 м²")
    assert ("PPM-104", "эвакуационный проход", 1.2) in _facts("Ширина эвакуационного прохода — 1,2 м")
    assert ("PPM-104", "эвакуационный проход", 1.2) in _facts("Ширина эвакуационного прохода 1200 мм")
    assert not _facts("Ширина эвакуационного прохода не менее 1,2 м")
    assert ("PPM-105", "наружная дверь", 1.2) in _facts("Ширина наружной двери в свету — 1,2 м")
    assert not _facts("Ширина наружной двери принимается не менее 0,9 м")


def test_ambiguity_keeps_agreed_or_dominant_values_only() -> None:
    def val(stage: str, loc: str, v: float) -> dict[str, Any]:
        return {"fact_key": "ppm.air_flow", "param_code": "PPM-112", "stage": stage, "location": loc,
                "value_norm": {"type": "number", "value": v, "unit": "м³/ч"}}  # fmt: skip

    vals = [val("PD", "ВД1", 13000.0), val("PD", "ВД1", 9000.0), val("RD", "ВД1", 13000.0)]
    resolve_ambiguity(vals)
    assert [bool(v.get("is_ambiguous")) for v in vals] == [False, True, False]  # the agreed reading survives
    vals = [val("PD", "ВД2", 1.0), val("PD", "ВД2", 2.0)]
    resolve_ambiguity(vals)
    assert all(v["is_ambiguous"] for v in vals)  # nobody wins → none is compared
    vals = [val("PD", "ВД3", 5.0)] * 3 + [val("PD", "ВД3", 6.0)]
    resolve_ambiguity(vals)
    assert [bool(v.get("is_ambiguous")) for v in vals] == [False, False, False, True]  # dominant reading


def test_from_ppm_emits_contract_values_with_rank_and_location() -> None:
    sink = ValueSink("F1", "OBJ-X", "0" * 64, "RD")
    from_ppm(
        sink, 3, extract("Д-1 EI 60 ВД1 (L=13000 м3/ч, Pc=500 Па) наружное пожаротушение — 30 л/с"), "OCR"
    )
    by = {v["fact_key"]: v for v in sink.values}
    assert by["ppm.door_ei"]["location"] == "Д-1" and by["ppm.door_ei"]["value_norm"]["rank"] == 60.0
    assert (
        by["ppm.air_flow"]["param_code"] == "PPM-112" and by["ppm.air_flow"]["value_norm"]["unit"] == "м³/ч"
    )
    assert by["ppm.external_flow"]["location_type"] == "OBJECT"
    assert by["ppm.air_flow"]["confidence"] < 0.9 + 1e-9  # OCR page: confidence lowered
