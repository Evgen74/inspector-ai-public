"""Page router (97 §2.13 F0–F2, 96 §4.1/§4.10, 95 R1/R11): page class and recognition plan per page.

Classes (contract ``PageClass``) and what happens to them:

| class | when | plan |
|---|---|---|
| EMPTY | no text, no images, tiny content stream | nothing |
| STAMP_PAGE | ≤ 20 visible chars, small images only («КОПИЯ ВЕРНА» separators, e-signature sheets) | OCR of the image regions only |
| RASTER_SCAN | a dominant image (≥ 50 % of the page) and no usable text layer, or partial images only | orientation + full OCR at native dpi |
| RASTER_HIDDEN_OCR | a dominant image under an invisible scanner-OCR layer | orientation + full OCR (the layer is not trusted) |
| HYBRID | a visible text layer over a dominant image | trusted layer: text + OCR of uncovered boxes; untrusted: full OCR |
| VECTOR_OUTLINED_TEXT | no text layer but a heavy content stream (text drawn as curves) | full OCR at 200 dpi |
| BROKEN_ENCODING | a garbled text layer | glyph-shift repair → text (TEXT_LAYER_REPAIRED); if it fails → full OCR |
| VECTOR | a usable text layer | text; sheets ≥ A3 or with raster inserts also get word-level coverage OCR |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from inspector_docproc.config import RouterConfig
from inspector_docproc.lexicon import Lexicon, load_lexicon, text_stats
from inspector_docproc.render import ImageFacts, image_facts, page_size_mm
from inspector_docproc.repair import RepairReport, repair_words, split_repaired, word_is_garbled
from inspector_docproc.textlayer import TextLayer

Action = Literal["none", "text", "text+coverage", "ocr_full", "ocr_images"]


@dataclass(slots=True)
class PageFacts:
    width_mm: float
    height_mm: float
    rotate: int
    visible_chars: int
    invisible_chars: int
    white_chars: int
    stream_bytes: int
    images: ImageFacts
    text: dict[str, float | int] = field(default_factory=dict)
    lexicon_hit: float = 0.0
    lexicon_words: int = 0
    garbled_word_share: float = 0.0

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["width_mm"] = round(self.width_mm, 1)
        d["height_mm"] = round(self.height_mm, 1)
        d["lexicon_hit"] = round(self.lexicon_hit, 4)
        d["garbled_word_share"] = round(self.garbled_word_share, 4)
        return d


@dataclass(slots=True)
class RoutePlan:
    page_class: str
    action: Action
    render_kind: Literal["scan", "vector"] = "vector"
    orientation: bool = False
    trusted_text: bool = True  # text-layer words become tokens
    repaired: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def content_stream_bytes(page) -> int:
    doc = page.parent
    total = 0
    try:
        for xref in page.get_contents():
            total += len(doc.xref_stream(xref) or b"")
    except Exception:
        return -1
    return total


def page_facts(page, layer: TextLayer, cfg: RouterConfig, lexicon: Lexicon | None = None) -> PageFacts:
    lexicon = lexicon or load_lexicon()
    w_mm, h_mm = page_size_mm(page)
    visible = layer.visible_words
    texts = [w.text for w in visible]
    stats = text_stats(texts)
    hit, n = lexicon.hit_ratio(texts)
    garbled = sum(word_is_garbled(t) for t in texts)
    return PageFacts(
        width_mm=w_mm,
        height_mm=h_mm,
        rotate=page.rotation,
        visible_chars=int(stats["chars"]),
        invisible_chars=layer.invisible_chars,
        white_chars=layer.white_chars,
        stream_bytes=content_stream_bytes(page),
        images=image_facts(page),
        text=stats,
        lexicon_hit=hit,
        lexicon_words=n,
        garbled_word_share=garbled / len(texts) if texts else 0.0,
    )


def layer_is_garbled(f: PageFacts, cfg: RouterConfig) -> bool:
    """95 R1 (mojibake ratio + low Cyrillic share) extended with the word-level garble share."""
    moj = float(f.text.get("mojibake_ratio", 0.0))
    cyr = float(f.text.get("cyrillic_share", 0.0))
    if f.visible_chars < cfg.min_visible_chars:
        return False
    if moj >= cfg.mojibake_ratio and (cyr < cfg.min_cyrillic_share or f.garbled_word_share >= 0.15):
        return True
    return f.garbled_word_share >= 0.3


def scanner_layer_trusted(f: PageFacts, cfg: RouterConfig) -> bool:
    """A text layer over a scan is trusted only when the lexicon and the script mix confirm it (96 §4.10)."""
    if f.lexicon_words >= cfg.min_words_for_quality and f.lexicon_hit < cfg.lexicon_hit_ok:
        return False
    return float(f.text.get("mixed_script_ratio", 0.0)) <= cfg.mixed_script_max


def route(
    page, layer: TextLayer, cfg: RouterConfig | None = None, lexicon: Lexicon | None = None
) -> tuple[PageFacts, RoutePlan, RepairReport | None]:
    """Classify the page and decide its recognition plan. May repair ``layer`` words in place."""
    cfg = cfg or RouterConfig()
    lexicon = lexicon or load_lexicon()
    f = page_facts(page, layer, cfg, lexicon)
    img = f.images
    vis = f.visible_chars
    long_side = max(f.width_mm, f.height_mm)

    # Near-empty pages: blank, or a separator with a stamp image («КОПИЯ ВЕРНА», 95 R11).
    if vis <= cfg.stamp_max_chars and img.total_share < cfg.stamp_max_image_share and f.stream_bytes < 5000:
        if img.count == 0 and vis <= cfg.empty_max_chars and f.stream_bytes < 1000:
            return f, RoutePlan("EMPTY", "none", reason="no_content"), None
        if img.count > 0:
            # the stamps themselves are read: e-signature sheets carry certificate serials, owners and
            # validity dates (GT v2 N01/N02); a separator's «КОПИЯ ВЕРНА» costs one small region OCR
            return f, RoutePlan("STAMP_PAGE", "ocr_images", "scan", reason="separator_or_stamp"), None
        if vis > 0:
            return f, RoutePlan("STAMP_PAGE", "none", reason="separator_or_stamp"), None
        return f, RoutePlan("EMPTY", "none", reason="no_text_small_stream"), None

    # Pages dominated by a raster image.
    if img.max_share >= 0.5:
        if f.invisible_chars >= cfg.min_visible_chars and vis < cfg.min_visible_chars:
            return (
                f,
                RoutePlan(
                    "RASTER_HIDDEN_OCR",
                    "ocr_full",
                    "scan",
                    True,
                    trusted_text=True,
                    reason="scanner_ocr_layer",
                ),
                None,
            )
        if vis >= cfg.min_visible_chars:
            if layer_is_garbled(f, cfg) or not scanner_layer_trusted(f, cfg):
                return (
                    f,
                    RoutePlan(
                        "HYBRID",
                        "ocr_full",
                        "scan",
                        True,
                        trusted_text=False,
                        reason="untrusted_layer_over_scan",
                    ),
                    None,
                )
            return f, RoutePlan("HYBRID", "text+coverage", "scan", False, reason="text_over_scan"), None
        return f, RoutePlan("RASTER_SCAN", "ocr_full", "scan", True, reason="scan"), None

    if vis < cfg.min_visible_chars:
        if f.stream_bytes >= cfg.outlined_stream_bytes:
            return (
                f,
                RoutePlan("VECTOR_OUTLINED_TEXT", "ocr_full", "vector", False, reason="text_as_curves"),
                None,
            )
        if img.total_share >= cfg.raster_insert_share:
            return f, RoutePlan("RASTER_SCAN", "ocr_full", "scan", True, reason="partial_images"), None
        if long_side >= cfg.coverage_min_side_mm:
            return f, RoutePlan("VECTOR", "text+coverage", "vector", reason="sparse_text_sheet"), None
        return f, RoutePlan("VECTOR", "text", "vector", reason="sparse_text"), None

    if layer_is_garbled(f, cfg):
        report = repair_words(layer.words, cfg, lexicon)
        layer.words = split_repaired(layer.words)
        after = text_stats([w.text for w in layer.visible_words])
        still_bad = report.unrepaired_words > 0.1 * max(1, len(layer.visible_words)) or (
            float(after["mojibake_ratio"]) >= cfg.mojibake_ratio
        )
        if report.repaired_words and not still_bad:
            # leftovers (unrepaired words) are excluded from the text tokens: coverage OCR reads them
            wide = long_side >= cfg.coverage_min_side_mm or report.unrepaired_words > 0
            action: Action = "text+coverage" if wide else "text"
            return (
                f,
                RoutePlan("BROKEN_ENCODING", action, "vector", repaired=True, reason="glyph_shift_repaired"),
                report,
            )
        return (
            f,
            RoutePlan(
                "BROKEN_ENCODING",
                "ocr_full",
                "vector",
                False,
                trusted_text=False,
                reason="garbled_unrepairable",
            ),
            report,
        )

    if long_side >= cfg.coverage_min_side_mm or img.total_share >= cfg.raster_insert_share:
        return f, RoutePlan("VECTOR", "text+coverage", "vector", reason="drawing_or_raster_inserts"), None
    return f, RoutePlan("VECTOR", "text", "vector", reason="text_layer"), None
