from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from inspector_registry import filetypes
from inspector_registry.archives import (
    ArchiveLimits,
    ArchiveListing,
    UnsafeMemberError,
    extract_member,
    list_archive,
    read_member_bytes,
)


def _by_path(listing: ArchiveListing) -> dict[str, object]:
    return {m.path: m for m in listing.members}


def test_zip_cp866_and_utf8_names_types_versions_and_hashes(build, tmp_path: Path) -> None:
    dwg = build.dwg("AC1027", salt="x")
    legacy = build.zip(
        tmp_path / "legacy.zip",
        [("Раздел КЖ/Лист 5.dwg", dwg), ("Раздел КЖ/Общие данные.pdf", b"%PDF-1.7\n%%EOF\n")],
    )
    listing = list_archive(legacy)
    assert listing.format == "zip" and listing.backend == "zipfile"
    members = _by_path(listing)
    sheet = members["Раздел КЖ/Лист 5.dwg"]
    assert sheet.name_encoding == "cp866"
    assert sheet.media_type == filetypes.DWG
    assert (sheet.dwg_version, sheet.dwg_release) == ("AC1027", "AutoCAD 2013–2017")
    assert sheet.sha256 == hashlib.sha256(dwg).hexdigest()
    assert members["Раздел КЖ/Общие данные.pdf"].media_type == filetypes.PDF
    modern = build.zip(tmp_path / "modern.zip", [("Имя/файл.txt", b"x")], codec=None)
    assert list_archive(modern).members[0].name_encoding == "utf-8"


def test_zip_unicode_path_extra_field_wins_over_legacy_name(build, tmp_path: Path) -> None:
    """7-Zip/WinRAR store a cp866 name plus the Info-ZIP Unicode Path field (0x7075)."""
    import struct
    import zlib

    name = "Раздел КЖ/Лист 7.dwg"
    legacy = name.encode("cp866")
    unicode_name = name.encode("utf-8")
    path = tmp_path / "upath.zip"
    with zipfile.ZipFile(path, "w") as zf:
        info = build.zip_info(name, "cp866")  # legacy bytes, no UTF-8 flag
        info.extra = struct.pack("<HHBL", 0x7075, 5 + len(unicode_name), 1, zlib.crc32(legacy)) + unicode_name
        zf.writestr(info, build.dwg("AC1032"))
    listing = list_archive(path)
    assert listing.backend == "zipfile" and listing.error is None
    member = listing.members[0]
    assert member.path == name and member.name_encoding == "unicode"
    assert read_member_bytes(path, name).startswith(b"AC1032")


def test_7z_names_with_bidi_characters(build, tmp_path: Path) -> None:
    path = build.seven_z(
        tmp_path / "a.7z", [("Папка‬/Лист‬ 3.dwg", build.dwg("AC1032")), ("Папка/doc.pdf", b"%PDF-1.4\n")]
    )
    listing = list_archive(path)
    assert listing.format == "7z" and listing.backend == "libarchive"
    members = _by_path(listing)
    assert set(members) == {"Папка/Лист 3.dwg", "Папка/doc.pdf"}
    bidi = members["Папка/Лист 3.dwg"]
    assert bidi.format_chars_removed == 2 and bidi.raw_name == "Папка‬/Лист‬ 3.dwg"
    assert bidi.dwg_version == "AC1032"


def test_rar4_oem_names_via_libarchive(build, tmp_path: Path) -> None:
    path = build.rar4(tmp_path / "a.rar", [("ЭОМ/Лист 1.dwg", build.dwg("AC1021")), ("readme.txt", b"hello")])
    listing = list_archive(path)
    assert listing.format.startswith("rar") and listing.backend == "libarchive"
    assert listing.error is None
    members = _by_path(listing)
    assert members["ЭОМ/Лист 1.dwg"].name_encoding == "cp866"
    assert members["ЭОМ/Лист 1.dwg"].dwg_version == "AC1021"
    assert members["readme.txt"].sha256 == hashlib.sha256(b"hello").hexdigest()


def test_ratio_guard_stops_decompression(build, tmp_path: Path) -> None:
    path = build.zip(tmp_path / "bomb.zip", [("zeros.bin", b"\x00" * 400_000)], codec=None)
    limits = ArchiveLimits(max_ratio=10, ratio_floor=1024)
    listing = list_archive(path, limits)
    assert listing.bomb_suspected and "степень сжатия" in (listing.bomb_reason or "")
    assert listing.members[0].sha256 is None and listing.read_bytes == 0  # nothing decompressed


