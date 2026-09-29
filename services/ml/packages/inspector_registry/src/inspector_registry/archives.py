"""Archive inventory for zip / 7z / rar without ever calling ``unrar`` (CLAUDE.md rule 5).

Backends:
- zip → Python ``zipfile`` (it exposes the general-purpose bit 11 «UTF-8 name», so flag-less legacy
  names are decoded cp437 → bytes → cp866 without guessing; libarchive hides the flag and may
  mis-decode cp866 bytes that happen to be valid UTF-8); libarchive is the fallback;
- 7z, rar (RAR4 and RAR5) and anything else → libarchive-c against the system libarchive (the same
  library as ``bsdtar``); raw name bytes are decoded by plausibility (UTF-8 vs cp866).

Guards (97 §2.12): ≤ 5,000 members, ≤ 2 GiB uncompressed (declared and actually read), compression
ratio limits, no path traversal / absolute paths / links. Nothing is written to disk by the listing;
``extract_member`` writes one member into a directory of ours after the same checks.

Members are never citable (97 §2.5); they are registered with a virtual id «F0006!path».
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import stat
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from inspector_registry import filetypes
from inspector_registry.names import (
    decode_member_name,
    member_path_problems,
    safe_member_path,
    split_stem,
    zip_raw_name,
)

# libarchive-c logs an INFO line at import about optional digest support; it is noise here.
logging.getLogger("libarchive").setLevel(logging.WARNING)

LISTING_VERSION = "archive-listing-2"  # 2: zip Unicode Path extra field (0x7075)
_READ_BLOCK = 1 << 20


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_members: int = 5000
    max_total_uncompressed: int = 16 * 1024**3  # an upload package may be up to 5 GB (stored PDFs)
    max_ratio: float = 100.0  # total uncompressed / archive size …
    ratio_floor: int = 64 * 1024**2  # … checked only above this many uncompressed bytes
    max_member_ratio: float = 1000.0  # per member (zip: compressed size is known) …
    member_ratio_floor: int = 16 * 1024**2  # … above this member size
    hash_members: bool = True

    def as_config(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArchiveMember:
    index: int
    path: str  # decoded, NFC, format characters removed, safe relative POSIX path
    raw_name: str  # decoded, not cleaned (audit)
    name_encoding: str
    format_chars_removed: int
    is_dir: bool
    is_link: bool
    size: int | None  # declared uncompressed size
    compressed_size: int | None
    encrypted: bool
    extension: str
    media_type: str | None = None  # sniffed from the data (None when not read)
    dwg_version: str | None = None
    dwg_release: str | None = None
    sha256: str | None = None
    bytes_read: int = 0
    problems: list[str] = field(default_factory=list)  # unsafe path reasons (Russian)
    read_error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ArchiveMember:
        return cls(**data)


@dataclass(slots=True)
class ArchiveListing:
    format: str  # "zip" | "7z" | "rar" | libarchive format name
    backend: str  # "zipfile" | "libarchive"
    archive_size: int
    members: list[ArchiveMember] = field(default_factory=list)
    members_declared: int | None = None  # zip: central-directory count (known before reading)
    declared_uncompressed: int = 0
    read_bytes: int = 0
    truncated: bool = False  # stopped by a guard
    bomb_suspected: bool = False
    bomb_reason: str | None = None
    too_many_members: bool = False
    encrypted: bool = False
    error: str | None = None
    listing_version: str = LISTING_VERSION

    @property
    def files(self) -> list[ArchiveMember]:
        return [m for m in self.members if not m.is_dir]

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["members"] = [m.to_json() for m in self.members]
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ArchiveListing:
        data = dict(data)
        members = [ArchiveMember.from_json(m) for m in data.pop("members", [])]
        return cls(members=members, **data)


class _Budget:
    """Actual decompressed bytes across one archive (zip-bomb guard on real data, not headers)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self, n: int) -> bool:
        self.used += n
        return self.used <= self.limit


