"""AG-00 placeholder tests for inspector_docproc (AG-02A/B/C replace/extend them)."""

from __future__ import annotations

import inspector_docproc
from inspector_docproc import batch


def test_package_imports_and_owner() -> None:
    assert inspector_docproc.__version__
    assert batch.OWNER == "AG-02A"


def test_recognition_stack_is_installed() -> None:
    import cv2
    import numpy
    import onnxruntime
    import pymupdf
    import rapidocr  # noqa: F401
    import tokenizers  # noqa: F401

    assert pymupdf.VersionBind.startswith("1.28")
    assert "CPUExecutionProvider" in onnxruntime.get_available_providers()
    assert int(numpy.__version__.split(".")[0]) >= 2
    assert cv2.__version__
