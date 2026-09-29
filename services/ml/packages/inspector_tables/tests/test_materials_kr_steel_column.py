"""KR-056 steel grade, KR-060 column section, KR-062 column rebar diameter: extraction from prose/spec text."""

from __future__ import annotations

from inspector_tables.materials import facts_from_act, facts_from_kr_text


def _kind(text: str, kind: str) -> set[tuple[str, str]]:
    return {(f.family, f.value) for f in facts_from_kr_text(text) if f.kind == kind}


def test_steel_grade_bound_to_steel_family() -> None:
    text = (
        "Верхние пояса ферм – труба 240х120х9 по ГОСТ 32931-2015 из стали С345 по ГОСТ 27772-2015; "
        "лестницы выполнены из металлических профилей из стали С245 по ГОСТ 27772-2015. "
        "Материал стальных элементов - сталь С 255."
    )
    got = {(f.kind, f.family, f.value, f.rank) for f in facts_from_kr_text(text)}
    assert ("steel_grade", "Фермы", "С345", 345.0) in got
    assert ("steel_grade", "Лестницы", "С245", 245.0) in got
    assert ("steel_grade", "Стальные конструкции", "С255", 255.0) in got


def test_steel_grade_rejects_stray_c_numbers() -> None:
    # no steel context; «СП 245»; a longer number
    text = "Расстояние С 245 мм между осями. По СП 245.1325800 принято. Индекс С2450 в таблице."
    assert not _kind(text, "steel_grade")
    # a rolled shape right before the value is context enough in a flattened spec table
    rows = "Колонна металлическая Двутавр 25К1 C345 34 Балка Двутавр 18Б1 C245"
    assert {("Колонны", "С345"), ("Балки", "С245")} <= _kind(rows, "steel_grade")


def test_column_sections_per_mark_and_generic() -> None:
    text = "Колонна К1 сечением 500х600 мм. Пилон Пн-3 300×1200. Колонны первого этажа сечением 400х400 мм."
    got = {(f.family, f.value, f.rank) for f in facts_from_kr_text(text) if f.kind == "column_section"}
    assert ("Колонна К1", "500×600", 300000.0) in got
    assert ("Колонна Пн3", "300×1200", 360000.0) in got
    assert ("Колонны", "400×400", 160000.0) in got


def test_column_section_ignores_windows_and_stray_dimensions() -> None:
    text = "Оконный блок 1500х1200 мм. Перемычка 250х120. Плита перекрытия 600х600 отм. +3,000."
    assert not _kind(text, "column_section")


def test_column_section_rejects_base_plates_and_three_dimension_chains() -> None:
    text = (
        "Колонна металлическая Двутавр 25К1 C345 127 металлической колонне приварить к базе и "
        "Прокат листовой Пластина 360х490х20 C345. Колонна К2 Пластина 200х300. Колонны К3 – 400х400."
    )
    assert _kind(text, "column_section") == {("Колонна К3", "400×400")}


def test_column_longitudinal_diameter_skips_stirrups_and_slabs() -> None:
    text = "Колонна К1: продольная арматура 4Ø25 А500С, хомуты Ø8 А240 шаг 100. Плита П1 - Ø12 А500С шаг 200."
    assert _kind(text, "column_rebar_dia") == {("Колонны", "Ø25")}


def test_column_diameter_in_id_act_of_columns() -> None:
    got = {
        (f.kind, f.family, f.value)
        for f in facts_from_act(
            "Армирование колонн К1-К4", "Арматура Ø25 А500С, хомуты Ø8 А240 по ГОСТ 34028-2016"
        )
    }
    assert ("column_rebar_dia", "Колонны", "Ø25") in got
    assert ("column_rebar_dia", "Колонны", "Ø8") not in got
