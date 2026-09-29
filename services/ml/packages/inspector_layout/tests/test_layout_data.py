"""Layout on real TRAIN documents (Тюменская, Новослободская). Skipped without the organizer data.

Fast checks use the text layer and embedded QR images only; the two acceptance gates (codes EM on the 17
benchmark stamps, sheet = stamp on every F0201/F0202 drawing page) OCR the stamps and are marked slow.
"""

from __future__ import annotations

import pytest

from inspector_common.settings import Settings

pytestmark = pytest.mark.data

TYUMEN = "OBJ-TYUMENSKAYA-5-GOLD-SEED"
NOVOSLOB = "OBJ-NOVOSLOBODSKAYA"


@pytest.fixture(scope="module")
def paths():
    p = Settings().paths
    if not p.documents_root.is_dir():
        pytest.skip("organizer data not found")
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    return p


@pytest.fixture(scope="module")
def manifest(paths):
    from inspector_docproc.inputs import load_manifest

    return load_manifest(paths)


def _job(paths, obj: str, fid: str):
    from inspector_docproc.inputs import select_files

    jobs, _ = select_files(paths, (obj,), [fid])
    assert jobs, fid
    return jobs[0]


def _scanner(manifest, obj: str, **kw):
    from inspector_layout.codes import CodeRegistry
    from inspector_layout.pagescan import PageScanner, ScanOptions

    return PageScanner(CodeRegistry.from_manifest_rows(manifest, obj), ScanOptions(**kw))


def test_text_layer_stamps_f0202(paths, manifest) -> None:
    """F0202 p10–p12: «Состав рабочей документации» (form 5) and two form-6 sheets, all in the text layer."""
    import pymupdf

    sc = _scanner(manifest, TYUMEN, ocr=False, qr=False)
    with pymupdf.open(_job(paths, TYUMEN, "F0202").path) as doc:
        tbs = {p: sc.scan(doc, p, file_id="F0202", stage_hint=None).title_block for p in (10, 11, 12)}
    assert [tbs[p]["sheet_number"] for p in (10, 11, 12)] == [1, 2, 3]
    assert {tbs[p]["document_code"] for p in (10, 11, 12)} == {"АНО/150321/1-РД-СП"}
    assert tbs[10]["stage"] == "RD" and tbs[10]["sheet_title"] == "Состав рабочей документации"
    assert tbs[10]["provenance"]["text_source"] == "TEXT_LAYER"


def test_qr_links_id_extract_to_rd_sheet(paths, manifest) -> None:
    """RT-07 (95): the ИД extract F0198 carries the QR of РД ОВ2.1 sheet p17 (F0202) → linked to F0202 p17."""
    from inspector_layout.codes import CodeRegistry
    from inspector_layout.pagescan import ScanOptions
    from inspector_layout.pipeline import FileTask, assemble_object, scan_files

    tasks = []
    for fid, pages in (("F0198", (1,)), ("F0202", tuple(range(14, 25)))):
        j = _job(paths, TYUMEN, fid)
        tasks.append(FileTask(fid, TYUMEN, str(j.path), j.sha256, j.stage, pages))
    opts = ScanOptions(ocr=False, qr_render=False)
    res = scan_files(tasks, {TYUMEN: CodeRegistry.from_manifest_rows(manifest, TYUMEN)}, opts, workers=1)
    docs = assemble_object(TYUMEN, res, pipeline_version="layout-test")
    (link,) = docs["F0198"]["qr_links"]
    assert link["payload"].endswith("87cc1a16-51a4-4f99-bb70-35afc204d773/1/wd/17")
    assert (link["target_file_id"], link["target_pdf_page_number"]) == ("F0202", 17)
    assert len(docs["F0202"]["qr_links"]) == 11


def test_registry_prior_on_real_manifest(manifest) -> None:
    from inspector_layout.codes import CodeRegistry

    nov = CodeRegistry.from_manifest_rows(manifest, NOVOSLOB)
    assert nov.resolve("HBC-2025/03-P3", stage="PD").code == "НВС-2025/03-ПЗ"
    tyu = CodeRegistry.from_manifest_rows(manifest, TYUMEN)
    assert tyu.resolve("AH0/150321/1-P-ИOC5.4.2", stage="PD").code == "АНО/150321/1-П-ИОС5.4.2"
    assert tyu.resolve("AHO/150321/1-PД-OB2.1", stage="RD").code == "АНО/150321/1-РД-ОВ2.1"


