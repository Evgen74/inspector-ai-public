"""Seed regexes: examples, static ReDoS safety, guarded execution (windows + time budget) and timing fuzz.

Owner: AG-03. The fuzz below runs every pattern on adversarial inputs (long runs of spaces, digits, letters,
CAD-like lines, anchor words pumped with fillers). `make test` runs it at 10 000 characters; the `slow` variant
runs 60 000 characters (several windows) with more pumps.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from inspector_common import params

# The original matrix_enriched.json M-044 pattern (roof layers): catastrophic on long CAD lines (97 §2.14).
ORIGINAL_M044 = r"(?i)(?P<layer>[А-ЯЁа-яё][А-ЯЁа-яё\s\-]{3,60}?)\s*[-–,]?\s*(?:t|h|δ|толщ\w*)?\s*=?\s*(?P<v>\d{1,4})\s*(?:мм)?$"
ORIGINAL_M109 = r"(?i)(?P<mark>[\wА-Яа-я]+нг\(?[АA]?\)?[\-‐](?P<idx>FRLSLTx|FRLS|FRHF|LSLTx|LS|HF|LTx))"


@pytest.fixture(scope="module")
def reg() -> params.ParamRegistry:
    return params.load_params()


def _all_patterns(reg: params.ParamRegistry) -> list[tuple[str, int, str]]:
    return [(p.code, i, src) for p in reg for i, src in enumerate((p.regex_pattern, *p.regex_aux))]


def _matches_example(hits: list[params.RegexHit], ex: dict) -> bool:
    for h in hits:
        if "value" in ex and h.value != ex["value"]:
            continue
        if any(h.groups.get(k) != v for k, v in ex.get("groups", {}).items()):
            continue
        return True
    return False


def test_every_parameter_has_examples(reg: params.ParamRegistry) -> None:
    for p in reg:
        ex = p["regex_examples"]
        assert ex["positive"] and ex["negative"], p.code


def test_positive_examples_match(reg: params.ParamRegistry) -> None:
    failures = []
    for p in reg:
        for ex in p["regex_examples"]["positive"]:
            hits = reg.extract(
                p.code, params.normalize_regex_input(ex["text"]), discipline=ex.get("discipline")
            )
            if not _matches_example(hits, ex):
                failures.append((p.code, ex["text"], [dict(h.groups) for h in hits]))
    assert failures == []


def test_negative_examples_do_not_match(reg: params.ParamRegistry) -> None:
    failures = []
    for p in reg:
        for ex in p["regex_examples"]["negative"]:
            hits = reg.extract(
                p.code, params.normalize_regex_input(ex["text"]), discipline=ex.get("discipline")
            )
            if hits:
                failures.append((p.code, ex["text"], [h.text for h in hits]))
    assert failures == []


def test_patterns_compile_are_safe_and_fit_the_tz_column(reg: params.ParamRegistry) -> None:
    for code, i, src in _all_patterns(reg):
        re.compile(src)
        assert params.regex_safety_problems(src) == (), (code, i)
        limit = params.MAX_REGEX_PATTERN_CHARS if i == 0 else params.MAX_AUX_PATTERN_CHARS
        assert len(src) <= limit, (code, i, len(src))
    for gate in reg.document["context_gates"]:
        for src in (*gate.get("require_any", ()), *gate.get("reject_any", ())):
            assert params.regex_safety_problems(src) == (), gate["id"]


@pytest.mark.parametrize(
    "pattern",
    [
        ORIGINAL_M044,
        ORIGINAL_M109,
        r"(a+)+$",
        r"(\w+\s?)*$",
        r"\s*,?\s*x",
        r"(?:\d|\d\d)+$",
        r"(a|aa)*b",
        r"(x)\1",
    ],
)
def test_static_analysis_rejects_known_redos_shapes(pattern: str) -> None:
    assert params.regex_safety_problems(pattern)
    with pytest.raises(params.UnsafeRegexError):
        params.compile_guarded(pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        r"(?<![\d.,])\d+(?: \d{3})*(?:[.,]\d+)?",
        r"(?<!\d)\d{1,3}",
        r"(?:[ \t][А-Я]+)*",
        r"(?m)^[ \t]*\S",
        r"этаж[а-яё]*+\s+\d",
        r"[а-яё]*+[^\n]{0,60}?\d",
        r"\d{1,3}(?:\s?\d{3})*+\s*м",
    ],
)
def test_static_analysis_accepts_linear_shapes(pattern: str) -> None:
    assert params.regex_safety_problems(pattern) == ()


def test_hard_time_limit_interrupts_a_runaway_match() -> None:
    gp = params.compile_guarded(ORIGINAL_M044, check=False, time_budget_s=0.2, label="M-044-original")
    cad_line = ("Утеплитель" + " " * 120 + "Пароизоляция" + " " * 120) * 40
    t0 = time.perf_counter()
    with pytest.raises(params.RegexTimeout):
        gp.findall_matches(cad_line)
    assert time.perf_counter() - t0 < 2.0


def test_hardened_ar044_is_fast_on_the_same_line(reg: params.ParamRegistry) -> None:
    cad_line = ("Утеплитель" + " " * 120 + "Пароизоляция" + " " * 120) * 40
    t0 = time.perf_counter()
    assert reg.extract("AR-044", cad_line) == []
    assert time.perf_counter() - t0 < 0.1


def test_windowing_equals_plain_search() -> None:
    lines = [
        f"Площадь застройки — {i * 7 % 1000},5 м²" if i % 3 == 0 else "текст " * (i % 9) for i in range(400)
    ]
    text = "\n".join(lines)
    pattern = r"(?i)площадь\s+застройки[^\d\n]{0,60}?(?P<v>\d+(?:[.,]\d+)?)\s*м²"
    plain = [(m.start(), m.end(), m.group("v")) for m in re.finditer(pattern, text)]
    gp = params.compile_guarded(pattern, max_window_chars=300)
    windowed = [(m.start(), m.end(), m.group("v")) for m in gp.finditer(text)]
    assert windowed == plain and len(plain) > 100


def test_windowing_long_line_without_breaks() -> None:
    chunk = "ааа EI 60 ббб " * 3000  # one line, ~42k chars: artificial window cuts
    gp = params.compile_guarded(r"(?<![A-Za-z])EI\s?(?P<v>\d{2,3})", max_window_chars=1000)
    windowed = [(m.start(), m.end()) for m in gp.finditer(chunk)]
    plain = [(m.start(), m.end()) for m in re.finditer(r"(?<![A-Za-z])EI\s?(?P<v>\d{2,3})", chunk)]
    assert windowed == plain


def test_normalize_regex_input() -> None:
    raw = "Площадь застройки 12,5 м2; объём 3 м3; ‑5 мм"
    out = params.normalize_regex_input(raw)
    assert out == "Площадь застройки 12,5 м²; объём 3 м³; -5 мм"
    assert params.normalize_regex_input("М2-1 помещение") == "М2-1 помещение"  # not a unit


def _adversarial_inputs(n: int, spec: params.ParamSpec) -> dict[str, str]:
    rnd = random.Random(7)
    cyr = "абвгдежзийклмнопрстуфхцчшщыьэюя"
    base = {
        "spaces": " " * n,
        "digits": "7" * n,
        "digits_spaced": ("1 234 " * (n // 6 + 1))[:n],
        "cyr_word": "а" * n,
        "cyr_words": " ".join(
            "".join(rnd.choice(cyr) for _ in range(rnd.randint(2, 9))) for _ in range(n // 5)
        )[:n],
        "cad_wide": (("Утеплитель" + " " * 120 + "Пароизоляция" + " " * 120) * (n // 244 + 1))[:n],
        "latin_word": "x" * n,
        "mixed": (
            "Бетон В25 F150 W6 плита 250 мм; система В20 L=1200 м³/ч, Ø200 400х200 КМ1 EI 60 " * (n // 80 + 1)
        )[:n],
        "newlines": ("В1\n" * (n // 3 + 1))[:n],
    }
    t = spec["regex_examples"]["positive"][0]["text"]
    head = t[: max(1, len(t) // 2)]
    for name, filler in (("pump_spaces", " "), ("pump_digits", "9"), ("pump_letters", "а")):
        unit = head + filler * 200
        base[name] = (unit * (n // len(unit) + 1))[:n]
    base["pos_repeated"] = ((t + " ") * (n // (len(t) + 1) + 1))[:n]
    return base


def _fuzz(reg: params.ParamRegistry, n: int, budget_s: float) -> list[tuple[float, str, int, str]]:
    worst: list[tuple[float, str, int, str]] = []
    for p in reg:
        inputs = _adversarial_inputs(n, p)
        for i, gp in enumerate(reg.patterns(p.code)):
            guarded = params.GuardedPattern(gp.pattern, label=gp.label, time_budget_s=2.0)
            for name, text in inputs.items():
                t0 = time.perf_counter()
                guarded.findall_matches(text)  # RegexTimeout fails the test
                worst.append((time.perf_counter() - t0, p.code, i, name))
    worst.sort(reverse=True)
    slow = [w for w in worst if w[0] > budget_s]
    assert slow == [], slow[:5]
    return worst


def test_fuzz_timing_all_patterns(reg: params.ParamRegistry) -> None:
    worst = _fuzz(reg, 10_000, budget_s=0.15)
    assert len(worst) >= 145 * 13


@pytest.mark.slow
def test_fuzz_timing_all_patterns_multi_window(reg: params.ParamRegistry) -> None:
    worst = _fuzz(reg, 60_000, budget_s=0.5)
    assert len(worst) >= 145 * 13
