"""PZ-013…018, 021…023: labelled prose values (synthetic snippets after real phrasings) and the ambiguity gate."""

from __future__ import annotations

import pytest

from inspector_tables import pzparams as pz


def _one(text: str, code: str) -> list[pz.PzFact]:
    return [f for f in pz.extract(text) if f.code == code]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Степень огнестойкости здания – I; класс конструктивной пожарной опасности здания – С0;", "I"),
        (
            "Комплекс запроектирован II степени огнестойкости С0 класса конструктивной пожарной опасности.",
            "II",
        ),
        ("проектирован в конструкциях, соответствующих l степени огнестойкости и СО конструктивной", "I"),
        ("-степень огнестойкости - 1; -класс конструктивной пожарной опасности - С 0.", "I"),
        ("Степень огнестойкости IV.", "IV"),
    ],
)
def test_fire_resistance_degree(text: str, value: str) -> None:
    got = _one(text, "PZ-022")
    assert [f.value for f in got] == [value]
    assert got[0].rank == pz.SCALES["PZ-022"][value]


@pytest.mark.parametrize(
    "text",
    [
        "Степень огнестойкости определена расчётом",
        "Степень огнестойкости и класс пожарной опасности",
        "для зданий 1-й степени огнестойкости требуется",  # a normative reference, not the building's value
        "Степень огнестойкости ПI, 4 Федерального закона",  # garbled OCR: never guessed
    ],
)
def test_fire_resistance_no_guess(text: str) -> None:
    assert _one(text, "PZ-022") == []


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Класс конструктивной пожарной опасности здания – С0;", "C0"),
        ("класс конструктивной пожарной опасности Со, срок службы", "C0"),
        ("-класс конструктивной пожарной опасности - С 1.", "C1"),
        ("в конструкциях l степени огнестойкости и СО конструктивной пожарной опасности.", "C0"),
        ("С0 класса конструктивной пожарной опасности.", "C0"),
    ],
)
def test_hazard_class(text: str, value: str) -> None:
    assert [f.value for f in _one(text, "PZ-023")] == [value]


def test_hazard_class_not_normed() -> None:
    assert _one("Класс конструктивной пожарной опасности не нормируется", "PZ-023") == []


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Класс энергетической эффективности здания — B+ (высокий)", "B+"),
        ("Класс энергосбережения С", "C"),
        ("класс энергоэффективности «А+»", "A+"),
        ("Класс энергетической эффективности: В", "B"),
    ],
)
def test_energy_class(text: str, value: str) -> None:
    assert [f.value for f in _one(text, "PZ-021")] == [value]


def test_energy_class_words_are_not_letters() -> None:
    assert _one("Класс энергетической эффективности — высокий", "PZ-021") == []
    assert _one("класс энергетической эффективности не присваивается", "PZ-021") == []
    assert (
        _one("Класс энергетической эффективности в проекте определён", "PZ-021") == []
    )  # lowercase «в» is a word


def test_reliability_category() -> None:
    t = "категория по надежности электроснабжения жилого комплекса принята - II. В отдельную группу выделены"
    assert [f.value for f in _one(t, "PZ-015")] == ["II"]
    assert [f.value for f in _one("Категория надежности электроснабжения: третья", "PZ-015")] == ["III"]
    assert [f.value for f in _one("II категория по надежности электроснабжения", "PZ-015")] == ["II"]
    # sub-systems and other networks never speak for the building
    assert _one("потребители СПЗ I категории надежности электроснабжения, к ним относятся", "PZ-015") == []
    assert _one("Водоснабжение обеспечивается по 1 категории надежности.", "PZ-015") == []
    assert _one("Категория надежности действия насосной станции – II.", "PZ-015") == []


def test_reliability_downgrade_rank() -> None:
    assert (
        pz.normalize_enum("PZ-015", "I")[1]
        > pz.normalize_enum("PZ-015", "II")[1]
        > pz.normalize_enum("PZ-015", "III")[1]
    )


