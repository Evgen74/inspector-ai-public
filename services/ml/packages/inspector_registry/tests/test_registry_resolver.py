from __future__ import annotations

import os
import shutil
import unicodedata
from pathlib import Path

from inspector_common.contracts.enums import LocalFileStatus
from inspector_registry.cache import RegistryCache
from inspector_registry.manifest import Registry
from inspector_registry.resolver import PathResolver


def _resolver(fake, cache: RegistryCache | None = None) -> tuple[Registry, PathResolver]:
    reg = Registry.load(fake.paths)
    return reg, PathResolver(reg, fake.paths, cache)


def test_present_missing_altered_renamed(fake) -> None:
    reg, res = _resolver(fake)
    out = {r.file_id: r for r in res.resolve_many(reg.files("OBJ-TRAIN-A"), verify=False)}
    assert out["F0001"].local_status is LocalFileStatus.PRESENT
    assert out["F0001"].found_via == "manifest_path" and out["F0001"].sha256_verified is None
    # Missing: never MISSING_DOCUMENT, always the file-level status + FILE_MISSING_ON_DISK.
    assert out["F0012"].local_status is LocalFileStatus.MISSING_ON_DISK
    assert [f.code for f in out["F0012"].flags] == ["FILE_MISSING_ON_DISK"]
    assert "не означает отсутствие документа" in out["F0012"].flags[0].detail
    # Same size, other bytes: undetectable without hashing …
    assert out["F0013"].local_status is LocalFileStatus.PRESENT and out["F0013"].sha256_verified is None
    # Renamed on disk: found by sha256 among unclaimed files of the same size.
    assert out["F0014"].local_status is LocalFileStatus.RECOVERED
    assert out["F0014"].found_via == "sha256_search" and out["F0014"].path is not None
    assert out["F0014"].path.name == "Другое имя.pdf"


def test_verify_detects_altered_bytes(fake) -> None:
    reg, res = _resolver(fake)
    r = res.resolve(reg.get("F0013"), verify=True)
    assert r.local_status is LocalFileStatus.MISSING_ON_DISK
    codes = [f.code for f in r.flags]
    assert codes == ["REGISTRY_HASH_MISMATCH", "FILE_MISSING_ON_DISK"]
    assert "содержимое отличается" in (r.flags[0].note_ru or "")
    good = res.resolve(reg.get("F0001"), verify=True)
    assert good.sha256_verified is True and good.sha256_actual == reg.get("F0001").sha256


def test_size_mismatch_is_detected_without_verify(fake) -> None:
    reg, res = _resolver(fake)
    path = fake.docs / reg.get("F0001").relative_path
    with open(path, "ab") as fh:
        fh.write(b"\n%tampered\n")
    r = res.resolve(reg.get("F0001"), verify=False)
    assert r.local_status is LocalFileStatus.MISSING_ON_DISK
    assert r.flags[0].code == "REGISTRY_HASH_MISMATCH"
    assert "размер на диске" in (r.flags[0].note_ru or "")


def test_nfd_and_case_variants_resolve(build, tmp_path: Path) -> None:
    fake = build.new_fake(tmp_path)
    row = fake.add("F0001", build.TRAIN, "Папка/Изменённый лист.pdf", builder=lambda p: build.pdf(p, ["x"]))
    fake.write_manifest()
    nfc_path = fake.docs / row["relative_path"]
    nfd_path = fake.docs / unicodedata.normalize("NFD", row["relative_path"])
    data = nfc_path.read_bytes()
    nfc_path.unlink()
    nfd_path.parent.mkdir(parents=True, exist_ok=True)
    nfd_path.write_bytes(data)
    reg, res = _resolver(fake)
    r = res.resolve(reg.get("F0001"), verify=True)
    assert r.local_status is LocalFileStatus.PRESENT and r.sha256_verified is True


