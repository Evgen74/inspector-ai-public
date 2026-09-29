"""`export` step for the protocol: build and validate the canonical JSON, then its DOCX and PDF views.

The JSON (contract ``protocol``) is always written: DOCX and PDF are views of it. A view that fails (no PDF
engine, a renderer error) is reported with its catalogue code (EXPORT_FAILED / RENDERER_UNAVAILABLE) and never
fails the submission, which is already written and validated at this point.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import ContractValidationError, validation_errors
from inspector_common.jsonlog import get_logger
from inspector_compare.artifacts import RunArtifacts, write_json
from inspector_compare.export.sidecar import local_status_of
from inspector_compare.objectctx import ObjectContext
from inspector_compare.protocol.builder import build_protocol

log = get_logger(__name__)


@dataclass(slots=True)
class ProtocolExportResult:
    protocol: dict[str, Any]
    written: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    pdf_engine: str | None = None


def _versions(run_dir: Path) -> dict[str, Any]:
    try:
        ctx = json.loads((run_dir / "run_context.export.json").read_text(encoding="utf-8"))
        return dict(ctx.get("versions") or {})
    except (OSError, ValueError):
        return {}


def export_protocol(
    octx: ObjectContext,
    groups: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    submission: Mapping[str, Any],
    arts: RunArtifacts,
    *,
    run_id: str,
    formats: Sequence[str] = ("json", "docx", "pdf"),
    pdf_engine: str = "auto",
    settings: Any = None,
    thumbnails: bool = True,
) -> ProtocolExportResult:
    t0 = time.perf_counter()
    statuses = (
        {fid: st for fid, (st, _) in local_status_of(octx, settings).items()} if settings is not None else {}
    )
    protocol = build_protocol(
        octx,
        groups,
        findings,
        submission,
        run_id=run_id,
        local_status=statuses,
        versions=_versions(arts.run_dir),
    )
    errors = validation_errors("protocol", protocol)
    if errors:
        raise ContractValidationError("protocol", errors)
    result = ProtocolExportResult(protocol)
    result.timings["protocol.build"] = time.perf_counter() - t0
    oid = octx.object_id
    write_json(arts.path("PROTOCOL_JSON", object_id=oid), protocol, "protocol")
    result.written["protocol_json"] = arts.relative("PROTOCOL_JSON", object_id=oid)
    thumbs: dict[str, list[Any]] = {}
    if thumbnails and settings is not None and ({"docx", "pdf"} & set(formats)):
        t_th = time.perf_counter()
        try:
            from inspector_compare.protocol.thumbs import card_thumbnails, registry_locator

            thumbs = card_thumbnails(protocol, registry_locator(settings))
        except Exception as exc:  # thumbnails are a view: never fail the export
            result.warnings.append("EXPORT_FAILED")
            result.messages.append(
                f"Миниатюры карточек доказательств не сформированы: {type(exc).__name__}: {exc}"
            )
            log.warning("export.thumbnails_failed", extra={"detail": str(exc)})
        result.timings["protocol.thumbnails"] = time.perf_counter() - t_th
    if "docx" in formats:
        t1 = time.perf_counter()
        try:
            from inspector_compare.protocol.docx_render import render_docx

            render_docx(protocol, arts.path("PROTOCOL_DOCX", object_id=oid), thumbs)
            result.written["protocol_docx"] = arts.relative("PROTOCOL_DOCX", object_id=oid)
        except Exception as exc:
            result.warnings.append("EXPORT_FAILED")
            result.messages.append(f"Протокол DOCX не сформирован: {type(exc).__name__}: {exc}")
            log.warning("export.docx_failed", extra={"detail": str(exc)})
        result.timings["protocol.docx"] = time.perf_counter() - t1
    if "pdf" in formats and pdf_engine != "none":
        t2 = time.perf_counter()
        from inspector_compare.protocol.html_render import render_html
        from inspector_compare.protocol.pdf import PdfEngineError, render_pdf

        try:
            pdf = render_pdf(
                render_html(protocol, thumbs), arts.path("PROTOCOL_PDF", object_id=oid), engine=pdf_engine
            )
            result.written["protocol_pdf"] = arts.relative("PROTOCOL_PDF", object_id=oid)
            result.pdf_engine = pdf.engine
            if pdf.engine != "chromium":
                result.messages.append(
                    "PDF сформирован резервным движком PyMuPDF (цветные эмодзи заменены символами); "
                    "для вида по Приложению 2 установите Chromium/Chrome или используйте DOCX."
                )
        except PdfEngineError as exc:
            result.warnings.append("RENDERER_UNAVAILABLE")
            result.messages.append(
                f"Протокол PDF не сформирован: {exc}. Протокол доступен в форматах JSON и DOCX."
            )
        result.timings["protocol.pdf"] = time.perf_counter() - t2
    return result
