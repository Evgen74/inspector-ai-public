"""Parameter code grammar (97 §2.9, packages/contracts/codes.yaml).

    parse_parameter_code("КР-55")   → ParsedCode(param_id=55, canonical="KR-055", style="short_cyrillic", …)
    canonical_code(79)              → "IOS4-079"
    parse_free_code("FREE-HEATING-001") → ("HEATING", 1)

The integer ``param_id`` is the join key for every style. The canonical external code is the
catalog code; M-xxx and the ТЗ/Приложение 2 short forms are aliases. A prefix that disagrees with
the id range is reported (``prefix_mismatch``) — resolve by parameter name (AG-03's params loader)
— except for known organizer typos listed in codes.yaml (``AR-14`` → ``AR-040``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from inspector_common.contracts.loader import load_codes, load_enums

CodeStyle = Literal["catalog", "matrix_m", "short_latin", "short_cyrillic"]


class ParameterCodeError(ValueError):
    """The string is not a parameter code in any accepted style."""


@dataclass(frozen=True, slots=True)
class Prefix:
    latin: str
    cyrillic: str
    first: int
    last: int
    section: str


@dataclass(frozen=True, slots=True)
class ParsedCode:
    raw: str
    param_id: int
    canonical: str
    style: CodeStyle
    prefix_mismatch: bool  # prefix disagrees with the id range (M-xxx is exempt)
    fixed_by_known_alias: bool = False


@lru_cache(maxsize=1)
def prefixes() -> tuple[Prefix, ...]:
    return tuple(Prefix(**p) for p in load_codes()["prefixes"])


@lru_cache(maxsize=1)
def _patterns() -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    codes = load_codes()
    return (
        re.compile(codes["canonical_pattern"]),
        re.compile(codes["alias_pattern"]),
        re.compile(codes["free_pattern"]),
    )


def _latin_prefix(prefix_text: str) -> str:
    """The Latin section prefix for a prefix in either alphabet (``АР`` → ``AR``); unknown text as is."""
    for prefix in prefixes():
        if prefix_text in (prefix.latin, prefix.cyrillic):
            return prefix.latin
    return prefix_text


@lru_cache(maxsize=1)
def _known_fixes() -> dict[tuple[str, int], str]:
    """codes.yaml known_alias_fixes keyed by (Latin prefix, number): «AR-14», «АР-14» and «AR-014» are one typo."""
    out: dict[tuple[str, int], str] = {}
    for fix in load_codes().get("known_alias_fixes", []):
        prefix_text, _, number = fix["alias"].upper().partition("-")
        out[(_latin_prefix(prefix_text), int(number))] = fix["resolves_to"]
    return out


def prefix_for_id(param_id: int) -> Prefix:
    for prefix in prefixes():
        if prefix.first <= param_id <= prefix.last:
            return prefix
    raise ParameterCodeError(f"parameter id {param_id} is outside 1..132")


def canonical_code(param_id: int) -> str:
    return f"{prefix_for_id(param_id).latin}-{param_id:03d}"


def is_canonical_code(code: str) -> bool:
    return bool(_patterns()[0].fullmatch(code))


def is_free_code(code: str) -> bool:
    return bool(_patterns()[2].fullmatch(code))


def parse_free_code(code: str) -> tuple[str, int]:
    """FREE-<TOPIC>-<NNN> → (topic, n). The topic must be in enums.FreeTopic."""
    match = _patterns()[2].fullmatch(code)
    if not match:
        raise ParameterCodeError(f"not a FREE-<TOPIC>-<NNN> code: {code!r}")
    topic = match.group(1)
    if topic not in load_enums()["FreeTopic"].codes:
        raise ParameterCodeError(f"unknown FREE topic {topic!r} in {code!r}")
    return topic, int(match.group(2))


def free_code(topic: str, n: int) -> str:
    if topic not in load_enums()["FreeTopic"].codes:
        raise ParameterCodeError(f"unknown FREE topic {topic!r}")
    if not 1 <= n <= 999:
        raise ParameterCodeError(f"FREE number out of range: {n}")
    return f"FREE-{topic}-{n:03d}"


def parse_parameter_code(raw: str) -> ParsedCode:
    """Parse any accepted style (catalog, M-xxx, ТЗ Latin/Cyrillic short) into a :class:`ParsedCode`."""
    text = raw.strip().upper().replace("–", "-").replace("—", "-")
    match = _patterns()[1].fullmatch(text)
    if not match:
        raise ParameterCodeError(f"not a parameter code: {raw!r}")
    prefix_text, number = match.group(1), int(match.group(2))
    fixed = None if prefix_text == "M" else _known_fixes().get((_latin_prefix(prefix_text), number))
    if fixed is not None:
        param_id = int(fixed.rsplit("-", 1)[1])
        if _patterns()[0].fullmatch(text):
            fixed_style: CodeStyle = "catalog"
        else:
            fixed_style = "short_cyrillic" if prefix_text != _latin_prefix(prefix_text) else "short_latin"
        return ParsedCode(
            raw, param_id, canonical_code(param_id), fixed_style, True, fixed_by_known_alias=True
        )
    lo, hi = load_codes()["param_id_range"]
    if not lo <= number <= hi:
        raise ParameterCodeError(f"parameter id {number} is outside {lo}..{hi}: {raw!r}")
    canonical = canonical_code(number)
    if prefix_text == "M":
        return ParsedCode(raw, number, canonical, "matrix_m", False)
    expected = prefix_for_id(number)
    is_cyrillic = prefix_text == expected.cyrillic or any(prefix_text == p.cyrillic for p in prefixes())
    mismatch = prefix_text not in (expected.latin, expected.cyrillic)
    if _patterns()[0].fullmatch(text):
        style: CodeStyle = "catalog"
    else:
        style = "short_cyrillic" if is_cyrillic else "short_latin"
    return ParsedCode(raw, number, canonical, style, mismatch)


def alias_codes(param_id: int) -> list[str]:
    """Every alias of a parameter: M-xxx, the ТЗ short Latin and Cyrillic forms."""
    prefix = prefix_for_id(param_id)
    return [f"M-{param_id:03d}", f"{prefix.latin}-{param_id:02d}", f"{prefix.cyrillic}-{param_id:02d}"]
