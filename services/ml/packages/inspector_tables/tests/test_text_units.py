"""Fast unit tests of the text primitives (no data)."""

from __future__ import annotations

import pytest

from inspector_tables.airx import norm_tag, split_tags
from inspector_tables.aosr import doc_refs
from inspector_tables.registry import split_no_date
from inspector_tables.text import (
    Word,
    fold,
    join_lines,
    join_words,
    norm_unit,
    parse_number,
    resplit_glued,
)
from inspector_tables.values import room_key


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("8.6", 8.6),
        ("10,2", 10.2),
        ("1 079,9", 1079.9),
        ("17 140,2", 17140.2),
        ("4168,9", 4168.9),
        ("281.60", 281.6),
        ("−12", -12.0),
        ("12.", 12.0),
        ("ИТОГО:", None),
        ("0,14/1 401", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_number_russian_forms(raw, value) -> None:
    assert parse_number(raw) == value


@pytest.mark.parametrize(
    ("raw", "unit"),
    [
        ("кв. м", "м²"),
        ("м2", "м²"),
        ("кв. м.", "м²"),
        ("куб. м", "м³"),
        ("м", "м"),
        ("эт.", "эт."),
        ("шт", "шт."),
        ("компл.", "компл."),
        ("Га", "га"),
        ("что-то", None),
    ],
)
def test_norm_unit(raw, unit) -> None:
    assert norm_unit(raw) == unit


def test_fold_joins_soft_hyphens_and_folds_lookalikes() -> None:
    assert fold("Номер поме- щения") == "номер помещения"
    assert fold("№ п/п") == "№ п п"
    assert fold("Кат. пом.") == "кат пом"
    assert fold("B4") == "в4"  # Latin look-alike → Cyrillic (matching only, never output)


def test_join_words_glues_split_glyph_runs_but_not_numbers() -> None:
    a = Word("Тамбур", 0, 0, 30, 10)
    b = Word("-шлюз", 30.5, 0, 55, 10)
    assert join_words([a, b]) == "Тамбур-шлюз"
    n1, n2 = Word("17", 0, 0, 10, 10), Word("140,2", 10.5, 0, 35, 10)
    assert join_words([n1, n2]) == "17 140,2"  # thousands group: a space, so parse_number re-joins


def test_join_lines_soft_hyphen_uses_the_lexicon() -> None:
    assert join_lines("с насад-", "кой") == "с насадкой"
    assert join_lines("биолого-", "химического") == "биолого-химического"
    assert join_lines("Вестибюль, в", "том числе:") == "Вестибюль, в том числе:"


def test_resplit_glued_splits_only_unknown_tokens() -> None:
    assert resplit_glued("Обеденныйзал") == "Обеденный зал"
    assert resplit_glued("Помещение оборудованиялифтов") == "Помещение оборудования лифтов"
    for word in ("Раздоточная", "Электрощитовая", "Лаборантская", "Артистическая-раздевальная"):
        assert resplit_glued(word) == word  # typos and known words are never split


def test_long_glued_runs_are_segmented_only_into_known_words() -> None:
    from inspector_tables.text import segment_glued

    assert segment_glued("Залдляпроведенияобщешкольныхмероприятий(на200мест)") == (
        "Зал для проведения общешкольных мероприятий (на 200 мест)"
    )
    for word in ("Специализированный", "трансформируемыми", "Лабораторно-исследовательский", "Раздоточная"):
        assert segment_glued(word) == word


def test_room_key_drops_surplus_leading_zeros() -> None:
    assert room_key("0012") == "012"
    assert room_key("012") == "012"
    assert room_key("001.1") == "001.1"
    assert room_key("140") == "140"


def test_system_tags() -> None:
    assert [norm_tag(t) for t in ("BE", "ПЗ", "B2.10", "N6", "П17.1")] == ["ВЕ", "П3", "В2.10", "П6", "П17.1"]
    assert norm_tag("16") is None and norm_tag("АБВ") is None
    assert split_tags("B2.7, B2.8, B2.9") == ["В2.7", "В2.8", "В2.9"]
    assert split_tags("В2.7,8,9") == ["В2.7", "В2.8", "В2.9"]
    assert split_tags("В2.4-В2.6") == ["В2.4", "В2.5", "В2.6"]
    assert split_tags("-") == []


def test_registry_number_and_date_split() -> None:
    assert split_no_date("№ 1А от 17.02.2026") == ("1А", "2026-02-17")
    assert split_no_date("№18-000001869 от 10.02.2026") == ("18-000001869", "2026-02-10")


def test_act_document_references() -> None:
    refs = doc_refs(
        'АНО/150321/1-РД-ОВ1 - изм. 3 - Система общеобменной вентиляции, ООО "БРАТКОМ-ГРУПП"', "rd_refs"
    )
    assert refs == [{"code": "АНО/150321/1-РД-ОВ1", "revision": 3, "source": "rd_refs"}]
    assert (
        doc_refs("Исполнительные чертежи АНО1301211-Р-ОВ1 от 09.01.2025", "q")[0]["code"]
        == "АНО1301211-Р-ОВ1"
    )
    assert doc_refs('Исполнительная схема "в/о 1-2.8/А-1.Л" №1БТ', "q") == []  # axes are not a document code
