"""Findings → the organizer submission (93 §3.1, §3.9; 97 §2.5), gated by the contract schemas and by
inspector-score's integrity rules R1–R14 before anything is written.

Row order: violations in protocol order (hedge twins after their primary), then the OBJECT rows by parameter id.
Evidence: ordered PD, RD, ID; 1–2 pages per stage; the group's anchor page first (93 §2.8).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from inspector_common.contracts.loader import validation_errors

STRICT_FIELDS = (
    "parameter_code",
    "location",
    "pd_value",
    "rd_value",
    "id_value",
    "violation_label",
    "protocol_status",
    "criticality",
    "evidence",
)
EXTRA_FIELDS = (
    "comparison_result",
    "location_type",
    "document_status",
    "matrix_scope",
    "parameter_mapping_status",
    "finding_id",
    "confidence",
)
STAGE_ORDER = {"PD": 0, "RD": 1, "ID": 2}
MAX_PAGES_PER_STAGE = 2


class SubmissionRejected(RuntimeError):
    """The export failed its gate; nothing was written. ``problems`` are Russian, user-facing."""

    def __init__(self, object_id: str, problems: list[str]):
        self.object_id = object_id
        self.problems = problems
        super().__init__(f"{object_id}: " + "; ".join(problems[:5]))


@dataclass(slots=True)
class Submission:
    object_id: str
    extended: dict[str, Any]
    strict: dict[str, Any]
    stats: dict[str, Any] = field(default_factory=dict)
    integrity: dict[str, Any] | None = None


def _evidence(items: Iterable[Mapping[str, Any]], *, extended: bool) -> list[dict[str, Any]]:
    """PD, RD, ID order; anchors first within a stage; ≤ 2 pages per stage; no duplicates."""
    rows = sorted(
        (e for e in items if e.get("stage") in STAGE_ORDER),
        key=lambda e: (STAGE_ORDER[e["stage"]], 0 if e.get("is_anchor") else 1),
    )
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    per_stage: Counter[str] = Counter()
    for e in rows:
        key = (e["stage"], e["file_id"], int(e["pdf_page_number"]))
        if key in seen or per_stage[e["stage"]] >= MAX_PAGES_PER_STAGE:
            continue
        seen.add(key)
        per_stage[e["stage"]] += 1
        item: dict[str, Any] = {
            "stage": e["stage"],
            "file_id": e["file_id"],
            "pdf_page_number": int(e["pdf_page_number"]),
        }
        if extended and e.get("document_sheet_number") is not None:
            item["document_sheet_number"] = e["document_sheet_number"]
        out.append(item)
    return out


def _row(finding: Mapping[str, Any], *, extended: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "parameter_code": finding["parameter_code"],
        "location": finding["location"],
        "pd_value": finding.get("pd_value"),
        "rd_value": finding.get("rd_value"),
        "id_value": finding.get("id_value"),
        "violation_label": finding["violation_label"],
        "protocol_status": finding["protocol_status"],
        "criticality": finding.get("criticality"),
        "evidence": _evidence(finding.get("evidence") or [], extended=extended),
    }
    if extended:
        for key in EXTRA_FIELDS:
            value = finding.get(key)
            if value is not None:
                row[key] = value
    return row


def select_rows(findings: list[Mapping[str, Any]], emit_negatives: str = "all") -> list[Mapping[str, Any]]:
    """Violations (file order = protocol order), then OBJECT rows by parameter id (when negatives are on)."""
    violations = [f for f in findings if f["violation_label"] == "VIOLATION_PRESENT"]
    negatives = [f for f in findings if f["violation_label"] != "VIOLATION_PRESENT"]
    if emit_negatives == "none":
        negatives = []
    negatives = sorted(
        negatives, key=lambda f: (f.get("parameter_id") or 999, f["parameter_code"], f["location"])
    )
    return violations + negatives


def build_submission(
    object_id: str, findings: list[Mapping[str, Any]], *, emit_negatives: str = "all"
) -> Submission:
    rows = select_rows(findings, emit_negatives)
    extended = {"object_id": object_id, "checks": [_row(f, extended=True) for f in rows]}
    strict = {"object_id": object_id, "checks": [_row(f, extended=False) for f in rows]}
    labels = Counter(r["violation_label"] for r in strict["checks"])
    stats = {
        "checks": len(strict["checks"]),
        "by_label": dict(sorted(labels.items())),
        "violations": labels.get("VIOLATION_PRESENT", 0),
        "free": sum(1 for r in strict["checks"] if str(r["parameter_code"]).startswith("FREE-")),
        "parameters": len(
            {
                r["parameter_code"]
                for r in strict["checks"]
                if not str(r["parameter_code"]).startswith("FREE-")
            }
        ),
    }
    return Submission(object_id, extended, strict, stats)


def schema_problems(sub: Submission) -> list[str]:
    problems: list[str] = []
    for name, doc in (
        ("submission.organizer", sub.extended),
        ("submission.extended", sub.extended),
        ("submission.organizer", sub.strict),
        ("submission.strict", sub.strict),
    ):
        problems += [f"схема {name}: {e}" for e in validation_errors(name, doc)[:10]]
    return problems


def local_problems(sub: Submission, catalog_codes: Iterable[str], *, expect_all_params: bool) -> list[str]:
    """Invariants the schemas cannot express: unique keys (R10), 132-row coverage."""
    problems: list[str] = []
    keys = Counter((c["parameter_code"], c["location"]) for c in sub.strict["checks"])
    problems += [f"повторяющийся ключ {k}" for k, n in keys.items() if n > 1]
    if expect_all_params:
        covered = {c["parameter_code"] for c in sub.strict["checks"]}
        missing = sorted(set(catalog_codes) - covered)
        if missing:
            problems.append(
                f"нет строк по параметрам: {', '.join(missing[:10])}" + (" …" if len(missing) > 10 else "")
            )
    return problems


def integrity_problems(
    sub: Submission, settings: Any, split: str | None
) -> tuple[list[str], dict[str, Any] | None]:
    """inspector-score integrity rules R1–R14 on the strict document (the scorer's own implementation)."""
    try:
        from inspector_eval.config import DEFAULT_CONFIG
        from inspector_eval.data import InputError, load_context
        from inspector_eval.validation import check_integrity, validate_schemas
    except ImportError:  # pragma: no cover - inspector-eval is a declared dependency
        return [], None
    try:
        sctx = load_context(settings.paths)
    except (InputError, OSError) as exc:
        return [f"контекст оценщика недоступен: {exc}"], None
    cfg = DEFAULT_CONFIG.replace(expected_split=split or DEFAULT_CONFIG.expected_split)
    report = check_integrity(sub.strict, sctx, cfg, schema=validate_schemas(sub.strict))
    problems = []
    for rule_id in report.failed:
        rule = report.rules[rule_id]
        for v in rule.violations[:5]:
            problems.append(f"{rule_id}: {v.detail_ru}")
    return problems, report.as_dict()
