from __future__ import annotations

import pytest

from inspector_common.contracts import loader, selfcheck


@pytest.mark.parametrize(
    "check",
    [
        selfcheck.check_generated,
        selfcheck.check_schemas,
        selfcheck.check_vendored,
        selfcheck.check_examples,
        selfcheck.check_enums,
        selfcheck.check_codes,
        selfcheck.check_errors,
        selfcheck.check_run_layout,
        selfcheck.check_table_columns,
        selfcheck.check_rbac,
        selfcheck.check_openapi,
    ],
    ids=lambda f: f.__name__,
)
def test_contract_selfcheck(check) -> None:
    assert check() == []


def test_expected_schemas_exist() -> None:
    required = {
        "common",
        "enums",
        "evidence_ref",
        "extracted_value",
        "finding",
        "page_tokens",
        "problem",
        "protocol",
        "finding_group",
        "decision",
        "layout_artifacts",
        "table_artifacts",
        "run_artifacts",
        "tokens_index",
        "submission_sidecar",
        "run_manifest",
        "submission.extended",
        "submission.organizer",
        "submission.strict",
        "manifest_row",
        "catalog_row",
        "gold_check",
        "gold_group",
    }
    assert required <= set(loader.schema_names())


def test_every_schema_with_properties_has_examples() -> None:
    root = selfcheck.examples_root()
    for name in loader.schema_names():
        if name in {"common", "enums"}:
            continue
        assert list((root / name / "valid").glob("*.json")), f"{name}: no valid example"
        assert list((root / name / "invalid").glob("*.json")), f"{name}: no invalid example"


def test_plan_v2_enums_present() -> None:
    enums = loader.load_enums()
    for name in (
        "ViolationLabel",
        "ProtocolParamStatus",
        "CriticalityLevel",
        "ParameterMappingStatus",
        "ComparisonResult",
        "LocationType",
        "MatrixScope",
        "ManifestStage",
        "LocalFileStatus",
        "TextSource",
        "ArchiveMemberRole",
        "PageBasis",
        "DocumentStatus",
        "ProcessStatus",
        "FindingStatus",
        "CompletenessStatus",
        "InspectorStatus",
    ):
        assert name in enums, name
    assert "SUBMISSION_SCORE" in enums["EvalKind"].codes
    assert "STAMP_PAGE" in enums["PageClass"].codes
    assert enums["InspectorStatus"].canonical("CONFIRMED") == "CONFIRMED_VIOLATION"
    assert enums["InspectorStatus"].canonical("REJECTED") == "NEGATIVE_VERIFIED"


def test_submission_enums_match_organizer_schema() -> None:
    organizer = loader.load_schema("submission.organizer")
    item = organizer["properties"]["checks"]["items"]["properties"]
    enums = loader.load_enums()
    assert list(enums["ViolationLabel"].codes) == item["violation_label"]["enum"]
    in_submission = [v.code for v in enums["ProtocolParamStatus"].values if v.attrs.get("in_submission")]
    assert sorted(in_submission) == sorted(item["protocol_status"]["enum"])
    assert list(enums["DocStage"].codes) == item["evidence"]["items"]["properties"]["stage"]["enum"]


def test_validate_raises_with_readable_errors() -> None:
    with pytest.raises(loader.ContractValidationError) as info:
        loader.validate("evidence_ref", {"stage": "XX", "file_id": "F0001"})
    assert "pdf_page_number" in str(info.value)


def test_rbac_matrix_follows_90_3_10(monkeypatch: pytest.MonkeyPatch) -> None:
    """rbac.yaml: the single INSPECTOR super-role holds every permission with scope ALL, reauth actions are the 09 §3.3.1 ones;
    the checker catches unknown roles and scopes."""
    raw = loader.load_rbac()
    grants = {p["code"]: p["grants"] for p in raw["permissions"]}
    roles = set(loader.load_enums()["Role"].codes)
    assert roles == {"INSPECTOR"}
    assert all(g == {"INSPECTOR": "ALL"} for g in grants.values())
    assert {p["code"] for p in raw["permissions"] if p.get("reauth")} == {
        "protocol.finalize",
        "protocol.unfinalize",
        "users.manage",
        "model.publish.approve",
        "model.rollback",
    }
    broken = {
        **raw,
        "permissions": [
            *raw["permissions"],
            {"code": "x.y", "label_ru": "t", "grants": {"JANITOR": "ALL"}},
            {"code": "Bad", "label_ru": "t", "grants": {"INSPECTOR": "SOMETIMES"}},
            {"code": "finding.decide", "label_ru": "t", "grants": {"INSPECTOR": "ALL"}},
        ],
    }
    monkeypatch.setattr(loader, "load_rbac", lambda: broken)
    problems = selfcheck.check_rbac()
    assert any("unknown Role JANITOR" in p for p in problems)
    assert any("unknown PermissionScope SOMETIMES" in p for p in problems)
    assert any("bad permission code 'Bad'" in p for p in problems)
    assert any("duplicate permission finding.decide" in p for p in problems)
