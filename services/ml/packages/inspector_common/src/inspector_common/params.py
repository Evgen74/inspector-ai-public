"""Parameter matrix (132) seed loader and domain helpers — OWNED BY AG-03 (CLAUDE.md, directory ownership).

The seed lives in ``packages/contracts/seed/`` (built by ``seed/src/build_seed.py``, validated by
``seed/schemas/*.schema.json``):

- ``params.json``: 132 parameters keyed by the catalog code (PZ-001 … SM-132), with aliases, criticality,
  the comparison-rule DSL, hardened regexes, context gates and hedge groups;
- ``change_matrix_map.json``: element family × discrepancy type → parameter code (97 §2.10 routing);
- ``free_topics.json``: the fixed FREE-<TOPIC> vocabulary (mirrors ``enums.FreeTopic``);
- ``recommendation_templates.json``: Раздел 7 texts (132 parameters + FREE topics) with web-verified norms, the
  «Отклонение» phrases, edition rules and the edition registry;
- ``value_templates.json``: submission-style formats and templates for pd_value / rd_value / id_value.

Quick use::

    from inspector_common import params
    reg = params.load_params()
    reg.get("КР-55").code                      # 'KR-055' (any code style, 97 §2.9)
    params.resolve_code("AR-14", name="Ширина эвакуационных коридоров").code   # 'AR-040' + warning
    params.criticality_level(55)               # CriticalityLevel.CRITICAL_SUSPEND
    reg.extract("KR-055", params.normalize_regex_input(text), discipline="КЖ")   # gated regex hits
    params.load_change_map().route("WARM_FLOOR", "ELEMENT_MISSING").parameter_code  # 'FREE-HEATING'
    params.stage_values(family="WARM_FLOOR", discrepancy_type="ELEMENT_MISSING")      # gold pd/rd/id_value
    params.render_recommendation("AR-040", discrepancy_type="VALUE_DECREASED", pd_value="1,4 м",
                                 rd_value="1,1 м", expected=1.4, actual=1.1, unit="м")  # Раздел 7 texts

Regex policy (97 §2.14): every seed regex runs only through :func:`compile_guarded`: static safety analysis
at compile time, inputs cut into windows of at most ``MAX_WINDOW_CHARS`` characters, and a hard per-window
time limit (``SIGALRM`` timer, main thread only; elsewhere the limit is soft and only logged).

CLI: ``python -m inspector_common.params check | show CODE | resolve CODE [--name NAME]``.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import re._constants as _sre_c  # stdlib internals, stable across 3.11–3.13
import re._parser as _sre_parse
import signal
import sys
import threading
import time
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import cache, lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from jsonschema import Draft202012Validator
from referencing import Resource
from referencing.jsonschema import DRAFT202012

from inspector_common.contracts import codes as _codes
from inspector_common.contracts.enums import (
    CriticalityLevel,
    DataType,
    DiscrepancyType,
    FreeTopic,
    ParameterMappingStatus,
    ReviewPriority,
)
from inspector_common.contracts.loader import enum_mappings, load_codes, load_enums
from inspector_common.contracts.loader import registry as _contracts_registry
from inspector_common.contracts.models import CatalogRow
from inspector_common.jsonlog import get_logger
from inspector_common.paths import contracts_dir, repo_root

__all__ = [
    "DEFAULT_TIME_BUDGET_S",
    "MATRIX_OVERRIDES_DEFAULT",
    "MATRIX_OVERRIDES_ENV",
    "MAX_AUX_PATTERN_CHARS",
    "MAX_REGEX_PATTERN_CHARS",
    "MAX_WINDOW_CHARS",
    "PRELIMINARY_PREFIX",
    "ChangeMap",
    "CodeResolution",
    "ContextGate",
    "FreeTopicSpec",
    "GateDecision",
    "GuardedPattern",
    "Noun",
    "ParamRegistry",
    "ParamSpec",
    "ParameterCodeError",
    "RecommendationTemplate",
    "RecommendationTemplates",
    "RegexHit",
    "RegexTimeout",
    "RenderedRecommendation",
    "Route",
    "SeedError",
    "UnsafeRegexError",
    "ValueTemplates",
    "classify_b_token",
    "classify_id_abbreviation",
    "clear_caches",
    "compile_guarded",
    "criticality_level",
    "format_delta",
    "format_number_ru",
    "format_value",
    "get_param",
    "load_catalog",
    "load_change_map",
    "load_free_topics",
    "load_params",
    "load_recommendation_templates",
    "load_value_templates",
    "location_display",
    "norm_edition",
    "normalize_regex_input",
    "overrides_summary",
    "plural_ru",
    "protocol_cell",
    "regex_safety_problems",
    "render_recommendation",
    "render_text",
    "resolve_code",
    "resolve_overrides_path",
    "seed_consistency_problems",
    "seed_dir",
    "seed_validation_errors",
    "stage_values",
    "unverified_numbers",
    "verified_corpus",
]

log = get_logger(__name__)

ParameterCodeError = _codes.ParameterCodeError

SEED_SCHEMA_BASE_URI = "https://contracts.inspector-ai.local/seed/"
SEED_FILES = {
    "params": "params.json",
    "change_matrix_map": "change_matrix_map.json",
    "free_topics": "free_topics.json",
    "recommendation_templates": "recommendation_templates.json",
    "value_templates": "value_templates.json",
}

MAX_REGEX_PATTERN_CHARS = 255  # ТЗ §8.1: regex_pattern VARCHAR(255)
MAX_AUX_PATTERN_CHARS = 512
MAX_WINDOW_CHARS = 20_000  # one regex call never sees more text than this
WINDOW_OVERLAP_CHARS = 512
DEFAULT_TIME_BUDGET_S = 0.5  # per window; hard in the main thread, soft elsewhere
_UNBOUNDED_AT = 200  # a repeat with a larger upper bound is treated as unbounded by the analyser


class SeedError(RuntimeError):
    """The seed files are missing, malformed or inconsistent."""


class UnsafeRegexError(ValueError):
    """A pattern failed the static safety analysis (catastrophic or polynomial backtracking risk)."""

    def __init__(self, pattern: str, problems: Sequence[str]):
        self.pattern = pattern
        self.problems = tuple(problems)
        super().__init__(f"unsafe regex ({'; '.join(problems)}): {pattern[:120]!r}")


class RegexTimeout(TimeoutError):
    """A guarded regex exceeded its hard time budget on one input window."""

    def __init__(self, label: str, elapsed_s: float, window_chars: int):
        self.label = label
        self.elapsed_s = elapsed_s
        self.window_chars = window_chars
        super().__init__(f"regex {label} exceeded its time budget: {elapsed_s:.3f}s on {window_chars} chars")


# ───────────────────────────────────── Text normalisation (regex input contract) ─────────────────────────────────────

_SPACE_LIKE = dict.fromkeys(map(ord, "           　"), " ")
_DASHES = dict.fromkeys(map(ord, "‐‑‒−"), "-")
_UNIT_SQ = re.compile(r"(?<![\w])(м|мм|см|км)2(?![\w])")
_UNIT_CU = re.compile(r"(?<![\w])(м|мм|см)3(?![\w])")


def normalize_regex_input(text: str) -> str:
    """Normalise text before any seed regex runs (the contract stated in ``regex_flags``).

    NFC; NBSP and other fixed-width spaces → space; hyphen-like dashes (‐ ‑ ‒ −) → «-» (en/em dashes are kept:
    the patterns accept them explicitly); «м2/м3» → «м²/м³» as units. Length-preserving for the dash and space
    maps; NFC may shorten decomposed text. The ё letter and homoglyphs are **not** folded: patterns accept both
    alphabets where OCR mixes them, and context gates disambiguate.
    """
    text = unicodedata.normalize("NFC", text).translate(_SPACE_LIKE).translate(_DASHES)
    text = _UNIT_SQ.sub(lambda m: m.group(1) + "²", text)
    return _UNIT_CU.sub(lambda m: m.group(1) + "³", text)


# ───────────────────────────────────────────── Regex safety: static analysis ─────────────────────────────────────────

_REPEATS = (_sre_c.MAX_REPEAT, _sre_c.MIN_REPEAT)
_ZERO_WIDTH = (_sre_c.AT, _sre_c.ASSERT, _sre_c.ASSERT_NOT)
_START_ANCHORS = (_sre_c.AT_BEGINNING, _sre_c.AT_BEGINNING_LINE, _sre_c.AT_BEGINNING_STRING)


def _probe_alphabet() -> str:
    ascii_part = "".join(chr(c) for c in range(32, 127))
    cyr = "".join(chr(c) for c in range(0x410, 0x450)) + "Ёё"
    extra = "\t\n²³×Ø⌀ø–—«»±‰°δλΔ№§·…"
    return ascii_part + cyr + extra


_PROBE = _probe_alphabet()
_CATEGORY_TESTS = {
    _sre_c.CATEGORY_DIGIT: str.isdigit,
    _sre_c.CATEGORY_NOT_DIGIT: lambda c: not c.isdigit(),
    _sre_c.CATEGORY_SPACE: str.isspace,
    _sre_c.CATEGORY_NOT_SPACE: lambda c: not c.isspace(),
    _sre_c.CATEGORY_WORD: lambda c: c.isalnum() or c == "_",
    _sre_c.CATEGORY_NOT_WORD: lambda c: not (c.isalnum() or c == "_"),
}


def _case_variants(chars: set[str]) -> set[str]:
    out = set(chars)
    for c in chars:
        out.add(c.lower())
        out.add(c.upper())
    return out


def _charset(op: Any, av: Any, ignorecase: bool) -> frozenset[str] | None:
    """Probe characters a single-character matcher accepts, or None when the node is not one."""
    if op is _sre_c.LITERAL:
        chars = {chr(av)}
    elif op is _sre_c.NOT_LITERAL:
        excluded = _case_variants({chr(av)}) if ignorecase else {chr(av)}
        return frozenset(c for c in _PROBE if c not in excluded)
    elif op is _sre_c.ANY:
        return frozenset(c for c in _PROBE if c != "\n")
    elif op is _sre_c.IN:
        negate = False
        chars = set()
        for iop, iav in av:
            if iop is _sre_c.NEGATE:
                negate = True
            elif iop is _sre_c.LITERAL:
                chars.add(chr(iav))
            elif iop is _sre_c.RANGE:
                lo, hi = iav
                chars.update(c for c in _PROBE if lo <= ord(c) <= hi)
            elif iop is _sre_c.CATEGORY:
                test = _CATEGORY_TESTS.get(iav)
                chars.update(c for c in _PROBE if test is None or test(c))
        if ignorecase:
            chars = _case_variants(chars)
        if negate:
            return frozenset(c for c in _PROBE if c not in chars)
        return frozenset(c for c in _PROBE if c in chars)
    else:
        return None
    return frozenset(_case_variants(chars) if ignorecase else chars)


def _single_charset(sub: Any, ignorecase: bool) -> frozenset[str] | None:
    items = list(sub)
    if len(items) != 1:
        return None
    return _charset(*items[0], ignorecase)


def _is_unbounded(hi: int) -> bool:
    return hi == _sre_c.MAXREPEAT or hi > _UNBOUNDED_AT


def _first_set(items: Sequence[Any], ignorecase: bool) -> frozenset[str]:
    """Union of characters that can start a match of ``items`` (conservative: everything when unknown)."""
    acc: set[str] = set()
    for op, av in items:
        if op in _ZERO_WIDTH:
            continue
        cs = _charset(op, av, ignorecase)
        if cs is not None:
            return frozenset(acc | cs)
        if op in (*_REPEATS, _sre_c.POSSESSIVE_REPEAT):
            lo, _hi, sub = av
            acc |= _first_set(list(sub), ignorecase)
            if lo > 0:
                return frozenset(acc)
            continue
        if op is _sre_c.SUBPATTERN:
            acc |= _first_set(list(av[3]), ignorecase)
            return frozenset(acc)
        if op is _sre_c.ATOMIC_GROUP:
            acc |= _first_set(list(av), ignorecase)
            return frozenset(acc)
        if op is _sre_c.BRANCH:
            for branch in av[1]:
                acc |= _first_set(list(branch), ignorecase)
            return frozenset(acc)
        return frozenset(_PROBE)
    return frozenset(acc)


_INF = 1 << 30


def _width(items: Sequence[Any]) -> tuple[int, int]:
    lo_sum = hi_sum = 0
    for op, av in items:
        if op in _ZERO_WIDTH:
            continue
        if op in (_sre_c.LITERAL, _sre_c.NOT_LITERAL, _sre_c.ANY, _sre_c.IN):
            lo, hi = 1, 1
        elif op in (*_REPEATS, _sre_c.POSSESSIVE_REPEAT):
            rlo, rhi, sub = av
            slo, shi = _width(list(sub))
            lo, hi = rlo * slo, _INF if rhi == _sre_c.MAXREPEAT else min(_INF, rhi * shi)
        elif op is _sre_c.SUBPATTERN:
            lo, hi = _width(list(av[3]))
        elif op is _sre_c.ATOMIC_GROUP:
            lo, hi = _width(list(av))
        elif op is _sre_c.BRANCH:
            widths = [_width(list(b)) for b in av[1]]
            lo, hi = min(w[0] for w in widths), max(w[1] for w in widths)
        else:
            lo, hi = 0, _INF
        lo_sum, hi_sum = lo_sum + lo, min(_INF, hi_sum + hi)
    return lo_sum, hi_sum


def _all_chars(op: Any, av: Any, ic: bool) -> frozenset[str]:
    cs = _charset(op, av, ic)
    if cs is not None:
        return cs
    if op in _ZERO_WIDTH:
        return frozenset()
    if op in (*_REPEATS, _sre_c.POSSESSIVE_REPEAT):
        return frozenset().union(*(_all_chars(o, a, ic) for o, a in av[2]))
    if op is _sre_c.SUBPATTERN:
        return frozenset().union(*(_all_chars(o, a, ic) for o, a in av[3]))
    if op is _sre_c.ATOMIC_GROUP:
        return frozenset().union(*(_all_chars(o, a, ic) for o, a in av))
    if op is _sre_c.BRANCH:
        return frozenset().union(*(_all_chars(o, a, ic) for b in av[1] for o, a in b))
    return frozenset(_PROBE)


def _unwrap(items: list[Any]) -> list[Any]:
    while len(items) == 1 and items[0][0] is _sre_c.SUBPATTERN:
        items = list(items[0][1][3])
    return items


def _ambiguous_body(items: list[Any], ic: bool) -> bool:
    """Can one iteration of a repeated body match the same text in several ways (``(a|aa)*``, ``(\\d\\d?)+``)?"""
    items = _unwrap(items)
    if len(items) == 1 and items[0][0] is _sre_c.BRANCH:
        branches = [list(b) for b in items[0][1][1]]
        firsts = [_first_set(b, ic) for b in branches]
        if any(firsts[i] & firsts[j] for i in range(len(firsts)) for j in range(i + 1, len(firsts))):
            return True
        return any(_ambiguous_body(b, ic) for b in branches)
    lo, hi = _width(items)
    if lo == hi:
        return False
    first = _first_set(items, ic)
    first_idx = next((i for i, (op, _) in enumerate(items) if op not in _ZERO_WIDTH), None)
    tail: set[str] = set()
    for idx, (op, av) in enumerate(items):
        if op in _ZERO_WIDTH:
            continue
        if idx == first_idx and _charset(op, av, ic) is not None:
            continue  # the body's first character itself
        tail |= _all_chars(op, av, ic)
    return bool(first & tail)


def _check_nested(items: Sequence[Any], outer_first: frozenset[str] | None, ic: bool, out: list[str]) -> None:
    for op, av in items:
        if op in _REPEATS:
            lo, hi, sub = av
            sub_items = list(sub)
            if _is_unbounded(hi) and _single_charset(sub, ic) is None and _ambiguous_body(sub_items, ic):
                out.append(
                    "quantified group can match the same text in several ways (catastrophic backtracking)"
                )
            variable = hi != lo and hi > 1
            if outer_first is not None and variable:
                inner = _single_charset(sub, ic)
                inner_set = inner if inner is not None else _first_set(sub_items, ic)
                if inner_set & outer_first:
                    out.append("nested quantifier over overlapping characters (catastrophic backtracking)")
            next_first = _first_set(sub_items, ic) if _is_unbounded(hi) else outer_first
            _check_nested(sub_items, next_first, ic, out)
        elif op is _sre_c.POSSESSIVE_REPEAT:
            _check_nested(list(av[2]), None, ic, out)
        elif op is _sre_c.ATOMIC_GROUP:
            _check_nested(list(av), None, ic, out)
        elif op is _sre_c.SUBPATTERN:
            _check_nested(list(av[3]), outer_first, ic, out)
        elif op is _sre_c.BRANCH:
            for branch in av[1]:
                _check_nested(list(branch), outer_first, ic, out)
        elif op in (_sre_c.ASSERT, _sre_c.ASSERT_NOT):
            _check_nested(list(av[1]), outer_first, ic, out)


_Open = tuple[frozenset[str], ...]


def _narrow(open_: _Open, chars: frozenset[str]) -> _Open:
    """Open elastics that can also absorb a mandatory item keep only the characters they share with it."""
    return tuple(dict.fromkeys(o & chars for o in open_ if o & chars))


def _check_adjacent(items: Sequence[Any], ic: bool, out: list[str], open_: _Open = ()) -> _Open:
    """Two elastic single-char repeats that can absorb the same characters at the same place.

    ``\\s*,?\\s*``-style runs split one stretch of characters in O(k²) ways per start position, which is what
    made the original M-044 pattern hang on CAD lines with long space runs. ``open_`` holds the character sets
    of the elastic repeats that could still stretch up to the current point: a mandatory item narrows each of
    them to the characters it can also absorb (and drops the ones it cannot); an optional item is skippable. The
    state is threaded through groups and branches; the state at the end of ``items`` is returned.
    """
    for op, av in items:
        if op in _ZERO_WIDTH:
            continue
        if op in _REPEATS:
            lo, hi, sub = av
            cs = _single_charset(sub, ic)
            if cs is not None:
                if _is_unbounded(hi):
                    if any(o & cs for o in open_):
                        out.append(
                            "adjacent elastic quantifiers over overlapping characters (polynomial backtracking)"
                        )
                    open_ = (cs,) if lo >= 1 else (*open_, cs)
                    continue
                if hi >= 2 and any(o & cs for o in open_):
                    # «слово[а-я]*[^\n]{0,60}?…»: the unbounded run gives back one character at a time and the
                    # filler re-scans it: O(run) per start, quadratic on long runs full of anchor words.
                    out.append(
                        "unbounded quantifier followed by an overlapping filler (quadratic on long runs)"
                    )
                if lo >= 1:
                    open_ = _narrow(open_, cs)
                continue  # an optional bounded filler is skippable and adds at most a constant factor
            inner = _check_adjacent(list(sub), ic, out, open_)
            open_ = tuple(dict.fromkeys((*open_, *inner))) if lo == 0 else inner
            continue
        if op is _sre_c.POSSESSIVE_REPEAT:
            _check_adjacent(list(av[2]), ic, out)
            open_ = ()
            continue
        cs = _charset(op, av, ic)
        if cs is not None:
            open_ = _narrow(open_, cs)
            continue
        if op is _sre_c.SUBPATTERN:
            open_ = _check_adjacent(list(av[3]), ic, out, open_)
        elif op is _sre_c.BRANCH:
            merged: list[frozenset[str]] = []
            for branch in av[1]:
                merged.extend(_check_adjacent(list(branch), ic, out, open_))
            open_ = tuple(dict.fromkeys(merged))
        elif op is _sre_c.ATOMIC_GROUP:
            _check_adjacent(list(av), ic, out)
            open_ = ()
        else:
            open_ = ()
    return open_


def _lookbehind_guard(op: Any, av: Any, ic: bool) -> frozenset[str] | None:
    """Characters excluded by a one-character negative lookbehind such as ``(?<!\\d)``."""
    if op is not _sre_c.ASSERT_NOT or av[0] != -1:
        return None
    return _single_charset(av[1], ic)


def _leading_elastic(items: Sequence[Any], ic: bool, guard: frozenset[str] = frozenset()) -> bool:
    """True when a match may start with an unbounded, backtracking repeat (O(n²) over search start positions).

    A preceding negative lookbehind that excludes the repeat's characters (``(?<!\\d)\\d+``) pins the start to
    the beginning of a run, which keeps the search linear.
    """
    for op, av in items:
        g = _lookbehind_guard(op, av, ic)
        if g is not None:
            guard = guard | g
            continue
        if op is _sre_c.AT and av in _START_ANCHORS:
            return False  # anchored at a line/string start: one attempt per line, not per character
        if op in _ZERO_WIDTH:
            continue
        if op in _REPEATS:
            lo, hi, sub = av
            cs = _single_charset(sub, ic)
            if _is_unbounded(hi) and cs is not None:
                return not cs <= guard
            if lo == 0:
                if _leading_elastic(list(sub), ic, guard):
                    return True
                continue
            return _leading_elastic(list(sub), ic, guard)
        if op is _sre_c.SUBPATTERN:
            return _leading_elastic(list(av[3]), ic, guard)
        if op is _sre_c.BRANCH:
            return any(_leading_elastic(list(b), ic, guard) for b in av[1])
        return False
    return False


def _walk(items: Sequence[Any]) -> Iterator[tuple[Any, Any]]:
    for op, av in items:
        yield op, av
        if op in (*_REPEATS, _sre_c.POSSESSIVE_REPEAT):
            yield from _walk(list(av[2]))
        elif op is _sre_c.SUBPATTERN:
            yield from _walk(list(av[3]))
        elif op is _sre_c.ATOMIC_GROUP:
            yield from _walk(list(av))
        elif op is _sre_c.BRANCH:
            for branch in av[1]:
                yield from _walk(list(branch))
        elif op in (_sre_c.ASSERT, _sre_c.ASSERT_NOT):
            yield from _walk(list(av[1]))
        elif op is _sre_c.GROUPREF_EXISTS:
            yield from _walk(list(av[1]))
            if av[2] is not None:
                yield from _walk(list(av[2]))


@lru_cache(maxsize=4096)
def regex_safety_problems(pattern: str, flags: int = 0) -> tuple[str, ...]:
    """Static ReDoS analysis of one pattern. Empty tuple = accepted.

    Rejected constructs: syntax errors; back-references; nested quantifiers whose inner repeat can re-match the
    outer iteration's first characters; adjacent elastic repeats over overlapping characters; a leading unbounded
    repeat (quadratic over search positions); bounded repeats above 1000. The analysis is conservative for the
    patterns in the seed and complements the timing fuzz test, it is not a proof for arbitrary regexes.
    """
    try:
        parsed = _sre_parse.parse(pattern, flags)
    except re.error as exc:
        return (f"does not compile: {exc}",)
    ic = bool(parsed.state.flags & re.IGNORECASE)
    items = list(parsed)
    problems: list[str] = []
    for op, av in _walk(items):
        if op in (_sre_c.GROUPREF, _sre_c.GROUPREF_EXISTS):
            problems.append("back-reference")
        if op in (*_REPEATS, _sre_c.POSSESSIVE_REPEAT):
            hi = av[1]
            if hi != _sre_c.MAXREPEAT and hi > 1000:
                problems.append(f"bounded repeat above 1000 ({hi})")
    _check_nested(items, None, ic, problems)
    _check_adjacent(items, ic, problems)
    if _leading_elastic(items, ic):
        problems.append("leading unbounded quantifier (quadratic search)")
    return tuple(dict.fromkeys(problems))


# ───────────────────────────────────────────── Regex safety: guarded execution ───────────────────────────────────────


def _raise_timeout(signum: int, frame: Any) -> None:
    raise _AlarmFired


class _AlarmFired(Exception):
    pass


@contextmanager
def _hard_time_limit(seconds: float) -> Iterator[bool]:
    """Arm a one-shot ITIMER_REAL alarm in the main thread; yields whether the limit is hard.

    CPython's regex engine checks for pending signals while backtracking, so the alarm interrupts a runaway
    match. The timer is not used when another SIGALRM user is active (a handler or a running timer), off the
    main thread, or on platforms without ``setitimer``.
    """
    if (
        seconds <= 0
        or not hasattr(signal, "setitimer")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield False
        return
    try:
        previous = signal.getsignal(signal.SIGALRM)
        busy = signal.getitimer(signal.ITIMER_REAL)[0] > 0
    except (ValueError, OSError):
        yield False
        return
    if busy or previous not in (signal.SIG_DFL, signal.SIG_IGN, None):
        yield False
        return
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous if previous is not None else signal.SIG_DFL)


def _windows(text: str, max_chars: int, overlap: int) -> Iterator[tuple[int, int, bool, bool]]:
    """Cut ``text`` into windows ``(start, end, artificial_start, artificial_end)`` of at most ``max_chars``.

    Windows end at a line break when one exists in the second half of the window; consecutive windows overlap
    by up to ``overlap`` characters and start at a line start when the overlap zone contains one.
    """
    n = len(text)
    if n <= max_chars:
        yield 0, n, False, False
        return
    start, artificial_start = 0, False
    while True:
        end = min(start + max_chars, n)
        if end >= n:
            yield start, n, artificial_start, False
            return
        cut = text.rfind("\n", start + max_chars // 2, end)
        artificial_end = cut == -1
        if not artificial_end:
            end = cut + 1
        yield start, end, artificial_start, artificial_end
        zone_lo = max(start + 1, end - overlap)
        line_start = text.rfind("\n", zone_lo, end - 1)
        if line_start != -1:
            start, artificial_start = line_start + 1, False
        else:
            start, artificial_start = zone_lo, True


@dataclass(frozen=True, slots=True)
class GuardedPattern:
    """A compiled, statically checked pattern that only ever runs on bounded windows under a time budget."""

    pattern: re.Pattern[str]
    label: str = "regex"
    max_window_chars: int = MAX_WINDOW_CHARS
    overlap_chars: int = WINDOW_OVERLAP_CHARS
    time_budget_s: float = DEFAULT_TIME_BUDGET_S

    @property
    def source(self) -> str:
        return self.pattern.pattern

    def _run_window(self, text: str, lo: int, hi: int) -> list[re.Match[str]]:
        t0 = time.perf_counter()
        with _hard_time_limit(self.time_budget_s) as hard:
            try:
                found = list(self.pattern.finditer(text, lo, hi))
            except _AlarmFired:
                raise RegexTimeout(self.label, time.perf_counter() - t0, hi - lo) from None
        elapsed = time.perf_counter() - t0
        if not hard and elapsed > self.time_budget_s:
            log.warning(
                "params.regex.slow",
                extra={"regex": self.label, "elapsed_s": round(elapsed, 4), "window_chars": hi - lo},
            )
        return found

    def finditer(self, text: str) -> Iterator[re.Match[str]]:
        """Non-overlapping matches in text order, across windows (duplicates from overlaps removed).

        Matches that touch an artificial window boundary (a cut inside a line longer than the window) are
        dropped because they may be truncated; the overlapping neighbour window sees them whole.
        """
        accepted: list[re.Match[str]] = []
        seen: set[tuple[int, int]] = set()
        for lo, hi, art_start, art_end in _windows(text, self.max_window_chars, self.overlap_chars):
            # finditer(pos, endpos) treats endpos as the end of the string, so «$» may fire at a cut: guarded below.
            for m in self._run_window(text, lo, hi):
                if (art_end and m.end() >= hi) or (art_start and m.start() == lo):
                    continue
                key = (m.start(), m.end())
                if key in seen:
                    continue
                seen.add(key)
                accepted.append(m)
        accepted.sort(key=lambda m: (m.start(), -m.end()))
        last_end = -1
        for m in accepted:
            if m.start() >= last_end or m.start() == m.end() == last_end:
                last_end = max(last_end, m.end())
                yield m

    def findall_matches(self, text: str) -> list[re.Match[str]]:
        return list(self.finditer(text))

    def search(self, text: str) -> re.Match[str] | None:
        return next(self.finditer(text), None)


def compile_guarded(
    pattern: str,
    flags: int = 0,
    *,
    label: str = "regex",
    max_chars: int = MAX_AUX_PATTERN_CHARS,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
    max_window_chars: int = MAX_WINDOW_CHARS,
    check: bool = True,
) -> GuardedPattern:
    """Compile a pattern for guarded use. Raises :class:`UnsafeRegexError` on a failed safety check."""
    if len(pattern) > max_chars:
        raise UnsafeRegexError(pattern, [f"pattern longer than {max_chars} characters ({len(pattern)})"])
    if check:
        problems = regex_safety_problems(pattern, flags)
        if problems:
            raise UnsafeRegexError(pattern, problems)
    return GuardedPattern(
        re.compile(pattern, flags),
        label=label,
        max_window_chars=max_window_chars,
        time_budget_s=time_budget_s,
    )


# ───────────────────────────────────────────────────── Context gates ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GateDecision:
    accepted: bool
    reason: str  # group:<name> | discipline:<code> | require | reject | nearest:require | nearest:reject | default


@dataclass(frozen=True, slots=True)
class ContextGate:
    """Accept or reject a regex match by its surroundings (e.g. «В20» concrete class vs «В20» exhaust system).

    Order: an ``accept_if_groups`` group that matched → accept; a discipline hint in ``reject_disciplines`` with
    no require-hit → reject, in ``accept_disciplines`` with no reject-hit → accept; then require/reject hits in
    the window; when both hit, the one nearest to the match wins (ties reject); nothing → ``default``.
    """

    id: str
    description: str
    window_chars: int
    require_any: tuple[GuardedPattern, ...] = ()
    reject_any: tuple[GuardedPattern, ...] = ()
    accept_if_groups: tuple[str, ...] = ()
    accept_disciplines: frozenset[str] = frozenset()
    reject_disciplines: frozenset[str] = frozenset()
    default: Literal["accept", "reject"] = "reject"

    @staticmethod
    def _nearest(patterns: Sequence[GuardedPattern], window: str, lo: int, hi: int) -> int | None:
        best: int | None = None
        for gp in patterns:
            for m in gp.finditer(window):
                if m.end() <= lo:
                    dist = lo - m.end()
                elif m.start() >= hi:
                    dist = m.start() - hi
                else:
                    dist = 0
                best = dist if best is None else min(best, dist)
        return best

    def decide(
        self,
        text: str,
        start: int,
        end: int,
        groups: Mapping[str, str | None] | None = None,
        discipline: str | None = None,
    ) -> GateDecision:
        for name in self.accept_if_groups:
            if groups and groups.get(name):
                return GateDecision(True, f"group:{name}")
        w_lo = max(0, start - self.window_chars)
        w_hi = min(len(text), end + self.window_chars)
        window = text[w_lo:w_hi]
        lo, hi = start - w_lo, end - w_lo
        req = self._nearest(self.require_any, window, lo, hi)
        rej = self._nearest(self.reject_any, window, lo, hi)
        disc = (discipline or "").strip().upper()
        if disc:
            keys = {disc, disc.rstrip("0123456789.")}  # «ОВ1» also matches a gate listing «ОВ»
            if keys & self.reject_disciplines and req is None:
                return GateDecision(False, f"discipline:{disc}")
            if keys & self.accept_disciplines and rej is None:
                return GateDecision(True, f"discipline:{disc}")
        if req is not None and rej is None:
            return GateDecision(True, "require")
        if rej is not None and req is None:
            return GateDecision(False, "reject")
        if req is not None and rej is not None:
            return GateDecision(req < rej, "nearest:require" if req < rej else "nearest:reject")
        return GateDecision(self.default == "accept", "default")


def _build_gate(raw: Mapping[str, Any]) -> ContextGate:
    def compile_all(key: str) -> tuple[GuardedPattern, ...]:
        return tuple(
            compile_guarded(p, label=f"gate:{raw['id']}:{key}:{i}", time_budget_s=0.1)
            for i, p in enumerate(raw.get(key, ()))
        )

    return ContextGate(
        id=raw["id"],
        description=raw.get("description", ""),
        window_chars=int(raw.get("window_chars", 60)),
        require_any=compile_all("require_any"),
        reject_any=compile_all("reject_any"),
        accept_if_groups=tuple(raw.get("accept_if_groups", ())),
        accept_disciplines=frozenset(d.upper() for d in raw.get("accept_disciplines", ())),
        reject_disciplines=frozenset(d.upper() for d in raw.get("reject_disciplines", ())),
        default=raw.get("default", "reject"),
    )


# ───────────────────────────────────────────────────── Seed files ────────────────────────────────────────────────────


def seed_dir() -> Path:
    return contracts_dir() / "seed"


@cache
def _read_seed_json(name: str, directory: str | None = None) -> dict[str, Any]:
    base = Path(directory) if directory else seed_dir()
    path = base / SEED_FILES[name]
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise SeedError(
            f"seed file not found: {path} (build it with packages/contracts/seed/src/build_seed.py)"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SeedError(f"seed file is not valid JSON: {path}: {exc}") from exc


@cache
def _seed_validator(name: str, directory: str | None = None) -> Draft202012Validator:
    base = (Path(directory) if directory else seed_dir()) / "schemas"
    resources = []
    for path in sorted(base.glob("*.schema.json")):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        resources.append(
            (
                f"{SEED_SCHEMA_BASE_URI}{path.name}",
                Resource.from_contents(doc, default_specification=DRAFT202012),
            )
        )
    reg = _contracts_registry().with_resources(resources)
    schema = reg.contents(f"{SEED_SCHEMA_BASE_URI}{name}.schema.json")
    return Draft202012Validator(schema, registry=reg)


def seed_validation_errors(name: str, document: Any = None, directory: str | Path | None = None) -> list[str]:
    """JSON-Schema errors of a seed document (default: the file on disk) against ``seed/schemas/<name>``."""
    d = str(directory) if directory else None
    doc = _read_seed_json(name, d) if document is None else document
    errors = sorted(_seed_validator(name, d).iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


# ───────────────────────────────────────────────────── Params ────────────────────────────────────────────────────────

_VALUE_GROUP_ORDER = ("v", "v2", "v3", "v4")


@dataclass(frozen=True, slots=True)
class RegexHit:
    code: str
    pattern_index: int  # 0 = regex_pattern, 1.. = regex_aux[i-1]
    start: int  # offsets in the (normalised) text given to extract()
    end: int
    text: str
    groups: Mapping[str, str | None]
    gate: str | None  # the gate decision reason, None when the parameter has no gate

    @property
    def value(self) -> str | None:
        """The primary value: the first non-empty of the ``v``, ``v2``, … named groups."""
        for name in _VALUE_GROUP_ORDER:
            val = self.groups.get(name)
            if val:
                return val
        return None


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One parameter of the seed. Typed accessors for the common fields; ``data`` holds the full record."""

    param_id: int
    code: str
    alias_codes: tuple[str, ...]
    short_name: str
    parameter_name: str
    name_variants: tuple[str, ...]
    section: str
    pd_section: str
    unit: str | None
    criticality: str
    criticality_level: CriticalityLevel
    review_priority: ReviewPriority
    data_type: DataType
    min_value: float | None
    max_value: float | None
    regex_pattern: str
    regex_aux: tuple[str, ...]
    regex_gates: tuple[str, ...]
    semantic_anchors: tuple[str, ...]
    linked_params: tuple[str, ...]
    hedge_group: tuple[str, ...]
    is_active: bool
    data: Mapping[str, Any] = field(repr=False, compare=False)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    @property
    def comparison_rule(self) -> Mapping[str, Any]:
        return self.data["comparison_rule"]

    @property
    def display(self) -> str:
        """Protocol display «{short_name} ({code})» (97 §2.9)."""
        return f"{self.short_name} ({self.code})"

    def to_catalog_row(self) -> CatalogRow:
        return CatalogRow(
            parameter_id=self.param_id,
            parameter_code=self.code,
            pd_section=self.pd_section,
            parameter_name=self.parameter_name,
            unit=self.unit,
            source_pd=self.data.get("source_pd"),
            source_rd=self.data.get("source_rd"),
            source_id=self.data.get("source_id"),
            trigger=self.data.get("trigger_logic"),
            criticality=self.criticality,
            matrix_row=self.data["matrix_row"],
            mapping_status=ParameterMappingStatus(self.data["mapping_status"]),
        )

    @classmethod
    def from_record(cls, rec: Mapping[str, Any]) -> ParamSpec:
        return cls(
            param_id=int(rec["param_id"]),
            code=rec["code"],
            alias_codes=tuple(rec["alias_codes"]),
            short_name=rec["short_name"],
            parameter_name=rec["parameter_name"],
            name_variants=tuple(rec.get("name_variants", ())),
            section=rec["section"],
            pd_section=rec["pd_section"],
            unit=rec.get("unit"),
            criticality=rec["criticality"],
            criticality_level=CriticalityLevel(rec["criticality_level"]),
            review_priority=ReviewPriority(rec["review_priority"]),
            data_type=DataType(rec["data_type"]),
            min_value=rec.get("min_value"),
            max_value=rec.get("max_value"),
            regex_pattern=rec["regex_pattern"],
            regex_aux=tuple(rec.get("regex_aux", ())),
            regex_gates=tuple(rec.get("regex_gates", ())),
            semantic_anchors=tuple(rec.get("semantic_anchors", ())),
            linked_params=tuple(rec.get("linked_params", ())),
            hedge_group=tuple(rec.get("hedge_group", ())),
            is_active=bool(rec.get("is_active", True)),
            data=MappingProxyType(dict(rec)),
        )


