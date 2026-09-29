"""File and archive-member name helpers: NFC, bidi/format-character stripping, legacy code pages.

97 §2.12: archive names are decoded cp437→cp866 when the zip UTF-8 flag is absent, and Unicode
format characters (category Cf, which includes the bidi controls U+200E/F, U+202A–U+202E and
U+2066–U+2069) are stripped. Raw names are kept separately for audit.

Everything here is pure (no I/O) and deterministic.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

# Characters we expect in Russian construction document names. Used only to choose between two
# candidate decodings of a legacy (flag-less) name, never to reject a name.
_PLAUSIBLE_RANGES: tuple[tuple[int, int], ...] = (
    (0x20, 0x7E),  # printable ASCII
    (0xA0, 0xFF),  # Latin-1 punctuation and letters (« » ° № in some fonts)
    (0x0400, 0x04FF),  # Cyrillic
    (0x2010, 0x2027),  # dashes, quotes, bullets
    (0x2030, 0x205E),  # per-mille, primes, misc punctuation
    (0x2116, 0x2116),  # №
)

_LATIN_TO_CYRILLIC = str.maketrans(
    {
        "a": "а",
        "b": "в",
        "c": "с",
        "e": "е",
        "h": "н",
        "k": "к",
        "m": "м",
        "o": "о",
        "p": "р",
        "t": "т",
        "x": "х",
        "y": "у",
    }
)
_SEPARATORS = re.compile(r"[\s_\-.,;:()\[\]{}«»\"'`+=#№]+")
_MAX_MEMBER_NAME = 1024
_MAX_MEMBER_DEPTH = 64


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def strip_format_chars(text: str) -> tuple[str, int]:
    """Remove Unicode Cf (format, incl. bidi) and Cc (control) characters; return (text, removed)."""
    kept = [ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cc")]
    return "".join(kept), len(text) - len(kept)


def clean_name(text: str) -> tuple[str, int]:
    """NFC + format/control characters removed. Returns (clean, removed_count)."""
    cleaned, removed = strip_format_chars(text)
    return nfc(cleaned), removed


def plausibility(text: str) -> float:
    """Share of characters inside the ranges typical for Russian document names (0…1)."""
    if not text:
        return 1.0
    good = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in _PLAUSIBLE_RANGES))
    return good / len(text)


@dataclass(frozen=True, slots=True)
class DecodedName:
    name: str  # decoded, NFC, format characters removed
    raw: str  # decoded but not cleaned (what the archive literally says)
    encoding: str  # codec used: "utf-8", "cp866", "ascii" or "unicode" (already text in the container)
    format_chars_removed: int


def decode_member_name(raw: bytes | str, *, utf8_flag: bool | None = None) -> DecodedName:
    """Decode an archive member name.

    - ``str`` input (7z, RAR5 and flagged zip names come as Unicode already): kept as is.
    - ``utf8_flag=True`` (zip general-purpose bit 11): UTF-8.
    - otherwise (legacy zip without the flag, RAR4 OEM names): ASCII if possible, else the more
      plausible of UTF-8 and cp866 (DOS Cyrillic). cp866 is what Russian Windows archivers write;
      UTF-8 without the flag is what some macOS/Linux tools write.
    """
    if isinstance(raw, str):
        decoded, encoding = raw, "unicode"
    elif utf8_flag:
        decoded, encoding = raw.decode("utf-8", errors="replace"), "utf-8"
    else:
        try:
            decoded, encoding = raw.decode("ascii"), "ascii"
        except UnicodeDecodeError:
            as_cp866 = raw.decode("cp866")
            try:
                as_utf8: str | None = raw.decode("utf-8")
            except UnicodeDecodeError:
                as_utf8 = None
            if as_utf8 is not None and plausibility(as_utf8) >= plausibility(as_cp866):
                decoded, encoding = as_utf8, "utf-8"
            else:
                decoded, encoding = as_cp866, "cp866"
    cleaned, removed = clean_name(decoded)
    return DecodedName(name=cleaned, raw=decoded, encoding=encoding, format_chars_removed=removed)


def zip_raw_name(filename: str, flag_bits: int) -> tuple[bytes | str, bool]:
    """Recover what the zip header stored, for ``decode_member_name``.

    zipfile decodes flagged names as UTF-8 and flag-less names as cp437 (both reversible), except
    when an Info-ZIP Unicode Path extra field (0x7075, written by 7-Zip/WinRAR next to a legacy
    name and CRC-checked against it) is present: then ``filename`` is already the authoritative
    Unicode name and is returned as text.
    """
    if flag_bits & 0x800:
        return filename.encode("utf-8"), True
    try:
        return filename.encode("cp437"), False
    except UnicodeEncodeError:
        return filename, False


def member_path_problems(name: str) -> list[str]:
    """Reasons (Russian, user-facing) why a member path is unsafe to extract; empty when safe."""
    problems: list[str] = []
    if not name.strip():
        problems.append("пустое имя")
        return problems
    unified = name.replace("\\", "/")
    if unified.startswith("/") or re.match(r"^[A-Za-z]:", unified) or unified.startswith("//"):
        problems.append("абсолютный путь")
    parts = [p for p in unified.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        problems.append("выход за пределы архива («..»)")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        problems.append("управляющие символы в имени")
    if len(name) > _MAX_MEMBER_NAME:
        problems.append("слишком длинное имя")
    if len(parts) > _MAX_MEMBER_DEPTH:
        problems.append("слишком глубокая вложенность")
    return problems


def safe_member_path(name: str) -> str:
    """Normalised relative POSIX path used in virtual ids «F0001!path» (never escapes the root)."""
    unified = name.replace("\\", "/")
    parts = [p for p in unified.split("/") if p not in ("", ".", "..")]
    parts = [re.sub(r"^[A-Za-z]:$", "", p) for p in parts]
    return "/".join(p for p in parts if p)


def split_stem(name: str) -> tuple[str, str]:
    """(stem, lowercase suffix) of the last path component."""
    last = PurePosixPath(name.replace("\\", "/")).name
    suffix = PurePosixPath(last).suffix.lower()
    stem = last[: -len(suffix)] if suffix else last
    return stem, suffix


def match_key(name: str) -> str:
    """Key for fuzzy name matching: NFC, no format chars, casefolded, ё→е, Latin look-alikes →
    Cyrillic, separators → single spaces, extension removed. Never used as an identifier."""
    cleaned, _ = clean_name(name)
    stem, _suffix = split_stem(cleaned)
    key = stem.casefold().replace("ё", "е").translate(_LATIN_TO_CYRILLIC)
    return _SEPARATORS.sub(" ", key).strip()


_SHEET_EXPLICIT = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])(?:лист(?:а|ы)?|sheet|list|л)\s*[.№#]?\s*(\d{1,3})(?!\d)", re.IGNORECASE
)
_SHEET_TRAILING = re.compile(r"(?:^|[\s_\-.])0*(\d{1,3})\s*(?:\(\d{1,2}\))?\s*$")


@dataclass(frozen=True, slots=True)
class SheetNumber:
    number: int
    explicit: bool  # «Лист 5» / «л.5» rather than a bare trailing number


def sheet_number(name: str) -> SheetNumber | None:
    """Sheet number from a drawing file name: «… Лист 5.dwg», «КЖ1-05.dwg», «АР_12 (1).dwg»."""
    stem, _ = split_stem(clean_name(name)[0])
    explicit = list(_SHEET_EXPLICIT.finditer(stem))
    if explicit:
        return SheetNumber(int(explicit[-1].group(1)), True)
    trailing = _SHEET_TRAILING.search(stem)
    if trailing:
        return SheetNumber(int(trailing.group(1)), False)
    return None