def test_electric_power() -> None:
    (f,) = _one("Суммарная нагрузка жилого дома: Расчетная мощность: Рр=462,5 кВт По", "PZ-014")
    assert (f.value, f.unit) == (462.5, "кВт")
    (f,) = _one("Расчётная электрическая мощность — 1 250 кВт", "PZ-014")
    assert f.value == 1250
    (f,) = _one("Расчетная мощность объекта 1,25 МВт", "PZ-014")
    assert (f.value, f.unit) == (1250, "кВт")
    assert _one("Расчётная мощность трансформатора 1000 кВА", "PZ-014") == []
    assert _one("расчетных нагрузках γc = 1.00, E = 2.1 · 106 кг/см²", "PZ-014") == []


def test_water_heat_gas() -> None:
    (w,) = _one("Водопотребление — 125,4 м³/сут", "PZ-016")
    assert (w.value, w.unit) == (125.4, "м³/сут")
    assert _one("Расход воды на внутреннее пожаротушение – 5 л/сек", "PZ-016") == []
    assert _one("Расход воды на полив территории 20 м3/сут", "PZ-016") == []  # another water kind
    (h,) = _one("Суммарная тепловая нагрузка — 2,15 Гкал/ч", "PZ-017")
    assert (h.value, h.unit) == (2.15, "Гкал/ч")
    assert _one("Тепловая нагрузка на отопление 1,2 Гкал/ч", "PZ-017") == []
    (g,) = _one("Максимальный часовой расход газа — 45,6 нм3/ч", "PZ-018")
    assert (g.value, g.unit) == (45.6, "м³/ч")
    assert _one("Расход газа не предусмотрен", "PZ-018") == []
    assert _one("Расход воды 12,5 л/с", "PZ-016") == []


def test_capacity() -> None:
    assert [f.value for f in _one("Устройство в школе на 600 мест по адресу", "PZ-013")] == [600]
    assert [f.value for f in _one("Детский сад на 220 мест", "PZ-013")] == [220]
    assert [f.value for f in _one("Вместимость 825 учащихся", "PZ-013")] == [825]
    assert _one("Общая вместимость автостоянки – 87 машино-мест", "PZ-013") == []
    assert _one("(1 сетка на 10 мест для переодевания)", "PZ-013") == []
    assert _one("Вместимость, человек до 66 до 66", "PZ-013") == []


def _val(code: str, stage: str, value, unit=None, page=1):
    return {"fact_key": pz.FACT_KEY, "param_code": code, "stage": stage, "page_no": page,
            "value_norm": {"type": "number", "value": value, **({"unit": unit} if unit else {})}}  # fmt: skip


def test_ambiguity_gate() -> None:
    vals = [_val("PZ-014", "PD", 462.5), _val("PZ-014", "PD", 150.0), _val("PZ-014", "RD", 300.0)]
    stats = pz.resolve_ambiguity(vals)
    assert stats["ambiguous_groups"] == 1
    assert [v.get("is_ambiguous") for v in vals] == [True, True, None]


def test_ambiguity_dominant_value_stays() -> None:
    vals = [_val("PZ-014", "PD", 462.5, page=p) for p in (1, 2, 3)] + [_val("PZ-014", "PD", 150.0)]
    stats = pz.resolve_ambiguity(vals)
    assert stats["dominant_groups"] == 1
    assert [v.get("is_ambiguous") for v in vals] == [None, None, None, True]


def test_ambiguity_reading_shared_with_another_stage_stays() -> None:
    vals = [
        _val("PZ-016", "PD", 106.95, "м³/сут"),
        _val("PZ-016", "PD", 107.5, "м³/сут"),
        _val("PZ-016", "RD", 107.5, "м³/сут"),
    ]
    pz.resolve_ambiguity(vals)
    assert [v.get("is_ambiguous") for v in vals] == [
        True,
        None,
        None,
    ]  # both stages print 107,5: EQUAL, no guess


def test_ambiguity_disjoint_readings_are_all_set_aside() -> None:
    vals = [_val("PZ-016", "PD", 106.95), _val("PZ-016", "PD", 81.2), _val("PZ-016", "RD", 107.5)]
    pz.resolve_ambiguity(vals)
    assert [v.get("is_ambiguous") for v in vals] == [
        True,
        True,
        None,
    ]  # RD has a single reading, PD none usable


def test_single_value_untouched() -> None:
    vals = [_val("PZ-022", "PD", "II", page=1), _val("PZ-022", "PD", "II", page=2)]
    pz.resolve_ambiguity(vals)
    assert not any(v.get("is_ambiguous") for v in vals)
