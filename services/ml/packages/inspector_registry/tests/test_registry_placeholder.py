"""AG-00 placeholder tests for inspector_registry (AG-01 replaces/extends them)."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import inspector_registry
from inspector_registry import batch


def test_package_imports() -> None:
    assert inspector_registry.__version__
    assert batch.OWNER == "AG-01"


def test_libarchive_reads_a_zip_with_cyrillic_names(tmp_path: Path) -> None:
    """libarchive-c works against the system libarchive (97: archives via bsdtar/libarchive, never unrar)."""
    libarchive = pytest.importorskip("libarchive")
    archive = tmp_path / "ИД.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Раздел АР/лист 1.dwg", b"AC1032" + b"\0" * 10)
        zf.writestr("Раздел АР/лист 1.pdf", b"%PDF-1.7\n")
    with libarchive.file_reader(str(archive)) as reader:
        names = sorted(entry.pathname for entry in reader)
    assert names == ["Раздел АР/лист 1.dwg", "Раздел АР/лист 1.pdf"]


def test_bsdtar_is_available_for_listing(tmp_path: Path) -> None:
    bsdtar = shutil.which("bsdtar")
    if bsdtar is None:
        pytest.skip("bsdtar not on PATH")
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("x.txt", b"x")
    out = subprocess.run(
        [bsdtar, "-tf", str(archive)], capture_output=True, text=True, check=True, timeout=30
    )
    assert out.stdout.split() == ["x.txt"]
