"""Page zones (R-10, 97 §2.13): round seals, rectangular stamps, QR codes and handwriting (signatures and
handwritten fill-ins), emitted as PageTokens ``zones`` so that extraction and the OCR metrics can exclude them.

The ТЗ excludes «рукописные и заранее размеченные нечитаемые зоны» from the OCR metric; the GT v2
(``tests/data/ocr_gt_v2.json``) marks seals, signatures, handwriting and QR codes as excluded zones but keeps
the legible printed lines under them in the score. So zones never delete text: they flag it.

Detectors (all deterministic, CPU, measured on the 14 GT v2 pages; see the benchmark ``scans_v2.zones``):

- **Colour ink** (blue/violet: seals, signatures, handwritten fill-ins on scans; signatures drawn in blue on
  vector sheets): an HSV + blue-over-red mask of the page render, analysed at ``work_dpi`` (max-pooled so
  thin anti-aliased vector strokes survive the downscale).
- **Seal**: Hough circles on the colour mask with a diameter of 25–60 mm, accepted when ink runs round the
  ring (``seal_ring_coverage`` of 36 angular sectors of the outer annulus).
- **Stamp**: a rectangle of colour ink lines (``stamp_*``); its printed text stays usable (quality OK).
- **Handwriting**: colour-ink clusters left after removing seal discs, straight ink lines and the boxes of
  confidently read OCR lines (printed text), that are not line-like and have handwriting size. Subkind
  ``SIGNATURE`` (≥ ``signature_min_mm`` on the long side) or ``TEXT``.
- **QR**: embedded images of QR size decoded from their own pixels (payload kept in ``attrs.payload``), plus
  OpenCV's ArUco-based QR detector on the render (QRs printed inside a scan or drawn as vectors).

Token flags (see :func:`assign_tokens`): OCR tokens whose own ink is mostly colour ink inside a handwriting
zone are ``ABSTAIN`` (handwriting is excluded from analysis, error catalogue ``HANDWRITING_ZONES``); tokens
inside seals keep their confidence flag and are listed in the zone (``SEAL_OVERLAP``). Every zone lists the
ids of the tokens centred in it in ``attrs.token_ids``.

Not detected (measured misses): black-ink seals and signatures on greyscale-looking scans (no colour cue),
signatures written inside a seal (the seal zone covers them).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from inspector_docproc.config import ZoneConfig

MM_PER_IN = 25.4


@dataclass(slots=True)
class Zone:
    kind: str  # contract ZoneKind: SEAL | STAMP | QR | HANDWRITING
    bbox: list[float]  # normalized displayed page
    conf: float
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def quality_flag(self) -> str:
        # handwriting and QR modules are not text to analyse; seal-covered text is doubtful; stamp text is fine
        return {"HANDWRITING": "ABSTAIN", "QR": "ABSTAIN", "SEAL": "LOW_QUALITY"}.get(self.kind, "OK")

    def as_contract(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "bbox": [round(float(v), 4) for v in self.bbox],
            "quality_flag": self.quality_flag,
            "conf": round(float(min(1.0, max(0.0, self.conf))), 3),
            "source": "AUTO",
            "attrs": self.attrs,
        }


# ── Colour ink ───────────────────────────────────────────────────────────────────────────────


def colour_ink_mask(img_bgr: np.ndarray, cfg: ZoneConfig) -> np.ndarray:
    """Blue/violet ink (seals, ballpoint and gel pens, blue CAD signatures): uint8 0/255 at the image size."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s = hsv[..., 0], hsv[..., 1]
    b = img_bgr[..., 0].astype(np.int16)
    r = img_bgr[..., 2].astype(np.int16)
    m = (
        (h >= cfg.ink_hue_min)
        & (h <= cfg.ink_hue_max)
        & (s >= cfg.ink_sat_min)
        & (b - r >= cfg.ink_blue_over_red)
    )
    return m.astype(np.uint8) * 255


def _downscale_max(mask: np.ndarray, factor: float) -> np.ndarray:
    """Binary mask at ``factor`` (< 1) of its size, keeping any ink of a source block (max pooling)."""
    if factor >= 1.0:
        return mask
    k = max(1, round(1.0 / factor))
    if k > 1:
        mask = cv2.dilate(mask, np.ones((k, k), np.uint8))
    h, w = mask.shape[:2]
    return cv2.resize(
        mask, (max(1, int(w * factor)), max(1, int(h * factor))), interpolation=cv2.INTER_NEAREST
    )


