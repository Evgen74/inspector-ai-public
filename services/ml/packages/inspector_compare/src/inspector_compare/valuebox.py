"""Locate an extracted value on its page: the words of the value (plus the label just before it) as normalized boxes.

Extracted values carry file, page, ``value_raw`` and ``context_text`` but no geometry. The PageTokens of the run carry
every word with its bbox (PDF_VISIBLE_ROTATED_TL_V1, the space of card boxes). The match runs on a whitespace-free,
case/ё/look-alike-normalized character stream of the page, so «1,7 %» matches the tokens «1,7» «%» and «1,7%»; the
label words before the value in ``context_text`` («уклон кровли») extend the box when the page prints them right
before it. Nothing found or no unique occurrence → no box (never a guess).
"""

from __future__ import annotations

import gzip
import json
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from inspector_common.runlayout import RunLayout

MAX_LABEL_WORDS = 2
MAX_BOXES = 8

# Latin letters that look like Cyrillic ones (OCR/PDF fonts mix them) → the Cyrillic letter.
_LOOKALIKE = str.maketrans(
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
_KEEP = re.compile(r"[0-9a-zа-я.%+]")
_DIGIT = re.compile(r"[0-9]")
_NUMBER = re.compile(r"[0-9.%+]+")


def normalize(text: str) -> str:
    """Lower case, ё→е, Latin look-alikes→Cyrillic, «,»→«.», dropping spaces and punctuation but «.» «%» «+»."""
    return "".join(_KEEP.findall(_fold(text)))


def _fold(text: str) -> str:
    return (text or "").lower().replace("ё", "е").replace(",", ".").translate(_LOOKALIKE)


def _stream(tokens: Sequence[Mapping[str, Any]]) -> tuple[str, list[int], list[bool]]:
    """The page as one normalized string, the token of every character, and ``brk[i]``: punctuation («;» «)» «–» …)
    was dropped between characters i-1 and i, so digits on its two sides are not one number («С1; 9)»)."""
    chars: list[str] = []
    owner: list[int] = []
    brk: list[bool] = []
    pending = False
    for i, t in enumerate(tokens):
        for ch in _fold(str(t.get("text") or "")):
            if _KEEP.match(ch):
                chars.append(ch)
                owner.append(i)
                brk.append(pending)
                pending = False
            elif not ch.isspace():
                pending = True
    return "".join(chars), owner, brk


def _occurrences(hay: str, needle: str) -> Iterable[int]:
    start = hay.find(needle)
    while start >= 0:
        yield start
        start = hay.find(needle, start + 1)


def _standalone(hay: str, owner: list[int], brk: list[bool], value_start: int, value_n: str) -> bool:
    """A numeric value is not the tail/head of a longer number («1.7%» inside «11.7%» or «1.75%»).

    A «.» next to the value counts as a decimal point only when a digit stands behind it («С0.» ends a sentence), and
    only for a plain number: a code with letters has no decimals, so «С0. 4. По…» (a list item follows) is «С0».
    Dropped punctuation between two digits separates them; so does a word gap after a code («С1 9»), but not inside a
    plain number («11 500»)."""
    end = value_start + len(value_n)
    numeric = _NUMBER.fullmatch(value_n) is not None

    def joined(i: int) -> bool:  # characters i-1 and i belong to one number
        return not brk[i] and (numeric or owner[i] == owner[i - 1])

    if _DIGIT.match(value_n[0]) and value_start > 0:
        s = value_start
        if _DIGIT.match(hay[s - 1]) and joined(s):
            return False
        if (
            numeric
            and hay[s - 1] == "."
            and s > 1
            and _DIGIT.match(hay[s - 2])
            and joined(s)
            and joined(s - 1)
        ):
            return False
    if _DIGIT.match(value_n[-1]) and end < len(hay):
        if _DIGIT.match(hay[end]) and joined(end):
            return False
        decimal = numeric and hay[end] == "." and end + 1 < len(hay) and _DIGIT.match(hay[end + 1])
        if decimal and joined(end) and joined(end + 1):
            return False
    return True


def _tail_score(hay: str, end: int, ctx_prefix: str) -> int:
    """Length of the common suffix of ``hay[:end]`` and the context prefix (how well the page text before agrees)."""
    n = 0
    while n < end and n < len(ctx_prefix) and hay[end - 1 - n] == ctx_prefix[-1 - n]:
        n += 1
    return n


def _norm_offset(text: str, nonspace: int) -> int:
    """Position in the normalized text of the character that has ``nonspace`` non-space characters before it."""
    seen = kept = 0
    for ch in text:
        if seen >= nonspace:
            break
        if ch.isspace():
            continue
        seen += 1
        kept += len(normalize(ch))
    return kept


def _context_variants(value_n: str, context_text: str | None, at: int | None = None) -> list[tuple[str, str]]:
    """[(phrase, context_prefix_before_value)] from the longest label+value to the bare value.

    ``at`` (non-space characters of the context before the value, from the extractor) picks the right occurrence when
    the value text repeats in its context («…Вт/(м3 °С) … Класс энергетической эффективности С»); without it the first
    occurrence that starts a word is used."""
    variants: list[tuple[str, str]] = []
    if context_text:
        norm = [normalize(w) for w in context_text.split()]
        joined = ""
        starts = []
        for n in norm:
            starts.append(len(joined))
            joined += n
        occ = list(_occurrences(joined, value_n))
        if occ:
            if at is not None:
                target = _norm_offset(context_text, at)
                pos = min(occ, key=lambda p: (abs(p - target), p))
            else:
                word_starts = set(starts)
                pos = next((p for p in occ if p in word_starts), occ[0])
            w = max(i for i, s in enumerate(starts) if s <= pos)
            prefix_all = joined[:pos]
            labels = [n for n in norm[:w] if n]
            for k in range(min(MAX_LABEL_WORDS, len(labels)), 0, -1):
                variants.append(("".join(labels[-k:]) + value_n, prefix_all))
            variants.append((value_n, prefix_all))
    if not variants:
        variants.append((value_n, ""))
    return variants


def _same_line(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    if a.get("line_id") is not None and b.get("line_id") is not None:
        return bool(a["line_id"] == b["line_id"])
    ba, bb = a["bbox"], b["bbox"]
    overlap = min(ba[3], bb[3]) - max(ba[1], bb[1])
    return overlap > 0.5 * min(ba[3] - ba[1], bb[3] - bb[1])


def _line_boxes(tokens: Sequence[Mapping[str, Any]], lo: int, hi: int) -> list[list[float]]:
    """One box per text line of the token range [lo, hi]."""
    groups: list[list[Mapping[str, Any]]] = []
    for t in tokens[lo : hi + 1]:
        if groups and _same_line(groups[-1][-1], t):
            groups[-1].append(t)
        else:
            groups.append([t])
    boxes = []
    for g in groups:
        bs = [t["bbox"] for t in g]
        boxes.append(
            [
                round(min(b[0] for b in bs), 5),
                round(min(b[1] for b in bs), 5),
                round(max(b[2] for b in bs), 5),
                round(max(b[3] for b in bs), 5),
            ]
        )
    return boxes


def locate_value(
    tokens: Sequence[Mapping[str, Any]],
    value_raw: str,
    context_text: str | None = None,
    context_at: int | None = None,
) -> list[list[float]]:
    """Boxes [x0,y0,x1,y1] (one per line) of the value with its label words, or [] when not found uniquely."""
    value_n = normalize(value_raw)
    if not value_n or not tokens:
        return []
    hay, owner, brk = _stream(tokens)
    for phrase, ctx_prefix in _context_variants(value_n, context_text, context_at):
        lead = len(phrase) - len(value_n)
        found = [s for s in _occurrences(hay, phrase) if _standalone(hay, owner, brk, s + lead, value_n)]
        if not found:
            continue
        if len(found) > 1:
            scored = sorted(((_tail_score(hay, s + lead, ctx_prefix), s) for s in found), reverse=True)
            if scored[0][0] == 0 or scored[0][0] == scored[1][0]:
                continue  # several equally good occurrences: no guessing
            found = [scored[0][1]]
        s = found[0]
        return _line_boxes(tokens, owner[s], owner[s + len(phrase) - 1])
    return []


class ValueLocator:
    """PageTokens of a run directory with a small LRU cache; ``boxes`` unions the boxes of several values of a page."""

    def __init__(self, run_dir: Path | str | None, cache_size: int = 32) -> None:
        self.layout = RunLayout(Path(run_dir)) if run_dir else None
        self._cache: OrderedDict[tuple[str, int], list[Mapping[str, Any]]] = OrderedDict()
        self._size = cache_size

    def _tokens(self, file_id: str, page: int) -> list[Mapping[str, Any]]:
        key = (file_id, page)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        tokens: list[Mapping[str, Any]] = []
        if self.layout is not None:
            path = self.layout.path("PAGE_TOKENS", file_id=file_id, page=page)
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    doc = json.load(fh)
                tokens = [t for t in doc.get("tokens", []) if t.get("bbox")]
            except (OSError, ValueError):
                tokens = []
        self._cache[key] = tokens
        if len(self._cache) > self._size:
            self._cache.popitem(last=False)
        return tokens

    def boxes(self, file_id: str, page: int, values: Iterable[tuple[Any, ...]]) -> list[list[float]]:
        """values: (value_raw, context_text[, context_at]) tuples; the deduplicated boxes (at most MAX_BOXES)."""
        tokens = self._tokens(file_id, int(page))
        out: list[list[float]] = []
        for raw, ctx, *rest in values:
            for b in locate_value(tokens, raw, ctx, rest[0] if rest else None):
                if b not in out:
                    out.append(b)
        return out[:MAX_BOXES]


__all__ = ["ValueLocator", "locate_value", "normalize"]
