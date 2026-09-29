"""Typed parsers on SYNTHETIC ruled tables drawn with PyMuPDF (no organizer data): the structure rules that
the real pages exercise — side-by-side parts sharing a border, merged section rows, «в том числе» sub-zones
and their double count, ТЭП hierarchy and units, change-register permit, registry blocks and continuation."""

from __future__ import annotations

import pymupdf

from inspector_common.contracts.loader import validate
from inspector_common.contracts.models import TableArtifacts
from inspector_tables import artifacts, changelog, explication, registry, spec21110, tep
from inspector_tables.evaluate import compare, explication_keys
from inspector_tables.pagesource import PageSource, page_from_pdf
from inspector_tables.testing import draw_table, write_text

EXPL_HEADER = ["Номер\nпоме-\nщения", "Наименование", "Площадь,\nм2", "Кат.\nпом."]
W = [40, 200, 45, 40]


def _explication_page(new_pdf):
    doc, page = new_pdf(842, 595)
    write_text(page, 60, 60, "Экспликация помещений 1 этажа", 12)
    left = [
        EXPL_HEADER,
        ["Группа начальных классов"],
        ["101", "Тамбур", "8.6", ""],
        ["102", "Вестибюль, в том числе:", "134.0", ""],
        ["", "зона ожидания", "30.4", ""],
        ["103", "Санузел", "5.0", "В4"],
        ["", "ИТОГО:", "178.0", ""],
        ["Прочие помещения"],
        ["104", "Коридор", "20,5", ""],
    ]
    right = [
        EXPL_HEADER,
        ["105", "Лестница", "10.5", ""],
        ["", "ИТОГО:", "31.0", ""],
        ["", "ИТОГО 1-ый этаж:", "178.6", ""],
    ]
    draw_table(page, 50, 70, W, [36] + [16] * (len(left) - 1), left, merged=(1, 7))
    draw_table(page, 50 + sum(W), 70, W, [36] + [16] * (len(right) - 1), right)
    return doc, page


def test_side_by_side_explication_with_subzone_double_count(new_pdf) -> None:
    _doc, page = _explication_page(new_pdf)
    pd = page_from_pdf(page, "F9001", 1)
    les = explication.parse_page(pd)
    assert len(les) == 1 and len(les[0].parts) == 2  # one logical table across two parts sharing a border
    le = les[0]
    keys = explication_keys(le.rows)
    expected = [
        ("SECTION_HEADER", None, "Группа начальных классов", None, None),
        ("DATA", "101", "Тамбур", 8.6, None),
        ("DATA", "102", "Вестибюль, в том числе:", 134.0, None),
        ("SUBZONE", None, "зона ожидания", 30.4, None),
        ("DATA", "103", "Санузел", 5.0, "В4"),
        ("TOTAL", None, "ИТОГО:", 178.0, None),
        ("SECTION_HEADER", None, "Прочие помещения", None, None),
        ("DATA", "104", "Коридор", 20.5, None),
        ("DATA", "105", "Лестница", 10.5, None),
        ("TOTAL", None, "ИТОГО:", 31.0, None),
        ("TOTAL", None, "ИТОГО 1-ый этаж:", 178.6, None),
    ]
    assert compare(keys, expected).exact == len(expected)
    kinds = [(c["kind"], c["passed"]) for c in le.checks]
    # 178.0 = 147.6 + 30.4: the sub-zone is counted twice; group 2 matches; the grand total is 147.6 + 31.0
    assert kinds == [
        ("SUBZONE_DOUBLE_COUNT", False),
        ("SUM_MATCHES_TOTAL", True),
        ("SUM_MATCHES_TOTAL", True),
    ]
    dc = le.checks[0]
    assert dc["expected"] == 147.6 and dc["actual"] == 178.0
    sub = next(r for r in le.rows if r.kind == "SUBZONE")
    assert le.rows[sub.parent].room_no == "102"
    t = artifacts.explication_table(le, "F9001", 1)
    doc_json = artifacts.table_artifacts(
        "F9001", "OBJ-SYNTH", "0" * 64, "RD", [t], generated_at="2026-09-28T00:00:00Z"
    )
    validate("table_artifacts", doc_json)
    TableArtifacts.model_validate(doc_json)
    row = t["rows"][1]
    assert row["cells"]["room_no"]["raw"] == "101" and row["cells"]["area_m2"]["value"] == 8.6
    assert all(0.0 <= v <= 1.0 for v in row["cells"]["area_m2"]["bbox"])


