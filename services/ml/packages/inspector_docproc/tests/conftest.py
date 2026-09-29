"""Fixtures for inspector_docproc tests: model availability (synthetic PDFs: inspector_docproc.testing)."""

from __future__ import annotations

import pytest

from inspector_docproc.testing import models_available


@pytest.fixture(scope="session")
def ocr_engine():
    """A CPU OCR engine (deterministic, no CoreML) shared by the tests that need models."""
    if not models_available():
        pytest.skip("OCR models not found in .models/ocr (make verify-models)")
    from inspector_docproc.ocr.engine import OcrEngine

    return OcrEngine(providers="cpu", threads=2)
