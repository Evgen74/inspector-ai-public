"""Loading a run directory: PageTokens, layout, tables and values through RunLayout paths; documents from the registry."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from inspector_common.contracts.models import PageTokens
from inspector_common.runlayout import RunLayout
from inspector_hypothesis import HypothesisInputs, RunPageSource, page_text_from_tokens, run_hypotheses
from inspector_hypothesis.inputs import PageText
from inspector_hypothesis.testing import (
    OBJECT_ID,
    SHA,
    layout,
    table_artifacts,
    title_block,
    typed_table,
    tyumen_warm_floor,
)


def _tokens_doc(p: PageText, sha: str, *, quality: str = "OK", warnings=None) -> dict:
    tokens, lines = [], []
    for li, idxs in enumerate(p.lines):
        ids = []
        for wi in idxs:
            w = p.words[wi]
            tokens.append(
                {
                    "id": wi,
                    "text": w.text,
                    "bbox": list(w.bbox),
                    "conf": 0.99,
                    "source": "TEXT_LAYER",
                    "line_id": li,
                    "quality_flag": "OK",
                }
            )
            ids.append(wi)
        lines.append(
            {
                "id": li,
                "text": " ".join(p.words[i].text for i in idxs),
                "bbox": [0, 0, 1, 1],
                "token_ids": ids,
            }
        )
    doc = {
        "file_id": p.file_id,
        "file_sha256": sha,
        "page_no": p.page_no,
        "page_basis": "PDF_NATIVE",
        "page": {"width_pt": p.width_pt, "height_pt": p.height_pt, "rotate": 0},
        "page_class": "VECTOR",
        "quality_flag": quality,
        "pipeline_version": "test",
        "tokens": tokens,
        "lines": lines,
    }
    if warnings:
        doc["warnings"] = warnings
    return PageTokens.model_validate(doc).dump()  # contract-valid


def _write_run(tmp_path: Path, scenario) -> Path:
    run_dir = tmp_path / "runs" / "t-run"
    rl = RunLayout(run_dir)
    for (fid, pno), p in scenario.pages._pages.items():
        path = rl.ensure_parent("PAGE_TOKENS", file_id=fid, page=pno)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(_tokens_doc(p, SHA[fid]), fh, ensure_ascii=False)
    lp = rl.ensure_parent("LAYOUT", file_id="F0202")
    lp.write_text(
        layout(
            "F0202", "RD", 20, [title_block(17, "АНО/150321/1-РД-ОВ2.1", 4, [("3", "01.03.2024")])]
        ).model_dump_json(),
        encoding="utf-8",
    )
    tp = rl.ensure_parent("TABLES", file_id="F0171")
    t = typed_table("TEP", "TEP", [{"indicator": "Площадь участка", "value": "10000"}])
    tp.write_text(table_artifacts("F0171", "PD", [t]).model_dump_json(), encoding="utf-8")
    return run_dir


def test_from_run_reads_contract_artifacts_and_finds_the_free_group(tmp_path):
    sc = tyumen_warm_floor()
    run_dir = _write_run(tmp_path, sc)
    inputs = HypothesisInputs.from_run(run_dir, OBJECT_ID, documents=sc.documents)
    assert inputs.run_id == "t-run" and inputs.problems == []
    assert inputs.documents["F0202"].document_code == "АНО/150321/1-РД-ОВ2.1"  # from the title blocks
    assert inputs.sheet_number("F0202", 17) == 4
    assert "F0171" in inputs.tables
    r = run_hypotheses(inputs)
    [g] = r.free_groups
    assert g.parameter_code == "FREE-HEATING-001"
    assert [(a.file_id, a.pdf_page_number, a.document_sheet_number) for a in g.anchor_evidence] == [
        ("F0171", 99, None),
        ("F0202", 17, 4),
    ]
    assert r.suspicions[0].rd_reference == "АНО/150321/1-РД-ОВ2.1, л.4, стр.17"  # ТЗ §9.5 reference format
    assert g.run_id == "t-run"


def test_run_page_source_marks_abstained_and_failed_pages_as_unread(tmp_path):
    sc = tyumen_warm_floor()
    run_dir = _write_run(tmp_path, sc)
    rl = RunLayout(run_dir)
    bad = rl.path("PAGE_TOKENS", file_id="F0202", page=5)
    with gzip.open(bad, "wt", encoding="utf-8") as fh:
        json.dump(_tokens_doc(sc.pages.page("F0202", 5), SHA["F0202"], quality="ABSTAIN"), fh)
    corrupt = rl.path("PAGE_TOKENS", file_id="F0202", page=6)
    corrupt.write_bytes(b"not gzip")
    src = RunPageSource(run_dir)
    assert src.page("F0202", 5).usable is False
    assert src.page("F0202", 6) is None and src.failed
    inputs = HypothesisInputs.from_run(run_dir, OBJECT_ID, documents=sc.documents)
    assert inputs.coverage(sc.documents["F0202"]) == (18, 20)
    r = run_hypotheses(inputs)
    assert (
        r.free_candidates[0].absence == "UNKNOWN"
    )  # the heating RD holding the anchor page is not fully read
    assert r.free_groups == []


def test_page_text_from_tokens_orders_lines_and_drops_abstained_tokens():
    doc = {
        "file_id": "F1",
        "page_no": 1,
        "page": {"width_pt": 595, "height_pt": 842, "rotate": 0},
        "tokens": [
            {"id": 0, "text": "второй", "bbox": [0.1, 0.5, 0.2, 0.51], "line_id": 1},
            {"id": 1, "text": "первый", "bbox": [0.1, 0.1, 0.2, 0.11], "line_id": 0},
            {
                "id": 2,
                "text": "мусор",
                "bbox": [0.3, 0.1, 0.4, 0.11],
                "line_id": 0,
                "quality_flag": "ABSTAIN",
            },
        ],
    }
    p = page_text_from_tokens(doc)
    assert [p.line_text(i) for i in range(len(p.lines))] == ["первый", "второй"]


@dataclass
class _File:
    file_id: str
    stage: str
    section: str
    pdf_pages: int
    sha256: str
    relative_path: str
    extension: str = ".pdf"

    @property
    def name(self) -> str:
        return self.relative_path.rsplit("/", 1)[-1]

    @property
    def is_pdf(self) -> bool:
        return self.extension == ".pdf"


class _Registry:
    def __init__(self, files):
        self._files = files

    def files(self, object_id):
        return self._files

    def is_citable(self, file_id):
        return file_id != "F0194"


def test_documents_from_the_registry_resolve_mixed_stages_from_page_one(tmp_path):
    sc = tyumen_warm_floor()
    run_dir = _write_run(tmp_path, sc)
    reg = _Registry(
        [
            _File("F0171", "PD", "OV", 177, SHA["F0171"], "ПД/5.4 Отопление/V2_Том 5.4.2 ОВ.pdf"),
            _File(
                "F0202",
                "RD_ID_MIXED",
                "OV",
                20,
                SHA["F0202"],
                "Рабочая и исполнительная документация/Полные разделы/АНО-150321-1-РД-ОВ2.1_изм. 3_в1.pdf",
            ),
            _File("F0194", "UNKNOWN", "OTHER", 0, "0" * 64, "Перечень нарушений.txt", ".txt"),
        ]
    )
    inputs = HypothesisInputs.from_run(run_dir, OBJECT_ID, registry=reg)
    assert set(inputs.documents) == {"F0171", "F0202"}  # PDFs only
    assert inputs.documents["F0171"].stage == "PD"
    assert inputs.documents["F0202"].stage in (
        "RD",
        None,
    )  # resolved from generic signals, never guessed as ID here
    assert inputs.documents["F0202"].manifest_stage == "RD_ID_MIXED"