def test_recovery_ledger_marks_recovered(build, tmp_path: Path) -> None:
    fake = build.new_fake(tmp_path)
    row = fake.add("F0001", build.TRAIN, "Папка/Акт.pdf", builder=lambda p: build.pdf(p, ["АКТ"]))
    fake.add("F0002", build.TRAIN, "Папка/Схема.pdf", builder=lambda p: build.pdf(p, ["Схема"]))
    fake.write_manifest()
    rel_from_parent = Path("data_utf8").joinpath(
        *fake.docs.relative_to(fake.root).parts, row["relative_path"]
    )
    (fake.root / "_recovered_files.txt").write_text(
        f"Recovered from the organizers' archive\nF0001\t{rel_from_parent}\nfree text line\n",
        encoding="utf-8",
    )
    reg, res = _resolver(fake)
    assert set(res.ledger) == {"F0001"}
    r1 = res.resolve(reg.get("F0001"), verify=True)
    r2 = res.resolve(reg.get("F0002"), verify=True)
    assert r1.local_status is LocalFileStatus.RECOVERED and r1.found_via == "recovery_ledger"
    assert r2.local_status is LocalFileStatus.PRESENT


def test_recovery_dir_is_searched_by_sha256(build, tmp_path: Path) -> None:
    fake = build.new_fake(tmp_path)
    row = fake.add("F0001", build.TRAIN, "Папка/Акт.pdf", builder=lambda p: build.pdf(p, ["АКТ"]))
    fake.write_manifest()
    src = fake.docs / row["relative_path"]
    recovered_dir = tmp_path / "data_recovered" / "obj"
    recovered_dir.mkdir(parents=True)
    shutil.move(src, recovered_dir / "F0001.pdf")
    reg, res = _resolver(fake)
    r = res.resolve(reg.get("F0001"))
    assert r.local_status is LocalFileStatus.RECOVERED and r.found_via == "sha256_search"
    assert r.path == recovered_dir / "F0001.pdf"


def test_sha256_cache_is_keyed_by_path_size_mtime(fake, tmp_path: Path) -> None:
    cache = RegistryCache(tmp_path / "cache" / "registry.sqlite")
    reg, res = _resolver(fake, cache)
    files = [reg.get("F0001"), reg.get("F0005")]
    res.resolve_many(files, verify=True)
    assert res.hashed_files == 2
    # Second pass: everything from the cache, and verified without hashing.
    _reg2, res2 = _resolver(fake, cache)
    out = res2.resolve_many(files, verify=False)
    assert res2.hashed_files == 0
    assert all(r.sha256_verified is True for r in out)
    # Touching a file changes mtime → cache miss → rehash on verify.
    path = fake.docs / reg.get("F0001").relative_path
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    res3 = PathResolver(reg, fake.paths, cache)
    out3 = res3.resolve(reg.get("F0001"), verify=False)
    assert out3.sha256_verified is None
    res3.resolve_many([reg.get("F0001")], verify=True)
    assert res3.hashed_files == 1
    cache.close()


def test_shared_inode_with_different_hashes_is_ambiguous(build, tmp_path: Path) -> None:
    fake = build.new_fake(tmp_path)
    a = fake.add("F0001", build.TRAIN, "Папка/АЗ.pdf", builder=lambda p: build.pdf(p, ["А"]))
    b = fake.add("F0002", build.TRAIN, "Папка/РЗ.pdf", builder=lambda p: build.pdf(p, ["Р"]))
    fake.write_manifest()
    # Emulate two names merged into one file (e.g. by a case-insensitive volume).
    (fake.docs / b["relative_path"]).unlink()
    os.link(fake.docs / a["relative_path"], fake.docs / b["relative_path"])
    reg, res = _resolver(fake)
    out = res.resolve_many(reg.files(build.TRAIN), verify=False)
    ambiguous = [r.file_id for r in out if any(f.code == "REGISTRY_AMBIGUOUS_MATCH" for f in r.flags)]
    assert sorted(ambiguous) == ["F0001", "F0002"]


def test_open_registry_api(fake, tmp_path: Path) -> None:
    from inspector_common.settings import Settings
    from inspector_registry.api import open_registry

    settings = Settings(data_root=fake.root, cache_root=tmp_path / "c", runs_root=tmp_path / "r")
    reg, res = open_registry(settings)
    readable = [r.file_id for r in res.resolve_many(reg.files("OBJ-TRAIN-A")) if r.readable]
    assert "F0001" in readable and "F0012" not in readable
    assert (tmp_path / "c" / "registry" / "registry_cache.sqlite").is_file()
    res.cache.close()
