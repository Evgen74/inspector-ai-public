"""Synthetic fixtures for inspector_registry tests (no organizer data needed).

Builders are exposed through the ``build`` fixture (a namespace) because tests run with
``--import-mode=importlib`` and cannot import sibling helper modules.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from inspector_common.paths import DOCUMENTS_DIR_PARTS, PACKAGE_DIR_NAME, DataPaths
from inspector_common.settings import Settings

TRAIN = "OBJ-TRAIN-A"
TRAIN_B = "OBJ-TRAIN-B"
HIDDEN = "OBJ-HIDDEN-Z"


# ── file builders ────────────────────────────────────────────────────────────────────────────


def make_pdf(path: Path, pages: list[str]) -> Path:
    """A PDF whose pages carry the given (Cyrillic-capable) text layer."""
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        y = 72
        for line in text.split("\n"):
            page.insert_text(
                (56, y), line, fontsize=11, fontname="helv", encoding=pymupdf.TEXT_ENCODING_CYRILLIC
            )
            y += 16
    doc.save(str(path))
    doc.close()
    return path


class RawNameZipInfo(zipfile.ZipInfo):
    """ZipInfo written with a legacy code page and without the UTF-8 flag (bit 11)."""

    def __init__(self, name: str, codec: str) -> None:
        super().__init__(name)
        self._codec = codec

    def _encodeFilenameFlags(self) -> tuple[bytes, int]:
        return self.filename.encode(self._codec), self.flag_bits & ~0x800


def make_zip(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    codec: str | None = "cp866",
    encrypted: set[str] | None = None,
) -> Path:
    """Zip with legacy-encoded names (``codec``) or UTF-8 flagged names (``codec=None``).

    ``encrypted``: names whose «encrypted» flag (bit 0) is set afterwards in both headers (the data
    stays plain; enough to test that such members are never read).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            info: zipfile.ZipInfo = RawNameZipInfo(name, codec) if codec else zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    if encrypted:
        _set_encrypted_flag(path, {n.encode(codec) if codec else n.encode("utf-8") for n in encrypted})
    return path


def _set_encrypted_flag(path: Path, names: set[bytes]) -> None:
    data = bytearray(path.read_bytes())
    eocd = data.rfind(b"PK\x05\x06")
    cd_size, cd_offset = struct.unpack("<II", data[eocd + 12 : eocd + 20])
    pos = cd_offset
    while pos < cd_offset + cd_size:
        name_len, extra_len, comment_len = struct.unpack("<HHH", data[pos + 28 : pos + 34])
        (local,) = struct.unpack("<I", data[pos + 42 : pos + 46])
        name = bytes(data[pos + 46 : pos + 46 + name_len])
        if name in names:
            data[pos + 8] |= 0x1
            data[local + 6] |= 0x1
        pos += 46 + name_len + extra_len + comment_len
    path.write_bytes(bytes(data))


def make_7z(path: Path, entries: list[tuple[str, bytes]]) -> Path:
    import py7zr

    path.parent.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(data, name)
    return path