def test_tep_hierarchy_units_and_sums(new_pdf) -> None:
    _doc, page = new_pdf(595, 842)
    write_text(page, 60, 60, "Технико-экономические показатели", 11)
    rows = [
        ["№ п/п", "Наименование", "Ед. изм.", "Показатель\nпо ГПЗУ", "Показатель\nпо ПД"],
        ["1", "Площадь застройки, в т.ч.:", "кв. м", "", "1225,8"],
        ["1.1", "Площадь застройки наземной части", "кв. м", "", "767,0"],
        ["1.2", "Площадь застройки подземной части", "кв. м", "", "458,8"],
        ["2", "Строительный объем, в т.ч.:", "кв. м.", "", "69 201,0"],
        ["", "подземная часть", "куб. м", "", "16 454,6"],
        ["", "наземная часть", "куб. м", "", "52 731,4"],
        ["3", "Высота здания", "м", "75", "74,5"],
    ]
    draw_table(page, 40, 80, [30, 230, 50, 70, 70], [30] + [16] * (len(rows) - 1), rows)
    lts = tep.parse_page(page_from_pdf(page, "F9002", 1))
    assert len(lts) == 1
    lt = lts[0]
    data = [(r.kind, r.row_no, r.value, r.param_code) for r in lt.rows]
    assert data == [
        ("DATA", "1", 1225.8, "PZ-001"),
        ("SUBZONE", "1.1", 767.0, None),  # a component never inherits its parent's parameter
        ("SUBZONE", "1.2", 458.8, None),
        ("DATA", "2", 69201.0, "PZ-004"),
        ("SUBZONE", None, 16454.6, "PZ-005"),
        ("SUBZONE", None, 52731.4, "PZ-006"),
        ("DATA", "3", 74.5, "PZ-008"),
    ]
    assert lt.rows[-1].limit == 75.0
    checks = {(c["kind"], c["detail"].split("»")[0]): c["passed"] for c in lt.checks}
    assert checks[("SUM_MATCHES_TOTAL", "«Площадь застройки, в т.ч.:")] is True
    assert checks[("SUM_MATCHES_TOTAL", "«Строительный объем, в т.ч.:")] is False  # 69 186,0 ≠ 69 201,0
    assert checks[("UNIT_CONSISTENT", "«Строительный объем, в т.ч.:")] is False  # «кв. м.» for a volume
    t = artifacts.tep_table(lt, "F9002", 1)
    validate(
        "table_artifacts",
        artifacts.table_artifacts(
            "F9002", "OBJ-SYNTH", "0" * 64, "PD", [t], generated_at="2026-09-28T00:00:00Z"
        ),
    )
    assert {c["key"] for c in t["columns"]} == {"indicator", "unit", "value", "note"}  # «№ п/п» is internal