def _straight_lines(mask: np.ndarray, px_per_mm: float, cfg: ZoneConfig) -> np.ndarray:
    """Horizontal and vertical ink lines longer than ``line_min_mm`` (stamp frames, form rules, underlines)."""
    n = max(3, int(cfg.line_min_mm * px_per_mm))
    horiz = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (n, 1)))
    vert = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, n)))
    return cv2.bitwise_or(horiz, vert)


# ── Seals ────────────────────────────────────────────────────────────────────────────────────


def _ring_coverage(
    mask: np.ndarray, cx: float, cy: float, r: float, sectors: int = 72
) -> tuple[float, float]:
    """(best radius, coverage): the thin band [0.94 ρ, 1.04 ρ] around ρ ∈ [0.85 r, 1.1 r] whose 72 angular
    sectors are most often inked. A seal's outer border is a continuous circle (coverage ≈ 1); circles that
    Hough finds in text, tables or line work are inked in scattered sectors only."""
    h, w = mask.shape[:2]
    x0, x1 = max(0, int(cx - 1.2 * r)), min(w, int(cx + 1.2 * r) + 1)
    y0, y1 = max(0, int(cy - 1.2 * r)), min(h, int(cy + 1.2 * r) + 1)
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    if len(xs) == 0:
        return r, 0.0
    dx, dy = xs + x0 - cx, ys + y0 - cy
    d = np.hypot(dx, dy)
    ang = ((np.arctan2(dy, dx) + math.pi) / (2 * math.pi) * sectors).astype(int) % sectors
    best = (r, 0.0)
    for rho in np.linspace(0.85 * r, 1.1 * r, 11):
        band = (d >= 0.94 * rho) & (d <= 1.04 * rho)
        if not band.any():
            continue
        cov = float(len(np.unique(ang[band]))) / sectors
        if cov > best[1]:
            best = (float(rho), cov)
    return best


def _outer_radius(
    mask: np.ndarray, cx: float, cy: float, rho: float, px_per_mm: float, cfg: ZoneConfig
) -> float:
    """Outer edge of a seal whose ring at ``rho`` is found: Hough locks onto the inner ring of a double-ring
    seal, so walk outward in 0.5 mm bands while each band is inked in ``seal_outer_coverage`` of 72 sectors
    (the text band and the outer ring); returns the last such radius plus half a band."""
    h, w = mask.shape[:2]
    rmax = cfg.seal_diameter_max_mm / 2 * px_per_mm
    x0, x1 = max(0, int(cx - rmax) - 2), min(w, int(cx + rmax) + 3)
    y0, y1 = max(0, int(cy - rmax) - 2), min(h, int(cy + rmax) + 3)
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    if len(xs) == 0:
        return rho
    dx, dy = xs + x0 - cx, ys + y0 - cy
    d = np.hypot(dx, dy)
    ang = ((np.arctan2(dy, dx) + math.pi) / (2 * math.pi) * 72).astype(int) % 72
    half = step = 0.5 * px_per_mm
    out, r = rho, rho + step
    while r <= rmax:
        band = (d >= r - half) & (d <= r + half)
        if len(np.unique(ang[band])) / 72.0 < cfg.seal_outer_coverage:
            break
        out, r = r, r + step
    return float(min(out + half, rmax))