def _consume(
    chunks: Any, member: ArchiveMember, budget: _Budget, *, hash_all: bool, limits: ArchiveLimits
) -> bool:
    """Read a member's data: head for sniffing, sha256 when ``hash_all``. False = guard tripped."""
    digest = hashlib.sha256() if hash_all else None
    head = b""
    declared = member.size
    for chunk in chunks:
        if len(head) < filetypes.HEAD_BYTES:
            head += chunk[: filetypes.HEAD_BYTES - len(head)]
        member.bytes_read += len(chunk)
        if digest is not None:
            digest.update(chunk)
        if not budget.take(len(chunk)):
            _sniff(member, head)
            return False
        if declared is not None and member.bytes_read > declared + _READ_BLOCK and declared >= 0:
            # More data than the header declared: a lying header is a classic bomb pattern.
            _sniff(member, head)
            return False
        if member.bytes_read > limits.max_total_uncompressed:
            _sniff(member, head)
            return False
        if digest is None and len(head) >= filetypes.HEAD_BYTES:
            break
    _sniff(member, head)
    if digest is not None:
        member.sha256 = digest.hexdigest()
    return True


def _sniff(member: ArchiveMember, head: bytes) -> None:
    member.media_type = filetypes.sniff(head, member.extension)
    version = filetypes.dwg_version(head)
    if version:
        member.dwg_version = version.code
        member.dwg_release = version.release


def _new_member(index: int, raw: bytes | str, utf8_flag: bool | None, **kw: Any) -> ArchiveMember:
    decoded = decode_member_name(raw, utf8_flag=utf8_flag)
    _stem, ext = split_stem(decoded.name)
    return ArchiveMember(
        index=index,
        path=safe_member_path(decoded.name),
        raw_name=decoded.raw,
        name_encoding=decoded.encoding,
        format_chars_removed=decoded.format_chars_removed,
        extension=ext,
        problems=member_path_problems(decoded.raw),
        **kw,
    )


def _ratio_guard(listing: ArchiveListing, limits: ArchiveLimits) -> None:
    total = listing.declared_uncompressed
    if total > limits.max_total_uncompressed:
        listing.bomb_suspected = True
        listing.bomb_reason = f"объявленный объём распаковки {total} байт > {limits.max_total_uncompressed}"
    elif (
        total > limits.ratio_floor
        and listing.archive_size > 0
        and total / listing.archive_size > limits.max_ratio
    ):
        listing.bomb_suspected = True
        listing.bomb_reason = (
            f"степень сжатия {total / listing.archive_size:.0f}:1 > {limits.max_ratio:.0f}:1"
        )


# ── zip (zipfile) ────────────────────────────────────────────────────────────────────────────


def _list_zip(path: Path, limits: ArchiveLimits) -> ArchiveListing:
    listing = ArchiveListing(format="zip", backend="zipfile", archive_size=path.stat().st_size)
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        listing.members_declared = len(infos)
        listing.declared_uncompressed = sum(max(zi.file_size, 0) for zi in infos)
        if len(infos) > limits.max_members:
            listing.too_many_members = True
            listing.truncated = True
        _ratio_guard(listing, limits)
        for zi in infos:
            if (
                zi.compress_size > 0
                and zi.file_size > limits.member_ratio_floor
                and zi.file_size / zi.compress_size > limits.max_member_ratio
            ):
                listing.bomb_suspected = True
                listing.bomb_reason = f"степень сжатия элемента {zi.file_size // zi.compress_size}:1"
        budget = _Budget(limits.max_total_uncompressed)
        read_data = not listing.bomb_suspected
        for index, zi in enumerate(infos[: limits.max_members]):
            raw, utf8 = zip_raw_name(zi.filename, zi.flag_bits)
            mode = zi.external_attr >> 16
            member = _new_member(
                index,
                raw,
                utf8,
                is_dir=zi.is_dir(),
                is_link=stat.S_ISLNK(mode),
                size=zi.file_size,
                compressed_size=zi.compress_size,
                encrypted=bool(zi.flag_bits & 0x1),
            )
            listing.members.append(member)
            listing.encrypted |= member.encrypted
            if not read_data or member.is_dir or member.is_link or member.encrypted:
                continue
            try:
                with zf.open(zi) as fh:
                    ok = _consume(
                        iter(lambda fh=fh: fh.read(_READ_BLOCK), b""),
                        member,
                        budget,
                        hash_all=limits.hash_members,
                        limits=limits,
                    )
            except (
                zipfile.BadZipFile,
                zlib.error,
                NotImplementedError,
                EOFError,
                OSError,
                RuntimeError,
                ValueError,
            ) as exc:
                member.read_error = f"{type(exc).__name__}: {exc}"
                continue
            if not ok:
                listing.bomb_suspected = True
                listing.bomb_reason = (
                    listing.bomb_reason or "фактический объём распаковки превышает объявленный или лимит"
                )
                listing.truncated = True
                read_data = False
        listing.read_bytes = budget.used
    return listing


