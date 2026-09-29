"""Title-block QR codes (95 R7): decode, parse and link to the page they identify.

Two kinds occur on the train objects:
- **Exon** (Тюменская RD and ИД): ``https://exon.exonproject.ru/document-status/<uuid>/<ver>/wd/<page>``,
  a 286×286 px image placed next to the stamp on every page of the source document. ``<page>`` is the page of
  the Exon document, so an ИД extract carrying the QR of an RD sheet points at that sheet (F0198 → F0202 p17).
- **Signal** (Новослободская RD): ``https://qr.sgnl.pro/d/<key>``, drawn as vector paths at the right edge
  above the stamp; one key per document, no page.
Other payloads (e.g. an SRO registry link) are kept with ``doc_key = None``.

Decoding: embedded square images are decoded at their native resolution first (≈ 20 ms a page, no render);
pages ≥ A3 without an image QR fall back to a 150 dpi render of the right edge and of the stamp window, where
only solid square blobs of QR-like ink density (:func:`square_blobs`) go to the detector.
Detector: OpenCV ``QRCodeDetector`` with ``QRCodeDetectorAruco`` as the second try (OpenCV ≥ 4.8; the
workspace pins opencv-python-headless 5.0). No zxing dependency is needed on the train data.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

_EXON = re.compile(
    r"^https?://exon\.[^/]+/document-status/(?P<doc>[0-9a-fA-F-]{8,64})/(?P<ver>\d+)/wd/(?P<page>\d+)"
)
_SGNL = re.compile(r"^https?://qr\.sgnl\.pro/d/(?P<key>[A-Za-z0-9_-]{4,64})")
_PAGE_PARAM = re.compile(r"[?&](?:page|p)=(?P<page>\d{1,5})\b")

MM = 72.0 / 25.4


@dataclass(frozen=True, slots=True)
class ParsedQr:
    host: str | None
    doc_key: str | None
    doc_page: int | None
    kind: str  # "EXON" | "SGNL" | "OTHER"


def parse_payload(payload: str) -> ParsedQr:
    p = payload.strip()
    host_m = re.match(r"^[a-z]+://([^/]+)", p, re.IGNORECASE)
    host = host_m.group(1).lower() if host_m else None
    m = _EXON.match(p)
    if m:
        return ParsedQr(host, f"exon:{m.group('doc').lower()}/{m.group('ver')}", int(m.group("page")), "EXON")
    m = _SGNL.match(p)
    if m:
        return ParsedQr(host, f"sgnl:{m.group('key')}", None, "SGNL")
    m = _PAGE_PARAM.search(p)
    return ParsedQr(host, None, int(m.group("page")) if m else None, "OTHER")


class QrDecoder:
    """OpenCV detectors created once per process."""

    def __init__(self) -> None:
        import cv2

        self._cv2 = cv2
        self._std = cv2.QRCodeDetector()
        self._aru = cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else None

    def decode_one(self, gray: np.ndarray) -> str | None:
        """A single QR filling most of ``gray`` (an embedded image)."""
        cv2 = self._cv2
        if not qr_like(gray):
            return None
        g = cv2.copyMakeBorder(gray, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        for scale in (1, 2, 3):
            x = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST) if scale > 1 else g
            for det in (self._std, self._aru):
                if det is None:
                    continue
                try:
                    val = det.detectAndDecode(x)[0]
                except cv2.error:
                    val = ""
                if val:
                    return val
        return None

    def decode_many(self, gray: np.ndarray) -> list[tuple[str, np.ndarray]]:
        """All QR codes of a rendered region → [(payload, 4×2 corner points in pixels)]."""
        cv2 = self._cv2
        for det in (self._std, self._aru):
            if det is None:
                continue
            try:
                ok, vals, pts, _ = det.detectAndDecodeMulti(gray)
            except cv2.error:
                continue
            if ok and vals is not None:
                out = [(v, np.asarray(p, dtype=np.float64)) for v, p in zip(vals, pts, strict=False) if v]
                if out:
                    return out
        return []


def qr_like(gray: np.ndarray) -> bool:
    """A QR is two-tone: ≥ 85 % of the pixels near black or white and 20–80 % dark. Raster tiles of a site plan
    or a photo fail this in microseconds instead of six detector passes each (F0154: 17 s of 20 s)."""
    if gray.size == 0:
        return False
    g = (
        gray
        if gray.size <= 250_000
        else gray[:: max(1, gray.shape[0] // 400), :: max(1, gray.shape[1] // 400)]
    )
    dark = float((g < 96).mean())
    light = float((g > 160).mean())
    return dark + light >= 0.85 and 0.2 <= dark <= 0.8


def square_blobs(
    gray: np.ndarray, px_per_mm: float, side_mm: tuple[float, float] = (8.0, 45.0)
) -> list[tuple]:
    """Candidate QR squares of a rendered window: ink closed at module scale becomes a solid square whose raw
    ink density is QR-like (0.25–0.75). ≈ 5 ms on a 200 × 72 mm window at 150 dpi, against ≈ 1.3 s for the
    OpenCV multi-detector on a busy drawing (F0154 p18): the detector only sees these crops.
    Returns [(x0, y0, x1, y1)] in pixels."""
    import cv2

    ink = (gray < 128).astype(np.uint8)
    k = max(3, round(2.0 * px_per_mm))  # modules are 0.5–1.2 mm: a 2 mm closing makes the code solid
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    out = []
    lo, hi = side_mm[0] * px_per_mm, side_mm[1] * px_per_mm
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (lo <= w <= hi and lo <= h <= hi) or not 0.8 <= w / h <= 1.25:
            continue
        if area < 0.6 * w * h:  # not solid after closing: a frame, a line, text
            continue
        dens = float(ink[y : y + h, x : x + w].mean())
        if 0.25 <= dens <= 0.75:
            out.append((x, y, x + w, y + h))
    return out


def square_xrefs(page, min_px: int = 40, max_px: int = 1600) -> list[int]:
    """Xrefs of square images used by the page, from its resources (≈ 1 ms). ``page.get_image_info(xrefs=True)``
    decodes and hashes every image of the page (1.3 s on a site plan with 62 raster tiles, F0154 p18)."""
    out = set()
    try:
        items = page.get_images(full=True)
    except Exception:
        return []
    for it in items:
        xref, w, h = int(it[0]), int(it[2]), int(it[3])
        if xref and min_px <= w <= max_px and min_px <= h <= max_px and abs(w - h) <= max(2, 0.03 * w):
            out.add(xref)
    return sorted(out)


def placements(page, xref: int, mm_range: tuple[float, float] = (5.0, 60.0)) -> list[tuple[float, ...]]:
    """Where the image is placed on the page (unrotated page space), square placements of 5–60 mm only."""
    try:
        rects = page.get_image_rects(xref)
    except Exception:
        return []
    out = []
    for r in rects:
        bw, bh = r.width / MM, r.height / MM
        if mm_range[0] <= bw <= mm_range[1] and abs(bw - bh) <= max(1.5, 0.08 * bw):
            out.append((r.x0, r.y0, r.x1, r.y1))
    return out


def _image_candidates(page) -> list[dict]:
    """QR-like square images placed 5–60 mm on the page: [{"xref", "bbox"}] (bbox in unrotated page space)."""
    out = []
    for xref in square_xrefs(page):
        gray = _gray_of_image(page.parent, xref)
        if gray is None or not qr_like(gray):
            continue
        out.extend({"xref": xref, "bbox": b} for b in placements(page, xref))
    return out


def _gray_of_image(doc, xref: int) -> np.ndarray | None:
    import pymupdf

    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.n != 1:
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    except Exception:
        return None


def decode_page(
    page,
    decoder: QrDecoder,
    *,
    render_fallback: bool = True,
    render_dpi: int = 150,
    image_cache: dict[int, str | None] | None = None,
) -> list[dict[str, Any]]:
    """QR codes of one page → [{"payload", "bbox", "method"}] (bbox normalized, displayed page)."""
    from inspector_docproc.render import mupdf_rect_to_norm, render_page

    doc = page.parent
    hits: list[dict[str, Any]] = []
    for xref in square_xrefs(page):
        if image_cache is not None and xref in image_cache:
            val = image_cache[xref]
        else:
            gray = _gray_of_image(doc, xref)
            val = decoder.decode_one(gray) if gray is not None else None
            if image_cache is not None:
                image_cache[xref] = val
        if not val:
            continue
        for box in placements(page, xref):
            hits.append({"payload": val, "bbox": [round(v, 5) for v in mupdf_rect_to_norm(page, box)],
                         "method": "IMAGE"})  # fmt: skip
    if hits or not render_fallback:
        return _unique(hits)
    wmm, hmm = page.rect.width / MM, page.rect.height / MM
    if wmm * hmm < 0.9 * 297 * 420:  # A4 text pages: no vector QR seen, not worth a render
        return hits
    import pymupdf

    r = page.rect
    windows = [
        (
            max(0.0, wmm - 70.0),
            max(0.0, hmm - 175.0),
            wmm,
            max(0.0, hmm - 40.0),
        ),  # right edge above the stamp
        (max(0.0, wmm - 200.0), max(0.0, hmm - 72.0), wmm, hmm),  # the stamp window
    ]
    # one display list for both windows: recording a heavy CAD page costs ≈ 0.2 s, rasterising a clip ≈ 10 ms
    try:
        dlist = page.get_displaylist()
    except Exception:
        dlist = None
    mat = pymupdf.Matrix(render_dpi / 72.0, render_dpi / 72.0)
    for x0, y0, x1, y1 in windows:
        clip = pymupdf.Rect(r.x0 + x0 * MM, r.y0 + y0 * MM, r.x0 + x1 * MM, r.y0 + y1 * MM)
        try:
            if dlist is not None:
                pix = dlist.get_pixmap(matrix=mat, colorspace=pymupdf.csGRAY, alpha=False, clip=clip)
                gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
            else:
                img = render_page(page, render_dpi, clip=clip)
                gray = np.ascontiguousarray(img[:, :, 1] if img.ndim == 3 else img)
        except Exception:
            continue
        zoom = render_dpi / 25.4  # px per mm
        pad = int(3 * zoom)
        blobs = square_blobs(gray, zoom)
        for bx0, by0, bx1, by1 in blobs:
            cx0, cy0 = max(0, bx0 - pad), max(0, by0 - pad)
            crop = gray[cy0 : by1 + pad, cx0 : bx1 + pad]
            val = decoder.decode_one(crop)
            if not val:
                continue
            box = [
                (cx0 / zoom + x0) / wmm,
                (cy0 / zoom + y0) / hmm,
                (min(gray.shape[1], bx1 + pad) / zoom + x0) / wmm,
                (min(gray.shape[0], by1 + pad) / zoom + y0) / hmm,
            ]
            hits.append(
                {"payload": val, "bbox": [round(min(1.0, max(0.0, v)), 5) for v in box], "method": "RENDER"}
            )
        if blobs and not hits:  # a QR-like square that did not decode on its crop: the full detector
            for val, pts in decoder.decode_many(gray):
                xs = pts[:, 0] / zoom + x0
                ys = pts[:, 1] / zoom + y0
                box = [
                    float(xs.min()) / wmm,
                    float(ys.min()) / hmm,
                    float(xs.max()) / wmm,
                    float(ys.max()) / hmm,
                ]
                hits.append(
                    {
                        "payload": val,
                        "bbox": [round(min(1.0, max(0.0, v)), 5) for v in box],
                        "method": "RENDER",
                    }
                )
        if hits:
            break
    return _unique(hits)


def _unique(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for h in hits:
        if h["payload"] in seen:
            continue
        seen.add(h["payload"])
        out.append(h)
    return out


# ── linking across the files of one object ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class QrTarget:
    file_id: str
    pdf_page_number: int | None


def link_targets(
    hits: Mapping[str, Iterable[tuple[int, str]]],
) -> dict[tuple[str, int, str], QrTarget]:
    """``hits``: file_id → [(pdf_page, payload)]. Returns (file_id, page, payload) → target page.

    The home file of a document key is the file holding most of its pages (at least two). Paged keys
    (Exon) resolve to the home page carrying the same (key, page); unpaged keys (Signal) resolve to the home
    file only. A key spread thinly over several one-page files (ИД extracts of a document absent from the
    package) has no home and no target.
    """
    by_key_file: dict[str, Counter[str]] = defaultdict(Counter)
    key_page: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    parsed: dict[str, ParsedQr] = {}
    for fid, items in hits.items():
        for page, payload in items:
            pq = parsed.setdefault(payload, parse_payload(payload))
            if pq.doc_key is None:
                continue
            by_key_file[pq.doc_key][fid] += 1
            if pq.doc_page is not None:
                key_page[(pq.doc_key, pq.doc_page)].append((fid, page))
    homes: dict[str, str] = {}
    for key, files in by_key_file.items():
        (top, n), *rest = files.most_common()
        if n >= 2 and (not rest or rest[0][1] < n):
            homes[key] = top
    out: dict[tuple[str, int, str], QrTarget] = {}
    for fid, items in hits.items():
        for page, payload in items:
            pq = parsed[payload]
            home = homes.get(pq.doc_key or "")
            if home is None:
                continue
            if pq.doc_page is None:
                out[(fid, page, payload)] = QrTarget(home, None)
                continue
            cands = [(f, p) for f, p in key_page.get((pq.doc_key, pq.doc_page), []) if f == home]
            if len(cands) == 1:
                out[(fid, page, payload)] = QrTarget(home, cands[0][1])
    return out
