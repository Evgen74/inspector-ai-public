"""OCR core v2 on one image (96 §4, 97 §2.13 F3): tiled detection with seam merge, crops, recognition with
score-driven retries (no text-line classifier), long-line chunking and local re-detection.

Coordinates are image pixels of the input array. The caller maps them to the displayed page
(content-rotation back-mapping, region offset, normalisation), see :mod:`inspector_docproc.recognize`.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from inspector_docproc.config import OcrConfig
from inspector_docproc.ocr.engine import Detector, OcrEngine, RecResult

# ── Data ─────────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class OcrWord:
    text: str
    quad: np.ndarray  # (4, 2) image px, clockwise from the reading-direction top-left
    conf: float


@dataclass(slots=True)
class OcrLine:
    quad: np.ndarray  # (4, 2) float32 image px as detected (tl, tr, br, bl in image orientation)
    text: str
    score: float
    angle: int  # reading direction relative to the image, clockwise degrees: 0/90/180/270
    words: list[OcrWord] = field(default_factory=list)
    detector: str = ""
    via: str = "base"  # base | rot180 | unrotated | chunked | redetect
    source: str = "OCR"  # contract TextSource: OCR | OCR_LAYER_ISOLATED

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        q = self.quad
        return float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())


@dataclass(slots=True)
class OcrStats:
    n_tiles: int = 0
    n_tiles_blank: int = 0
    n_boxes: int = 0
    n_retry180: int = 0
    n_unrotated: int = 0
    n_chunked: int = 0
    n_redetect: int = 0
    n_retry_skipped: int = 0  # retry reads not made because they could not win (see recognize_crops)
    det_s: float = 0.0
    rec_s: float = 0.0
    detector: str = ""

    def as_dict(self) -> dict[str, float | int | str]:
        return {k: getattr(self, k) for k in self.__slots__}


# ── Tiling and seam merge ────────────────────────────────────────────────────────────────────


def tile_origins(size: int, tile: int, overlap: int) -> list[int]:
    """Tile start offsets along one axis (identical to the measured prototype grid)."""
    if size <= tile:
        return [0]
    return list(range(0, size - overlap, tile - overlap))


def merge_seam_boxes(quads: list[np.ndarray], tiles_of: list[int]) -> list[np.ndarray]:
    """Merge boxes from different tiles that are collinear and overlap (lines cut by a tile seam).

    Two boxes merge when they come from disjoint tile sets, have the same orientation (horizontal or
    vertical), overlap, and agree on the cross-axis (overlap ≥ 60 % of the smaller extent, extents within
    45 %). Merged boxes become axis-aligned rectangles; untouched boxes keep their quads.
    """
    rects = [[q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()] for q in quads]
    src = [{t} for t in tiles_of]
    alive = [True] * len(rects)
    keep: list[np.ndarray | None] = list(quads)
    changed = True
    while changed:
        changed = False
        idx = sorted([i for i in range(len(rects)) if alive[i]], key=lambda i: rects[i][0])
        for a_i, i in enumerate(idx):
            if not alive[i]:
                continue
            for j in idx[a_i + 1 :]:
                if not alive[j]:
                    continue
                ri, rj = rects[i], rects[j]
                if rj[0] > ri[2]:
                    break
                if src[i] & src[j]:
                    continue
                ix = min(ri[2], rj[2]) - max(ri[0], rj[0])
                iy = min(ri[3], rj[3]) - max(ri[1], rj[1])
                if ix <= 0 or iy <= 0:
                    continue
                wi, hi = ri[2] - ri[0], ri[3] - ri[1]
                wj, hj = rj[2] - rj[0], rj[3] - rj[1]
                horiz_i, horiz_j = wi >= hi, wj >= hj
                if horiz_i != horiz_j:
                    continue
                if horiz_i:
                    if iy < 0.6 * min(hi, hj) or abs(hi - hj) > 0.45 * max(hi, hj):
                        continue
                elif ix < 0.6 * min(wi, wj) or abs(wi - wj) > 0.45 * max(wi, wj):
                    continue
                rects[i] = [min(ri[0], rj[0]), min(ri[1], rj[1]), max(ri[2], rj[2]), max(ri[3], rj[3])]
                src[i] = src[i] | src[j]
                alive[j] = False
                keep[i] = None
                changed = True
    out: list[np.ndarray] = []
    for i in range(len(rects)):
        if not alive[i]:
            continue
        q = keep[i]
        if q is not None:
            out.append(q.astype(np.float32))
        else:
            x0, y0, x1, y1 = rects[i]
            out.append(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32))
    return out


def detect_tiled(
    det: Detector, img: np.ndarray, cfg: OcrConfig, stats: OcrStats | None = None
) -> list[np.ndarray]:
    """Detection on overlapping fixed-size tiles, then seam merge. Returns quads in image px."""
    h, w = img.shape[:2]
    quads: list[np.ndarray] = []
    tiles_of: list[int] = []
    ti = 0
    for y in tile_origins(h, cfg.det_tile_px, cfg.det_overlap_px):
        for x in tile_origins(w, cfg.det_tile_px, cfg.det_overlap_px):
            sub = img[y : y + cfg.det_tile_px, x : x + cfg.det_tile_px]
            if stats is not None:
                stats.n_tiles += 1
            if sub.size == 0 or int(sub.min()) > cfg.blank_tile_level:
                if stats is not None:
                    stats.n_tiles_blank += 1
                ti += 1
                continue
            boxes, _ = det.detect(np.ascontiguousarray(sub))
            for b in boxes:
                quads.append(b + np.array([x, y], np.float32))
                tiles_of.append(ti)
            ti += 1
    return merge_seam_boxes(quads, tiles_of)


# ── Crops ────────────────────────────────────────────────────────────────────────────────────


def quad_size(q: np.ndarray) -> tuple[float, float]:
    wq = max(float(np.linalg.norm(q[0] - q[1])), float(np.linalg.norm(q[2] - q[3])))
    hq = max(float(np.linalg.norm(q[0] - q[3])), float(np.linalg.norm(q[1] - q[2])))
    return wq, hq


def rotate_crop(img: np.ndarray, quad: np.ndarray, vertical_ratio: float = 1.5) -> np.ndarray:
    """Perspective crop of a quad (RapidOCR ``get_rotate_crop_image``); tall crops are turned 90° CCW."""
    pts = quad.astype(np.float32)
    cw = int(max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[2] - pts[3])))
    ch = int(max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2])))
    cw, ch = max(cw, 1), max(ch, 1)
    dst = np.array([[0, 0], [cw, 0], [cw, ch], [0, ch]], np.float32)
    m = cv2.getPerspectiveTransform(pts, dst)
    crop = cv2.warpPerspective(img, m, (cw, ch), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
    if crop.shape[0] * 1.0 / crop.shape[1] >= vertical_ratio:
        crop = np.rot90(crop)
    return np.ascontiguousarray(crop)


# ── Word geometry ────────────────────────────────────────────────────────────────────────────


def _bilerp(quad: np.ndarray, u: float, v: float) -> np.ndarray:
    top = quad[0] + (quad[1] - quad[0]) * u
    bottom = quad[3] + (quad[2] - quad[3]) * u
    return top + (bottom - top) * v


def reading_span_to_quad(quad: np.ndarray, rot_k: int, a: float, b: float) -> np.ndarray:
    """Map a span [a, b] along the recognised image's x-axis back to a quad in image px.

    ``rot_k`` is the number of CCW quarter turns (np.rot90) applied to the dewarped crop D to obtain the
    image R that was read. Returned corners are clockwise starting from the reading-direction top-left.
    """
    k = rot_k % 4
    if k == 0:  # R = D
        rect = [(a, 0.0), (b, 0.0), (b, 1.0), (a, 1.0)]
    elif k == 2:  # R = rot180(D)
        rect = [(1 - a, 1.0), (1 - b, 1.0), (1 - b, 0.0), (1 - a, 0.0)]
    elif k == 1:  # R = rot90_ccw(D): R column ↔ D row (top→bottom), R row 0 ↔ D right column
        rect = [(1.0, a), (1.0, b), (0.0, b), (0.0, a)]
    else:  # k == 3, R = rot90_cw(D): R column ↔ D row (bottom→top), R row 0 ↔ D left column
        rect = [(0.0, 1 - a), (0.0, 1 - b), (1.0, 1 - b), (1.0, 1 - a)]
    return np.array([_bilerp(quad, u, v) for u, v in rect], np.float32)


def _words_for(res: RecResult, quad: np.ndarray, rot_k: int) -> list[OcrWord]:
    return [
        OcrWord(text, reading_span_to_quad(quad, rot_k, a, b), round(conf, 5))
        for text, a, b, conf in res.words()
    ]


def angle_of(quad: np.ndarray, rot_k: int) -> int:
    """Reading direction (clockwise degrees) of a reading with ``rot_k`` CCW turns of the dewarped crop."""
    return (rot_k % 4) * 90


# ── Recognition with retries ─────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Reading:
    res: RecResult
    rot_k: int
    via: str
    words: list[OcrWord] | None = None  # set when the reading has its own geometry (chunk/redetect)


def _chunk_long_crop(
    eng: OcrEngine, crop: np.ndarray, cfg: OcrConfig
) -> tuple[RecResult, list[tuple[int, int]]]:
    """Split a very long crop at inter-word ink gaps and read the pieces (96 §4.5, fallback only)."""
    h, w = crop.shape[:2]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    ink = (g < 150).sum(0)
    x = 0
    maxw = int(cfg.chunk_ratio * h * 0.8)
    spans: list[tuple[int, int]] = []
    while x < w:
        if w - x <= maxw * 1.25:
            spans.append((x, w))
            break
        lo, hi = x + int(maxw * 0.6), x + maxw
        best, cut, cur, cs = -1, lo + (hi - lo) // 2, 0, lo
        for k, v in enumerate(ink[lo:hi]):
            if v == 0:
                if cur == 0:
                    cs = lo + k
                cur += 1
                if cur > best:
                    best, cut = cur, cs + cur // 2
            else:
                cur = 0
        spans.append((x, cut))
        x = cut
    pieces = [np.ascontiguousarray(crop[:, a:b]) for a, b in spans]
    reads = eng.rec(pieces)
    text = " ".join(r.text for r in reads)
    n = [max(len(r.text), 1) for r in reads]
    score = sum(r.score * k for r, k in zip(reads, n, strict=True)) / sum(n)
    # stitch character positions back onto the full crop width
    pos: list[float] = []
    prob: list[float] = []
    for idx, (r, (a, b)) in enumerate(zip(reads, spans, strict=True)):
        if idx > 0:
            pos.append(a / w)
            prob.append(r.score)
        for p, pr in zip(r.char_pos, r.char_prob, strict=True):
            pos.append((a + p * (b - a)) / w)
            prob.append(pr)
    step = min((r.step * (b - a) / w for r, (a, b) in zip(reads, spans, strict=True)), default=0.0)
    return RecResult(text, float(score), pos, prob, step=step), spans


def _read_retries(
    eng: OcrEngine,
    idx: list[int],
    shapes: list[tuple[int, int]],
    make: Callable[[int], np.ndarray],
    readings: list[_Reading],
    cfg: OcrConfig,
    stats: OcrStats | None,
    skip: bool,
) -> list[tuple[int, RecResult]]:
    """Re-read crops ``idx`` (``make(i)`` builds the turned crop, ``shapes`` its (h, w)) for a retry pass.

    A retry replaces a reading only when its score beats it by ``retry_gain``; scores never exceed 1.0 (mean
    of per-character probabilities rounded to 5 decimals), so a crop whose current score is at least
    ``1 − retry_gain`` cannot be replaced and is not re-read (``skip``). The others keep the padded width the
    whole pass would have given them (:meth:`Recognizer.plan_widths`), so every reading and every decision
    is exactly the one of the full pass (verified bit-for-bit by ``tests/test_docproc_rec_batching.py``).
    """
    widths = eng.rec.plan_widths(shapes)
    live = [k for k, i in enumerate(idx) if not skip or readings[i].res.score + cfg.retry_gain < 1.0]
    if stats is not None:
        stats.n_retry_skipped += len(idx) - len(live)
    if not live:
        return []
    reads = eng.rec([np.ascontiguousarray(make(idx[k])) for k in live], widths=[widths[k] for k in live])
    return [(idx[k], r) for k, r in zip(live, reads, strict=True)]


def recognize_crops(
    eng: OcrEngine,
    quads: list[np.ndarray],
    crops: list[np.ndarray],
    vertical: list[bool],
    cfg: OcrConfig,
    stats: OcrStats | None = None,
) -> list[_Reading]:
    """Batch recognition plus the measured retry policy of the v2 prototype.

    1. Base reading (vertical crops were turned 90° CCW by the cropper → rot_k = 1).
    2. Very long crops with a weak score are chunked at ink gaps and re-read.
    3. Vertical crops and lines below ``retry_180_below`` are also read upside down.
    4. «Short vertical» crops (single glyphs, 2–3 char tokens) are also read un-rotated.
    Each retry replaces the reading only when its score is higher by ``retry_gain``.
    """
    if not crops:
        return []
    base = eng.rec(crops)
    readings = [_Reading(r, 1 if vertical[i] else 0, "base") for i, r in enumerate(base)]
    for i, crop in enumerate(crops):
        h, w = crop.shape[:2]
        if w <= cfg.chunk_ratio * h or readings[i].res.score >= cfg.chunk_below:
            continue
        res, _ = _chunk_long_crop(eng, crop, cfg)
        if res.score > readings[i].res.score + cfg.chunk_gain:
            readings[i] = _Reading(res, readings[i].rot_k, "chunked")
            if stats is not None:
                stats.n_chunked += 1
    skip = bool(getattr(eng, "skip_futile_retries", True))
    redo = [i for i in range(len(crops)) if vertical[i] or readings[i].res.score < cfg.retry_180_below]
    if redo:
        flipped = _read_retries(
            eng,
            redo,
            [crops[i].shape[:2] for i in redo],
            lambda i: np.rot90(crops[i], 2),
            readings,
            cfg,
            stats,
            skip,
        )
        for i, r in flipped:
            if r.score > readings[i].res.score + cfg.retry_gain:
                readings[i] = _Reading(r, (readings[i].rot_k + 2) % 4, "rot180")
                if stats is not None:
                    stats.n_retry180 += 1
    short = [
        i
        for i in range(len(crops))
        if vertical[i] and crops[i].shape[1] < cfg.short_vertical_max_ratio * crops[i].shape[0]
    ]
    if short:
        unrot = _read_retries(
            eng, short, [crops[i].shape[1::-1] for i in short], lambda i: np.rot90(crops[i], -1), readings, cfg,
            stats, skip,
        )  # fmt: skip
        for i, r in unrot:
            if r.score > readings[i].res.score + cfg.retry_gain:
                readings[i] = _Reading(r, 0, "unrotated")
                if stats is not None:
                    stats.n_unrotated += 1
    return readings


def redetect_long_line(
    eng: OcrEngine, det: Detector, img: np.ndarray, bb: tuple[float, float, float, float]
) -> tuple[str, float, list[OcrWord]]:
    """Local re-detection for a long, curved or skewed line (96 §4.5).

    The band is split at inter-word gaps into windows about 10 line-heights wide; detection runs per
    window so boxes follow the local baseline; boxes centred on the target line are recognised.
    """
    x0, y0, x1, y1 = (round(v) for v in bb)
    h = max(y1 - y0, 1)
    ih, iw = img.shape[:2]
    by0, by1 = max(0, y0 - int(0.5 * h)), min(ih, y1 + int(0.5 * h))
    bx0 = max(0, x0 - 5)
    band = img[by0:by1, bx0 : min(iw, x1 + 5)]
    if band.size == 0:
        return "", 0.0, []
    g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band
    core = g[int(0.4 * h) : int(0.4 * h) + h] if g.shape[0] > h else g
    ink = (core < 150).sum(0)
    target = 10 * h
    cuts = [0]
    x = 0
    bw = band.shape[1]
    while bw - x > 1.4 * target:
        lo, hi = x + int(0.7 * target), x + int(1.3 * target)
        zeros = np.where(ink[lo:hi] == 0)[0]
        c = lo + (int(zeros[np.argmin(np.abs(zeros - (hi - lo) // 2))]) if len(zeros) else (hi - lo) // 2)
        cuts.append(int(c))
        x = int(c)
    cuts.append(bw)
    texts: list[str] = []
    weights: list[tuple[float, int]] = []
    words: list[OcrWord] = []
    centre = 0.5 * h + (y0 - by0)
    for a, b in itertools.pairwise(cuts):
        win = np.ascontiguousarray(band[:, a:b])
        boxes, _ = det.detect(win)
        if len(boxes) == 0:
            continue
        cand = sorted(boxes, key=lambda q: float(q[:, 0].min()))
        keep = [q for q in cand if abs(float(q[:, 1].mean()) - centre) < 0.35 * h]
        if not keep:
            continue
        crops = [rotate_crop(win, q) for q in keep]
        reads = eng.rec(crops)
        for q, r in zip(keep, reads, strict=True):
            texts.append(r.text)
            weights.append((r.score, max(len(r.text), 1)))
            q_img = q + np.array([bx0 + a, by0], np.float32)
            words.extend(_words_for(r, q_img, 0))
    if not texts:
        return "", 0.0, []
    score = sum(s * n for s, n in weights) / sum(n for _, n in weights)
    return " ".join(texts), float(score), words


# ── Public entry point ───────────────────────────────────────────────────────────────────────


def ocr_image(
    eng: OcrEngine,
    img: np.ndarray,
    cfg: OcrConfig | None = None,
    *,
    detector: str = "small",
    quads: list[np.ndarray] | None = None,
) -> tuple[list[OcrLine], OcrStats]:
    """Run OCR v2 on a BGR image. ``quads`` skips detection (coverage routing passes uncovered boxes)."""
    cfg = cfg or eng.cfg
    det = eng.detector(detector)
    stats = OcrStats(detector=det.name)
    t0 = time.perf_counter()
    if quads is None:
        quads = detect_tiled(det, img, cfg, stats)
    stats.det_s = time.perf_counter() - t0
    stats.n_boxes = len(quads)
    t1 = time.perf_counter()
    crops: list[np.ndarray] = []
    vertical: list[bool] = []
    for q in quads:
        wq, hq = quad_size(q)
        crops.append(rotate_crop(img, q, cfg.vertical_ratio))
        vertical.append(hq / max(wq, 1.0) >= cfg.vertical_ratio)
    readings = recognize_crops(eng, quads, crops, vertical, cfg, stats)
    lines: list[OcrLine] = []
    for q, vert, rd in zip(quads, vertical, readings, strict=True):
        text, score, words, via, rot_k = rd.res.text, rd.res.score, None, rd.via, rd.rot_k
        x0, y0, x1, y1 = (
            float(q[:, 0].min()),
            float(q[:, 1].min()),
            float(q[:, 0].max()),
            float(q[:, 1].max()),
        )
        if (
            not vert
            and score < cfg.redetect_below
            and (x1 - x0) >= cfg.redetect_min_ratio * max(y1 - y0, 1.0)
        ):
            t2, s2, w2 = redetect_long_line(eng, det, img, (x0, y0, x1, y1))
            if s2 > score + cfg.redetect_gain:
                text, score, words, via, rot_k = t2, s2, w2, "redetect", 0
                stats.n_redetect += 1
        if words is None:
            words = _words_for(rd.res, q, rot_k)
        lines.append(
            OcrLine(
                quad=q.astype(np.float32),
                text=text,
                score=float(score),
                angle=angle_of(q, rot_k),
                words=words,
                detector=det.name,
                via=via,
            )
        )
    stats.rec_s = time.perf_counter() - t1
    return lines, stats
