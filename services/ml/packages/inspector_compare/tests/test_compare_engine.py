"""The comparison engine on synthetic objects: comparators, router, atomic split, anchor pages, FREE numbering,
the bounded top-2 hedge, directional value triggers and the 132-row emission."""

from __future__ import annotations

import dataclasses
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import Finding, FindingGroup
from inspector_common.params import load_params
from inspector_compare.config import apply_overrides
from inspector_compare.engine import compare_object


def _groups(result: Any) -> dict[tuple[str, str], dict[str, Any]]:
    return {(g["parameter_code"], g["comparison_result"]): g for g in result.groups}


def _violations(result: Any) -> set[tuple[str, str]]:
    return {
        (f["parameter_code"], f["location"])
        for f in result.findings
        if f["violation_label"] == "VIOLATION_PRESENT"
    }


# ── ventilation rooms ─────────────────────────────────────────────────────────────────────────


def test_room_comparators_route_and_split(tmp_path: Path, cfg: Any, syn: Any) -> None:
    result = compare_object(syn.make_context(tmp_path, syn.ventilation_layouts()), cfg)
    groups = _groups(result)
    miss = groups[("IOS4-078", "MISSING_DESIGN_ELEMENT")]
    changed = groups[("IOS4-078", "CONFIGURATION_MISMATCH")]
    assert miss["locations"] == ["101"]
    assert changed["locations"] == ["102", "202", "203"]
    assert miss["pd_value"] == "Вытяжная вентиляция предусмотрена"
    assert miss["rd_value"] == "Вытяжная вентиляция отсутствует"
    assert changed["pd_value"] == "Конфигурация вентиляции по листу 10 ПД"
    assert changed["rd_value"] == "Конфигурация вентиляции изменена"
    assert miss["parameter_mapping_status"] == "PROVISIONAL_DOMAIN_MAPPING"
    assert miss["protocol_status"] == "CRITICAL" and miss["criticality"] == "Критическое (приостановка работ)"
    # atomic split: one finding per room, exact tokens
    assert _violations(result) == {("IOS4-078", r) for r in ("101", "102", "202", "203")}
    # renumbered (103), added (105), kept + added (201: В5.1 → В5.1, В5.2) are context (directional trigger);
    # 104 is not on any RD sheet → abstain, never a finding
    context = {(c["location"], c["outcome"]) for c in result.trace["context"]}
    assert ("103", "RENUMBERED") in context and ("105", "ELEMENT_ADDED") in context
    assert ("201", "ELEMENT_ADDED") in context
    assert any(
        a.get("location") == "104" and a["reason"] == "ELEMENT_KEY_UNRESOLVED"
        for a in result.trace["abstained"]
    )
    for g in result.groups:
        assert not validation_errors("finding_group", g)
        FindingGroup.model_validate(g)
    for f in result.findings:
        assert not validation_errors("finding", f)
        Finding.model_validate(f)


def test_anchor_page_is_the_majority_page(tmp_path: Path, cfg: Any, syn: Any) -> None:
    result = compare_object(syn.make_context(tmp_path, syn.ventilation_layouts()), cfg)
    g = _groups(result)[("IOS4-078", "CONFIGURATION_MISMATCH")]
    anchors = {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in g["anchor_evidence"]}
    assert anchors == {("PD", "F9001", 10), ("RD", "F9002", 5)}  # 102/202 on p5, 203 alone on p7
    assert all(e["is_anchor"] for e in g["anchor_evidence"])
    assert [(e["stage"], e["pdf_page_number"]) for e in g["location_pages"]["203"]] == [("PD", 10), ("RD", 7)]
    f203 = next(f for f in result.findings if f["location"] == "203")
    assert [(e["stage"], e["pdf_page_number"]) for e in f203["evidence"]] == [("PD", 10), ("RD", 5)]
    # the location's own page as a second item when configured (93 §2.8 case D)
    wide = apply_overrides(cfg, {"add_location_pages": True})
    result2 = compare_object(syn.make_context(tmp_path / "b", syn.ventilation_layouts()), wide)
    f203b = next(f for f in result2.findings if f["location"] == "203")
    assert [(e["stage"], e["pdf_page_number"]) for e in f203b["evidence"]] == [
        ("PD", 10),
        ("RD", 5),
        ("RD", 7),
    ]


