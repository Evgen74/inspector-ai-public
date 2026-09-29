"""Room index, counterparts, labels and the tag benchmarks on hand-built pages (AG-02B-2; fast, no data)."""

from __future__ import annotations

import json
from pathlib import Path

from inspector_layout.cad.geometry import PageFrame
from inspector_layout.rooms.bench import (
    evaluate_counterparts,
    evaluate_tag_checks,
    fixture_tag_checks,
    gt_tag_benchmark,
)
from inspector_layout.rooms.grammar import LIST_SEP
from inspector_layout.rooms.index import RoomIndex, sheet_overlap, title_topic
from inspector_layout.rooms.labels import _is_explication, detect_labels
from inspector_layout.rooms.tokens import Line, PageText, Tok, _fill_lines

# ── hand-built layouts: a PD scheme of floors 1–3, RD vent plans of floors 1 and 3, an RD heating plan ─────


def _room(token: str, page: int, source: str = "PLAN_LABEL", floor: str | None = None) -> dict:
    n = int(token[-2:]) if token[-2:].isdigit() else 0
    return {"room_token": token, "pdf_page_number": page, "bbox": [0.01 * n, 0.1, 0.01 * n + 0.005, 0.105],
            "zone": [[0.0, 0.0], [0.1, 0.0], [0.1, 0.1]], "source": source, "floor": floor}  # fmt: skip


def _tag(tag: str, norm: str, kind: str, page: int, room: str | None, bbox=(0.5, 0.5, 0.51, 0.51)) -> dict:
    return {"tag": tag, "tag_norm": norm, "tag_kind": kind, "pdf_page_number": page, "bbox": list(bbox),
            "room_token": room, "room_link": "LEADER" if room else None,
            "provenance": {"text_source": "OCR", "confidence": 0.95}}  # fmt: skip


def _layout(file_id: str, stage: str, rooms: list[dict], tags: list[dict], pages: dict[int, str]) -> dict:
    return {"file_id": file_id, "stage": stage, "rooms": rooms, "tags": tags, "revision_clouds": [],
            "ext": {"rooms_stage": {"pages": [{"page": p, "kind": k, "floor": None, "title": None}
                                              for p, k in pages.items()]}}}  # fmt: skip


def _layouts() -> dict[str, dict]:
    pd_rooms = [_room(r, 10, "SCHEMATIC_LABEL") for r in ["101", "102", "103", "104"]]
    pd_rooms += [_room(str(r), 10, "SCHEMATIC_LABEL") for r in range(201, 221)]
    pd_rooms += [_room(r, 10, "SCHEMATIC_LABEL") for r in ["301", "302", "303", "304"]]
    pd_tags = [
        _tag("B2.4,5", LIST_SEP.join(["В2.4", "В2.5"]), "VENT_SYSTEM", 10, "101"),
        _tag("тёплый пол", "тёплый пол", "HEATING_SYSTEM", 10, "103"),
        _tag("B3.1", "В3.1", "VENT_SYSTEM", 10, "301"),
    ]
    pd = _layout("F9001", "PD", pd_rooms, pd_tags, {10: "SCHEMATIC"})
    vent = [_room(str(r), 18, floor="1") for r in range(101, 121)]
    vent += [_room(str(r), 23, floor="1") for r in range(101, 121)]  # the duplicate sheet, without marks
    vent += [_room(str(r), 20, floor="3") for r in range(301, 316)]
    vent_tags = [
        _tag("B2.4", "В2.4", "VENT_SYSTEM", 18, "101"),
        _tag("П2", "П2", "VENT_SYSTEM", 18, "102"),
        _tag("B3.1", "В3.1", "VENT_SYSTEM", 20, "301"),
    ]
    rd_vent = _layout("F9002", "RD", vent, vent_tags, {18: "PLAN", 20: "PLAN", 23: "PLAN"})
    heat = [_room(str(r), 16, floor="1") for r in range(101, 121)]
    heat_tags = [
        _tag("22-500-700", "22-500-700", "EQUIPMENT", 16, "103", (0.2, 0.2, 0.21, 0.21)),
        _tag("Ст1", "Ст1", "PIPE_RISER", 16, "103", (0.3, 0.3, 0.31, 0.31)),
        _tag("Ст1", "Ст1", "PIPE_RISER", 16, "104", (0.3, 0.3, 0.31, 0.31)),  # the same mark, two rooms
        _tag("T11", "Т11", "HEATING_SYSTEM", 16, None, (0.4, 0.4, 0.41, 0.41)),
    ]
    rd_heat = _layout("F9003", "RD", heat, heat_tags, {16: "PLAN"})
    return {"F9001": pd, "F9002": rd_vent, "F9003": rd_heat}


