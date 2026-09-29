"""Fast checks on real TRAIN pages of the benchmark (router only, no OCR): page classes and the coordinate
contract on a real /Rotate 270 sheet. Skipped without the organizer data."""

from __future__ import annotations

import numpy as np
import pytest

from inspector_common.settings import Settings
from inspector_docproc.bench.suites import EXPECTED_ROUTES, load_benchmark
from inspector_docproc.router import route
from inspector_docproc.textlayer import extract_text_layer

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def bench_pages():
    paths = Settings().paths
    if not paths.documents_root.is_dir():
        pytest.skip("organizer data not found")
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    return paths.documents_root, {p["id"]: p for p in load_benchmark()["pages"]}


def _open_page(bench_pages, pid: str):
    import pymupdf

    root, pages = bench_pages
    entry = pages[pid]
    doc = pymupdf.open(root / entry["relative_path"])
    return doc, doc[entry["pdf_page_number"] - 1]


@pytest.mark.parametrize("pid", sorted(EXPECTED_ROUTES))
def test_real_page_routes(bench_pages, pid: str) -> None:
    doc, page = _open_page(bench_pages, pid)
    with doc:
        _, plan, _ = route(page, extract_text_layer(page))
    assert (plan.page_class, plan.action) == EXPECTED_ROUTES[pid], plan.reason


@pytest.mark.parametrize("pid", ["A07", "A08"])  # A07: A0 plan with /Rotate 270; A08: /Rotate 0 control
def test_real_text_layer_boxes_land_on_ink(bench_pages, pid: str) -> None:
    import pymupdf

    doc, page = _open_page(bench_pages, pid)
    with doc:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(60 / 72, 60 / 72), colorspace=pymupdf.csGRAY)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        words = [w for w in extract_text_layer(page).visible_words if len(w.text) >= 3]
    assert len(words) > 100

    def ink(bbox) -> tuple[bool, float]:
        x0, y0 = int(bbox[0] * pix.width), int(bbox[1] * pix.height)
        x1, y1 = int(np.ceil(bbox[2] * pix.width)), int(np.ceil(bbox[3] * pix.height))
        box = img[max(0, y0) : y1 + 1, max(0, x0) : x1 + 1]
        # any non-white pixel: CAD text is also light grey (0xBABABA dimension numbers render at 185)
        return (box.size > 0 and int(box.min()) < 230), float((box < 230).mean()) if box.size else 0.0

    placed = [ink(w.bbox) for w in words]
    # control: the same boxes turned 180° about the page centre (a wrong /Rotate mapping lands there)
    turned = [ink([1 - w.bbox[2], 1 - w.bbox[3], 1 - w.bbox[0], 1 - w.bbox[1]]) for w in words]
    hit_share = sum(h for h, _ in placed) / len(words)
    density, control = np.mean([d for _, d in placed]), np.mean([d for _, d in turned])
    assert hit_share >= 0.99, hit_share
    assert density >= 2.0 * control, (density, control)
