"""The 132-row precedence (97 §2.6) on synthetic stage availability."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from inspector_common.params import load_params
from inspector_compare.precedence import document_status, evaluate_param


def _ctx(tmp_path: Path, syn: Any, extra_rows: list[dict[str, Any]] | None = None):
    rows = syn.default_rows() + (extra_rows or [])
    return syn.make_context(tmp_path, [], rows=rows)


def test_document_status_grammar() -> None:
    assert document_status(["PD", "RD"]) == "PD_RD_AVAILABLE_ID_MISSING"
    assert document_status(["PD", "RD", "ID"]) == "PD_RD_ID_AVAILABLE"
    assert document_status(["RD"]) == "RD_AVAILABLE_PD_ID_MISSING"
    assert document_status([]) == "PD_RD_ID_MISSING"


def test_rule1_single_stage_is_comparison_impossible(tmp_path: Path, syn: Any) -> None:
    o = evaluate_param(_ctx(tmp_path, syn), load_params().get("KR-058"), violated=False, verified=False)
    assert (o.rule, o.violation_label, o.protocol_status) == (
        1,
        "COMPARISON_IMPOSSIBLE",
        "COMPARISON_IMPOSSIBLE",
    )
    assert o.available == ("PD",) and o.bucket == "NOT_CHECKED_NO_PD_RD"
    assert o.completeness_basis == "MANDATORY_SOURCE_MISSING"


def test_rule2_violation_wins_over_missing_third_stage(tmp_path: Path, syn: Any) -> None:
    o = evaluate_param(_ctx(tmp_path, syn), load_params().get("IOS4-078"), violated=True, verified=True)
    assert (o.rule, o.violation_label, o.bucket) == (2, "VIOLATION_PRESENT", "CHECKED_OK")


def test_rule3_missing_id_is_missing_document(tmp_path: Path, syn: Any) -> None:
    vk = [
        syn.manifest_row("F9010", "PD", "VK", "syn/ПД/5.2 Водоснабжение/Том 5.2.1.pdf"),
        syn.manifest_row("F9011", "RD", "VK", "syn/РД/SYN-РД-ВК.pdf"),
    ]
    o = evaluate_param(_ctx(tmp_path, syn, vk), load_params().get("IOS2-071"), violated=False, verified=True)
    assert (o.rule, o.violation_label, o.protocol_status) == (3, "MISSING_DOCUMENT", "ID_MISSING")
    assert o.document_status == "PD_RD_AVAILABLE_ID_MISSING"
    assert o.bucket == "NOT_CHECKED_NO_ID"


def test_rules5_6_verified_and_unverified(tmp_path: Path, syn: Any) -> None:
    ctx = _ctx(tmp_path, syn)
    spec = load_params().get("IOS4-076")  # ОВ: PD F9001, RD F9002/F9003, ID F9005 (АОСР ОВ)
    ok = evaluate_param(ctx, spec, violated=False, verified=True)
    assert (ok.rule, ok.violation_label, ok.protocol_status) == (5, "NO_VIOLATION", "OK")
    assert ok.available == ("PD", "RD", "ID")
    unknown = evaluate_param(ctx, spec, violated=False, verified=False)
    assert (unknown.rule, unknown.violation_label, unknown.completeness_basis) == (
        6,
        "COMPARISON_IMPOSSIBLE",
        "VALUE_ABSTAINED",
    )
    assert unknown.bucket == "NOT_LOADED_TECH_ERRORS"
    lenient = evaluate_param(ctx, spec, violated=False, verified=False, unverified_status="NO_VIOLATION")
    assert lenient.violation_label == "NO_VIOLATION"


def test_rule4_missing_on_disk_is_never_missing_document(tmp_path: Path, syn: Any) -> None:
    ctx = _ctx(tmp_path, syn)
    ctx.files = {
        k: (dataclasses.replace(v, local_status="MISSING_ON_DISK") if k in ("F9002", "F9003") else v)
        for k, v in ctx.files.items()
    }
    o = evaluate_param(ctx, load_params().get("IOS4-076"), violated=False, verified=True)
    assert (o.rule, o.violation_label, o.completeness_basis) == (
        4,
        "COMPARISON_IMPOSSIBLE",
        "FILE_NOT_PROCESSED",
    )
    assert "RD" in o.available and "RD" not in o.readable


def test_non_citable_files_do_not_count(tmp_path: Path, syn: Any) -> None:
    ctx = _ctx(tmp_path, syn)
    ctx.files = {
        k: (dataclasses.replace(v, citable=False) if k == "F9002" else v) for k, v in ctx.files.items()
    }
    o = evaluate_param(ctx, load_params().get("IOS4-076"), violated=False, verified=True)
    assert o.stage_files["RD"] == ["F9003"]
