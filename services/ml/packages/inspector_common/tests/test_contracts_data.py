"""Organizer package vs our contracts (fast, needs data; format-level only on the hidden object)."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from inspector_common.contracts import codes, loader, models
from inspector_common.hashing import sha256_file

pytestmark = pytest.mark.data


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_package_checksums_match_sha256sums(data_paths) -> None:
    expected = {}
    for line in data_paths.package_sha256sums_path.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        expected[rel] = digest
    for rel in (
        "data/document_manifest.jsonl",
        "data/parameter_catalog_132.jsonl",
        "data/submission_schema.json",
        "data/split_policy.json",
        "data/public_train_checks.jsonl",
        "data/public_train_finding_groups.jsonl",
    ):
        assert sha256_file(data_paths.package_root / rel) == expected[rel], rel


def test_vendored_submission_schema_is_the_package_file(data_paths) -> None:
    ours = loader.contracts_dir() / "schemas" / "submission.organizer.schema.json"
    assert sha256_file(ours) == sha256_file(data_paths.submission_schema_path)


def test_manifest_rows_satisfy_contract(data_paths) -> None:
    """Format check over all 416 rows (includes the hidden object's rows: format only, 97 §2.17)."""
    rows = _jsonl(data_paths.manifest_path)
    assert len(rows) == 416
    errors = {r["file_id"]: loader.validation_errors("manifest_row", r) for r in rows}
    assert {k: v for k, v in errors.items() if v} == {}
    for row in rows:
        models.ManifestRow.model_validate(row)
    assert len({r["file_id"] for r in rows}) == 416
    enums = loader.load_enums()
    for field, enum in (
        ("section", "ManifestSection"),
        ("dataset_role", "DatasetRole"),
        ("annotation_status", "AnnotationStatus"),
        ("distribution_status", "DistributionStatus"),
        ("label_visibility", "LabelVisibility"),
    ):
        unknown = set(Counter(r[field] for r in rows)) - set(enums[enum].codes)
        assert not unknown, f"new organizer values for open enum {enum}: {unknown} (add them to enums.yaml)"


def test_excluded_ids_are_not_in_manifest(data_paths) -> None:
    policy = json.loads(data_paths.split_policy_path.read_text(encoding="utf-8"))
    ids = {r["file_id"] for r in _jsonl(data_paths.manifest_path)}
    assert set(policy["excluded_file_ids"]) == {"F0149", "F0418"}
    assert not ids & set(policy["excluded_file_ids"])


def test_catalog_rows_and_code_grammar(data_paths) -> None:
    rows = _jsonl(data_paths.catalog_path)
    assert len(rows) == 132
    prefix_sections = {p.latin: p.section for p in codes.prefixes()}
    for row in rows:
        assert loader.validation_errors("catalog_row", row) == []
        models.CatalogRow.model_validate(row)
        assert codes.canonical_code(row["parameter_id"]) == row["parameter_code"]
        assert prefix_sections[row["parameter_code"].split("-")[0]] == row["pd_section"]
    counts = Counter(r["criticality"] for r in rows)
    assert counts == {"Критическое (приостановка работ)": 106, "Существенное (предписание)": 26}


def test_train_gold_satisfies_contract(data_paths) -> None:
    checks = _jsonl(data_paths.train_checks_path)
    groups = _jsonl(data_paths.train_groups_path)
    assert len(checks) == 10 and len(groups) == 4
    for row in checks:
        assert loader.validation_errors("gold_check", row) == []
        gold = models.GoldCheck.model_validate(row)
        assert (
            loader.load_enums()["InspectorStatus"].canonical(gold.inspector_status) == "CONFIRMED_VIOLATION"
        )
    for row in groups:
        assert loader.validation_errors("gold_group", row) == []
        models.GoldGroup.model_validate(row)


def test_gold_as_submission_validates_everywhere(data_paths) -> None:
    """Project the train gold to a submission: it must satisfy organizer, extended and strict schemas."""
    checks = _jsonl(data_paths.train_checks_path)
    extras = ("comparison_result", "location_type", "document_status", "matrix_scope")
    sub = {"object_id": checks[0]["object_id"], "checks": []}
    for c in checks:
        row = {
            k: c[k]
            for k in (
                "parameter_code",
                "location",
                "pd_value",
                "rd_value",
                "id_value",
                "violation_label",
                "protocol_status",
                "criticality",
            )
        }
        row["evidence"] = [
            {k: e[k] for k in ("stage", "file_id", "pdf_page_number", "document_sheet_number")}
            for e in c["evidence"]
        ]
        row.update({k: c[k] for k in extras})
        sub["checks"].append(row)
    assert loader.validation_errors("submission.organizer", sub) == []
    assert loader.validation_errors("submission.extended", sub) == []
    strict = models.Submission.model_validate(sub).to_strict()
    assert loader.validation_errors("submission.strict", strict) == []
