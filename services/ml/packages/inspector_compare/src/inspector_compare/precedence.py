"""The 132-row precedence (97 §2.6; 93 §3.3; enums.yaml ``mappings.parameter_precedence``).

Per catalog parameter p, with R(p) the stages of its sufficient sets and A the stages whose documents of the
required disciplines are in the object's manifest (citable PDFs):

1. no sufficient set of R(p) is available (≤ 1 required stage) → COMPARISON_IMPOSSIBLE;
2. a pairwise violation wins over a missing third stage → VIOLATION_PRESENT (the violation rows);
3. a required stage is missing → MISSING_DOCUMENT with RD_MISSING > PD_MISSING > ID_MISSING;
4. a required stage is present in the manifest but not readable here (missing on disk) → COMPARISON_IMPOSSIBLE
   (technical; a local file status is never MISSING_DOCUMENT, 97 §2.12);
5. a comparator verified the parameter without a violation → NO_VIOLATION / OK;
6. otherwise the stages are present but no value was compared (fragment-level MISSING_EVIDENCE) →
   ``CompareConfig.unverified_status`` (COMPARISON_IMPOSSIBLE by default, 97 §2.6 status mapping).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from inspector_common.contracts.status import missing_document_status
from inspector_compare.disciplines import required_marks
from inspector_compare.objectctx import ObjectContext

STAGES = ("PD", "RD", "ID")
MISSING_PRECEDENCE = ("RD", "PD", "ID")


@dataclass(slots=True)
class ParamOutcome:
    code: str
    param_id: int
    section: str
    required: tuple[str, ...]
    available: tuple[str, ...]
    readable: tuple[str, ...]
    missing: tuple[str, ...]
    stage_files: dict[str, list[str]]
    violated: bool
    verified: bool
    violation_label: str
    protocol_status: str
    completeness_status: str
    completeness_basis: str | None
    document_status: str
    rule: int
    bucket: str  # ProtocolSummaryRow partition key
    reason_ru: str
    missing_marks: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def is_negative(self) -> bool:
        return self.violation_label != "VIOLATION_PRESENT"


def document_status(available: Iterable[str]) -> str:
    """DocumentStatus by the gold grammar: <stages>_AVAILABLE[_<stages>_MISSING] (all three stages)."""
    avail = [s for s in STAGES if s in set(available)]
    missing = [s for s in STAGES if s not in set(available)]
    if not avail:
        return "PD_RD_ID_MISSING"
    head = "_".join(avail) + "_AVAILABLE"
    return head + ("_" + "_".join(missing) + "_MISSING" if missing else "")


def _stage_files(ctx: ObjectContext, stage: str, marks: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """(declared, readable) citable PDF files of ``stage`` that cover one of ``marks``."""
    declared: list[str] = []
    readable: list[str] = []
    for f in sorted(ctx.files.values(), key=lambda x: x.file_id):
        if f.stage != stage or not f.citable or not f.is_pdf:
            continue
        if not set(f.marks) & set(marks):
            continue
        declared.append(f.file_id)
        if f.local_status != "MISSING_ON_DISK":
            readable.append(f.file_id)
    return declared, readable


_STAGE_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}


def evaluate_param(
    ctx: ObjectContext,
    spec: Any,
    *,
    violated: bool,
    verified: bool,
    unverified_status: str = "COMPARISON_IMPOSSIBLE",
    value_stages: Iterable[str] = (),
) -> ParamOutcome:
    """Apply the precedence to one parameter (``spec``: inspector_common.params.ParamSpec).

    ``value_stages``: stages whose extracted value was actually compared (labelled ПЗ values found in a file of
    another discipline than the parameter's source): the value itself proves the stage is present and readable."""
    data: Mapping[str, Any] = spec.data
    sets = [tuple(s) for s in (data.get("stages_required") or {}).get("sufficient_sets") or [["PD", "RD"]]]
    required = tuple(s for s in STAGES if any(s in ss for ss in sets))
    sources = data.get("source_docs") or {}
    stage_files: dict[str, list[str]] = {}
    available: list[str] = []
    readable: list[str] = []
    missing_marks: dict[str, tuple[str, ...]] = {}
    for stage in STAGES:
        marks = required_marks(spec.section, sources.get(stage.lower()))
        if stage == "ID":
            # ИД sources carry document kinds, not disciplines: the parameter's own section decides.
            marks = required_marks(spec.section, None)
        declared, ok = _stage_files(ctx, stage, marks)
        stage_files[stage] = declared
        if declared or stage in value_stages:
            available.append(stage)
        else:
            missing_marks[stage] = marks
        if ok or (not declared and stage in value_stages):
            readable.append(stage)
    missing = tuple(s for s in MISSING_PRECEDENCE if s in required and s not in available)
    doc_status = document_status(available)
    satisfied = any(set(ss) <= set(available) for ss in sets)

    def out(
        rule: int, label: str, status: str, comp: str, basis: str | None, bucket: str, reason: str
    ) -> ParamOutcome:
        return ParamOutcome(
            code=spec.code,
            param_id=spec.param_id,
            section=spec.section,
            required=required,
            available=tuple(available),
            readable=tuple(readable),
            missing=missing,
            stage_files=stage_files,
            violated=violated,
            verified=verified,
            violation_label=label,
            protocol_status=status,
            completeness_status=comp,
            completeness_basis=basis,
            document_status=doc_status,
            rule=rule,
            bucket=bucket,
            reason_ru=reason,
            missing_marks=missing_marks,
        )

    missing_ru = ", ".join(_STAGE_RU[s] for s in missing)
    if not getattr(spec, "is_active", True):
        return out(
            0,
            "NO_VIOLATION",
            "OK",
            "NOT_APPLICABLE",
            "PARAM_DEACTIVATED",
            "NOT_APPLICABLE",
            "Параметр отключён в версии Матрицы",
        )
    if not satisfied:
        bucket = "NOT_CHECKED_NO_ID" if missing and set(missing) == {"ID"} else "NOT_CHECKED_NO_PD_RD"
        reason = (
            f"Для сравнения недостаточно стадий: отсутствует {missing_ru}"
            if missing
            else "Для сравнения недостаточно стадий документации"
        )
        return out(
            1,
            "COMPARISON_IMPOSSIBLE",
            "COMPARISON_IMPOSSIBLE",
            "MISSING_EVIDENCE",
            "MANDATORY_SOURCE_MISSING",
            bucket,
            reason,
        )
    if violated:
        return out(2, "VIOLATION_PRESENT", "", "COMPLETE", None, "CHECKED_OK", "Выявлено расхождение")
    if missing:
        status = missing_document_status(missing)
        bucket = "NOT_CHECKED_NO_ID" if status == "ID_MISSING" else "NOT_CHECKED_NO_PD_RD"
        return out(
            3,
            "MISSING_DOCUMENT",
            status,
            "MISSING_EVIDENCE",
            "MANDATORY_SOURCE_MISSING",
            bucket,
            f"Отсутствует {missing_ru}",
        )
    unreadable = [s for s in available if s in required and s not in readable]
    if unreadable:
        return out(
            4,
            "COMPARISON_IMPOSSIBLE",
            "COMPARISON_IMPOSSIBLE",
            "NOT_COMPARABLE",
            "FILE_NOT_PROCESSED",
            "NOT_LOADED_TECH_ERRORS",
            "Файлы стадии " + ", ".join(_STAGE_RU[s] for s in unreadable) + " не найдены на диске",
        )
    if verified:
        return out(5, "NO_VIOLATION", "OK", "COMPLETE", None, "CHECKED_OK", "Расхождений не выявлено")
    if unverified_status == "NO_VIOLATION":
        return out(6, "NO_VIOLATION", "OK", "COMPLETE", None, "CHECKED_OK", "Расхождений не выявлено")
    return out(
        6,
        "COMPARISON_IMPOSSIBLE",
        "COMPARISON_IMPOSSIBLE",
        "NOT_COMPARABLE",
        "VALUE_ABSTAINED",
        "NOT_LOADED_TECH_ERRORS",
        "Документы стадий представлены, значение параметра не извлечено",
    )


def evaluate_all(
    ctx: ObjectContext,
    params: Iterable[Any],
    *,
    violated: set[str],
    verified: set[str],
    unverified_status: str = "COMPARISON_IMPOSSIBLE",
    value_stages: Mapping[str, Iterable[str]] | None = None,
) -> list[ParamOutcome]:
    return [
        evaluate_param(
            ctx,
            spec,
            violated=spec.code in violated,
            verified=spec.code in verified,
            unverified_status=unverified_status,
            value_stages=(value_stages or {}).get(spec.code, ()),
        )
        for spec in sorted(params, key=lambda s: s.param_id)
    ]