def _pункт3_layouts(syn: Any) -> list[dict[str, Any]]:
    """The shape of the organizers' «пункт 3» on real AG-02B output: missing exhausts in 140/142 and changed
    branches in 147/198 on RD p18; changed branches in 314/339/341 and a kept + added room 317 on RD p20."""
    pd_tags = {
        "140": ("В2.7", "В2.8", "В2.9"),
        "142": ("В2.4", "В2.5", "В2.6"),
        "147": ("В2.10",),
        "198": ("В2.2", "В2.3"),
        "314": ("В3.1", "В3.2"),
        "317": ("В3.3",),
        "339": ("В2.12", "В2.13", "В2.15"),
        "341": ("В4.1",),
    }
    rd_tags = {
        18: {"147": ("В2.2", "В2.3", "В2.4"), "198": ("В2.8", "В2.9", "В2.10")},
        20: {
            "314": ("В3.1",),
            "317": ("В3.3", "В2.2", "В2.3", "В2.4"),
            "339": ("В2.11", "В2.12", "В2.14", "В2.15"),
            "341": ("В4.5", "В4.6"),
        },
    }
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(88, 10, syn.VENT_PD, stage="PD")],
        rooms=[syn.room(r, 88, "SCHEMATIC_LABEL") for r in pd_tags],
        tags=[syn.tag(t, "VENT_SYSTEM", 88, r) for r, ts in pd_tags.items() for t in ts],
    )
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[
            syn.title(18, 5, "План 1-го этажа (вентиляция)", "SYN/1-РД-ОВ1"),
            syn.title(20, 7, "План 3-го этажа (вентиляция)", "SYN/1-РД-ОВ1"),
        ],
        rooms=[syn.room(r, 18) for r in ("140", "142", "147", "198")]
        + [syn.room(r, 20) for r in ("314", "317", "339", "341")],
        tags=[
            syn.tag(t, "VENT_SYSTEM", p, r)
            for p, rooms in rd_tags.items()
            for r, ts in rooms.items()
            for t in ts
        ],
    )
    return [pd, rd]


def test_anchor_majority_counts_the_whole_finding(tmp_path: Path, cfg: Any, syn: Any) -> None:
    """93 §2.8 on the gold: both groups of «пункт 3» are anchored on RD p18, although most of the changed rooms
    are drawn on p20; the group-only pool (anchor_scope "group") would pick p20."""
    result = compare_object(syn.make_context(tmp_path, _pункт3_layouts(syn)), cfg)
    groups = _groups(result)
    miss, changed = (
        groups[("IOS4-078", "MISSING_DESIGN_ELEMENT")],
        groups[("IOS4-078", "CONFIGURATION_MISMATCH")],
    )
    assert miss["locations"] == ["140", "142"]
    assert changed["locations"] == ["147", "198", "314", "339", "341"]  # 317 kept В3.3 and added: context
    assert ("317", "ELEMENT_ADDED") in {(c["location"], c["outcome"]) for c in result.trace["context"]}

    def rd_anchor(g: dict[str, Any]) -> int:
        return next(e["pdf_page_number"] for e in g["anchor_evidence"] if e["stage"] == "RD")

    assert rd_anchor(miss) == rd_anchor(changed) == 18
    assert [e["pdf_page_number"] for e in changed["location_pages"]["314"]] == [88, 20]  # own page kept
    f314 = next(f for f in result.findings if f["location"] == "314")
    assert [(e["stage"], e["pdf_page_number"]) for e in f314["evidence"]] == [("PD", 88), ("RD", 18)]
    local = compare_object(
        syn.make_context(tmp_path / "g", _pункт3_layouts(syn)),
        apply_overrides(cfg, {"anchor_scope": "group"}),
    )
    assert rd_anchor(_groups(local)[("IOS4-078", "CONFIGURATION_MISMATCH")]) == 20
    assert rd_anchor(_groups(local)[("IOS4-078", "MISSING_DESIGN_ELEMENT")]) == 18
    # the anchor always depicts one of the group's own rooms: a pool page without them is never chosen
    for g in result.groups:
        for e in g["anchor_evidence"]:
            own = {
                loc
                for loc, pages in g["location_pages"].items()
                for p in pages
                if p["pdf_page_number"] == e["pdf_page_number"] and p["stage"] == e["stage"]
            }
            assert own, (g["finding_group_id"], e)