def find_seals(
    mask: np.ndarray, px_per_mm: float, cfg: ZoneConfig
) -> list[tuple[float, float, float, float]]:
    """Round seals on the colour mask: (cx, cy, outer radius, border coverage) in mask pixels."""
    rmin = int(cfg.seal_diameter_min_mm / 2 * px_per_mm)
    rmax = int(cfg.seal_diameter_max_mm / 2 * px_per_mm) + 1
    if rmin < 4 or not mask.any():
        return []
    blur = cv2.GaussianBlur(mask, (0, 0), max(1.0, 0.4 * px_per_mm))
    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.5, minDist=1.6 * rmin, param1=100, param2=cfg.seal_hough_votes,
        minRadius=rmin, maxRadius=rmax,
    )  # fmt: skip
    out: list[tuple[float, float, float, float]] = []
    if circles is None:
        return out
    cand = []
    for cx, cy, r in circles[0][: cfg.seal_max_candidates]:
        rho, cov = _ring_coverage(mask, float(cx), float(cy), float(r))
        if (
            cov >= cfg.seal_ring_coverage
            and cfg.seal_diameter_min_mm <= 2 * rho / px_per_mm <= cfg.seal_diameter_max_mm
        ):
            cand.append(
                (float(cx), float(cy), _outer_radius(mask, float(cx), float(cy), rho, px_per_mm, cfg), cov)
            )
    for c in sorted(cand, key=lambda c: (-c[3], -c[2])):
        if any(math.hypot(c[0] - o[0], c[1] - o[1]) < max(c[2], o[2]) for o in out):
            continue  # overlapping circle: inner ring of the same seal or a weaker duplicate
        out.append(c)
    return out


def ellipse_ring(
    ink: np.ndarray, sectors: int = 72
) -> tuple[float, tuple[float, float, float, float, float]] | None:
    """Oval seals (photographed at an angle, or on a page scaled down, so Hough's circle size range misses
    them): fit an ellipse to the convex hull of a cluster's ink and return (share of ``sectors`` inked in the
    band 0.86–1.08 of the ellipse radius, (cx, cy, full axis 1, full axis 2, angle°)). A seal's border runs all
    round (≈ 1); a signature touches its hull at a few points only."""
    ys, xs = np.nonzero(ink)
    if len(xs) < 20:
        return None
    hull = cv2.convexHull(np.stack([xs, ys], 1).astype(np.float32))
    if len(hull) < 5:
        return None
    (cx, cy), (ax1, ax2), ang = cv2.fitEllipse(hull)
    if min(ax1, ax2) < 8:
        return None
    t = math.radians(ang)
    dx, dy = xs - cx, ys - cy
    u = (dx * math.cos(t) + dy * math.sin(t)) / (ax1 / 2)
    v = (-dx * math.sin(t) + dy * math.cos(t)) / (ax2 / 2)
    rho = np.hypot(u, v)
    band = (rho >= 0.86) & (rho <= 1.08)
    sec = ((np.arctan2(v[band], u[band]) + math.pi) / (2 * math.pi) * sectors).astype(int) % sectors
    return float(len(np.unique(sec))) / sectors, (float(cx), float(cy), float(ax1), float(ax2), float(ang))


# ── Stamps and handwriting ───────────────────────────────────────────────────────────────────


def find_stamps(lines: np.ndarray, px_per_mm: float, cfg: ZoneConfig) -> list[tuple[int, int, int, int]]:
    """Rectangular frames of colour ink lines: (x0, y0, x1, y1) in mask pixels."""
    if not lines.any():
        return []
    closed = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        wmm, hmm = w / px_per_mm, h / px_per_mm
        if not (
            cfg.stamp_min_mm <= wmm <= cfg.stamp_max_mm and cfg.stamp_min_mm / 2 <= hmm <= cfg.stamp_max_mm
        ):
            continue
        sub = closed[y : y + h, x : x + w] > 0
        band = max(2, int(0.8 * px_per_mm))
        edges = [
            sub[:band].any(0).mean(),
            sub[-band:].any(0).mean(),
            sub[:, :band].any(1).mean(),
            sub[:, -band:].any(1).mean(),
        ]
        if sum(e >= cfg.stamp_edge_coverage for e in edges) >= 3:
            out.append((x, y, x + w, y + h))
    return out


