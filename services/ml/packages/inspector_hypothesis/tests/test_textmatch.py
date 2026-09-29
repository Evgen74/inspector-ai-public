"""Anchor phrases, room lists, Russian numbers and document-code keys."""

from __future__ import annotations

import pytest

from inspector_hypothesis.textmatch import (
    PhraseMatcher,
    clean_room_token,
    code_key,
    code_stage_hint,
    document_codes,
    fmt_number,
    is_negated,
    parse_number,
    room_lists,
    sentences,
)


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("предусмотрена система подогрева полов (теплые полы) совмещенная", "тёплый пол"),
        ("Регулятор для систы “теплый пол” Multibox C/RTL", "тёплый пол"),
        ("контур тёплого пола в санузле", "контур тёплого пола"),
        ("План 2 эт. отопл.", "Отопление"),
        ("ИТП", "ИТП"),
    ],
)
def test_anchor_phrases_match_real_wordings(text, phrase):
    m = PhraseMatcher(["тёплый пол", "контур тёплого пола", "Multibox", "Отопление", "ИТП"])
    assert phrase in [h.phrase for h in m.search_text(text)]


@pytest.mark.parametrize("text", ["теплоснабжения полов", "ИТП-1", "полотенцесушитель тёплый"])
def test_anchor_phrases_do_not_overmatch(text):
    m = PhraseMatcher(["тёплый пол", "ИТП"])
    assert m.search_text(text) == []


def test_room_lists_keep_printed_tokens_and_expand_short_ranges():
    lists = room_lists("В помещениях для МГН (пом. 267, 270, 271, 272) предусмотрена система")
    assert [t for _, _, t in lists] == [["267", "270", "271", "272"]]
    got = [t for _, _, t in room_lists("в помещении № 012 и пом. 1.109; помещения 101–105 и 107")]
    assert got == [["012"], ["1.109"], ["101", "102", "103", "104", "105", "107"]]


def test_document_numbers_are_not_room_lists():
    assert room_lists("Постановление правительства РФ от 16 февраля 2008 г. №87 «О составе разделов»") == []
    assert [t for _, _, t in room_lists("в помещении № 012")] == [["012"]]


def test_clean_room_token():
    assert clean_room_token("270,") == "270"
    assert clean_room_token("“012”") == "012"
    assert clean_room_token("Т11") is None


def test_sentences_do_not_split_room_abbreviations():
    text = "Все приборы. В помещениях (пом. 267, 270) предусмотрены теплые полы. Регулирование"
    spans = [text[a:b] for a, b in sentences(text)]
    assert spans[1] == "В помещениях (пом. 267, 270) предусмотрены теплые полы."


def test_negation():
    assert is_negated("Тёплые полы не предусмотрены")
    assert is_negated("тёплый пол отсутствует")
    assert not is_negated("предусмотрена система подогрева полов")


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("2797,27", 2797.27),
        ("1 079,9", 1079.9),
        ("1 079,9", 1079.9),
        ("−5", -5.0),
        ("30.4 м²", 30.4),
        (12, 12.0),
    ],
)
def test_parse_number(raw, value):
    assert parse_number(raw) == pytest.approx(value)


@pytest.mark.parametrize("raw", ["abc", "1-2", None, True, "12,3,4"])
def test_parse_number_rejects(raw):
    assert parse_number(raw) is None


def test_fmt_number():
    assert fmt_number(2797.27, 2) == "2797,27"
    assert fmt_number(30.4) == "30,4"
    assert fmt_number(-1.5, 1) == "−1,5"
    assert fmt_number(12.0) == "12"


def test_document_codes_keys_revisions_and_stage():
    refs = document_codes("АНО/150321/1-РД-ОВ2.1 - изм. 3, Исполнительные чертежи АНО1301211-Р-ОВ1")
    assert [(r.raw, r.revision, r.stage_hint) for r in refs] == [
        ("АНО/150321/1-РД-ОВ2.1", 3, "RD"),
        ("АНО1301211-Р-ОВ1", None, "RD"),
    ]
    # separators, stage «РД»/«Р» and Latin look-alikes do not change the key
    assert code_key("АНО-150321-1-РД-ОВ1") == code_key("АНO/150321/1-P-ОВ1 изм. 4") == "АНО1503211РОВ1"
    assert code_key("АНО1301211-Р-ОВ1") != code_key("АНО-150321-1-РД-ОВ1")
    assert code_stage_hint("АНО/150321/1-П-ИОС4") == "PD"