def test_floor_partitioned_sheet_matching() -> None:
    idx = RoomIndex.from_layouts(_layouts().values())
    a, b18 = idx.pages[("F9001", 10)], idx.pages[("F9002", 18)]
    # whole pages: 4 shared of min(28, 20) = 0.2 — a multi-floor scheme never matches a floor plan that way
    assert len(a.rooms & b18.rooms) / min(len(a.rooms), len(b18.rooms)) < 0.3
    assert sheet_overlap(a, b18) == (1.0, {"101", "102", "103", "104"}, "1")
    matches = {(m.b_file, m.b_page): m for m in idx.match_sheets("PD", "RD")}
    assert matches[("F9002", 18)].basis_floor == "1" and matches[("F9002", 20)].basis_floor == "3"
    assert ("F9002", 20) in matches and matches[("F9002", 20)].overlap == 1.0
    assert matches[("F9002", 18)].as_dict()["basis_floor"] == "1"


def test_counterparts_follow_the_room_topic() -> None:
    idx = RoomIndex.from_layouts(_layouts().values())
    assert idx.pages[("F9002", 18)].topic == "vent" and idx.pages[("F9003", 16)].topic == "heating"
    vent = idx.counterparts("101", "F9001", 10)  # vent branches in 101 on the PD scheme
    assert [(c.file_id, c.pdf_page_number) for c in vent] == [("F9002", 18), ("F9002", 23), ("F9003", 16)]
    assert vent[0].marks == 1 and vent[1].marks == 0  # the duplicate sheet ties on overlap, loses on marks
    heat = idx.counterparts("103", "F9001", 10)  # a warm floor in 103: the heating plan comes first
    assert (heat[0].file_id, heat[0].pdf_page_number) == ("F9003", 16)
    assert idx.counterparts("301", "F9001", 10)[0].pdf_page_number == 20
    gold = [
        {"check_id": "T1", "room": "101", "evidence": [("PD", "F9001", 10), ("RD", "F9002", 18)]},
        {"check_id": "T2", "room": "103", "evidence": [("PD", "F9001", 10), ("RD", "F9003", 16)]},
        {"check_id": "T3", "room": "301", "evidence": [("PD", "F9001", 10), ("RD", "F9002", 18)]},
    ]
    res = evaluate_counterparts(idx, gold)
    assert [r["status"] for r in res["rows"]] == ["HIT", "HIT", "HIT_DRAWN"]  # 301 cited on p18, drawn on p20
    assert (res["hit"], res["hit_drawn"], res["n"]) == (2, 1, 3)


def test_title_topic() -> None:
    assert title_topic("План подвала (вентиляция)") == "vent"
    assert title_topic("План 2-го этажа. Отопление") == "heating"
    assert title_topic("Схема теплоснабжения приточных установок и вентиляции") == "mixed"
    assert title_topic("Общие данные") is None and title_topic(None) is None


def test_fixture_tag_checks(tmp_path: Path) -> None:
    fixtures = {
        "page_facts": {
            "F9001:10": {"anchors": {"pd_local_exhaust_tags": {"101": ["В2.4", "В2.5"], "102": ["В2.6"]}}},
            "F9002:18": {"anchors": {"rd_tags_ocr": {"101": ["В2.4 −150 м³/ч"], "102": ["П2/ВЕ ±400 м³/ч"]},
                                     "zone_012_bbox": [0.45, 0.45, 0.55, 0.55],
                                     "ocr_tokens_text_layers_only_300dpi": ["В2.4 (OCR: B2.4)", "П2"]}},
        },
    }  # fmt: skip
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
    checks = fixture_tag_checks(path)
    assert {c["check"] for c in checks} == {"ROOM_BRANCHES_EXACT", "ROOM_ELEMENTS_RECALL", "ZONE_RECALL"}
    res = evaluate_tag_checks(_layouts(), checks)
    rows = {(r["check"], r.get("room")): r for r in res["rows"]}
    assert rows[("ROOM_BRANCHES_EXACT", "101")]["pass"]  # «B2.4,5» is one printed mark, two branches
    assert not rows[("ROOM_BRANCHES_EXACT", "102")]["pass"]
    assert rows[("ROOM_ELEMENTS_RECALL", "101")]["pass"]
    assert rows[("ROOM_ELEMENTS_RECALL", "102")]["missing"] == ["ВЕ"]
    assert rows[("ZONE_RECALL", None)]["pass"]
    assert res["passed"] == 3 and res["n"] == 5


