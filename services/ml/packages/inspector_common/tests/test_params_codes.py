"""Parameter code resolution in every style (97 §2.9): catalog, M-xxx, ТЗ/Приложение 2 Latin/Cyrillic. Owner: AG-03."""

from __future__ import annotations

import pytest

from inspector_common import params
from inspector_common.contracts import codes


@pytest.fixture(scope="module")
def reg() -> params.ParamRegistry:
    return params.load_params()


def test_every_alias_round_trips(reg: params.ParamRegistry) -> None:
    n = 0
    for p in reg:
        prefix = codes.prefix_for_id(p.param_id)
        variants = {
            p.code,
            *p.alias_codes,
            f"{prefix.latin}-{p.param_id}",  # no zero padding
            f"{prefix.cyrillic}-{p.param_id:03d}",  # Cyrillic, catalog width
            p.code.lower(),
            f" {p.alias_codes[2]} ",
            p.code.replace("-", "–"),  # typographic dash
            f"({p.alias_codes[1]})",  # as printed after a name: «Класс бетона (KR-55)»
            p.code.replace("-", ""),  # «KR055»
            p.alias_codes[1].replace("-", " "),  # «KR 55»
        }
        for raw in variants:
            res = reg.resolve(raw)
            assert (res.code, res.param_id) == (p.code, p.param_id), raw
            assert res.warnings == (), (raw, res.warnings)
            assert reg.get(raw) is p
            n += 1
    assert n >= 132 * 8


@pytest.mark.parametrize(
    ("raw", "code", "method"),
    [
        ("KR-055", "KR-055", "canonical"),
        ("M-055", "KR-055", "alias"),
        ("KR-55", "KR-055", "alias"),
        ("КР-55", "KR-055", "alias"),
        ("КР-67", "KR-067", "alias"),
        ("СПЗУ-30", "SPZU-030", "alias"),
        ("ИОС1-69", "IOS1-069", "alias"),
        ("ППМ-103", "PPM-103", "alias"),
        ("ИОС4-79", "IOS4-079", "alias"),
    ],
)
def test_appendix2_and_tz_styles(reg: params.ParamRegistry, raw: str, code: str, method: str) -> None:
    res = reg.resolve(raw)
    assert (res.code, res.method) == (code, method)


def test_ar14_resolves_to_ar040_with_a_warning(reg: params.ParamRegistry) -> None:
    """Приложение 2: «Ширина эвакуационных коридоров (AR-14)» is parameter 40 (id 14 is PZ-014)."""
    plain = reg.resolve("AR-14")
    assert plain.code == "AR-040" and plain.method == "known_fix" and plain.warnings
    named = params.resolve_code("AR-14", name="Ширина эвакуационных коридоров")
    assert named.code == "AR-040" and named.warnings
    assert reg.get("AR-14").code == "AR-040"
    for variant in ("АР-14", "AR-014", "AP-14", "ar 14"):  # the same typo in another alphabet or padding
        res = reg.resolve(variant)
        assert (res.code, res.method) == ("AR-040", "known_fix") and res.warnings, variant


def test_prefix_mismatch_is_resolved_by_name(reg: params.ParamRegistry) -> None:
    res = reg.resolve("PZ-40", name="Ширина эвакуационных коридоров")
    assert (res.code, res.method) == ("AR-040", "by_name") and res.warnings
    res = reg.resolve("AR-14", name="Расчетная электрическая мощность")  # the name wins over the known fix
    assert res.code == "PZ-014" and len(res.warnings) == 2


def test_prefix_mismatch_without_a_name(reg: params.ParamRegistry) -> None:
    res = reg.resolve("PZ-40")
    assert (res.code, res.method) == ("AR-040", "by_id_prefix_mismatch") and res.warnings
    with pytest.raises(params.ParameterCodeError):
        reg.resolve("PZ-40", strict=True)
    with pytest.raises(params.ParameterCodeError):
        reg.get("PZ-40")  # get() is strict


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("KP-55", "KR-055"),
        ("AP-41", "AR-041"),
        ("CM-132", "SM-132"),
        ("ООС-99", "OOS-099"),
        ("OOC-99", "OOS-099"),
    ],
)
def test_wrong_alphabet_prefix(reg: params.ParamRegistry, raw: str, code: str) -> None:
    res = reg.resolve(raw)
    assert res.code == code
    if raw != "ООС-99":
        assert res.method == "homoglyph" and res.warnings


def test_name_disagreement_is_reported_but_code_kept(reg: params.ParamRegistry) -> None:
    res = reg.resolve("KR-55", name="Площадь застройки")
    assert res.code == "KR-055" and any("PZ-001" in w for w in res.warnings)
    ambiguous = reg.resolve("KR-55", name="Ширина эвакуационных дверей")  # AR-041 vs PPM-105: no clear winner
    assert ambiguous.code == "KR-055" and any("слабо согласуется" in w for w in ambiguous.warnings)
    ok = reg.resolve("KR-55", name="Класс бетона")
    assert ok.code == "KR-055" and ok.warnings == ()


@pytest.mark.parametrize(
    "bad", ["", "KR", "KR-", "XX-001", "KR-133", "KR-000", "FREE-HEATING-001", "KR-0055a", "123"]
)
def test_rejects_non_codes(reg: params.ParamRegistry, bad: str) -> None:
    with pytest.raises(params.ParameterCodeError):
        reg.resolve(bad)


def test_get_by_int(reg: params.ParamRegistry) -> None:
    assert reg.get(1).code == "PZ-001"
    with pytest.raises(params.ParameterCodeError):
        reg.get(133)


def test_short_names_and_variants_resolve_by_name(reg: params.ParamRegistry) -> None:
    for p in reg:
        for name in (p.short_name, p.parameter_name, *p.name_variants):
            best = reg.match_name(name)
            if best is not None:
                assert best.code == p.code or best.parameter_name == p.parameter_name, (
                    p.code,
                    name,
                    best.code,
                )
    matched = sum(reg.match_name(p.short_name) is not None for p in reg)
    assert matched >= 120, matched  # near-duplicates (AR-041/PPM-105 …) are ambiguous by design


def test_cli_resolve_and_check(capsys) -> None:
    assert params.main(["resolve", "AR-14", "--name", "Ширина эвакуационных коридоров"]) == 0
    assert '"AR-040"' in capsys.readouterr().out
    assert params.main(["resolve", "PZ-40", "--strict"]) == 2
    assert params.main(["show", "КР-55"]) == 0
    assert "Класс бетона" in capsys.readouterr().out
