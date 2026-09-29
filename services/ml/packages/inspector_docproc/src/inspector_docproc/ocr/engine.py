"""ONNX detector and recogniser (PP-OCRv6 det + PP-OCRv5 cyrillic rec) with RapidOCR-exact pre/post-processing.

Pre- and post-processing reproduce RapidOCR 3.9.2 (the measured pipeline of 96): detector input is
resized so that its short side is at least 736 px and rounded to multiples of 32, normalised to
[-1, 1], and decoded by DB post-processing (thresh 0.3, box 0.5, unclip 1.6, dilation); recognition
sorts crops by aspect ratio, batches 6 of them at height 48 with zero padding to the widest crop, and
decodes CTC greedily with the character list stored in the model metadata.

Execution differs only in where the numbers are computed: on CoreML the inputs are padded to a small
set of static canvases (1600² and 3200²) because CoreML is fast only with static shapes; the padding is
white, i.e. the page background the detector already sees. The recogniser runs on the CPU (measured
faster than CoreML for this model); its CoreML path with width buckets is kept for experiments.
On CUDA both models run on the GPU with dynamic shapes (no canvases: CUDA has no per-shape compile step).
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # Windows: no advisory locks; CoreML (the only user) is macOS-only
    fcntl = None  # type: ignore[assignment]

import cv2
import numpy as np

from inspector_docproc.config import OcrConfig
from inspector_docproc.models import (
    ROLE_DET_FALLBACK,
    ROLE_DET_PRIMARY,
    ROLE_REC_PRIMARY,
    ModelRegistry,
    ModelSpec,
    resolve_provider_mode,
)

log = logging.getLogger("inspector_docproc.ocr")

# CoreML detector canvases: two static shapes only. Every extra shape costs a compiled model per
# worker process (0.1–0.5 s to load plus a slow first run), and padding is nearly free on the GPU.
DET_CANVASES = ((1600, 1600), (3200, 3200))
REC_WIDTH_BUCKETS = (
    320,
    480,
    640,
    800,
    960,
    1120,
    1280,
    1440,
    1600,
    1920,
    2240,
    2560,
    3200,
    3840,
    4800,
    6400,
)


@contextmanager
def _file_lock(path: Path):
    """Serialise CoreML compilation of one shape across worker processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)


class _SessionPool:
    """Lazily created sessions of one model: one dynamic-shape session (CPU, or CUDA when ``mode`` is ``cuda``)
    + static CoreML sessions per shape."""

    def __init__(self, registry: ModelRegistry, spec: ModelSpec, mode: str, threads: int) -> None:
        self.registry = registry
        self.spec = spec
        self.mode = mode
        self.threads = threads
        self._cpu: Any = None
        self._static: dict[tuple[int, ...], Any] = {}
        self._lock = threading.Lock()
        self.calls: dict[str, int] = {"cpu": 0, "coreml": 0}

    def cpu(self) -> Any:
        """The dynamic-shape session: on the CPU, or on the GPU in ``cuda`` mode."""
        with self._lock:
            if self._cpu is None:
                dyn = "cuda" if self.mode == "cuda" else "cpu"
                self._cpu = self.registry.session(self.spec, mode=dyn, threads=self.threads)
            return self._cpu

    def static(self, dims: dict[int, int]) -> Any:
        key = tuple(sorted(dims.items()))
        with self._lock:
            sess = self._static.get(key)
            if sess is None:
                tag = "x".join(str(v) for _, v in key)
                lock = self.registry.cache_root / "coreml" / self.spec.sha256[:16] / f".{tag}.lock"
                with _file_lock(lock):
                    sess = self.registry.session(
                        self.spec, mode="coreml", threads=self.threads, static_dims=dims
                    )
                self._static[key] = sess
            return sess

    def close(self) -> None:
        """Release the sessions now (ORT joins their thread pools); a later call recreates them lazily."""
        with self._lock:
            self._cpu = None
            self._static.clear()

    def run_cpu(self, x: np.ndarray) -> np.ndarray:
        self.calls["cpu"] += 1
        sess = self.cpu()
        return sess.run(None, {sess.get_inputs()[0].name: x})[0]

    def run_static(self, x: np.ndarray, dims: dict[int, int]) -> np.ndarray:
        self.calls["coreml"] += 1
        sess = self.static(dims)
        return sess.run(None, {sess.get_inputs()[0].name: x})[0]


# ── Detection ────────────────────────────────────────────────────────────────────────────────


