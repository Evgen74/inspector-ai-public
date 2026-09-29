"""Cheap per-PDF probe for the inventory: page count, encryption, first-page fingerprints and the
text of the first pages for stage signals. PyMuPDF opens files lazily (a 658 MB binder opens in
tens of milliseconds), so this stays well under a second per file.

Fingerprints for near-duplicate detection (97 §2.12 «near-duplicates by text hash»):
- ``first_page_text_hash``: sha256 of the normalised text layer of page 1 (when it has at least
  ``MIN_TEXT_CHARS`` characters);
- ``first_page_image_hash``: sha256 over the raw streams of the images drawn on page 1 (scans).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROBE_VERSION = "pdf-probe-1"
MIN_TEXT_CHARS = 40
STAGE_TEXT_PAGES = 3
STAGE_TEXT_MAX_CHARS = 20_000
_IMAGE_HASH_MAX_BYTES = 64 * 1024**2
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """NFC, casefold, ё→е, whitespace collapsed. Used for hashing and keyword signals only."""
    text = unicodedata.normalize("NFC", text).casefold().replace("ё", "е")
    return _WS.sub(" ", text).strip()


@dataclass(slots=True)
class PdfProbe:
    page_count: int | None
    encrypted: bool
    repaired: bool
    error: str | None
    first_page_chars: int
    first_page_text_hash: str | None
    first_page_image_hash: str | None
    stage_text: str  # normalised text of the first pages (kept in memory / cache only)
    probe_version: str = PROBE_VERSION

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PdfProbe:
        return cls(**data)


def probe_pdf(path: Path, *, want_stage_text: bool = True) -> PdfProbe:
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # PyMuPDF raises several exception types for broken files
        return PdfProbe(None, False, False, f"{type(exc).__name__}: {exc}", 0, None, None, "")
    try:
        if doc.needs_pass:
            return PdfProbe(doc.page_count or None, True, False, "PDF защищён паролем", 0, None, None, "")
        page_count = doc.page_count
        repaired = bool(getattr(doc, "is_repaired", False))
        first_text = ""
        image_hash: str | None = None
        stage_chunks: list[str] = []
        if page_count:
            page = doc.load_page(0)
            first_text = normalize_text(page.get_text("text"))
            image_hash = _image_hash(doc, page)
            if want_stage_text:
                stage_chunks.append(first_text)
                for index in range(1, min(STAGE_TEXT_PAGES, page_count)):
                    stage_chunks.append(normalize_text(doc.load_page(index).get_text("text")))
        text_hash = (
            hashlib.sha256(first_text.encode("utf-8")).hexdigest()
            if len(first_text) >= MIN_TEXT_CHARS
            else None
        )
        stage_text = "\n".join(stage_chunks)[:STAGE_TEXT_MAX_CHARS]
        return PdfProbe(page_count, False, repaired, None, len(first_text), text_hash, image_hash, stage_text)
    except Exception as exc:
        return PdfProbe(
            doc.page_count or None, False, False, f"{type(exc).__name__}: {exc}", 0, None, None, ""
        )
    finally:
        doc.close()


def _image_hash(doc: Any, page: Any) -> str | None:
    digest = hashlib.sha256()
    total = 0
    seen = False
    for info in page.get_images(full=True):
        xref = info[0]
        try:
            raw = doc.xref_stream_raw(xref)
        except Exception:
            continue
        if not raw:
            continue
        total += len(raw)
        if total > _IMAGE_HASH_MAX_BYTES:
            break
        digest.update(hashlib.sha256(raw).digest())
        seen = True
    return digest.hexdigest() if seen else None


def probe_pdf_bytes_pages(data: bytes) -> int | None:
    """Page count of an in-memory PDF (archive members); None when unreadable."""
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return None if doc.needs_pass else doc.page_count
    except Exception:
        return None
