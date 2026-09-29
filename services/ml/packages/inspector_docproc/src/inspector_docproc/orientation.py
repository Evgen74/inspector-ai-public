"""Page-content orientation detector (96 §4.3, R-03): 0/90/180/270 without a text-line classifier.

1. Detect text boxes on a thumbnail (long side 1600 px) and compare vertical vs horizontal boxes:
   text rotated by 90/270 produces mostly tall boxes.
2. Disambiguate 0 vs 180 (or 90 vs 270) with a recognition probe: the largest boxes of the dominant
   orientation are read as cropped and turned 180°; the mean recognition score decides. When neither
   orientation dominates (plans, schemes), both are probed and the best of the four hypotheses wins.
3. When the probe is ambiguous (score margin below ``tie_margin``) and the Tesseract binary with
   ``osd.traineddata`` is installed, its OSD result breaks the tie. Tesseract is optional.

Result convention: ``content_rotation`` is the clockwise rotation of the content relative to the
displayed page (contract ``page.content_rotation``). ``k = content_rotation // 90`` is the number of
counter-clockwise quarter turns (``np.rot90(img, k)``) that make the content upright.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from inspector_docproc.config import OrientationConfig
from inspector_docproc.ocr.engine import OcrEngine
from inspector_docproc.ocr.pipeline import quad_size, rotate_crop

log = logging.getLogger("inspector_docproc.orientation")


@dataclass(slots=True)
class OrientationResult:
    content_rotation: int  # 0/90/180/270, clockwise
    method: str  # det_rec_probe | osd | no_text | default
    margin: float = 0.0  # mean probe score of the best hypothesis minus the runner-up
    n_vertical: int = 0
    n_horizontal: int = 0
    score_upright: float = 0.0
    score_flipped: float = 0.0
    osd_rotate: int | None = None
    osd_confidence: float | None = None

    @property
    def k(self) -> int:
        return (self.content_rotation // 90) % 4

    def as_dict(self) -> dict[str, object]:
        return {key: (round(v, 4) if isinstance(v, float) else v) for key, v in asdict(self).items()}


def rotate_image(img: np.ndarray, k: int) -> np.ndarray:
    """Rotate by ``k`` counter-clockwise quarter turns (contiguous copy)."""
    return np.ascontiguousarray(np.rot90(img, k % 4)) if k % 4 else img


def map_points_back(points: np.ndarray, k: int, width: int, height: int) -> np.ndarray:
    """Points on ``np.rot90(img, k)`` → points on ``img`` (``img`` is ``height`` × ``width`` px).

    Continuous pixel-edge coordinates: the rotated image of a W×H image is H×W (odd k).
    """
    p = np.asarray(points, dtype=np.float64)
    x, y = p[..., 0], p[..., 1]
    k %= 4
    if k == 0:
        out = np.stack([x, y], -1)
    elif k == 1:  # B = rot90(A) (CCW): B(x', y') = A(W - y', x')
        out = np.stack([width - y, x], -1)
    elif k == 2:
        out = np.stack([width - x, height - y], -1)
    else:  # k == 3 (CW): B(x', y') = A(y', H - x')
        out = np.stack([y, height - x], -1)
    return out.astype(np.float32)


def _thumbnail(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s >= 1.0:
        return img
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)


def _cap_width(crop: np.ndarray, max_ratio: float) -> np.ndarray:
    """Keep the first ``max_ratio`` × height pixels of a long crop (its reading direction is unchanged)."""
    h, w = crop.shape[:2]
    limit = int(max_ratio * h)
    return np.ascontiguousarray(crop[:, :limit]) if max_ratio > 0 and w > limit > 0 else crop


def detect_orientation(
    eng: OcrEngine, img: np.ndarray, cfg: OrientationConfig | None = None
) -> OrientationResult:
    cfg = cfg or OrientationConfig()
    small = _thumbnail(img, cfg.thumb_max_side)
    quads, _ = eng.det_small.detect(np.ascontiguousarray(small))
    if len(quads) < cfg.min_boxes:
        osd = _osd(small) if cfg.use_osd else None
        if osd is not None and osd[1] >= 2.0:
            return OrientationResult((360 - osd[0]) % 360, "osd", osd_rotate=osd[0], osd_confidence=osd[1])
        return OrientationResult(0, "no_text", n_vertical=0, n_horizontal=len(quads))
    dims = [quad_size(q) for q in quads]
    vert = [h / max(w, 1.0) >= 1.5 for w, h in dims]
    horiz = [w / max(h, 1.0) >= 1.5 for w, h in dims]
    nv, nh = sum(vert), sum(horiz)
    order = sorted(range(len(quads)), key=lambda i: -dims[i][0] * dims[i][1])

    def probe(mask: list[bool], always_flip: bool) -> tuple[float, float] | None:
        """Mean rec score of the largest boxes of one orientation, read as cropped and turned 180°.

        The turned reading is skipped when the direct one is already confident (upside-down text
        reads at ~0.45 on this recogniser), which halves the probe cost on ordinary pages.
        """
        pick = [i for i in order if mask[i]][: cfg.n_probe]
        if len(pick) < min(cfg.min_boxes, 2):
            return None
        # tall crops are turned 90° CCW; long lines are cut: the recogniser cost grows with the width
        crops = [_cap_width(rotate_crop(small, quads[i]), cfg.probe_max_ratio) for i in pick]
        s0 = float(np.mean([r.score for r in eng.rec(crops)]))
        if s0 >= cfg.confident_score and not always_flip:
            return s0, 0.0
        s1 = float(np.mean([r.score for r in eng.rec([np.ascontiguousarray(np.rot90(c, 2)) for c in crops])]))
        return s0, s1

    if nv > cfg.vertical_majority * nh:
        candidates = {"v": probe(vert, False)}
    elif nh > cfg.vertical_majority * nv:
        candidates = {"h": probe(horiz, False)}
    else:  # mixed geometry (plans, schemes): probe both orientations, the best reading wins
        candidates = {"h": probe(horiz, True), "v": probe(vert, True)}
    hyps: list[tuple[float, int, float, float]] = []  # (score, rotation, s_as_read, s_turned)
    for kind, sc in candidates.items():
        if sc is None:
            continue
        s0, s1 = sc
        if kind == "h":
            hyps.append((s0, 0, s0, s1))
            hyps.append((s1, 180, s0, s1))
        else:
            # A tall crop that reads upright after the CCW turn → content rotated 90° clockwise.
            hyps.append((s0, 90, s0, s1))
            hyps.append((s1, 270, s0, s1))
    if not hyps:
        return OrientationResult(0, "default", n_vertical=nv, n_horizontal=nh)
    hyps.sort(key=lambda h: -h[0])
    best = hyps[0]
    margin = best[0] - hyps[1][0] if len(hyps) > 1 else best[0]
    result = OrientationResult(best[1], "det_rec_probe", margin, nv, nh, round(best[2], 4), round(best[3], 4))
    if result.margin < cfg.tie_margin and cfg.use_osd:
        osd = _osd(small)
        if osd is not None:
            result.osd_rotate, result.osd_confidence = osd
            if osd[1] >= 1.0:
                result.content_rotation = (360 - osd[0]) % 360
                result.method = "osd"
    return result


_TESSERACT: str | bool | None = False


def tesseract_binary() -> str | None:
    global _TESSERACT
    if _TESSERACT is False:
        _TESSERACT = shutil.which("tesseract")
    return _TESSERACT  # type: ignore[return-value]


def _osd(img: np.ndarray) -> tuple[int, float] | None:
    """Tesseract OSD («Rotate: N» = clockwise turn that fixes the image). None when unavailable."""
    binary = tesseract_binary()
    if not binary:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="inspector_osd_") as tmp:
            path = Path(tmp) / "page.png"
            cv2.imwrite(str(path), img)
            proc = subprocess.run(
                [binary, str(path), "-", "--psm", "0", "-l", "osd"],
                capture_output=True,
                text=True,
                timeout=30,
                env={"OMP_THREAD_LIMIT": "1", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
            )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("orientation.osd_failed", extra={"error": str(exc)})
        return None
    out = proc.stdout + proc.stderr
    rot = re.search(r"Rotate:\s*(\d+)", out)
    conf = re.search(r"Orientation confidence:\s*([\d.]+)", out)
    if not rot:
        return None
    return int(rot.group(1)) % 360, float(conf.group(1)) if conf else 0.0