class Detector:
    """PP-OCRv6 DB text detector. ``detect(img_bgr)`` → (quads float32 [N,4,2] in image px, scores)."""

    def __init__(
        self,
        registry: ModelRegistry,
        spec: ModelSpec,
        mode: str,
        threads: int,
        cfg: OcrConfig,
        *,
        which: str = "small",
        remote: Any = None,
    ):
        from rapidocr.ch_ppocr_det.utils import DBPostProcess

        self.spec = spec
        self.cfg = cfg
        self.which = which
        self.remote = remote  # detection-server client (ocr.detserver) that runs the CoreML canvases
        self.pool = _SessionPool(registry, spec, mode, threads)
        self.post = DBPostProcess(
            thresh=cfg.det_thresh,
            box_thresh=cfg.det_box_thresh,
            max_candidates=cfg.det_max_candidates,
            unclip_ratio=cfg.det_unclip_ratio,
            score_mode="fast",
            use_dilation=True,
        )
        self.seconds = 0.0

    @property
    def name(self) -> str:
        return self.spec.stem

    def _resized_shape(self, h: int, w: int) -> tuple[int, int]:
        """RapidOCR DetPreProcess (limit_type=min, limit_side_len=736) then round to multiples of 32."""
        limit = self.cfg.det_min_side_px
        ratio = float(limit) / min(h, w) if min(h, w) < limit else 1.0
        rh = int(round(int(h * ratio) / 32) * 32)
        rw = int(round(int(w * ratio) / 32) * 32)
        return max(rh, 32), max(rw, 32)

    def detect(self, img: np.ndarray) -> tuple[np.ndarray, list[float]]:
        import time

        t0 = time.perf_counter()
        h, w = img.shape[:2]
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        rh, rw = self._resized_shape(h, w)
        resized = cv2.resize(img, (rw, rh)) if (rh, rw) != (h, w) else img
        x = (resized.astype(np.float32) * (1.0 / 255.0) - 0.5) / 0.5
        x = x.transpose(2, 0, 1)[np.newaxis]
        canvas_shape = next((c for c in DET_CANVASES if rh <= c[0] and rw <= c[1]), None)
        if self.pool.mode == "coreml" and canvas_shape is not None:
            ch, cw = canvas_shape
            canvas = np.ones((1, 3, ch, cw), dtype=np.float32)  # normalised white
            canvas[:, :, :rh, :rw] = x
            if self.remote is not None:
                pred = self.remote.run(self.which, canvas)[:, :, :rh, :rw]
            else:
                pred = self.pool.run_static(canvas, {0: 1, 2: ch, 3: cw})[:, :, :rh, :rw]
        else:
            pred = self.pool.run_cpu(np.ascontiguousarray(x))
        boxes, scores = self.post(pred, (h, w))
        self.seconds += time.perf_counter() - t0
        if len(boxes) == 0:
            return np.zeros((0, 4, 2), np.float32), []
        return np.asarray(boxes, dtype=np.float32), [float(s) for s in scores]


# ── Recognition ──────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RecResult:
    """One crop reading: text, RapidOCR score and per-character positions along the crop (0..1)."""

    text: str
    score: float
    char_pos: list[float] = field(default_factory=list)  # centre of each char as a fraction of width
    char_prob: list[float] = field(default_factory=list)
    step: float = 0.0  # width of one CTC step as a fraction of the crop width

    def words(self) -> list[tuple[str, float, float, float]]:
        """Whitespace-separated words with (start, end) fractions of the crop width and mean char prob."""
        out: list[tuple[str, float, float, float]] = []
        cur: list[int] = []

        def flush() -> None:
            if not cur:
                return
            a = self.char_pos[cur[0]] - self.step
            b = self.char_pos[cur[-1]] + self.step
            text = "".join(self.text[i] for i in cur)
            prob = float(np.mean([self.char_prob[i] for i in cur])) if self.char_prob else self.score
            out.append((text, max(0.0, a), min(1.0, b), prob))
            cur.clear()

        if len(self.char_pos) != len(self.text):  # defensive: no positions → one word per line
            return [(self.text.strip(), 0.0, 1.0, self.score)] if self.text.strip() else []
        for i, ch in enumerate(self.text):
            if ch.isspace():
                flush()
            else:
                cur.append(i)
        flush()
        return out