@dataclass(frozen=True, slots=True)
class CodeResolution:
    """Result of resolving any code style (and optionally a parameter name) to a catalog parameter."""

    raw: str
    param_id: int
    code: str
    method: Literal["canonical", "alias", "homoglyph", "known_fix", "by_name", "by_id_prefix_mismatch"]
    style: str | None
    warnings: tuple[str, ...] = ()


_DASH_CHARS = "‐‑‒–—―−"
_CODE_SPACES = re.compile(r"\s*-\s*")
_LAT_TO_CYR = str.maketrans("ABCEHKMOPTXY", "АВСЕНКМОРТХУ")
_CYR_TO_LAT = str.maketrans("АВСЕНКМОРТХУ", "ABCEHKMOPTXY")
_NAME_WORD = re.compile(r"[0-9a-zа-я]+")


_NO_DASH_CODE = re.compile(r"^((?:IOS|ИОС)[1-5]|[A-ZА-ЯЁ]+)\s*(\d{1,3})$")


def _clean_code(raw: str) -> str:
    """Typography-insensitive form: NFKC, brackets/quotes stripped, any dash → «-», «KR 55»/«KR55» → «KR-55»."""
    text = unicodedata.normalize("NFKC", raw).strip().strip("()[]«»\"'").strip()
    for ch in _DASH_CHARS:
        text = text.replace(ch, "-")
    text = _CODE_SPACES.sub("-", text).upper()
    if "-" not in text:
        text = _NO_DASH_CODE.sub(r"\1-\2", text)
    return text


