"""Document-code corrector (96 §7.2): the measured OCR outputs and their expected corrections."""

from __future__ import annotations

import pytest

from inspector_docproc.codefix import (
    dictionary_from_names,
    fix_code,
    fix_text,
    fold_mixed_script,
    homoglyph_key,
    is_code_like,
    post_correct,
    registry_match,
)

EXTRAS = dictionary_from_names(["АНО1503211-РД-ВК изм. 2_в1.pdf", "НВС-2025.03-1.2-ПЗ.pdf"])


@pytest.mark.parametrize(
    ("ocr", "expected"),
    [
        ("АН0/150321/1-П-И0C5.4.2", "АНО/150321/1-П-ИОС5.4.2"),
        ("AHO/150321/1-PД-OB1", "АНО/150321/1-РД-ОВ1"),
        ("АHO/150321/1-П3У-П3", "АНО/150321/1-ПЗУ-ПЗ"),
        ("АНО/150321/1-П-ВОР.И0С5.4.2", "АНО/150321/1-П-ВОР.ИОС5.4.2"),
        ("AH0/150321/1-П-АP", "АНО/150321/1-П-АР"),
        ("HBC-2025/03-KP", "НВС-2025/03-КР"),
        ("AHO/150321/1-PD-OB2.1", "АНО/150321/1-РД-ОВ2.1"),  # Д read as Latin D (F0202 p17 stamp)
        ("АНО/150321/1-PД-ОВ1", "АНО/150321/1-РД-ОВ1"),
        ("С-ДЭМ/20-02-2026/506367016", "С-ДЭМ/20-02-2026/506367016"),
    ],
)
def test_fix_code_measured_cases(ocr: str, expected: str) -> None:
    assert fix_text(ocr, EXTRAS) == expected


def test_p_for_pi_needs_the_registry_prior() -> None:
    """«ПЗ» read as «P3» is not fixable by rules (П → P is not a look-alike pair)…"""
    assert fix_text("HBC-2025/03-P3", EXTRAS) == "НВС-2025/03-Р3"
    # … but the registry prior finds the known code within distance 1
    assert registry_match("HBC-2025/03-P3", ["НВС-2025/03-ПЗ", "НВС-2025/03-КР"]) == "НВС-2025/03-ПЗ"
    assert registry_match("HBC-2025/03-P3", ["АНО/150321/1-РД-ОВ1"]) is None


def test_latin_segments_and_plain_words_are_untouched() -> None:
    assert fix_text("Д-RU.РА01.В.44924/25") == "Д-RU.РА01.В.44924/25"  # RU has no Cyrillic twin
    assert fix_text("HW-10KGV") == "HW-10KGV"  # one separator: not code-shaped
    # confusables (D → Д, N → П) only when the segment becomes a known abbreviation
    assert fix_text("AB-12/ND-DN") == "АВ-12/ND-DN"  # look-alike «AB» maps; «ND»/«DN» spell nothing known
    assert fix_text("СП-12/UDC-1") == "СП-12/UDC-1"
    assert fix_text("Школа на 600 мест") == "Школа на 600 мест"
    assert fix_text("кабель ВВГнг(А)-LS 3х2,5") == "кабель ВВГнг(А)-LS 3х2,5"


def test_is_code_like() -> None:
    assert is_code_like("АНО/150321/1-РД-ОВ1")
    assert not is_code_like("12-34")
    assert not is_code_like("ABC-DEF-GHI")  # no digits


def test_dictionary_from_names() -> None:
    assert {"АНО", "РД", "ВК", "НВС", "ПЗ"} <= EXTRAS
    assert "изм" not in EXTRAS


def test_homoglyph_key_folds_variants() -> None:
    assert homoglyph_key("AHO/150321/1-PД-OB1") == homoglyph_key("АНО/150321/1-РД-ОВ1")
    assert fix_code("ОВ1") == "ОВ1"


@pytest.mark.parametrize(
    ("ocr", "expected"),
    [
        ("PД", "РД"),  # stage cell of an outlined title block (F0202 p17)
        ("TCП", "ТСП"),
        ("BД1", "ВД1"),  # vent system tags on the gold RD plans
        ("П1/BЕ", "П1/ВЕ"),
        ("cут", "сут"),
        ("ВВГнг(А)-LS", "ВВГнг(А)-LS"),  # L, S have no Cyrillic twin: a genuine Latin part
        ("В15П4F(I)150W6", "В15П4F(I)150W6"),
        ("AMP-K", "AMP-K"),  # all-Latin tokens are ambiguous and stay as read
        ("EI30", "EI30"),
        ("350x300", "350x300"),
    ],
)
def test_fold_mixed_script(ocr: str, expected: str) -> None:
    assert fold_mixed_script(ocr) == expected


def test_post_correct_reports_what_changed() -> None:
    assert post_correct("AHO/150321/1-PД-OB1", EXTRAS) == ("АНО/150321/1-РД-ОВ1", "code_corrector")
    assert post_correct("Стадия PД", EXTRAS) == ("Стадия РД", "homoglyph_fold")
    assert post_correct("Школа на 600 мест", EXTRAS) == ("Школа на 600 мест", None)
    assert post_correct("PД", EXTRAS, fold=False) == ("PД", None)


