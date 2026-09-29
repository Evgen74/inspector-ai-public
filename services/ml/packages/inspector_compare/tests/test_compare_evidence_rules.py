"""Evidence rules added on the whole-object Тюменская run (M1 end to end, compare-rules-m1.3).

Each rule is tested with a positive twin (the same data without the rule's condition still makes the violation),
so a test cannot pass because the violation was never produced:

- stable-mark axis (RD→ИД): a mark missing from the room but printed elsewhere on the ИД copy of the sheet is an
  attribution disagreement, not an absence;
- title-authoritative coverage: a heating plan never proves «no ventilation» in a room drawn on it;
- bridged axis (PD→ИД over RD): rooms that RD covers are compared on PD→RD and RD→ИД only;
- anchor present: a room that still shows the element by its anchor phrase («М.О.») is not missing it;
- family ambiguity counts only the differing labels (no hedge for a vent chamber holding units and branches).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from inspector_compare.engine import CompareEngine, compare_object

VENT_ID = "План 1-го этажа (вентиляция)"
CODE = "SYN/1-РД-ОВ1"


def _violations(result: Any) -> set[tuple[str, str]]:
    return {
        (f["parameter_code"], f["location"])
        for f in result.findings
        if f["violation_label"] == "VIOLATION_PRESENT"
    }


def _abstained(result: Any, room: str) -> list[dict[str, Any]]:
    return [a for a in result.trace["abstained"] if a.get("location") == room]


def _rd_id_pair(syn: Any, id_tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """RD plan p5 and its ИД copy (F9005 p1, same sheet): RD 101 has В1.1, 102 has В1.2."""
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(5, 5, VENT_ID, CODE)],
        rooms=[syn.room(r, 5) for r in ("101", "102")],
        tags=[
            syn.tag("В1.1", "VENT_SYSTEM", 5, "101", xy=(0.2, 0.2)),
            syn.tag("В1.2", "VENT_SYSTEM", 5, "102", xy=(0.6, 0.2)),
        ],
    )
    id_ = syn.layout(
        "F9005",
        "ID",
        titles=[syn.title(1, 5, VENT_ID, CODE, stage="ID")],
        rooms=[syn.room(r, 1) for r in ("101", "102")],
        tags=id_tags,
    )
    return [rd, id_]


def test_stable_marks_rd_id_attribution_is_not_absence(tmp_path: Path, cfg: Any, syn: Any) -> None:
    # the ИД copy prints В1.1 but the layout linked it to room 102: no evidence that 101 lost its branch
    moved = _rd_id_pair(
        syn,
        [
            syn.tag("В1.1", "VENT_SYSTEM", 1, "102", xy=(0.2, 0.2)),
            syn.tag("В1.2", "VENT_SYSTEM", 1, "102", xy=(0.6, 0.2)),
        ],
    )
    result = compare_object(syn.make_context(tmp_path, moved), cfg)
    assert ("IOS4-078", "101") not in _violations(result)
    assert any(a["reason"] == "AMBIGUOUS_VALUE" and a["axis"] == "RD_ID" for a in _abstained(result, "101"))
    # positive twin: the mark is gone from the whole ИД sheet → a real as-built absence
    gone = _rd_id_pair(syn, [syn.tag("В1.2", "VENT_SYSTEM", 1, "102", xy=(0.6, 0.2))])
    assert ("IOS4-078", "101") in _violations(compare_object(syn.make_context(tmp_path / "b", gone), cfg))
    # the rule is per axis: without RD_ID among the stable axes the attribution noise is a violation
    loose = dataclasses.replace(cfg, stable_mark_axes=())
    assert ("IOS4-078", "101") in _violations(compare_object(syn.make_context(tmp_path / "c", moved), loose))


def test_heating_sheet_never_proves_no_ventilation(tmp_path: Path, cfg: Any, syn: Any) -> None:
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(6, 6, "План 2-го этажа (вентиляция)", CODE)],
        rooms=[syn.room("201", 6)],
        tags=[syn.tag("В5.1", "VENT_SYSTEM", 6, "201")],
    )
    heating = syn.layout(
        "F9005",
        "ID",
        titles=[syn.title(1, 4, "План 2-го этажа (отопление)", "SYN/1-РД-ОВ2", stage="ID")],
        rooms=[syn.room("201", 1), syn.room("202", 1, xy=(0.8, 0.8))],
        # a vent-shaft mark in another room makes the heating sheet «relevant» to ventilation by its tags
        tags=[syn.tag("В20", "VENT_SYSTEM", 1, "202", xy=(0.8, 0.8))],
    )
    result = compare_object(syn.make_context(tmp_path, [rd, heating]), cfg)
    assert ("IOS4-078", "201") not in _violations(result)
    assert any(a["reason"] == "ELEMENT_KEY_UNRESOLVED" for a in _abstained(result, "201"))
    # positive twin: with coverage by layers/tags (the M1.2 rule) the heating sheet «proves» the absence
    old = dataclasses.replace(cfg, title_authoritative_coverage=False)
    assert ("IOS4-078", "201") in _violations(
        compare_object(syn.make_context(tmp_path / "b", [rd, heating]), old)
    )


def test_pd_id_is_compared_only_where_rd_does_not_cover_the_room(tmp_path: Path, cfg: Any, syn: Any) -> None:
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(10, 10, syn.VENT_PD, stage="PD")],
        rooms=[syn.room("101", 10, "SCHEMATIC_LABEL")],
        tags=[syn.tag("В1.1", "VENT_SYSTEM", 10, "101")],
    )
    # RD renumbers the branch (context); the ИД copy prints В1.5 but links it to room 102 (attribution noise)
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(5, 5, VENT_ID, CODE)],
        rooms=[syn.room(r, 5) for r in ("101", "102")],
        tags=[syn.tag("В1.5", "VENT_SYSTEM", 5, "101", xy=(0.2, 0.2))],
    )
    id_ = syn.layout(
        "F9005",
        "ID",
        titles=[syn.title(1, 5, VENT_ID, CODE, stage="ID")],
        rooms=[syn.room(r, 1) for r in ("101", "102")],
        tags=[syn.tag("В1.5", "VENT_SYSTEM", 1, "102", xy=(0.2, 0.2))],
    )
    result = compare_object(syn.make_context(tmp_path, [pd, rd, id_]), cfg)
    assert not any(
        f["axis"] == "PD_ID" for f in result.findings if f["violation_label"] == "VIOLATION_PRESENT"
    )
    assert ("IOS4-078", "101") not in _violations(result)
    # positive twin: the direct PD→ИД comparison (no bridge) reports the room as missing its branch
    direct = dataclasses.replace(cfg, bridged_axes={})
    assert ("IOS4-078", "101") in _violations(
        compare_object(syn.make_context(tmp_path / "b", [pd, rd, id_]), direct)
    )


def test_anchor_phrase_keeps_the_element_present(tmp_path: Path, cfg: Any, syn: Any) -> None:
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(10, 10, syn.VENT_PD, stage="PD")],
        rooms=[syn.room("189", 10, "SCHEMATIC_LABEL")],
        tags=[syn.tag("В17.1", "VENT_SYSTEM", 10, "189")],
    )

    def rd_with(tags: list[dict[str, Any]]) -> dict[str, Any]:
        return syn.layout(
            "F9002", "RD", titles=[syn.title(5, 5, VENT_ID, CODE)], rooms=[syn.room("189", 5)], tags=tags
        )

    # the local exhaust is drawn («М.О.», местный отсос) but its system mark is not printed in the room
    shown = rd_with([syn.tag("М.О.", "EQUIPMENT", 5, "189")])
    result = compare_object(syn.make_context(tmp_path, [pd, shown]), cfg)
    assert ("IOS4-078", "189") not in _violations(result)
    assert any(a["reason"] == "AMBIGUOUS_VALUE" for a in _abstained(result, "189"))
    # positive twin: no mark and no «М.О.» → the local exhaust is missing
    bare = rd_with([syn.tag("АМН-К 200х150", "AIR_TERMINAL", 5, "189")])
    assert ("IOS4-078", "189") in _violations(
        compare_object(syn.make_context(tmp_path / "b", [pd, bare]), cfg)
    )


def test_vent_chamber_with_units_and_branches_is_not_family_ambiguous(
    tmp_path: Path, cfg: Any, syn: Any
) -> None:
    """Supply units split (П17 → П17.1 + П17.2) in a chamber that also has an unchanged exhaust branch: the differing
    labels are supply units only, so no IOS4-078 hedge twin is emitted for the IOS4-079 finding. Five rooms missing
    their local exhaust make the hedge budget (20 % of the critical checks) large enough for one twin, so only the
    ambiguity rule decides."""
    others = [f"10{i}" for i in range(1, 6)]
    pd = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(26, 26, "Принципиальная схема систем общеобменной вентиляции", stage="PD")],
        rooms=[syn.room("012", 26, "SCHEMATIC_LABEL", name="Венткамера")]
        + [syn.room(r, 26, "SCHEMATIC_LABEL", xy=(0.1 * i, 0.9)) for i, r in enumerate(others, 1)],
        tags=[
            syn.tag("П17", "EQUIPMENT", 26, "012"),
            syn.tag("П2", "EQUIPMENT", 26, "012", xy=(0.4, 0.5)),
            syn.tag("В2.1", "VENT_SYSTEM", 26, "012", xy=(0.3, 0.5)),
        ]
        + [syn.tag(f"В1.{i}", "VENT_SYSTEM", 26, r, xy=(0.1 * i, 0.9)) for i, r in enumerate(others, 1)],
    )
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(4, 4, "План подвала (вентиляция)", CODE)],
        rooms=[syn.room("012", 4, name="Венткамера")]
        + [syn.room(r, 4, xy=(0.1 * i, 0.9)) for i, r in enumerate(others, 1)],
        tags=[
            syn.tag("П17.1, 17.2", "EQUIPMENT", 4, "012"),
            syn.tag("П2", "EQUIPMENT", 4, "012", xy=(0.4, 0.5)),
            syn.tag("В2.1", "VENT_SYSTEM", 4, "012", xy=(0.3, 0.5)),
        ],
    )
    result = compare_object(syn.make_context(tmp_path, [pd, rd]), cfg)
    assert _violations(result) == {("IOS4-079", "012")} | {("IOS4-078", r) for r in others}
    assert not [g for g in result.groups if g.get("hedge_kind")]
    # the room itself holds elements of two families on the PD side (the M1.2 rule called that ambiguous and, with
    # this budget, emitted an IOS4-078 twin); the differing labels belong to the supply units only
    engine = CompareEngine(syn.make_context(tmp_path / "b", [pd, rd]), cfg)
    diff = next(
        d for g in engine.run_comparators() if g.code == "IOS4-079" for d in g.diffs if d.room == "012"
    )
    held = {
        f
        for f in cfg.families
        if (v := engine.obs.views.get(("PD", f))) is not None
        and "012" in v.rooms
        and v.rooms["012"].element_pages
    }
    assert (
        "VENT_SUPPLY_UNIT" in held and len(held) >= 2
    )  # supply units + the exhaust unit «В2.1» of the chamber
    assert engine._families_of_room(diff) == {"VENT_SUPPLY_UNIT"}


def test_family_elements_come_from_its_own_discipline(tmp_path: Path, cfg: Any, syn: Any) -> None:
    """A КР document that happens to print a vent mark in a room (an automation or structural plan showing the
    ducts) is not the ventilation design: with discipline scoping only the ОВ volume counts."""
    ov = syn.layout(
        "F9001",
        "PD",
        titles=[syn.title(10, 10, syn.VENT_PD, stage="PD")],
        rooms=[syn.room("101", 10, "SCHEMATIC_LABEL")],
        tags=[syn.tag("В1.1", "VENT_SYSTEM", 10, "101")],
    )
    other = syn.layout(
        "F9004",
        "PD",
        titles=[syn.title(5, 5, "План расположения оборудования 1-го этажа", stage="PD")],
        rooms=[syn.room("101", 5)],
        tags=[syn.tag("В1.2", "VENT_SYSTEM", 5, "101")],
    )
    rd = syn.layout(
        "F9002",
        "RD",
        titles=[syn.title(5, 5, VENT_ID, CODE)],
        rooms=[syn.room("101", 5)],
        tags=[syn.tag("В1.1", "VENT_SYSTEM", 5, "101")],
    )
    assert ("IOS4-078", "101") not in _violations(
        compare_object(syn.make_context(tmp_path, [ov, other, rd]), cfg)
    )
    # positive twin: read from every document, the КР mark doubles the PD branch count (2 → 1: changed)
    loose = dataclasses.replace(cfg, discipline_scoped_families=False)
    assert ("IOS4-078", "101") in _violations(
        compare_object(syn.make_context(tmp_path / "b", [ov, other, rd]), loose)
    )


def _chamber(
    syn: Any, file_id: str, stage: str, page: int, title: str, rooms: dict[str, list[tuple[str, str]]]
) -> Any:
    return syn.layout(
        file_id,
        stage,
        titles=[syn.title(page, page, title, None if stage == "PD" else CODE, stage=stage)],
        rooms=[syn.room(r, page, name=name) for r, (name, _) in ((r, v[0]) for r, v in rooms.items())],
        tags=[
            syn.tag(label, kind, page, r, xy=(0.1 + 0.05 * i, 0.5))
            for r, v in rooms.items()
            for i, (label, kind) in enumerate(v[1:])
        ],
    )


def test_vent_chamber_marks_are_units_not_branches(tmp_path: Path, cfg: Any, syn: Any) -> None:
    """В9.1/В9.2 in a vent chamber are the fans standing there: the unit family compares them (IOS4-079); the branch
    family (IOS4-078) does not read them again."""
    rooms_pd = {"403": [("Венткамера", ""), ("В9.1", "VENT_SYSTEM"), ("В9.2", "VENT_SYSTEM")]}
    rooms_rd = {"403": [("Венткамера", ""), ("В9.1", "VENT_SYSTEM")]}
    pd = _chamber(syn, "F9001", "PD", 10, syn.VENT_PD, rooms_pd)
    rd = _chamber(syn, "F9002", "RD", 8, "План кровли (вентиляция)", rooms_rd)
    assert _violations(compare_object(syn.make_context(tmp_path, [pd, rd]), cfg)) == {("IOS4-079", "403")}
    fams = dict(cfg.families)
    fams["VENT_EXHAUST_BRANCH"] = dataclasses.replace(
        fams["VENT_EXHAUST_BRANCH"], exclude_room_name_pattern=None
    )
    both = compare_object(syn.make_context(tmp_path / "b", [pd, rd]), dataclasses.replace(cfg, families=fams))
    assert ("IOS4-078", "403") in _violations(both)


def test_unit_moved_to_another_vent_chamber_is_context(tmp_path: Path, cfg: Any, syn: Any) -> None:
    pd = _chamber(
        syn,
        "F9001",
        "PD",
        10,
        syn.VENT_PD,
        {"403": [("Венткамера", ""), ("В9.1", "VENT_SYSTEM"), ("В10.5", "VENT_SYSTEM")]},
    )

    def rd_with(neighbour: str) -> Any:
        return _chamber(
            syn,
            "F9002",
            "RD",
            8,
            "План кровли (вентиляция)",
            {
                "403": [("Венткамера", ""), ("В9.1", "VENT_SYSTEM")],
                "404": [(neighbour, ""), ("В10.5", "VENT_SYSTEM")],
            },
        )

    moved = compare_object(syn.make_context(tmp_path, [pd, rd_with("Венткамера")]), cfg)
    assert ("IOS4-079", "403") not in _violations(moved)
    assert any(c.get("location") == "403" and c.get("outcome") == "RELOCATED" for c in moved.trace["context"])
    # positive twin: in a corridor «В10.5» is a duct mark, not the unit: the fan is gone from the chamber
    gone = compare_object(syn.make_context(tmp_path / "b", [pd, rd_with("Коридор")]), cfg)
    assert ("IOS4-079", "403") in _violations(gone)
