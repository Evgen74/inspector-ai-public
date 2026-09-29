"""Submission exporter (full + strict) and the sidecar, on a synthetic compare result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.params import load_params
from inspector_compare.engine import compare_object
from inspector_compare.export.sidecar import build_sidecar
from inspector_compare.export.submission import (
    STRICT_FIELDS,
    build_submission,
    local_problems,
    schema_problems,
    select_rows,
)


def _result(tmp_path: Path, syn: Any, cfg: Any):
    ctx = syn.make_context(tmp_path, syn.ventilation_layouts())
    return ctx, compare_object(ctx, cfg, run_id="t-run", config_hash="c" * 64)


def test_submission_rows_order_fields_and_evidence(tmp_path: Path, syn: Any, cfg: Any) -> None:
    ctx, result = _result(tmp_path, syn, cfg)
    sub = build_submission(ctx.object_id, result.findings)
    checks = sub.strict["checks"]
    labels = [c["violation_label"] for c in checks]
    first_negative = labels.index(next(lab for lab in labels if lab != "VIOLATION_PRESENT"))
    assert set(labels[:first_negative]) == {"VIOLATION_PRESENT"}
    assert "VIOLATION_PRESENT" not in labels[first_negative:]
    ids = [load_params().get(c["parameter_code"]).param_id for c in checks[first_negative:]]
    assert ids == sorted(ids)
    for c in checks:
        assert tuple(c) == STRICT_FIELDS
        stages = [e["stage"] for e in c["evidence"]]
        assert stages == sorted(stages, key=["PD", "RD", "ID"].index)
        for stage in set(stages):
            assert stages.count(stage) <= 2
    ext = sub.extended["checks"][0]
    assert {"finding_id", "comparison_result", "location_type", "document_status", "matrix_scope"} <= set(ext)
    assert ext["document_status"] == "PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK"
    assert all("document_sheet_number" in e for e in ext["evidence"])
    assert schema_problems(sub) == []
    assert local_problems(sub, [p.code for p in load_params()], expect_all_params=True) == []
    assert sub.stats["violations"] == 4 and sub.stats["checks"] == len(checks)  # 101, 102, 202, 203


def test_negatives_switch_and_local_gate(tmp_path: Path, syn: Any, cfg: Any) -> None:
    ctx, result = _result(tmp_path, syn, cfg)
    only = build_submission(ctx.object_id, result.findings, emit_negatives="none")
    assert {c["violation_label"] for c in only.strict["checks"]} == {"VIOLATION_PRESENT"}
    assert len(select_rows(result.findings, "none")) == 4
    problems = local_problems(only, [p.code for p in load_params()], expect_all_params=True)
    assert problems and "нет строк по параметрам" in problems[0]
    dup = build_submission(ctx.object_id, result.findings + result.violation_findings[:1])
    assert any("повторяющийся ключ" in p for p in local_problems(dup, [], expect_all_params=False))


def test_sidecar_is_a_one_object_run_manifest(tmp_path: Path, syn: Any, cfg: Any, settings: Any) -> None:
    ctx, result = _result(tmp_path, syn, cfg)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_context.export.json").write_text(
        json.dumps(
            {
                "command": "inspector-batch export --object OBJ-SYN-1",
                "versions": {"pipeline_version": "0.1.0+m0", "contract_version": "0.1.0"},
                "inputs": {
                    "manifest_sha256": "a" * 64,
                    "catalog_sha256": "b" * 64,
                    "submission_schema_sha256": "c" * 64,
                },
                "host": {"platform": "test", "machine": "arm64", "python": "3.12", "cpu_count": 12},
            }
        ),
        encoding="utf-8",
    )
    import dataclasses

    ctx.files = {
        k: (dataclasses.replace(v, local_status="MISSING_ON_DISK") if k == "F9003" else v)
        for k, v in ctx.files.items()
    }
    sub = build_submission(ctx.object_id, result.findings)
    doc = build_sidecar(
        ctx=ctx,
        run_id="t-run",
        run_dir=run_dir,
        settings=settings,
        compare_config_hash="c" * 64,
        export_config_hash="e" * 64,
        artifacts={"submission": "submission/OBJ-SYN-1.json"},
        checks_total=len(sub.strict["checks"]),
        started_at="2026-09-28T00:00:00Z",
        timings={"export": 0.5},
        freeze_tag=None,
        warnings=["RENDERER_UNAVAILABLE"],
        matrix_version="1.1.0",
    )
    assert validation_errors("submission_sidecar", doc) == []
    obj = doc["objects"][0]
    assert obj["input_manifest_hash"] == ctx.input_manifest_hash
    assert obj["missing_on_disk"] == ["F9003"] and obj["files_present"] == obj["files_total"] - 1
    assert doc["stage_config_hashes"] == {"export": "e" * 64, "compare": "c" * 64}
    assert doc["versions"]["engine_versions"]["inspector_compare"]
    assert {f["file_id"] for f in doc["files"]} == set(ctx.files)
    assert next(f for f in doc["files"] if f["file_id"] == "F9002")["stage_resolved"] == "RD"


def test_deactivated_parameter_still_exports_a_valid_row(
    tmp_path: Path, syn: Any, cfg: Any, monkeypatch: Any
) -> None:
    """Module 8: a parameter switched off in /admin/normative keeps its row (NOT_APPLICABLE), the 132 stay complete."""
    path = tmp_path / "matrix_overrides.json"
    path.write_text(
        json.dumps(
            {"matrix_version": "1.1.1+ovr.2", "overrides": [{"param_code": "IOS4-078", "is_active": False}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("INSPECTOR_MATRIX_OVERRIDES", str(path))
    ctx, result = _result(tmp_path / "run", syn, cfg)
    sub = build_submission(ctx.object_id, result.findings)
    assert schema_problems(sub) == []
    assert local_problems(sub, [p.code for p in load_params()], expect_all_params=True) == []
    rows = [c for c in sub.extended["checks"] if c["parameter_code"] == "IOS4-078"]
    assert len(rows) == 1 and rows[0]["violation_label"] == "NO_VIOLATION"
    assert sub.stats["violations"] == 0  # all four synthetic violations belong to the deactivated IOS4-078
