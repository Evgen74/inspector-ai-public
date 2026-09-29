"""ИГС scheme facts (tolerance notes + signed deviation annotations) on synthetic pages built from the pilot
OKT103 description (04 §3.4: «Допуски на листе: 15 мм, ±12 мм и 20 мм. Факт: +491/+552, +980/+537 и
+201/+349 мм»)."""

from __future__ import annotations

from inspector_common.contracts.loader import validate
from inspector_tables import igs
from inspector_tables.pagesource import PageData
from inspector_tables.text import Word
from inspector_tables.values import ValueSink, from_igs


def _page(items: list[tuple[float, float, str]], width: float = 1191, height: float = 842) -> PageData:
    """(x, y, line text) → words of 6 pt per character, one space between words."""
    words = []
    for x, y, text in items:
        cx = x
        for t in text.split():
            words.append(Word(t, cx, y, cx + 6 * len(t), y + 10, source="OCR", conf=0.93))
            cx += 6 * len(t) + 6
    return PageData("F9", 7, width, height, words, text_source="OCR", from_tokens=True)


PILOT = [
    (40, 40, "Исполнительная геодезическая схема колонн в осях 1-5/А-Г на отм. +3.300"),
    (60, 200, "+491/+552"),
    (400, 200, "+980/+537"),
    (700, 200, "+201/+349"),
    (60, 700, "Допуски на листе: 15 мм, ±12 мм и 20 мм."),
    (60, 720, "Работы выполнять при температуре не ниже -15 °С"),
    (900, 800, "Изм. Кол.уч Лист №док. Подп. Дата 12.05.26"),
]


def test_tolerance_line_grammar() -> None:
    assert igs.tolerances_of_line("Допуски на листе: 15 мм, ±12 мм и 20 мм.") == [
        (15.0, "15 мм", None),
        (12.0, "±12 мм", None),
        (20.0, "20 мм", None),
    ]
    assert igs.tolerances_of_line(
        "Допускаемое отклонение смещения осей колонн ±8 мм (СП 70.13330.2012, табл. 5.10)"
    ) == [(8.0, "±8 мм", "PLAN")]
    assert igs.tolerances_of_line("Предельные отклонения отметок верха плиты +/-10мм")[0][2] == "ELEVATION"
    assert igs.tolerances_of_line("Допустимое отклонение по толщине стен 5 мм")[0][2] == "THICKNESS"
    # no unit and no ± → not a tolerance; a licence «допуск» with a date → nothing
    assert igs.tolerances_of_line("Свидетельство о допуске к работам № 0123-2019 от 12.03.2015") == []
    assert igs.tolerances_of_line("Допуск по табл. 5") == []


def test_deviation_token_grammar() -> None:
    assert igs.deviation_of_token("+491/+552") == [(491.0, "+491/+552", "x"), (552.0, "+491/+552", "y")]
    assert igs.deviation_of_token("−8") == [(-8.0, "−8", None)]
    assert igs.deviation_of_token("+224мм") == [(224.0, "+224мм", None)]
    for not_dev in ("+158.850", "-1.05", "10.02.26", "491", "+9999", "+5°", "Ф620"):
        assert igs.deviation_of_token(not_dev) == [], not_dev


def test_scheme_detection() -> None:
    assert igs.is_scheme("Исполнительнаясхемаармированной ООО МегаСтрой")  # glued OCR words
    assert igs.is_scheme("Исполнительная геодезическая схема монолитной плиты")
    assert igs.is_scheme("Исполнительная схема №3. Приложение к акту освидетельствования скрытых работ №12")
    act = "АКТ освидетельствования скрытых работ. Предъявлены к освидетельствованию работы. Исполнительная схема №3"
    assert not igs.is_scheme(act)
    assert not igs.is_scheme("Пояснительная записка. Допуск 10 мм")


def test_pilot_page_facts_and_values() -> None:
    page = _page(PILOT)
    r = igs.parse_page(page)
    assert r is not None
    assert sorted(t.value for t in r.tolerances) == [12.0, 15.0, 20.0]
    assert sorted(d.value for d in r.deviations) == [201.0, 349.0, 491.0, 537.0, 552.0, 980.0]  # not −15 °С
    assert r.element_kind == "COLUMN"
    assert r.axes == "1-5/А-Г"
    sink = ValueSink("F9", "OBJ-X", "0" * 64, "ID")
    from_igs(sink, r, lambda pg, box: page.norm_bbox(box), "OCR")
    for v in sink.values:
        validate("extracted_value", v)
    keys = [(v["fact_key"], v["value_norm"]["value"]) for v in sink.values]
    assert ("id.tolerance", 20) in keys and ("id.deviation", 980) in keys
    assert all(v["value_norm"]["qualifiers"]["source"] == "IGS_ANNOTATION" for v in sink.values)
    assert all(v["page_no"] == 7 and v["stage"] == "ID" and v.get("geometry") for v in sink.values)


def test_scheme_without_tolerance_yields_nothing() -> None:
    # the Новослободская форшахта scheme: deviations printed, no допуск on the sheet → no facts (abstain)
    page = _page(
        [
            (40, 40, "Исполнительная схема №1Б Бетонирование форшахты"),
            (60, 200, "+224 +227 +571 -142"),
            (60, 700, "– фактическое отклонение в плане относительно проекта, в (мм);"),
        ]
    )
    assert igs.parse_page(page) is None


def test_non_scheme_page_is_ignored() -> None:
    page = _page([(40, 40, "Протокол испытаний бетона"), (60, 100, "Допуск 10 мм"), (60, 200, "+50 +60")])
    assert igs.parse_page(page) is None