def _line_share(comp: np.ndarray, px_per_mm: float, cfg: ZoneConfig) -> float:
    """Share of a component's ink on straight segments (Hough, any angle): pipes and rules score ~1."""
    n = int(comp.sum() // 255) if comp.dtype == np.uint8 else int(comp.sum())
    if n == 0:
        return 1.0
    segs = cv2.HoughLinesP(
        comp, 1, np.pi / 180, threshold=max(8, int(2 * px_per_mm)),
        minLineLength=max(6, int(cfg.line_min_mm * px_per_mm)), maxLineGap=max(1, int(0.3 * px_per_mm)),
    )  # fmt: skip
    if segs is None:
        return 0.0
    drawn = np.zeros_like(comp)
    for x1, y1, x2, y2 in np.asarray(segs).reshape(-1, 4):
        cv2.line(drawn, (int(x1), int(y1)), (int(x2), int(y2)), 255, max(2, int(0.35 * px_per_mm)))
    return float(((drawn > 0) & (comp > 0)).sum()) / n


def find_handwriting(
    mask: np.ndarray,
    printed: np.ndarray,
    seals: Sequence[tuple[float, float, float, float]],
    lines: np.ndarray,
    px_per_mm: float,
    cfg: ZoneConfig,
) -> list[tuple[int, int, int, int, str, float]]:
    """Handwriting clusters: (x0, y0, x1, y1, subkind, conf) in mask pixels."""
    rest = mask.copy()
    rest[lines > 0] = 0
    rest[printed > 0] = 0
    for cx, cy, r, _ in seals:
        cv2.circle(rest, (int(cx), int(cy)), int(r * 1.06), 0, -1)
    if not rest.any():
        return []
    gap = max(1, int(cfg.handwriting_join_mm * px_per_mm))
    joined = cv2.dilate(rest, np.ones((gap, gap), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    out = []
    min_ink = cfg.handwriting_min_ink_mm2 * px_per_mm * px_per_mm
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        sub = (labels[y : y + h, x : x + w] == i) & (rest[y : y + h, x : x + w] > 0)
        ink = int(sub.sum())
        if ink < min_ink:
            continue
        ys, xs = np.nonzero(sub)
        bx0, by0, bx1, by1 = x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1
        wmm, hmm = (bx1 - bx0) / px_per_mm, (by1 - by0) / px_per_mm
        long_mm, short_mm = max(wmm, hmm), min(wmm, hmm)
        if (
            long_mm < cfg.handwriting_min_mm
            or long_mm > cfg.handwriting_max_mm
            or short_mm < cfg.handwriting_min_short_mm
        ):
            continue
        comp = (sub * 255).astype(np.uint8)
        ls = _line_share(comp, px_per_mm, cfg)
        if ls > cfg.handwriting_max_line_share:
            continue
        subkind = "SIGNATURE" if long_mm >= cfg.signature_min_mm else "TEXT"
        conf = 0.6 + 0.3 * (1.0 - ls)
        out.append((int(bx0), int(by0), int(bx1), int(by1), subkind, conf))
    return _merge_boxes(out, gap)


def _merge_boxes(
    boxes: list[tuple[int, int, int, int, str, float]], gap: int
) -> list[tuple[int, int, int, int, str, float]]:
    """Merge overlapping handwriting boxes (a signature split into strokes)."""
    items = sorted(boxes)
    merged: list[list[Any]] = []
    for b in items:
        for m in merged:
            if b[0] <= m[2] + gap and m[0] <= b[2] + gap and b[1] <= m[3] + gap and m[1] <= b[3] + gap:
                m[0], m[1], m[2], m[3] = min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])
                if b[4] == "SIGNATURE":
                    m[4] = "SIGNATURE"
                m[5] = max(m[5], b[5])
                break
        else:
            merged.append(list(b))
    return [tuple(m) for m in merged]  # type: ignore[misc]


# ── QR ───────────────────────────────────────────────────────────────────────────────────────


def _decode_qr(gray: np.ndarray) -> tuple[str | None, np.ndarray | None]:
    """(payload or None, 4×2 corner points or None) of the first QR code in a grayscale crop."""
    det = cv2.QRCodeDetector()
    try:
        val, pts, _ = det.detectAndDecode(gray)
    except cv2.error:
        val, pts = "", None
    if pts is not None and len(pts):
        return (val or None), np.asarray(pts, float).reshape(-1, 2)
    try:
        ok, pts = cv2.QRCodeDetectorAruco().detectMulti(gray)
    except cv2.error:
        ok, pts = False, None
    if ok and pts is not None and len(pts):
        return None, np.asarray(pts[0], float).reshape(-1, 2)
    return None, None


def qr_from_images(page, cfg: ZoneConfig) -> list[Zone]:
    """QR codes placed as small images (e-document system stamps): decoded from the image's own pixels."""
    import pymupdf

    doc = page.parent
    w, h = page.rect.width, page.rect.height
    out: list[Zone] = []
    seen: set[int] = set()
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref") or 0
        if not xref or xref in seen:
            continue
        r = pymupdf.Rect(info["bbox"]) * page.rotation_matrix
        wmm, hmm = abs(r.width) * MM_PER_IN / 72, abs(r.height) * MM_PER_IN / 72
        if not (cfg.qr_min_mm <= min(wmm, hmm) and max(wmm, hmm) <= cfg.qr_max_mm):
            continue
        if (
            not 0.6 <= (wmm / max(hmm, 1e-6)) <= 1.6
            or max(info.get("width", 0), info.get("height", 0)) > 2000
        ):
            continue
        seen.add(xref)
        try:
            pix = pymupdf.Pixmap(doc, xref)
            if pix.alpha or pix.n - pix.alpha != 1:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., 0].copy()
        except Exception:  # an image the decoder cannot read is simply not a QR candidate
            continue
        pad = max(8, gray.shape[0] // 10)
        gray = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        payload, pts = _decode_qr(gray)
        if pts is None:
            continue
        box = [min(r.x0, r.x1) / w, min(r.y0, r.y1) / h, max(r.x0, r.x1) / w, max(r.y0, r.y1) / h]
        attrs: dict[str, Any] = {"method": "embedded_image", "xref": int(xref)}
        if payload:
            attrs["payload"] = payload
        out.append(Zone("QR", [min(1.0, max(0.0, v)) for v in box], 0.99 if payload else 0.9, attrs))
    return out


def qr_from_render(gray: np.ndarray, dpi: int, cfg: ZoneConfig) -> list[tuple[list[float], str | None]]:
    """QR codes on the render (scan content, vector QR): normalized boxes and payloads when decodable."""
    h, w = gray.shape[:2]
    work = gray
    s = 1.0
    if dpi > cfg.qr_render_dpi:
        s = cfg.qr_render_dpi / dpi
        work = cv2.resize(gray, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    try:
        ok, pts = cv2.QRCodeDetectorAruco().detectMulti(work)
    except cv2.error:
        ok, pts = False, None
    out = []
    if not ok or pts is None:
        return out
    for q in pts:
        q = np.asarray(q, float).reshape(-1, 2) / s
        x0, y0 = q.min(0)
        x1, y1 = q.max(0)
        side_mm = max(x1 - x0, y1 - y0) / dpi * MM_PER_IN
        if not cfg.qr_min_mm <= side_mm <= cfg.qr_max_mm:
            continue
        m = 0.1 * (x1 - x0)
        crop = gray[max(0, int(y0 - m)) : int(y1 + m) + 1, max(0, int(x0 - m)) : int(x1 + m) + 1]
        payload, _ = (
            _decode_qr(cv2.copyMakeBorder(crop, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255))
            if crop.size
            else (None, None)
        )
        out.append(([max(0.0, x0 / w), max(0.0, y0 / h), min(1.0, x1 / w), min(1.0, y1 / h)], payload))
    return out


# ── Page entry point ─────────────────────────────────────────────────────────────────────────


def detect_zones(
    img_bgr: np.ndarray,
    dpi: int,
    printed_boxes_px: Sequence[Sequence[float]],
    cfg: ZoneConfig,
    *,
    image_qr: Sequence[Zone] = (),
    vector_sheet: bool = False,
) -> tuple[list[Zone], dict[str, Any]]:
    """Zones of one displayed-page render at ``dpi``. ``printed_boxes_px``: pixel boxes of confidently read OCR
    lines (printed text), used to keep printed colour text out of the handwriting zones. ``vector_sheet``: a
    vector drawing sheet (long side ≥ ``sheet_min_long_side_mm``): handwriting only in the title-block window.
    Returns (zones, diagnostics incl. the colour and black ink masks at work resolution for
    :func:`assign_tokens`)."""
    _h, _w = img_bgr.shape[:2]
    zones: list[Zone] = list(image_qr)
    factor = min(1.0, cfg.work_dpi / float(dpi))
    px_per_mm = dpi * factor / MM_PER_IN
    full = colour_ink_mask(img_bgr, cfg)
    mask = _downscale_max(full, factor)
    mh, mw = mask.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    dark = _downscale_max(((gray < cfg.dark_level) & (full == 0)).astype(np.uint8) * 255, factor)
    diag: dict[str, Any] = {"mask": mask, "dark": dark, "colour_share": round(float((mask > 0).mean()), 5)}

    def norm(x0: float, y0: float, x1: float, y1: float) -> list[float]:
        return [max(0.0, x0 / mw), max(0.0, y0 / mh), min(1.0, x1 / mw), min(1.0, y1 / mh)]

    if mask.any():
        seals = find_seals(mask, px_per_mm, cfg)
        for cx, cy, r, cov in seals:
            zones.append(
                Zone("SEAL", norm(cx - r, cy - r, cx + r, cy + r), 0.5 + 0.5 * cov,
                     {"method": "colour_hough", "diameter_mm": round(2 * r / px_per_mm, 1), "ring": round(cov, 2)})
            )  # fmt: skip
        lines = _straight_lines(mask, px_per_mm, cfg)
        for x0, y0, x1, y1 in find_stamps(lines, px_per_mm, cfg):
            box = norm(x0, y0, x1, y1)
            if not any(z.kind == "SEAL" and _iou(z.bbox, box) > 0.3 for z in zones):
                zones.append(Zone("STAMP", box, 0.8, {"method": "colour_frame"}))
        printed = np.zeros_like(mask)
        for b in printed_boxes_px:
            x0, y0, x1, y1 = (round(v * factor) for v in b)
            printed[max(0, y0) : max(0, y1) + 1, max(0, x0) : max(0, x1) + 1] = 255
        if vector_sheet:  # keep only the title-block window (bottom right)
            wx = int(mw - cfg.title_block_window_mm[0] * px_per_mm)
            wy = int(mh - cfg.title_block_window_mm[1] * px_per_mm)
            window = np.zeros_like(mask)
            window[max(0, wy) :, max(0, wx) :] = 255
            hw_mask = cv2.bitwise_and(mask, window)
        else:
            hw_mask = mask
        dark_full = (gray < cfg.dark_level) & (full == 0)
        for x0, y0, x1, y1, sub, conf in find_handwriting(hw_mask, printed, seals, lines, px_per_mm, cfg):
            why = _not_handwriting((x0, y0, x1, y1), sub, full, dark_full, factor, dpi, seals, cfg)
            if why:
                diag.setdefault("handwriting_rejected", []).append(why)
                continue
            if min(x1 - x0, y1 - y0) >= cfg.seal_oval_min_mm * px_per_mm:
                ring = ellipse_ring(mask[y0:y1, x0:x1])
                if ring is not None and ring[0] >= cfg.seal_ring_coverage:
                    zones.append(
                        Zone("SEAL", norm(x0, y0, x1, y1), 0.5 + 0.5 * ring[0],
                             {"method": "colour_ellipse", "axes_mm": [round(ring[1][2] / px_per_mm, 1),
                              round(ring[1][3] / px_per_mm, 1)], "ring": round(ring[0], 2)})
                    )  # fmt: skip
                    continue
            zones.append(
                Zone("HANDWRITING", norm(x0, y0, x1, y1), conf, {"method": "colour_strokes", "subkind": sub})
            )
    if cfg.qr:
        for box, payload in qr_from_render(gray, dpi, cfg):
            if any(z.kind == "QR" and _iou(z.bbox, box) > 0.3 for z in zones):
                continue
            attrs: dict[str, Any] = {"method": "render_detector"}
            if payload:
                attrs["payload"] = payload
            zones.append(Zone("QR", box, 0.95 if payload else 0.8, attrs))
    return zones, diag


def _not_handwriting(
    box: tuple[int, int, int, int],
    subkind: str,
    full: np.ndarray,
    dark_full: np.ndarray,
    factor: float,
    dpi: int,
    seals: Sequence[tuple[float, float, float, float]],
    cfg: ZoneConfig,
) -> str | None:
    """Why a colour-ink cluster (work-resolution box) is not handwriting, from its full-resolution ink; None if
    it is. Measured on the GT v2 pages: colour fringes of black print, filled logos and bold stamp graphics,
    and leftovers of seal rings are the false alarms of the stroke detector."""
    x0, y0, x1, y1 = box
    if seals:  # mostly inside a seal disc: ring or seal text the disc mask did not remove
        inside = 0.0
        for cx, cy, r, _ in seals:
            iw = max(0.0, min(x1, cx + r) - max(x0, cx - r))
            ih = max(0.0, min(y1, cy + r) - max(y0, cy - r))
            inside = max(inside, iw * ih / max(1.0, (x1 - x0) * (y1 - y0)))
        if inside >= 0.5:
            return "seal_residue"
    s = 1.0 / factor
    fx0, fy0, fx1, fy1 = int(x0 * s), int(y0 * s), math.ceil(x1 * s), math.ceil(y1 * s)
    ink = full[fy0:fy1, fx0:fx1] > 0
    n = int(ink.sum())
    if n == 0:
        return "no_ink"
    px_mm = dpi / MM_PER_IN
    k = max(3, round(0.4 * px_mm) | 1)
    near_dark = cv2.dilate(dark_full[fy0:fy1, fx0:fx1].astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    if (ink & near_dark).sum() / n >= cfg.handwriting_max_fringe:
        return "colour_fringe"
    dt = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)
    if 2.0 * float(dt[ink].mean()) / px_mm > cfg.handwriting_max_stroke_mm:
        return "wide_strokes"
    if subkind == "TEXT" and n / ink.size > cfg.handwriting_text_max_fill:
        return "dense_small"
    return None


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def assign_tokens(
    zones: list[Zone],
    tokens: list[dict[str, Any]],
    colour_mask: np.ndarray | None,
    dark_mask: np.ndarray | None,
    cfg: ZoneConfig,
) -> dict[str, int]:
    """List the tokens centred in each zone (``attrs.token_ids``) and flag handwritten OCR tokens ABSTAIN.

    A token is handwritten when it is an OCR token centred in a HANDWRITING zone and at least
    ``handwritten_token_colour_share`` of the ink in its box is colour ink (printed black text under a blue
    signature keeps its flag); QR modules read as text are always ABSTAIN. Masks are the work-resolution
    colour and black ink of :func:`detect_zones` (``diag``). Returns counts for the page report.
    """
    counts = {"tokens_in_zones": 0, "tokens_abstained": 0, "tokens_under_seal": 0}
    if not zones or not tokens:
        return counts
    centres = np.array(
        [[(t["bbox"][0] + t["bbox"][2]) / 2, (t["bbox"][1] + t["bbox"][3]) / 2] for t in tokens]
    )
    in_any = np.zeros(len(tokens), bool)
    for z in zones:
        b = z.bbox
        inside = np.nonzero(
            (centres[:, 0] >= b[0])
            & (centres[:, 0] <= b[2])
            & (centres[:, 1] >= b[1])
            & (centres[:, 1] <= b[3])
        )[0]
        z.attrs["token_ids"] = [int(tokens[i]["id"]) for i in inside]
        in_any[inside] = True
        if z.kind == "SEAL":
            counts["tokens_under_seal"] += len(inside)
        if z.kind not in ("HANDWRITING", "QR"):
            continue
        for i in inside:
            t = tokens[i]
            if t.get("source") not in ("OCR", "OCR_LAYER_ISOLATED"):
                continue
            if z.kind == "HANDWRITING" and float(t.get("conf", 0.0)) >= cfg.handwritten_token_max_conf:
                continue  # read confidently: printed text under or next to the handwriting
            if z.kind == "HANDWRITING" and colour_mask is not None:
                mh, mw = colour_mask.shape[:2]
                x0, y0 = int(t["bbox"][0] * mw), int(t["bbox"][1] * mh)
                x1, y1 = math.ceil(t["bbox"][2] * mw), math.ceil(t["bbox"][3] * mh)
                win = (slice(max(0, y0), max(y0 + 1, y1)), slice(max(0, x0), max(x0 + 1, x1)))
                col = int((colour_mask[win] > 0).sum())
                blk = int((dark_mask[win] > 0).sum()) if dark_mask is not None else 0
                if col == 0 or col / (col + blk) < cfg.handwritten_token_colour_share:
                    continue
            if t.get("quality_flag") != "ABSTAIN":
                t["quality_flag"] = "ABSTAIN"
                counts["tokens_abstained"] += 1
    counts["tokens_in_zones"] = int(in_any.sum())
    return counts