def test_total_size_guard_on_actual_bytes_for_libarchive(build, tmp_path: Path) -> None:
    path = build.seven_z(tmp_path / "big.7z", [(f"f{i}.bin", bytes([i]) * 50_000) for i in range(4)])
    listing = list_archive(path, ArchiveLimits(max_total_uncompressed=120_000, ratio_floor=10**12))
    assert listing.truncated and listing.bomb_suspected
    assert len(listing.members) < 4


def test_member_count_guard(build, tmp_path: Path) -> None:
    path = build.zip(tmp_path / "many.zip", [(f"f{i}.txt", b"x") for i in range(6)], codec=None)
    listing = list_archive(path, ArchiveLimits(max_members=3))
    assert listing.too_many_members and listing.truncated
    assert listing.members_declared == 6 and len(listing.members) == 3


def test_traversal_names_are_flagged_and_never_extracted(build, tmp_path: Path) -> None:
    path = build.zip(tmp_path / "evil.zip", [("../../evil.txt", b"x"), ("ok/fine.txt", b"y")], codec=None)
    listing = list_archive(path)
    evil = next(m for m in listing.members if m.raw_name == "../../evil.txt")
    assert "выход за пределы архива («..»)" in evil.problems
    assert evil.path == "evil.txt"  # the safe path used in the virtual id
    dest = tmp_path / "out"
    with pytest.raises(UnsafeMemberError):
        extract_member(path, "../../evil.txt", dest)
    target = extract_member(path, "ok/fine.txt", dest)
    assert target == (dest / "ok" / "fine.txt").resolve() and target.read_bytes() == b"y"
    assert not (tmp_path / "evil.txt").exists()


def test_read_member_bytes_from_libarchive_formats(build, tmp_path: Path) -> None:
    path = build.rar4(tmp_path / "a.rar", [("ЭОМ/Лист 1.dwg", build.dwg("AC1021"))])
    assert read_member_bytes(path, "ЭОМ/Лист 1.dwg").startswith(b"AC1021")
    with pytest.raises(UnsafeMemberError):
        read_member_bytes(path, "ЭОМ/Лист 1.dwg", max_bytes=10)
    with pytest.raises(KeyError):
        read_member_bytes(path, "нет/такого.dwg")


def test_encrypted_members_are_not_read(build, tmp_path: Path) -> None:
    path = build.zip(
        tmp_path / "enc.zip",
        [("secret.pdf", b"%PDF-1.4"), ("open.txt", b"x")],
        codec=None,
        encrypted={"secret.pdf"},
    )
    listing = list_archive(path)
    assert listing.encrypted
    secret = next(m for m in listing.members if m.path == "secret.pdf")
    assert secret.encrypted and secret.sha256 is None and secret.media_type is None


def test_corrupt_archive_reports_error_instead_of_raising(tmp_path: Path) -> None:
    path = tmp_path / "broken.zip"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    listing = list_archive(path)
    assert listing.error


def test_crc_error_is_a_member_read_error(build, tmp_path: Path) -> None:
    path = build.zip(tmp_path / "crc.zip", [("a.txt", b"hello world" * 100)], codec=None)
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as zf:
        info = zf.infolist()[0]
    offset = info.header_offset + 30 + len(info.filename.encode()) + 5
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))
    listing = list_archive(path)
    assert listing.members[0].read_error


def test_listing_json_roundtrip(build, tmp_path: Path) -> None:
    path = build.zip(tmp_path / "a.zip", [("Лист 1.dwg", build.dwg())])
    listing = list_archive(path)
    again = ArchiveListing.from_json(listing.to_json())
    assert again.to_json() == listing.to_json()


def test_sniffing_table() -> None:
    assert filetypes.sniff(b"%PDF-1.7") == filetypes.PDF
    assert filetypes.sniff(b"PK\x03\x04", ".docx") == filetypes.DOCX
    assert filetypes.sniff(b"PK\x03\x04", ".zip") == filetypes.ZIP
    assert filetypes.sniff(b"7z\xbc\xaf\x27\x1c") == filetypes.SEVEN_Z
    assert filetypes.sniff(b"Rar!\x1a\x07\x01\x00") == filetypes.RAR
    assert filetypes.sniff(b"MZ\x90\x00") == filetypes.EXECUTABLE
    assert filetypes.sniff(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") == filetypes.OLE
    assert filetypes.sniff(b"  0\r\nSECTION\r\n", ".dxf") == filetypes.DXF
    assert filetypes.sniff(b"\x00\x01", ".bin") == filetypes.OCTET
    assert filetypes.dwg_version(b"AC1015\x00") is not None
    assert filetypes.dwg_version(b"AC9999") is None
    assert filetypes.is_executable(filetypes.OCTET, ".bat")
