from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from inspector_common.contracts import loader, models
from inspector_common.contracts.selfcheck import examples_root


def _resolve_pointer(doc: dict[str, Any], pointer: str) -> dict[str, Any]:
    node: Any = doc
    for part in [p for p in pointer.split("/") if p]:
        node = node[part]
    return node


@pytest.mark.parametrize(
    ("model", "schema", "pointer"),
    models.MODEL_SCHEMAS,
    ids=[f"{m.__name__}@{s}{p}" for m, s, p in models.MODEL_SCHEMAS],
)
def test_model_fields_match_schema_properties(model: type[BaseModel], schema: str, pointer: str) -> None:
    node = _resolve_pointer(loader.load_schema(schema), pointer)
    schema_props = set(node.get("properties", {}))
    model_fields = set(model.model_fields)
    assert model_fields == schema_props, (
        f"only in model: {model_fields - schema_props}; only in schema: {schema_props - model_fields}"
    )
    required = set(node.get("required", []))
    model_required = {name for name, f in model.model_fields.items() if f.is_required()}
    assert model_required <= required, (
        f"model requires fields the schema does not: {model_required - required}"
    )


_TOP_MODELS: dict[str, type[BaseModel]] = {
    "evidence_ref": models.EvidenceRef,
    "finding": models.Finding,
    "page_tokens": models.PageTokens,
    "extracted_value": models.ExtractedValue,
    "run_manifest": models.RunManifest,
    "submission.extended": models.Submission,
    "manifest_row": models.ManifestRow,
    "catalog_row": models.CatalogRow,
    "gold_check": models.GoldCheck,
    "gold_group": models.GoldGroup,
    "protocol": models.Protocol,
    "finding_group": models.FindingGroup,
    "decision": models.Decision,
    "layout_artifacts": models.LayoutArtifacts,
    "table_artifacts": models.TableArtifacts,
    "run_artifacts": models.RunArtifacts,
    "tokens_index": models.TokensIndex,
    "submission_sidecar": models.SubmissionSidecar,
}


def _examples(kind: str) -> list[tuple[str, str, Any]]:
    out = []
    for name in _TOP_MODELS:
        for file in sorted((examples_root() / name / kind).glob("*.json")):
            out.append((name, file.stem, json.loads(file.read_text(encoding="utf-8"))))
    return out


@pytest.mark.parametrize(
    ("schema", "stem", "doc"), _examples("valid"), ids=lambda v: v if isinstance(v, str) else ""
)
def test_valid_examples_parse_and_round_trip(schema: str, stem: str, doc: Any) -> None:
    model = _TOP_MODELS[schema].model_validate(doc)
    dumped = model.model_dump(mode="json", exclude_unset=True)
    assert loader.is_valid(schema, dumped), loader.validation_errors(schema, dumped)


@pytest.mark.parametrize(
    ("schema", "stem", "doc"), _examples("invalid"), ids=lambda v: v if isinstance(v, str) else ""
)
def test_invalid_examples_rejected_by_models(schema: str, stem: str, doc: Any) -> None:
    with pytest.raises(ValidationError):
        _TOP_MODELS[schema].model_validate(doc)


def test_submission_to_strict_validates_against_strict_and_organizer() -> None:
    doc = json.loads(
        (examples_root() / "submission.extended" / "valid" / "tyumen_three_rows.json").read_text(
            encoding="utf-8"
        )
    )
    strict = models.Submission.model_validate(doc).to_strict()
    assert loader.validation_errors("submission.strict", strict) == []
    assert loader.validation_errors("submission.organizer", strict) == []
    assert set(strict["checks"][0]) == set(models.SubmissionCheck.STRICT_FIELDS)
