"""QR payload parsing, decoding (embedded image and vector render) and cross-file linking."""

from __future__ import annotations

from pathlib import Path

import pytest

from inspector_layout.qr import QrDecoder, QrTarget, decode_page, link_targets, parse_payload
from inspector_layout.testing import StampSpec, make_stamp_pdf, qr_png

EXON = "https://exon.exonproject.ru/document-status/3eb2aa9d-d725-468e-9e01-741010c01f17/1/wd/{}"
EXON_B = "https://exon.exonproject.ru/document-status/87cc1a16-51a4-4f99-bb70-35afc204d773/1/wd/{}"
EXON_C = "https://exon.exonproject.ru/document-status/a95715d1-bfcc-47ce-a056-4329e7320969/1/wd/{}"


def test_parse_exon() -> None:
    q = parse_payload(EXON.format(17))
    assert q.kind == "EXON" and q.doc_page == 17
    assert q.doc_key == "exon:3eb2aa9d-d725-468e-9e01-741010c01f17/1"
    assert q.host == "exon.exonproject.ru"


def test_parse_sgnl_and_other() -> None:
    q = parse_payload("https://qr.sgnl.pro/d/c_dFsM-1MeNe")
    assert (q.kind, q.doc_key, q.doc_page) == ("SGNL", "sgnl:c_dFsM-1MeNe", None)
    q = parse_payload("https://reestr.nopriz.ru/member/19241099")
    assert (q.kind, q.doc_key) == ("OTHER", None)
    assert parse_payload("plain text").host is None


def test_link_targets_extract_to_source_page() -> None:
    """F0198 (ИД extract) carries the QR of F0202 p17; F0197/F0199 point at a document absent from the set."""
    hits = {
        "F0202": [(p, EXON_B.format(p)) for p in range(14, 25)],
        "F0198": [(1, EXON_B.format(17))],
        "F0197": [(1, EXON_C.format(19))],
        "F0199": [(1, EXON_C.format(21))],
    }
    t = link_targets(hits)
    assert t[("F0198", 1, EXON_B.format(17))] == QrTarget("F0202", 17)
    assert t[("F0202", 17, EXON_B.format(17))] == QrTarget("F0202", 17)
    assert ("F0197", 1, EXON_C.format(19)) not in t


def test_link_targets_unpaged_key_to_home_file() -> None:
    s = "https://qr.sgnl.pro/d/Mqx9rUx9tcoF"
    t = link_targets({"F0138": [(3, s), (4, s), (5, s)], "F0050": [(2, s)]})
    assert t[("F0050", 2, s)] == QrTarget("F0138", None)