def make_rar4(path: Path, entries: list[tuple[str, bytes]], *, oem: str = "cp866") -> Path:
    """Minimal RAR 2.9/4.x archive (stored files, Win32 host, OEM code page names)."""

    def block(head_type: int, flags: int, body: bytes) -> bytes:
        header = struct.pack("<BHH", head_type, flags, 7 + len(body)) + body
        return struct.pack("<H", zlib.crc32(header) & 0xFFFF) + header

    out = bytearray(b"Rar!\x1a\x07\x00")
    out += block(0x73, 0x0000, struct.pack("<HI", 0, 0))
    for name, data in entries:
        encoded = name.replace("/", "\\").encode(oem)
        body = struct.pack(
            "<IIBIIBBHI",
            len(data),
            len(data),
            2,
            zlib.crc32(data) & 0xFFFFFFFF,
            0x5A210000,
            29,
            0x30,
            len(encoded),
            0x20,
        )
        out += block(0x74, 0x8000, body + encoded) + data
    out += block(0x7B, 0x4000, b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


def make_docx(path: Path, text: str) -> Path:
    import docx

    path.parent.mkdir(parents=True, exist_ok=True)
    d = docx.Document()
    d.add_paragraph(text)
    d.save(str(path))
    return path


def dwg_bytes(version: str = "AC1032", size: int = 256, salt: str = "") -> bytes:
    body = version.encode("ascii") + salt.encode("utf-8")
    return body + b"\x00" * (size - len(body))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── synthetic organizer data root ────────────────────────────────────────────────────────────


@dataclass
class FakeData:
    root: Path  # data_utf8-like root
    paths: DataPaths
    rows: list[dict[str, Any]] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)

    @property
    def docs(self) -> Path:
        return self.paths.documents_root

    def add(
        self,
        file_id: str,
        object_id: str,
        rel: str,
        *,
        stage: str = "PD",
        section: str = "OTHER",
        annotation: str = "UNLABELED",
        duplicate_group: str | None = None,
        builder: Callable[[Path], Path] | None = None,
        data: bytes | None = None,
        write: bool = True,
        sha_override: str | None = None,
        size_override: int | None = None,
        split: str | None = None,
    ) -> dict[str, Any]:
        path = self.docs / rel
        tmp: Path
        if write:
            if builder is not None:
                builder(path)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data if data is not None else b"")
            tmp = path
        else:
            scratch = self.root.parent / "_unwritten" / file_id / Path(rel).name
            if builder is not None:
                builder(scratch)
            else:
                scratch.parent.mkdir(parents=True, exist_ok=True)
                scratch.write_bytes(data if data is not None else b"")
            tmp = scratch
        ext = Path(rel).suffix.lower()
        pages = None
        if ext == ".pdf":
            import pymupdf

            with pymupdf.open(str(tmp)) as doc:
                pages = doc.page_count
        hidden = object_id in self.policy.get("TEST_HIDDEN", [])
        row = {
            "schema_version": "0.1.0",
            "file_id": file_id,
            "object_id": object_id,
            "corpus": object_id,
            "dataset_role": "UNLABELED_POOL",
            "split": split or ("TEST_HIDDEN" if hidden else "TRAIN_PUBLIC"),
            "relative_path": rel,
            "extension": ext,
            "size_bytes": size_override if size_override is not None else tmp.stat().st_size,
            "sha256": sha_override or sha256(tmp),
            "stage": stage,
            "section": section,
            "pdf_pages": pages,
            "annotation_status": annotation,
            "exclusion_reason": None,
            "duplicate_group": duplicate_group,
            "distribution_status": "INCLUDE",
            "label_visibility": "ORGANIZER_ONLY" if hidden else "PUBLIC_TRAIN",
        }
        self.rows.append(row)
        return row

    def write_manifest(self, extra_lines: list[str] | None = None) -> Path:
        data_dir = self.paths.package_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(r, ensure_ascii=False) for r in self.rows] + list(extra_lines or [])
        self.paths.manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (data_dir / "split_policy.json").write_text(
            json.dumps(self.policy, ensure_ascii=False), encoding="utf-8"
        )
        for name in ("parameter_catalog_132.jsonl", "submission_schema.json"):
            (data_dir / name).write_text("{}\n", encoding="utf-8")
        return self.paths.manifest_path


def new_fake(tmp_path: Path) -> FakeData:
    root = tmp_path / "data_utf8"
    paths = DataPaths(
        data_root=root,
        models_root=tmp_path / "models",
        cache_root=tmp_path / "cache",
        runs_root=tmp_path / "runs",
    )
    root.joinpath(PACKAGE_DIR_NAME, "data").mkdir(parents=True)
    root.joinpath(*DOCUMENTS_DIR_PARTS).mkdir(parents=True)
    policy = {"TRAIN_PUBLIC": [TRAIN, TRAIN_B], "TEST_HIDDEN": [HIDDEN], "excluded_file_ids": ["F0999"]}
    return FakeData(root=root, paths=paths, policy=policy)


