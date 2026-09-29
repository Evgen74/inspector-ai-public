"""Per-page title-block and QR pass (runs inside a worker process).

For each page:
1. **Words of the stamp window** from PageTokens of a recognition run when available (AG-02A), otherwise
   from the PDF text layer. Garbled (mojibake) words do not count as text.
2. **Title block from those words** (:func:`titleblock.read_title_block`).
3. **OCR fallback** when no key field was read and the window has almost no text: only if a ruled stamp grid is
   drawn there (cheap 100 dpi render, :func:`stamp_grid`), the window (200 × 72 mm) is OCR'd at 300 dpi
   through AG-02A's ``PageRecognizer.ocr_region`` (v6-small detector only: the medium detector added 55 % of
   the time and nothing on the stamps). This is the only OCR the layout step does: on the gold RD sheets the
   whole stamp is curves (96 §7.1). The Exon QR image is pasted *over* the sheet title of the Тюменская RD
   stamps («План по|двала», «Схе|ма системы…»): square images inside the window are removed from a one-page
   in-memory copy before the OCR (:func:`hide_window_images`, ≈ 0.1 s), so the vector title underneath reads
   whole. The QR itself is decoded from the original page.
4. **QR codes** (:func:`qr.decode_page`).
"""

from __future__ import annotations

import gzip
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from inspector_layout.codes import CodeRegistry
from inspector_layout.qr import QrDecoder, decode_page
from inspector_layout.titleblock import TitleBlockRead, read_title_block
from inspector_layout.words import Word, from_text_layer, from_tokens, page_size_mm

OCR_WINDOW_MM = (200.0, 72.0)
MIN_WINDOW_CHARS = 20  # 96 §7.3: text layer when the stamp zone holds ≥ 20 characters
CELL_DPI = 400  # key-value cells re-read on a crop (a lone «Лист» digit the window pass missed)
TITLE_DPI = 300
CELL_PAD_MM = 2.0  # context around a cell crop; the value is taken from words centred inside the cell
_MOJIBAKE = re.compile(r"[ƀ-˿Ͱ-Ͽ�]")


@dataclass(slots=True)
class ScanOptions:
    ocr: bool = True
    ocr_dpi: int = 300
    ocr_scans: bool = False  # OCR stamps on raster scans too (off: ИД scans are AG-02A/02C territory)
    providers: str = "cpu"
    threads: int = 2
    qr: bool = True
    qr_render: bool = True
    tokens_dir: str | None = None  # runs/<run>/tokens (PageTokens of a recognition run)


@dataclass(slots=True)
class PageScan:
    page: int
    width_mm: float
    height_mm: float
    title_block: dict[str, Any] | None = None
    form: str | None = None
    words_source: str | None = None  # "tokens" | "text_layer" | "ocr"
    code_basis: str | None = None
    sheet_raw: str | None = None
    sheet_source: str | None = None
    qr: list[dict[str, Any]] = field(default_factory=list)
    is_stamp_page: bool = False
    stamp_grid: bool | None = None
    ocr_hidden_images: int = 0  # square images (QR) removed from the OCR copy of the window
    cells_reread: list[str] = field(default_factory=list)  # cells re-OCR'd on a crop that changed a field
    words_ms: float = 0.0
    grid_ms: float = 0.0
    ocr_ms: float = 0.0
    cell_ms: float = 0.0
    qr_ms: float = 0.0
    total_ms: float = 0.0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def load_page_tokens(tokens_dir: str | None, file_id: str, page: int) -> dict[str, Any] | None:
    """PageTokens of one page from a recognition run; ``tokens_dir`` is that run's ``tokens/`` directory and the
    file inside it is resolved through the contract layout (``PAGE_TOKENS``)."""
    if not tokens_dir:
        return None
    from inspector_common.runlayout import RunLayout

    p = RunLayout(Path(tokens_dir).parent).path("PAGE_TOKENS", file_id=file_id, page=page)
    if not p.is_file():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


STAMP_CORE_MM = (190.0, 60.0)  # the 185 × 55 mm stamp inside the 5 mm frame margin