def test_change_register_from_a_permit(new_pdf) -> None:
    _doc, page = new_pdf(595, 842)
    draw_table(
        page,
        40,
        40,
        [80, 120, 300],
        [18, 18],
        [["Разрешение", "Обозначение", "АБВ/123/1-РД-ОВ1"], ["839-24", "", ""]],
    )
    rows = [
        ["Изм.", "Лист", "Содержание изменения", "Код", "Примечание"],
        ["4", "1", "Заменен. Внесены данные в ведомость", "5", ""],
        ["4", "10", "Заменен. В пом. 195 добавлены системы К6.1", "5", "-//-"],
        ["Изм. внес", "Иванов", "08.24", "", ""],
    ]
    draw_table(page, 40, 90, [35, 35, 300, 30, 100], [20, 18, 18, 18], rows)
    lgs = changelog.parse_page(page_from_pdf(page, "F9003", 1))
    assert len(lgs) == 1
    lg = lgs[0]
    assert lg.permit_no == "839-24" and lg.document_code == "АБВ/123/1-РД-ОВ1"
    assert [(r.cells["change_no"], r.cells["sheets_changed"], r.cells["doc_no"]) for r in lg.rows] == [
        ("4", "1", "839-24"),
        ("4", "10", "839-24"),
    ]
    assert (
        lg.rows[1].cells["note"].startswith("Заменен. В пом. 195") and "[код 5]" in lg.rows[1].cells["note"]
    )
    t = artifacts.changelog_table(lg, "F9003", 1)
    validate(
        "table_artifacts",
        artifacts.table_artifacts(
            "F9003", "OBJ-SYNTH", "0" * 64, "RD", [t], generated_at="2026-09-28T00:00:00Z"
        ),
    )


def test_title_block_is_not_a_change_register(new_pdf) -> None:
    _doc, page = new_pdf(595, 842)
    stamp = [["Изм.", "Кол.уч", "Лист", "№ док.", "Подп.", "Дата"], ["", "", "", "", "", ""]]
    draw_table(page, 40, 700, [30, 30, 30, 40, 40, 30], [14, 14], stamp)
    assert changelog.parse_page(page_from_pdf(page, "F9004", 1)) == []


def test_registry_sections_and_continuation_page(tmp_path, new_pdf) -> None:
    doc = pymupdf.open()
    widths = [40, 200, 150, 120]
    p1 = doc.new_page(width=595, height=842)
    write_text(p1, 60, 60, "Реестр приложений №1 к акту АОСР №1А от «24» февраля 2026", 10)
    draw_table(
        p1,
        40,
        70,
        widths,
        [30, 14],
        [
            [
                "№ п/п",
                "Наименование документа",
                "№ чертежа, акта, разрешения",
                "Организация, составившая документ",
            ],
            ["1", "2", "3", "4"],
        ],
    )
    write_text(p1, 200, 140, "Исполнительные геодезические схемы", 10)
    draw_table(
        p1, 40, 150, widths, [16], [["1", "Исполнительная схема", "№ 1А от 17.02.2026", 'ООО "МЕГАСТРОЙ"']]
    )
    write_text(p1, 200, 200, "Документы, подтверждающие качество", 10)
    draw_table(p1, 40, 210, widths, [16, 28], [["1", "Документ о качестве", "№004301 от 19.01.2026", 'ООО "АРМИКОН"'],
                                                ["2", "Документ о качестве бетонной\nсмеси партии", "№18-01 от 10.02.2026", 'ООО "Бетолюкс"']])  # fmt: skip
    p2 = doc.new_page(width=595, height=842)
    draw_table(p2, 40, 40, widths, [16], [["", "БСТ В25 П4F(I)200W8", "", ""]])
    path = tmp_path / "reg.pdf"
    doc.save(path)
    d = pymupdf.open(path)
    src = PageSource(d, "F9005")
    regs = registry.parse_page(src.page(1))
    assert len(regs) == 1
    registry.parse_page(src.page(2), regs[0])
    reg = regs[0]
    registry.finalize(reg)
    data = [r for r in reg.rows if r.kind == "DATA"]
    assert [(r.cells["row_no"], r.doc_no, r.doc_date) for r in data] == [
        ("1", "1А", "2026-02-17"),
        ("1", "004301", "2026-01-19"),
        ("2", "18-01", "2026-02-10"),
    ]
    assert data[-1].cells["doc_name"].endswith("БСТ В25 П4F(I)200W8")  # continued on the next page
    assert [r.cells["doc_name"] for r in reg.rows if r.kind == "SECTION_HEADER"] == [
        "Исполнительные геодезические схемы",
        "Документы, подтверждающие качество",
    ]
    assert sorted({p.page_no for p in reg.parts}) == [1, 2]
    t = artifacts.registry_table(reg, "F9005", 1)
    validate(
        "table_artifacts",
        artifacts.table_artifacts(
            "F9005", "OBJ-SYNTH", "0" * 64, "ID", [t], generated_at="2026-09-28T00:00:00Z"
        ),
    )