def test_ambiguous_attribution_never_makes_a_violation(tmp_path: Path, cfg: Any, syn: Any) -> None:
    """One RD tag instance linked to two rooms (same page, box and label) is evidence for neither: room 339 keeps
    its firm branches (renumbered: context, abstained as AMBIGUOUS_VALUE); room 341, whose change holds without
    the shared instance, stays a violation."""
    shared = (0.53, 0.47)
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(88, 10, syn.VENT_PD, stage="PD")],
        rooms=[syn.room(r, 88, "SCHEMATIC_LABEL") for r in ("339", "341")],
        tags=[
            syn.tag("В2.12", "VENT_SYSTEM", 88, "339", xy=(0.1, 0.1)),
            syn.tag("В2.13", "VENT_SYSTEM", 88, "339", xy=(0.1, 0.2)),
            syn.tag("В2.20", "VENT_SYSTEM", 88, "341", xy=(0.3, 0.1)),
        ],
    )
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(20, 7, "План 3-го этажа (вентиляция)", "SYN/1-РД-ОВ1")],
        rooms=[syn.room(r, 20) for r in ("339", "341")],
        tags=[
            syn.tag("В2.12", "VENT_SYSTEM", 20, "339", xy=(0.5, 0.40)),
            syn.tag("В2.14", "VENT_SYSTEM", 20, "339", xy=(0.5, 0.44)),
            syn.tag("В2.11", "VENT_SYSTEM", 20, "339", xy=shared),  # one leader read for both rooms
            syn.tag("В2.11", "VENT_SYSTEM", 20, "341", xy=shared),
            syn.tag("В2.21", "VENT_SYSTEM", 20, "341", xy=(0.6, 0.5)),
            syn.tag("В2.22", "VENT_SYSTEM", 20, "341", xy=(0.6, 0.54)),
        ],
    )
    result = compare_object(syn.make_context(tmp_path, [pd, rd]), cfg)
    assert _violations(result) == {("IOS4-078", "341")}  # 1 branch → 2 firm branches (+1 shared): changed
    assert any(
        a.get("location") == "339" and a["reason"] == "AMBIGUOUS_VALUE" for a in result.trace["abstained"]
    )
    # without the shared instance the reading is unambiguous and 339 is a change (2 → 3 branches)
    rd["tags"] = [t for t in rd["tags"] if not (t["room_token"] == "341" and t["tag"] == "В2.11")]
    plain = compare_object(syn.make_context(tmp_path / "b", [pd, rd]), cfg)
    assert ("IOS4-078", "339") in _violations(plain)


def test_explication_names_feed_room_rules_and_rationale(tmp_path: Path, cfg: Any, syn: Any) -> None:
    """Room names from AG-02C's EXPLICATION tables: a system mark counts as a unit only in a room named a vent
    chamber (here named by the table alone), and the rationale prints the name."""
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(20, 26, "Принципиальная схема теплоснабжения приточных установок", stage="PD")],
        rooms=[syn.room("012", 20, "SCHEMATIC_LABEL")],
        tags=[syn.tag(u, "VENT_SYSTEM", 20, "012") for u in ("П1", "П2")],
    )
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(8, 4, "План подвала (вентиляция)")],  # no шифр in the title block
        rooms=[syn.room("012", 8)],
        tags=[syn.tag("П1", "VENT_SYSTEM", 8, "012")],
    )
    bare = compare_object(syn.make_context(tmp_path / "a", [pd, rd]), cfg)
    assert not any(g["parameter_code"] == "IOS4-079" for g in bare.groups)  # unnamed room: marks are ducts
    named = compare_object(
        syn.make_context(
            tmp_path / "b", [pd, rd], tables=[syn.explication("F9002", "RD", 8, [("012", "Венткамера")])]
        ),
        cfg,
    )
    g = _groups(named)[("IOS4-079", "CONFIGURATION_MISMATCH")]
    assert g["locations"] == ["012"]
    assert "пом. 012 (Венткамера)" in g["rationale"]
    # the plan mark comes from the шифр of the file name when the title block has none («SYN-РД-ОВ1.pdf»)
    assert g["rd_value"] == "Иная конфигурация на плане ОВ1, помещение 012"


