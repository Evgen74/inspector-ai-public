from __future__ import annotations

import json

import pytest

from inspector_common import geometry as g
from inspector_common.paths import contracts_dir

VECTORS = json.loads((contracts_dir() / "vectors" / "geometry.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[c["name"] for c in VECTORS["cases"]])
def test_pdf_rect_to_norm_matches_golden_vectors(case: dict) -> None:
    got = g.pdf_rect_to_norm_bbox(case["rect_pdf"], case["mediabox"], case["cropbox"], case["rotate"])
    assert got == case["expected_bbox_norm"]


@pytest.mark.parametrize("rotate", [0, 90, 180, 270, -90])
def test_point_round_trip(rotate: int) -> None:
    mb, cb = [0, 0, 600, 800], [50, 100, 550, 750]
    for x, y in [(50, 100), (550, 750), (123.4, 456.7)]:
        nx, ny = g.pdf_point_to_norm(x, y, mb, cb, rotate)
        bx, by = g.norm_point_to_pdf(nx, ny, mb, cb, rotate)
        assert bx == pytest.approx(x) and by == pytest.approx(y)


def test_displayed_size_swaps_for_quarter_turns() -> None:
    assert g.displayed_size([0, 0, 600, 800], None, 0) == (600, 800)
    assert g.displayed_size([0, 0, 600, 800], None, 90) == (800, 600)
    assert g.displayed_size([0, 0, 600, 800], [0, 0, 600, 1000], 270) == (800, 600)


def test_invalid_rotation_and_disjoint_crop() -> None:
    with pytest.raises(ValueError):
        g.normalize_rotation(45)
    with pytest.raises(ValueError):
        g.visible_rect([0, 0, 100, 100], [200, 200, 300, 300])


def test_rotate_norm_bbox_is_invertible() -> None:
    box = [0.1, 0.2, 0.3, 0.5]
    for k in range(4):
        assert g.rotate_norm_bbox(g.rotate_norm_bbox(box, k), -k) == box
    assert g.rotate_norm_bbox(box, 1) == [0.5, 0.1, 0.8, 0.3]


def test_pixel_bbox_and_clamping() -> None:
    assert g.pixel_bbox_to_norm([100, 50, 300, 150], 1000, 500) == [0.1, 0.1, 0.3, 0.3]
    assert g.pixel_bbox_to_norm([-10, 0, 1200, 500], 1000, 500) == [0.0, 0.0, 1.0, 1.0]


def test_box_ops_and_polygons() -> None:
    a, b = [0.0, 0.0, 0.5, 0.5], [0.25, 0.25, 0.75, 0.75]
    assert g.bbox_iou(a, a) == 1.0
    assert g.bbox_iou(a, b) == pytest.approx(0.0625 / 0.4375)
    assert g.bbox_iou(a, [0.6, 0.6, 0.7, 0.7]) == 0.0
    assert g.bbox_union([a, b]) == [0.0, 0.0, 0.75, 0.75]
    poly = g.bbox_to_polygon(b)
    assert g.polygon_to_bbox(poly) == b
    assert g.polygon_iou(g.bbox_to_polygon(a), poly) == pytest.approx(g.bbox_iou(a, b))
    assert g.is_valid_bbox(b) and not g.is_valid_bbox([0.5, 0.0, 0.4, 1.0])


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
@pytest.mark.parametrize("offset_crop", [False, True])
def test_matches_pymupdf_render(rotate: int, offset_crop: bool) -> None:
    """Ground truth = the rendered page (get_pixmap applies CropBox and /Rotate).

    PyMuPDF drawing/text coordinates map to PDF user space through ``~page.transformation_matrix``.
    Note for AG-02A: the shortcut ``rect * page.rotation_matrix / page.rect`` from 02 §3.14 is off by
    up to 0.155 on rotated pages with an offset CropBox (measured); use this conversion instead.
    """
    pymupdf = pytest.importorskip("pymupdf")
    np = pytest.importorskip("numpy")
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    if offset_crop:
        page.set_cropbox(pymupdf.Rect(50, 50, 550, 700))
    page.set_rotation(rotate)
    rect = pymupdf.Rect(100, 200, 200, 300)
    page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY)
    pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    ys, xs = np.where(pixels < 128)
    rendered = [
        xs.min() / pix.width,
        ys.min() / pix.height,
        (xs.max() + 1) / pix.width,
        (ys.max() + 1) / pix.height,
    ]
    pdf = rect * ~page.transformation_matrix
    mediabox = list(page.mediabox)
    cropbox = [
        page.cropbox.x0,
        page.mediabox.y1 - page.cropbox.y1,
        page.cropbox.x1,
        page.mediabox.y1 - page.cropbox.y0,
    ]
    ours = g.pdf_rect_to_norm_bbox([pdf.x0, pdf.y0, pdf.x1, pdf.y1], mediabox, cropbox, rotate, decimals=None)
    assert ours == pytest.approx(rendered, abs=1.5 / min(pix.width, pix.height))
    doc.close()
