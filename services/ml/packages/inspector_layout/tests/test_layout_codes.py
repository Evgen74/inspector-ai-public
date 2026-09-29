"""Code gate: corrector + registry prior + stage-letter fold (96 §7.2, R-06). Synthetic names only."""

from __future__ import annotations

import pytest

from inspector_layout.codes import CodeRegistry, code_key, fold_stage, gate_text, looks_like_code, name_codes

NAMES = [
    ("F9001", "Проект/Стадия П/НВС-2025.03-1.2-ПЗ.pdf"),
    ("F9002", "Проект/Стадия П/НВС-2025.03-4.2-КР2.pdf"),
    ("F9003", "Проект/Стадия РД/АНО-150321-1-РД-ОВ1 изм. 4_в1 (1).pdf"),
    ("F9004", "Проект/ПД/2 Схема ЗУ/АНО1503211-П-ПЗУ.pdf"),
    ("F9005", "Проект/ПД/5.4 Отопление/V2_01-05-04-02-07_Том 5.4.2 ОВ (1).pdf"),
    ("F9006", "Проект/Стадия РД/2451.Р.ДР (1).pdf"),
]
STAGES = {"F9001": "PD", "F9002": "PD", "F9003": "RD", "F9004": "PD", "F9005": "PD", "F9006": "RD"}


@pytest.fixture(scope="module")
def reg() -> CodeRegistry:
    return CodeRegistry.from_names(NAMES, STAGES)


def test_code_key_folds_separators_and_lookalikes() -> None:
    assert code_key("AHO/150321/1-PД-OB1") == code_key("АНО-150321-1-РД-ОВ1")
    assert code_key("НВС-2025/03-ПЗ") != code_key("НВС-2025/03-КР")


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("АНО/150321/1-РД-ОВ1", True),
        ("2451.Р.ДР.ГИ", True),
        ("НВС-2025/03", True),  # benchmark A08: the stamp prints the prefix alone
        ("20.03.2024", False),
        ("690-23", False),
        ("0,003м", False),
        ("Школа на 600", False),
        ("С-ДЭМ/20-02-2026/506367016", True),
        ("НСЛ-17-02/2026-1,2", True),
        ("4,01л/с.", False),  # a flow in a PD text stamp zone (F0164 p8)
        ("п.3.6.4", False),  # a clause reference
        ("м3/ч.2-1", False),
    ],
)
def test_looks_like_code(text: str, ok: bool) -> None:
    assert looks_like_code(text) is ok


def test_name_codes_strip_revision_suffixes() -> None:
    assert name_codes("АНО-150321-1-РД-ОВ1 изм. 4_в1 (1).pdf") == ["АНО-150321-1-РД-ОВ1"]
    assert name_codes("НСЛ-12-02.2026-1_2-КЖ1.1.8_Изм.1.pdf") == ["НСЛ-12-02.2026-1_2-КЖ1.1.8"]
    assert name_codes("ИЗМ ПО ЗАМЕЧАНИЯМ АНО1503211-П-ПЗУ.pdf") == ["АНО1503211-П-ПЗУ"]


def test_registry_segments_from_names_and_folders(reg: CodeRegistry) -> None:
    assert "ПЗ" in reg.segments and "ОВ1" in reg.segments and "ПЗУ" in reg.segments
    assert "НВС" in reg.heads and "АНО" in reg.heads and "ОВ" in reg.heads
    assert "ЗАМЕЧА" not in reg.heads  # long capital words are not abbreviations


def test_corrector_fixes_lookalikes(reg: CodeRegistry) -> None:
    res = reg.resolve("AHO/150321/1-PД-OB1", stage="RD")
    assert res.code == "АНО/150321/1-РД-ОВ1"
    assert res.basis == "corrector"
    assert res.registry_match is not None


def test_registry_prior_fixes_p3_to_pz(reg: CodeRegistry) -> None:
    """«HBC-2025/03-P3»: П read as P and З as 3 — only the registry knows the segment «ПЗ» (96 §7.2)."""
    res = reg.resolve("HBC-2025/03-P3", stage="PD")
    assert res.code == "НВС-2025/03-ПЗ"
    assert res.basis == "registry_segment"
    assert ("Р3", "ПЗ") in res.changed_segments


def test_known_segments_are_kept(reg: CodeRegistry) -> None:
    assert reg.resolve("НВС-2025/03-КР", stage="PD").code == "НВС-2025/03-КР"
    assert reg.resolve("АНО/150321/1-П-ИОС5.4.2", stage="PD").code == "АНО/150321/1-П-ИОС5.4.2"


def test_stage_letter_fold_follows_file_stage(reg: CodeRegistry) -> None:
    res = reg.resolve("АНО/150321/1-Р-ИОС5.4.2", stage="PD")
    assert res.code == "АНО/150321/1-П-ИОС5.4.2"
    assert res.basis == "stage_fold"
    # RD keeps «Р»; no stage → no fold; «РД» is never folded
    assert reg.resolve("2451.Р.ДР.ГИ", stage="RD").code == "2451.Р.ДР.ГИ"
    assert reg.resolve("АНО/150321/1-Р-ОВ", stage=None).code == "АНО/150321/1-Р-ОВ"
    assert reg.resolve("АНО/150321/1-РД-ОВ1", stage="PD").code == "АНО/150321/1-РД-ОВ1"


def test_genuine_latin_segments_are_untouched(reg: CodeRegistry) -> None:
    assert reg.resolve("ВВГнг(А)-LS-3х2.5-RU", stage=None).code.endswith("LS-3х2.5-RU")
    assert reg.resolve("KR22-031295/1", stage=None).code == "KR22-031295/1"


def test_registry_code_patches_one_substitution() -> None:
    reg = CodeRegistry.from_names([("F1", "X/АНО-150321-1-РД-ОВ1.pdf")])
    res = reg.resolve("АНО/150327/1-РД-ОВ1")  # one digit misread
    assert res.code == "АНО/150321/1-РД-ОВ1"
    assert res.basis == "registry_code"


def test_empty_registry_still_corrects() -> None:
    assert CodeRegistry().resolve("AHO/150321/1-PД-OB2.1").code == "АНО/150321/1-РД-ОВ2.1"
    # «АН0» (digit zero) is fixed only when the registry knows the organisation prefix «АНО»
    assert CodeRegistry().resolve("AH0/150321/1-PД-0B2.1").code.startswith("АН0/")


def test_registry_knows_org_prefix(reg: CodeRegistry) -> None:
    assert reg.resolve("AH0/150321/1-PД-0B2.1", stage="RD").code == "АНО/150321/1-РД-ОВ2.1"


def test_gate_text_applies_to_code_tokens_only(reg: CodeRegistry) -> None:
    out = gate_text("Шифр HBC-2025/03-P3, лист 5 от 20.03.2024.", reg, stage="PD")
    assert out == "Шифр НВС-2025/03-ПЗ, лист 5 от 20.03.2024."


@pytest.mark.parametrize(
    ("raw", "folded", "stage"),
    [
        ("П", "П", "PD"),
        ("P", "Р", "RD"),
        ("PД", "РД", "RD"),
        ("РД", "РД", "RD"),
        ("N", "П", "PD"),
        ("ИД", "ИД", "ID"),
    ],
)
def test_fold_stage(raw: str, folded: str, stage: str) -> None:
    assert fold_stage(raw) == (folded, stage)


def test_fold_stage_unknown_and_empty() -> None:
    assert fold_stage(None) == (None, None)
    assert fold_stage("Эскиз")[1] is None
