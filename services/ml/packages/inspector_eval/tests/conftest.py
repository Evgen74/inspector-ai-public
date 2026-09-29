"""Fixtures for inspector_eval tests.

Synthetic fixtures need no organizer data (object ids OBJ-A/OBJ-B train, OBJ-Z hidden; file ids outside
the hidden-object range). Tests on the real package are marked ``data`` and skip without it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from inspector_common.contracts.loader import contracts_dir
from inspector_common.settings import Settings
from inspector_eval.data import ScoringContext, SplitPolicy, load_context, read_jsonl

CRIT = "Критическое (приостановка работ)"
SUBST = "Существенное (предписание)"
FREE_CRIT = "Существенное (предписание) — требует утверждения"
WEIGHTS = {
    "finding_detection_f1": 60.0,
    "source_localization_exact_file_page": 15.0,
    "normalized_value_and_status_accuracy": 15.0,
    "document_integrity_and_split_handling": 10.0,
}
SPLIT_POLICY = {
    "TRAIN_PUBLIC": ["OBJ-A", "OBJ-B"],
    "TEST_HIDDEN": ["OBJ-Z"],
    "do_not_release": [],
    "excluded_file_ids": ["F0999"],
}


def _file(file_id: str, object_id: str, stage: str, pages: int | None, **extra: Any) -> dict[str, Any]:
    row = {
        "schema_version": "0.1.0",
        "file_id": file_id,
        "object_id": object_id,
        "corpus": "SYN",
        "dataset_role": "UNLABELED_POOL",
        "split": "TEST_HIDDEN" if object_id == "OBJ-Z" else "TRAIN_PUBLIC",
        "relative_path": f"syn/{file_id}.pdf",
        "extension": ".pdf",
        "size_bytes": 1,
        "sha256": f"{int(file_id[1:]):064x}",
        "stage": stage,
        "section": "OTHER",
        "pdf_pages": pages,
        "annotation_status": "UNLABELED",
        "exclusion_reason": None,
        "duplicate_group": None,
        "distribution_status": "INCLUDE",
        "label_visibility": "PUBLIC_TRAIN",
    }
    row.update(extra)
    return row


MANIFEST = [
    _file("F0001", "OBJ-A", "PD", 120),
    _file("F0002", "OBJ-A", "RD_ID_MIXED", 40),
    _file("F0003", "OBJ-A", "ID", 5),
    _file("F0004", "OBJ-A", "UNKNOWN", None, extension=".txt", annotation_status="GROUND_TRUTH_INDEX"),
    _file("F0005", "OBJ-B", "PD", 10),
    _file("F0006", "OBJ-B", "RD", 10),
    _file("F0007", "OBJ-A", "PD", 8, duplicate_group="dupgroup01"),
    _file("F0008", "OBJ-A", "PD", 8, duplicate_group="dupgroup01"),
    _file("F0900", "OBJ-Z", "PD", 10),
]


def _cat(code: str, pid: int, section: str, crit: str) -> dict[str, Any]:
    return {
        "parameter_id": pid,
        "parameter_code": code,
        "pd_section": section,
        "parameter_name": f"Параметр {pid}",
        "unit": None,
        "source_pd": None,
        "source_rd": None,
        "source_id": None,
        "trigger": None,
        "criticality": crit,
        "matrix_row": pid,
        "mapping_status": "SOURCE_MATRIX",
    }


CATALOG = [
    _cat("PZ-001", 1, "Раздел 1. ПЗ", CRIT),
    _cat("SPZU-025", 25, "Раздел 2. СПЗУ", SUBST),
    _cat("AR-040", 40, "Раздел 3. АР", CRIT),
    _cat("KR-055", 55, "Раздел 4. КР", CRIT),
    _cat("IOS4-077", 77, "Раздел 5. ИОС4", CRIT),
    _cat("IOS4-078", 78, "Раздел 5. ИОС4", CRIT),
    _cat("IOS4-079", 79, "Раздел 5. ИОС4", CRIT),
    _cat("PPM-104", 104, "Раздел 9. ППМ", CRIT),
]


def gold_row(
    check_id: str,
    group: str,
    code: str,
    location: str,
    *,
    object_id: str = "OBJ-A",
    label: str = "VIOLATION_PRESENT",
    status: str | None = None,
    criticality: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    pd_value: Any = "Предусмотрено",
    rd_value: Any = "Отсутствует",
    **extra: Any,
) -> dict[str, Any]:
    free = code.startswith("FREE-")
    crit = criticality or (
        FREE_CRIT if free else next(c["criticality"] for c in CATALOG if c["parameter_code"] == code)
    )
    if status is None:
        status = {"VIOLATION_PRESENT": "CRITICAL" if crit == CRIT else "WARNING", "NO_VIOLATION": "OK"}.get(
            label, "COMPARISON_IMPOSSIBLE"
        )
    row = {
        "check_id": check_id,
        "finding_group_id": group,
        "object_id": object_id,
        "split": "TEST_HIDDEN" if object_id == "OBJ-Z" else "TRAIN_PUBLIC",
        "matrix_scope": "FREE_SEARCH" if free else "MATRIX",
        "parameter_id": None,
        "parameter_code": code,
        "location_type": "OBJECT" if location == "OBJECT" else "ROOM",
        "location": location,
        "pd_value": pd_value,
        "rd_value": rd_value,
        "id_value": None,
        "comparison_result": "MISSING_DESIGN_ELEMENT",
        "violation_label": label,
        "protocol_status": status,
        "criticality": crit,
        "gold_status": "FINAL_GOLD_EXISTENCE",
        "score_eligible": True,
        "evidence": evidence
        if evidence is not None
        else [
            {"stage": "PD", "file_id": "F0001", "pdf_page_number": 10},
            {"stage": "RD", "file_id": "F0002", "pdf_page_number": 3},
        ],
    }
    row.update(extra)
    return row


def synthetic_gold() -> list[dict[str, Any]]:
    """OBJ-A: 4 positives in 3 groups + 1 approved-critical negative; OBJ-B: 1 positive."""
    return [
        gold_row("T-1", "G-1", "IOS4-079", "012"),
        gold_row("T-2", "G-2", "IOS4-078", "140"),
        gold_row("T-3", "G-2", "IOS4-078", "142"),
        gold_row("T-4", "G-3", "FREE-HEATING-001", "267"),
        gold_row("T-5", "G-4", "KR-055", "OBJECT", label="NO_VIOLATION", pd_value="B35", rd_value="B35"),
        gold_row(
            "T-6",
            "G-5",
            "AR-040",
            "1.109",
            object_id="OBJ-B",
            evidence=[
                {"stage": "PD", "file_id": "F0005", "pdf_page_number": 2},
                {"stage": "RD", "file_id": "F0006", "pdf_page_number": 4},
            ],
        ),
    ]


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


def as_submission(gold: list[dict[str, Any]], object_id: str) -> dict[str, Any]:
    checks = []
    for g in gold:
        if g["object_id"] != object_id:
            continue
        row = {k: copy.deepcopy(g[k]) for k in STRICT_FIELDS}
        row["evidence"] = [{k: e[k] for k in ("stage", "file_id", "pdf_page_number")} for e in g["evidence"]]
        checks.append(row)
    return {"object_id": object_id, "checks": checks}


@pytest.fixture()
def h() -> SimpleNamespace:
    """Helpers for test modules (conftest is not importable under --import-mode=importlib)."""
    return SimpleNamespace(
        CRIT=CRIT,
        SUBST=SUBST,
        FREE_CRIT=FREE_CRIT,
        WEIGHTS=WEIGHTS,
        SPLIT_POLICY=SPLIT_POLICY,
        MANIFEST=MANIFEST,
        CATALOG=CATALOG,
        gold_row=gold_row,
        synthetic_gold=synthetic_gold,
        as_submission=as_submission,
        write_fake_data_root=write_fake_data_root,
    )


@pytest.fixture()
def ctx() -> ScoringContext:
    return ScoringContext(
        manifest={r["file_id"]: r for r in MANIFEST},
        catalog={r["parameter_code"]: r for r in CATALOG},
        split_policy=SplitPolicy.from_dict(SPLIT_POLICY),
        weights=dict(WEIGHTS),
        gate_cap=59.0,
    )


@pytest.fixture()
def gold() -> list[dict[str, Any]]:
    return synthetic_gold()


def write_fake_data_root(root: Path, gold: list[dict[str, Any]] | None = None) -> Path:
    """A minimal organizer package on disk with the synthetic manifest, catalog and gold."""
    from inspector_common.paths import PACKAGE_DIR_NAME

    data = root / "data_utf8" / PACKAGE_DIR_NAME / "data"
    data.mkdir(parents=True)
    (data / "split_policy.json").write_text(json.dumps(SPLIT_POLICY), encoding="utf-8")
    (data / "document_manifest.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in MANIFEST) + "\n", encoding="utf-8"
    )
    (data / "parameter_catalog_132.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in CATALOG) + "\n", encoding="utf-8"
    )
    (data / "public_train_checks.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in (gold if gold is not None else synthetic_gold()))
        + "\n",
        encoding="utf-8",
    )
    (data / "scoring_summary_without_answers.json").write_text(
        json.dumps(
            {
                "weights_points": WEIGHTS,
                "critical_miss_gate": "При пропуске любой утверждённой критической контрольной точки итоговый балл ограничивается 59 из 100.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    schema = contracts_dir() / "schemas" / "submission.organizer.schema.json"
    (data / "submission_schema.json").write_bytes(schema.read_bytes())
    return root / "data_utf8"


@pytest.fixture()
def fake_data_root(tmp_path: Path) -> Path:
    return write_fake_data_root(tmp_path)


# ── real organizer data (marked `data`) ──────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def real_paths():
    paths = Settings().paths
    if not paths.has_package():
        pytest.skip(f"organizer data not found under {paths.data_root}")
    return paths


@pytest.fixture(scope="session")
def real_ctx(real_paths) -> ScoringContext:
    return load_context(real_paths)


@pytest.fixture(scope="session")
def real_gold(real_paths) -> list[dict[str, Any]]:
    return read_jsonl(real_paths.train_checks_path)