# ── libarchive (7z, rar, zip fallback, others) ───────────────────────────────────────────────


def _entry_is_encrypted(entry: Any) -> bool:
    from libarchive import ffi

    fn = getattr(ffi.libarchive, "archive_entry_is_encrypted", None)
    if fn is None:  # pragma: no cover - libarchive < 3.2
        return False
    fn.argtypes = [ctypes.c_void_p]
    fn.restype = ctypes.c_int
    return fn(entry._entry_p) > 0


def _entry_raw_name(entry: Any) -> bytes | str:
    from libarchive import ffi

    raw = ffi.entry_pathname(entry._entry_p)
    if raw:
        return bytes(raw)
    name = entry.pathname
    return name if name is not None else ""


def _list_libarchive(path: Path, limits: ArchiveLimits, fmt_hint: str) -> ArchiveListing:
    import libarchive
    from libarchive import ffi
    from libarchive.exception import ArchiveError

    listing = ArchiveListing(format=fmt_hint, backend="libarchive", archive_size=path.stat().st_size)
    budget = _Budget(limits.max_total_uncompressed)
    read_data = True
    try:
        with libarchive.file_reader(str(path)) as reader:
            for index, entry in enumerate(reader):
                if index == 0:
                    name = ffi.format_name(reader._pointer)
                    if name:
                        listing.format = _short_format(name.decode("ascii", "replace"), fmt_hint)
                if index >= limits.max_members:
                    listing.too_many_members = True
                    listing.truncated = True
                    break
                size = entry.size if entry.size is not None else None
                member = _new_member(
                    index,
                    _entry_raw_name(entry),
                    None,
                    is_dir=bool(entry.isdir),
                    is_link=bool(entry.issym or entry.islnk),
                    size=size,
                    compressed_size=None,
                    encrypted=_entry_is_encrypted(entry),
                )
                listing.members.append(member)
                listing.encrypted |= member.encrypted
                listing.declared_uncompressed += max(size or 0, 0)
                if listing.declared_uncompressed > limits.max_total_uncompressed:
                    _ratio_guard(listing, limits)
                    listing.truncated = True
                    break
                if not read_data or member.is_dir or member.is_link or member.encrypted:
                    continue
                try:
                    ok = _consume(
                        entry.get_blocks(_READ_BLOCK),
                        member,
                        budget,
                        hash_all=limits.hash_members,
                        limits=limits,
                    )
                except ArchiveError as exc:
                    member.read_error = str(exc)
                    if "ncrypt" in str(exc) or "assphrase" in str(exc):
                        member.encrypted = True
                        listing.encrypted = True
                    continue
                if not ok:
                    listing.bomb_suspected = True
                    listing.bomb_reason = "фактический объём распаковки превышает объявленный или лимит"
                    listing.truncated = True
                    break
    except ArchiveError as exc:
        listing.error = str(exc)
        if "ncrypt" in str(exc) or "assphrase" in str(exc):
            listing.encrypted = True
    if not listing.bomb_suspected:
        _ratio_guard(listing, limits)
    listing.read_bytes = budget.used
    return listing


