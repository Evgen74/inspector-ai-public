from __future__ import annotations

import pytest

from inspector_common.contracts import loader
from inspector_common.contracts.enums import ErrorCode
from inspector_common.errors import InspectorError, render
from inspector_common.exitcodes import ExitCode


def test_error_renders_russian_detail_and_problem() -> None:
    err = InspectorError(
        "FILE_TOO_LARGE", file_name="том 1.pdf", size_mb="51,5", size_bytes=53993684, limit_bytes=52428800
    )
    assert err.http_status == 413 and err.severity == "error" and not err.retryable
    assert "«том 1.pdf» (51,5 МБ)" in err.detail
    body = err.problem(instance="/api/v1/documents/upload", request_id="req-1")
    assert loader.validation_errors("problem", body) == []
    assert body["type"] == "/problems/file-too-large"


def test_every_catalog_code_is_in_the_generated_enum() -> None:
    assert {c.value for c in ErrorCode} == set(loader.load_errors())


def test_unknown_code_is_a_programming_error() -> None:
    with pytest.raises(KeyError):
        InspectorError("NO_SUCH_CODE")


def test_render_keeps_unknown_placeholders_visible() -> None:
    assert render("Файл {file_id}: {reason}", {"file_id": "F0001"}) == "Файл F0001: {reason}"


def test_exit_codes_are_stable() -> None:
    assert ExitCode.GATE_TRIGGERED == 3 and ExitCode.NOT_IMPLEMENTED == 69