@pytest.fixture(scope="module")
def qr_pdf(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("qr")
    return make_stamp_pdf(d / "qr.pdf", [StampSpec(), StampSpec()], qr_payloads=[EXON.format(1), None])


def test_decode_one_image() -> None:
    import cv2
    import numpy as np

    buf = np.frombuffer(qr_png(EXON.format(5), module_px=4), np.uint8)
    gray = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    assert QrDecoder().decode_one(gray) == EXON.format(5)


def test_decode_page_embedded_image(qr_pdf: Path) -> None:
    import pymupdf

    dec = QrDecoder()
    with pymupdf.open(qr_pdf) as doc:
        hits = decode_page(doc[0], dec, render_fallback=False)
        assert [h["payload"] for h in hits] == [EXON.format(1)]
        assert hits[0]["method"] == "IMAGE"
        x0, y0, x1, y1 = hits[0]["bbox"]
        assert 0.6 < x0 < x1 < 0.8 and 0.9 < y0 < y1 <= 1.0
        assert decode_page(doc[1], dec, render_fallback=False) == []


def test_decode_page_vector_render(tmp_path: Path) -> None:
    """A QR drawn as vector paths at the right edge above the stamp (Signal QR on Новослободская RD)."""
    import cv2
    import pymupdf

    mm = 72.0 / 25.4
    img = cv2.QRCodeEncoder.create().encode("https://qr.sgnl.pro/d/TestKey123")
    doc = pymupdf.open()
    page = doc.new_page(width=594 * mm, height=420 * mm)
    n = img.shape[0]
    size = 22.0 / n  # 22 mm code
    x0, y0 = 594 - 31 - 11, 420 - 80 - 11
    shape = page.new_shape()
    for r in range(n):
        for c in range(n):
            if img[r, c] < 128:
                shape.draw_rect(
                    pymupdf.Rect(
                        (x0 + c * size) * mm,
                        (y0 + r * size) * mm,
                        (x0 + (c + 1) * size) * mm,
                        (y0 + (r + 1) * size) * mm,
                    )
                )
    shape.finish(color=None, fill=(0, 0, 0), width=0)
    shape.commit()
    path = tmp_path / "vec.pdf"
    doc.save(path)
    doc.close()
    with pymupdf.open(path) as d2:
        hits = decode_page(d2[0], QrDecoder(), render_fallback=True)
    assert [h["payload"] for h in hits] == ["https://qr.sgnl.pro/d/TestKey123"]
    assert hits[0]["method"] == "RENDER"
    bx = hits[0]["bbox"]
    assert abs((bx[0] + bx[2]) / 2 - (594 - 31) / 594) < 0.02


# ── cheap pre-filters: two-tone images, square blobs ─────────────────────────────────────────────


def test_qr_like_rejects_raster_tiles() -> None:
    import cv2
    import numpy as np

    from inspector_layout.qr import qr_like

    qr = cv2.imdecode(np.frombuffer(qr_png(EXON.format(3), module_px=4), np.uint8), cv2.IMREAD_GRAYSCALE)
    assert qr_like(qr)
    rng = np.random.default_rng(7)
    photo = rng.integers(60, 200, size=(263, 266), dtype=np.uint8)  # a site-plan raster tile
    paper = np.full((300, 300), 250, np.uint8)
    paper[::25, :] = 0  # a ruled, mostly white scan
    assert not qr_like(photo) and not qr_like(paper) and not qr_like(np.zeros((0, 0), np.uint8))


def test_square_blobs_find_the_code_among_drawing_lines() -> None:
    import cv2
    import numpy as np

    from inspector_layout.qr import square_blobs

    px_mm = 150 / 25.4
    win = np.full((int(135 * px_mm), int(70 * px_mm)), 255, np.uint8)
    cv2.line(win, (0, 50), (win.shape[1] - 1, 50), 0, 2)  # a frame line
    cv2.putText(win, "PLAN 1:100", (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    code = cv2.QRCodeEncoder.create().encode("https://qr.sgnl.pro/d/TestKey123")
    side = int(22 * px_mm)
    code = cv2.resize(code, (side, side), interpolation=cv2.INTER_NEAREST)
    y0, x0 = 400, 120
    win[y0 : y0 + side, x0 : x0 + side] = code
    blobs = square_blobs(win, px_mm)
    assert len(blobs) == 1
    bx0, by0, bx1, _ = blobs[0]
    assert abs(bx0 - x0) < 15 and abs(by0 - y0) < 15 and abs((bx1 - bx0) - side) < 25


def test_raster_tiles_are_not_decoded_but_the_qr_is(tmp_path: Path) -> None:
    """A site plan made of square raster tiles (F0154) next to an Exon QR: only the QR is decoded."""
    import cv2
    import numpy as np
    import pymupdf

    mm = 72.0 / 25.4
    doc = pymupdf.open()
    page = doc.new_page(width=420 * mm, height=297 * mm)
    rng = np.random.default_rng(3)
    for i in range(12):
        tile = rng.integers(60, 200, size=(120, 120), dtype=np.uint8)
        _, buf = cv2.imencode(".png", tile)
        x = 20 + 25 * (i % 6)
        y = 20 + 25 * (i // 6)
        page.insert_image(pymupdf.Rect(x * mm, y * mm, (x + 20) * mm, (y + 20) * mm), stream=buf.tobytes())
    page.insert_image(pymupdf.Rect(300 * mm, 270 * mm, 313 * mm, 283 * mm), stream=qr_png(EXON.format(9)))
    path = tmp_path / "tiles.pdf"
    doc.save(path)
    doc.close()
    with pymupdf.open(path) as d:
        cache: dict[int, str | None] = {}
        hits = decode_page(d[0], QrDecoder(), render_fallback=False, image_cache=cache)
    assert [h["payload"] for h in hits] == [EXON.format(9)]
    assert sum(v is not None for v in cache.values()) == 1 and len(cache) == 13