def test_gt_tag_benchmark(tmp_path: Path) -> None:
    gt = {"pages": {"X01": {"file_id": "F9003", "pdf_page_number": 16, "lines": [
        {"text": "Ст1, Ст2"}, {"text": "22-500-700"}, {"text": "Т11 Т21"}, {"text": "Т1", "exclude_from_scoring": True},
    ]}}}  # fmt: skip
    path = tmp_path / "gt.json"
    path.write_text(json.dumps(gt, ensure_ascii=False), encoding="utf-8")
    res = gt_tag_benchmark(path, _layouts())
    (page,) = res["pages"]
    # expected Ст1, Ст2, 22-500-700, Т11, Т21; found Ст1 (once: two rooms, one printed mark), 22-500-700, Т11
    assert (page["expected"], page["found"], page["tp"]) == (5, 3, 3)
    assert res["recall"] == 0.6 and res["precision"] == 1.0
    assert sorted(page["missed"]) == ["Ст2", "Т21"]


# ── labels on hand-built text ─────────────────────────────────────────────────────────────────────────────


def _page_text(
    items: list[tuple[str, float, float, float, float]], lines: list[list[int]] | None = None
) -> PageText:
    toks = [Tok(i, t, x0, y0, x1, y1, 1.0, "TEXT_LAYER", font="ISOCPEUR", size=10.0) for i, (t, x0, y0, x1, y1) in
            enumerate(items)]  # fmt: skip
    page = PageText(1, PageFrame(1190.0, 842.0, (1, 0, 0, 1, 0, 0)), toks,
                    [Line(n, ids, "", "TEXT_LAYER") for n, ids in enumerate(lines or [])])  # fmt: skip
    _fill_lines(page)
    return page


def test_room_names_under_right_aligned_numbers_and_continuations() -> None:
    page = _page_text(
        [
            ("012", 100, 100, 118, 110),
            ("Венткамера", 60, 112, 118, 122),  # right-aligned under the number (F0171 p88)
            ("140", 300, 100, 318, 110),
            ("Физического", 321, 100, 390, 110),
            ("эксперимента", 300, 112, 380, 122),  # continues the name, under the number
            ("147", 500, 100, 518, 110),
            ("Кабинет", 521, 100, 560, 110),
            ("Примечание", 500, 112, 570, 122),  # a capitalised line below is not a continuation
        ],
        lines=[[2, 3], [5, 6]],
    )
    labels = {lab.rooms[0]: lab for lab in detect_labels(page, []).plan_labels}
    assert labels["012"].name == "Венткамера"
    assert labels["140"].name == "Физического эксперимента"
    assert labels["147"].name == "Кабинет"


def _rows(names: list[str | None], areas: list[float | None]) -> list:
    return [
        (Tok(i, str(100 + i), 0, 0, 1, 1, 1.0, "OCR"), n, a)
        for i, (n, a) in enumerate(zip(names, areas, strict=True))
    ]


def test_explication_needs_room_rows() -> None:
    rooms = ["Коридор", "Санузел", "Венткамера", "Учебный кабинет", "Лестница"]
    fans = ["Канальный", "Канальный", "Крышный", "Канальный", "Радиальный"]
    assert _is_explication(_rows(rooms, [12.5, 3.0, 86.4, 50.1, 25.8]), has_caption=True)
    assert _is_explication(_rows(rooms, [12.5, 3.0, 86.4, 50.1, 25.8]), has_caption=False)
    assert _is_explication(_rows(rooms, [None] * 5), has_caption=True)  # captioned, names only
    assert not _is_explication(_rows(rooms, [None] * 5), has_caption=False)
    # «Характеристика систем» (F0201 p15-16): served rooms next to fan types and powers
    assert not _is_explication(_rows(fans, [0.23, 1.6, 0.74, None, 0.06]), has_caption=False)
    # a specification caption over positions (F0202 p21)
    assert not _is_explication(_rows(["Термометр", "Термометр", None, None], [None] * 4), has_caption=True)
