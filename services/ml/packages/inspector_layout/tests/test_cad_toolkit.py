"""CAD layer toolkit (AG-02B-2): layer classes, isolated renders, drawing index, leaders, clouds."""

from __future__ import annotations

from pathlib import Path

import pytest

from inspector_layout.cad.clouds import detect_clouds
from inspector_layout.cad.geometry import PageFrame, Seg, cluster_boxes, index_drawings
from inspector_layout.cad.layers import (
    discipline_hint,
    layer_catalog,
    layer_classes,
    only_layers,
    render_gray,
    revision_label,
)
from inspector_layout.cad.leaders import LeaderGraph, drop_glyph_strokes
from inspector_layout.rooms.synth import vent_plan_pdf


@pytest.mark.parametrize(
    ("name", "must"),
    [
        ("DUCT-Вытяжка-TEXT", {"DUCT", "TEXT", "LEADER"}),
        ("ОВ-Вентиляция-Выноски", {"LEADER"}),
        ("ОВ-Воздухообмены", {"AIRFLOW", "LEADER"}),
        ("ОВ-Архитектура", {"WALL"}),
        ("ОВ-Архитектура-П", {"WALL"}),
        ("S_перегородки", {"WALL"}),
        ("A-DOORS", {"DOOR"}),
        ("Glass_outline", {"WINDOW"}),
        ("АР_мебель", {"FURNITURE"}),
        ("ОВ-Отопление-Изм. №3", {"REVISION", "HEATING"}),
        ("ОВ-Изм.3", {"REVISION"}),
        ("ОВ-Категории помещений", {"CATEGORY"}),
    ],
)
def test_layer_classes(name: str, must: set[str]) -> None:
    assert must <= layer_classes(name)


def test_layer_labels() -> None:
    assert revision_label("ОВ-Отопление-Изм. №3") == "Изм. №3"
    assert revision_label("ОВ-Изм.2") == "Изм. №2"
    assert revision_label("ОВ-Текст") is None
    assert discipline_hint("ОВ-Текст") == "ОВ"
    assert discipline_hint("0 ОВ_текст ОД") == "ОВ"
    assert discipline_hint("DUCT-Приток") is None
    assert "WALL" not in layer_classes("ОВ-Архитектура-Изм") or "REVISION" in layer_classes(
        "ОВ-Архитектура-Изм"
    )


@pytest.fixture(scope="module")
def plan(tmp_path_factory) -> Path:
    return vent_plan_pdf(tmp_path_factory.mktemp("synth") / "plan.pdf")


def test_catalog_and_isolated_render(plan: Path) -> None:
    import pymupdf

    with pymupdf.open(plan) as doc:
        page = doc[0]
        cat = layer_catalog(doc, {1: ["АР-Стены", "ОВ-Изм. №2"]})
        layers = {c["name"]: c for c in cat.cad_layers()}
        assert set(layers) >= {"АР-Стены", "ОВ-Изм. №2", "DUCT-Вытяжка-TEXT"}
        assert (
            layers["ОВ-Изм. №2"]["is_revision_layer"] and layers["ОВ-Изм. №2"]["revision_label"] == "Изм. №2"
        )
        assert layers["DUCT-Вытяжка-TEXT"]["is_text_layer"] and layers["АР-Стены"]["pages"] == [1]
        full = render_gray(page, 0.5)
        with only_layers(doc, lambda n: "WALL" in layer_classes(n)) as off:
            walls = render_gray(page, 0.5)
        assert off == 5  # every layer but the walls
        assert (walls < 128).sum() < (full < 128).sum()  # labels and clouds hidden
        again = render_gray(page, 0.5)
        assert (again == full).all()  # visibility restored