def test_exact_room_tokens_and_label_multiset(tmp_path: Path, cfg: Any, syn: Any) -> None:
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(20, 26, "Принципиальная схема теплоснабжения приточных установок", stage="PD")],
        rooms=[syn.room("012", 20, "SCHEMATIC_LABEL", name="Венткамера")],
        tags=[syn.tag(u, "EQUIPMENT", 20, "012") for u in ("П1", "П2", "П17")],
    )
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[
            syn.title(8, 4, "План подвала (вентиляция)", "SYN/1-РД-ОВ1"),
            syn.title(9, 17, "План венткамеры", "SYN/1-РД-ОВ1"),
        ],
        rooms=[syn.room("012", 8, name="Венткамера"), syn.room("012", 9)],
        tags=[syn.tag("П1", "EQUIPMENT", 8, "012"), syn.tag("П17.1, 17.2", "EQUIPMENT", 8, "012")]
        + [syn.tag(u, "EQUIPMENT", 9, "012") for u in ("П1", "П2", "П17.1", "П17.2")],
    )
    result = compare_object(syn.make_context(tmp_path, [pd, rd]), cfg)
    g = _groups(result)[("IOS4-079", "CONFIGURATION_MISMATCH")]
    assert g["locations"] == ["012"]  # leading zero kept
    rd_anchor = next(e for e in g["anchor_evidence"] if e["stage"] == "RD")
    assert rd_anchor["pdf_page_number"] == 8  # the plan shows the change more strongly than the detail sheet
    assert g["pd_value"] == "Конфигурация приточных установок по листу 26 ПД"
    assert g["rd_value"] == "Иная конфигурация на плане ОВ1, помещение 012"
    assert g["alt_parameter_codes"] == ["IOS4-078"]  # runner-up recorded
    assert not any(x.get("hedge_of_group_id") for x in result.groups)  # gold-basis route: p < 0.1, no twin


def test_warm_floor_goes_to_free_heating_numbered_per_group(tmp_path: Path, cfg: Any, syn: Any) -> None:
    cfg2 = apply_overrides(
        cfg, {"families": {"HEAT_POINT": {"mode": "PRESENCE", "tag_kinds": ["EQUIPMENT"]}}}
    )
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[
            syn.title(30, 21, "Принципиальная схема системы отопления", stage="PD"),
            syn.title(31, 22, "Схема ИТП (отопление)", stage="PD"),
        ],
        rooms=[syn.room(t, 30, "SCHEMATIC_LABEL") for t in ("267", "270")]
        + [syn.room("001", 31, "SCHEMATIC_LABEL")],
        tags=[syn.tag("Контур тёплого пола", "HEATING_SYSTEM", 30, t) for t in ("267", "270")]
        + [syn.tag("Тепловой пункт ИТП-1", "EQUIPMENT", 31, "001")],
    )
    rd = syn.layout(
        "F9003",
        "RD",
        titles=[
            syn.title(17, 4, "План 2-го этажа (отопление)", "SYN/1-РД-ОВ2"),
            syn.title(3, 1, "План подвала (отопление)", "SYN/1-РД-ОВ2"),
        ],
        rooms=[syn.room(t, 17) for t in ("267", "270")] + [syn.room("001", 3)],
        tags=[syn.tag("Радиатор 22-500-700", "EQUIPMENT", 17, t) for t in ("267", "270")],
        clouds=[
            {
                "pdf_page_number": 17,
                "bbox": [0.1, 0.1, 0.3, 0.3],
                "source": "OCG_LAYER",
                "revision_label": "Изм. №3",
                "rooms_covered": ["270"],
            }
        ],
    )
    result = compare_object(syn.make_context(tmp_path, [pd, rd]), cfg2)
    free = sorted(
        (g for g in result.groups if g["matrix_scope"] == "FREE_SEARCH"), key=lambda g: g["parameter_code"]
    )
    assert [g["parameter_code"] for g in free] == ["FREE-HEATING-001", "FREE-HEATING-002"]
    warm = next(g for g in free if g["locations"] == ["267", "270"])
    assert warm["parameter_code"] == "FREE-HEATING-001"  # PD page 30 comes before page 31
    assert warm["criticality"] == "Существенное (предписание) — требует утверждения"
    assert warm["protocol_status"] == "WARNING" and warm["parameter_id"] is None
    assert warm["parameter_mapping_status"] == "MATRIX_GAP_CONFIRMED"
    assert warm["evidence_bind_status"] == "BOUND"
    assert (warm["pd_value"], warm["rd_value"]) == ("Тёплый пол предусмотрен", "Тёплый пол отсутствует")
    assert warm["ext"]["revision_clouds"] == ["Изм. №3"]
    # the FREE cap keeps the most confident group
    capped = compare_object(
        syn.make_context(tmp_path / "cap", [pd, rd]), dataclasses.replace(cfg2, max_free_groups=1)
    )
    assert [g["parameter_code"] for g in capped.groups if g["matrix_scope"] == "FREE_SEARCH"] == [
        "FREE-HEATING-001"
    ]
    assert any(a["reason"] == "FREE_CAP" for a in capped.trace["abstained"])


