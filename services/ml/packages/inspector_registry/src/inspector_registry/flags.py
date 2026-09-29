"""Integrity flags: catalogue-backed findings about inputs (never violations of the object).

Every flag carries a code from packages/contracts/errors.yaml (contracts are law), the Russian
title/detail rendered from the catalogue, the catalogue details, and where it applies (file id,
archive member). Codes the catalogue lacks are listed in the package README as proposals.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from inspector_common.errors import InspectorError


@dataclass(frozen=True, slots=True)
class IntegrityFlag:
    code: str
    severity: str
    title: str
    detail: str
    details: dict[str, Any] = field(default_factory=dict)
    file_id: str | None = None
    member: str | None = None
    note_ru: str | None = None  # extra context that the catalogue template has no slot for

    @classmethod
    def make(
        cls,
        code: str,
        details: dict[str, Any] | None = None,
        /,
        *,
        file_id: str | None = None,
        member: str | None = None,
        note_ru: str | None = None,
    ) -> IntegrityFlag:
        """``details`` fill the catalogue template; ``file_id``/``member`` say where the flag applies."""
        details = dict(details or {})
        err = InspectorError(code, **details)  # KeyError for a code outside the catalogue
        return cls(
            code=code,
            severity=err.severity,
            title=err.title,
            detail=err.detail,
            details=details,
            file_id=file_id,
            member=member,
            note_ru=note_ru,
        )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "details": self.details,
            "file_id": self.file_id,
            "member": self.member,
        }
        if self.note_ru:
            out["note_ru"] = self.note_ru
        return out


def count_codes(flags: Iterable[IntegrityFlag]) -> dict[str, int]:
    return dict(sorted(Counter(f.code for f in flags).items()))