def window_text_chars(
    words: list[Word], w_mm: float, h_mm: float, core_mm: tuple[float, float] = STAMP_CORE_MM
) -> int:
    """Readable text-layer characters inside the stamp core. Drawing text next to an outlined stamp (a table
    column left of it on F0201 p31) must not hide that the stamp itself has no text; OCR tokens of a
    recognition run do not count either (a stamp they could not be read from is re-OCR'd at 300 dpi)."""
    x0, y0 = w_mm - core_mm[0], h_mm - core_mm[1]
    n = 0
    for w in words:
        if not w.source.startswith("TEXT_LAYER"):
            continue
        if w.cx >= x0 and w.cy >= y0 and not _MOJIBAKE.search(w.text):
            n += len(w.text.strip())
    return n


def stamp_grid(page, window_mm: tuple[float, float] = OCR_WINDOW_MM, dpi: int = 100) -> bool:
    """A ruled stamp is drawn in the bottom-right window: ≥ 3 long horizontal and ≥ 3 vertical rulings."""
    import cv2
    import pymupdf

    from inspector_docproc.render import render_page

    mm = 72.0 / 25.4
    r = page.rect
    wmm, hmm = r.width / mm, r.height / mm
    x0, y0 = max(0.0, wmm - window_mm[0]), max(0.0, hmm - window_mm[1])
    clip = pymupdf.Rect(r.x0 + x0 * mm, r.y0 + y0 * mm, r.x1, r.y1)
    try:
        img = render_page(page, dpi, clip=clip)
    except Exception:
        return False
    gray = img[:, :, 1] if img.ndim == 3 else img
    ink = (gray < 190).astype(np.uint8)
    px_mm = dpi / 25.4
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(35 * px_mm)), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(7 * px_mm))))
    hor = cv2.morphologyEx(ink, cv2.MORPH_OPEN, hk)
    ver = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vk)
    rows = np.flatnonzero(hor.any(axis=1))
    cols = np.flatnonzero(ver.any(axis=0))
    n_h = int((np.diff(rows) > 1).sum() + 1) if rows.size else 0
    n_v = int((np.diff(cols) > 1).sum() + 1) if cols.size else 0
    return n_h >= 3 and n_v >= 3


def _is_scan(page) -> bool:
    from inspector_docproc.render import image_facts

    try:
        return image_facts(page).max_share > 0.6
    except Exception:
        return False


def _window_images(page, window_norm: list[float]) -> list[dict[str, Any]]:
    """Square images (QR-sized, 5–60 mm) whose centre lies inside the normalized window."""
    from inspector_docproc.render import mupdf_rect_to_norm
    from inspector_layout.qr import _image_candidates

    out = []
    for inf in _image_candidates(page):
        try:
            x0, y0, x1, y1 = mupdf_rect_to_norm(page, inf["bbox"])
        except Exception:
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if window_norm[0] <= cx <= window_norm[2] and window_norm[1] <= cy <= window_norm[3]:
            out.append(inf)
    return out


def hide_window_images(page, window_norm: list[float]):
    """A one-page in-memory copy of ``page`` without the square images of the window, or None.

    Returns ``(copy_document, copy_page, n_removed)``; the caller closes the document. The source document is
    never modified (it is shared by the QR pass and by other readers of the worker).
    """
    import pymupdf

    if not _window_images(page, window_norm):
        return None
    tmp = pymupdf.open()
    try:
        tmp.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        tpage = tmp[0]
        n = 0
        for inf in _window_images(tpage, window_norm):
            try:
                tpage.delete_image(int(inf["xref"]))
                n += 1
            except Exception:
                continue
        if n == 0:
            tmp.close()
            return None
        return tmp, tpage, n
    except Exception:
        tmp.close()
        return None