# ── bounded top-2 hedge ───────────────────────────────────────────────────────────────────────


def _hedge_layouts(syn: Any, extra_rooms: int) -> list[dict[str, Any]]:
    """Room 012 loses its supply units (analogy route IOS4-079, runner-up IOS4-078) + N rooms lose exhausts."""
    rooms = [f"1{n:02d}" for n in range(extra_rooms)]
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(10, 10, syn.VENT_PD, stage="PD")],
        rooms=[syn.room("012", 10, "SCHEMATIC_LABEL")] + [syn.room(r, 10, "SCHEMATIC_LABEL") for r in rooms],
        tags=[syn.tag("П1", "EQUIPMENT", 10, "012"), syn.tag("П2", "EQUIPMENT", 10, "012")]
        + [syn.tag("В1.1", "VENT_SYSTEM", 10, r, xy=(0.1 + 0.08 * i, 0.6)) for i, r in enumerate(rooms)],
    )
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(5, 5, "План подвала (вентиляция)", "SYN/1-РД-ОВ1")],
        rooms=[syn.room("012", 5)] + [syn.room(r, 5) for r in rooms],
    )
    return [pd, rd]


def test_hedge_twin_within_budget(tmp_path: Path, cfg: Any, syn: Any) -> None:
    result = compare_object(syn.make_context(tmp_path, _hedge_layouts(syn, 4)), cfg)
    keys = _violations(result)
    assert ("IOS4-079", "012") in keys and ("IOS4-078", "012") in keys  # 1 hedge of 6 critical checks = 17 %
    twin = next(g for g in result.groups if g.get("hedge_of_group_id"))
    primary = next(g for g in result.groups if g["finding_group_id"] == twin["hedge_of_group_id"])
    assert twin["parameter_code"] == "IOS4-078" and primary["parameter_code"] == "IOS4-079"
    assert twin["card_no"] == primary["card_no"]
    assert twin["hedge_kind"] == "SAME_SYSTEM"
    assert twin["confidence"] <= primary["confidence"]
    f_twin = next(f for f in result.findings if f["finding_group_id"] == twin["finding_group_id"])
    assert f_twin["hedge_of_finding_id"] == primary["finding_ids"][0]


def test_hedge_budget_blocks_twins(tmp_path: Path, cfg: Any, syn: Any) -> None:
    result = compare_object(
        syn.make_context(tmp_path, _hedge_layouts(syn, 0)), cfg
    )  # 1 hedge of 2 = 50 % > 20 %
    assert _violations(result) == {("IOS4-079", "012")}
    assert any(a["reason"] == "HEDGE_BUDGET" for a in result.trace["abstained"])
    lowered = apply_overrides(cfg, {"hedge": {"runner_up_prior": {"ANALOGY": 0.05}}})
    result2 = compare_object(syn.make_context(tmp_path / "b", _hedge_layouts(syn, 4)), lowered)
    assert ("IOS4-078", "012") not in _violations(result2)  # runner-up p < 0.1: no hedge at all


# ── directional value triggers ────────────────────────────────────────────────────────────────


