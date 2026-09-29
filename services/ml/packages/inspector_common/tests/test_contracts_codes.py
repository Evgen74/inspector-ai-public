from __future__ import annotations

import pytest

from inspector_common.contracts import codes


@pytest.mark.parametrize(
    ("raw", "param_id", "canonical", "style", "mismatch"),
    [
        ("KR-055", 55, "KR-055", "catalog", False),
        ("KR-55", 55, "KR-055", "short_latin", False),
        ("КР-55", 55, "KR-055", "short_cyrillic", False),
        ("КР-67", 67, "KR-067", "short_cyrillic", False),
        ("M-055", 55, "KR-055", "matrix_m", False),
        ("СПЗУ-30", 30, "SPZU-030", "short_cyrillic", False),
        ("ИОС1-69", 69, "IOS1-069", "short_cyrillic", False),
        ("ППМ-103", 103, "PPM-103", "short_cyrillic", False),
        (" ios4-079 ", 79, "IOS4-079", "catalog", False),
        ("PZ-055", 55, "KR-055", "catalog", True),
    ],
)
def test_parse_styles(raw: str, param_id: int, canonical: str, style: str, mismatch: bool) -> None:
    parsed = codes.parse_parameter_code(raw)
    assert (parsed.param_id, parsed.canonical, parsed.style, parsed.prefix_mismatch) == (
        param_id,
        canonical,
        style,
        mismatch,
    )


def test_known_appendix2_typo_resolves_to_ar_040() -> None:
    parsed = codes.parse_parameter_code("AR-14")
    assert parsed.canonical == "AR-040" and parsed.fixed_by_known_alias
    assert parsed.style == "short_latin" and parsed.param_id == 40


@pytest.mark.parametrize(
    ("raw", "style"), [("АР-14", "short_cyrillic"), ("AR-014", "catalog"), ("ar–14", "short_latin")]
)
def test_known_typo_in_any_alphabet_or_padding(raw: str, style: str) -> None:
    # Same rule as inspector_common.params (AG-03): the fix is keyed by (Latin prefix, number).
    parsed = codes.parse_parameter_code(raw)
    assert (parsed.canonical, parsed.style, parsed.fixed_by_known_alias) == ("AR-040", style, True)


def test_known_typo_does_not_touch_other_codes_with_the_same_number() -> None:
    assert codes.parse_parameter_code("PZ-014").canonical == "PZ-014"
    assert codes.parse_parameter_code("M-14").canonical == "PZ-014"  # M-xxx is exempt from prefix rules
    assert codes.parse_parameter_code("ПЗ-14").canonical == "PZ-014"
    assert not codes.parse_parameter_code("KR-14").fixed_by_known_alias  # a different prefix: plain mismatch


@pytest.mark.parametrize(
    "bad", ["", "KR", "KR-", "XX-001", "KR-133", "KR-000", "FREE-HEATING-001", "KR-0055a"]
)
def test_rejects_non_codes(bad: str) -> None:
    with pytest.raises(codes.ParameterCodeError):
        codes.parse_parameter_code(bad)


def test_canonical_codes_cover_all_132_ids() -> None:
    all_codes = [codes.canonical_code(i) for i in range(1, 133)]
    assert len(set(all_codes)) == 132
    assert all_codes[0] == "PZ-001" and all_codes[-1] == "SM-132"
    assert codes.canonical_code(79) == "IOS4-079"
    assert all(codes.is_canonical_code(c) for c in all_codes)
    assert all(codes.parse_parameter_code(c).canonical == c for c in all_codes)
    with pytest.raises(codes.ParameterCodeError):
        codes.canonical_code(133)


def test_alias_codes_parse_back() -> None:
    for param_id in (1, 40, 55, 79, 132):
        for alias in codes.alias_codes(param_id):
            assert codes.parse_parameter_code(alias).param_id == param_id


def test_free_codes() -> None:
    assert codes.free_code("HEATING", 1) == "FREE-HEATING-001"
    assert codes.parse_free_code("FREE-HEATING-001") == ("HEATING", 1)
    assert codes.is_free_code("FREE-STRUCTURE-012")
    with pytest.raises(codes.ParameterCodeError):
        codes.parse_free_code("FREE-PLUMBING-001")
    with pytest.raises(codes.ParameterCodeError):
        codes.free_code("HEATING", 1000)