@lru_cache(maxsize=4096)
def _norm_name(text: str) -> str:
    return " ".join(_NAME_WORD.findall(text.lower().replace("ё", "е")))


@lru_cache(maxsize=4096)
def _stems(text: str) -> frozenset[str]:
    """Crude Russian stemming: the first five letters of every word of three or more letters (and numbers)."""
    return frozenset(w[:5] for w in _norm_name(text).split() if len(w) >= 3 or w.isdigit())


def _name_score(query: str, candidate: str) -> float:
    """0…1: stem containment (0.6) + stem Jaccard (0.2) + character sequence ratio (0.2)."""
    q, c = _stems(query), _stems(candidate)
    if not q or not c:
        return 0.0
    common = len(q & c)
    if not common:
        return 0.0  # at most 0.2 from the sequence ratio: never a match (NAME_MATCH_MIN_SCORE = 0.75)
    containment = common / len(q)
    jaccard = common / len(q | c)
    seq = difflib.SequenceMatcher(None, _norm_name(query), _norm_name(candidate)).ratio()
    return 0.6 * containment + 0.2 * jaccard + 0.2 * seq


NAME_MATCH_MIN_SCORE = 0.75
NAME_MATCH_MIN_MARGIN = 0.08


class ParamRegistry:
    """All 132 parameters plus the seed-level dictionaries (context gates, hedge groups)."""

    def __init__(self, document: Mapping[str, Any]):
        self.document = document
        self.params: tuple[ParamSpec, ...] = tuple(ParamSpec.from_record(r) for r in document["params"])
        self.by_id: dict[int, ParamSpec] = {p.param_id: p for p in self.params}
        self.by_code: dict[str, ParamSpec] = {p.code: p for p in self.params}
        self._by_alias: dict[str, ParamSpec] = {}
        for p in self.params:
            for key in (p.code, *p.alias_codes):
                self._by_alias[_clean_code(key)] = p
        self.gates: dict[str, ContextGate] = {
            g["id"]: _build_gate(g) for g in document.get("context_gates", ())
        }
        self.hedge_groups: tuple[tuple[str, ...], ...] = tuple(
            tuple(g["codes"]) for g in document.get("hedge_groups", ())
        )
        self._patterns: dict[str, tuple[GuardedPattern, ...]] = {}

    def __len__(self) -> int:
        return len(self.params)

    def __iter__(self) -> Iterator[ParamSpec]:
        return iter(self.params)

    @property
    def matrix_version(self) -> str:
        return str(self.document["matrix_version"])

    @property
    def content_sha256(self) -> str:
        return str(self.document["content_sha256"])

    @property
    def overrides(self) -> dict[str, Any]:
        """What was read from the admin overrides file (``applied``, ``reason``, ``path``, ``sha256``, ``changed`` …)."""
        info = self.document.get("matrix_overrides")
        return dict(info) if info else _no_overrides()

    def get(self, key: str | int) -> ParamSpec:
        """Look a parameter up by id, catalog code or any alias. Strict: raises on a prefix/id conflict."""
        if isinstance(key, int):
            try:
                return self.by_id[key]
            except KeyError:
                raise ParameterCodeError(f"parameter id {key} is outside 1..132") from None
        return self.by_id[self.resolve(key, strict=True).param_id]

    def resolve(self, raw: str, name: str | None = None, *, strict: bool = False) -> CodeResolution:
        """Resolve a code in any style (97 §2.9) to a parameter; see :func:`resolve_code`."""
        warnings: list[str] = []
        text = _clean_code(raw)
        hit = self._by_alias.get(text)
        if hit is not None and name is None:
            method = "canonical" if text == hit.code else "alias"
            return CodeResolution(raw, hit.param_id, hit.code, method, _style_of(text))
        parsed, method = self._parse(text, warnings)
        if parsed is None:
            raise ParameterCodeError(f"not a parameter code: {raw!r}")
        by_name = self.match_name(name) if name else None
        fixed_code = _known_fix(text)
        if parsed.fixed_by_known_alias or fixed_code:
            spec = self.by_code[fixed_code] if fixed_code else self.by_id[parsed.param_id]
            warnings.append(
                f"код {raw!r} — известная ошибка в материалах организаторов, по наименованию это {spec.code}"
            )
            if by_name is not None and by_name.param_id != spec.param_id:
                warnings.append(f"наименование {name!r} указывает на {by_name.code}; принят {by_name.code}")
                spec = by_name
            return CodeResolution(raw, spec.param_id, spec.code, "known_fix", parsed.style, tuple(warnings))
        if parsed.prefix_mismatch:
            if by_name is not None:
                warnings.append(
                    f"префикс кода {raw!r} не соответствует номеру {parsed.param_id}; "
                    f"параметр определён по наименованию: {by_name.code}"
                )
                return CodeResolution(
                    raw, by_name.param_id, by_name.code, "by_name", parsed.style, tuple(warnings)
                )
            msg = f"префикс кода {raw!r} не соответствует диапазону номеров раздела; принят номер {parsed.canonical}"
            if strict:
                raise ParameterCodeError(msg)
            warnings.append(msg)
            return CodeResolution(
                raw, parsed.param_id, parsed.canonical, "by_id_prefix_mismatch", parsed.style, tuple(warnings)
            )
        spec = self.by_id[parsed.param_id]
        if name:
            if by_name is not None and by_name.param_id != spec.param_id:
                warnings.append(
                    f"наименование {name!r} ближе к {by_name.code}, чем к {spec.code}; код сохранён"
                )
            elif by_name is None and self.name_score(name, spec) < 0.5:
                warnings.append(f"наименование {name!r} слабо согласуется с {spec.code}")
        if method == "homoglyph":
            warnings.append(
                f"префикс кода {raw!r} набран буквами другого алфавита (латиница/кириллица); распознан как {spec.code}"
            )
        if method is None:
            method = "canonical" if text == spec.code else "alias"
        return CodeResolution(raw, spec.param_id, spec.code, method, parsed.style, tuple(warnings))

    @staticmethod
    def _parse(text: str, warnings: list[str]) -> tuple[_codes.ParsedCode | None, Any]:
        try:
            return _codes.parse_parameter_code(text), None
        except ParameterCodeError:
            pass
        prefix, sep, rest = text.partition("-")
        if not sep:
            return None, None
        for candidate in (prefix.translate(_LAT_TO_CYR), prefix.translate(_CYR_TO_LAT)):
            if candidate == prefix:
                continue
            try:
                return _codes.parse_parameter_code(f"{candidate}-{rest}"), "homoglyph"
            except ParameterCodeError:
                continue
        return None, None

    def name_score(self, name: str, spec: ParamSpec) -> float:
        return max(_name_score(name, n) for n in (spec.parameter_name, spec.short_name, *spec.name_variants))

    def match_name(self, name: str) -> ParamSpec | None:
        """Best parameter for a (short or full) name, or None when no candidate is clear enough."""
        scored = sorted(((self.name_score(name, p), p.param_id) for p in self.params), reverse=True)
        (best, best_id), (second, _) = scored[0], scored[1]
        if best >= NAME_MATCH_MIN_SCORE and best - second >= NAME_MATCH_MIN_MARGIN:
            return self.by_id[best_id]
        return None

    def hedge_codes(self, code: str) -> tuple[str, ...]:
        """The other codes of the parameter's hedge group (97 §2.10 top-2 hedge candidates)."""
        spec = self.get(code)
        return tuple(c for c in spec.hedge_group if c != spec.code)

    def patterns(self, code: str) -> tuple[GuardedPattern, ...]:
        spec = self.get(code)
        cached = self._patterns.get(spec.code)
        if cached is None:
            sources = (spec.regex_pattern, *spec.regex_aux)
            cached = tuple(
                compile_guarded(src, label=f"{spec.code}#{i}") for i, src in enumerate(sources) if src
            )
            self._patterns[spec.code] = cached
        return cached

    def extract(
        self, code: str, text: str, *, discipline: str | None = None, apply_gates: bool = True
    ) -> list[RegexHit]:
        """Run the parameter's regexes over already normalised text (:func:`normalize_regex_input`)."""
        spec = self.get(code)
        gates = [self.gates[g] for g in spec.regex_gates]
        hits: list[RegexHit] = []
        for index, gp in enumerate(self.patterns(spec.code)):
            for m in gp.finditer(text):
                groups = MappingProxyType(m.groupdict())
                reason: str | None = None
                if apply_gates and gates:
                    accepted = True
                    reasons = []
                    for gate in gates:
                        decision = gate.decide(text, m.start(), m.end(), groups, discipline)
                        reasons.append(f"{gate.id}:{decision.reason}")
                        accepted = accepted and decision.accepted
                    if not accepted:
                        continue
                    reason = ",".join(reasons)
                hits.append(RegexHit(spec.code, index, m.start(), m.end(), m.group(0), groups, reason))
        hits.sort(key=lambda h: (h.start, h.pattern_index))
        return hits


