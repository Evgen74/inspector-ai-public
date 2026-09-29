"""Submission status consistency (97 §2.6, enums.yaml `mappings`), shared by the exporter (AG-04)
and the scorer's integrity rule R13 (AG-10). Pure functions over the contract data.
"""

from __future__ import annotations

from collections.abc import Iterable

from inspector_common.contracts.loader import enum_mappings, load_enums


def allowed_protocol_statuses(violation_label: str) -> tuple[str, ...]:
    return tuple(enum_mappings()["protocol_status_by_label"][violation_label])


def is_consistent(violation_label: str, protocol_status: str) -> bool:
    """Integrity rule R13: protocol_status agrees with violation_label."""
    return protocol_status in allowed_protocol_statuses(violation_label)


def criticality_level_for_string(criticality: str | None) -> str | None:
    """Catalog criticality string → CriticalityLevel code (FREE variant → SUBSTANTIAL_ORDER)."""
    if criticality is None:
        return None
    if criticality == enum_mappings()["free_search"]["criticality_string"]:
        return str(enum_mappings()["free_search"]["criticality_level"])
    for value in load_enums()["CriticalityLevel"].values:
        if value.attrs.get("catalog_string") == criticality:
            return value.code
    raise ValueError(f"unknown criticality string: {criticality!r}")


def violation_protocol_status(criticality_level: str) -> str:
    """VIOLATION_PRESENT → CRITICAL for Критическое, WARNING otherwise (97 §2.6)."""
    return "CRITICAL" if criticality_level == "CRITICAL_SUSPEND" else "WARNING"


def missing_document_status(missing_stages: Iterable[str]) -> str:
    """MISSING_DOCUMENT → *_MISSING for the highest-precedence missing stage (RD > PD > ID)."""
    rule = enum_mappings()["missing_stage_status"]
    missing = set(missing_stages)
    for stage in rule["precedence"]:
        if stage in missing:
            return str(rule["status"][stage])
    raise ValueError("missing_document_status needs at least one missing stage")


def expected_protocol_status(
    violation_label: str, criticality_level: str | None = None, missing_stages: Iterable[str] = ()
) -> str:
    """The single protocol_status the contract prescribes for a label."""
    if violation_label == "VIOLATION_PRESENT":
        if criticality_level is None:
            raise ValueError("VIOLATION_PRESENT needs a criticality level")
        return violation_protocol_status(criticality_level)
    if violation_label == "NO_VIOLATION":
        return "OK"
    if violation_label == "MISSING_DOCUMENT":
        return missing_document_status(missing_stages)
    if violation_label == "COMPARISON_IMPOSSIBLE":
        return "COMPARISON_IMPOSSIBLE"
    raise ValueError(f"unknown violation_label {violation_label!r}")