def test_novoslobodskaya_rd_text_stamp(paths, manifest) -> None:
    """Новослободская КЖ sheets carry text-layer stamps with a Signal QR drawn as vector paths."""
    import pymupdf

    sc = _scanner(manifest, NOVOSLOB, ocr=False)
    with pymupdf.open(_job(paths, NOVOSLOB, "F0140").path) as doc:
        res = sc.scan(doc, 5, file_id="F0140", stage_hint="RD")
    tb = res.title_block
    assert tb is not None and tb["document_code"].startswith("НСЛ-17-02/2026")
    assert isinstance(tb["sheet_number"], int)
    assert any(q["payload"].startswith("https://qr.sgnl.pro/d/") for q in res.qr)


def test_pd_text_layer_stamp_regressions(paths, manifest) -> None:
    """Real text-layer stamps that broke the reader: a garbled layer (constant glyph shift, F0153 p8), a code
    split into overlapping runs under a topographic plan's own nomenclature (F0148 p371), and a one-sheet
    document with «Лист» blank and «Листов 1» (F0161 p5)."""
    import pymupdf

    from inspector_layout.codes import CodeRegistry
    from inspector_layout.pagescan import ScanOptions
    from inspector_layout.pipeline import FileTask, assemble_object, scan_files

    sc = _scanner(manifest, TYUMEN, ocr=False, qr=False)
    with pymupdf.open(_job(paths, TYUMEN, "F0153").path) as doc:
        tb = sc.scan(doc, 8, file_id="F0153", stage_hint="PD").title_block
    assert tb["document_code"] == "АНО/150321/1-П-БЭОКС10(1).ПЗ" and tb["sheet_number"] == 4
    with pymupdf.open(_job(paths, TYUMEN, "F0148").path) as doc:
        tb = sc.scan(doc, 371, file_id="F0148", stage_hint="PD").title_block
    assert tb["document_code"] == "АНО/150321/1-П-ПЗУ" and (tb["sheet_number"], tb["sheets_total"]) == (2, 10)
    j = _job(paths, TYUMEN, "F0161")
    task = FileTask("F0161", TYUMEN, str(j.path), j.sha256, j.stage, (5, 6, 7))
    res = scan_files([task], {TYUMEN: CodeRegistry()}, ScanOptions(ocr=False, qr=False), workers=1)
    doc = assemble_object(TYUMEN, res, pipeline_version="layout-test")["F0161"]
    assert [t["sheet_number"] for t in doc["title_blocks"]] == [None, None, None]  # as printed
    assert [(e["pdf_page_number"], e["sheet_number"]) for e in doc["sheet_page_map"]] == [
        (5, 1),
        (6, 1),
        (7, 1),
    ]


@pytest.mark.slow
def test_gate_document_codes_17_stamps(paths) -> None:
    """R-06 gate: document codes EM ≥ 0.95 on the 17 benchmark stamps (11 vector + 6 outlined)."""
    from inspector_docproc.testing import models_available
    from inspector_layout.bench import suite_codes

    if not models_available():
        pytest.skip("OCR models not found")
    res = suite_codes(paths, log=lambda _m: None)
    assert res["n_stamps"] == 17
    assert res["em"] >= 0.95, [r for r in res["vector"]["rows"] if not r["gate"]]
    assert res["outlined"]["key_fields_em"] >= 0.95


@pytest.mark.slow
def test_gate_sheet_equals_stamp(paths) -> None:
    """R-07 gate: sheet = stamp ≥ 0.95 on all F0201/F0202 drawing pages (182), duplicates flagged."""
    from inspector_docproc.testing import models_available
    from inspector_layout.bench import suite_sheets

    if not models_available():
        pytest.skip("OCR models not found")
    res = suite_sheets(paths, workers=3, log=lambda _m: None)
    assert res["n_pages"] == 182
    assert res["sheet_eq_stamp"] >= 0.95, res["misses"]
    assert res["duplicates"]["flagged"] == res["duplicates"]["expected"] == 2