@lru_cache(maxsize=1)
def _known_fixes() -> dict[tuple[str, int], str]:
    """codes.yaml known_alias_fixes keyed by (Latin prefix, number): «AR-14», «АР-14», «AR-014» are one typo."""
    out: dict[tuple[str, int], str] = {}
    for fix in load_codes().get("known_alias_fixes", ()):
        prefix, _, number = fix["alias"].upper().partition("-")
        out[(_latin_prefix(prefix), int(number))] = fix["resolves_to"]
    return out


def _latin_prefix(prefix: str) -> str:
    """Latin section prefix for a prefix typed in either alphabet or with look-alike letters («AP» → «AR»)."""
    for candidate in (prefix, prefix.translate(_LAT_TO_CYR), prefix.translate(_CYR_TO_LAT)):
        for p in _codes.prefixes():
            if candidate in (p.latin, p.cyrillic):
                return p.latin
    return prefix


def _known_fix(text: str) -> str | None:
    prefix, sep, number = text.partition("-")
    if not sep or not number.isdigit():
        return None
    return _known_fixes().get((_latin_prefix(prefix), int(number)))


def _style_of(text: str) -> str | None:
    try:
        return _codes.parse_parameter_code(text).style
    except ParameterCodeError:
        return None


# ─────────────────────────────────────── admin overrides (ТЗ module 8, «без перекодирования») ───────────────────────────

MATRIX_OVERRIDES_ENV = "INSPECTOR_MATRIX_OVERRIDES"
"""Path of the overrides file, or ``off``/``none``/``0`` to disable them. Unset → ``<repo>/.cache/matrix_overrides.json``
when that file exists (the API writes it on every edit in /admin/normative)."""
MATRIX_OVERRIDES_DEFAULT = Path(".cache") / "matrix_overrides.json"
_OVERRIDES_OFF = frozenset({"off", "none", "0", "false", "disabled"})
_OVERRIDE_FIELDS = ("min_value", "max_value", "is_active")


def _no_overrides(reason: str = "no_file") -> dict[str, Any]:
    return {
        "applied": False,
        "reason": reason,
        "path": None,
        "sha256": None,
        "count": 0,
        "changed": [],
        "changed_count": 0,
    }


def resolve_overrides_path() -> tuple[Path | None, str]:
    """(path, reason): the overrides file the pipeline would read now; ``path`` is None when there is none."""
    raw = os.environ.get(MATRIX_OVERRIDES_ENV)
    if raw is not None:
        if raw.strip().lower() in _OVERRIDES_OFF or not raw.strip():
            return None, "disabled_by_env"
        return Path(raw).expanduser(), "env"
    try:
        default = repo_root() / MATRIX_OVERRIDES_DEFAULT
    except Exception:
        return None, "no_file"
    return (default, "default") if default.is_file() else (None, "no_file")


def overrides_summary(info: Mapping[str, Any]) -> str:
    """One-line record of the overrides state for ``versions.engine_versions.matrix_overrides`` (str → str map)."""
    if not info.get("sha256"):
        return f"none ({info.get('reason', 'no_file')})"
    return f"sha256:{str(info['sha256'])[:12]} rows={info.get('count', 0)} changed={info.get('changed_count', 0)}"


def _file_key(path: Path | None) -> tuple[str, int, int] | None:
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), st.st_mtime_ns, st.st_size)


