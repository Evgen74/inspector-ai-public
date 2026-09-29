"""Normalisation modes (93 §4.3)."""

from __future__ import annotations

import pytest

from inspector_eval.normalize import (
    is_approved_critical_string,
    normalize_code,
    normalize_criticality,
    normalize_location,
    normalize_value_text,
    value_match,
    value_similarity,
)


@pytest.mark.parametrize(
    ("raw", "light", "relaxed"),
    [
        ("012", "012", "12"),
        (" 012 ", "012", "12"),
        ("пом. 012", "012", "12"),
        ("Помещение №012", "012", "12"),
        ("№ 012", "012", "12"),
        ("12", "12", "12"),
        ("1.109", "1.109", "1.109"),
        ("-1.05", "-1.05", "-1.05"),
        ("−1.05", "-1.05", "-1.05"),
        ("Корпус 1 ,  этаж 3", "корпус 1,этаж 3", "корпус 1,этаж 3"),
        ("венткамера 012", "венткамера 012", "12"),
        ("OBJECT", "object", "object"),
    ],
)
def test_location_modes(raw: str, light: str, relaxed: str) -> None:
    assert normalize_location(raw, "light") == light
    assert normalize_location(raw, "relaxed") == relaxed
    assert normalize_location(raw, "strict") == raw.strip()


def test_location_light_keeps_leading_zero_distinct() -> None:
    assert normalize_location("12", "light") != normalize_location("012", "light")
    assert normalize_location("12", "relaxed") == normalize_location("012", "relaxed")
    assert normalize_location("1.109", "relaxed") != normalize_location("11.09", "relaxed")


@pytest.mark.parametrize("alias", ["KR-055", "KR-55", "КР-55", "кр-55", "M-055", "M-55", " KR-055 "])
def test_code_aliases_resolve_in_light_not_strict(alias: str) -> None:
    assert normalize_code(alias, "light") == "KR-055"
    if alias.strip() != "KR-055":
        assert normalize_code(alias, "strict") != "KR-055"


def test_code_prefix_mismatch_only_in_relaxed() -> None:
    assert normalize_code("PZ-040", "light") == "PZ-040"
    assert normalize_code("PZ-040", "relaxed") == "AR-040"
    assert normalize_code("AR-14", "light") == "AR-040"  # known organizer typo (codes.yaml)
    assert normalize_code("FREE-HEATING-001", "light") == "FREE-HEATING-001"
    assert normalize_code("free-heating-001", "light") == "FREE-HEATING-001"
    assert normalize_code("garbage", "light") == "GARBAGE"
    assert normalize_code(None, "light") == ""


def test_criticality_modes() -> None:
    a, b = "Критическое (приостановка работ)", "критическое  приостановка работ"
    assert normalize_criticality(a, "light") == normalize_criticality(b, "light")
    assert normalize_criticality(a, "strict") != normalize_criticality(b, "strict")
    assert normalize_criticality("Критическое (приостановка)", "relaxed") == "критическое"
    assert normalize_criticality(None, "light") is None
    assert is_approved_critical_string(a)
    assert not is_approved_critical_string("Существенное (предписание) — требует утверждения")
    assert not is_approved_critical_string("Критическое (приостановка работ) — требует утверждения")
    assert not is_approved_critical_string(None)


def test_value_text_normalisation() -> None:
    assert normalize_value_text("«Тёплый пол» предусмотрен.") == "теплый пол предусмотрен"
    assert normalize_value_text("1 000,5 м2") == "1000.5 м²"
    assert normalize_value_text("850 кв. м") == "850 м²"
    assert normalize_value_text(True) == "true"


@pytest.mark.parametrize(
    ("gold", "pred", "expected"),
    [
        (None, None, 1.0),
        (None, "", 1.0),
        ("x", None, 0.0),
        ("1,0 м", "1000 мм", 1.0),
        ("1,0 м", "1,1 м", 0.0),
        (250, "250", 1.0),
        (250, "250 мм", 1.0),
        ("B35", "B25", 0.0),
        ("Тёплый пол предусмотрен", "Теплый пол предусмотрен", 1.0),
        ("Тёплый пол предусмотрен", "Предусмотрено по ПД", 0.0),
        ("Конфигурация вентиляции по листу 10 ПД", "Конфигурация вентиляции по листу 10 ПД.", 1.0),
    ],
)
def test_value_match_light(gold, pred, expected: float) -> None:
    assert value_match(gold, pred, "light", 0.85) == expected


def test_value_match_strict_and_relaxed() -> None:
    assert value_match("Тёплый пол", "Теплый пол", "strict") == 0.0
    assert value_match(None, None, "strict") == 1.0
    long_gold = "Иная конфигурация на плане ОВ1, помещение 012"
    reordered = "помещение 012 иная конфигурация на плане ОВ1"
    assert value_match(long_gold, reordered, "light", 0.85) == 0.0
    assert value_match(long_gold, reordered, "relaxed", 0.85) == 1.0
    assert 0.0 <= value_similarity("abc", "abd", "light") < 1.0
