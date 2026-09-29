"""`inspector-batch layout` end to end on a synthetic organizer package (no real data, no OCR models)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from inspector_common.contracts import loader
from inspector_common.contracts.models import LayoutArtifacts
from inspector_common.paths import DOCUMENTS_DIR_PARTS, PACKAGE_DIR_NAME
from inspector_layout.codes import CodeRegistry
from inspector_layout.pagescan import ScanOptions
from inspector_layout.pipeline import FileTask, assemble_object, chunk_tasks, scan_files, write_layout
from inspector_layout.testing import StampSpec, make_stamp_pdf

OBJ = "OBJ-TRAIN-A"
EXON = "https://exon.exonproject.ru/document-status/87cc1a16-51a4-4f99-bb70-35afc204d773/1/wd/{}"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _rd_sheets(path: Path) -> Path:
    specs = [StampSpec(sheet=str(s), code="АНО/150321/1-РД-ОВ2.1", change_rows=()) for s in (1, 2, 3, 3, 5)]
    return make_stamp_pdf(path, specs, qr_payloads=[EXON.format(p) for p in range(1, 6)])


def _id_extract(path: Path) -> Path:
    return make_stamp_pdf(
        path,
        [StampSpec(sheet="3", code="АНО/150321/1-РД-ОВ2.1", change_rows=())],
        qr_payloads=[EXON.format(3)],
    )


@pytest.fixture
def package(tmp_path: Path) -> Path:
    """Organizer-like data root: split policy, manifest and three PDFs of one TRAIN object."""
    root = tmp_path / "data_utf8"
    data = root / PACKAGE_DIR_NAME / "data"
    data.mkdir(parents=True)
    docs = root.joinpath(*DOCUMENTS_DIR_PARTS) / "Рабочая"
    docs.mkdir(parents=True)
    files = {
        "F9001": (_rd_sheets(docs / "АНО-150321-1-РД-ОВ2.1_изм. 3.pdf"), "RD"),
        "F9002": (_id_extract(docs / "Исполнительный чертеж.pdf"), "ID"),
        "F9003": (make_stamp_pdf(docs / "Пустой.pdf", [None, None]), "PD"),
    }
    rows = []
    for fid, (p, stage) in files.items():
        rows.append(
            {
                "file_id": fid,
                "object_id": OBJ,
                "relative_path": str(p.relative_to(root.joinpath(*DOCUMENTS_DIR_PARTS))),
                "extension": ".pdf",
                "sha256": _sha(p),
                "stage": stage,
                "pdf_pages": None,
            }
        )
    (data / "document_manifest.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    (data / "split_policy.json").write_text(
        json.dumps({"TRAIN_PUBLIC": [OBJ], "TEST_HIDDEN": ["OBJ-HIDDEN-Z"], "excluded_file_ids": []}),
        encoding="utf-8",
    )
    for name in ("parameter_catalog_132.jsonl", "submission_schema.json"):
        (data / name).write_text("{}\n", encoding="utf-8")
    return root


def _tasks(package: Path) -> list[FileTask]:
    base = package.joinpath(*DOCUMENTS_DIR_PARTS)
    rows = [
        json.loads(x)
        for x in (package / PACKAGE_DIR_NAME / "data" / "document_manifest.jsonl").read_text().splitlines()
    ]
    out = []
    for r in rows:
        import pymupdf

        path = base / r["relative_path"]
        with pymupdf.open(path) as d:
            n = len(d)
        out.append(FileTask(r["file_id"], OBJ, str(path), r["sha256"], r["stage"], tuple(range(1, n + 1))))
    return out


def test_scan_and_assemble_in_process(package: Path, tmp_path: Path) -> None:
    tasks = _tasks(package)
    res = scan_files(tasks, {OBJ: CodeRegistry()}, ScanOptions(ocr=False, qr_render=False), workers=1)
    docs = assemble_object(OBJ, res, pipeline_version="layout-test", generated_at="2026-09-28T00:00:00Z")
    assert set(docs) == {"F9001", "F9002", "F9003"}
    rd = docs["F9001"]
    loader.validate("layout_artifacts", rd)
    LayoutArtifacts.model_validate(rd)
    assert [tb["sheet_number"] for tb in rd["title_blocks"]] == [1, 2, 3, 3, 5]
    smap = {e["pdf_page_number"]: e for e in rd["sheet_page_map"]}
    # page 4 repeats sheet 3 → flagged; pages 3/4/5 are not a linear run, page 5 keeps what it prints
    assert smap[4]["duplicate_of_page"] == 3
    assert smap[5]["sheet_number"] == 5
    assert rd["stage"] == "RD" and rd["pages_total"] == 5
    assert {"scan_wall_ms", "words_ms", "grid_ms", "ocr_ms", "cell_ms", "qr_ms"} <= set(rd["timings_ms"])
    assert rd["ext"]["title_block"]["cells_reread"] == {} and rd["ext"]["title_block"]["ocr_qr_hidden"] == 0
    ident = docs["F9002"]
    assert ident["qr_links"][0]["target_file_id"] == "F9001"
    assert ident["qr_links"][0]["target_pdf_page_number"] == 3
    assert docs["F9003"]["title_blocks"] == [] and docs["F9003"]["sheet_page_map"] == []
    out = write_layout(tmp_path / "run", rd)
    assert out == tmp_path / "run" / "layout" / "F9001.json"
    assert json.loads(out.read_text(encoding="utf-8"))["file_id"] == "F9001"


def test_scan_in_worker_processes(package: Path) -> None:
    tasks = _tasks(package)
    assert len(chunk_tasks(tasks, chunk_pages=2)) == 5
    res = scan_files(
        tasks, {OBJ: CodeRegistry()}, ScanOptions(ocr=False, qr_render=False), workers=2, chunk_pages=2
    )
    assert [s["page"] for s in res["F9001"].scans] == [1, 2, 3, 4, 5]
    assert not any(r.errors for r in res.values())


def test_write_layout_refuses_invalid_document(tmp_path: Path) -> None:
    with pytest.raises(Exception):  # noqa: B017 — jsonschema ValidationError or the loader's wrapper
        write_layout(tmp_path, {"schema_version": 1, "file_id": "F9001"})
    assert not (tmp_path / "layout").exists()


def test_cli_layout_writes_artifacts(package: Path, tmp_path: Path) -> None:
    from inspector_batch import cli
    from inspector_common.exitcodes import ExitCode
    from inspector_common.runlayout import load_artifacts_index

    runs = tmp_path / "runs"
    code = cli.main(
        ["--data-root", str(package), "--runs-root", str(runs), "--log-format", "console", "--run-id", "lay",
         "layout", "--object", OBJ, "--workers", "1", "--no-ocr", "--no-qr-render"]
    )  # fmt: skip
    assert code == ExitCode.OK
    run = runs / "lay"
    for fid in ("F9001", "F9002", "F9003"):
        doc = json.loads((run / "layout" / f"{fid}.json").read_text(encoding="utf-8"))
        loader.validate("layout_artifacts", doc)
    index = load_artifacts_index(run)
    kinds = [a["kind"] for a in index["artifacts"]]
    assert kinds.count("LAYOUT") == 3
    assert (run / "layout_summary.json").is_file()


def test_cli_layout_without_files_is_data_missing(package: Path, tmp_path: Path) -> None:
    from inspector_batch import cli
    from inspector_common.exitcodes import ExitCode

    code = cli.main(
        ["--data-root", str(package), "--runs-root", str(tmp_path / "runs"), "--log-format", "console",
         "layout", "--object", OBJ, "--file", "F9999", "--no-ocr"]
    )  # fmt: skip
    assert code == ExitCode.DATA_MISSING


def test_stamp_stage_conflict_and_resolved_stage(tmp_path: Path) -> None:
    """RD file whose «Общие данные» stamp prints «П» (as F0202 p14) → META_CONFLICT; a RD_ID_MIXED file takes
    AG-01's resolved stage, never the stamp's (ИД extracts print «РД»)."""
    rd = make_stamp_pdf(
        tmp_path / "rd.pdf",
        [StampSpec(stage="П", sheet="1", change_rows=()), StampSpec(sheet="2", change_rows=())],
    )
    ext = make_stamp_pdf(tmp_path / "id.pdf", [StampSpec(sheet="4", change_rows=())])
    tasks = [
        FileTask("F9101", OBJ, str(rd), "a" * 64, "RD", (1, 2)),
        FileTask("F9102", OBJ, str(ext), "b" * 64, "RD_ID_MIXED", (1,)),
        FileTask("F9103", OBJ, str(ext), "c" * 64, "RD_ID_MIXED", (1,)),
    ]
    res = scan_files(tasks, {OBJ: CodeRegistry()}, ScanOptions(ocr=False, qr=False), workers=1)
    docs = assemble_object(OBJ, res, pipeline_version="t", resolved_stages={"F9102": "ID"})
    assert "META_CONFLICT" in docs["F9101"]["warnings"]
    assert docs["F9101"]["ext"]["title_block"]["stage_conflicts"][0]["pdf_page_number"] == 1
    assert docs["F9102"]["stage"] == "ID" and docs["F9102"]["warnings"] == []
    assert docs["F9103"]["stage"] is None  # unresolved: no stage guessed from the stamp
    for d in docs.values():
        loader.validate("layout_artifacts", d)


def test_page_tokens_are_used_when_present(tmp_path: Path) -> None:
    """With a recognition run's PageTokens the stamp is read from them (no text layer, no OCR)."""
    import gzip

    import pymupdf

    from inspector_docproc.textlayer import extract_text_layer
    from inspector_layout.pagescan import PageScanner

    pdf = make_stamp_pdf(tmp_path / "s.pdf", [StampSpec(sheet="9", change_rows=())])
    with pymupdf.open(pdf) as doc:
        words = extract_text_layer(doc[0]).visible_words
    tokens = [
        {"id": i, "text": w.text, "bbox": w.bbox, "conf": 0.97, "source": "OCR", "angle": 0}
        for i, w in enumerate(words)
    ]
    tdir = tmp_path / "tokens" / "F9001"
    tdir.mkdir(parents=True)
    with gzip.open(tdir / "p00001.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"tokens": tokens, "is_stamp_page": False}, fh)
    sc = PageScanner(CodeRegistry(), ScanOptions(ocr=False, qr=False, tokens_dir=str(tmp_path / "tokens")))
    with pymupdf.open(pdf) as doc:
        res = sc.scan(doc, 1, file_id="F9001", stage_hint="RD")
    assert res.words_source == "tokens"
    assert res.title_block["sheet_number"] == 9 and res.sheet_source == "OCR"
    assert res.title_block["provenance"]["text_source"] == "OCR"


def test_resolved_stages_from_inventory(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from inspector_layout.batch import _resolved_stages

    run = tmp_path / "run"
    (run / "inventory").mkdir(parents=True)
    (run / "inventory" / f"{OBJ}.json").write_text(
        json.dumps(
            {
                "files": [
                    {"file_id": "F9001", "stage_resolved": "ID"},
                    {"file_id": "F9002", "stage": {"stage_resolved": "RD"}},
                    {"file_id": "F9003", "stage_resolved": None},
                ]
            }
        ),
        encoding="utf-8",
    )
    ctx = SimpleNamespace(run_dir=run, settings=SimpleNamespace(paths=SimpleNamespace(runs_root=tmp_path)))
    assert _resolved_stages(ctx, OBJ, None) == {"F9001": "ID", "F9002": "RD"}
    assert _resolved_stages(ctx, OBJ, "run") == {"F9001": "ID", "F9002": "RD"}
    assert _resolved_stages(ctx, "OBJ-OTHER", None) == {}
    task = FileTask("F9001", OBJ, "x.pdf", "a" * 64, "RD_ID_MIXED", (1,), "ID")
    assert task.stage_hint == "ID"
    assert FileTask("F9004", OBJ, "x.pdf", "a" * 64, "UNKNOWN", (1,)).stage_hint is None


def test_zero_based_exon_pages_are_reported_one_based(tmp_path: Path) -> None:
    """Новослободская F0136: «…/wd/0» on PDF page 1. The contract's doc_page is ≥ 1: the key is 0-based."""
    zero = "https://exon.exonproject.ru/document-status/639848bf-bb23-43d4-b0a2-f690594af114/1/wd/{}"
    specs = [StampSpec(sheet=str(s), code="НСЛ-17-02/2026-1,2-КЖ1.1.1", change_rows=()) for s in (1, 2, 3)]
    pdf = make_stamp_pdf(tmp_path / "z.pdf", specs, qr_payloads=[zero.format(p) for p in range(3)])
    res = scan_files(
        [FileTask("F9201", OBJ, str(pdf), "d" * 64, "RD", (1, 2, 3))],
        {OBJ: CodeRegistry()},
        ScanOptions(ocr=False, qr_render=False),
        workers=1,
    )
    doc = assemble_object(OBJ, res, pipeline_version="t")["F9201"]
    loader.validate("layout_artifacts", doc)
    assert [q["doc_page"] for q in doc["qr_links"]] == [1, 2, 3]
    assert [q["target_pdf_page_number"] for q in doc["qr_links"]] == [1, 2, 3]
    assert doc["ext"]["qr"]["zero_based_keys"] == ["exon:639848bf-bb23-43d4-b0a2-f690594af114/1"]


def test_write_layout_salvages_one_bad_item(tmp_path: Path) -> None:
    doc = {
        "schema_version": 1, "file_id": "F9001", "object_id": OBJ, "file_sha256": "a" * 64,
        "pipeline_version": "t", "generated_at": "2026-09-28T00:00:00Z", "pages_total": 2, "warnings": [],
        "ext": {},
        "qr_links": [
            {"pdf_page_number": 1, "payload": "https://x.test/a", "doc_page": 0},
            {"pdf_page_number": 2, "payload": "https://x.test/b", "doc_page": 2},
        ],
    }  # fmt: skip
    out = write_layout(tmp_path, doc)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert [q["pdf_page_number"] for q in saved["qr_links"]] == [2]
    assert saved["warnings"] == ["CONTRACT_VALIDATION_FAILED"]
    assert saved["ext"]["dropped_invalid"][0].startswith("qr_links/0/doc_page")
