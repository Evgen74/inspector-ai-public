"""Errors backed by the catalogue in packages/contracts/errors.yaml (RFC 9457 in the web mode).

raise InspectorError("FILE_MISSING_ON_DISK", file_id="F0015", relative_path="…")
err.detail  → «Файл F0015 из манифеста не найден на диске (…); …»
err.problem(instance="/api/v1/…", request_id="…")  → application/problem+json body
"""

from __future__ import annotations

import datetime as dt
import string
from typing import Any

from inspector_common.contracts.loader import load_errors


class _Missing(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def catalog_entry(code: str) -> dict[str, Any]:
    try:
        return load_errors()[code]
    except KeyError:
        raise KeyError(f"error code {code!r} is not in packages/contracts/errors.yaml") from None


def render(template: str, details: dict[str, Any]) -> str:
    """Fill ``{name}`` placeholders; unknown placeholders are left visible rather than raising."""
    return string.Formatter().vformat(template, (), _Missing(details))


class InspectorError(Exception):
    """An error with a catalogue code. Unknown codes are a programming error (KeyError)."""

    def __init__(self, code: str, /, **details: Any) -> None:
        self.code = code
        self.entry = catalog_entry(code)
        self.details = details
        super().__init__(f"{code}: {self.detail}")

    @property
    def title(self) -> str:
        return str(self.entry["title_ru"])

    @property
    def detail(self) -> str:
        return render(str(self.entry["detail_ru"]), self.details)

    @property
    def hint(self) -> str | None:
        hint = self.entry.get("hint_ru")
        return render(str(hint), self.details) if hint else None

    @property
    def http_status(self) -> int | None:
        return self.entry.get("http")

    @property
    def retryable(self) -> bool:
        return bool(self.entry.get("retryable", False))

    @property
    def severity(self) -> str:
        return str(self.entry["severity"])

    def item(self) -> dict[str, Any]:
        """Per-item problem subset {code, title, detail, details} (10 §3.2)."""
        return {"code": self.code, "title": self.title, "detail": self.detail, "details": self.details}

    def problem(self, *, instance: str, request_id: str, status: int | None = None) -> dict[str, Any]:
        """Full RFC 9457 body (schemas/problem.schema.json)."""
        http = status or self.http_status or 500
        slug = self.code.lower().replace("_", "-")
        body: dict[str, Any] = {
            "type": f"/problems/{slug}",
            "title": self.title,
            "status": http,
            "detail": self.detail,
            "instance": f"{instance}#{request_id}",
            "code": self.code,
            "request_id": request_id,
            "timestamp": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "retryable": self.retryable,
        }
        if self.details:
            body["details"] = self.details
        return body