class PageScanner:
    """One per worker process: holds the QR detectors and, lazily, the OCR engine."""

    def __init__(self, registry: CodeRegistry, opts: ScanOptions) -> None:
        self.registry = registry
        self.opts = opts
        self.qr = QrDecoder() if opts.qr else None
        self._rec = None
        self._lexicon = None
        self._qr_image_cache: dict[int, str | None] = {}
        self._qr_render_misses = 0
        self._qr_render_hits = 0

    @property
    def recognizer(self):
        if self._rec is None:
            from inspector_docproc.config import ExecutionConfig, RecognitionConfig
            from inspector_docproc.recognize import PageRecognizer

            cfg = RecognitionConfig().replace(ocr={"medium_mode": "off"})
            exec_cfg = ExecutionConfig(providers=self.opts.providers, threads=self.opts.threads, warmup=False)
            self._rec = PageRecognizer(cfg, exec_cfg)
        return self._rec

    def text_layer(self, page):
        """The page's text layer; a garbled layer (constant glyph shift, «ȺɇɈ/150321» for «АНО/150321») is
        repaired by AG-02A's per-font shift search, accepted only when the lexicon confirms it (as in
        ``recognize``). Unrepaired garbled words stay flagged and are ignored by the reader."""
        from inspector_docproc.repair import repair_words, shift_text, split_repaired, word_is_garbled
        from inspector_docproc.textlayer import extract_text_layer

        layer = extract_text_layer(page)
        if any(w.visible and word_is_garbled(w.text) for w in layer.words):
            if self._lexicon is None:
                from inspector_docproc.lexicon import load_lexicon

                self._lexicon = load_lexicon()
            rep = repair_words(layer.words, lexicon=self._lexicon)
            # A font whose few lexicon-checkable words are already correct is never shifted (its hit ratio
            # cannot improve), although another font of the same page confirmed the offset (F0153 p5:
            # 165 words of TimesNewRomanPSMT left garbled, +0x1D6 accepted for ArialMT). One page-wide
            # confirmed offset is applied to the words still garbled; a word is kept only if it comes out clean.
            offs = {f.offset for f in rep.fonts if f.accepted and f.offset is not None}
            if rep.unrepaired_words and len(offs) == 1:
                off = offs.pop()
                digs = {f.digit_offset for f in rep.fonts if f.accepted and f.digit_offset is not None}
                dig = digs.pop() if len(digs) == 1 else None
                for w in layer.words:
                    if not (w.visible and w.garbled):
                        continue
                    fixed = shift_text(w.text, off, dig)
                    if fixed != w.text and not word_is_garbled(fixed):
                        w.text_raw, w.text, w.repaired, w.garbled = w.text, fixed, True, False
            layer.words = split_repaired(layer.words)
        return layer

    def new_document(self) -> None:
        self._qr_image_cache = {}
        self._qr_render_misses = 0
        self._qr_render_hits = 0

    def _read(self, words: list[Word], w: float, h: float, stage_hint: str | None) -> TitleBlockRead | None:
        return read_title_block(words, w, h, registry=self.registry, stage_hint=stage_hint)

    def reread_cells(
        self, page, tb: TitleBlockRead, w_mm: float, h_mm: float, *, title_covered: bool
    ) -> None:
        """OCR fallback on cell crops (``PageRecognizer.ocr_region``): a key value whose label was read but
        whose value was not (a lone «Лист» digit, at 400 dpi), and — when ``title_covered`` — the sheet title
        under an image (Exon QR), read on the QR-free copy of the page."""
        win = [max(0.0, 1 - OCR_WINDOW_MM[0] / w_mm), max(0.0, 1 - OCR_WINDOW_MM[1] / h_mm), 1.0, 1.0]
        covers: list[tuple[float, float, float, float]] = []
        if title_covered and tb.title_cell is not None:
            from inspector_docproc.render import mupdf_rect_to_norm

            for inf in _window_images(page, win):
                x0, y0, x1, y1 = mupdf_rect_to_norm(page, inf["bbox"])
                covers.append((x0 * w_mm, y0 * h_mm, x1 * w_mm, y1 * h_mm))
        cells = tb.retry_cells(covers)
        if not cells:
            return
        hidden = hide_window_images(page, win) if any(n == "sheet_title" for n, _ in cells) else None
        try:
            for name, (x0, y0, x1, y1) in cells:
                if name == "sheet_title" and hidden is None:
                    continue
                target = hidden[1] if hidden is not None else page
                box = [
                    max(0.0, (x0 - CELL_PAD_MM) / w_mm),
                    max(0.0, (y0 - CELL_PAD_MM) / h_mm),
                    min(1.0, (x1 + CELL_PAD_MM) / w_mm),
                    min(1.0, (y1 + CELL_PAD_MM) / h_mm),
                ]
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                dpi = TITLE_DPI if name == "sheet_title" else CELL_DPI
                out = self.recognizer.ocr_region(target, box, dpi=dpi)
                tb.apply_cell(name, from_tokens(out["tokens"], w_mm, h_mm), (x0, y0, x1, y1))
        finally:
            if hidden is not None:
                hidden[0].close()

    def scan(self, doc, page_no: int, *, file_id: str, stage_hint: str | None) -> PageScan:
        t0 = time.perf_counter()
        page = doc[page_no - 1]
        w_mm, h_mm = page_size_mm(page)
        res = PageScan(page_no, round(w_mm, 1), round(h_mm, 1))
        toks = load_page_tokens(self.opts.tokens_dir, file_id, page_no)
        if toks is not None:
            words = from_tokens(toks.get("tokens", []), w_mm, h_mm)
            res.words_source = "tokens"
            res.is_stamp_page = bool(toks.get("is_stamp_page", False))
        else:
            words = from_text_layer(self.text_layer(page), w_mm, h_mm, keep_garbled=True)
            res.words_source = "text_layer"
        res.words_ms = _ms(t0)
        tb = self._read(words, w_mm, h_mm, stage_hint)
        need_ocr = tb is None or (tb.sheet_number is None and tb.code is None)
        if need_ocr and self.opts.ocr and not res.is_stamp_page:
            sparse = window_text_chars(words, w_mm, h_mm) < MIN_WINDOW_CHARS or tb is not None
            if sparse and (self.opts.ocr_scans or not _is_scan(page)):
                tg = time.perf_counter()
                res.stamp_grid = stamp_grid(page)
                res.grid_ms = _ms(tg)
                if res.stamp_grid:
                    t1 = time.perf_counter()
                    win = [
                        max(0.0, 1 - OCR_WINDOW_MM[0] / w_mm),
                        max(0.0, 1 - OCR_WINDOW_MM[1] / h_mm),
                        1.0,
                        1.0,
                    ]
                    hidden = hide_window_images(page, win)
                    try:
                        target = page if hidden is None else hidden[1]
                        res.ocr_hidden_images = 0 if hidden is None else hidden[2]
                        out = self.recognizer.ocr_region(target, win, dpi=self.opts.ocr_dpi)
                    finally:
                        if hidden is not None:
                            hidden[0].close()
                    ocr_words = from_tokens(out["tokens"], w_mm, h_mm)
                    # text-layer words outside the OCR'd window still count (a stamp partly in text)
                    keep = [
                        x
                        for x in words
                        if not (x.cx >= w_mm - OCR_WINDOW_MM[0] and x.cy >= h_mm - OCR_WINDOW_MM[1])
                    ]
                    tb2 = self._read(ocr_words + keep, w_mm, h_mm, stage_hint)
                    res.ocr_ms = round((time.perf_counter() - t1) * 1000, 1)
                    if tb2 is not None and (tb is None or tb2.key_fields_found >= tb.key_fields_found):
                        tb = tb2
                        res.words_source = "ocr"
        ocr_read = tb is not None and not str(tb.text_source or "").startswith("TEXT_LAYER")
        if ocr_read and self.opts.ocr and not res.is_stamp_page:
            tc = time.perf_counter()
            # our own window OCR already ran on the QR-free copy; a recognition run's tokens did not
            self.reread_cells(page, tb, w_mm, h_mm, title_covered=res.words_source == "tokens")
            res.cells_reread = list(tb.cells_reread)
            res.cell_ms = _ms(tc)
        if tb is not None:
            res.title_block = tb.as_contract(page_no, w_mm, h_mm, is_stamp_page=res.is_stamp_page)
            res.form = tb.form
            res.code_basis = tb.code_basis
            res.sheet_raw = tb.sheet_raw
            res.sheet_source = tb.sheet_source
        if self.qr is not None:
            tq = time.perf_counter()
            big = w_mm * h_mm >= 0.9 * 297 * 420
            # stop rendering for QR in a file whose first large pages had none (vector QR is per document)
            render = (
                self.opts.qr_render
                and big
                and not (self._qr_render_misses >= 6 and self._qr_render_hits == 0)
            )
            res.qr = decode_page(page, self.qr, render_fallback=render, image_cache=self._qr_image_cache)
            if render and not any(h["method"] == "IMAGE" for h in res.qr):
                if any(h["method"] == "RENDER" for h in res.qr):
                    self._qr_render_hits += 1
                else:
                    self._qr_render_misses += 1
            res.qr_ms = _ms(tq)
        res.total_ms = _ms(t0)
        return res


def _ms(t: float) -> float:
    return round((time.perf_counter() - t) * 1000, 1)
