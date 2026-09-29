"""Room index and inventories on the Тюменская gold pages (AG-02B-2; 96 R-15, 95 RT-04/RT-09).

Fast data tests use the PDF text layer only (PD tags and all room numbers are text). The RD inventories need
PageTokens (outlined tags): they read the recognition run named by ``INSPECTOR_LAYOUT_TOKENS_RUN`` (default
``m1-ag02b2-tokens``, produced by ``inspector-batch --run-id m1-ag02b2-tokens recognize --object
OBJ-TYUMENSKAYA-5-GOLD-SEED --files F0171 F0201 F0202 --pages …``) and skip when it is absent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from inspector_common.paths import repo_root
from inspector_common.settings import Settings

pytestmark = pytest.mark.data
OBJECT = "OBJ-TYUMENSKAYA-5-GOLD-SEED"


@pytest.fixture(scope="module")
def files() -> dict[str, Path]:
    paths = Settings().paths
    if not paths.documents_root.is_dir():
        pytest.skip("organizer data not found")
    from inspector_docproc.inputs import select_files

    jobs, _ = select_files(paths, [OBJECT], ["F0171", "F0201", "F0202"])
    if len(jobs) != 3:
        pytest.skip("gold files missing")
    return {j.file_id: j.path for j in jobs}


@pytest.fixture(scope="module")
def fixtures() -> dict:
    p = repo_root() / "docs/analysis/95_tyumen_dev_fixtures.json"
    if not p.is_file():
        pytest.skip("95 fixtures not found")
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vocab(files: dict[str, Path]):
    """The closed vocabulary of the object as the batch builds it: vent marks of the PD text layers."""
    from inspector_layout.rooms.fileproc import text_layer_vocabulary

    return text_layer_vocabulary([files["F0171"]])


def _page(files: dict[str, Path], fid: str, page: int, tokens: Path | None = None, vocab=None):
    import pymupdf

    from inspector_layout.rooms.page import process_page

    pymupdf.TOOLS.mupdf_display_errors(False)
    with pymupdf.open(files[fid]) as doc:
        return process_page(doc[page - 1], page, tokens, vocab)


def _inv(result, room: str):
    from inspector_layout.rooms.inventory import RoomInventory

    inv = RoomInventory(None, result.page_no, room)
    inv.items = [t for t in result.tags if t["room_token"] == room]
    return inv


def _labels(result) -> dict[str, dict]:
    return {r["room_token"]: r for r in result.rooms if r["source"] in ("PLAN_LABEL", "SCHEMATIC_LABEL")}


def test_pd_ventilation_scheme_rooms_and_local_exhausts(files, fixtures) -> None:
    r = _page(files, "F0171", 88)
    labels = _labels(r)
    expected = fixtures["page_facts"]["F0171:88"]["anchors"]["pd_local_exhaust_tags"]
    for room, tags in expected.items():
        assert room in labels and labels[room]["zone"], room
        assert _inv(r, room).branches == sorted(tags, key=lambda t: int(t.split(".")[1])), room
        assert _inv(r, room).local_exhausts >= 1


def test_pd_supply_units_of_vent_chamber_012(files, fixtures) -> None:
    """RT-09: supply-unit tags inside the 012 wall interval of PD л.26."""
    r = _page(files, "F0171", 104)
    want = set(fixtures["page_facts"]["F0171:104"]["anchors"]["supply_units_in_012_text_layer"])
    inv = _inv(r, "012")
    assert set(inv.branches) | set(inv.systems) == want
    assert "П20" in _inv(r, "007").systems  # the unit outside 012 stays outside


def test_pd_scheme_room_names(files) -> None:
    """Names printed under right-aligned numbers («012» / «Венткамера») and names continued on the next line."""
    labels = _labels(_page(files, "F0171", 88))
    assert labels["012"]["name"] == "Венткамера" and labels["012.1"]["name"] == "Форкамера"
    assert labels["140"]["name"] == "Физического эксперимента"
    assert labels["142"]["name"] == "Астрономии и физики"
    assert labels["314"]["name"] == "Схемотехники и микроэлектроники"
    assert _labels(_page(files, "F0171", 104))["012"]["name"] == "Венткамера"


def test_pd_warm_floor_rooms(files) -> None:
    r = _page(files, "F0171", 99)
    labels = _labels(r)
    for room in ("267", "270", "271", "272"):
        assert room in labels
        assert "тёплый пол" in _inv(r, room).tags_of("warm_floor"), room
    assert labels["267"]["zone"] == labels["270"]["zone"]  # «267, 270»: one cell, two rooms


@pytest.mark.slow
def test_rd_heating_plan_revision_cloud_over_270_272(files) -> None:
    """RT-04: the «ОВ-Отопление-Изм. №3» cloud lies over rooms 270/272 of RD F0202 p17."""
    r = _page(files, "F0202", 17)
    labels = _labels(r)
    assert {"267", "270", "271", "272"} <= set(labels)
    assert labels["270"]["name"] == "Санузел с душем для МГН" and labels["267"]["area_m2"] == 13.7
    covering = [c for c in r.clouds if "270" in c["rooms_covered"]]
    assert len(covering) == 1
    cloud = covering[0]
    assert cloud["layer"] == "ОВ-Отопление-Изм. №3" and set(cloud["rooms_covered"]) == {"270", "272"}
    assert cloud["bbox"] == pytest.approx([0.337, 0.687, 0.423, 0.718], abs=0.004)


@pytest.mark.slow
def test_rd_room_314_is_drawn_on_page_20(files) -> None:
    r = _page(files, "F0201", 20)
    labels = _labels(r)
    assert labels["314"]["source"] == "PLAN_LABEL" and labels["314"]["floor"] == "3" and labels["314"]["zone"]


def test_rd_basement_012(files) -> None:
    r = _page(files, "F0201", 17)
    labels = _labels(r)
    assert labels["012"]["name"] == "Венткамера" and r.floor == "подвал"
    assert "12" not in labels  # the zero is kept


def _tokens_dir(fid: str) -> Path:
    run = os.environ.get("INSPECTOR_LAYOUT_TOKENS_RUN", "m1-ag02b2-tokens")
    d = Settings().paths.runs_root / run / "tokens" / fid
    if not d.is_dir():
        pytest.skip(f"PageTokens of {fid} not found in runs/{run}/tokens")
    return d


@pytest.mark.slow
def test_rd_first_floor_inventories(files, vocab) -> None:
    """G-TR-003/004 on RD F0201 p18: 140/142 without local exhausts, 147 and 198 with their new branches."""
    tdir = _tokens_dir("F0201")
    r = _page(files, "F0201", 18, tdir / "p00018.json.gz", vocab)
    for room in ("140", "142", "147", "198"):
        assert room in _labels(r)
    assert _inv(r, "140").branches == [] and _inv(r, "142").branches == []
    assert _inv(r, "147").branches == ["В2.2", "В2.3", "В2.4"]
    assert _inv(r, "198").branches == ["В2.8", "В2.9", "В2.10"]
    assert {"П2", "ВЕ"} <= set(_inv(r, "198").systems)  # «П2/ВЕ ±150» read by OCR as «12/BE»
    assert {"В2.7", "В2.8", "В2.9"} <= set(_inv(r, "141").branches)  # the exhausts moved from 140 (95 §3.3)


@pytest.mark.slow
def test_rd_third_floor_314_and_vent_chamber_012(files, vocab) -> None:
    tdir = _tokens_dir("F0201")
    r20 = _page(files, "F0201", 20, tdir / "p00020.json.gz", vocab)
    assert _inv(r20, "314").branches == ["В3.1"]
    r17 = _page(files, "F0201", 17, tdir / "p00017.json.gz", vocab)
    inv = _inv(r17, "012")
    assert {"П17.1", "П17.2"} <= set(inv.branches) and "П17" not in inv.systems  # П17 split into two units
    # RT-02: every supply unit of the chamber, «П9» included (outlined «П9» is read as «119», conf 0.69)
    assert {"П2.1", "П3", "П8", "П9", "П10", "П15", "П17.1", "П17.2", "П18"} <= set(
        inv.branches + inv.systems
    )
    assert "В2" not in inv.systems  # the red «В2» in 012 is its fire category (room-category layer)
    # «В2.1» above the chamber (read «32.1» on the leader layer) is repaired from the closed vocabulary
    assert any(t["tag"] == t["tag_norm"] == "В2.1" for t in r17.tags)
    (p9,) = [t for t in r17.tags if t["tag_norm"] == "П9" and t["room_token"] == "012"]
    assert p9["tag"] == "П9" and p9["provenance"]["confidence"] <= 0.7  # the repaired reading, flagged


@pytest.mark.slow
def test_rd_system_tables_are_not_explications(files) -> None:
    """F0201 p15-16 «Характеристика систем» list served rooms next to fan types: no explication rows."""
    tdir = _tokens_dir("F0201")
    for page in (15, 16):
        r = _page(files, "F0201", page, tdir / f"p{page:05d}.json.gz")
        assert not [x for x in r.rooms if x["source"] == "EXPLICATION_TABLE"], page
    r18 = _page(files, "F0201", 18, tdir / "p00018.json.gz")
    expl = {x["room_token"] for x in r18.rooms if x["source"] == "EXPLICATION_TABLE"}
    assert len(expl) >= 95 and {"167а", "140", "198"} <= expl  # sub-zones «167а -эстрада…» are rooms


@pytest.mark.slow
def test_heating_scheme_tags_against_adjudicated_gt(files, tmp_path) -> None:
    """D02 of ocr_gt_v2 (F0202 p19): risers, radiators and pipelines read from outlined text."""
    gt = repo_root() / "docs/analysis/gt_staging/ocr_gt_v2.json"
    if not gt.is_file():
        pytest.skip("ocr_gt_v2 not found")
    from inspector_layout.rooms.bench import gt_tag_benchmark
    from inspector_layout.rooms.fileproc import assemble

    tdir = _tokens_dir("F0202")
    r = _page(files, "F0202", 19, tdir / "p00019.json.gz")
    layout = {"file_id": "F0202", **assemble([r], [])}
    res = gt_tag_benchmark(gt, {"F0202": layout})
    (page,) = res["pages"]
    assert page["recall"] >= 0.9 and page["precision"] >= 0.98, page
