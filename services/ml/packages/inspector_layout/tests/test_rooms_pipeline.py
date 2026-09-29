"""Room/CAD pipeline on a synthetic CAD sheet (AG-02B-2): labels, zones, leaders, clouds, contract output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspector_common.contracts.loader import validate
from inspector_layout.rooms.bench import evaluate_gold, explication_crosscheck, token_em
from inspector_layout.rooms.fileproc import (
    FileInput,
    assemble,
    build_layout_artifacts,
    layout_sections,
    merge_fragment,
    process_file,
    select_pages,
)
from inspector_layout.rooms.index import RoomIndex
from inspector_layout.rooms.inventory import inventories, room_inventories, tag_subkind
from inspector_layout.rooms.page import process_page
from inspector_layout.rooms.synth import vent_plan_pdf
from inspector_layout.rooms.zones import orient_clockwise


@pytest.fixture(scope="module")
def plan(tmp_path_factory) -> Path:
    return vent_plan_pdf(tmp_path_factory.mktemp("synth") / "plan.pdf")


@pytest.fixture(scope="module")
def page_result(plan: Path):
    import pymupdf

    with pymupdf.open(plan) as doc:
        return process_page(doc[0], 1, None)


def test_rooms_labels_and_zones(page_result) -> None:
    r = page_result
    assert r.kind == "PLAN" and r.floor == "1" and r.zone_method == "WALLS"
    plan = {x["room_token"]: x for x in r.rooms if x["source"] == "PLAN_LABEL"}
    assert set(plan) == {"101", "102", "012"}  # «012» keeps its zero
    assert plan["012"]["name"] == "Венткамера" and plan["012"]["area_m2"] == 30.1
    for x in plan.values():
        xs = [p[0] for p in x["zone"]]
        ys = [p[1] for p in x["zone"]]
        cx, cy = (x["bbox"][0] + x["bbox"][2]) / 2, (x["bbox"][1] + x["bbox"][3]) / 2
        assert min(xs) < cx < max(xs) and min(ys) < cy < max(ys)
    # 101 and 102 are split by the partition (x = 310 pt of 1190), 012 lies under the 320 pt wall
    assert max(p[0] for p in plan["101"]["zone"]) < 312 / 1190
    assert min(p[0] for p in plan["102"]["zone"]) > 309 / 1190
    assert min(p[1] for p in plan["012"]["zone"]) > 319 / 842
    expl = {x["room_token"]: x for x in r.rooms if x["source"] == "EXPLICATION_TABLE"}
    assert set(expl) == {"101", "102", "012", "103"} and expl["102"]["name"] == "Лаборантская"


def test_tags_follow_leaders(page_result) -> None:
    tags = {(t["tag_norm"], t["room_token"]): t["room_link"] for t in page_result.tags}
    assert tags[("В2.4", "102")] == "LEADER"  # printed in 101, its leader ends in 102
    assert ("В2.4", "101") not in tags
    assert tags[("П1", "101")] == "INSIDE"
    assert tags[("М.О.", "102")] == "INSIDE"
    # «В2.7,8,9» is one printed mark (contract: one TagInstance) standing for three branches
    (lst,) = [t for t in page_result.tags if t["room_token"] == "012"]
    assert lst["tag"] == "В2.7,8,9" and lst["tag_norm"] == "В2.7, В2.8, В2.9" and lst["system_code"] == "В2"


def test_cloud_covers_room(page_result) -> None:
    (cloud,) = page_result.clouds
    assert cloud["rooms_covered"] == ["102"] and cloud["revision_label"] == "Изм. №2"
    assert cloud["source"] == "OCG_LAYER" and cloud["confidence"] >= 0.9


def test_file_fragment_validates_and_merges(plan: Path, tmp_path: Path) -> None:
    fragment, results = process_file(FileInput("F9001", plan, None, None))
    assert [r.page_no for r in results] == [1]
    doc = build_layout_artifacts(file_id="F9001", object_id="OBJ-SYNTH", file_sha256="0" * 64, stage="RD",
                                 pages_total=1, fragment=fragment)  # fmt: skip
    validate("layout_artifacts", doc)
    assert "OCR_PARTIAL" in doc["warnings"]  # no PageTokens: text layer only
    # merging into a title-block document keeps its sections and adds the sheet number
    base = build_layout_artifacts(file_id="F9001", object_id="OBJ-SYNTH", file_sha256="0" * 64, stage="RD",
                                  pages_total=1, fragment={"rooms": [], "tags": [], "cad_layers": [],
                                                           "revision_clouds": [], "warnings": [],
                                                           "timings_ms": {}, "ext": {}})  # fmt: skip
    base["sheet_page_map"] = [{"pdf_page_number": 1, "sheet_number": 5, "basis": "TITLE_BLOCK"}]
    merged = merge_fragment(base, fragment)
    validate("layout_artifacts", merged)
    assert {r["sheet_number"] for r in merged["rooms"]} == {5}


def test_provider_hook(plan: Path, tmp_path: Path) -> None:
    tokens = tmp_path / "tokens"
    tokens.mkdir()
    frag = layout_sections(path=str(plan), file_id="F9001", object_id="OBJ-SYNTH", pages=[1],
                           tokens_dir=str(tokens), title_blocks=[{"pdf_page_number": 1,
                                                                  "sheet_title": "План 2-го этажа"}],
                           sheet_page_map=[{"pdf_page_number": 1, "sheet_number": 7}], workers=1)  # fmt: skip
    assert {r["sheet_number"] for r in frag["rooms"]} == {7}
    assert {r["floor"] for r in frag["rooms"]} == {"1"}  # the page's own title wins over the stamp
    # per-room inventories travel in ext for consumers without the grammar (the web viewer)
    inv = {(r["page"], r["room"]): r for r in frag["ext"]["rooms_stage"]["inventories"]}
    assert set(inv) == {(1, "101"), (1, "102"), (1, "012")}
    assert inv[(1, "012")]["branches"] == ["В2.7", "В2.8", "В2.9"] and inv[(1, "012")]["name"] == "Венткамера"
    assert inv[(1, "101")]["branches"] == [] and inv[(1, "101")]["systems"] == ["П1"]
    json.dumps(frag["ext"])
    assert set(frag) >= {"rooms", "tags", "cad_layers", "revision_clouds", "warnings", "timings_ms", "ext"}


def test_page_selection_skips_a4_text(tmp_path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_text((72, 72), "text")
    doc.new_page(width=1684, height=1190)
    with doc:
        assert select_pages(doc, None) == [2]
        assert select_pages(doc, [1]) == []


def _layout(plan: Path, file_id: str, stage: str) -> dict:
    fragment, _ = process_file(FileInput(file_id, plan, None, None))
    return build_layout_artifacts(file_id=file_id, object_id="OBJ-SYNTH", file_sha256="0" * 64, stage=stage,
                                  pages_total=1, fragment=fragment)  # fmt: skip


def test_inventories_index_and_bench(plan: Path) -> None:
    rd = _layout(plan, "F9002", "RD")
    inv = inventories(rd)
    assert set(room for _, room in inv) == {"101", "102", "012"}
    assert inv[(1, "102")].branches == ["В2.4"] and inv[(1, "102")].local_exhausts == 1
    assert inv[(1, "101")].branches == [] and inv[(1, "101")].systems == ["П1"]
    assert inv[(1, "012")].branches == ["В2.7", "В2.8", "В2.9"]
    assert tag_subkind({"tag_kind": "OTHER", "tag_norm": "L=-950"}) == "flow"
    assert tag_subkind({"tag_kind": "EQUIPMENT", "tag_norm": "М.О. поз.160"}) == "local_exhaust"
    pd = _layout(plan, "F9001", "PD")
    idx = RoomIndex.from_layouts([pd, rd])
    assert idx.pages_of("012") == [("F9001", 1), ("F9002", 1)]
    (m,) = idx.match_sheets("PD", "RD")
    assert (m.a_file, m.b_file, m.overlap) == ("F9001", "F9002", 1.0)
    assert [i.file_id for i in room_inventories([pd, rd], "102")] == ["F9001", "F9002"]
    gold = [{"check_id": "T1", "group": "G1", "room": "012", "evidence": [("RD", "F9002", 1)]},
            {"check_id": "T2", "group": "G1", "room": "999", "evidence": [("RD", "F9002", 1)]}]  # fmt: skip
    g = evaluate_gold({"F9002": rd}, gold)
    assert (g["located"], g["n"]) == (1, 2)
    em = token_em({"F9002": rd}, [{"file_id": "F9002", "pdf_page_number": 1, "room": "012",
                                   "point": [310 / 1190, 430 / 842], "anchor": "room_012"}])  # fmt: skip
    assert em["by_set"]["fixture_anchor"]["em"] == 1.0
    # a page read from the text layer alone is coverage, not token exactness: 103 is not on the plan
    assert "explication_row" not in em["by_set"]
    assert em["text_layer_only"] == {"pages": 1, "rows": 4, "located": 3}
    for page in rd["ext"]["rooms_stage"]["pages"]:
        page["tokens"] = "PAGE_TOKENS"  # as if recognised: the rows enter the EM set
    em = token_em({"F9002": rd}, [])
    assert em["by_set"]["explication_row"]["n"] == 4 and em["misses"][0]["room"] == "103"
    assert explication_crosscheck({"F9002": rd})["precision"] == 1.0
    json.dumps(g)  # the report is JSON-serialisable


def test_orient_clockwise_from_top_left() -> None:
    ccw = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]  # counter-clockwise on screen (y down)
    assert orient_clockwise(ccw) == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_object_vocabulary_is_cached_per_file(plan: Path, tmp_path: Path) -> None:
    from inspector_layout.rooms.fileproc import cached_file_vocabulary, is_vent_document

    cache = tmp_path / "vocab"
    tags = cached_file_vocabulary(plan, cache)
    assert {"В2.4", "П1", "В2.7", "В2.8", "В2.9"} <= tags  # text-layer marks of the synthetic plan
    (entry,) = cache.glob("*.json")
    entry.write_text('["В9.9"]', encoding="utf-8")
    assert cached_file_vocabulary(plan, cache) == {"В9.9"}  # served from the cache
    assert cached_file_vocabulary(plan, None) == tags
    assert is_vent_document("ПД/5.4 Отопление, вентиляц/V2_01-05-04-02-07_Том 5.4.2 ОВ (1).pdf")
    assert is_vent_document("Полные разделы/АНО-150321-1-РД-ОВ2.1_изм. 3_в1.pdf")
    assert not is_vent_document("ПД/3 Архитектурные решения/V2_01-03-00-01-20_Том 3.РЕД.pdf")
    assert not is_vent_document("Полные разделы/АНО1503211-РД-ВК изм. 2_в1.pdf")


def test_textless_sheets_skip_the_vector_pass(plan: Path, tmp_path: Path) -> None:
    """A drawing without a word (F0160 p63: 867 k paths) has nothing to anchor rooms or marks on."""
    import pymupdf

    path = tmp_path / "lines.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=1684, height=1190)
    for i in range(200):
        page.draw_line((10, 10 + 5 * i), (1600, 10 + 5 * i), color=(0, 0, 0), width=0.2)
    doc.save(path)
    doc.close()
    with pymupdf.open(path) as d:
        r = process_page(d[0], 1, None)
    assert r.skipped == "NO_ANCHORS" and not r.rooms and not r.tags and "drawings" not in r.timings_ms
    with pymupdf.open(plan) as d:
        assert process_page(d[0], 1, None).skipped is None
    frag = assemble([r], [])
    assert frag["ext"]["rooms_stage"]["pages"][0]["skipped"] == "NO_ANCHORS"


def test_weak_repair_evidence() -> None:
    from inspector_layout.rooms.tags import _mark_evidence
    from inspector_layout.rooms.tokens import Tok

    def tok(conf: float, layer: str | None, share: float = 1.0) -> Tok:
        return Tok(0, "32.1", 0, 0, 1, 1, conf, "OCR", layer=layer, layer_share=share)

    assert _mark_evidence(tok(0.98, "ОВ-Вентиляция-Выноски"))  # a vent label layer (F0201 p17)
    assert _mark_evidence(tok(0.98, "DUCT-Приток-TEXT"))
    assert not _mark_evidence(tok(0.98, "PDF2_Text"))  # plain text: may be an area
    assert not _mark_evidence(tok(0.98, "ОВ-Вентиляция-Выноски", share=0.3))  # the layer is uncertain
    assert not _mark_evidence(tok(0.98, None))
    assert _mark_evidence(tok(0.69, None))  # the recogniser itself was unsure («119» for «П9»)
