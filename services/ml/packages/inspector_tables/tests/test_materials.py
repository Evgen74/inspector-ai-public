"""Structural materials from prose: family binding, «кроме» exclusion, F(I)/W marks, АОСР/ИД pages, file gate,
and the tables worker surviving damaged PDFs and rotated pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from inspector_tables.materials import (
    facts_from_act,
    facts_from_id_page,
    facts_from_text,
    family_of,
    is_structural,
)


def _facts(text: str) -> set[tuple[str, str, str]]:
    return {(f.kind, f.family, f.value) for f in facts_from_text(text)}


def test_rd_general_notes_bind_each_value_to_its_family() -> None:
    text = (
        "23. Конструкция форшахты из бетона класса B15 (F и W не регламентируются);\n"
        '«стена в грунте» из бетона класса B25, F200, W8; "Сваи-пустышки" (сваи\n'
        "первой очереди) выполняются из бетона класса В15, F200, W8; армированные\n"
        "сваи из бетона класса В25, F200, W8; обвязочный ж.б. пояс из бетона класса\n"
        "В25, F200, W8. Арматура класса А500С и класса А240 по ГОСТ 34028-2016."
    )
    got = _facts(text)
    assert ("concrete_class", "Форшахта", "B15") in got
    assert ("concrete_class", "Стена в грунте", "B25") in got
    assert {("concrete_class", "Сваи", "B15"), ("concrete_class", "Сваи", "B25")} <= got
    assert ("concrete_frost", "Сваи", "F200") in got and ("concrete_water", "Сваи", "W8") in got
    assert ("concrete_class", "Обвязочный пояс", "B25") in got
    assert not any(k == "concrete_frost" and fam == "Форшахта" for k, fam, _ in got)


def test_exclusion_and_thickness() -> None:
    text = (
        "4. Фундамент жилого дома предусмотрен в виде монолитной железобетонной плиты толщиной 1200 и 1500 мм. "
        "Под телом фундаментной плиты выполнена бетонная подготовка из бетона В10 толщиной 100 мм. "
        "5. Все несущие железобетонные конструкции нулевого цикла кроме фундаментной плиты выполнены из бетона "
        "класса В60 по прочности на сжатие."
    )
    got = _facts(text)
    assert ("thickness", "Фундаментная плита", "1200") in got and (
        "thickness",
        "Фундаментная плита",
        "1500",
    ) in got
    assert ("concrete_class", "Бетонная подготовка", "B10") in got
    assert not any(v == "B60" for _, _, v in got)  # «кроме фундаментной плиты» binds nothing
    assert not any(k == "thickness" and fam == "Бетонная подготовка" for k, fam, _ in got)


def test_preposition_v_and_foreign_numbers_are_not_classes() -> None:
    assert _facts("Сваи установлены в 15 рядов в 2025 году по оси В") == set()
    assert _facts("Сваи В15") == set()  # no concrete context and no F/W/П marks → not a class


def test_aosr_and_id_pages() -> None:
    assert family_of("Устройство неармированных свай БСС-1н в/о 4-2.8/А-Х1") == "Сваи"
    assert family_of("Бетонирование стены в грунте, захватка №8") == "Стена в грунте"
    facts = facts_from_id_page("Паспорт БСТ В15 П4 F150(I) W8; одна партия В15П4F(I)150W6", "Сваи", "1Н-БСС")
    got = {(f.kind, f.value) for f in facts}
    assert got == {
        ("concrete_class", "B15"),
        ("concrete_frost", "F150"),
        ("concrete_water", "W8"),
        ("concrete_water", "W6"),
    }
    assert all(f.act_no == "1Н-БСС" for f in facts)
    act = facts_from_act("Армирование фундаментной плиты", "арматура А500С d28, бетон B30 F150 W6")
    assert {(f.kind, f.family, f.value) for f in act} >= {
        ("rebar_class", "Фундаментная плита", "A500С"),
        ("concrete_class", "Фундаментная плита", "B30"),
    }


def test_structural_file_gate() -> None:
    assert is_structural("Стадия П/НВС-2025.03-4.1-КР1.pdf")
    assert is_structural("Стадия РД/НСЛ-17-02.2026-1_2-КЖ1.1.1.pdf")
    assert is_structural("Стадия РД/2025-12-23 Новослободская _СВГ (1).pdf")
    assert not is_structural("Стадия П/НВС-2025.03-3-АР.pdf")
    assert not is_structural("Стадия П/НВС-2025.03-ИОС4.1.pdf")


def _task(path: Path, stage: str, name: str):
    from inspector_tables.batch import EXTRA_KINDS, TABLE_TYPES, FileTask, TokenPlan

    return FileTask("F9901", "OBJ-TEST", str(path), "0" * 64, stage, name, stage, TokenPlan((), ()),
                    (*TABLE_TYPES, *EXTRA_KINDS))  # fmt: skip


def test_worker_survives_a_damaged_pdf(tmp_path: Path) -> None:
    from inspector_common.contracts.loader import validate
    from inspector_tables.batch import process_file

    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\n this is not a pdf \n%%EOF")
    res = process_file(_task(bad, "RD", "Стадия РД/КЖ1.pdf"))
    assert res["values"] == [] and res["artifact"]["warnings"] == ["FILE_CORRUPTED"]
    validate("table_artifacts", res["artifact"])


FONT = Path("/System/Library/Fonts/Supplemental/Arial.ttf")


@pytest.mark.skipif(not FONT.is_file(), reason="needs a Cyrillic TrueType font")
def test_rotated_page_text_layer_yields_material_facts(tmp_path: Path) -> None:
    import pymupdf

    from inspector_tables.batch import process_file

    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    page.insert_font(fontname="ar", fontfile=str(FONT))
    page.insert_text((60, 100), "Сваи из бетона класса В25, F200, W8.", fontname="ar", fontsize=11)
    page.set_rotation(270)
    path = tmp_path / "kj.pdf"
    doc.save(path)
    res = process_file(_task(path, "RD", "Стадия РД/НСЛ-КЖ1.1.1.pdf"))
    got = {
        (v["fact_key"], v["location"], v["value_raw"])
        for v in res["values"]
        if v["fact_key"].startswith("kr.")
    }
    assert ("kr.concrete_class", "Сваи", "B25") in got and ("kr.concrete_frost", "Сваи", "F200") in got
    kr055 = next(v for v in res["values"] if v["fact_key"] == "kr.concrete_class")
    assert kr055["param_code"] == "KR-055" and kr055["value_norm"]["rank"] == 25


def test_id_page_skips_values_of_other_families() -> None:
    text = "Плита фундаментная из бетона B30 F150 W6; стены из бетона класса B25 F150 W6"
    got = {(f.kind, f.value) for f in facts_from_id_page(text, "Фундаментная плита")}
    assert ("concrete_class", "B30") in got and ("concrete_class", "B25") not in got


def test_act_family_falls_back_to_the_works_phrase() -> None:
    from inspector_tables.materials import act_family, is_act_page

    ocr = "АКТ освидетельствования скрытых работ № 12 1. К освидетельствованию предъявлены следующие работы: бетонирование стены в грунте захв. 3"
    assert is_act_page(ocr)
    assert act_family(ocr, None) == "Стена в грунте"
    assert act_family(ocr, "Устройство форшахты") == "Форшахта"