class Recognizer:
    """PP-OCRv5 cyrillic CTC recogniser with RapidOCR batching (sort by ratio, batch 6, height 48)."""

    def __init__(self, registry: ModelRegistry, spec: ModelSpec, mode: str, threads: int, cfg: OcrConfig):
        self.spec = spec
        self.cfg = cfg
        self.pool = _SessionPool(registry, spec, mode, threads)
        meta = self.pool.cpu().get_modelmeta().custom_metadata_map
        if "character" not in meta:
            from inspector_common.errors import InspectorError

            raise InspectorError("OCR_MODEL_MISSING", model=f"{spec.name} (character list)")
        chars = meta["character"].splitlines()
        self.characters = ["blank", *chars, " "]
        self.seconds = 0.0
        self.crops = 0

    @property
    def name(self) -> str:
        return self.spec.stem

    def plan_widths(self, shapes: Sequence[tuple[int, int]]) -> list[int]:
        """Padded input width of every crop (``shapes``: (h, w) each) under RapidOCR batching: crops sorted
        by aspect ratio, batches of ``rec_batch``, each batch zero-padded to its widest member and to at least
        320 px (ratio 320/48).

        A crop's reading depends on this width (the SVTR neck attends over the whole padded sequence) and on
        nothing else in its batch: the model is batch-invariant on the CPU provider (bit-identical logits for
        any batch size and position; ``tests/test_docproc_rec_batching.py``). Any subset of the crops read later
        with its planned widths therefore gets exactly the readings of the full batched call, which is what
        lets :func:`inspector_docproc.ocr.pipeline.recognize_crops` skip retries that cannot win.
        """
        hgt = self.cfg.rec_height
        base_ratio = 320 / 48
        ratios = [w / float(h) for h, w in shapes]
        order = np.argsort(np.array(ratios))
        widths = [0] * len(ratios)
        n = self.cfg.rec_batch
        for beg in range(0, len(ratios), n):
            idx = [int(i) for i in order[beg : beg + n]]
            img_w = int(hgt * max([base_ratio, *(ratios[i] for i in idx)]))
            for i in idx:
                widths[i] = img_w
        return widths

    def __call__(self, crops: list[np.ndarray], widths: Sequence[int] | None = None) -> list[RecResult]:
        """Read ``crops``; ``widths`` (from :meth:`plan_widths` of a larger set) pins each crop's padded width,
        default: the canonical batching of ``crops`` themselves."""
        import time

        if not crops:
            return []
        t0 = time.perf_counter()
        hgt = self.cfg.rec_height
        ratios = [c.shape[1] / float(c.shape[0]) for c in crops]
        if widths is None:
            widths = self.plan_widths([c.shape[:2] for c in crops])
        elif len(widths) != len(crops):
            raise ValueError(f"{len(widths)} widths for {len(crops)} crops")
        # Crops of one padded width in ratio order, then chunks of rec_batch: for the canonical plan these are
        # exactly the RapidOCR batches (widths never decrease along the sorted order).
        groups: dict[int, list[int]] = {}
        for i in np.argsort(np.array(ratios)):
            groups.setdefault(int(widths[int(i)]), []).append(int(i))
        out: list[RecResult | None] = [None] * len(crops)
        n = self.cfg.rec_batch
        for img_w, members in groups.items():
            for beg in range(0, len(members), n):
                idx = members[beg : beg + n]
                batch = np.zeros((len(idx), 3, hgt, img_w), dtype=np.float32)
                resized_w: list[int] = []
                for k, i in enumerate(idx):
                    crop = crops[i]
                    if crop.ndim == 2:
                        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
                    rw = min(img_w, math.ceil(hgt * ratios[i]))
                    rw = max(rw, 1)
                    resized = cv2.resize(crop, (rw, hgt)).astype(np.float32)
                    batch[k, :, :, :rw] = (resized.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
                    resized_w.append(rw)
                preds = self._run(batch)
                steps = preds.shape[1]
                px_per_step = img_w / float(steps)
                idx_arr = preds.argmax(axis=2)
                prob_arr = preds.max(axis=2)
                for k, i in enumerate(idx):
                    out[i] = self._decode(idx_arr[k], prob_arr[k], px_per_step, resized_w[k])
        self.seconds += time.perf_counter() - t0
        self.crops += len(crops)
        return [r if r is not None else RecResult("", 0.0) for r in out]

    def _run(self, batch: np.ndarray) -> np.ndarray:
        b, _, hgt, w = batch.shape
        if self.pool.mode == "coreml":
            bucket = next((bw for bw in REC_WIDTH_BUCKETS if bw >= w), None)
            if bucket is not None:
                n = self.cfg.rec_batch
                full = np.zeros((n, 3, hgt, bucket), dtype=np.float32)
                full[:b, :, :, :w] = batch
                return self.pool.run_static(full, {0: n, 3: bucket})[:b]
        return self.pool.run_cpu(batch)

    def _decode(self, idx: np.ndarray, prob: np.ndarray, px_per_step: float, resized_w: int) -> RecResult:
        sel = np.ones(len(idx), dtype=bool)
        sel[1:] = idx[1:] != idx[:-1]
        sel &= idx != 0
        cols = np.nonzero(sel)[0]
        if len(cols) == 0:
            return RecResult("", 0.0)
        text = "".join(self.characters[int(c)] for c in idx[cols])
        probs = [round(float(p), 5) for p in prob[cols]]
        score = float(np.round(np.mean(probs), 5))
        width = float(max(resized_w, 1))
        pos = [min(1.0, ((float(c) + 0.5) * px_per_step) / width) for c in cols]
        return RecResult(text, score, pos, probs, step=min(1.0, px_per_step / width))


def warm_plan(eng: OcrEngine, medium: bool) -> list[tuple[Detector, tuple[tuple[int, int], ...]]]:
    """Detector canvases used by the pipeline: small on both, medium (union pass) on the 1600² one."""
    plan = [(eng.det_small, DET_CANVASES)]
    if medium:
        plan.append((eng.detector("medium"), DET_CANVASES[:1]))
    return plan


# ── Engine ───────────────────────────────────────────────────────────────────────────────────


class OcrEngine:
    """Detector(s) + recogniser sharing one execution mode. Created once per worker process."""

    # Retry reads that cannot win are skipped (exact: :func:`inspector_docproc.ocr.pipeline._read_retries`).
    # A switch only for the identical-output tests and timing comparisons; it never changes PageTokens.
    skip_futile_retries: bool = True

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        *,
        cfg: OcrConfig | None = None,
        providers: str = "auto",
        threads: int = 1,
        remote: Any = None,
        strict_providers: bool = False,
    ) -> None:
        self.registry = registry or ModelRegistry()
        if strict_providers:
            self.registry.strict = True
        self.remote = remote
        self.cfg = cfg or OcrConfig()
        self.mode = resolve_provider_mode(providers, strict_providers)
        self.threads = threads
        self._det: dict[str, Detector] = {}
        # The recogniser runs on the CPU unless the mode is CUDA: with CoreML it is 3-10x slower on this model
        # (measured 0.27-1.3 s vs 0.05-0.15 s per batch of 6), while the detector is ~9x faster (0.11 s vs 1.0 s).
        # With CUDA both models run on the GPU (dynamic shapes).
        self.rec = Recognizer(
            self.registry,
            self.registry.by_role(ROLE_REC_PRIMARY),
            "cuda" if self.mode == "cuda" else "cpu",
            threads,
            self.cfg,
        )
        self.det_small = self.detector("small")
        log.info(
            "ocr.engine_ready",
            extra={
                "mode": self.mode,
                "threads": threads,
                "det": self.det_small.name,
                "rec": self.rec.name,
            },
        )

    def warmup(self, medium: bool = True) -> float:
        """Create (and on first use compile + cache on disk) the CoreML detector canvases; returns seconds."""
        import time

        t0 = time.perf_counter()
        if self.mode == "cuda":  # load cuDNN/cuBLAS and the first kernels before the first page
            for det, _ in warm_plan(self, medium):
                det.pool.run_cpu(np.ones((1, 3, 736, 736), dtype=np.float32))
            self.rec.pool.run_cpu(np.zeros((1, 3, self.cfg.rec_height, 320), dtype=np.float32))
            return time.perf_counter() - t0
        if self.mode != "coreml" or self.remote is not None:
            return 0.0
        for det, canvases in warm_plan(self, medium):
            for ch, cw in canvases:
                det.pool.run_static(np.ones((1, 3, ch, cw), dtype=np.float32), {0: 1, 2: ch, 3: cw})
        return time.perf_counter() - t0

    def detector(self, which: str = "small") -> Detector:
        if which not in self._det:
            role = {"small": ROLE_DET_PRIMARY, "medium": ROLE_DET_FALLBACK}[which]
            self._det[which] = Detector(
                self.registry, self.registry.by_role(role), self.mode, self.threads, self.cfg,
                which=which, remote=self.remote,
            )  # fmt: skip
        return self._det[which]

    def close(self) -> None:
        """Release every ONNX Runtime session of this engine (detectors and recogniser) deterministically,
        instead of leaving them to interpreter finalization. Idempotent; the engine stays usable (sessions are
        recreated lazily on the next call)."""
        for det in self._det.values():
            det.pool.close()
        self.rec.pool.close()

    def __enter__(self) -> OcrEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def provider_name(self) -> str:
        """Providers actually used: detector / recogniser."""
        det = {"coreml": "CoreMLExecutionProvider", "cuda": "CUDAExecutionProvider"}.get(
            self.mode, "CPUExecutionProvider"
        )
        rec = "CUDAExecutionProvider" if self.mode == "cuda" else "CPUExecutionProvider"
        return f"det={det},rec={rec}"

    def versions(self) -> dict[str, str]:
        out = {
            "det": self.det_small.name,
            "det_sha256": self.det_small.spec.sha256[:12],
            "rec": self.rec.name,
            "rec_sha256": self.rec.spec.sha256[:12],
            "provider": self.provider_name,
        }
        if "medium" in self._det:
            out["det_fallback"] = self._det["medium"].name
        return out

    def timings(self) -> dict[str, float]:
        out = {f"det_{k}_s": round(d.seconds, 3) for k, d in self._det.items()}
        out["rec_s"] = round(self.rec.seconds, 3)
        return out
