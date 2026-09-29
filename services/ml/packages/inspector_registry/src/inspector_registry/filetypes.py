"""Content-type sniffing by magic bytes (never by extension alone) and DWG header versions.

Types are reported as standard media types (IANA or widely used x- types), not as our own enum.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEAD_BYTES = 64

PDF = "application/pdf"
DWG = "image/vnd.dwg"
DXF = "image/vnd.dxf"
ZIP = "application/zip"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
OLE = "application/x-ole-storage"  # legacy .doc/.xls
SEVEN_Z = "application/x-7z-compressed"
RAR = "application/vnd.rar"
GZIP = "application/gzip"
PNG = "image/png"
JPEG = "image/jpeg"
TIFF = "image/tiff"
GIF = "image/gif"
BMP = "image/bmp"
XML = "application/xml"
RTF = "application/rtf"
TEXT = "text/plain"
EXECUTABLE = "application/x-executable"
OCTET = "application/octet-stream"

ARCHIVE_TYPES = frozenset({ZIP, SEVEN_Z, RAR, GZIP})
OOXML_BY_EXT = {".docx": DOCX, ".docm": DOCX, ".xlsx": XLSX, ".xlsm": XLSX, ".pptx": PPTX}
EXECUTABLE_EXTENSIONS = frozenset(
    {
        ".exe",
        ".com",
        ".bat",
        ".cmd",
        ".scr",
        ".msi",
        ".dll",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".wsf",
        ".ps1",
        ".sh",
        ".jar",
        ".lnk",
        ".app",
    }
)
IGNORED_NAMES = frozenset({"thumbs.db", "desktop.ini", ".ds_store"})
IGNORED_EXTENSIONS = frozenset({".bak", ".dwl", ".dwl2", ".tmp", ".log", ".err", ".sv$", ".ac$"})

# DWG «AC10xx» header codes → AutoCAD release family (public format history).
DWG_RELEASES: dict[str, str] = {
    "MC0.0": "R1.0",
    "AC1.2": "R1.2",
    "AC1.4": "R1.4",
    "AC1.50": "R2.0",
    "AC2.10": "R2.10",
    "AC1001": "R2.2",
    "AC1002": "R2.5",
    "AC1003": "R2.6",
    "AC1004": "R9",
    "AC1006": "R10",
    "AC1009": "R11/R12",
    "AC1012": "R13",
    "AC1014": "R14",
    "AC1015": "AutoCAD 2000–2002",
    "AC1018": "AutoCAD 2004–2006",
    "AC1021": "AutoCAD 2007–2009",
    "AC1024": "AutoCAD 2010–2012",
    "AC1027": "AutoCAD 2013–2017",
    "AC1032": "AutoCAD 2018+",
}
_DWG_HEAD = re.compile(rb"^(AC1\d{3}|AC1\.\d{1,2}|AC2\.10|MC0\.0)")
_DXF_HEAD = re.compile(rb"^\s*0\s*\r?\n\s*SECTION", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DwgVersion:
    code: str  # e.g. "AC1032"
    release: str  # e.g. "AutoCAD 2018+" or "unknown"


def dwg_version(head: bytes) -> DwgVersion | None:
    m = _DWG_HEAD.match(head[:8])
    if not m:
        return None
    code = m.group(1).decode("ascii")
    return DwgVersion(code=code, release=DWG_RELEASES.get(code, "unknown"))


def sniff(head: bytes, extension: str = "") -> str:
    """Media type from the first bytes; ``extension`` only disambiguates containers (zip → docx)."""
    ext = extension.lower()
    if head.startswith(b"%PDF-") or (b"%PDF-" in head[:1024] and ext == ".pdf"):
        return PDF
    if dwg_version(head):
        return DWG
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return OOXML_BY_EXT.get(ext, ZIP)
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return SEVEN_Z
    if head.startswith(b"Rar!\x1a\x07"):
        return RAR
    if head.startswith(b"\x1f\x8b"):
        return GZIP
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return OLE
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return TIFF
    if head.startswith((b"GIF87a", b"GIF89a")):
        return GIF
    if head.startswith(b"BM") and ext == ".bmp":
        return BMP
    if head.startswith(b"{\\rtf"):
        return RTF
    if head.startswith(
        (
            b"MZ",
            b"\x7fELF",
            b"\xca\xfe\xba\xbe",
            b"\xfe\xed\xfa\xce",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
            b"\xce\xfa\xed\xfe",
        )
    ):
        return EXECUTABLE
    if head.startswith(b"#!"):
        return EXECUTABLE
    stripped = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if stripped.startswith(b"<?xml") or (stripped.startswith(b"<") and ext == ".xml"):
        return XML
    if _DXF_HEAD.match(head) or (ext == ".dxf" and b"SECTION" in head):
        return DXF
    if ext in (".txt", ".csv") and head and b"\x00" not in head:
        return TEXT
    return OCTET


def expected_types(extension: str) -> frozenset[str] | None:
    """Media types acceptable for a manifest extension (None = no expectation)."""
    ext = extension.lower()
    table: dict[str, frozenset[str]] = {
        ".pdf": frozenset({PDF}),
        ".zip": frozenset({ZIP}),
        ".7z": frozenset({SEVEN_Z}),
        ".rar": frozenset({RAR}),
        ".dwg": frozenset({DWG}),
        ".dxf": frozenset({DXF}),
        ".docx": frozenset({DOCX}),
        ".xlsx": frozenset({XLSX}),
        ".doc": frozenset({OLE, RTF}),
        ".xls": frozenset({OLE}),
        ".xml": frozenset({XML}),
    }
    return table.get(ext)


def is_executable(media_type: str, extension: str) -> bool:
    return media_type == EXECUTABLE or extension.lower() in EXECUTABLE_EXTENSIONS
