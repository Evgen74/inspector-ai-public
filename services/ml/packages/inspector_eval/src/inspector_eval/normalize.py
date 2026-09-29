"""Normalisation modes of inspector-score (93 §4.3). Versioned: bump config.NORMALIZATION_VERSION on any change.

Three modes per item; ``light`` is the default (H1):

| item          | strict            | light (default)                                   | relaxed                                  |
|---------------|-------------------|---------------------------------------------------|------------------------------------------|
| parameter code| upper, trim       | + alias resolution to the catalog code            | + prefix-agnostic resolution by id       |
| location      | trim              | NFC, casefold, ё→е, dashes, strip «пом.»/«№»,     | + strip leading zeros, strip «венткамера»|
|               |                   | collapse spaces; leading zeros are KEPT            |   and «тех. помещение» nouns             |
| values        | exact             | NFC, casefold, ё→е, punctuation, numbers and units | + token-set similarity                   |
| criticality   | exact             | normalised text                                    | prefix (Критическое / Существенное)      |
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz

from inspector_common.contracts.codes import ParameterCodeError, is_free_code, parse_parameter_code
from inspector_eval.config import MODES, NORMALIZATION_VERSION, Mode

__all__ = ["MODES", "NORMALIZATION_VERSION", "Mode"]

_CHAR_MAP = str.maketrans(
    {
        "−": "-",  # minus sign
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
    }
)
_SPACES = re.compile(r"\s+")


def base_text(value: Any) -> str:
    """NFC, unified dashes and spaces, casefold, ё→е, collapsed whitespace."""
    text = unicodedata.normalize("NFC", str(value)).translate(_CHAR_MAP)
    text = text.casefold().replace("ё", "е")
    return _SPACES.sub(" ", text).strip()


# ── parameter codes ───────────────────────────────────────────────────────────────────────────


def normalize_code(code: Any, mode: Mode = "light") -> str:
    """Parameter code for the scoring key. Unparseable codes are returned upper-cased as is."""
    text = str(code or "").strip().upper()
    if mode == "strict" or is_free_code(text):
        return text
    try:
        parsed = parse_parameter_code(text)
    except ParameterCodeError:
        return text
    if mode == "light" and parsed.prefix_mismatch and not parsed.fixed_by_known_alias:
        return text
    return parsed.canonical


# ── locations ─────────────────────────────────────────────────────────────────────────────────

_LOC_PREFIX = re.compile(r"^(?:помещение|пом\.?|комн\.?|№|n°|no\.)\s*")
_LOC_PUNCT_SPACING = re.compile(r"\s*([,;/])\s*")
_LOC_EDGE_PUNCT = re.compile(r"^[\s«»\"“”„'’.,;:]+|[\s«»\"“”„'’.,;:]+$")
_LOC_NOUNS = re.compile(r"^(?:венткамера|вент\.?\s*камера|тех\.?\s*помещение|техническое\s+помещение)\s*")
_LEADING_ZEROS = re.compile(r"(?<![\d.])0+(?=\d)")


def normalize_location(location: Any, mode: Mode = "light") -> str:
    """Location token for the scoring key (93 §2.7, §4.3). ``light`` keeps «012» ≠ «12»."""
    if location is None:
        return ""
    if mode == "strict":
        return str(location).strip()
    text = base_text(location)
    text = _LOC_EDGE_PUNCT.sub("", text)
    previous = None
    while previous != text:  # «пом. № 012» → «012»
        previous = text
        text = _LOC_PREFIX.sub("", text).strip()
        if mode == "relaxed":
            text = _LOC_NOUNS.sub("", text).strip()
    text = _LOC_PUNCT_SPACING.sub(r"\1", text)
    if mode == "relaxed":
        text = _LEADING_ZEROS.sub("", text)
    return text


# ── criticality ───────────────────────────────────────────────────────────────────────────────

_CRIT_PUNCT = re.compile(r"[«»\"“”„().,;:]")


def normalize_criticality(value: Any, mode: Mode = "light") -> str | None:
    if value is None:
        return None
    if mode == "strict":
        return str(value)
    text = _SPACES.sub(" ", _CRIT_PUNCT.sub(" ", base_text(value))).strip()
    if mode == "relaxed":
        return text.split(" ", 1)[0] if text else text
    return text


def is_approved_critical_string(criticality: Any) -> bool:
    """«утверждённая критическая контрольная точка»: «Критическое…» without «требует утверждения» (93 §2.4)."""
    if not isinstance(criticality, str):
        return False
    text = base_text(criticality)
    return text.startswith("критическое") and "требует утверждения" not in text


# ── values ────────────────────────────────────────────────────────────────────────────────────

_THOUSANDS = re.compile(r"(?<=\d) (?=\d{3}(?!\d))")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_VALUE_PUNCT = re.compile(r"[«»\"“”„()\[\];:!?,]")
_LONE_DOT = re.compile(r"(?<!\d)\.|\.(?!\d)")
_UNIT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bкв\s*м\b"), "м²"),
    (re.compile(r"\bкуб\s*м\b"), "м³"),
    (re.compile(r"(?<=[мm])(?:\^?2)(?![\d])"), "²"),
    (re.compile(r"(?<=[мm])(?:\^?3)(?![\d])"), "³"),
)
_NUMBER_UNIT = re.compile(r"^([-+]?\d+(?:\.\d+)?)\s*([a-zа-я²³/%°]*)$")
# unit → (dimension, factor to the base unit of that dimension)
_UNITS: dict[str, tuple[str, float]] = {
    "": ("", 1.0),
    "мм": ("length", 1.0),
    "см": ("length", 10.0),
    "м": ("length", 1000.0),
    "км": ("length", 1_000_000.0),
    "мм²": ("area", 1.0),
    "см²": ("area", 100.0),
    "м²": ("area", 1_000_000.0),
    "м³": ("volume", 1.0),
    "л": ("volume", 0.001),
    "%": ("percent", 1.0),
    "шт": ("count", 1.0),
}


def normalize_value_text(value: Any) -> str:
    """Light value normalisation: text, numbers (decimal comma, thin spaces) and canonical units."""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = base_text(value)
    text = _THOUSANDS.sub("", text)
    text = _DECIMAL_COMMA.sub(".", text)
    text = _VALUE_PUNCT.sub(" ", text)
    text = _LONE_DOT.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    for pattern, replacement in _UNIT_RULES:
        text = pattern.sub(replacement, text)
    return _SPACES.sub(" ", text).strip()


def _as_quantity(value: Any) -> tuple[str, float] | None:
    """(dimension, magnitude in the base unit) when the value is a plain number with an optional unit."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return ("", float(value)) if math.isfinite(value) else None
    match = _NUMBER_UNIT.match(normalize_value_text(value))
    if not match:
        return None
    unit = _UNITS.get(match.group(2))
    if unit is None:
        return None
    return unit[0], float(match.group(1)) * unit[1]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def value_similarity(gold: Any, pred: Any, mode: Mode = "light") -> float:
    """Similarity in [0, 1] of two non-null stage values (1.0 = equal)."""
    if mode == "strict":
        return 1.0 if gold == pred else 0.0
    q_gold, q_pred = _as_quantity(gold), _as_quantity(pred)
    if q_gold is not None and q_pred is not None:
        same_dim = q_gold[0] == q_pred[0] or "" in (q_gold[0], q_pred[0])
        tolerance = 1e-9 * max(1.0, abs(q_gold[1]))
        return 1.0 if same_dim and abs(q_gold[1] - q_pred[1]) <= tolerance else 0.0
    a, b = normalize_value_text(gold), normalize_value_text(pred)
    if a == b:
        return 1.0
    score = fuzz.ratio(a, b) / 100.0
    if mode == "relaxed":
        score = max(score, fuzz.token_set_ratio(a, b) / 100.0)
    return score


def value_match(gold: Any, pred: Any, mode: Mode = "light", threshold: float = 0.85) -> float:
    """H1 value rule (93 §2.2): 1 when both null, 0 when one is null, else similarity ≥ threshold."""
    if mode == "strict":
        return 1.0 if gold == pred else 0.0
    gold_blank, pred_blank = _is_blank(gold), _is_blank(pred)
    if gold_blank and pred_blank:
        return 1.0
    if gold_blank or pred_blank:
        return 0.0
    return 1.0 if value_similarity(gold, pred, mode) >= threshold else 0.0
