from __future__ import annotations

import unicodedata

import pytest

from inspector_registry.names import (
    clean_name,
    decode_member_name,
    match_key,
    member_path_problems,
    plausibility,
    safe_member_path,
    sheet_number,
    zip_raw_name,
)


def test_legacy_zip_name_is_decoded_cp437_to_cp866() -> None:
    stored = "Раздел КЖ/Лист 5.dwg".encode("cp866")
    as_zipfile_sees_it = stored.decode("cp437")  # what zipfile returns for a flag-less entry
    raw, utf8 = zip_raw_name(as_zipfile_sees_it, flag_bits=0)
    assert raw == stored and utf8 is False
    decoded = decode_member_name(raw, utf8_flag=utf8)
    assert decoded.name == "Раздел КЖ/Лист 5.dwg"
    assert decoded.encoding == "cp866"


def test_utf8_flag_wins() -> None:
    raw, utf8 = zip_raw_name("Имя.txt", flag_bits=0x800)
    assert utf8 is True
    assert decode_member_name(raw, utf8_flag=utf8).name == "Имя.txt"


def test_flagless_utf8_is_recognised() -> None:
    decoded = decode_member_name("План этажа.pdf".encode(), utf8_flag=False)
    assert decoded.name == "План этажа.pdf"
    assert decoded.encoding == "utf-8"


def test_cp866_bytes_that_are_valid_utf8_still_decode_as_cp866() -> None:
    # «сАБ» in cp866 is E1 80 81, which is also valid UTF-8 (U+1001, a Myanmar letter).
    raw = "сАБ.dwg".encode("cp866")
    assert raw.decode("utf-8") == "\u1001.dwg"
    decoded = decode_member_name(raw)
    assert decoded.name == "сАБ.dwg"
    assert decoded.encoding == "cp866"
    assert plausibility("сАБ") > plausibility("\u1001")


def test_ascii_and_unicode_inputs() -> None:
    assert decode_member_name(b"readme.txt").encoding == "ascii"
    assert decode_member_name("Лист.dwg").encoding == "unicode"


def test_bidi_and_format_characters_are_stripped_and_counted() -> None:
    decoded = decode_member_name("Папка\u202c/Лист\u200e 3.dwg")
    assert decoded.name == "Папка/Лист 3.dwg"
    assert decoded.raw == "Папка\u202c/Лист\u200e 3.dwg"
    assert decoded.format_chars_removed == 2


def test_clean_name_normalises_to_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "Изменённый.pdf")
    cleaned, removed = clean_name(nfd)
    assert cleaned == "Изменённый.pdf" and removed == 0


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("../evil.txt", "выход за пределы архива («..»)"),
        ("a/../../evil.txt", "выход за пределы архива («..»)"),
        ("/etc/passwd", "абсолютный путь"),
        ("C:\\Windows\\x.dll", "абсолютный путь"),
        ("\\\\server\\share\\x", "абсолютный путь"),
        ("bad\x01name.txt", "управляющие символы в имени"),
        ("   ", "пустое имя"),
    ],
)
def test_unsafe_member_paths(name: str, problem: str) -> None:
    assert problem in member_path_problems(name)


def test_safe_member_path_never_escapes() -> None:
    assert member_path_problems("КЖ1/Лист 1.dwg") == []
    assert safe_member_path("../../a/./b\\c.dwg") == "a/b/c.dwg"
    assert safe_member_path("/abs/x") == "abs/x"
    assert safe_member_path("C:\\x\\y") == "x/y"


@pytest.mark.parametrize(
    ("name", "number", "explicit"),
    [
        ("КЖ1 Лист 5.dwg", 5, True),
        ("ОБЪ-РД-АР л.12.dwg", 12, True),
        ("sheet 03.dwg", 3, True),
        ("АР_12 (1).dwg", 12, False),
        ("КЖ1-05.dwg", 5, False),
        ("Материал 3.dwg", 3, False),  # «л 3» inside a word is not «Лист 3»
    ],
)
def test_sheet_numbers(name: str, number: int, explicit: bool) -> None:
    sheet = sheet_number(name)
    assert sheet is not None
    assert (sheet.number, sheet.explicit) == (number, explicit)


def test_no_sheet_number() -> None:
    assert sheet_number("План подвала.dwg") is None


def test_match_key_unifies_homoglyphs_separators_and_extension() -> None:
    latin_k = "KЖ1_Лист-1.dwg"  # Latin K
    assert match_key(latin_k) == match_key("КЖ1 лист 1.pdf")
    assert match_key("Том\u202c 1.pdf") == "том 1"
