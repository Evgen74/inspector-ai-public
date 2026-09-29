"""Page recognition (97 §2.13 F0–F5): route → text layer → OCR (full or uncovered boxes) → merge → post-fix.

``PageRecognizer.recognize_page`` returns one PageTokens document (packages/contracts/schemas/
page_tokens.schema.json): word tokens and lines from the text layer and from OCR with provenance,
normalized bboxes/polygons of the displayed page, confidences and quality flags.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from inspector_common.geometry import normalize_rotation
from inspector_docproc.codefix import page_script, post_correct_line
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.layers import document_ocgs, layer_plan, page_layer_names, text_layers_only
from inspector_docproc.lexicon import Lexicon, load_lexicon, load_wordfreq
from inspector_docproc.models import (
    ROLE_DET_FALLBACK,
    ROLE_DET_PRIMARY,
    ROLE_REC_PRIMARY,
    ModelRegistry,
    resolve_provider_mode,
)
from inspector_docproc.ocr.engine import OcrEngine
from inspector_docproc.ocr.pipeline import OcrLine, OcrStats, detect_tiled, ocr_image
from inspector_docproc.orientation import OrientationResult, detect_orientation, map_points_back, rotate_image
from inspector_docproc.render import capped_dpi, choose_dpi, norm_bbox_from_points, norm_polygon, render_page
from inspector_docproc.router import PageFacts, RoutePlan, route
from inspector_docproc.textlayer import TextWord, extract_text_layer
from inspector_docproc.textnorm import similarity
from inspector_docproc.version import pipeline_version
from inspector_docproc.zones import Zone, assign_tokens, detect_zones, qr_from_images

LOW_DPI_BELOW = 150
OCR_SOURCES = frozenset({"OCR", "OCR_LAYER_ISOLATED"})  # contract TextSource values produced by OCR


def quality_flag(conf: float, ok: float, low: float) -> str:
    if conf >= ok:
        return "OK"
    if conf >= low:
        return "LOW_QUALITY"
    return "ABSTAIN"


def expected_chars(lines: list[OcrLine], min_score: float) -> float:
    """Σ score × length over accepted lines: the fallback-detector selection objective."""
    return float(sum(line.score * len(line.text.strip()) for line in lines if line.score >= min_score))


def coverage_of(boxes: np.ndarray, cover: np.ndarray) -> np.ndarray:
    """Share of each box (N×4 normalized) covered by the union-free sum of ``cover`` boxes (M×4)."""
    if len(boxes) == 0:
        return np.zeros(0)
    if len(cover) == 0:
        return np.zeros(len(boxes))
    bx0, by0, bx1, by1 = (boxes[:, i : i + 1] for i in range(4))
    cx0, cy0, cx1, cy1 = (cover[:, i][None, :] for i in range(4))
    iw = np.clip(np.minimum(bx1, cx1) - np.maximum(bx0, cx0), 0, None)
    ih = np.clip(np.minimum(by1, cy1) - np.maximum(by0, cy0), 0, None)
    inter = (iw * ih).sum(axis=1)
    area = np.maximum((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]), 1e-12)
    return np.minimum(inter / area, 1.0)


def _aabb(quads: list[np.ndarray]) -> np.ndarray:
    if not quads:
        return np.zeros((0, 4))
    return np.array(
        [[q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()] for q in quads], dtype=float
    )


def _overlap_matrix(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """IoU and intersection-over-smaller-area between two sets of boxes (N×4, M×4)."""
    if len(a) == 0 or len(b) == 0:
        z = np.zeros((len(a), len(b)))
        return z, z
    iw = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    ih = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    inter = iw * ih
    area_a = np.maximum((a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]), 1e-9)
    area_b = np.maximum((b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1]), 1e-9)
    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-9), inter / np.minimum(area_a[:, None], area_b[None, :])


def ink_count(img: np.ndarray, step: int = 4) -> int:
    """Dark pixels on a subsampled grid: cheap measure of how much a layer toggle hid."""
    sub = img[::step, ::step]
    gray = sub.min(axis=2) if sub.ndim == 3 else sub
    return int((gray < 160).sum())


def merge_isolated(
    base: list[OcrLine],
    iso: list[OcrLine],
    *,
    min_score: float,
    prefer_margin: float,
    min_len_ratio: float,
) -> tuple[list[OcrLine], int, int]:
    """Merge readings of the layer-isolated render into the full-render lines.

    An isolated line that overlaps no full-render line is added. One that overlaps full-render lines
    (IoU ≥ 0.3 or ≥ 60 % of the smaller box) replaces them when its score is within ``prefer_margin``
    of theirs and its text is not much shorter (a hidden layer may have cut the label). Returns
    (lines, n_added, n_replaced).
    """
    good = [ln for ln in iso if ln.score >= min_score and ln.text.strip()]
    if not good:
        return base, 0, 0
    iou, ios = _overlap_matrix(_aabb([ln.quad for ln in good]), _aabb([ln.quad for ln in base]))
    drop: set[int] = set()
    added = replaced = 0
    out_new: list[OcrLine] = []
    for i, ln in enumerate(good):
        hits = [j for j in range(len(base)) if iou[i, j] >= 0.3 or ios[i, j] >= 0.6] if len(base) else []
        if not hits:
            out_new.append(ln)
            added += 1
            continue
        best = max(base[j].score if base[j].text.strip() else 0.0 for j in hits)
        base_len = sum(len(base[j].text.strip()) for j in hits)
        if ln.score >= best - prefer_margin and len(ln.text.strip()) >= min_len_ratio * base_len:
            drop.update(hits)
            out_new.append(ln)
            replaced += 1
    kept = [ln for j, ln in enumerate(base) if j not in drop]
    return kept + out_new, added, replaced


def ocr_with_fallback(eng: OcrEngine, img: np.ndarray, ocfg) -> tuple[list[OcrLine], dict[str, Any]]:
    """OCR v2 with the v6-small detector plus the configured use of v6-medium (``ocfg.medium_mode``).

    - ``union``: medium boxes that small boxes do not cover are recognised and added (96 §4.8 refined:
      lines next to seals that v6-small misses).
    - ``fallback``: pages whose mean accepted line score is below ``medium_fallback_below`` are re-read
      with v6-medium; the reading with more expected correct characters (Σ score × length) wins.
    """
    lines, stats = ocr_image(eng, img, ocfg)
    info: dict[str, Any] = {"fallback_tried": False, "fallback_used": False, "stats": stats, "union_added": 0}
    if ocfg.medium_mode == "union":
        t0 = time.perf_counter()
        h, w = img.shape[:2]
        scale = min(1.0, ocfg.union_max_side / max(h, w))
        low = (
            cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
            if scale < 1
            else img
        )
        medium_quads, _ = eng.detector("medium").detect(np.ascontiguousarray(low))
        medium_quads = [q / scale for q in medium_quads]
        share = coverage_of(_aabb(medium_quads), _aabb([ln.quad for ln in lines]))
        extra = [q for q, c in zip(medium_quads, share, strict=True) if c < ocfg.union_covered_share]
        stats.det_s += time.perf_counter() - t0
        info["fallback_tried"] = True
        if extra:
            more, st2 = ocr_image(eng, img, ocfg, quads=extra)
            stats.rec_s += st2.rec_s
            more = [ln for ln in more if ln.score >= ocfg.union_min_score]
            stats.n_boxes += len(more)
            lines = lines + more
            info["union_added"] = len(more)
            info["fallback_used"] = bool(more)
        return lines, info
    accepted = [ln for ln in lines if ln.score >= ocfg.min_line_score]
    if ocfg.medium_mode == "fallback" and len(accepted) >= ocfg.medium_fallback_min_lines:
        mean = float(np.mean([ln.score for ln in accepted]))
        if mean < ocfg.medium_fallback_below:
            info["fallback_tried"] = True
            lines_m, stats_m = ocr_image(eng, img, ocfg, detector="medium")
            if expected_chars(lines_m, ocfg.min_line_score) > expected_chars(lines, ocfg.min_line_score):
                stats_m.det_s += stats.det_s
                stats_m.rec_s += stats.rec_s
                lines, info["stats"], info["fallback_used"] = lines_m, stats_m, True
            else:
                stats.det_s += stats_m.det_s
                stats.rec_s += stats_m.rec_s
    return lines, info


@dataclass(slots=True)
class _OcrOutcome:
    lines: list[OcrLine]
    width: int
    height: int
    dpi: int
    orientation: OrientationResult | None
    stats: OcrStats
    boxes_detected: int = 0
    boxes_covered: int = 0
    fallback_used: bool = False
    fallback_tried: bool = False
    union_added: int = 0
    t_render: float = 0.0
    t_orient: float = 0.0
    iso: dict[str, Any] | None = None  # layer-isolated pass: tried/added/replaced/boxes/layers
    t_iso: float = 0.0
    zones: list[Zone] | None = None  # seal/stamp/QR/handwriting zones found on the render (R-10)
    zone_masks: tuple[np.ndarray, np.ndarray] | None = None  # colour / black ink at the zone work dpi
    t_zones: float = 0.0
    regions: int = 0  # «ocr_images»: image regions read


class PageRecognizer:
    """Recognises pages of one process; the OCR engine is created lazily on the first OCR page."""

    def __init__(
        self,
        cfg: RecognitionConfig | None = None,
        exec_cfg: ExecutionConfig | None = None,
        *,
        engine: OcrEngine | None = None,
        lexicon: Lexicon | None = None,
        code_extras: frozenset[str] = frozenset(),
    ) -> None:
        self.cfg = cfg or RecognitionConfig()
        self.code_extras = code_extras  # abbreviations from the object's own file names (codefix rule 3)
        self.exec_cfg = exec_cfg or ExecutionConfig()
        self._engine = engine
        self._owns_engine = engine is None  # an engine passed in belongs to the caller (close() leaves it)
        self.lexicon = lexicon or load_lexicon()
        self._pipeline_version: str | None = None
        self._ocg_cache: tuple[int, str, dict[int, dict]] | None = None  # (id(doc), doc.name, ocgs)

    def _doc_ocgs(self, doc) -> dict[int, dict]:
        """OCGs of the current document, computed once per open document (~45 ms on a 3,000-OCG file)."""
        key = (id(doc), str(getattr(doc, "name", "")))
        if self._ocg_cache is None or self._ocg_cache[:2] != key:
            self._ocg_cache = (*key, document_ocgs(doc))
        return self._ocg_cache[2]

    @property
    def engine(self) -> OcrEngine:
        if self._engine is None:
            self._engine = OcrEngine(
                cfg=self.cfg.ocr,
                providers=self.exec_cfg.providers,
                threads=self.exec_cfg.threads,
                strict_providers=self.exec_cfg.strict_providers,
            )
        return self._engine

    def close(self) -> None:
        """Release the ONNX Runtime sessions of the engine this recognizer created (idempotent)."""
        if self._engine is not None and self._owns_engine:
            self._engine.close()
            self._engine = None

    def __enter__(self) -> PageRecognizer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def engine_mode(self) -> str:
        """Resolved execution mode (``coreml`` or ``cpu``) without loading any model."""
        if self._engine is not None:
            return self._engine.mode
        return resolve_provider_mode(self.exec_cfg.providers, self.exec_cfg.strict_providers)

    def pipeline_version(self) -> str:
        """Same for every page of a run (no model session needed): config + model sha256 + provider."""
        if self._pipeline_version is None:
            registry = self._engine.registry if self._engine is not None else ModelRegistry()
            shas = {
                "det": registry.by_role(ROLE_DET_PRIMARY).sha256,
                "det_fallback": registry.by_role(ROLE_DET_FALLBACK).sha256,
                "rec": registry.by_role(ROLE_REC_PRIMARY).sha256,
            }
            self._pipeline_version = pipeline_version(self.cfg, shas, self.engine_mode())
        return self._pipeline_version

    # ── OCR paths ───────────────────────────────────────────────────────────────────────────────
    def _render(self, page, plan: RoutePlan, facts: PageFacts, warnings: list[str]) -> tuple[np.ndarray, int]:
        dpi = choose_dpi(plan.render_kind, facts.images.native_dpi, self.cfg.render)
        dpi, capped = capped_dpi(page, dpi, self.cfg.render)
        if capped:
            warnings.append("RENDER_CAPPED")
        return render_page(page, dpi), dpi

    def _isolated_pass(
        self,
        page,
        dpi: int,
        base_ink: int,
        base_lines: list[OcrLine],
        cover: np.ndarray,
        stats: OcrStats,
        page_layers: list[str] | None = None,
    ) -> tuple[list[OcrLine], dict[str, Any] | None]:
        """F2 on the layer-isolated render (97 §2.13, 95 R2): read labels without the drawing underneath.

        Runs only on vector pages whose document has text-like CAD layers and whose text-only render
        hides at least ``isolation_min_ink_drop`` of the ink. Boxes covered by the text layer, or matching
        a confident full-render line, are not re-read. Returns the merged lines and the pass report.
        """
        rcfg, ocfg = self.cfg.router, self.cfg.ocr
        if not rcfg.layer_isolation:
            return base_lines, None
        doc = page.parent
        if not self._doc_ocgs(doc):
            return base_lines, None
        plan = layer_plan(doc, rcfg.text_layer_pattern)
        if not plan.usable:
            return base_lines, None
        if page_layers and not set(page_layers) & set(plan.text_layers):
            return base_lines, None  # the page draws nothing on a text-like layer
        with text_layers_only(doc, plan):
            iso_img = render_page(page, dpi)
        iso_ink = ink_count(iso_img)
        info: dict[str, Any] = {"tried": False, "ink_share": round(iso_ink / max(base_ink, 1), 4)}
        if iso_ink >= base_ink * (1.0 - rcfg.isolation_min_ink_drop) or iso_ink == 0:
            return base_lines, info  # the toggle hid nothing on this page (or everything)
        info["tried"] = True
        h, w = iso_img.shape[:2]
        t0 = time.perf_counter()
        quads = detect_tiled(self.engine.det_small, iso_img, ocfg)
        stats.det_s += time.perf_counter() - t0
        boxes = _aabb(quads) / np.array([w, h, w, h], dtype=float) if quads else np.zeros((0, 4))
        keep = coverage_of(boxes, cover) < rcfg.covered_share
        confident = [ln for ln in base_lines if ln.score >= rcfg.isolation_skip_score]
        if confident and len(quads):
            iou, _ = _overlap_matrix(_aabb(quads), _aabb([ln.quad for ln in confident]))
            keep &= iou.max(axis=1) < 0.5
        todo = [q for q, k in zip(quads, keep, strict=True) if k]
        info.update(boxes=len(quads), reread=len(todo), added=0, replaced=0)
        if not todo:
            return base_lines, info
        t1 = time.perf_counter()
        iso_lines, _ = ocr_image(self.engine, iso_img, ocfg, quads=todo)
        stats.rec_s += time.perf_counter() - t1
        for ln in iso_lines:
            ln.source = "OCR_LAYER_ISOLATED"
        merged, added, replaced = merge_isolated(
            base_lines,
            iso_lines,
            min_score=ocfg.min_line_score,
            prefer_margin=rcfg.isolation_prefer_margin,
            min_len_ratio=rcfg.isolation_min_len_ratio,
        )
        info.update(added=added, replaced=replaced)
        return merged, info

    def _probe_layer(self, page, words: list[TextWord]) -> dict[str, Any] | None:
        """Read the boxes of the longest text-layer words with the recogniser only and compare.

        Returns ``{"words": n, "agreement": mean similarity weighted by length}`` or None when the page
        has fewer than ``probe_min_words`` usable words. No detection runs: this costs one render at
        ``probe_dpi`` and one recognition batch.
        """
        rcfg = self.cfg.router
        cand = [w for w in words if len("".join(w.text.split())) >= 3]
        cand.sort(key=lambda w: -len(w.text))
        cand = cand[: rcfg.probe_words]
        if len(cand) < rcfg.probe_min_words:
            return None
        dpi, _ = capped_dpi(page, rcfg.probe_dpi, self.cfg.render)
        img = render_page(page, dpi)
        h, w = img.shape[:2]
        crops: list[np.ndarray] = []
        texts: list[str] = []
        for wd in cand:
            x0, y0, x1, y1 = wd.bbox[0] * w, wd.bbox[1] * h, wd.bbox[2] * w, wd.bbox[3] * h
            pad = 0.2 * max(1.0, min(x1 - x0, y1 - y0))
            crop = img[
                int(max(0, y0 - pad)) : int(min(h, y1 + pad + 1)),
                int(max(0, x0 - pad)) : int(min(w, x1 + pad + 1)),
            ]
            if crop.size == 0 or min(crop.shape[:2]) < 4:
                continue
            k = (wd.angle // 90) % 4  # reading direction clockwise → k CCW quarter turns make it upright
            crops.append(np.ascontiguousarray(np.rot90(crop, k)) if k else crop)
            texts.append(wd.text)
        if len(crops) < rcfg.probe_min_words:
            return None
        t0 = time.perf_counter()
        reads = self.engine.rec(crops)
        weights = [len(t) for t in texts]
        sims = [similarity(t, r.text) for t, r in zip(texts, reads, strict=True)]
        agreement = sum(s * n for s, n in zip(sims, weights, strict=True)) / max(sum(weights), 1)
        return {
            "words": len(crops),
            "agreement": round(float(agreement), 4),
            "dpi": dpi,
            "rec_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    def _verify_garble_verdict(
        self, page, layer, facts: PageFacts, plan: RoutePlan
    ) -> tuple[RoutePlan, dict[str, Any] | None]:
        """OCR arbitration of a BROKEN_ENCODING verdict (see :class:`RouterConfig` ``layer_probe``).

        - Unrepairable verdict, but the layer reads like the page → the layer is trusted (the statistics
          were fooled by symbol-heavy technical text). Garbled leftovers are read by coverage OCR.
        - Repaired layer that does not read like the page → the repair is rejected, full OCR.
        """
        rcfg = self.cfg.router
        if not rcfg.layer_probe or plan.page_class != "BROKEN_ENCODING":
            return plan, None
        visible = layer.visible_words
        if plan.action == "ocr_full":
            total = sum(len(w.text) for w in visible)
            garbled = sum(len(w.text) for w in visible if w.garbled)
            if garbled > rcfg.probe_max_garbled_share * max(total, 1):
                return plan, None  # the clean words would not represent the page
            probe = self._probe_layer(page, [w for w in visible if not w.garbled])
            if probe is None or probe["agreement"] < rcfg.probe_accept:
                return plan, probe
            repaired = any(w.repaired for w in visible)
            leftovers = any(w.garbled for w in visible)
            large = max(facts.width_mm, facts.height_mm) >= rcfg.coverage_min_side_mm
            action = "text+coverage" if (large or leftovers) else "text"
            new = RoutePlan(
                "BROKEN_ENCODING" if repaired else "VECTOR",
                action,  # type: ignore[arg-type]
                "vector",
                repaired=repaired,
                reason="layer_verified_by_ocr",
            )
            return new, probe
        if plan.repaired:
            probe = self._probe_layer(page, [w for w in visible if w.repaired])
            if probe is not None and probe["agreement"] < rcfg.probe_accept:
                new = RoutePlan(
                    "BROKEN_ENCODING", "ocr_full", "vector", False, trusted_text=False,
                    reason="repair_rejected_by_ocr",
                )  # fmt: skip
                return new, probe
            return plan, probe
        return plan, None

    def _zones_on_render(
        self,
        outcome: _OcrOutcome,
        img: np.ndarray,
        printed_px: list[list[float]],
        image_qr: list[Zone],
        vector_sheet: bool = False,
    ) -> None:
        """Zones (R-10) of the full-page render ``img``: printed text = confident OCR lines + ``printed_px``."""
        zcfg = self.cfg.zones
        if not zcfg.enabled:
            return
        t0 = time.perf_counter()
        boxes = list(printed_px)
        for ln in outcome.lines:
            if ln.score >= zcfg.printed_min_score and len(ln.text.strip()) >= 2:
                boxes.append(list(ln.bbox))
        zones, diag = detect_zones(
            img, outcome.dpi, boxes, zcfg, image_qr=image_qr, vector_sheet=vector_sheet
        )
        outcome.zones = zones
        outcome.zone_masks = (diag["mask"], diag["dark"])
        outcome.t_zones = time.perf_counter() - t0

    def _is_vector_sheet(self, plan: RoutePlan, facts: PageFacts) -> bool:
        return (
            plan.render_kind == "vector"
            and max(facts.width_mm, facts.height_mm) >= self.cfg.zones.sheet_min_long_side_mm
        )

    def _ocr_full(
        self,
        page,
        plan: RoutePlan,
        facts: PageFacts,
        warnings: list[str],
        page_layers: list[str],
        image_qr: list[Zone] | None = None,
    ) -> _OcrOutcome:
        ocfg = self.cfg.ocr
        t0 = time.perf_counter()
        img, dpi = self._render(page, plan, facts, warnings)
        h, w = img.shape[:2]
        t_render = time.perf_counter() - t0
        orient = None
        k = 0
        t1 = time.perf_counter()
        if plan.orientation:
            orient = detect_orientation(self.engine, img, self.cfg.orientation)
            k = orient.k
        t_orient = time.perf_counter() - t1
        work = rotate_image(img, k)
        lines, info = ocr_with_fallback(self.engine, work, ocfg)
        stats = info["stats"]
        outcome = _OcrOutcome(lines, w, h, dpi, orient, stats, boxes_detected=stats.n_boxes)
        outcome.fallback_tried, outcome.fallback_used = info["fallback_tried"], info["fallback_used"]
        outcome.union_added = info["union_added"]
        if k:
            for ln in outcome.lines:
                ln.quad = map_points_back(ln.quad, k, w, h)
                ln.angle = (ln.angle + 90 * k) % 360
                for wd in ln.words:
                    wd.quad = map_points_back(wd.quad, k, w, h)
        outcome.t_render, outcome.t_orient = t_render, t_orient
        self._zones_on_render(outcome, img, [], image_qr or [], self._is_vector_sheet(plan, facts))
        if plan.render_kind == "vector" and k == 0:
            t2 = time.perf_counter()
            base_ink = ink_count(img)
            del img, work
            outcome.lines, outcome.iso = self._isolated_pass(
                page, dpi, base_ink, outcome.lines, np.zeros((0, 4)), stats, page_layers
            )
            outcome.t_iso = time.perf_counter() - t2
        return outcome

    def _ocr_coverage(
        self,
        page,
        plan: RoutePlan,
        facts: PageFacts,
        words: list[TextWord],
        warnings: list[str],
        page_layers: list[str],
        image_qr: list[Zone] | None = None,
    ) -> _OcrOutcome:
        ocfg = self.cfg.ocr
        t0 = time.perf_counter()
        img, dpi = self._render(page, plan, facts, warnings)
        h, w = img.shape[:2]
        t_render = time.perf_counter() - t0
        stats = OcrStats(detector=self.engine.det_small.name)
        t1 = time.perf_counter()
        quads = detect_tiled(self.engine.det_small, img, ocfg, stats)
        stats.det_s = time.perf_counter() - t1
        boxes = (
            np.array(
                [[q[:, 0].min() / w, q[:, 1].min() / h, q[:, 0].max() / w, q[:, 1].max() / h] for q in quads]
            )
            if quads
            else np.zeros((0, 4))
        )
        cover = np.array([wd.bbox for wd in words]) if words else np.zeros((0, 4))
        share = coverage_of(boxes, cover)
        uncovered = [q for q, s in zip(quads, share, strict=True) if s < self.cfg.router.covered_share]
        lines: list[OcrLine] = []
        if uncovered:
            lines, st2 = ocr_image(self.engine, img, ocfg, quads=uncovered)
            stats.rec_s = st2.rec_s
            stats.n_retry180, stats.n_unrotated = st2.n_retry180, st2.n_unrotated
            stats.n_chunked, stats.n_redetect = st2.n_chunked, st2.n_redetect
        stats.n_boxes = len(quads)
        out = _OcrOutcome(
            lines,
            w,
            h,
            dpi,
            None,
            stats,
            boxes_detected=len(quads),
            boxes_covered=len(quads) - len(uncovered),
        )
        out.t_render = t_render
        self._zones_on_render(
            out, img, [[b[0] * w, b[1] * h, b[2] * w, b[3] * h] for b in cover], image_qr or [],
            self._is_vector_sheet(plan, facts),
        )  # fmt: skip
        if plan.render_kind == "vector":
            t2 = time.perf_counter()
            base_ink = ink_count(img)
            del img
            out.lines, out.iso = self._isolated_pass(
                page, dpi, base_ink, out.lines, cover, stats, page_layers
            )
            out.t_iso = time.perf_counter() - t2
        return out

    def _ocr_images(self, page, facts: PageFacts, warnings: list[str]) -> _OcrOutcome:
        """STAMP_PAGE: OCR of the placed image regions only (stamps, e-signature certificates), not the blank
        page. Regions are the image boxes padded by ~2 mm and merged. The page is rendered once at the scan
        dpi ceiling and everything outside the regions is blanked, so detection runs on the standard tiles
        (blank tiles skipped, the CoreML canvases reused): a small strip read on its own would be upscaled to
        the detector's 736-px minimum side and miss every static canvas (measured: 24 s of CPU detection per
        e-signature sheet instead of < 1 s). Lines come back in pixels of the whole page at that dpi."""
        from inspector_docproc.render import mupdf_rect_to_norm

        ocfg = self.cfg.ocr
        dpi, capped = capped_dpi(page, self.cfg.render.scan_dpi_max, self.cfg.render)
        if capped:
            warnings.append("RENDER_CAPPED")
        pw, ph = page.rect.width, page.rect.height
        pad_x, pad_y = 6.0 / pw, 6.0 / ph  # ~2 mm
        boxes: list[list[float]] = []
        for info in page.get_image_info():
            b = mupdf_rect_to_norm(page, info["bbox"])
            if b[2] - b[0] <= 0 or b[3] - b[1] <= 0:
                continue
            boxes.append(
                [
                    max(0.0, b[0] - pad_x),
                    max(0.0, b[1] - pad_y),
                    min(1.0, b[2] + pad_x),
                    min(1.0, b[3] + pad_y),
                ]
            )
        merged: list[list[float]] = []
        for b in sorted(boxes):
            for m in merged:
                if b[0] <= m[2] and m[0] <= b[2] and b[1] <= m[3] and m[1] <= b[3]:
                    m[:] = [min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])]
                    break
            else:
                merged.append(list(b))
        t0 = time.perf_counter()
        img = render_page(page, dpi)
        h, w = img.shape[:2]
        canvas = np.full_like(img, 255)
        for x0, y0, x1, y1 in merged:
            xa, ya, xb, yb = int(x0 * w), int(y0 * h), int(np.ceil(x1 * w)), int(np.ceil(y1 * h))
            canvas[ya:yb, xa:xb] = img[ya:yb, xa:xb]
        t_render = time.perf_counter() - t0
        lines, info = ocr_with_fallback(self.engine, canvas, ocfg)
        out = _OcrOutcome(lines, w, h, dpi, None, info["stats"], boxes_detected=info["stats"].n_boxes)
        out.fallback_tried, out.fallback_used = info["fallback_tried"], info["fallback_used"]
        out.union_added = info["union_added"]
        out.t_render = t_render
        out.regions = len(merged)
        return out

    # ── OCR lines → contract tokens ───────────────────────────────────────────────────────────
    def _append_ocr_lines(
        self,
        lines: list[OcrLine],
        width: float,
        height: float,
        cover: np.ndarray,
        tokens: list[dict[str, Any]],
        lines_out: list[dict[str, Any]],
        offset: tuple[float, float] | None = None,
    ) -> tuple[int, int]:
        """Append accepted OCR lines as PageTokens tokens/lines; returns (rejected, accepted) line counts.

        ``width``/``height`` are the pixel size of the whole displayed page at the render dpi and
        ``offset`` the pixel position of the rendered image on it (region OCR); quads are image pixels.
        Words whose box is covered by ``cover`` (normalized text-layer word boxes) are dropped.
        """
        ocfg = self.cfg.ocr
        shift = np.asarray(offset, np.float32) if offset is not None else None

        def px(q: np.ndarray) -> np.ndarray:
            return q + shift if shift is not None else q

        pcfg = self.cfg.post
        good = [ln for ln in lines if ln.score >= ocfg.min_line_score and ln.text.strip()]
        # script prior of the page (codefix rule 2): every accepted OCR word of this call
        prior = page_script(wd.text for ln in good for wd in ln.words) if pcfg.script_context else None
        freq = load_wordfreq() if pcfg.script_context else None
        rejected = accepted = 0
        for ln in lines:
            if ln.score < ocfg.min_line_score or not ln.text.strip():
                rejected += 1
                continue
            words = [wd for wd in ln.words if wd.text.strip()]
            if not words:
                continue
            wboxes = np.array([norm_bbox_from_points(px(wd.quad), width, height) for wd in words])
            keep = coverage_of(wboxes, cover) < self.cfg.router.covered_share
            if not keep.any():
                continue
            fixed_words = post_correct_line(
                [wd.text for wd in words],
                self.code_extras,
                page=prior,
                code=pcfg.code_corrector,
                fold=pcfg.homoglyph_fold,
                context=pcfg.script_context,
                diameter=pcfg.diameter_sign,
                lexicon=self.lexicon.words,
                freq=freq,
            )
            lid = len(lines_out)
            ids: list[int] = []
            for wd, wb, k, (fixed, corrector) in zip(words, wboxes, keep, fixed_words, strict=True):
                if not k:
                    continue
                raw = wd.text
                conf = float(min(1.0, max(0.0, wd.conf)))
                tok = {
                    "id": len(tokens),
                    "text": fixed,
                    "bbox": [float(v) for v in wb],
                    "polygon": norm_polygon(px(wd.quad), width, height),
                    "conf": round(conf, 4),
                    "source": ln.source,
                    "angle": ln.angle,
                    "line_id": lid,
                    "quality_flag": quality_flag(conf, ocfg.quality_ok, ocfg.quality_low),
                }
                if fixed != raw:
                    tok["text_raw"] = raw
                    tok["corrected_by"] = corrector
                ids.append(tok["id"])
                tokens.append(tok)
            accepted += 1
            lines_out.append(
                {
                    "id": lid,
                    "text": " ".join(tokens[i]["text"] for i in ids),
                    "bbox": _union([tokens[i]["bbox"] for i in ids]),
                    "polygon": norm_polygon(px(ln.quad), width, height),
                    "token_ids": ids,
                    "conf": round(float(min(1.0, max(0.0, ln.score))), 4),
                    "source": ln.source,
                    "angle": ln.angle,
                }
            )
        return rejected, accepted

    def ocr_region(
        self,
        page,
        bbox_norm: Sequence[float],
        *,
        dpi: int = 300,
        orientation: bool = False,
    ) -> dict[str, Any]:
        """OCR of one region of a page at a chosen dpi, e.g. a title block at 300 dpi (96 §7.3, AG-02B).

        ``bbox_norm`` is a region of the displayed page in contract space. Returns ``{"tokens", "lines",
        "render_dpi", "content_rotation", "capped"}``: tokens and lines use the PageTokens layout (source
        ``OCR``, post-corrected text with ``text_raw``), with bbox/polygon normalized to the **whole page**
        and ids starting at 0 (renumber when merging into a PageTokens document). The text layer is not
        consulted: the caller decides what to OCR. Same engine and OCR v2 pipeline as full pages.
        """
        import pymupdf

        x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in bbox_norm)
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"empty region {list(bbox_norm)}")
        pw, ph = page.rect.width, page.rect.height
        area_in2 = (x1 - x0) * pw * (y1 - y0) * ph / 72.0 / 72.0
        capped = area_in2 * dpi * dpi / 1e6 > self.cfg.render.max_megapixels
        if capped:
            dpi = max(72, int((self.cfg.render.max_megapixels * 1e6 / area_in2) ** 0.5))
        zoom = dpi / 72.0
        clip = pymupdf.Rect(
            page.rect.x0 + x0 * pw, page.rect.y0 + y0 * ph, page.rect.x0 + x1 * pw, page.rect.y0 + y1 * ph
        )
        img = render_page(page, dpi, clip=clip)
        h, w = img.shape[:2]
        k = 0
        orient = None
        if orientation:
            orient = detect_orientation(self.engine, img, self.cfg.orientation)
            k = orient.k
        lines, _ = ocr_with_fallback(self.engine, rotate_image(img, k), self.cfg.ocr)
        if k:
            for ln in lines:
                ln.quad = map_points_back(ln.quad, k, w, h)
                ln.angle = (ln.angle + 90 * k) % 360
                for wd in ln.words:
                    wd.quad = map_points_back(wd.quad, k, w, h)
        tokens: list[dict[str, Any]] = []
        lines_out: list[dict[str, Any]] = []
        origin = (float(round(clip.x0 * zoom)), float(round(clip.y0 * zoom)))  # pixmap origin (irect)
        self._append_ocr_lines(lines, pw * zoom, ph * zoom, np.zeros((0, 4)), tokens, lines_out, origin)
        return {
            "tokens": tokens,
            "lines": lines_out,
            "render_dpi": dpi,
            "content_rotation": orient.content_rotation if orient is not None else 0,
            "capped": capped,
        }

    # ── Page ────────────────────────────────────────────────────────────────────────────────────
    def recognize_page(self, doc, page_no: int, *, file_id: str, file_sha256: str) -> dict[str, Any]:
        t_start = time.perf_counter()
        page = doc[page_no - 1]
        warnings: list[str] = []
        t0 = time.perf_counter()
        layer = extract_text_layer(page)
        facts, plan, repair = route(page, layer, self.cfg.router, self.lexicon)
        plan, probe = self._verify_garble_verdict(page, layer, facts, plan)
        ocgs = self._doc_ocgs(doc)
        page_layers = page_layer_names(page, ocgs) if ocgs else []
        t_text = time.perf_counter() - t0

        text_words = [w for w in layer.visible_words if plan.trusted_text and not w.garbled]
        zcfg = self.cfg.zones
        t_qr = time.perf_counter()
        image_qr = qr_from_images(page, zcfg) if (zcfg.enabled and zcfg.qr and facts.images.count) else []
        t_qr = time.perf_counter() - t_qr
        outcome: _OcrOutcome | None = None
        if plan.action == "ocr_full":
            outcome = self._ocr_full(page, plan, facts, warnings, page_layers, image_qr)
        elif plan.action == "text+coverage":
            outcome = self._ocr_coverage(page, plan, facts, text_words, warnings, page_layers, image_qr)
        elif plan.action == "ocr_images":
            outcome = self._ocr_images(page, facts, warnings)

        tokens: list[dict[str, Any]] = []
        lines_out: list[dict[str, Any]] = []
        ocfg = self.cfg.ocr

        # Text-layer tokens (grouped into their PDF lines).
        line_ids: dict[tuple[int, int], int] = {}
        line_members: dict[int, list[int]] = {}
        for wd in text_words:
            lid = line_ids.setdefault((wd.block, wd.line), len(line_ids))
            tok: dict[str, Any] = {
                "id": len(tokens),
                "text": wd.text,
                "bbox": wd.bbox,
                "conf": 1.0,
                "source": "TEXT_LAYER_REPAIRED" if wd.repaired else "TEXT_LAYER",
                "angle": wd.angle,
                "line_id": lid,
                "block_id": wd.block,
                "quality_flag": "OK",
            }
            if wd.repaired and wd.text_raw is not None:
                tok["text_raw"] = wd.text_raw
                tok["corrected_by"] = "glyph_shift_repair"
            if wd.font:
                tok["font"] = wd.font
            if wd.size > 0:
                tok["font_size_pt"] = round(wd.size, 2)
            tokens.append(tok)
            line_members.setdefault(lid, []).append(tok["id"])
        for lid, ids in line_members.items():
            members = [tokens[i] for i in ids]
            lines_out.append(
                {
                    "id": lid,
                    "text": " ".join(t["text"] for t in members),
                    "bbox": _union([t["bbox"] for t in members]),
                    "token_ids": ids,
                    "conf": 1.0,
                    "source": members[0]["source"],
                    "angle": members[0]["angle"],
                }
            )

        # OCR tokens: accepted lines only; words already covered by the text layer are dropped.
        rejected = 0
        n_ocr_lines = 0
        if outcome is not None:
            cover = np.array([wd.bbox for wd in text_words]) if text_words else np.zeros((0, 4))
            rejected, n_ocr_lines = self._append_ocr_lines(
                outcome.lines, outcome.width, outcome.height, cover, tokens, lines_out
            )

        # Zones (R-10): seals, stamps, QR, handwriting; tokens inside are listed, handwriting ABSTAIN.
        zones: list[Zone] = (
            outcome.zones if outcome is not None and outcome.zones is not None else None
        ) or list(image_qr)
        zone_counts: dict[str, int] = {}
        if zones:
            masks = (
                outcome.zone_masks if outcome is not None and outcome.zone_masks is not None else (None, None)
            )
            zone_counts = assign_tokens(zones, tokens, masks[0], masks[1], zcfg)
            if any(z.kind == "HANDWRITING" for z in zones):
                warnings.append("HANDWRITING_ZONES")
            if zone_counts.get("tokens_under_seal"):
                warnings.append("SEAL_OVERLAP")

        # Page-level quality and warnings.
        ocr_confs = [t["conf"] for t in tokens if t["source"] in OCR_SOURCES]
        all_confs = [t["conf"] for t in tokens]
        mean_conf = round(float(np.mean(all_confs)), 4) if all_confs else None
        if plan.action in ("ocr_full", "ocr_images"):
            if not ocr_confs:
                page_quality = "ABSTAIN"
                if outcome is not None and outcome.boxes_detected:
                    warnings.append("OCR_FAILED")
            else:
                page_quality = quality_flag(float(np.mean(ocr_confs)), ocfg.quality_ok, ocfg.quality_low)
            if outcome is not None and outcome.lines and rejected / len(outcome.lines) >= 0.2:
                warnings.append("OCR_PARTIAL")
        else:
            page_quality = "OK"
        native = facts.images.native_dpi
        if (
            plan.render_kind == "scan"
            and plan.action != "none"
            and native is not None
            and native < LOW_DPI_BELOW
        ):
            warnings.append("LOW_DPI")

        coverage = None
        if outcome is not None and outcome.boxes_detected:
            if plan.action == "text+coverage":
                ocr_boxes = outcome.boxes_detected - outcome.boxes_covered
                ok_boxes = outcome.boxes_covered + max(0, ocr_boxes - rejected)
            else:
                ok_boxes = outcome.boxes_detected - rejected
            coverage = round(min(1.0, max(0.0, ok_boxes / outcome.boxes_detected)), 4)

        sources = [t["source"] for t in tokens]
        text_source = max(set(sources), key=sources.count) if sources else None
        if plan.action == "ocr_full" and outcome is not None:
            text_source = "OCR"

        eng_versions: dict[str, str] | None = None
        timings = {"text_layer_ms": round(t_text * 1000, 1)}
        t_zone_total = t_qr + (outcome.t_zones if outcome is not None else 0.0)
        if zones or t_zone_total >= 0.0005:
            timings["zones_ms"] = round(t_zone_total * 1000, 1)
        page_info: dict[str, Any] = {
            "width_pt": round(float(page.rect.width), 3),
            "height_pt": round(float(page.rect.height), 3),
            "rotate": normalize_rotation(page.rotation),
            "content_rotation": 0,
            "mediabox": [round(float(v), 3) for v in page.mediabox],
            "cropbox": _raw_cropbox(page),
            "native_dpi": round(native) if native else None,
            "render_dpi": None,
        }
        ext: dict[str, Any] = {"route": plan.as_dict(), "facts": facts.as_dict()}
        if repair is not None:
            ext["repair"] = repair.as_dict()
        if probe is not None:
            ext["layer_probe"] = probe
        if outcome is not None:
            eng_versions = self.engine.versions()
            if outcome.fallback_used:
                eng_versions["det_used"] = self.engine.detector("medium").name
            page_info["render_dpi"] = outcome.dpi
            if outcome.orientation is not None:
                page_info["content_rotation"] = outcome.orientation.content_rotation
                ext["orientation"] = outcome.orientation.as_dict()
            ext["ocr"] = {
                **outcome.stats.as_dict(),
                "boxes_detected": outcome.boxes_detected,
                "boxes_covered_by_text_layer": outcome.boxes_covered,
                "lines_rejected": rejected,
                "lines_accepted": n_ocr_lines,
                "fallback_tried": outcome.fallback_tried,
                "fallback_used": outcome.fallback_used,
                "medium_union_lines": outcome.union_added,
            }
            if outcome.iso is not None:
                ext["ocr"]["layer_isolation"] = outcome.iso
            if outcome.regions:
                ext["ocr"]["regions"] = outcome.regions
            timings.update(
                render_ms=round(outcome.t_render * 1000, 1),
                orientation_ms=round(outcome.t_orient * 1000, 1),
                det_ms=round(outcome.stats.det_s * 1000, 1),
                rec_ms=round(outcome.stats.rec_s * 1000, 1),
            )
            if outcome.iso is not None:
                timings["isolation_ms"] = round(outcome.t_iso * 1000, 1)
        timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 1)

        doc_out: dict[str, Any] = {
            "schema_version": 1,
            "file_id": file_id,
            "file_sha256": file_sha256,
            "page_no": page_no,
            "page_basis": "PDF_NATIVE",
            "geometry_space": "PDF_VISIBLE_ROTATED_TL_V1",
            "page": page_info,
            "page_class": plan.page_class,
            "is_stamp_page": plan.page_class == "STAMP_PAGE",
            "quality_flag": page_quality,
            "mean_conf": mean_conf,
            "coverage": coverage,
            "pipeline_version": self.pipeline_version(),
            "timings_ms": timings,
            "warnings": sorted(set(warnings)),
            "tokens": tokens,
            "lines": lines_out,
            "ext": ext,
        }
        if text_source:
            doc_out["text_source"] = text_source
        if page_layers:
            doc_out["layers"] = page_layers
        if eng_versions:
            doc_out["engine_versions"] = eng_versions
        zone_docs = [z.as_contract() for z in zones]
        if plan.page_class == "STAMP_PAGE" and facts.images.largest_bbox_norm is not None:
            zone_docs.insert(0, {
                "kind": "STAMP",
                "bbox": [round(v, 4) for v in facts.images.largest_bbox_norm],
                "source": "AUTO",
                "attrs": {"method": "stamp_page_largest_image"},
            })  # fmt: skip
        if zone_docs:
            doc_out["zones"] = zone_docs
        if zones or zone_counts:
            ext["zones"] = {
                **zone_counts,
                "n": len(zones),
                "kinds": dict(sorted(Counter(z.kind for z in zones).items())),
            }
        return doc_out


def _union(boxes: list[list[float]]) -> list[float]:
    return [
        round(min(b[0] for b in boxes), 5),
        round(min(b[1] for b in boxes), 5),
        round(max(b[2] for b in boxes), 5),
        round(max(b[3] for b in boxes), 5),
    ]


def _raw_cropbox(page) -> list[float]:
    """CropBox in PDF user space (PyMuPDF reports it top-left based, relative to the MediaBox top)."""
    mb = page.mediabox
    cb = page.cropbox
    return [round(float(v), 3) for v in (cb.x0, mb.y1 - cb.y1, cb.x1, mb.y1 - cb.y0)]
