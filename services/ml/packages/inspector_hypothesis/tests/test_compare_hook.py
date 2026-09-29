"""The hook AG-04's compare calls: ObjectContext in, contract FindingGroup dicts out, never raising."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from types import SimpleNamespace

from inspector_common.contracts.loader import validation_errors
from inspector_common.runlayout import RunLayout
from inspector_hypothesis import compare_hook
from inspector_hypothesis.testing import OBJECT_ID, SHA, layout, title_block, tyumen_warm_floor


@dataclass
class _FileInfo:  # the fields of inspector_compare.objectctx.FileInfo the hook reads
    file_id: str
    stage: str | None
    section: str
    pdf_pages: int | None
    sha256: str
    manifest_stage: str
    citable: bool = True
    is_pdf: bool = True

    @property
    def name(self) -> str:
        return f"{self.file_id}.pdf"


def _tokens(p) -> dict:
    tokens = [
        {
            "id": wi,
            "text": p.words[wi].text,
            "bbox": list(p.words[wi].bbox),
            "conf": 0.99,
            "source": "OCR",
            "line_id": li,
        }
        for li, idxs in enumerate(p.lines)
        for wi in idxs
    ]
    return {
        "file_id": p.file_id,
        "file_sha256": SHA[p.file_id],
        "page_no": p.page_no,
        "page_basis": "PDF_NATIVE",
        "page": {"width_pt": p.width_pt, "height_pt": p.height_pt, "rotate": 0},
        "pipeline_version": "test",
        "tokens": tokens,
    }


def _context(tmp_path, *, with_run_dir: bool = True):
    sc = tyumen_warm_floor()
    run_dir = tmp_path / "runs" / "hook-run"
    rl = RunLayout(run_dir)
    for (fid, pno), p in sc.pages._pages.items():
        with gzip.open(rl.ensure_parent("PAGE_TOKENS", file_id=fid, page=pno), "wt", encoding="utf-8") as fh:
            json.dump(_tokens(p), fh, ensure_ascii=False)
    files = {
        fid: _FileInfo(
            fid, d.stage, d.section, d.pages_total, SHA[fid], "RD_ID_MIXED" if d.stage == "RD" else "PD"
        )
        for fid, d in sc.documents.items()
    }
    layouts = {"F0202": layout("F0202", "RD", 20, [title_block(17, "АНО/150321/1-РД-ОВ2.1", 4)])}
    ctx = SimpleNamespace(
        object_id=OBJECT_ID, files=files, layouts=layouts, tables={}, values=[], layout_source=None
    )
    if with_run_dir:
        ctx.run_dir = run_dir
    return ctx, run_dir


def test_hook_returns_valid_bound_free_groups(tmp_path):
    compare_hook.clear_cache()
    ctx, _ = _context(tmp_path)
    groups = compare_hook.free_finding_groups(
        ctx=ctx, observations=None, config=SimpleNamespace(max_free_groups=5)
    )
    assert [g["parameter_code"] for g in groups] == ["FREE-HEATING-001"]
    g = groups[0]
    assert validation_errors("finding_group", g) == []  # exactly what AG-04 checks
    assert g["matrix_scope"] == "FREE_SEARCH" and g["evidence_bind_status"] == "BOUND"
    assert g["locations"] == ["267", "270", "271", "272"]
    assert [
        (a["file_id"], a["pdf_page_number"], a.get("document_sheet_number")) for a in g["anchor_evidence"]
    ] == [
        ("F0171", 99, None),
        ("F0202", 17, 4),
    ]


def test_hook_takes_the_run_dir_argument_and_caches_the_full_result(tmp_path):
    compare_hook.clear_cache()
    ctx, run_dir = _context(tmp_path, with_run_dir=False)
    assert compare_hook.free_finding_groups(ctx=ctx) == []  # no run directory known: nothing, no exception
    groups = compare_hook.free_finding_groups(ctx=ctx, run_dir=run_dir)
    assert len(groups) == 1
    r1 = compare_hook.run_for_context(ctx=ctx, run_dir=run_dir)
    r2 = compare_hook.run_for_context(ctx=ctx, run_dir=run_dir)
    assert r1 is r2 and r1.section6_rows(1)[0].parameter_code == "FREE-HEATING-001"


def test_hook_never_raises(tmp_path):
    broken = SimpleNamespace(object_id=OBJECT_ID, files=None, run_dir=tmp_path / "missing")
    assert compare_hook.free_finding_groups(ctx=broken) == []
    assert compare_hook.free_finding_groups(ctx=object()) == []


def _with_double_count(ctx):
    from inspector_hypothesis.testing import (
        TYUMEN_P18_ROOMS,
        TYUMEN_P18_SUBZONE,
        explication,
        table_artifacts,
    )

    t = explication(
        "F0201-p18-expl",
        TYUMEN_P18_ROOMS,
        ("Итого", "1079.9"),
        subzones=TYUMEN_P18_SUBZONE,
        page_no=18,
    )
    ctx.tables = {"F0201": table_artifacts("F0201", "RD", [t])}
    return ctx


def test_protocol_suspicions_continue_after_the_rendered_free_groups(tmp_path):
    from inspector_common.contracts.models import HypothesisRow, SuspicionRow

    compare_hook.clear_cache()
    ctx, _ = _context(tmp_path)
    _with_double_count(ctx)
    groups = compare_hook.free_finding_groups(ctx=ctx, config=SimpleNamespace(max_free_groups=5))
    assert len(compare_hook._CACHE) == 1
    extra = compare_hook.protocol_suspicions(
        ctx=ctx, rendered_free_groups=groups, start_no=2, first_card_no=5
    )
    assert len(compare_hook._CACHE) == 1  # the protocol reuses compare's run
    assert extra["error"] is None
    [row] = extra["section6_rows"]
    assert (row["no"], row["card_ref"], row["method"]) == (2, "Б.5", "LOGICAL_ANALYSIS")
    assert "повторно включает площадь подзон" in row["description"] and "parameter_code" not in row
    SuspicionRow.model_validate(row)
    [a5] = extra["a5_rows"]
    HypothesisRow.model_validate(a5)
    assert a5["card_ref"] == "Б.5" and "ГОСТ 21.501-2018" in a5["normative_base"]
    [rec] = extra["suspicions"]
    assert rec["rule_code"] == "HR-LOG-011" and rec["rd_reference"].endswith("стр.18")
    assert rec["exported"] is False and (rec["card_ref"], rec["section6_no"]) == ("Б.5", 2)


def test_a_free_group_the_builder_did_not_keep_becomes_a_plain_suspicion_row(tmp_path):
    compare_hook.clear_cache()
    ctx, _ = _context(tmp_path)
    _with_double_count(ctx)
    extra = compare_hook.protocol_suspicions(ctx=ctx, rendered_free_groups=[])
    rows = extra["section6_rows"]
    assert [r["method"] for r in rows] == ["SEMANTIC_DISSONANCE", "LOGICAL_ANALYSIS"]
    assert [r["no"] for r in rows] == [1, 2] and [r["card_ref"] for r in rows] == ["Б.1", "Б.2"]
    assert "parameter_code" not in rows[0] and "finding_group_id" not in rows[0]
    assert rows[0]["description"].endswith("(пом. 267, 270, 271, 272)")


def test_suspicion_records_are_valid_against_the_proposed_contract(tmp_path):
    from inspector_hypothesis.suspicion import suspicion_schema_errors

    compare_hook.clear_cache()
    ctx, run_dir = _context(tmp_path)
    _with_double_count(ctx)
    records = compare_hook.suspicion_records(ctx=ctx, run_dir=run_dir)
    assert [r["rule_code"] for r in records] == ["HR-SEM-005", "HR-LOG-011"]
    assert [r["suspicion_id"] for r in records] == [1, 2]
    for r in records:
        assert suspicion_schema_errors(r) == []
        assert r["finding_status"] == "SUSPICION" and r["inspector_status"] == "PENDING"


def test_protocol_helpers_never_raise(tmp_path):
    compare_hook.clear_cache()
    extra = compare_hook.protocol_suspicions(ctx=object())  # not a context at all: an error, no exception
    assert extra["section6_rows"] == [] and extra["a5_rows"] == [] and extra["error"]
    assert compare_hook.suspicion_records(ctx=object()) == []
    empty = SimpleNamespace(object_id=OBJECT_ID, files=None, run_dir=tmp_path / "missing")
    extra = compare_hook.protocol_suspicions(
        ctx=empty
    )  # an object with nothing recognised: no rows, no error
    assert extra == {"section6_rows": [], "a5_rows": [], "suspicions": [], "error": None}