def _value(
    syn: Any,
    code: str,
    stage: str,
    file_id: str,
    value: Any,
    *,
    unit: str | None,
    rank: float | None = None,
    dtype: str = "number",
    location: str | None = None,
    raw: str | None = None,
) -> dict[str, Any]:
    return {
        "value_id": f"v-{code}-{stage}-{location}-{value}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": stage,
        "page_no": 5,
        "param_code": code,
        "location": location,
        "location_type": "ELEMENT" if location else "OBJECT",
        "value_raw": raw or str(value),
        "value_norm": {"type": dtype, "value": value, "unit": unit, "rank": rank},
        "method": "TABLE",
        "confidence": 0.95,
        "quality_flag": "OK",
        "pipeline_version": "test",
    }


def test_value_comparators_enforce_directional_triggers(tmp_path: Path, cfg: Any, syn: Any) -> None:
    values = [
        # KR-058 slab thickness, direction DECREASE: 300 → 250 violates, 300 → 350 is an improvement
        _value(syn, "KR-058", "PD", "F9004", 300, unit="мм", location="Плита Пм1"),
        _value(syn, "KR-058", "RD", "F9002", 250, unit="мм", location="Плита Пм1"),
        _value(syn, "KR-058", "PD", "F9004", 300, unit="мм", location="Плита Пм2"),
        _value(syn, "KR-058", "RD", "F9002", 350, unit="мм", location="Плита Пм2"),
        # KR-055 concrete class, DOWNGRADE by ordinal rank
        _value(syn, "KR-055", "PD", "F9004", "B35", unit=None, rank=35, dtype="enum", location="Колонны"),
        _value(syn, "KR-055", "RD", "F9002", "B30", unit=None, rank=30, dtype="enum", location="Колонны"),
        _value(syn, "KR-055", "PD", "F9004", "B30", unit=None, rank=30, dtype="enum", location="Стены"),
        _value(syn, "KR-055", "RD", "F9002", "B40", unit=None, rank=40, dtype="enum", location="Стены"),
        # SPZU-025 asphalt area, ANY with a 5 % tolerance: 850 → 720 violates, 850 → 860 is within tolerance
        _value(syn, "SPZU-025", "PD", "F9001", 850, unit="м²"),
        _value(syn, "SPZU-025", "RD", "F9002", 720, unit="м²"),
    ]
    result = compare_object(syn.make_context(tmp_path, [], values=values), cfg)
    keys = _violations(result)
    assert ("KR-058", "Плита Пм1") in keys and ("KR-058", "Плита Пм2") not in keys
    assert ("KR-055", "Колонны") in keys and ("KR-055", "Стены") not in keys
    assert ("SPZU-025", "OBJECT") in keys
    improvements = {
        (c["code"], c["location"]) for c in result.trace["context"] if c["outcome"] == "IMPROVEMENT"
    }
    assert improvements == {("KR-058", "Плита Пм2"), ("KR-055", "Стены")}
    by_code = {g["parameter_code"]: g for g in result.groups}
    assert (by_code["KR-058"]["pd_value"], by_code["KR-058"]["rd_value"]) == ("300 мм", "250 мм")
    assert by_code["KR-058"]["discrepancy_type"] == "VALUE_DECREASED"
    assert by_code["KR-055"]["comparison_result"] == "MATERIAL_SUBSTITUTION"
    assert by_code["SPZU-025"]["protocol_status"] == "WARNING"
    assert by_code["SPZU-025"]["ext"]["deviation_text"].startswith("⬇️")
    assert "15,3%" in by_code["SPZU-025"]["ext"]["deviation_text"]
    within = compare_object(
        syn.make_context(
            tmp_path / "b",
            [],
            values=[
                _value(syn, "SPZU-025", "PD", "F9001", 850, unit="м²"),
                _value(syn, "SPZU-025", "RD", "F9002", 860, unit="м²"),
            ],
        ),
        cfg,
    )
    assert not _violations(within)