def full_fixture(tmp_path: Path) -> FakeData:
    """One object exercising every inventory path (see test_inventory_synthetic)."""
    fake = new_fake(tmp_path)
    a = "Объект А"
    fake.add(
        "F0001",
        TRAIN,
        f"{a}/ПД/3 Архитектурные решения/АР.pdf",
        builder=lambda p: make_pdf(
            p, ["ПРОЕКТНАЯ ДОКУМЕНТАЦИЯ\nРаздел 3. Архитектурные решения", "План", "Разрез"]
        ),
    )
    fake.add(
        "F0002",
        TRAIN,
        f"{a}/Рабочая и исполнительная документация/АОСР №1 от 01.02.2026.pdf",
        stage="RD_ID_MIXED",
        builder=lambda p: make_pdf(
            p,
            [
                "АКТ освидетельствования скрытых работ № 1\nвыполнены в соответствии с рабочей документацией ОБЪ-РД-АР"
            ],
        ),
    )
    fake.add(
        "F0003",
        TRAIN,
        f"{a}/Рабочая и исполнительная документация/Полные разделы/ОБЪ-РД-АР изм. 1.pdf",
        stage="RD_ID_MIXED",
        builder=lambda p: make_pdf(p, ["РАБОЧАЯ ДОКУМЕНТАЦИЯ\nАрхитектурные решения", "Общие данные"]),
    )
    fake.add(
        "F0004",
        TRAIN,
        f"{a}/Перечень нарушений.txt",
        stage="UNKNOWN",
        annotation="GROUND_TRUTH_INDEX",
        data=b"1. ...\n",
    )
    # Archive of drawings with cp866 names + its same-folder PDF twin (2 cover pages + 3 sheets).
    fake.add(
        "F0005",
        TRAIN,
        f"{a}/РД/КЖ1/ОБЪ-РД-КЖ1.pdf",
        stage="RD",
        builder=lambda p: make_pdf(p, ["РАБОЧАЯ ДОКУМЕНТАЦИЯ КЖ1", "Состав", "Лист 1", "Лист 2", "Лист 3"]),
    )
    fake.add(
        "F0006",
        TRAIN,
        f"{a}/РД/КЖ1/ОБЪ-РД-КЖ1.zip",
        stage="RD",
        builder=lambda p: make_zip(
            p,
            [
                ("КЖ1/ОБЪ-РД-КЖ1 Лист 1.dwg", dwg_bytes("AC1032", salt="1")),
                ("КЖ1/ОБЪ-РД-КЖ1 Лист 2.dwg", dwg_bytes("AC1027", salt="2")),
                ("КЖ1/ОБЪ-РД-КЖ1 Лист 3.dwg", dwg_bytes("AC1032", salt="3")),
                ("КЖ1/ОБЪ-РД-КЖ1 Лист 3.bak", dwg_bytes("AC1032", salt="3b")),
                ("КЖ1/сАБ.txt", b"note"),
            ],
        ),
    )
    # 7z with bidi characters, a copy of a manifest PDF (DUPLICATE) and an unlisted PDF.
    fake.add(
        "F0007",
        TRAIN,
        f"{a}/РД/АР/ОБЪ-РД-АР.7z",
        stage="RD",
        builder=lambda p: make_7z(
            p,
            [
                ("АР‬/Копия АР.pdf", (fake.docs / f"{a}/ПД/3 Архитектурные решения/АР.pdf").read_bytes()),
                ("АР/Приложение.pdf", b"%PDF-1.4\n%%EOF\n"),
                ("АР/Пояснения.docx", b"PK\x03\x04" + b"\x00" * 30),
            ],
        ),
    )
    # RAR4 with OEM (cp866) names; no PDF twin in its folder.
    fake.add(
        "F0008",
        TRAIN,
        f"{a}/РД/ЭОМ/ЭОМ.rar",
        stage="RD",
        builder=lambda p: make_rar4(
            p, [("ЭОМ/Лист 1.dwg", dwg_bytes("AC1021")), ("ЭОМ/readme.txt", b"hello")]
        ),
    )
    # Loose DWG + DOCX with a same-folder PDF twin.
    fake.add("F0009", TRAIN, f"{a}/РД/АР/АР-5.dwg", stage="RD", data=dwg_bytes("AC1024", 512))
    fake.add(
        "F0010",
        TRAIN,
        f"{a}/РД/АР/АР-5.pdf",
        stage="RD",
        builder=lambda p: make_pdf(p, ["РАБОЧАЯ ДОКУМЕНТАЦИЯ АР-5"]),
    )
    fake.add(
        "F0011",
        TRAIN,
        f"{a}/РД/АР/П_АР-5_Изм.1.docx",
        stage="RD",
        builder=lambda p: make_docx(p, "Изменение 1"),
    )
    # Missing, altered and renamed files.
    fake.add(
        "F0012",
        TRAIN,
        f"{a}/ИД/Акт отсутствует.pdf",
        stage="ID",
        builder=lambda p: make_pdf(p, ["АКТ"]),
        write=False,
    )
    fake.add(
        "F0013",
        TRAIN,
        f"{a}/ИД/Изменённый.pdf",
        stage="ID",
        builder=lambda p: make_pdf(p, ["АКТ приемки"]),
        sha_override="0" * 64,
    )
    renamed = fake.add(
        "F0014",
        TRAIN,
        f"{a}/ИД/Исходное имя.pdf",
        stage="ID",
        builder=lambda p: make_pdf(p, ["АКТ испытания"]),
    )
    shutil.move(fake.docs / renamed["relative_path"], fake.docs / f"{a}/ИД/Другое имя.pdf")
    # Exact duplicate pair and near-duplicate pair.
    fake.add(
        "F0015",
        TRAIN,
        f"{a}/ПД/Копии/Том 1.pdf",
        builder=lambda p: make_pdf(p, ["Проектная документация Том 1 содержание раздела", "стр 2"]),
    )
    fake.add(
        "F0016",
        TRAIN,
        f"{a}/ПД/Копии/Том 1 (копия).pdf",
        data=(fake.docs / f"{a}/ПД/Копии/Том 1.pdf").read_bytes(),
    )
    fake.add(
        "F0017",
        TRAIN,
        f"{a}/ПД/Копии/Том 1 изм.pdf",
        builder=lambda p: make_pdf(p, ["Проектная документация Том 1 содержание раздела", "стр 2 изменена"]),
    )
    # Excluded id in the manifest and a hidden object with one PDF.
    fake.add("F0999", TRAIN, f"{a}/ПД/Исключённый.pdf", builder=lambda p: make_pdf(p, ["x"]))
    fake.add(
        "F0100",
        HIDDEN,
        "Объект Z/Рабочая и исполнительная документация/АОСР №7.pdf",
        stage="RD_ID_MIXED",
        builder=lambda p: make_pdf(p, ["АКТ освидетельствования скрытых работ № 7"]),
    )
    fake.write_manifest()
    return fake


@pytest.fixture()
def build() -> SimpleNamespace:
    return SimpleNamespace(
        pdf=make_pdf,
        zip=make_zip,
        zip_info=RawNameZipInfo,
        seven_z=make_7z,
        rar4=make_rar4,
        docx=make_docx,
        dwg=dwg_bytes,
        sha256=sha256,
        new_fake=new_fake,
        full_fixture=full_fixture,
        TRAIN=TRAIN,
        TRAIN_B=TRAIN_B,
        HIDDEN=HIDDEN,
    )


@pytest.fixture()
def fake(tmp_path: Path) -> FakeData:
    return full_fixture(tmp_path)


@pytest.fixture(scope="session")
def real_paths() -> DataPaths:
    """Organizer data; tests marked ``data`` skip when it is absent."""
    paths = Settings().paths
    if not paths.has_package():
        pytest.skip(f"organizer data not found under {paths.data_root}")
    return paths
