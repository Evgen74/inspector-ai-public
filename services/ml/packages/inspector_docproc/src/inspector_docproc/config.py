"""Recognition configuration (97 §2.13 F0–F5, 96 §4–§5 measured defaults).

One frozen dataclass holds every knob that changes recognition output. Its canonical JSON is part of
the pipeline version (see :mod:`inspector_docproc.version`), so a cached PageTokens file is reused only
by a run with the same configuration. Knobs that change speed but not output (workers, threads) live
in :class:`ExecutionConfig` and are not hashed.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from typing import Any, Literal

ProviderMode = Literal["auto", "cpu", "coreml", "cuda"]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw.strip().isdigit() and int(raw) > 0 else default


@dataclass(frozen=True, slots=True)
class OcrConfig:
    """OCR core v2 (96 §4, 97 §2.13 F3). Defaults reproduce the measured «v2 + PP-OCRv6-small» pipeline."""

    # Detection: fixed-size tiles with overlap and seam merge (96 §4.9: keep the tile size fixed).
    det_tile_px: int = 3200
    det_overlap_px: int = 400
    blank_tile_level: int = 245  # a tile whose darkest pixel is lighter than this is skipped
    det_thresh: float = 0.3
    det_box_thresh: float = 0.5
    det_unclip_ratio: float = 1.6
    det_max_candidates: int = 1000
    det_min_side_px: int = 736  # small inputs are padded (white) up to this side, never upscaled
    # Recognition: PP-OCRv5 cyrillic, batches of 6, no text-line classifier (96 §4.2).
    rec_batch: int = 6
    rec_height: int = 48
    vertical_ratio: float = 1.5  # h/w of a crop at or above which the cropper rotates it (RapidOCR rule)
    retry_180_below: float = 0.75  # 180° re-read for vertical crops and lines below this score
    retry_gain: float = 0.02  # a retry replaces the reading only when it beats it by this margin
    short_vertical_max_ratio: float = 3.2  # «short vertical» crops also get the un-rotated reading
    chunk_ratio: float = 24.0  # very long crops (w > chunk_ratio·h) with a weak score are split
    chunk_below: float = 0.85
    chunk_gain: float = 0.03
    redetect_below: float = 0.85  # local re-detection of long, low-score lines (96 §4.5)
    redetect_min_ratio: float = 12.0
    redetect_gain: float = 0.05
    # Line acceptance and quality flags (97 §2.13: OK ≥ 0.85 / LOW_QUALITY ≥ 0.6 / ABSTAIN).
    min_line_score: float = 0.5  # lines below are dropped from PageTokens (bench: «not returned»)
    quality_ok: float = 0.85
    quality_low: float = 0.6
    # Second detector (96 §4.8): v6-medium. «union» (default) runs v6-medium once on the page scaled to
    # ``union_max_side`` and adds the boxes that no small box covers (large lines next to seals that
    # v6-small misses, e.g. the B06 title); added lines need ``union_min_score`` (seal-ring text reads
    # at 0.6–0.86). «fallback» re-reads a page with v6-medium when its mean line score is low (the 96
    # proposal); «off» is the 96 baseline pipeline.
    medium_mode: Literal["union", "fallback", "off"] = "union"
    union_covered_share: float = 0.5  # a medium box is new when small boxes cover less than this share
    union_max_side: int = 1600  # one static 1600² canvas: ~0.09 s on the GPU, ~2 GB less wired memory
    union_min_score: float = 0.9
    medium_fallback_below: float = 0.9  # «fallback»: mean accepted line score of the page
    medium_fallback_min_lines: int = 5


@dataclass(frozen=True, slots=True)
class OrientationConfig:
    """Page-content orientation detector (96 §4.3): det geometry + rec-score probe, OSD tie-break."""

    thumb_max_side: int = 1600
    n_probe: int = 12
    vertical_majority: float = 1.5  # vertical boxes must outnumber horizontal ones by this factor
    min_boxes: int = 3
    tie_margin: float = 0.03  # best − runner-up probe score below this → ambiguous → OSD tie-break
    confident_score: float = 0.85  # a direct probe reading this good skips the 180° re-read
    probe_max_ratio: float = 12.0  # probe crops are cut to this width/height (~15 characters is enough)
    use_osd: bool = True  # Tesseract OSD (system binary with osd.traineddata), only when ambiguous


@dataclass(frozen=True, slots=True)
class RenderConfig:
    """Render policy (96 §5, 97 §2.16): native DPI for scans, 200 dpi for vector outlines, no upsampling."""

    scan_dpi_min: int = 150
    scan_dpi_max: int = 300
    vector_dpi: int = 200
    fallback_dpi: int = 300  # image pages whose native resolution cannot be measured
    dominant_image_share: float = 0.5  # an image covering at least this share of the page is «dominant»
    max_megapixels: float = 80.0  # render cap (RENDER_CAPPED); an A0 sheet at 200 dpi is ~62 MP


@dataclass(frozen=True, slots=True)
class RouterConfig:
    """Page classification and word-level coverage routing (97 §2.13 F0–F2, 95 R1/R11)."""

    min_visible_chars: int = 50  # a text layer with fewer visible characters is not a text layer
    outlined_stream_bytes: int = 60_000  # large content stream + no text → text drawn as curves
    stamp_max_chars: int = 20  # «КОПИЯ ВЕРНА» separators: page-number stamp only
    stamp_max_image_share: float = 0.1
    stamp_max_drawings: int = 10
    empty_max_chars: int = 3
    raster_insert_share: float = 0.05  # embedded rasters above this share of the page are OCR'd
    coverage_min_side_mm: float = 400.0  # sheets ≥ A3 (long side) get the det coverage check
    covered_share: float = 0.5  # a det box is covered when this share of its area lies under words
    # Layer-isolated OCR (97 §2.13 F2, 95 R2): vector sheets with CAD layers are also read on a render
    # with only text-like layers visible; its lines replace weaker full-render readings or add new ones.
    layer_isolation: bool = True
    text_layer_pattern: str = (
        r"(-TEXT$|Выноск|Текст|Text|Подпис|Надпис|Воздухообмен|Маркировк|Теплопотер|Нагрузк)"
    )
    isolation_min_ink_drop: float = 0.05  # the text-only render must hide at least this share of ink
    isolation_skip_score: float = 0.95  # boxes that match a full-render line this good are not re-read
    isolation_prefer_margin: float = 0.02  # the isolated reading wins unless the full one is better by this
    isolation_min_len_ratio: float = 0.8  # …and it must not be much shorter (text cut by hidden layers)
    # Text-layer quality (96 §4.10, 95 R1).
    mojibake_ratio: float = 0.12
    min_cyrillic_share: float = 0.35
    lexicon_hit_ok: float = 0.8
    mixed_script_max: float = 0.05
    min_words_for_quality: int = 8
    # Garbled-layer repair acceptance (97 §2.16: repair first, OCR if it fails).
    repair_min_hit: float = 0.75
    repair_min_gain: float = 0.2
    repair_min_words: int = 3  # lexicon-checkable words a font needs to validate its own shift
    # OCR probe of a suspicious text layer: the recogniser reads the boxes of up to ``probe_words`` layer
    # words; mean similarity ≥ ``probe_accept`` confirms the layer (a garble verdict is overturned: SCAD
    # printouts full of «[T=2.15 / f=0.46Hz]»), below it rejects the layer (a lucky repair offset).
    layer_probe: bool = True
    probe_words: int = 24
    probe_min_words: int = 4
    probe_accept: float = 0.75  # train: garbled layers ≤ 0.59, correct/repaired layers ≥ 0.85
    probe_max_garbled_share: float = 0.15  # a verdict is overturned only if garbled words are a minority
    probe_dpi: int = 150


@dataclass(frozen=True, slots=True)
class ZoneConfig:
    """Seal, stamp, QR and handwriting zones (R-10, :mod:`inspector_docproc.zones`); tuned on the GT v2 zones."""

    enabled: bool = True
    work_dpi: int = 100  # analysis resolution of the colour-ink mask (max-pooled from the render)
    # blue/violet ink in OpenCV HSV (hue 0–180): seals, ballpoint/gel pens, blue CAD signatures
    ink_hue_min: int = 95
    ink_hue_max: int = 140
    ink_sat_min: int = 45
    ink_blue_over_red: int = 25  # B − R: rejects grey and colour-cast print
    dark_level: int = 110  # grey level below which non-colour pixels count as black ink
    seal_diameter_min_mm: float = 25.0  # official seals are 38–45 mm; small company stamps ≥ 25 mm
    seal_diameter_max_mm: float = 60.0
    seal_hough_votes: int = 30
    seal_max_candidates: int = 40  # strongest Hough circles verified per page
    seal_ring_coverage: float = 0.85  # share of 72 sectors of the thin outer border band with ink
    # Hough locks onto the inner ring of a double-ring seal (measured: 0.73–0.89 of the GT radius); the seal
    # extends outward while 0.5 mm bands stay inked in at least this share of sectors (text band, outer ring)
    seal_outer_coverage: float = 0.75
    seal_oval_min_mm: float = (
        12.0  # colour clusters at least this big on both sides are tested for an oval ring
    )
    line_min_mm: float = (
        8.0  # straight ink segments at least this long are frames/rules/pipes, not handwriting
    )
    stamp_min_mm: float = 20.0
    stamp_max_mm: float = 150.0
    stamp_edge_coverage: float = 0.7
    handwriting_join_mm: float = 1.5  # strokes closer than this form one cluster
    handwriting_min_ink_mm2: float = 4.0
    handwriting_min_mm: float = 5.0  # long side of a cluster
    handwriting_min_short_mm: float = 1.5
    handwriting_max_mm: float = 150.0
    handwriting_max_line_share: float = (
        0.85  # clusters whose ink is almost all straight segments are line work
    )
    # Colour fringes of black print on colour scans (chromatic aberration at table rulings): the colour
    # pixels of such a cluster lie next to black ink (measured 0.82–1.00; pen strokes ≤ 0.39)
    handwriting_max_fringe: float = 0.6
    handwriting_max_stroke_mm: float = (
        0.8  # pen strokes 0.25–0.6 mm; filled logos and bold graphics are wider
    )
    handwriting_text_max_fill: float = 0.15  # small clusters (< signature_min_mm) denser than this are logos
    printed_min_score: float = (
        0.75  # OCR lines at least this confident are printed text (kept out of handwriting)
    )
    signature_min_mm: float = 10.0  # handwriting clusters at least this long are signatures
    # Vector sheets ≥ A2: signatures live in the title block (ГОСТ Р 21.101 main inscription, bottom right);
    # colour line work elsewhere on a drawing (pipes, valves, revision clouds) is not handwriting.
    sheet_min_long_side_mm: float = 500.0
    title_block_window_mm: tuple[float, float] = (200.0, 65.0)
    handwritten_token_colour_share: float = 0.5  # OCR token in a handwriting zone whose ink is ≥ this colour
    handwritten_token_max_conf: float = 0.85  # …and read below this confidence (a confident token is printed)
    qr: bool = True
    qr_min_mm: float = 8.0
    qr_max_mm: float = 70.0
    qr_render_dpi: int = 300  # the render QR detector works at ≤ this dpi (dense codes need ≥ 3 px/module)


@dataclass(frozen=True, slots=True)
class PostConfig:
    """F5 post-correction (96 §7.2)."""

    code_corrector: bool = True
    homoglyph_fold: bool = (
        True  # mixed-script OCR tokens: Latin look-alikes → Cyrillic (codefix.fold_mixed_script)
    )
    # M1 (GT v2 conventions, codefix «line/page script context»): homoglyph words take the script of their
    # line/page, italic Cyrillic read as Latin is transliterated when the result is a lexicon word
    script_context: bool = True
    diameter_sign: bool = True  # «φ15», «ф16х2,2» → «Ø15», «Ø16х2,2»


@dataclass(frozen=True, slots=True)
class RecognitionConfig:
    ocr: OcrConfig = field(default_factory=OcrConfig)
    orientation: OrientationConfig = field(default_factory=OrientationConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    post: PostConfig = field(default_factory=PostConfig)
    zones: ZoneConfig = field(default_factory=ZoneConfig)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def replace(self, **sections: Any) -> RecognitionConfig:
        """``cfg.replace(ocr={"medium_mode": "off"})`` → a new config with overridden fields."""
        updates: dict[str, Any] = {}
        for name, values in sections.items():
            current = getattr(self, name)
            updates[name] = dataclasses.replace(current, **values) if isinstance(values, dict) else values
        return dataclasses.replace(self, **updates)


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """How recognition runs (does not change its output beyond provider numerics)."""

    providers: ProviderMode = "auto"
    # Frozen runs (``--hidden-run``, ``--strict-providers``): the provider must be named (cpu | coreml | cuda), is
    # never replaced by a fallback (models.resolve_provider_mode, ModelRegistry.strict).
    strict_providers: bool = False
    threads: int = 1  # ONNX Runtime intra-op threads per process
    workers: int = 0  # process pool size; 0 = cpu_count - 2
    keep_awake: bool = True  # hold a «no idle sleep» assertion while a batch runs (runner.keep_awake)
    # CUDA mode: every worker process owns a CUDA context and three sessions (~0.5-1.5 GB of VRAM), and the
    # GPU serialises their kernels anyway, so more processes only help the CPU-side work (render, pre/post).
    # The pool is capped here (also for an explicit --workers); INSPECTOR_CUDA_MAX_WORKERS overrides.
    max_gpu_workers: int = field(default_factory=lambda: _env_int("INSPECTOR_CUDA_MAX_WORKERS", 4))
    # Supervision of worker processes (runner): a page running longer than this is killed and reported as
    # PROCESSING_TIMEOUT (the slowest measured page, an A4 scan at 1 thread under load, took 37 s); a page
    # whose worker dies is retried in a fresh worker up to ``max_page_attempts`` times (WORKER_CRASHED).
    page_timeout_s: float = 900.0
    max_page_attempts: int = 2
    max_server_restarts: int = 3  # CoreML detection server rebuilds before the remaining pages fail
    worker_start_timeout_s: float = 600.0
    warmup: bool = True  # load (and on first use compile) the models before the first page

    def resolved_workers(self, mode: str | None = None) -> int:
        """Process pool size; ``mode`` is the resolved provider mode (``cuda`` caps the pool, see above)."""
        n = self.workers if self.workers > 0 else max(1, (os.cpu_count() or 2) - 2)
        if mode == "cuda":
            n = min(n, max(1, self.max_gpu_workers))
        return n


DEFAULT_CONFIG = RecognitionConfig()