def test_value_findings_hedge_with_the_seed_duplicate_group(tmp_path: Path, cfg: Any, syn: Any) -> None:
    """A corridor narrowed PD 1,8 → RD 1,4 м (AR-040, critical) gets a PPM-104 twin (seed hedge group DUPLICATE,
    p 0.30 ≥ 0.1) when the budget allows it: 1 hedge of 6 critical checks (the 4 ventilation rooms + AR-040 +
    the twin) = 17 % ≤ 20 %; alone (1 of 2 = 50 %) it is blocked."""
    values = [
        _value(syn, "AR-040", "PD", "F9001", 1.8, unit="м", location="Коридор 1.12"),
        _value(syn, "AR-040", "RD", "F9002", 1.4, unit="м", location="Коридор 1.12"),
    ]
    result = compare_object(syn.make_context(tmp_path, syn.ventilation_layouts(), values=values), cfg)
    keys = _violations(result)
    assert ("AR-040", "Коридор 1.12") in keys and ("PPM-104", "Коридор 1.12") in keys
    twin = next(g for g in result.groups if g["parameter_code"] == "PPM-104")
    primary = next(g for g in result.groups if g["parameter_code"] == "AR-040")
    assert twin["hedge_of_group_id"] == primary["finding_group_id"] and twin["hedge_kind"] == "DUPLICATE"
    assert primary["alt_parameter_codes"] == ["PPM-104"]
    assert (
        (twin["pd_value"], twin["rd_value"])
        == (primary["pd_value"], primary["rd_value"])
        == ("1,8 м", "1,4 м")
    )
    f_twin = next(f for f in result.findings if f["parameter_code"] == "PPM-104")
    assert f_twin["sub_id"] is None and f_twin["hedge_of_finding_id"] == primary["finding_ids"][0]
    for g in result.groups:
        assert not validation_errors("finding_group", g)
    alone = compare_object(syn.make_context(tmp_path / "b", [], values=values), cfg)
    assert _violations(alone) == {("AR-040", "Коридор 1.12")}
    assert any(a["reason"] == "HEDGE_BUDGET" and a["code"] == "PPM-104" for a in alone.trace["abstained"])


# ── 132 rows ──────────────────────────────────────────────────────────────────────────────────


def test_every_catalog_parameter_has_a_row(tmp_path: Path, cfg: Any, syn: Any) -> None:
    result = compare_object(syn.make_context(tmp_path, syn.ventilation_layouts()), cfg)
    params = [p.code for p in load_params()]
    rows = Counter(f["parameter_code"] for f in result.findings)
    assert set(params) <= set(rows)
    object_rows = [f for f in result.findings if f["location"] == "OBJECT"]
    assert len(object_rows) == len(params) - 1  # IOS4-078 is violated: its OBJECT row is omitted by default
    assert "IOS4-078" not in {f["parameter_code"] for f in object_rows}
    for f in object_rows:
        assert f["violation_label"] in ("NO_VIOLATION", "MISSING_DOCUMENT", "COMPARISON_IMPOSSIBLE")
        assert f["evidence"] == []
        assert f["criticality"] == load_params().get(f["parameter_code"]).criticality
    negative = compare_object(
        syn.make_context(tmp_path / "n", syn.ventilation_layouts()),
        apply_overrides(cfg, {"object_row_when_violated": "negative"}),
    )
    assert any(f["parameter_code"] == "IOS4-078" and f["location"] == "OBJECT" for f in negative.findings)
    off = compare_object(
        syn.make_context(tmp_path / "o", syn.ventilation_layouts()),
        apply_overrides(cfg, {"emit_object_rows": False}),
    )
    assert all(f["location"] != "OBJECT" for f in off.findings)