def _parse_overrides(
    path: Path, raw: bytes, doc: Mapping[str, Any], registry_codes: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """code → {min_value?, max_value?, is_active?}. Strict: a malformed file must never be half-applied."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeedError(f"matrix overrides file is not valid JSON: {path}: {exc}") from exc
    rows = data.get("overrides") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise SeedError(f"matrix overrides file must hold a list `overrides`: {path}")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise SeedError(f"matrix override row is not an object: {row!r}")
        code = row.get("param_code", row.get("code"))
        if code not in registry_codes:
            raise SeedError(f"matrix override for an unknown parameter: {code!r}")
        patch: dict[str, Any] = {}
        for key in ("min_value", "max_value"):
            if key in row:
                v = row[key]
                if v is not None and (isinstance(v, bool) or not isinstance(v, int | float) or v != v):
                    raise SeedError(f"matrix override {code}.{key} must be a number or null, got {v!r}")
                patch[key] = None if v is None else float(v)
        if row.get("is_active") is not None:
            if not isinstance(row["is_active"], bool):
                raise SeedError(f"matrix override {code}.is_active must be boolean, got {row['is_active']!r}")
            patch["is_active"] = row["is_active"]
        lo, hi = (
            patch.get("min_value", registry_codes[code].get("min_value")),
            patch.get("max_value", registry_codes[code].get("max_value")),
        )
        if lo is not None and hi is not None and lo > hi:
            raise SeedError(f"matrix override {code}: min_value {lo} is greater than max_value {hi}")
        if patch:
            out[code] = patch
    return out


def _retarget_rule(node: Any, base: Mapping[str, Any], eff: Mapping[str, Any]) -> Any:
    """Copy of a comparison rule whose threshold literals follow the effective min/max.

    ``"$min_value"`` / ``"$max_value"`` tokens are replaced; so are bounds equal to the seed value
    (``bounds.min/max``, ``min_ratio``, ``max_distance_m``). Conditional bounds that differ from the seed value
    (e.g. the 1.0 m corridor case) are content, not the matrix threshold, and stay as they are.
    """
    if isinstance(node, list):
        return [_retarget_rule(x, base, eff) for x in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, val in node.items():
        if key == "bounds" and isinstance(val, dict):
            nb: dict[str, Any] = {}
            for bk, bv in val.items():
                which = {"min": "min_value", "max": "max_value"}.get(bk)
                if which and (
                    bv == f"${which}"
                    or (bv is not None and not isinstance(bv, str) and bv == base.get(which))
                ):
                    nb[bk] = eff[which]
                else:
                    nb[bk] = _retarget_rule(bv, base, eff)
            out[key] = nb
        elif (
            key in ("min_ratio", "max_distance_m")
            and isinstance(val, int | float)
            and not isinstance(val, bool)
        ):
            which = "min_value" if key == "min_ratio" else "max_value"
            out[key] = eff[which] if val == base.get(which) and eff[which] is not None else val
        else:
            out[key] = _retarget_rule(val, base, eff)
    return out


def _apply_overrides(document: dict[str, Any], path: Path, reason: str) -> dict[str, Any]:
    """The seed document with the admin overrides applied (a new dict; the cached seed is never mutated)."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SeedError(f"matrix overrides file cannot be read: {path}: {exc}") from exc
    by_code = {r["code"]: r for r in document["params"]}
    patches = _parse_overrides(path, raw, document, by_code)
    sha = hashlib.sha256(raw).hexdigest()
    try:
        file_version = json.loads(raw).get("matrix_version")
    except (ValueError, AttributeError):
        file_version = None
    params_out: list[dict[str, Any]] = []
    changed: list[str] = []
    for rec in document["params"]:
        patch = patches.get(rec["code"])
        new = dict(rec)
        if patch:
            diffs = {k: v for k, v in patch.items() if rec.get(k) != v}
            if diffs:
                new.update(diffs)
                new["comparison_rule"] = _retarget_rule(
                    rec["comparison_rule"],
                    rec,
                    {"min_value": new.get("min_value"), "max_value": new.get("max_value")},
                )
                new["override"] = {"base": {k: rec.get(k) for k in diffs}, "effective": diffs}
                changed.append(rec["code"])
        params_out.append(new)
    base_version = str(document["matrix_version"])
    doc = dict(document)
    doc["params"] = params_out
    if changed or patches:
        version = (
            str(file_version)
            if isinstance(file_version, str) and file_version.startswith(base_version)
            else f"{base_version}+ovr.{sha[:8]}"
        )
        doc["matrix_version"] = version
    if changed:
        canon = json.dumps({c: patches[c] for c in sorted(changed)}, sort_keys=True, ensure_ascii=False)
        doc["content_sha256"] = hashlib.sha256(
            (str(document["content_sha256"]) + "\n" + canon).encode()
        ).hexdigest()
    doc["matrix_overrides"] = {
        "applied": bool(changed),
        "reason": reason,
        "path": str(path),
        "sha256": sha,
        "count": len(patches),
        "changed": sorted(changed),
        "changed_count": len(changed),
        "base_matrix_version": base_version,
        "matrix_version": str(doc["matrix_version"]),
    }
    return doc


@cache
def _load_params_cached(
    directory: str | None, overrides_key: tuple[str, int, int] | None, reason: str
) -> ParamRegistry:
    document = _read_seed_json("params", directory)
    if overrides_key is None:
        info = _no_overrides(reason)
        info["base_matrix_version"] = info["matrix_version"] = str(document["matrix_version"])
        document = {**document, "matrix_overrides": info}
    else:
        document = _apply_overrides(document, Path(overrides_key[0]), reason)
    return ParamRegistry(document)


def load_params(directory: str | Path | None = None) -> ParamRegistry:
    """The params seed as a :class:`ParamRegistry` (cached per directory and overrides file state).

    Admin overrides from ``/admin/normative`` (``min_value`` / ``max_value`` / ``is_active``) are applied over the seed
    from ``.cache/matrix_overrides.json`` or the file named by ``INSPECTOR_MATRIX_OVERRIDES`` (``off`` disables). The
    registry then carries the effective ``matrix_version`` («<seed>+ovr.N») and ``registry.overrides`` (what was read).
    A custom seed ``directory`` never reads overrides.
    """
    if directory:
        return _load_params_cached(str(directory), None, "custom_seed_dir")
    path, reason = resolve_overrides_path()
    return _load_params_cached(None, _file_key(path), reason)


def get_param(code_or_alias: str | int) -> ParamSpec:
    """Any code style or the integer id → :class:`ParamSpec` (``.to_catalog_row()`` gives the organizer row)."""
    return load_params().get(code_or_alias)


def resolve_code(raw: str, name: str | None = None, *, strict: bool = False) -> CodeResolution:
    """Resolve a parameter code in any style to the catalog parameter (97 §2.9).

    Accepts the catalog code (KR-055), M-xxx, the ТЗ/Приложение 2 short forms in Latin or Cyrillic (KR-55, КР-55),
    any zero padding, typographic dashes, and prefixes typed in the wrong alphabet (KP-55 → КР-55, with a warning).
    The prefix must agree with the id range: a known organizer typo (AR-14 → AR-040) is resolved with a warning; any
    other disagreement is resolved by ``name`` when given, else by the number (warning) or raises when ``strict``.
    """
    return load_params().resolve(raw, name, strict=strict)


def criticality_level(param: int | str) -> CriticalityLevel:
    return load_params().get(param).criticality_level


# ─────────────────────────────────────────────── Catalog (organizer data) ────────────────────────────────────────────


def load_catalog(path: str | Path | None = None) -> list[CatalogRow]:
    """``parameter_catalog_132.jsonl`` rows (organizer data, read-only) validated by the contract model."""
    if path is None:
        from inspector_common.settings import Settings

        path = Settings().paths.catalog_path
    rows: list[CatalogRow] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(CatalogRow.model_validate(json.loads(line)))
    return rows


# ─────────────────────────────────────────────── Change map and FREE topics ──────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Route:
    family: str
    discrepancy_types: tuple[str, ...]
    parameter_code: str | None  # a catalog code, «FREE-<TOPIC>» (numbered per group at export), or None
    parameter_mapping_status: ParameterMappingStatus | None
    emit: bool
    comparison_result: str | None
    hedge_codes: tuple[str, ...]
    basis: str
    data: Mapping[str, Any] = field(repr=False, compare=False)

    @property
    def is_free(self) -> bool:
        return bool(self.parameter_code and self.parameter_code.startswith("FREE-"))

    @property
    def free_topic(self) -> FreeTopic | None:
        return (
            FreeTopic(self.parameter_code.removeprefix("FREE-"))
            if self.is_free and self.parameter_code
            else None
        )


class ChangeMap:
    """Element-family routing (97 §2.10): which code a change of an element family is reported under."""

    def __init__(self, document: Mapping[str, Any]):
        self.document = document
        self.families: dict[str, Mapping[str, Any]] = {f["family"]: f for f in document["element_families"]}
        self._routes: dict[tuple[str, str], Route] = {}
        for fam in document["element_families"]:
            for r in fam["routes"]:
                route = Route(
                    family=fam["family"],
                    discrepancy_types=tuple(r["discrepancy_types"]),
                    parameter_code=r.get("parameter_code"),
                    parameter_mapping_status=(
                        ParameterMappingStatus(r["parameter_mapping_status"])
                        if r.get("parameter_mapping_status")
                        else None
                    ),
                    emit=bool(r["emit"]),
                    comparison_result=r.get("comparison_result"),
                    hedge_codes=tuple(r.get("hedge_codes", ())),
                    basis=r.get("basis", ""),
                    data=MappingProxyType(dict(r)),
                )
                for dt in route.discrepancy_types:
                    key = (fam["family"], dt)
                    if key in self._routes:
                        raise SeedError(f"change map: duplicate route for {key}")
                    self._routes[key] = route

    def route(self, family: str, discrepancy_type: str | DiscrepancyType) -> Route:
        dt = str(discrepancy_type)
        try:
            return self._routes[(family, dt)]
        except KeyError:
            if family not in self.families:
                raise KeyError(f"unknown element family {family!r}") from None
            raise KeyError(f"no route for {family} × {dt}") from None

    def routes(self) -> list[Route]:
        return list(dict.fromkeys(self._routes.values()))

    def families_for_code(self, code: str) -> list[str]:
        return sorted({r.family for r in self._routes.values() if r.parameter_code == code})


@dataclass(frozen=True, slots=True)
class FreeTopicSpec:
    topic: FreeTopic
    label_ru: str
    disciplines: tuple[str, ...]
    data: Mapping[str, Any] = field(repr=False, compare=False)

    def code(self, n: int) -> str:
        return _codes.free_code(self.topic.value, n)


@cache
def _load_change_map_cached(directory: str | None) -> ChangeMap:
    return ChangeMap(_read_seed_json("change_matrix_map", directory))


def load_change_map(directory: str | Path | None = None) -> ChangeMap:
    return _load_change_map_cached(str(directory) if directory else None)


@cache
def _load_free_topics_cached(directory: str | None) -> dict[str, FreeTopicSpec]:
    doc = _read_seed_json("free_topics", directory)
    return {
        t["topic"]: FreeTopicSpec(FreeTopic(t["topic"]), t["label_ru"], tuple(t.get("disciplines", ())), t)
        for t in doc["topics"]
    }


def load_free_topics(directory: str | Path | None = None) -> dict[str, FreeTopicSpec]:
    return _load_free_topics_cached(str(directory) if directory else None)


# ─────────────────────────────────────────────── Term classifiers (context gates) ────────────────────────────────────

BTokenKind = Literal["CONCRETE_CLASS", "VENT_SYSTEM", "UNKNOWN"]
IdKind = Literal["AS_BUILT", "SOURCE_DATA", "UNKNOWN"]


def classify_b_token(text: str, start: int, end: int, discipline: str | None = None) -> BTokenKind:
    """«В20»/«B20» at ``text[start:end]``: concrete strength class or an exhaust-ventilation system (97 §2.14)."""
    reg = load_params()
    concrete = reg.gates["CONCRETE_CLASS"].decide(text, start, end, None, discipline)
    vent = reg.gates["VENT_SYSTEM_TAG"].decide(text, start, end, None, discipline)
    if concrete.accepted and not vent.accepted:
        return "CONCRETE_CLASS"
    if vent.accepted and not concrete.accepted:
        return "VENT_SYSTEM"
    return "UNKNOWN"


def classify_id_abbreviation(text: str, start: int, end: int) -> IdKind:
    """«ИД» at ``text[start:end]``: исполнительная документация (the ID stage) or «исходные данные» (П-ИД)."""
    reg = load_params()
    source = reg.gates["ID_AS_SOURCE_DATA"].decide(text, start, end)
    if source.accepted:
        return "SOURCE_DATA"
    asbuilt = reg.gates["ID_AS_BUILT"].decide(text, start, end)
    return "AS_BUILT" if asbuilt.accepted else "UNKNOWN"


# ─────────────────────────────────── Russian number and value formatting (93 §3.5) ───────────────────────────────────


def _to_decimal(value: Any) -> Decimal:
    """int/float/Decimal/numeric string → Decimal, keeping the written scale («1,0» → 1.0, 1.0 → 1.0)."""
    if isinstance(value, bool):
        raise TypeError("a boolean is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip().replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return Decimal(text)
        except InvalidOperation:
            raise ValueError(f"not a number: {value!r}") from None
    raise TypeError(f"not a number: {value!r}")


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    return isinstance(value, str) and bool(_NUMBER_TEXT.fullmatch(value.strip()))


_NUMBER_TEXT = re.compile(r"[+-]?\d+(?:[   ]\d{3})*(?:[.,]\d+)?")


def format_number_ru(value: Any, *, decimals: int | None = None, group_thousands: bool = False) -> str:
    """Russian number format: decimal comma, the written scale kept («1,0»), no exponent.

    ``decimals`` rounds half-up to that many places. ``group_thousands`` separates groups of five-digit and longer
    integer parts with a space (the submission style keeps them unseparated, value_templates number_format).
    """
    d = _to_decimal(value)
    if decimals is not None:
        d = d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    int_part, _, frac = format(abs(d), "f").partition(".")
    if group_thousands and len(int_part) > 4:
        head = len(int_part) % 3 or 3
        int_part = " ".join([int_part[:head], *(int_part[i : i + 3] for i in range(head, len(int_part), 3))])
    return sign + int_part + ("," + frac if frac else "")


def plural_ru(n: int, forms: Mapping[str, str]) -> str:
    """Russian count form: 1, 21 → one; 2–4, 22–24 → few; 0, 5–20, 25… → many (93 §5.4 «Отсутствуют 2 узла»)."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms["one"]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms["few"]
    return forms["many"]


def _plural_key(n: int) -> str:
    return plural_ru(n, {"one": "one", "few": "few", "many": "many"})


def _scale(d: Decimal) -> int:
    exp = d.as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def _display_unit(unit: str | None, vt: ValueTemplates | None = None) -> str | None:
    if unit is None:
        return None
    unit = unit.strip()
    if not unit:
        return None
    vt = vt or load_value_templates()
    return vt.units.get(unit, unit)


def _with_unit(number_text: str, unit: str | None, vt: ValueTemplates | None = None) -> str:
    vt = vt or load_value_templates()
    unit = _display_unit(unit, vt)
    if not unit:
        return number_text
    if unit == "%":
        return vt.number_format["percent"].format(value=number_text)
    if unit == "‰":
        return vt.number_format["per_mille"].format(value=number_text)
    return f"{number_text}{vt.number_format['unit_separator']}{unit}"


def format_value(
    value: Any, unit: str | None = None, *, kind: str | None = None, directory: str | Path | None = None
) -> str | None:
    """One stage value in submission style (93 §3.5): «1,0 м», «4×95 мм²», «850 м²», «B35», «EI-60».

    Numbers keep their written scale; a list/tuple is a dimension set («4×95», «500×300»); a class or mark string
    is normalised by value_templates ``class_formats`` (``kind`` selects a format that needs it, e.g.
    CONCRETE_CLASS); any other string is returned with collapsed spaces. ``None`` stays ``None``.
    """
    if value is None:
        return None
    vt = load_value_templates(directory)
    group = bool(vt.number_format["group_thousands"])
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        sep = vt.number_format["dimension_separator"]
        text = sep.join(format_number_ru(v, group_thousands=group) for v in value)
        return _with_unit(text, unit, vt)
    if _is_number(value):
        return _with_unit(format_number_ru(value, group_thousands=group), unit, vt)
    text = " ".join(str(value).split())
    if not text:
        return None
    formatted = vt.format_class(text, kind)
    if formatted is not None:
        text = formatted
    return _with_unit(text, unit, vt) if unit and _display_unit(unit, vt) not in text else text


def format_delta(
    fmt: str,
    expected: Any,
    actual: Any,
    *,
    unit: str | None = None,
    count_noun: Mapping[str, str] | None = None,
    directory: str | Path | None = None,
) -> tuple[str, float, str | None] | None:
    """Magnitude of a deviation (93 §5.4, recommendation_templates conventions.delta_formats).

    ABS → |ПД − факт| in the parameter unit («0,3 м»); PCT → |Δ| / ПД × 100, one decimal half-up without «,0»
    («16%», «7,7%»); COUNT → integer with the Russian count form («2 узла»); NONE → None. Returns
    ``(text, magnitude, unit)`` or None when it cannot be computed.
    """
    fmt = fmt.upper()
    if fmt == "NONE" or expected is None or actual is None:
        return None
    try:
        e, a = _to_decimal(expected), _to_decimal(actual)
    except (TypeError, ValueError):
        return None
    diff = abs(e - a)
    vt = load_value_templates(directory)
    if fmt == "ABS":
        diff = diff.quantize(Decimal(1).scaleb(-max(_scale(e), _scale(a))), rounding=ROUND_HALF_UP)
        return _with_unit(format_number_ru(diff), unit, vt), float(diff), _display_unit(unit, vt)
    if fmt == "PCT":
        if e == 0:
            return None
        pct = (diff / abs(e) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if pct == pct.to_integral_value():
            pct = pct.quantize(Decimal(1))
        return _with_unit(format_number_ru(pct), "%", vt), float(pct), "%"
    if fmt == "COUNT":
        if diff != diff.to_integral_value() or not count_noun:
            return None
        n = int(diff)
        noun = plural_ru(n, count_noun)
        return f"{n} {noun}", float(n), count_noun.get("many")
    raise ValueError(f"unknown delta format {fmt!r}")


# ───────────────────────────────────────────── Value templates (pd/rd/id_value) ──────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Noun:
    """An element noun of the value templates: nominative («Тёплый пол»), agreement (m/f/n/pl), genitive."""

    nom: str
    agr: Literal["m", "f", "n", "pl"]
    gen: str | None = None


_STAGE_KEYS = {"PD": "pd_value", "RD": "rd_value", "ID": "id_value"}
_TEMPLATE_PLACEHOLDER = re.compile(r"\{([~]?[A-Za-zА-Яа-яЁё_]+)\}")


def _fill_class_format(fmt: str, groups: Sequence[str]) -> str:
    """«{1}-{2}» with («EI», «60») → «EI-60»; a decimal point in a class («22.5») is printed with a comma."""
    filled = re.sub(r"\{(\d)\}", lambda g: groups[int(g.group(1)) - 1].replace(",", "."), fmt)
    return filled.replace(".", ",")


class ValueTemplates:
    """value_templates.json: submission-style formats, generic templates per ComparisonResult, noun lexicon."""

    def __init__(self, document: Mapping[str, Any]):
        self.document = document
        self.number_format: Mapping[str, Any] = document["number_format"]
        self.units: Mapping[str, str] = document["units"]
        self.cells: Mapping[str, str] = document["cells"]
        self.predicates: Mapping[str, Mapping[str, str]] = document["predicates"]
        self.by_comparison_result: Mapping[str, Mapping[str, str | None]] = document["by_comparison_result"]
        self.fallbacks: tuple[Mapping[str, str], ...] = tuple(document["fallbacks"])
        self.nouns_by_family: dict[str, Noun] = {k: Noun(**v) for k, v in document["nouns"].items()}
        self.lexicon: dict[str, Noun] = {k: Noun(**v) for k, v in document["lexicon"].items()}
        self._agreement = tuple(document["agreement_by_ending"])
        self._classes = tuple(
            (c["kind"], re.compile(c["pattern"]), c["format"], bool(c.get("requires_kind")))
            for c in document["class_formats"]
        )

    def format_class(self, text: str, kind: str | None) -> str | None:
        for ckind, pattern, fmt, requires_kind in self._classes:
            if requires_kind and kind != ckind:
                continue
            if kind and kind != ckind:
                continue
            m = pattern.fullmatch(text.strip())
            if m:
                return _fill_class_format(fmt, m.groups())
        return None

    def agreement(self, noun: str) -> str:
        words = noun.strip().lower().replace("ё", "е").split()
        if not words:
            return "m"
        first, last = words[0].strip("«»\"'"), words[-1].strip("«»\"'")
        for rule in self._agreement:
            if not first.endswith(rule["first"]):
                continue
            allowed_last = rule.get("last")
            if allowed_last and not (len(words) > 1 and any(last.endswith(e) for e in allowed_last)):
                continue
            return str(rule["agr"])
        return "m"

    def noun(self, element: str | None = None, family: str | None = None) -> Noun | None:
        """The noun for an explicit element («Тёплый пол», «тёплый пол») or for a change-map family."""
        if element:
            key = " ".join(element.split()).lower()
            hit = self.lexicon.get(key)
            if hit is not None:
                return hit
            nom = element.strip()
            return Noun(nom=nom[:1].upper() + nom[1:], agr=self.agreement(nom), gen=None)  # type: ignore[arg-type]
        if family:
            return self.nouns_by_family.get(family)
        return None

    def cell(self, value: Any, *, applicable: bool = True) -> str:
        """Приложение 2 sections 4–5 ПД/РД/ИД cell: the value, «—» (stage not applicable), «нет данных» (missing)."""
        if not applicable:
            return self.cells["not_applicable"]
        if value is None or (isinstance(value, str) and not value.strip()):
            return self.cells["missing"]
        return str(value)


@cache
def _load_value_templates_cached(directory: str | None) -> ValueTemplates:
    return ValueTemplates(_read_seed_json("value_templates", directory))


def load_value_templates(directory: str | Path | None = None) -> ValueTemplates:
    return _load_value_templates_cached(str(directory) if directory else None)


def protocol_cell(value: Any, *, applicable: bool = True) -> str:
    return load_value_templates().cell(value, applicable=applicable)


def _fill_value_template(
    template: str, ctx: Mapping[str, Any], noun: Noun | None, vt: ValueTemplates
) -> str | None:
    text = template
    for fb in vt.fallbacks:
        if ctx.get(fb["placeholder"]) in (None, "") and fb["find"] in text:
            text = text.replace(fb["find"], fb["replace"])

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name.startswith("~"):
            forms = vt.predicates[name[1:]]
            return forms[noun.agr if noun else "m"]
        if name == "Element":
            return noun.nom if noun else "\x00"
        if name == "element_gen":
            return noun.gen if noun and noun.gen else (noun.nom.lower() if noun else "\x00")
        val = ctx.get(name)
        return "\x00" if val in (None, "") else str(val)

    out = _TEMPLATE_PLACEHOLDER.sub(repl, text)
    if "\x00" in out:
        return None
    return " ".join(out.split())


def stage_values(
    comparison_result: str | None = None,
    *,
    stages: Sequence[str] = ("PD", "RD"),
    values: Mapping[str, Any] | None = None,
    unit: str | None = None,
    kind: str | None = None,
    family: str | None = None,
    discrepancy_type: str | DiscrepancyType | None = None,
    element: str | None = None,
    pd_sheet: Any = None,
    rd_plan_mark: str | None = None,
    location: str | None = None,
    directory: str | Path | None = None,
) -> dict[str, str | None]:
    """``{"pd_value", "rd_value", "id_value"}`` for one check, in the gold phrasing (93 §3.5, 97 §2.5).

    The change-map route of ``family`` × ``discrepancy_type`` supplies the template when it has one (gold wording,
    e.g. «Иная конфигурация на плане {rd_plan_mark}, помещение {location}»); otherwise the generic template of the
    comparison result with the element noun («{Element} предусмотрен(а/о/ы)»). ``values`` maps PD/RD/ID to raw
    values (formatted by :func:`format_value` with ``unit``/``kind``). A stage outside ``stages`` is ``None``, and so
    is a stage whose template needs a value that is missing.
    """
    vt = load_value_templates(directory)
    route: Route | None = None
    if family and discrepancy_type:
        try:
            route = load_change_map(directory).route(family, str(discrepancy_type))
        except KeyError:
            route = None
    cr = comparison_result or (route.comparison_result if route else None)
    if cr is None and discrepancy_type:
        cr = enum_mappings()["discrepancy_to_comparison_result"].get(str(discrepancy_type))
    if cr is None:
        raise ValueError("stage_values needs a comparison result, or a family and a discrepancy type")
    values = values or {}
    ctx: dict[str, Any] = {
        key: format_value(values.get(stage), unit, kind=kind, directory=directory)
        for stage, key in _STAGE_KEYS.items()
    }
    ctx.update(
        pd_sheet=None if pd_sheet in (None, "") else str(pd_sheet),
        rd_plan_mark=rd_plan_mark,
        location=location,
        element=element,
    )
    noun = vt.noun(element, family)
    wanted = {s.upper() for s in stages}
    route_templates = (route.data.get("value_templates") or {}) if route else {}
    out: dict[str, str | None] = {}
    for stage, key in _STAGE_KEYS.items():
        if stage not in wanted:
            out[key] = None
            continue
        template = route_templates.get(stage.lower()) or vt.by_comparison_result.get(str(cr), {}).get(stage)
        out[key] = _fill_value_template(template, ctx, noun, vt) if template else None
    return out


# ───────────────────────────────────────────── Recommendation templates (Раздел 7) ────────────────────────────────────

PRELIMINARY_PREFIX = "Проект рекомендации (до подтверждения инспектором): "
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_PAREN_GROUP = re.compile(r"(\s?)\(([^()]*)\)")
_OUTSIDE = re.compile(r"(?P<pre>\s+на\s+|:\s+|\s+—\s+|,\s+|\s+|^)\{(?P<name>[a-z_]+)\}")


def _available(values: Mapping[str, Any], name: str) -> bool:
    v = values.get(name)
    return v is not None and str(v).strip() != ""


def render_text(text: str, values: Mapping[str, Any]) -> str:
    """Fill a recommendation-template text (rules R1–R3 of recommendation_templates conventions).

    Inside a parenthesised group, parts are separated by «; »: a part whose placeholder has no value is dropped,
    and an emptied group is dropped with the space before it. A placeholder outside parentheses ({delta},
    {element}, {norm_value}, {norm_ref}) with no value is dropped with its connector («на », «: », « — », «, »,
    a space).
    """

    def fill(part: str) -> str:
        return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]).strip(), part)

    def group(m: re.Match[str]) -> str:
        lead, inner = m.group(1), m.group(2)
        if not _PLACEHOLDER.search(inner):
            return m.group(0)
        kept = [
            fill(part)
            for part in inner.split("; ")
            if all(_available(values, n) for n in _PLACEHOLDER.findall(part))
        ]
        kept = [k for k in kept if k.strip()]
        return f"{lead}({'; '.join(kept)})" if kept else ""

    out = _PAREN_GROUP.sub(group, text)

    def outside(m: re.Match[str]) -> str:
        name = m.group("name")
        if _available(values, name):
            return m.group("pre") + str(values[name]).strip()
        return ""

    out = _OUTSIDE.sub(outside, out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([.,;:)])", r"\1", out)
    out = re.sub(r"\(\s*\)", "", out)
    return out.strip()


def location_display(locations: Sequence[str] | str | None, location_type: str | None = None) -> str | None:
    """{location} of the recommendation texts: «пом. 012», «пом. 140, 142»; other grammar as printed; OBJECT → None."""
    if locations is None:
        return None
    items = [locations] if isinstance(locations, str) else [str(x) for x in locations]
    items = [x.strip() for x in items if x and x.strip() and x.strip() != "OBJECT"]
    if not items:
        return None
    if (location_type or "ROOM").upper() == "ROOM":
        return "пом. " + ", ".join(dict.fromkeys(items))
    return "; ".join(dict.fromkeys(items))


@dataclass(frozen=True, slots=True)
class RenderedRecommendation:
    """Раздел 7 row texts plus the «Отклонение» cell of Разделы 4–5, ready for the protocol contract rows."""

    template_id: str
    parameter_code: str
    protocol_section: Literal["7.1", "7.2"]
    deviation_kind: str | None
    work_type: str  # «{work_type} ({code})» (7.1)
    violation_kind: str  # «{violation text} ({code})» (7.2)
    recommendation: str  # with the preliminary prefix when preliminary
    recommendation_text: str  # without the prefix
    deviation_text: str | None  # «⬇️ Сужение на 0,3 м»
    deviation_direction: str | None  # DeviationDirection: DECREASE | INCREASE | ABSENT | CHANGED
    deviation_magnitude: float | None
    deviation_unit: str | None
    text_origin: str  # TextOrigin of the recommendation
    is_draft: bool
    norm_ref: str | None
    norm_value: str | None
    normative_refs: tuple[str, ...]

    def resolution_row(self, no: int, source_row_no: int | None = None) -> dict[str, Any]:
        """A protocol ResolutionCriticalRow (7.1) or ResolutionSubstantialRow (7.2) body."""
        row: dict[str, Any] = {"no": no}
        if self.protocol_section == "7.1":
            row["work_type"] = self.work_type
        else:
            row["violation_kind"] = self.violation_kind
        row.update(
            recommendation=self.recommendation,
            parameter_code=self.parameter_code,
            is_draft=self.is_draft,
            text_origin=self.text_origin,
            template_id=self.template_id,
            source_row_no=source_row_no,
        )
        return row

    def deviation_cell(self) -> dict[str, Any] | None:
        """The protocol Deviation object of Разделы 4–5 (arrow + verb + magnitude)."""
        if self.deviation_text is None:
            return None
        return {
            "direction": self.deviation_direction,
            "text": self.deviation_text,
            "magnitude": self.deviation_magnitude,
            "unit": self.deviation_unit,
        }


@dataclass(frozen=True, slots=True)
class RecommendationTemplate:
    """One template of recommendation_templates.json (a catalog parameter or a FREE topic)."""

    template_id: str  # catalog code or FREE-<TOPIC>
    code: str | None
    topic: str | None
    short_name: str
    criticality: str
    criticality_level: str
    protocol_section: Literal["7.1", "7.2"]
    protocol_status: str
    data: Mapping[str, Any] = field(repr=False, compare=False)

    @property
    def is_free(self) -> bool:
        return self.topic is not None

    def delta_format(self, kind: str | None) -> str:
        fmt = self.data["delta_format"]
        return str(fmt["by_kind"].get(kind or "", fmt["default"]))


def _date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class RecommendationTemplates:
    """recommendation_templates.json: 132 parameter templates + FREE topics, vocabularies and the renderer."""

    def __init__(self, document: Mapping[str, Any], directory: str | None = None):
        self.document = document
        self._directory = directory
        voc = document["vocabularies"]
        self.deviation_kinds: dict[str, Mapping[str, Any]] = {k["code"]: k for k in voc["deviation_kinds"]}
        self.default_phrases: dict[str, str] = {
            k["code"]: k["default_phrase"] for k in voc["deviation_kinds"] if k.get("default_phrase")
        }
        self.markers: dict[str, str] = dict(voc["markers"])
        self.by_discrepancy: dict[str, str] = dict(voc["discrepancy_to_deviation_kind"])
        self.by_comparison_result: dict[str, str] = dict(voc["comparison_result_to_deviation_kind"])
        self.by_violation_type: dict[str, str] = dict(voc["violation_type_to_deviation_kind"])
        self.templates: dict[str, RecommendationTemplate] = {}
        for t in document["templates"]:
            self.templates[t["code"]] = RecommendationTemplate(
                template_id=t["template_id"],
                code=t["code"],
                topic=None,
                short_name=t["short_name"],
                criticality=t["criticality"],
                criticality_level=t["criticality_level"],
                protocol_section=t["protocol_section"],
                protocol_status=t["protocol_status"],
                data=MappingProxyType(dict(t)),
            )
        self.free: dict[str, RecommendationTemplate] = {}
        for t in document["free_topics"]:
            self.free[t["topic"]] = RecommendationTemplate(
                template_id=t["template_id"],
                code=None,
                topic=t["topic"],
                short_name=t["short_name"],
                criticality=t["criticality"],
                criticality_level=t["criticality_level"],
                protocol_section=t["protocol_section"],
                protocol_status=t["protocol_status"],
                data=MappingProxyType(dict(t)),
            )
        self.documents: tuple[Mapping[str, Any], ...] = tuple(document["documents"])

    def __len__(self) -> int:
        return len(self.templates)

    def get(self, code: str | int) -> RecommendationTemplate:
        """By catalog code, any alias, the id, «FREE-<TOPIC>» or «FREE-<TOPIC>-<NNN>»."""
        if isinstance(code, str) and code.strip().upper().startswith("FREE-"):
            parts = code.strip().upper().split("-")
            topic = parts[1] if len(parts) >= 2 else ""
            if topic not in self.free:
                raise KeyError(f"unknown FREE topic in {code!r}")
            return self.free[topic]
        return self.templates[load_params(self._directory).get(code).code]

    # — deviation kind ——————————————————————————————————————————————————————————————————————————————————————————

    def deviation_kind(
        self,
        *,
        discrepancy_type: str | None = None,
        comparison_result: str | None = None,
        violation_type: str | None = None,
        expected: Any = None,
        actual: Any = None,
    ) -> str | None:
        """DeviationKind for a discrepancy (DiscrepancyType first, then ViolationType, then ComparisonResult).

        BY_SIGN kinds resolve by the numbers (actual below expected → DECREASE, above → INCREASE), else DECREASE.
        """
        kind = None
        for key, table in (
            (discrepancy_type, self.by_discrepancy),
            (violation_type, self.by_violation_type),
            (comparison_result, self.by_comparison_result),
        ):
            if key and str(key) in table:
                kind = table[str(key)]
                break
        if kind == "BY_SIGN":
            try:
                kind = "INCREASE" if _to_decimal(actual) > _to_decimal(expected) else "DECREASE"
            except (TypeError, ValueError):
                kind = "DECREASE"
        return kind

    # — editions ————————————————————————————————————————————————————————————————————————————————————————————————

    def edition_rule(
        self, template: RecommendationTemplate, pd_approved_on: date | str | None
    ) -> Mapping[str, Any] | None:
        """The template's edition rule for a PD approved on ``pd_approved_on`` (the earliest applicable one)."""
        when = _date(pd_approved_on)
        if when is None:
            return None
        rules = sorted(template.data.get("edition_rules", ()), key=lambda r: r["pd_approved_before"])
        for rule in rules:
            if when < date.fromisoformat(rule["pd_approved_before"]):
                return rule
        return None

    def apply_editions(self, text: str, *, pd_approved_on: date | str | None) -> str:
        """Rewrite inline citations of design norms replaced after the PD approval date (norms.yaml registry).

        «(СП 59.13330.2020, пп. 6.1.5, 6.2.4)» becomes «(СП 59.13330.2016)» for a PD approved before 01.07.2021:
        the clause list is dropped because numbering differs between editions.
        """
        when = _date(pd_approved_on)
        if when is None:
            return text
        for doc in sorted(self.documents, key=lambda d: d.get("effective_from") or "", reverse=True):
            new = doc.get("replaced_by")
            if not new or not doc.get("inline_replace") or doc.get("applies_by") != "PD_APPROVAL_DATE":
                continue
            if when >= date.fromisoformat(doc["effective_from"]):
                continue
            pattern = re.escape(new) + _CLAUSE_TAIL
            text = re.sub(pattern, doc["designation"], text)
        return text

    # — rendering ——————————————————————————————————————————————————————————————————————————————————————————————

    def render(
        self,
        code: str | int,
        *,
        deviation_kind: str | None = None,
        discrepancy_type: str | None = None,
        comparison_result: str | None = None,
        violation_type: str | None = None,
        display_code: str | None = None,
        pd_value: Any = None,
        rd_value: Any = None,
        id_value: Any = None,
        expected: Any = None,
        actual: Any = None,
        unit: str | None = None,
        delta: str | None = None,
        location: str | None = None,
        element: str | None = None,
        element_key: str | None = None,
        norm_value: str | None = None,
        norm_ref: str | None = None,
        pd_approved_on: date | str | None = None,
        preliminary: bool = True,
    ) -> RenderedRecommendation:
        """Fill the Раздел 7 texts and the «Отклонение» cell for one finding (group).

        ``pd_value``/``rd_value``/``id_value`` are display values (see :func:`format_value`); ``expected``/``actual``
        are the numbers for {delta} (ПД and the deviating stage) when ``delta`` is not given. ``location`` is the
        display form («пом. 140, 142», :func:`location_display`). ``display_code`` is the code printed in «(…)»
        (default: the catalog code; for FREE, the numbered code, e.g. «FREE-HEATING-001»). Norm values/references
        come from the arguments, else the template's edition rule for ``pd_approved_on``, else ``norm_fill``;
        inline citations of norms replaced after ``pd_approved_on`` are rewritten to the previous edition.
        """
        tpl = self.get(code)
        d = tpl.data
        if deviation_kind is None:
            deviation_kind = self.deviation_kind(
                discrepancy_type=discrepancy_type,
                comparison_result=comparison_result,
                violation_type=violation_type,
                expected=expected,
                actual=actual,
            )
        shown = display_code or (tpl.code if tpl.code else f"FREE-{tpl.topic}-001")
        # {actual_value}: the deviating value — ИД when present and different from ПД/РД, else РД.
        actual_value = (
            id_value if id_value not in (None, "") and id_value not in (pd_value, rd_value) else rd_value
        )
        if actual_value in (None, "") and id_value not in (None, ""):
            actual_value = id_value
        # {delta}
        fmt = tpl.delta_format(deviation_kind)
        count_noun = d.get("count_noun")
        magnitude: tuple[str, float, str | None] | None = None
        if delta is None and fmt != "NONE":
            magnitude = format_delta(fmt, expected, actual, unit=unit, count_noun=count_noun)
            delta = magnitude[0] if magnitude else None
        delta_acc = delta
        count_form: str | None = None
        if fmt == "COUNT" and count_noun and magnitude is not None:
            n = int(magnitude[1])
            count_form = _plural_key(n)
            if count_form == "one" and count_noun.get("one_acc"):
                delta_acc = f"{n} {count_noun['one_acc']}"
        # norms
        rule = self.edition_rule(tpl, pd_approved_on)
        fill = d.get("norm_fill") or {}
        nv = norm_value or (rule or {}).get("norm_value") or fill.get("norm_value")
        nr = norm_ref or (rule or {}).get("norm_ref") or fill.get("norm_ref")
        # element presets (FREE): a known element noun selects its own texts
        preset = None
        if element and d.get("element_presets"):
            key = " ".join(element.split()).lower()
            preset = next((p for n, p in d["element_presets"].items() if n.lower() == key), None)
        values = {
            "pd_value": pd_value,
            "rd_value": rd_value,
            "id_value": id_value,
            "actual_value": actual_value,
            "delta": delta,
            "delta_acc": delta_acc,
            "location": location,
            "norm_value": nv,
            "norm_ref": nr,
            "element": (element[:1].lower() + element[1:]) if element else None,
        }

        def grammar(text: str) -> str:
            # R6: «Отсутствуют 1 узел» → «Отсутствует 1 узел»; R7: «на 1 квартиру» (accusative after «на»).
            if count_form == "one":
                text = text.replace("Отсутствуют {delta}", "Отсутствует {delta}")
            if delta_acc != delta:
                text = text.replace("на {delta}", "на {delta_acc}")
            return text

        def render(text: str | None) -> str | None:
            if text is None:
                return None
            return self.apply_editions(render_text(grammar(text), values), pd_approved_on=pd_approved_on)

        # «Вид нарушения» (7.2): element variant «KIND:элемент», kind variant, preset, default
        variants = d.get("violation_kind_variants") or {}
        vk_text = None
        if preset:
            vk_text = preset.get("violation_kind")
        if vk_text is None and deviation_kind and element_key:
            vk_text = variants.get(f"{deviation_kind}:{element_key}")
        if vk_text is None and deviation_kind:
            vk_text = variants.get(deviation_kind)
        if vk_text is None:
            vk_text = d["violation_kind"]
        rec_text = (
            (preset or {}).get("recommendation")
            or (d.get("recommendation_variants") or {}).get(deviation_kind or "")
            or d["recommendation"]
        )
        recommendation_text = render(rec_text) or ""
        phrase = None
        if deviation_kind:
            phrase = (d.get("deviation_phrases") or {}).get(deviation_kind) or self.default_phrases.get(
                deviation_kind
            )
        deviation_text = render(phrase)
        direction = None
        if deviation_text:
            direction = next(
                (code for mark, code in self.markers.items() if deviation_text.startswith(mark)), None
            )
        origin = d["text_origin"]["recommendation"]
        return RenderedRecommendation(
            template_id=tpl.template_id,
            parameter_code=shown,
            protocol_section=tpl.protocol_section,
            deviation_kind=deviation_kind,
            work_type=f"{d['work_type']} ({shown})",
            violation_kind=f"{render(vk_text)} ({shown})",
            recommendation=(PRELIMINARY_PREFIX + recommendation_text) if preliminary else recommendation_text,
            recommendation_text=recommendation_text,
            deviation_text=deviation_text,
            deviation_direction=direction,
            deviation_magnitude=magnitude[1] if magnitude else None,
            deviation_unit=magnitude[2] if magnitude else None,
            text_origin=origin,
            is_draft=True,
            norm_ref=nr,
            norm_value=nv,
            normative_refs=tuple(
                dict.fromkeys(
                    self.apply_editions(r["ref"], pd_approved_on=pd_approved_on)
                    for r in d.get("norm_refs", ())
                )
            ),
        )


_CLAUSE_NO = (
    r"[\dА-ЯA-Z](?:\w|\.(?=\w))*"  # «6.3.3», «А.1.1», «6.1»; a sentence-final period is not part of it
)
_CLAUSE_LIST = (
    rf"(?:пп?\.|табл\.|разд\.|прил\.|приложение|раздел|гл\.)\s*{_CLAUSE_NO}"
    rf"(?:(?:,\s+|\s*[–-]\s*|\s+и\s+)(?:(?:пп?\.|табл\.|разд\.|прил\.)\s*)?{_CLAUSE_NO})*"
)
# The clause references that follow a designation: «, пп. 6.1.5, 6.2.4», «, табл. 6.1» or « (пп. 5.1.14, 6.2.13)».
_CLAUSE_TAIL = rf"(?:(?:,?\s*{_CLAUSE_LIST})+|\s*\({_CLAUSE_LIST}\))?"


@cache
def _load_recommendation_templates_cached(directory: str | None) -> RecommendationTemplates:
    return RecommendationTemplates(_read_seed_json("recommendation_templates", directory), directory)


def load_recommendation_templates(directory: str | Path | None = None) -> RecommendationTemplates:
    return _load_recommendation_templates_cached(str(directory) if directory else None)


def render_recommendation(code: str | int, **kwargs: Any) -> RenderedRecommendation:
    """Shortcut for ``load_recommendation_templates().render(code, **kwargs)``."""
    return load_recommendation_templates().render(code, **kwargs)


def norm_edition(designation: str, *, on: date | str | None, applies_by: str = "PD_APPROVAL_DATE") -> str:
    """The designation in force on ``on`` for a document of the edition registry (90 C-50)."""
    when = _date(on)
    if when is None:
        return designation
    docs = load_recommendation_templates().documents
    current = designation
    changed = True
    while changed:  # walk back through successive replacements (ГОСТ Р 51261-2025 → -2022 → -2017)
        changed = False
        for doc in docs:
            if doc.get("replaced_by") == current and when < date.fromisoformat(doc["effective_from"]):
                current, changed = doc["designation"], True
                break
    return current


# ─────────────────────────────────────── Numbers in normative texts (verification) ──────────────────────────────────

_REF_TOKENS = re.compile(
    r"""
      (?:СП|СНиП|ГОСТ(?:\s?Р)?|СанПиН|ТР\s?ТС|ПУЭ|ВСН|МДС|EN|ISO|РД)\s*\d[\d.\/:]*(?:-\d+)?(?:\.\d+)?   # designations
    | №\s*\d[\d\/]*(?:-?[А-Яа-яA-Za-z]+)?                    # document and amendment numbers
    | \d+-ФЗ
    | \d{2}\.\d{2}\.\d{4}                                     # dates
    | (?:пп?|табл|разд|прил|ст|ч|гл|подп|абз|поз|рис)\.\s*[\dА-ЯA-Z][\w.()]*
      (?:(?:,\s+|\s*[–-]\s*|\s+и\s+)(?=[\dА-ЯA-Z])[\dА-ЯA-Z][\w.()]*)*   # clause lists
    | \b[А-ЯA-Z]{1,3}\d(?:/[А-ЯA-Z]{1,3}\d)*\b                          # system tags В1/Т3, К1/К2, КМ2
    | \b[А-ЯA-Z]{1,3}-\d+\b                                              # КС-2
    | \b\d+-(?:го|й|м|х|я|е)\b                                          # ordinals «1-го типа»
    | \{[a-z_]+\}                                                       # placeholders
    """,
    re.X,
)
_BARE_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?")


def _norm_num(text: str) -> str:
    return text.replace(".", ",")


def unverified_numbers(text: str, corpus: str) -> list[str]:
    """Numbers of ``text`` that are not normative designations/clauses and do not occur in ``corpus``.

    Used to enforce the template policy «every number in a recommendation comes from a verified (HIGH) norm
    record» (build_seed.py and the tests). Designations, document numbers, dates, clause lists, system tags,
    ordinals and placeholders are not quantities and are skipped.
    """
    stripped = _REF_TOKENS.sub(" ", text)
    haystack = re.sub(r"(\d)\.(\d)", r"\1,\2", corpus)
    missing = []
    for m in _BARE_NUMBER.finditer(stripped):
        num = _norm_num(m.group(0))
        if not re.search(r"(?<![\d,])" + re.escape(num) + r"(?![\d])", haystack):
            missing.append(m.group(0))
    return missing


def verified_corpus(
    codes: Iterable[str], *, min_confidence: str = "HIGH", directory: str | Path | None = None
) -> str:
    """Text of the verified references (value, condition, quote, clause, edition, designation) of ``codes``.

    Only references at ``min_confidence`` or above and not NOT_FOUND count; the verified threshold condition is
    included unless it is a customer threshold or has no basis.
    """
    reg = load_params(directory)
    floor = CONF_ORDER[min_confidence]
    parts: list[str] = []
    for code in codes:
        spec = reg.get(code)
        for refs in spec["references"].values():
            for r in refs:
                if CONF_ORDER[r["confidence"]] < floor or r.get("status") == "NOT_FOUND":
                    continue
                parts.extend(
                    str(r[k])
                    for k in ("ref", "designation", "clause", "edition", "condition", "value", "quote")
                    if r.get(k)
                )
        thr = spec["norm_verification"]["threshold"]
        if thr["status"] not in ("CUSTOMER_THRESHOLD", "NO_BASIS_FOUND") and thr.get("condition"):
            parts.append(thr["condition"])
    return "\n".join(parts)


CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


# ─────────────────────────────────────────────── Consistency checks and CLI ──────────────────────────────────────────


def seed_consistency_problems(directory: str | Path | None = None) -> list[str]:
    """Cross-file checks the JSON Schemas cannot express (the full list is in seed/README.md)."""
    problems: list[str] = []
    reg = load_params(directory)
    if len(reg) != 132 or sorted(reg.by_id) != list(range(1, 133)):
        problems.append(f"expected parameters 1..132, got {len(reg)}")
    enums = load_enums()
    crit_strings = {
        v.attrs.get("catalog_string"): v.code
        for v in enums["CriticalityLevel"].values
        if v.attrs.get("catalog_string")
    }
    for p in reg:
        if p.code != _codes.canonical_code(p.param_id):
            problems.append(f"{p.code}: code does not match id {p.param_id}")
        if list(p.alias_codes) != _codes.alias_codes(p.param_id):
            problems.append(
                f"{p.code}: alias_codes {p.alias_codes} != contracts {_codes.alias_codes(p.param_id)}"
            )
        if crit_strings.get(p.criticality) != p.criticality_level.value:
            problems.append(f"{p.code}: criticality string and level disagree")
        if len(p.regex_pattern) > MAX_REGEX_PATTERN_CHARS:
            problems.append(f"{p.code}: regex_pattern longer than {MAX_REGEX_PATTERN_CHARS}")
        for gate in p.regex_gates:
            if gate not in reg.gates:
                problems.append(f"{p.code}: unknown gate {gate}")
        for other in (*p.linked_params, *p.hedge_group):
            if other not in reg.by_code:
                problems.append(f"{p.code}: unknown linked/hedge code {other}")
        if p.hedge_group and p.code not in p.hedge_group:
            problems.append(f"{p.code}: hedge_group does not contain the parameter itself")
        for i, src in enumerate((p.regex_pattern, *p.regex_aux)):
            issues = regex_safety_problems(src)
            if issues:
                problems.append(f"{p.code}#{i}: unsafe regex: {'; '.join(issues)}")
    for pair in load_codes().get("hedge_pairs", ()):
        if not any(set(pair) <= set(group) for group in reg.hedge_groups):
            problems.append(f"codes.yaml hedge pair {pair} is not covered by the seed hedge groups")
    topics = load_free_topics(directory)
    if sorted(topics) != sorted(enums["FreeTopic"].codes):
        problems.append("free_topics.json topics differ from enums.FreeTopic")
    cmap = load_change_map(directory)
    for route in cmap.routes():
        code = route.parameter_code
        if code is None:
            if route.emit:
                problems.append(f"route {route.family}: emit=true without a parameter code")
            continue
        if code.startswith("FREE-"):
            if code.removeprefix("FREE-") not in topics:
                problems.append(f"route {route.family}: unknown FREE topic in {code}")
            if route.parameter_mapping_status is not ParameterMappingStatus.MATRIX_GAP_CONFIRMED:
                problems.append(f"route {route.family}: FREE route must be MATRIX_GAP_CONFIRMED")
        elif code not in reg.by_code:
            problems.append(f"route {route.family}: unknown parameter code {code}")
        elif route.parameter_mapping_status is ParameterMappingStatus.MATRIX_GAP_CONFIRMED:
            problems.append(f"route {route.family}: matrix route marked MATRIX_GAP_CONFIRMED")
        for h in route.hedge_codes:
            if h not in reg.by_code:
                problems.append(f"route {route.family}: unknown hedge code {h}")
        for dt in route.discrepancy_types:
            if dt not in DiscrepancyType.__members__:
                problems.append(f"route {route.family}: unknown discrepancy type {dt}")
        expected = enum_mappings()["discrepancy_to_comparison_result"]
        if route.comparison_result and any(
            expected.get(dt) != route.comparison_result for dt in route.discrepancy_types
        ):
            problems.append(
                f"route {route.family}: comparison_result disagrees with the DiscrepancyType mapping"
            )
    problems += _template_consistency_problems(reg, cmap, directory)
    return problems


def _template_consistency_problems(
    reg: ParamRegistry, cmap: ChangeMap, directory: str | Path | None
) -> list[str]:
    """recommendation_templates.json and value_templates.json against params.json and the change map."""
    problems: list[str] = []
    tpl = load_recommendation_templates(directory)
    if list(tpl.templates) != [p.code for p in reg]:
        problems.append("recommendation_templates: codes differ from the 132 catalog codes")
    for p in reg:
        t = tpl.templates.get(p.code)
        if t is None:
            continue
        if t.short_name != p.short_name or t.criticality != p.criticality:
            problems.append(f"{p.code}: template short_name/criticality differ from params.json")
        if t.data["work_type"] != p["work_type"] or t.data["recommendation"] != p["recommendation_template"]:
            problems.append(f"{p.code}: params.json texts are not the template texts")
    for code in (
        *tpl.by_discrepancy.values(),
        *tpl.by_comparison_result.values(),
        *tpl.by_violation_type.values(),
    ):
        if code != "BY_SIGN" and code not in tpl.deviation_kinds:
            problems.append(f"recommendation_templates: unknown deviation kind {code}")
    if sorted(tpl.free) != sorted(load_enums()["FreeTopic"].codes):
        problems.append("recommendation_templates: FREE topics differ from enums.FreeTopic")
    vt = load_value_templates(directory)
    if set(vt.nouns_by_family) != set(cmap.families):
        problems.append("value_templates: nouns do not cover the change-map families exactly")
    return problems


def clear_caches() -> None:
    for fn in (
        _read_seed_json,
        _seed_validator,
        _load_params_cached,
        _load_change_map_cached,
        _load_free_topics_cached,
        _load_value_templates_cached,
        _load_recommendation_templates_cached,
    ):
        fn.cache_clear()
    regex_safety_problems.cache_clear()


def _cmd_check(_: argparse.Namespace) -> int:
    failed = False
    for name in SEED_FILES:
        errors = seed_validation_errors(name)
        print(f"schema {name}: {'OK' if not errors else f'{len(errors)} ошибок'}")
        for err in errors[:20]:
            print(f"  {err}")
        failed |= bool(errors)
    problems = seed_consistency_problems()
    print(f"consistency: {'OK' if not problems else f'{len(problems)} проблем'}")
    for p in problems[:40]:
        print(f"  {p}")
    reg = load_params()
    crit = sum(p.criticality_level is CriticalityLevel.CRITICAL_SUSPEND for p in reg)
    n_regex = sum(1 + len(p.regex_aux) for p in reg)
    print(
        f"params: {len(reg)} (критических {crit}, существенных {len(reg) - crit}); regex: {n_regex}; "
        f"gates: {len(reg.gates)}; hedge groups: {len(reg.hedge_groups)}; matrix_version {reg.matrix_version}; "
        f"content_sha256 {reg.content_sha256[:12]}"
    )
    ovr = reg.overrides
    print(
        f"overrides: {'applied' if ovr['applied'] else 'none'} ({ovr['reason']}); rows {ovr['count']}, "
        f"changed {ovr['changed_count']}"
    )
    tpl = load_recommendation_templates()
    refs = sum(len(b) for p in reg for b in p["references"].values())
    print(
        f"templates: {len(tpl)} + FREE {len(tpl.free)}; references: {refs} (verified {reg.get(1)['norm_verification']['checked_at']}); "
        f"edition registry: {len(tpl.documents)}; value-template nouns: {len(load_value_templates().lexicon)}"
    )
    return 1 if failed or problems else 0


def _cmd_show(args: argparse.Namespace) -> int:
    spec = get_param(args.code)
    print(json.dumps(dict(spec.data), ensure_ascii=False, indent=2))
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    res = resolve_code(args.code, args.name, strict=args.strict)
    print(
        json.dumps(
            {"code": res.code, "param_id": res.param_id, "method": res.method, "warnings": res.warnings},
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    r = render_recommendation(
        args.code,
        deviation_kind=args.kind,
        discrepancy_type=args.discrepancy,
        pd_value=args.pd,
        rd_value=args.rd,
        id_value=args.id,
        expected=args.expected,
        actual=args.actual,
        unit=args.unit,
        location=args.location,
        element=args.element,
        display_code=args.display_code,
        pd_approved_on=args.pd_approved,
        preliminary=not args.final,
    )
    out = {
        "section": r.protocol_section,
        "work_type": r.work_type,
        "violation_kind": r.violation_kind,
        "recommendation": r.recommendation,
        "deviation": r.deviation_cell(),
        "text_origin": r.text_origin,
        "norm_ref": r.norm_ref,
        "normative_refs": list(r.normative_refs),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    """Expert review checklist (97 Q3, U-18): demo-priority templates with their verified references."""
    reg = load_params()
    tpl = load_recommendation_templates()
    codes = [p.code for p in reg if p["demo_priority"] <= args.priority or p.code in args.extra]
    lines = [
        f"Проверка шаблонов резолютивной части: {len(codes)} параметров (demo_priority ≤ {args.priority})",
        "",
    ]
    for code in codes:
        spec, t = reg.get(code), tpl.get(code).data
        lines.append(f"■ {spec.display} — {spec.criticality}; Раздел {t['protocol_section']}")
        lines.append(f"  Вид работ: {t['work_type']}")
        lines.append(f"  Вид нарушения: {t['violation_kind']}")
        lines.append(f"  Рекомендация: {t['recommendation']}")
        for kind, phrase in t["deviation_phrases"].items():
            lines.append(f"  Отклонение [{kind}]: {phrase}")
        for ref in t["norm_refs"]:
            clause = f", {ref['clause']}" if ref.get("clause") else ""
            lines.append(f"  Норма: {ref['designation']}{clause} — {ref['status']}, {ref['confidence']}")
        lines.append("  Решение эксперта: [ ] принять  [ ] исправить: ____________________")
        lines.append("")
    print("\n".join(lines))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m inspector_common.params", description="Матрица 132 параметров: сид и проверки"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="проверить сид (схемы, согласованность, безопасность regex)").set_defaults(
        func=_cmd_check
    )
    show = sub.add_parser("show", help="показать параметр по любому коду")
    show.add_argument("code")
    show.set_defaults(func=_cmd_show)
    res = sub.add_parser("resolve", help="распознать код параметра (с наименованием — для кодов с ошибкой)")
    res.add_argument("code")
    res.add_argument("--name")
    res.add_argument("--strict", action="store_true")
    res.set_defaults(func=_cmd_resolve)
    ren = sub.add_parser("render", help="тексты Раздела 7 и «Отклонение» для находки (шаблоны рекомендаций)")
    ren.add_argument("code", help="код параметра (любой стиль) или FREE-<TOPIC>[-NNN]")
    ren.add_argument("--kind", help="DeviationKind (DECREASE, ABSENCE, …)")
    ren.add_argument("--discrepancy", help="DiscrepancyType (VALUE_DECREASED, ELEMENT_MISSING, …)")
    for opt in ("--pd", "--rd", "--id", "--expected", "--actual", "--unit", "--location", "--element"):
        ren.add_argument(opt)
    ren.add_argument("--display-code", help="код в «(…)», например FREE-HEATING-001")
    ren.add_argument("--pd-approved", help="дата утверждения ПД (ГГГГ-ММ-ДД) для выбора редакции нормы")
    ren.add_argument("--final", action="store_true", help="без префикса «Проект рекомендации …»")
    ren.set_defaults(func=_cmd_render)
    rev = sub.add_parser("review", help="чек-лист экспертной проверки шаблонов (97 Q3)")
    rev.add_argument("--priority", type=int, default=2, help="demo_priority не выше (1–3), по умолчанию 2")
    rev.add_argument("--extra", nargs="*", default=["IOS4-077"], help="дополнительные коды")
    rev.set_defaults(func=_cmd_review)
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ParameterCodeError, SeedError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