# ── Line/page script context (M1, GT v2 conventions) ─────────────────────────────────────────


def _line(words: list[str], page: str | None = "cyr") -> list[str]:
    from inspector_docproc.codefix import post_correct_line
    from inspector_docproc.lexicon import load_lexicon, load_wordfreq

    return [
        t for t, _ in post_correct_line(words, page=page, lexicon=load_lexicon().words, freq=load_wordfreq())
    ]


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        # measured D01/D02 outputs (outlined italic ГОСТ type B text) and their GT v2 lines
        (
            ["Cm4,", "Cm10,", "Cm18,", "noм.", "154", "(Cm7)"],
            ["Ст4,", "Ст10,", "Ст18,", "пом.", "154", "(Ст7)"],
        ),
        (["nom.", "114", "(Cm5),"], ["пом.", "114", "(Ст5),"]),
        (["Pacxog"], ["Расход"]),
        (["Tun,", "uc-"], ["Тип,", "ис-"]),
        (["N=0,5", "kBm)"], ["N=0,5", "кВт)"]),  # «N» (power) stays Latin, one hard letter is no line context
        (["Om", "Cm21/"], ["От", "Ст21/"]),
        (["T11=+85", "C"], ["Т11=+85", "С"]),  # homoglyph-only words follow the page
        (["И3м."], ["Изм."]),
        (["000", "«ТСП»"], ["ООО", "«ТСП»"]),
        (["RA-N", "угловой", "φ15"], ["RA-N", "угловой", "Ø15"]),
        (["ф16х2,2"], ["Ø16х2,2"]),
        (["Ф1"], ["Ф1"]),  # foundation mark, not a diameter
        # Latin stays Latin
        (["HW-10KGV,", "SBOW", "EI30", "DN15"], ["HW-10KGV,", "SBOW", "EI30", "DN15"]),
        (["НW-10КGV,"], ["HW-10KGV,"]),  # Cyrillic twins inside a Latin word
        (["mm", "cm", "kg"], ["mm", "cm", "kg"]),  # Latin units
        (
            ["Сертификат", "7A0173FCDCDB1B04E1ACBC8019D", "19C7"],
            ["Сертификат", "7A0173FCDCDB1B04E1ACBC8019D", "19C7"],
        ),
        (["Действителен", "с", "23.03.2026"], ["Действителен", "с", "23.03.2026"]),
    ],
)
def test_script_context(words: list[str], expected: list[str]) -> None:
    assert _line(words) == expected


def test_script_context_needs_a_context() -> None:
    assert _line(["T11", "C"], page=None) == ["T11", "C"]  # no line or page script: as read
    assert _line(["Т11"], page="lat") == ["T11"]
    assert _line(["Cm15"], page=None) == ["Cm15"]  # the italic rule needs a Cyrillic context
    # a Latin line keeps its twins
    assert _line(["Danfoss", "RA-N", "15", "C"]) == ["Danfoss", "RA-N", "15", "C"]


def test_page_script_prior() -> None:
    from inspector_docproc.codefix import page_script

    assert page_script(["Узел", "подключения", "к", "магистральным", "трубопроводам", "SBOW"]) == "cyr"
    assert (
        page_script(["Danfoss", "thermostatic", "valve", "RA-N", "with", "sensor", "RTR", "7096", "Ду"])
        == "lat"
    )
    assert page_script(["T11", "C", "15"]) is None  # no unambiguous letters


def test_post_correct_line_reports_rules() -> None:
    from inspector_docproc.codefix import post_correct_line

    out = post_correct_line(["φ15", "Cm4", "AHO/150321/1-PД-OB1", "мест"], EXTRAS, page="cyr", lexicon={"ст"})
    assert out == [
        ("Ø15", "diameter_sign"),
        ("Ст4", "script_context"),
        ("АНО/150321/1-РД-ОВ1", "code_corrector"),
        ("мест", None),
    ]
    legacy = post_correct_line(["PД", "Cm4"], page="cyr", context=False, diameter=False)
    assert legacy == [("РД", "homoglyph_fold"), ("Cm4", None)]


def test_word_frequencies_match_the_lexicon() -> None:
    """``ru_wordfreq.txt.gz`` (document frequencies, same TRAIN builder) covers exactly the lexicon words."""
    from inspector_docproc.lexicon import load_lexicon, load_wordfreq

    freq, lex = load_wordfreq(), load_lexicon()
    if not len(lex):
        pytest.skip("lexicon resource absent")
    assert set(freq) == set(lex.words)
    assert freq["пом"] > freq["пот"] and all(n >= 2 for n in freq.values())


def test_lexicon_resources_are_deterministic(tmp_path) -> None:
    from inspector_docproc.lexicon import _write_gz_deterministic

    a, b = tmp_path / "a.gz", tmp_path / "b.gz"
    _write_gz_deterministic(a, "ст\t70\n")
    _write_gz_deterministic(b, "ст\t70\n")
    assert a.read_bytes() == b.read_bytes()