def test_free_hook_groups_are_validated_bound_and_renumbered(tmp_path: Path, cfg: Any, syn: Any) -> None:
    good = {
        "finding_group_id": "X",
        "object_id": syn.OBJ,
        "matrix_scope": "FREE_SEARCH",
        "parameter_code": "FREE-LIFT-007",
        "parameter_id": None,
        "parameter_mapping_status": "MATRIX_GAP_CONFIRMED",
        "comparison_result": "MISSING_DESIGN_ELEMENT",
        "location_type": "BUILDING",
        "locations": ["Корпус 1"],
        "pd_value": "Лифт предусмотрен",
        "rd_value": "Лифт отсутствует",
        "id_value": None,
        "violation_label": "VIOLATION_PRESENT",
        "protocol_status": "WARNING",
        "criticality": "Существенное (предписание) — требует утверждения",
        "anchor_evidence": [
            {"stage": "PD", "file_id": "F9001", "pdf_page_number": 3, "is_anchor": True},
            {"stage": "RD", "file_id": "F9002", "pdf_page_number": 4, "is_anchor": True},
        ],
        "finding_ids": ["tmp-1"],
        "discovery_method": "LOGICAL_ANALYSIS",
        "evidence_bind_status": "BOUND",
        "confidence": 0.7,
    }
    unbound = {**good, "locations": ["Корпус 2"], "evidence_bind_status": "PARTIAL"}
    invalid = {"parameter_code": "FREE-LIFT-001"}

    def hook(**_: Any) -> list[dict[str, Any]]:
        return [good, unbound, invalid]

    result = compare_object(syn.make_context(tmp_path, []), cfg, free_hook=hook)
    free = [g for g in result.groups if g["matrix_scope"] == "FREE_SEARCH"]
    assert [g["parameter_code"] for g in free] == ["FREE-LIFT-001"]
    assert free[0]["locations"] == ["Корпус 1"] and free[0]["card_no"] == "Б.1"
    assert any(a["reason"] == "FREE_HOOK_INVALID" for a in result.trace["abstained"])

    def broken(**_: Any) -> list[dict[str, Any]]:
        raise RuntimeError("boom")

    assert compare_object(syn.make_context(tmp_path / "b", []), cfg, free_hook=broken).groups == []


@pytest.mark.parametrize(
    "bad", [{"hedge": {"budget_share": 1.5}}, {"nope": 1}, {"families": {"X": {"mode": "BAD"}}}]
)
def test_config_overrides_are_checked(cfg: Any, bad: dict[str, Any]) -> None:
    from inspector_compare.config import ConfigError

    with pytest.raises(ConfigError):
        apply_overrides(cfg, bad)


def test_config_hash_is_stable_and_sensitive(cfg: Any) -> None:
    a = cfg.describe({"seed": "1"})["config_hash"]
    assert a == cfg.describe({"seed": "1"})["config_hash"]
    assert a != apply_overrides(cfg, {"max_free_groups": 3}).describe({"seed": "1"})["config_hash"]
    assert a != cfg.describe({"seed": "2"})["config_hash"]


# ── module 8: admin overrides ─────────────────────────────────────────────────────────────────


def test_deactivated_parameter_is_emitted_as_not_applicable_never_dropped(
    tmp_path: Path, cfg: Any, syn: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    layouts = syn.ventilation_layouts()
    base = compare_object(syn.make_context(tmp_path / "base", layouts), cfg)
    assert ("IOS4-078", "OBJECT") not in {(f["parameter_code"], f["location"]) for f in base.findings}
    assert any(g["parameter_code"] == "IOS4-078" for g in base.groups)

    path = tmp_path / "matrix_overrides.json"
    path.write_text(
        json.dumps(
            {"matrix_version": "1.1.1+ovr.1", "overrides": [{"param_code": "IOS4-078", "is_active": False}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("INSPECTOR_MATRIX_OVERRIDES", str(path))
    result = compare_object(syn.make_context(tmp_path / "off", layouts), cfg)
    assert not any(g["parameter_code"] == "IOS4-078" for g in result.groups)
    assert not any(
        f["parameter_code"] == "IOS4-078" and f["violation_label"] == "VIOLATION_PRESENT"
        for f in result.findings
    )
    rows = [f for f in result.findings if f["parameter_code"] == "IOS4-078"]
    assert len(rows) == 1 and rows[0]["location"] == "OBJECT"
    assert rows[0]["completeness_status"] == "NOT_APPLICABLE"
    assert rows[0]["completeness_basis"] == "PARAM_DEACTIVATED"
    assert rows[0]["violation_label"] == "NO_VIOLATION"
    assert result.trace["matrix_version"] == "1.1.1+ovr.1"
    assert result.trace["deactivated_params"].get("IOS4-078", 0) >= 1
    assert result.trace["matrix_overrides"]["changed"] == ["IOS4-078"]
    object_rows = [f for f in result.findings if f["location"] == "OBJECT"]
    assert {f["parameter_code"] for f in object_rows} == {
        p.code for p in load_params()
    }  # all 132, none dropped