def _short_format(libarchive_name: str, hint: str) -> str:
    low = libarchive_name.lower()
    if "7-zip" in low or "7zip" in low:
        return "7z"
    if "rar5" in low:
        return "rar5"
    if "rar" in low:
        return "rar"
    if "zip" in low:
        return "zip"
    return hint or low


def _detect_format(path: Path) -> str:
    with open(path, "rb") as fh:
        head = fh.read(filetypes.HEAD_BYTES)
    media = filetypes.sniff(head, path.suffix)
    return {filetypes.ZIP: "zip", filetypes.SEVEN_Z: "7z", filetypes.RAR: "rar"}.get(
        media, path.suffix.lstrip(".").lower()
    )


def list_archive(path: Path, limits: ArchiveLimits | None = None) -> ArchiveListing:
    """List an archive with guards; never raises for a corrupt archive (``error`` is set instead)."""
    limits = limits or ArchiveLimits()
    fmt = _detect_format(path)
    if fmt == "zip":
        try:
            return _list_zip(path, limits)
        except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError, OSError, ValueError) as exc:
            fallback = _list_libarchive(path, limits, "zip")
            if fallback.error:
                fallback.error = f"zipfile: {exc}; libarchive: {fallback.error}"
            return fallback
    return _list_libarchive(path, limits, fmt)


# ── safe extraction of one member ────────────────────────────────────────────────────────────


class UnsafeMemberError(ValueError):
    pass


def read_member_bytes(archive: Path, member_path: str, *, max_bytes: int = 512 * 1024**2) -> bytes:
    """Bytes of one member (matched by its safe path), with the size guard applied while reading."""
    fmt = _detect_format(archive)
    if fmt == "zip":
        with zipfile.ZipFile(archive) as zf:
            for zi in zf.infolist():
                raw, utf8 = zip_raw_name(zi.filename, zi.flag_bits)
                decoded = decode_member_name(raw, utf8_flag=utf8)
                if safe_member_path(decoded.name) != member_path or zi.is_dir():
                    continue
                if stat.S_ISLNK(zi.external_attr >> 16):
                    raise UnsafeMemberError(f"{member_path}: ссылка, не извлекается")
                if zi.file_size > max_bytes:
                    raise UnsafeMemberError(f"{member_path}: {zi.file_size} байт > {max_bytes}")
                with zf.open(zi) as fh:
                    data = fh.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise UnsafeMemberError(f"{member_path}: больше {max_bytes} байт")
                return data
        raise KeyError(member_path)
    import libarchive

    with libarchive.file_reader(str(archive)) as reader:
        for entry in reader:
            decoded = decode_member_name(_entry_raw_name(entry), utf8_flag=None)
            if safe_member_path(decoded.name) != member_path or entry.isdir:
                continue
            if entry.issym or entry.islnk:
                raise UnsafeMemberError(f"{member_path}: ссылка, не извлекается")
            out = bytearray()
            for block in entry.get_blocks(_READ_BLOCK):
                out += block
                if len(out) > max_bytes:
                    raise UnsafeMemberError(f"{member_path}: больше {max_bytes} байт")
            return bytes(out)
    raise KeyError(member_path)


def extract_member(
    archive: Path, member_path: str, dest_dir: Path, *, max_bytes: int = 512 * 1024**2
) -> Path:
    """Write one member under ``dest_dir`` (never outside it). ``dest_dir`` must be ours (cache/runs)."""
    problems = member_path_problems(member_path)
    safe = safe_member_path(member_path)
    if problems or not safe:
        raise UnsafeMemberError(f"{member_path}: {', '.join(problems) or 'пустой путь'}")
    root = dest_dir.resolve()
    target = (root / safe).resolve()
    if root != target and root not in target.parents:
        raise UnsafeMemberError(f"{member_path}: выход за пределы каталога извлечения")
    data = read_member_bytes(archive, safe, max_bytes=max_bytes)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target
