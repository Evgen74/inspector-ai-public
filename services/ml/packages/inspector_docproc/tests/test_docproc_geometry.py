"""Coordinate contract (PDF_VISIBLE_ROTATED_TL_V1) on rotated / cropped / offset synthetic PDFs."""

from __future__ import annotations

import numpy as np
import pytest

from inspector_docproc.ocr.pipeline import reading_span_to_quad
from inspector_docproc.orientation import map_points_back, rotate_image
from inspector_docproc.render import mupdf_rect_to_norm, render_page
from inspector_docproc.testing import ink_bbox, make_pdf
from inspector_docproc.textlayer import extract_text_layer

CASES = [
    (rot, crop, mb)
    for rot in (0, 90, 180, 270)
    for crop in (None, (50, 60, 550, 700))
    for mb in (None, (-30, 20, 570, 820))
]


@pytest.mark.parametrize(("rot", "crop", "mb"), CASES)
def test_text_layer_word_bbox_matches_rendered_ink(tmp_path, rot, crop, mb) -> None:
    """Text-layer bboxes land on the rendered glyphs for every /Rotate, CropBox and MediaBox offset.

    (Measured alternative: ``~page.transformation_matrix`` + raw PDF boxes is off by 0.05–0.2 here.)
    """
    import pymupdf

    path = make_pdf(
        tmp_path / "p.pdf",
        [(150, 300, "SHIFR-12", 24)],
        size=(600, 800),
        rotate=rot,
        cropbox=crop,
        mediabox=mb,
    )
    with pymupdf.open(path) as doc:
        page = doc[0]
        layer = extract_text_layer(page)
        assert [w.text for w in layer.words] == ["SHIFR-12"]
        box = layer.words[0].bbox
        ink = ink_bbox(page)
    # glyph boxes include ascender/descender space: compare with a font-size tolerance
    assert all(abs(a - b) < 0.02 for a, b in zip(box, ink, strict=True)), (box, ink)
    assert (
        box[0] <= ink[0] + 0.005 and box[2] >= ink[2] - 0.005
    )  # the glyph box contains the ink horizontally


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_word_angle_follows_rotation(tmp_path, rot) -> None:
    import pymupdf

    path = make_pdf(tmp_path / "p.pdf", [(100, 200, "ABC", 20)], rotate=rot)
    with pymupdf.open(path) as doc:
        assert extract_text_layer(doc[0]).words[0].angle == rot


def test_mupdf_rect_to_norm_full_page(tmp_path) -> None:
    import pymupdf

    path = make_pdf(tmp_path / "p.pdf", [(100, 200, "X", 10)], rotate=90, cropbox=(10, 20, 510, 720))
    with pymupdf.open(path) as doc:
        page = doc[0]
        unrot = pymupdf.Rect(0, 0, page.rect.height, page.rect.width)  # unrotated CropBox-relative
        assert mupdf_rect_to_norm(page, unrot) == pytest.approx([0, 0, 1, 1])


def test_clip_render_equals_full_render_slice(tmp_path) -> None:
    import pymupdf

    path = make_pdf(tmp_path / "p.pdf", [(100, 200, "Hello", 30)], rotate=270, cropbox=(50, 60, 550, 700))
    with pymupdf.open(path) as doc:
        page = doc[0]
        full = render_page(page, 144)
        w, h = page.rect.width, page.rect.height
        clip = pymupdf.Rect(w * 0.25, h * 0.5, w * 0.75, h)
        part = render_page(page, 144, clip=clip)
        x0, y0 = round(clip.x0 * 2), round(clip.y0 * 2)
        assert np.array_equal(full[y0 : y0 + part.shape[0], x0 : x0 + part.shape[1]], part)


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_content_rotation_back_mapping(k) -> None:
    """A point found on np.rot90(img, k) maps back onto the same pixel of img."""
    h, w = 40, 70
    img = np.zeros((h, w), np.uint8)
    img[10, 55] = 255
    rot = rotate_image(img, k)
    ys, xs = np.nonzero(rot)
    back = map_points_back(np.array([[xs[0] + 0.5, ys[0] + 0.5]]), k, w, h)[0]
    assert back == pytest.approx([55.5, 10.5])


def test_reading_span_to_quad_orientation() -> None:
    quad = np.array([[0, 0], [100, 0], [100, 10], [0, 10]], np.float32)  # horizontal line
    left = reading_span_to_quad(quad, 0, 0.0, 0.5)
    assert left[:, 0].max() == pytest.approx(50) and left[:, 0].min() == pytest.approx(0)
    upside = reading_span_to_quad(quad, 2, 0.0, 0.5)  # read turned 180°: first half = right half
    assert upside[:, 0].min() == pytest.approx(50) and upside[:, 0].max() == pytest.approx(100)
    tall = np.array([[0, 0], [10, 0], [10, 100], [0, 100]], np.float32)  # vertical line
    top = reading_span_to_quad(tall, 1, 0.0, 0.25)  # read after a CCW turn: runs top → bottom
    assert top[:, 1].min() == pytest.approx(0) and top[:, 1].max() == pytest.approx(25)
    bottom = reading_span_to_quad(tall, 3, 0.0, 0.25)  # read after a CW turn: runs bottom → top
    assert bottom[:, 1].min() == pytest.approx(75) and bottom[:, 1].max() == pytest.approx(100)
