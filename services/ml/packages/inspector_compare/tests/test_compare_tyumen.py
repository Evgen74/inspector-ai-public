"""Тюменская 5 (TRAIN_PUBLIC gold seed) on the AG-04 development fixture: the must-pass case of 95 §3.8.

The fixture is hand-made from 95 page facts (not recognition output); these tests check that, given such layout
artifacts, compare → export reproduces the organizers' 10 checks exactly (codes, exact room tokens, anchor pages,
value texts, statuses) and scores 100 with inspector-score. Marked ``data``: they need the organizer package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import LayoutArtifacts, TableArtifacts
from inspector_compare.config import default_config
from inspector_compare.engine import compare_object
from inspector_compare.export.submission import build_submission, integrity_problems, schema_problems
from inspector_compare.fixtures import get_fixture
from inspector_compare.objectctx import InputDirs, context_from_registry

pytestmark = pytest.mark.data

TYUMEN = "OBJ-TYUMENSKAYA-5-GOLD-SEED"


@pytest.fixture(scope="module")
def registry(data_paths: Any):
    from inspector_registry.manifest import Registry

    return Registry.load(data_paths)


@pytest.fixture(scope="module")
def tyumen(registry: Any) -> dict[str, Any]:
    fx = get_fixture("tyumen")
    ctx = context_from_registry(
        TYUMEN, registry, InputDirs(fx.layout_dir, fx.tables_dir, None, None, "fixture:tyumen")
    )
    result = compare_object(ctx, default_config(), run_id="t-tyumen")
    return {"ctx": ctx, "result": result, "submission": build_submission(TYUMEN, result.findings)}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_fixture_layouts_follow_the_contract_and_the_manifest(registry: Any) -> None:
    fx = get_fixture("tyumen")
    for path in sorted(fx.layout_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert validation_errors("layout_artifacts", doc) == []
        LayoutArtifacts.model_validate(doc)
        assert doc["file_sha256"] == registry.get(doc["file_id"]).sha256
        assert doc["object_id"] == TYUMEN
    assert fx.tables_dir is not None
    tables = sorted(fx.tables_dir.glob("*.json"))
    assert [p.stem for p in tables] == ["F0201", "F0202"]
    for path in tables:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert validation_errors("table_artifacts", doc) == []
        TableArtifacts.model_validate(doc)
        assert doc["file_sha256"] == registry.get(doc["file_id"]).sha256
        assert doc["object_id"] == TYUMEN


def test_groups_match_the_organizer_groups(tyumen: dict[str, Any], data_paths: Any) -> None:
    gold = _jsonl(data_paths.train_groups_path)
    ours = {
        (g["parameter_code"], g["comparison_result"], tuple(g["locations"])): g
        for g in tyumen["result"].groups
    }
    assert len(ours) == len(gold) == 4
    for g in gold:
        key = (g["parameter_code"], g["difference_type"], tuple(g["locations"]))
        assert key in ours, key
        mine = ours[key]
        gold_pages = {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in g["evidence"]}
        anchor_pages = {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in mine["anchor_evidence"]}
        assert anchor_pages == gold_pages, key
        assert mine["parameter_mapping_status"] == g["parameter_mapping_status"]
        assert mine["criticality"] == g["criticality"]
    cfg_group = ours[("IOS4-078", "CONFIGURATION_MISMATCH", ("147", "198", "314"))]
    rd_314 = [e for e in cfg_group["location_pages"]["314"] if e["stage"] == "RD"]
    assert [(e["file_id"], e["pdf_page_number"], e["is_anchor"]) for e in rd_314] == [("F0201", 20, False)]


def test_checks_match_the_gold_rows(tyumen: dict[str, Any], data_paths: Any) -> None:
    gold = {(c["parameter_code"], c["location"]): c for c in _jsonl(data_paths.train_checks_path)}
    rows = {
        (c["parameter_code"], c["location"]): c
        for c in tyumen["submission"].strict["checks"]
        if c["violation_label"] == "VIOLATION_PRESENT"
    }
    assert set(rows) == set(gold)
    for key, g in gold.items():
        r = rows[key]
        for field in (
            "pd_value",
            "rd_value",
            "id_value",
            "violation_label",
            "protocol_status",
            "criticality",
        ):
            assert r[field] == g[field], (key, field)
        assert [(e["stage"], e["file_id"], e["pdf_page_number"]) for e in r["evidence"]] == [
            (e["stage"], e["file_id"], e["pdf_page_number"]) for e in g["evidence"]
        ]


def test_export_passes_schemas_and_integrity_and_scores_100(
    tyumen: dict[str, Any], settings: Any, data_paths: Any
) -> None:
    from inspector_eval.config import DEFAULT_CONFIG
    from inspector_eval.data import load_context, read_jsonl
    from inspector_eval.scoring import score_object

    sub = tyumen["submission"]
    assert schema_problems(sub) == []
    problems, report = integrity_problems(sub, settings, "TRAIN_PUBLIC")
    assert problems == [] and report is not None and report["share"] == 1.0
    sctx = load_context(data_paths)
    gold = [g for g in read_jsonl(data_paths.train_checks_path) if g["object_id"] == TYUMEN]
    for doc in (sub.extended, sub.strict):
        score = score_object(gold, doc, sctx, DEFAULT_CONFIG, object_id=TYUMEN)
        assert score.total == pytest.approx(100.0)
        assert not score.gate_triggered


def test_no_hedges_and_one_free_group_on_the_gold(tyumen: dict[str, Any]) -> None:
    groups = tyumen["result"].groups
    assert not [g for g in groups if g.get("hedge_of_group_id")]
    assert [g["parameter_code"] for g in groups if g["matrix_scope"] == "FREE_SEARCH"] == ["FREE-HEATING-001"]
    context = {(c["family"], c["location"], c["outcome"]) for c in tyumen["result"].trace["context"]}
    assert (
        "VENT_EXHAUST_BRANCH",
        "141",
        "ELEMENT_ADDED",
    ) in context  # branches moved to 141: context (95 §3.7)


def test_fixture_pd_tokens_are_in_the_pdf_text_layer(registry: Any, data_paths: Any) -> None:
    """The PD half of the fixture is checkable against the real text layer (PD tags are text, 95 §3.3)."""
    import pymupdf

    f = registry.get("F0171")
    path = data_paths.document_path(f.relative_path)
    if not path.is_file():
        pytest.skip("F0171 not on disk")
    with pymupdf.open(path) as doc:
        text = {p: doc[p - 1].get_text() for p in (88, 99, 104)}
    for token in ("В2.10", "В2.4", "В3.2", "142", "314", "198"):
        assert token in text[88], token
    for token in ("П17", "П2.1", "012"):
        assert token in text[104], token
    folded = text[99].casefold().replace("ё", "е")
    assert "267" in folded and "теплый пол" in folded


def test_room_names_come_from_the_explications(tyumen: dict[str, Any]) -> None:
    """The explication tables name the gold rooms in the rationale (evidence cards); continuation lines of a split
    name («моделирования и конструирования») are not printed as names."""
    by_code = {(g["parameter_code"], g["comparison_result"]): g for g in tyumen["result"].groups}
    assert "пом. 147 (Лаборантская тип АВ)" in by_code[("IOS4-078", "CONFIGURATION_MISMATCH")]["rationale"]
    assert "пом. 012 (Венткамера)" in by_code[("IOS4-079", "CONFIGURATION_MISMATCH")]["rationale"]
    warm = by_code[("FREE-HEATING-001", "MISSING_DESIGN_ELEMENT")]["rationale"]
    assert "пом. 267 (Раздевальная для МГН)" in warm and "пом. 270 (Санузел с душем для МГН)" in warm
    assert "пом. 140:" in by_code[("IOS4-078", "MISSING_DESIGN_ELEMENT")]["rationale"]


def test_fixture_tables_and_title_blocks_are_in_the_pdf_text_layer(registry: Any, data_paths: Any) -> None:
    """Every explication row of the tables fixture and the PD title-block cells are printed in the text layer."""
    import pymupdf

    fx = get_fixture("tyumen")
    assert fx.tables_dir is not None

    def page_text(file_id: str, page: int) -> str:
        path = data_paths.document_path(registry.get(file_id).relative_path)
        if not path.is_file():
            pytest.skip(f"{file_id} not on disk")
        with pymupdf.open(path) as doc:
            return " ".join(doc[page - 1].get_text().split())

    checked = 0
    for path in sorted(fx.tables_dir.glob("*.json")):
        doc = TableArtifacts.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for table in doc.tables:
            text = page_text(doc.file_id, table.pages[0])
            for row in table.rows:
                parts = [str(c.raw) for c in row.cells.values() if c.raw]
                for part in parts:
                    assert " ".join(part.split()) in text, (doc.file_id, table.pages[0], part)
                checked += 1
    assert checked == 25
    layout = LayoutArtifacts.model_validate(
        json.loads((fx.layout_dir / "F0171.json").read_text(encoding="utf-8"))
    )
    for tb in layout.title_blocks or []:
        text = page_text("F0171", tb.pdf_page_number)
        assert tb.document_code and tb.document_code in text
        assert tb.object_name and tb.object_name in text
