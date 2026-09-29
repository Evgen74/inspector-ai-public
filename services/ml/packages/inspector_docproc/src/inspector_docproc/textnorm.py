"""Text normalisation shared by recognition and its benchmark (96 §1.3 metric conventions).

- ``strict``: NFC, whitespace removed (CAD text layers have unreliable spacing).
- ``relaxed``: also dashes, quotes and ``ё`` unified, Latin look-alikes folded to Cyrillic.
- ``relaxed_ci``: also case-folded.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz.distance import Levenshtein

HOMO = str.maketrans(
    {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
     "X": "Х", "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
     "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-", "ё": "е", "Ё": "Е",
     "«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "’": "'", "‘": "'", "`": "'"}
)  # fmt: skip


def norm_strict(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", s))


def norm_relaxed(s: str) -> str:
    return norm_strict(s).translate(HOMO)


def norm_relaxed_ci(s: str) -> str:
    return norm_relaxed(s).lower()


def similarity(reference: str, candidate: str) -> float:
    """1 − normalised Levenshtein distance after ``relaxed_ci`` normalisation (0 for an empty reference)."""
    a, b = norm_relaxed_ci(reference), norm_relaxed_ci(candidate)
    if not a:
        return 0.0
    return 1.0 - Levenshtein.normalized_distance(a, b)