def test_drawing_index_circles_arcs_segments(plan: Path) -> None:
    import pymupdf

    with pymupdf.open(plan) as doc:
        page = doc[0]
        idx = index_drawings(page, keep_segments=lambda n: "LEADER" in layer_classes(n),
                             keep_paths=lambda n: "REVISION" in layer_classes(n))  # fmt: skip
    assert len([c for c in idx.circles if c.layer == "АР_мебель"]) == 3
    assert all(abs(c.r - 10) < 0.5 for c in idx.circles)
    assert len([a for a in idx.arcs if a.layer == "ОВ-Изм. №2"]) == 12
    assert idx.segments["ОВ-Вентиляция-Выноски"]
    clouds = detect_clouds(idx)
    assert len(clouds) == 1 and clouds[0].source == "OCG_LAYER" and clouds[0].revision_label == "Изм. №2"
    x0, y0, x1, y1 = clouds[0].bbox
    assert x0 < 460 < x1 and y0 < 200 < y1


def test_frame_maps_rotation(tmp_path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=200)
    page.draw_rect(pymupdf.Rect(10, 20, 30, 40), color=(0, 0, 0))
    page.set_rotation(90)
    frame = PageFrame.of(page)
    assert (frame.width, frame.height) == (200, 400)
    box = frame.rect((10, 20, 30, 40))
    # displayed = unrotated × rotation_matrix; check against PyMuPDF itself
    r = pymupdf.Rect(10, 20, 30, 40) * page.rotation_matrix
    assert box == pytest.approx((r.x0, r.y0, r.x1, r.y1))
    assert frame.norm_box(box) == pytest.approx([r.x0 / 200, r.y0 / 400, r.x1 / 200, r.y1 / 400], abs=1e-4)


def test_cluster_boxes() -> None:
    boxes = [(0, 0, 1, 1), (1.5, 0, 2, 1), (10, 10, 11, 11)]
    groups = sorted(cluster_boxes(boxes, 1.0))
    assert groups == [[0, 1], [2]]


def _seg(x0, y0, x1, y1, layer="L") -> Seg:
    return Seg(x0, y0, x1, y1, layer, 0)


def test_leader_shelf_and_tip() -> None:
    label = (100.0, 90.0, 130.0, 100.0)  # text box, height 10
    segs = [_seg(98, 102, 132, 102), _seg(132, 102, 250, 200)]  # shelf + leader
    tips = LeaderGraph(segs).follow(label, 10.0)
    assert [(round(t.x), round(t.y)) for t in tips] == [(250, 200)]


def test_leader_arrowhead_and_t_junction() -> None:
    label = (100.0, 90.0, 130.0, 100.0)
    arrow = [_seg(250, 200, 251, 201), _seg(251, 201, 250, 202), _seg(250, 202, 250, 200)]  # tiny closed head
    segs = [_seg(98, 102, 132, 102), _seg(115, 102, 115, 180), _seg(115, 180, 250, 200), *arrow]
    tips = LeaderGraph(segs).follow(label, 10.0)
    assert (250, 200) in [(round(t.x), round(t.y)) for t in tips]


def test_leader_closed_frame_is_not_a_tip() -> None:
    label = (100.0, 90.0, 130.0, 100.0)
    frame = [_seg(96, 88, 134, 88), _seg(134, 88, 134, 104), _seg(134, 104, 96, 104), _seg(96, 104, 96, 88)]
    assert LeaderGraph(frame).follow(label, 10.0) == []


def test_leader_dense_network_gives_nothing() -> None:
    label = (100.0, 90.0, 130.0, 100.0)
    segs = [_seg(98, 102, 132, 102)] + [_seg(132 + i, 102, 133 + i, 102 + (i % 2)) for i in range(0, 300)]
    assert LeaderGraph(segs).follow(label, 10.0, max_segments=50) == []


def test_glyph_strokes_dropped() -> None:
    boxes = [(100.0, 90.0, 130.0, 100.0)]
    segs = [_seg(101, 91, 105, 99), _seg(98, 102, 132, 102)]
    kept = drop_glyph_strokes(segs, boxes)
    assert len(kept) == 1 and kept[0].y0 == 102