def test_spec_items_span_rows_and_sections(new_pdf) -> None:
    _doc, page = new_pdf(842, 595)
    rows = [
        [
            "Позиция",
            "Наименование и техническая характеристика",
            "Тип, марка",
            "Код",
            "Завод-\nизготовитель",
            "Единица\nизмерения",
            "Коли-\nчество",
            "Масса",
            "Примечание",
        ],
        ["", "^ОБОРУДОВАНИЕ", "", "", "", "", "", "", ""],
        ["П1", "Приточная установка в комплекте", "V1.40", "", "KORF", "компл.", "1", "", ""],
        ["", "воздухонагревателя, см. подборку", "", "", "", "", "", "", ""],
        ["", "Кран шаровый латунный с насад-", "", "", "", "", "", "", ""],
        ["", "кой для шланга, Ø15", "BVR-C", "", "-//-", "шт", "86", "", ""],
    ]
    draw_table(page, 30, 40, [40, 250, 80, 40, 80, 50, 50, 40, 60], [30] + [16] * (len(rows) - 1), rows)
    lss = spec21110.parse_page(page_from_pdf(page, "F9006", 1))
    assert len(lss) == 1
    assert next((i.kind, i.cells["name"]) for i in lss[0].items) == ("SECTION_HEADER", "ОБОРУДОВАНИЕ")
    data = [i for i in lss[0].items if i.kind == "DATA"]
    assert [(i.cells.get("position"), i.cells["name"], i.quantity) for i in data] == [
        ("П1", "Приточная установка в комплекте воздухонагревателя, см. подборку", 1.0),
        ("", "Кран шаровый латунный с насадкой для шланга, Ø15", 86.0),
    ]


def test_deviation_table_tolerance_and_values(new_pdf) -> None:
    from inspector_tables import deviation
    from inspector_tables.values import ValueSink, from_table

    _doc, page = new_pdf(842, 595)
    write_text(page, 60, 50, "Ведомость отклонений (синтетическая)", 11)
    rows = [
        [
            "№ п/п",
            "Конструкция",
            "Оси",
            "Параметр",
            "Проектное\nзначение",
            "Фактическое\nзначение",
            "Отклонение",
            "Допуск",
            "Ед. изм.",
        ],
        ["1", "Стена", "1-2/А", "Отметка верха", "159,50", "159,508", "+8", "±10", "мм"],
        ["2", "Стена", "2-3/А", "Толщина", "600", "585", "-15", "+5/-10", "мм"],
    ]
    draw_table(page, 30, 60, [30, 90, 50, 110, 70, 70, 70, 60, 40], [30, 16, 16], rows)
    lds = deviation.parse_page(page_from_pdf(page, "F9007", 1))
    assert len(lds) == 1
    r1, r2 = lds[0].rows
    assert (r1.within, r2.within) == (True, False)  # −15 is outside +5/−10
    assert r2.computed == -15.0 and r2.consistent is True
    assert deviation.parse_tolerance("±10") == (-10.0, 10.0) and deviation.parse_tolerance("+5/−10") == (
        -10.0,
        5.0,
    )
    t, evals = artifacts.deviation_table(lds[0], "F9007", 1)
    validate(
        "table_artifacts",
        artifacts.table_artifacts(
            "F9007", "OBJ-SYNTH", "0" * 64, "ID", [t], generated_at="2026-09-28T00:00:00Z"
        ),
    )
    sink = ValueSink("F9007", "OBJ-SYNTH", "0" * 64, "ID")
    from_table(sink, t, None, evals)
    for v in sink.values:
        validate("extracted_value", v)
    assert [v["value_norm"]["qualifiers"]["within_tolerance"] for v in sink.values] == [True, False]
    assert sink.values[0]["location_type"] == "AXES" and sink.values[0]["location"] == "1-2/А"
