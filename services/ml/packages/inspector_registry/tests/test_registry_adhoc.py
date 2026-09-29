"""Ad-hoc registry for user uploads: stage guess, registry file, archive unpacking, manifest/data-root layout."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pymupdf
import pytest

from inspector_common.contracts.loader import validation_errors
from inspector_common.paths import DOCUMENTS_DIR_PARTS, PACKAGE_DIR_NAME
from inspector_registry import adhoc

OBJECT_ID = "OBJ-UPLOAD-1a2b3c4d"


def _pdf(path: Path, text: str = "Лист", pages: int = 1) -> None:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ПД", "PD"),
        ("рабочая документация", "RD"),
        ("АОСР", "ID"),
        ("Исполнительная", "ID"),
        ("id", "ID"),
        ("что-то", None),
        ("", None),
    ],
)
def test_normalize_stage(value: str, expected: str | None) -> None:
    assert adhoc.normalize_stage(value) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("ПД/1 Пояснительная записка/Том 1.pdf", "PD"),
        ("Рабочая документация/АР/лист.pdf", "RD"),
        ("Исполнительная документация/АОСР №1.pdf", "ID"),
        ("АОСР_1.pdf", "ID"),
        ("РД_План.pdf", "RD"),
        ("Том 1.pdf", None),
    ],
)
def test_guess_stage_from_names(path: str, expected: str | None) -> None:
    assert adhoc.guess_stage(path) == expected


def test_object_id_for_is_stable_and_valid() -> None:
    oid = adhoc.object_id_for("01a0ebb5-b715-7ef5-a425-28907de7f69f")
    assert oid == "OBJ-UPLOAD-7de7f69f"
    assert adhoc.object_id_for("01a0ebb5-b715-7ef5-a425-28907de7f69f") == oid


def test_prepare_builds_manifest_compatible_dataroot(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    (incoming / "ПД").mkdir(parents=True)
    (incoming / "ИД").mkdir()
    _pdf(incoming / "ПД" / "том1.pdf", pages=3)
    _pdf(incoming / "ИД" / "АОСР 1.pdf")
    _pdf(incoming / "без_подсказки.pdf")
    (incoming / "readme.txt").write_text("x")
    summary = adhoc.prepare(tmp_path, object_name="Дом 7", object_id=OBJECT_ID)

    assert summary["files_total"] == 3
    assert summary["pdf_pages_total"] == 5
    assert any("readme.txt" in n for n in summary["notes"])
    ids = [f["file_id"] for f in summary["files"]]
    assert ids == ["U1a2b3c4d-0001", "U1a2b3c4d-0002", "U1a2b3c4d-0003"]
    by_name = {f["name"]: f for f in summary["files"]}
    assert by_name["том1.pdf"]["stage"] == "PD" and by_name["том1.pdf"]["stage_source"] == "PATH"
    assert by_name["АОСР 1.pdf"]["stage"] == "ID"
    assert by_name["без_подсказки.pdf"]["stage"] == "UNKNOWN"

    data = tmp_path / "dataroot" / PACKAGE_DIR_NAME / "data"
    rows = [
        json.loads(line)
        for line in (data / "document_manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {r["object_id"] for r in rows} == {OBJECT_ID}
    assert all(r["split"] == "TRAIN_PUBLIC" and r["corpus"] == "Дом 7" for r in rows)
    for r in rows:
        assert validation_errors("manifest_row", r) == []
        assert (tmp_path / "dataroot").joinpath(*DOCUMENTS_DIR_PARTS, r["relative_path"]).is_file()
    policy = json.loads((data / "split_policy.json").read_text(encoding="utf-8"))
    assert policy["TRAIN_PUBLIC"] == [OBJECT_ID] and policy["TEST_HIDDEN"] == []
    assert (tmp_path / "prepare.json").is_file()


def test_registry_csv_overrides_guess(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    _pdf(incoming / "ПД_странное_имя.pdf")
    reg = tmp_path / "registry.csv"
    reg.write_text("Файл;Стадия;Раздел\nПД_странное_имя.pdf;Рабочая документация;AR\n", encoding="utf-8")
    summary = adhoc.prepare(tmp_path, object_name="X", object_id=OBJECT_ID, registry_path=reg)
    f = summary["files"][0]
    assert (f["stage"], f["stage_source"]) == ("RD", "REGISTRY")
    row = json.loads(
        (tmp_path / "dataroot" / PACKAGE_DIR_NAME / "data" / "document_manifest.jsonl").read_text(
            encoding="utf-8"
        )
    )
    assert row["section"] == "AR"


def test_registry_json_and_xlsx(tmp_path: Path) -> None:
    j = tmp_path / "r.json"
    j.write_text(json.dumps([{"file": "a.pdf", "stage": "ИД"}]), encoding="utf-8")
    assert adhoc.load_registry(j)["a.pdf"].stage == "ID"
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "stage"])
    ws.append(["b.pdf", "РД"])
    x = tmp_path / "r.xlsx"
    wb.save(x)
    assert adhoc.load_registry(x)["b.pdf"].stage == "RD"


def test_archives_are_unpacked_and_unsafe_members_skipped(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    src = tmp_path / "src.pdf"
    _pdf(src)
    with zipfile.ZipFile(incoming / "комплект.zip", "w") as z:
        z.write(src, "РД/лист1.pdf")
        z.writestr("../evil.pdf", b"%PDF-1.4")
        z.writestr("notes.txt", "x")
    summary = adhoc.prepare(tmp_path, object_name="Архив", object_id=OBJECT_ID)
    names = [f["name"] for f in summary["files"]]
    assert names == ["лист1.pdf"]
    assert summary["files"][0]["from_archive"] == "комплект.zip"
    assert summary["files"][0]["stage"] == "RD"
    assert not (tmp_path / "evil.pdf").exists()
    assert summary["notes"]


def test_empty_stage_folder_and_missing_stage_are_reported(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    src = tmp_path / "src.pdf"
    _pdf(src)
    with zipfile.ZipFile(incoming / "объект.zip", "w") as z:
        z.write(src, "Объект 7/Проектная документация/ПЗ.pdf")
        z.write(src, "Объект 7/Рабочая документация/ОВ1.pdf")
        z.writestr("Объект 7/Исполнительная документация/", b"")  # an empty stage folder
    summary = adhoc.prepare(tmp_path, object_name="Объект 7", object_id=OBJECT_ID)
    assert summary["stages"] == {"PD": 1, "RD": 1, "ID": 0, "UNKNOWN": 0}
    notes = " ".join(summary["notes"])
    assert "«Объект 7/Исполнительная документация» архива «объект.zip» пуста" in notes
    assert "нет документов стадии ИД" in notes
    assert "Проектная документация» архива" not in notes


def test_prepare_without_organizer_package_rebuilds_catalog_and_schema(tmp_path: Path) -> None:
    """A fresh machine has no data_utf8: the catalog comes from the params seed, the schema from contracts."""
    from inspector_common.params import load_catalog

    incoming = tmp_path / "incoming"
    (incoming / "ПД").mkdir(parents=True)
    _pdf(incoming / "ПД" / "ПЗ.pdf")
    empty = tmp_path / "no_organizer_data"
    empty.mkdir()
    adhoc.prepare(tmp_path, object_name="Без данных", object_id=OBJECT_ID, source_data_root=empty)
    data_dir = tmp_path / "dataroot" / adhoc.PACKAGE_DIR_NAME / "data"
    rows = load_catalog(data_dir / "parameter_catalog_132.jsonl")
    assert len(rows) == 132 and rows[0].parameter_code
    schema = json.loads((data_dir / "submission_schema.json").read_text(encoding="utf-8"))
    assert schema["type"] == "object" and "properties" in schema


def test_rejects_bad_object_id(tmp_path: Path) -> None:
    (tmp_path / "incoming").mkdir()
    with pytest.raises(ValueError):
        adhoc.prepare(tmp_path, object_name="X", object_id="../../etc")
