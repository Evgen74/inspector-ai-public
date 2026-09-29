"""Energy-efficiency facts from prose (ZU-124…128): labelled values only, wall/roof binding by the last marker, the
insulation material group as the location, and the file gate."""

from __future__ import annotations

from inspector_tables.energy import CLASS_RANK, facts_from_text, is_envelope_source
from inspector_tables.values import ValueSink, from_energy


def _facts(text: str, **kw: bool) -> set[tuple[str, float | str, str | None]]:
    return {(f.kind, f.value, f.material) for f in facts_from_text(text, envelope=kw.get("envelope", True))}


def test_class_from_labelled_sentences_and_passport_rows() -> None:
    assert ("class", "C", None) in _facts(
        "Зданию присваивается Класс энергетической эффективности С (нормальный)."
    )
    assert ("class", "A", None) in _facts("соответствует классу энергосбережения «А» (СП 50.13330.2012).")
    # the passport row keeps the label and the value on separate lines
    assert ("class", "B+", None) in _facts("32\nКласс энергосбережения\nВ+\n33 Соответствует ли")
    assert CLASS_RANK["A"] > CLASS_RANK["B"] > CLASS_RANK["C"] > CLASS_RANK["D"]


def test_class_requirements_and_negatives_are_not_a_class() -> None:
    assert not _facts("(класс энергосбережения не ниже «C»), требуемое сопротивление теплопередачи")
    assert not _facts("класс энергетической эффективности не присваивается")
    # a Cyrillic «В» that starts the next word is not the class
    assert not _facts("Класс энергетической эффективности В соответствии с приказом определяется расчетом")


def test_wall_and_roof_thickness_bind_by_last_marker_and_group_by_material() -> None:
    text = (
        "Наружные стены. Сэндвич-панель, толщина δ1=0.2м, коэффициент\nтеплопроводности\nλБ1=0.041Вт/(м°С).\n"
        "Кровля\nЖелезобетон (ГОСТ 26633), толщина δ1=0.2м, коэффициент теплопроводности\nλБ1=2.04Вт/(м°С)\n"
        "ТЕХНОНИКОЛЬ XPS CARBON PROF 400, толщина δ2=0.15м, коэффициент\nтеплопроводности\nλБ2=0.032Вт/(м°С).\n"
        "- Утеплитель пенополистирол экструдированный, плотность 32 кг/м³ (100+100мм) - 2 слоя\n"
    )
    got = _facts(text)
    assert ("wall_thickness", 200.0, "Минеральная вата / сэндвич-панель") in got
    assert ("roof_thickness", 150.0, "Пенополистирол (XPS/EPS)") in got
    assert ("roof_thickness", 200.0, "Пенополистирол (XPS/EPS)") in got  # 100+100 mm, two layers
    # concrete (λ 2,04) is never an insulation layer
    assert not any(v == 200.0 and m is None for _, v, m in got)


def test_thickness_needs_a_marker_and_skips_fire_protection_and_dimensions() -> None:
    assert not _facts("Утеплитель труб K-Flex толщиной 19 мм")  # no wall/roof marker: dropped
    assert not _facts("Кровля\n- Огнезащита плитами базальтового утеплителя - 40мм\n")
    assert not _facts("Стык стеновых панелей\nФасонный элемент Экструзионный пенополистирол А=310ММ\n")
    assert ("roof_thickness", 150.0, "Утеплитель (материал не указан)") in _facts(
        "Клинья 2,1%\nУтеплитель, 100+50 мм\nПароизоляция, 2,0 мм\n"
    )


def test_lambda_of_insulation_only_and_ro_of_windows() -> None:
    text = (
        "Наружные стены из газобетона, λБ1=0.15Вт/(м°С).\n"
        "Плиты минераловатные Rockwool, λА=0,038 Вт/(м°С), λБ=0,040 Вт/(м°С)\n"
        "Остекление – двухкамерный стеклопакет (3 стекла) (Ro=0,65(м² °С)/Вт);\n"
    )
    got = _facts(text)
    assert ("lambda", 0.038, "Минеральная вата / сэндвич-панель") in got
    assert ("lambda", 0.04, "Минеральная вата / сэндвич-панель") in got
    assert not any(k == "lambda" and v == 0.15 for k, v, _ in got)
    assert ("window_ro", 0.65, None) in got


def test_window_ro_ambiguous_passport_row_and_normative_are_skipped() -> None:
    assert not _facts("пр Rо,ок 1\n0.63\n0.69\nвитражей")  # normative + design: which one is unknown
    assert ("window_ro", 0.63, None) in _facts("пр Rо,ок 1 0.63 витражей")
    assert not _facts("Нормируемое приведенное сопротивление теплопередаче окон не менее 0,55 м²·°С/Вт")


def test_file_gate_and_page_scope() -> None:
    assert is_envelope_source(
        "ПД/10.1 Мероприятия по обеспечению соблюдения требований энергетической эффективности/x.pdf"
    )
    assert is_envelope_source("Проектная документация/3. Раздел 3 ЖС-РД-270121-П-АР.pdf")
    assert is_envelope_source("Рабочая документация/РД-2025-04-266-АР1.pdf")
    assert not is_envelope_source("ПД/5.4 Отопление/Том 5.4.1.pdf")
    # outside a ЭЭ/АР/КР file only the class is read
    text = "Класс энергетической эффективности С (нормальный). Плиты минераловатные λ=0,041 Вт/(м°С)"
    assert _facts(text, envelope=False) == {("class", "C", None)}


def test_values_carry_param_code_rank_and_material_location() -> None:
    sink = ValueSink("F0001", "OBJ-X", "0" * 64, "PD")
    facts = facts_from_text(
        "Здание класса энергетической эффективности В (высокий).\nКровля\nУтеплитель, 100+50 мм\n"
        "Плиты минераловатные λ=0,041 Вт/(м°С) - 100 мм",
        envelope=True,
    )
    from_energy(sink, 7, facts, "TEXT")
    by_key = {v["fact_key"]: v for v in sink.values}
    cls = by_key["ee.class"]
    assert cls["param_code"] == "ZU-124" and cls["value_norm"]["rank"] == CLASS_RANK["B"]
    assert cls["location"] == "OBJECT" and cls["page_no"] == 7
    thick = by_key["ee.roof_insulation_thickness"]
    assert thick["param_code"] == "ZU-128" and thick["value_norm"]["unit"] == "мм"
    assert thick["location_type"] == "ELEMENT" and thick["location"]
    lam = by_key["ee.insulation_lambda"]
    assert lam["param_code"] == "ZU-126" and lam["value_norm"]["unit"] == "Вт/(м·°С)"
