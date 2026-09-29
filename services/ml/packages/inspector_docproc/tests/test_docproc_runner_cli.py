"""Cache, parallel runner and the ``inspector-batch recognize`` command on a synthetic data root."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_common.paths import DOCUMENTS_DIR_PARTS, PACKAGE_DIR_NAME
from inspector_docproc.cache import TokenCache, load_gz
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.inputs import FileJob, parse_pages
from inspector_docproc.models import ModelRegistry
from inspector_docproc.runner import run_recognition
from inspector_docproc.testing import make_pdf, models_available

TEXT = [(60, 90 + 18 * i, f"Раздел {i} проектной документации строительства здания", 11) for i in range(12)]


def test_parse_pages() -> None:
    assert parse_pages(None, 3) == [1, 2, 3]
    assert parse_pages("2-3,5,9", 6) == [2, 3, 5]
    with pytest.raises(ValueError):
        parse_pages("0-2", 5)


def test_cache_roundtrip(tmp_path) -> None:
    cache = TokenCache(tmp_path, "docproc-test")
    assert cache.get("a" * 64, 1) is None
    p = cache.put("a" * 64, 1, {"x": "значение"})
    assert p.name == "p00001.json.gz" and cache.get("a" * 64, 1) == {"x": "значение"}


def _multi_page_pdf(path: Path, n: int) -> Path:
    import pymupdf

    out = pymupdf.open()
    for _ in range(n):
        single = make_pdf(path.with_suffix(".one.pdf"), TEXT)
        with pymupdf.open(single) as d:
            out.insert_pdf(d)
    out.save(path)
    return path


@pytest.mark.skipif(not models_available(), reason="OCR models not found (make fetch-models)")
def test_runner_in_process_with_resume(tmp_path) -> None:
    pdf = _multi_page_pdf(tmp_path / "doc.pdf", 3)
    job = FileJob("F9100", "OBJ-TEST", "PD", "doc.pdf", pdf, "c" * 64, 3)
    kwargs = dict(
        pages_spec=None,
        cfg=RecognitionConfig(),
        exec_cfg=ExecutionConfig(providers="cpu", workers=1),
        cache_root=tmp_path / "cache",
    )
    first = run_recognition([job], run_dir=tmp_path / "run1", **kwargs)
    s = first.summary
    assert s["pages_processed"] == 3 and s["pages_cached"] == 0 and s["pages_failed"] == 0
    assert s["page_classes"] == {"VECTOR": 3}
    files = sorted((tmp_path / "run1" / "tokens" / "F9100").glob("p*.json.gz"))
    assert [f.name for f in files] == ["p00001.json.gz", "p00002.json.gz", "p00003.json.gz"]
    doc = load_gz(files[0])
    assert validation_errors("page_tokens", doc) == [] and doc["pipeline_version"] == s["pipeline_version"]
    index = [
        json.loads(line) for line in (tmp_path / "run1" / "tokens" / "index.jsonl").read_text().splitlines()
    ]
    assert [r["page_no"] for r in index] == [1, 2, 3]
    tindex = json.loads((tmp_path / "run1" / "tokens" / "index.json").read_text())
    assert validation_errors("tokens_index", tindex) == []
    assert tindex["run_id"] == "run1" and tindex["pipeline_version"] == s["pipeline_version"]
    (entry,) = tindex["files"]
    assert (entry["file_id"], entry["stage"], entry["pages_total"]) == ("F9100", "PD", 3)
    assert [p["path"] for p in entry["pages"]] == [f"tokens/F9100/p0000{i}.json.gz" for i in (1, 2, 3)]
    assert entry["pages"][0]["text_sources"] == ["TEXT_LAYER"] and entry["pages"][0]["page_class"] == "VECTOR"
    second = run_recognition(
        [job],
        run_dir=tmp_path / "run2",
        pages_spec="2-3",
        **{k: v for k, v in kwargs.items() if k != "pages_spec"},
    )
    assert second.summary["pages_cached"] == 2 and second.summary["pages_processed"] == 0
    assert (tmp_path / "run2" / "tokens" / "F9100" / "p00002.json.gz").is_file()
    tindex2 = json.loads((tmp_path / "run2" / "tokens" / "index.json").read_text())
    assert [p["cache_hit"] for p in tindex2["files"][0]["pages"]] == [True, True]
    assert tindex2["files"][0]["pages_total"] == 3  # the file has 3 pages, 2 were selected


@pytest.mark.skipif(not models_available(), reason="OCR models not found (make fetch-models)")
def test_runner_pages_by_file(tmp_path) -> None:
    """Per-file page selection in one pool (layout/tables re-reads, sampled timing runs)."""
    a = _multi_page_pdf(tmp_path / "a.pdf", 3)
    b = _multi_page_pdf(tmp_path / "b.pdf", 2)
    jobs = [
        FileJob("F9101", "OBJ-TEST", "PD", "a.pdf", a, "d" * 64, 3),
        FileJob("F9102", "OBJ-TEST", "RD", "b.pdf", b, "e" * 64, 2),
    ]
    res = run_recognition(
        jobs,
        pages_spec="1",
        pages_by_file={"F9101": "2-3"},
        cfg=RecognitionConfig(),
        exec_cfg=ExecutionConfig(providers="cpu", workers=1),
        run_dir=tmp_path / "run",
        cache_root=tmp_path / "cache",
    )
    assert [(s["file_id"], s["page_no"]) for s in res.index] == [("F9101", 2), ("F9101", 3), ("F9102", 1)]
    tindex = json.loads((tmp_path / "run" / "tokens" / "index.json").read_text())
    assert validation_errors("tokens_index", tindex) == []
    assert {f["file_id"]: f["pages_total"] for f in tindex["files"]} == {"F9101": 3, "F9102": 2}


@pytest.fixture()
def fake_data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data_utf8"
    pkg = root / PACKAGE_DIR_NAME / "data"
    pkg.mkdir(parents=True)
    docs = root.joinpath(*DOCUMENTS_DIR_PARTS) / "obj"
    docs.mkdir(parents=True)
    make_pdf(docs / "text.pdf", TEXT)
    rows = [
        {"file_id": "F9001", "object_id": "OBJ-TRAIN-X", "split": "TRAIN_PUBLIC", "relative_path": "obj/text.pdf",
         "extension": ".pdf", "sha256": "d" * 64, "stage": "PD", "pdf_pages": 1},
        {"file_id": "F9002", "object_id": "OBJ-TRAIN-X", "split": "TRAIN_PUBLIC", "relative_path": "obj/missing.pdf",
         "extension": ".pdf", "sha256": "e" * 64, "stage": "PD", "pdf_pages": 1},
    ]  # fmt: skip
    (pkg / "document_manifest.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )
    (pkg / "split_policy.json").write_text(
        json.dumps(
            {"TRAIN_PUBLIC": ["OBJ-TRAIN-X"], "TEST_HIDDEN": ["OBJ-HIDDEN-X"], "excluded_file_ids": []}
        )
    )
    (pkg / "parameter_catalog_132.jsonl").write_text("{}\n")
    (pkg / "submission_schema.json").write_text("{}\n")
    return root


@pytest.mark.skipif(not models_available(), reason="OCR models not found (make fetch-models)")
def test_recognize_command_end_to_end(fake_data_root: Path, tmp_path: Path, monkeypatch) -> None:
    from inspector_batch.cli import main

    ModelRegistry()  # the manifest must be readable (model files are not needed for text pages)
    monkeypatch.setenv("INSPECTOR_CACHE_ROOT", str(tmp_path / "cache"))
    runs = tmp_path / "runs"
    code = main(
        ["--data-root", str(fake_data_root), "--runs-root", str(runs), "--run-id", "t1", "--log-level", "ERROR",
         "recognize", "--object", "OBJ-TRAIN-X", "--workers", "1", "--providers", "cpu"]
    )  # fmt: skip
    assert code == 0
    summary = json.loads((runs / "t1" / "recognize_summary.json").read_text())
    assert (
        summary["pages_processed"] == 1 and summary["files"] == 1
    )  # the missing file is reported, not fatal
    assert (runs / "t1" / "tokens" / "F9001" / "p00001.json.gz").is_file()


def test_recognize_refuses_hidden_object_without_flag(fake_data_root: Path, tmp_path: Path) -> None:
    from inspector_batch.cli import main

    code = main(
        ["--data-root", str(fake_data_root), "--runs-root", str(tmp_path / "runs"), "--log-level", "ERROR",
         "recognize", "--object", "OBJ-HIDDEN-X"]
    )  # fmt: skip
    assert code == 5


def test_malformed_manifest_rows_are_reported_not_fatal(fake_data_root: Path, tmp_path: Path) -> None:
    from inspector_batch.cli import main
    from inspector_common.paths import DataPaths
    from inspector_docproc.inputs import select_files

    manifest = fake_data_root / PACKAGE_DIR_NAME / "data" / "document_manifest.jsonl"
    manifest.write_text(manifest.read_text() + "{}\nnot json\n", encoding="utf-8")
    paths = DataPaths(fake_data_root, tmp_path / "models", tmp_path / "cache", tmp_path / "runs")
    jobs, problems = select_files(paths, ["OBJ-TRAIN-X"])
    assert [j.file_id for j in jobs] == ["F9001"]
    assert [p["code"] for p in problems].count("MANIFEST_ROW_INVALID") == 2
    manifest.write_text("{}\n", encoding="utf-8")  # nothing usable: a clean «no files» exit, no traceback
    code = main(
        ["--data-root", str(fake_data_root), "--runs-root", str(tmp_path / "runs"), "--log-level", "ERROR",
         "recognize", "--object", "OBJ-TRAIN-X"]
    )  # fmt: skip
    assert code == 6  # ExitCode.DATA_MISSING
