"""Fixtures for inspector_tables tests (helpers: inspector_tables.testing).

Synthetic ruled tables are built with PyMuPDF (no organizer data). Real TRAIN pages are ``@pytest.mark.data``
and skip when the organizer data is absent. Nothing here touches the hidden object.
"""

from __future__ import annotations

import pytest

from inspector_tables.testing import train_path


@pytest.fixture(scope="session")
def open_train():
    """open_train(file_id) → pymupdf.Document of a TRAIN file (cached for the session); skips without data."""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    cache: dict[str, object] = {}

    def _open(file_id: str):
        if file_id not in cache:
            path = train_path(file_id)
            if path is None:
                pytest.skip(f"organizer data not found ({file_id})")
            cache[file_id] = pymupdf.open(path)
        return cache[file_id]

    return _open


@pytest.fixture
def new_pdf():
    """new_pdf(width, height) → (doc, page) of a fresh synthetic PDF."""
    import pymupdf

    def _new(width: float = 842.0, height: float = 595.0):
        doc = pymupdf.open()
        page = doc.new_page(width=width, height=height)
        return doc, page

    return _new
