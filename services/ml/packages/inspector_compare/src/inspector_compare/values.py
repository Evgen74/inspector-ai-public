"""Value templates (93 §3.5, seed ``change_matrix_map`` route ``value_templates``) and Russian number formatting.

Gold phrasing is reproduced verbatim by the seed templates, e.g. «Конфигурация приточных установок по листу
{pd_sheet} ПД» / «Иная конфигурация на плане {rd_plan_mark}, помещение {location}». A placeholder without a
value is removed together with its clause (never printed as «{…}» or «None»).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

# Clause fallbacks when a placeholder has no value (checked before the generic removal).
_FALLBACKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\s*по листу \{pd_sheet\}\s*ПД"), " по ПД"),
    (re.compile(r"\s*по листу \{rd_sheet\}\s*РД"), " по РД"),
    (re.compile(r"на плане \{rd_plan_mark\}"), "на плане РД"),
    (re.compile(r"на плане \{pd_plan_mark\}"), "на плане ПД"),
    (re.compile(r",\s*помещение \{location\}"), ""),
)


def render_template(template: str | None, values: Mapping[str, Any]) -> str | None:
    """Fill ``{name}`` placeholders; unknown/empty ones drop their clause. None template → None."""
    if template is None:
        return None
    text = template
    present = {k: v for k, v in values.items() if v not in (None, "")}
    for pattern, replacement in _FALLBACKS:
        names = set(_PLACEHOLDER.findall(pattern.pattern.replace("\\{", "{").replace("\\}", "}")))
        if names and not names & set(present):
            text = pattern.sub(replacement, text)

    def repl(match: re.Match[str]) -> str:
        value = present.get(match.group(1))
        return "" if value is None else str(value)

    text = _PLACEHOLDER.sub(repl, text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text or None


# ── numbers ───────────────────────────────────────────────────────────────────────────────────


def ru_number(value: float | int | Decimal, decimals: int | None = None) -> str:
    """Russian number format of the seed ``value_templates.number_format``: decimal comma, no thousands grouping
    («1560 м³», «6252,3»), no trailing zeros unless ``decimals`` is given («1,0 м»)."""
    d = Decimal(str(value))
    if decimals is not None:
        d = d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        text = f"{d:f}"
    else:
        text = f"{d.normalize():f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", ",")


def natural_key(token: str) -> tuple[Any, ...]:
    """Sort room tokens naturally while keeping them as printed («012» < «140» < «1.109»)."""
    parts = re.split(r"(\d+)", token)
    return tuple((0, int(p), p) if p.isdigit() else (1, 0, p) for p in parts)


def rooms_phrase(locations: list[str]) -> str:
    """«пом. 012» / «пом. 140, 142» (93 §5.4, the readable location of the protocol)."""
    return "пом. " + ", ".join(locations) if locations else ""
