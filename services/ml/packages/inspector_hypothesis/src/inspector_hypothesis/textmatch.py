"""Text normalisation and matching shared by the hypothesis detectors.

- :func:`norm_word` / :func:`norm_text`: lowercase, «ё» → «е», quotes and edge punctuation stripped, NFKC.
- :class:`PhraseMatcher`: element-family anchors from the seed (``change_matrix_map.json``) matched on word
  sequences with a light Russian stemmer (inflected forms «теплые полы», «теплого пола»), exact matching for
  short words, codes and Latin brand names («ИТП», «Multibox»), and dotted abbreviations («отопл.»).
- Room lists in PD text («(пом. 267, 270, 271, 272)», «помещения № 101–105») with the exact printed tokens
  («012» stays «012», 93 §2.7).
- Russian numbers («2797,27», «1 079,9») and their display format («2797,27 м²»).
- Document-code keys («АНО/150321/1-РД-ОВ1 изм. 3» → key «АНО1503211РОВ1», revision 3) for the ИД rules.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_QUOTES = "«»“”„‟\"'‘’‚`´"
_EDGE_PUNCT = _QUOTES + "()[]{}<>,;:!?…—–-·•*/\\|"
_LAT_TO_CYR = str.maketrans("ABCEHKMOPTXYaceopxy", "АВСЕНКМОРТХУасеорху")

# Russian inflection: cut the ending, then allow a short suffix after the stem.
_MAX_SUFFIX = 4


def norm_text(text: str) -> str:
    """Lowercase, «ё» → «е», NFKC, quotes removed, whitespace collapsed."""
    t = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    t = t.translate({ord(c): " " for c in _QUOTES})
    return re.sub(r"\s+", " ", t).strip()


def norm_word(word: str) -> str:
    """One token normalised for matching; a trailing «.» is kept (it marks an abbreviation)."""
    w = unicodedata.normalize("NFKC", word).lower().replace("ё", "е")
    trailing_dot = w.rstrip(_EDGE_PUNCT).endswith(".")
    w = w.strip(_EDGE_PUNCT + ".")
    if trailing_dot and w:
        w += "."
    return w


def split_words(text: str) -> list[str]:
    """Normalised words of a text span; tokens that are pure punctuation are dropped."""
    out: list[str] = []
    for raw in re.split(r"[\s/]+", text):
        w = norm_word(raw)
        if w and w != ".":
            out.append(w)
    return out


def _is_code_like(word: str) -> bool:
    return bool(re.search(r"\d", word)) or bool(re.fullmatch(r"[a-z.\-]+", word))


@dataclass(frozen=True, slots=True)
class _WordPattern:
    stem: str
    exact: bool

    def matches(self, word: str) -> bool:
        w = word.rstrip(".")
        if self.exact:
            return w == self.stem
        if w.startswith(self.stem):
            return len(w) - len(self.stem) <= _MAX_SUFFIX
        # a dotted abbreviation of the anchor word: «отопл.» for «отопление»
        return word.endswith(".") and len(w) >= 4 and self.stem.startswith(w)


def _word_pattern(word: str) -> _WordPattern:
    raw = word.strip(_EDGE_PUNCT + ". ")
    w = norm_word(word).rstrip(".")
    if _is_code_like(w) or (len(raw) >= 2 and raw.isupper()):
        return _WordPattern(w, exact=True)  # «ИТП», «ОЗК», «Multibox», «Т1»
    if len(w) <= 4:
        return _WordPattern(w, exact=False)  # «пол» → «полы», «лифт» → «лифта»
    cut = 2 if len(w) <= 7 else 3
    return _WordPattern(w[: len(w) - cut], exact=False)


@dataclass(frozen=True, slots=True)
class Phrase:
    text: str
    words: tuple[_WordPattern, ...]

    @property
    def size(self) -> int:
        return len(self.words)


def compile_phrase(text: str) -> Phrase | None:
    raw_words = [w for w in re.split(r"[\s/]+", text) if norm_word(w) not in ("", ".")]
    words = tuple(_word_pattern(w) for w in raw_words)  # the raw case marks abbreviations («ИТП»)
    return Phrase(text, words) if words else None


@dataclass(frozen=True, slots=True)
class PhraseHit:
    phrase: str
    start: int  # index of the first matched word
    end: int  # exclusive


class PhraseMatcher:
    """Finds any of a set of anchor phrases in a sequence of normalised words."""

    def __init__(self, phrases: Iterable[str]):
        compiled = [p for p in (compile_phrase(t) for t in phrases) if p is not None]
        # longest first, so «контур тёплого пола» wins over «тёплый пол» at the same position
        self.phrases: tuple[Phrase, ...] = tuple(sorted(compiled, key=lambda p: -p.size))

    def __bool__(self) -> bool:
        return bool(self.phrases)

    def find(self, words: Sequence[str]) -> list[PhraseHit]:
        hits: list[PhraseHit] = []
        i = 0
        n = len(words)
        while i < n:
            matched = None
            for p in self.phrases:
                if i + p.size <= n and all(p.words[k].matches(words[i + k]) for k in range(p.size)):
                    matched = PhraseHit(p.text, i, i + p.size)
                    break
            if matched:
                hits.append(matched)
                i = matched.end
            else:
                i += 1
        return hits

    def search_text(self, text: str) -> list[PhraseHit]:
        return self.find(split_words(text))


# ───────────────────────────────────────────── Room tokens ─────────────────────────────────────────────

# A room number as printed: «012», «267», «1.109», «-1.05», «12а». Up to 4 leading digits.
ROOM_TOKEN = r"-?\d{1,4}(?:\.\d{1,3}){0,2}[а-я]?"
_ROOM_TOKEN_RE = re.compile(rf"^{ROOM_TOKEN}$")
# a room word must introduce the list; a bare «№» also numbers documents («Постановление … №87»)
_LIST_PREFIX = r"(?:\bпом(?:ещени[а-я]*)?\.?|\bкомнат[а-я]*)"
_ITEM = rf"(?:№\s*)?({ROOM_TOKEN})"
_SEP = r"(?:\s*[,;]\s*(?:и\s+)?|\s+и\s+|\s*[–-]\s*)"
_ROOM_LIST_RE = re.compile(rf"{_LIST_PREFIX}\s*{_ITEM}(?:{_SEP}{_ITEM})*", re.IGNORECASE)
_ITEM_RE = re.compile(rf"(?:№\s*)?({ROOM_TOKEN})")
_RANGE_RE = re.compile(rf"({ROOM_TOKEN})\s*[–-]\s*({ROOM_TOKEN})")
_MAX_RANGE = 30


def is_room_token(token: str) -> bool:
    return bool(_ROOM_TOKEN_RE.match(token))


def clean_room_token(token: str) -> str | None:
    """A plan-label token as a room token («270,» → «270»), or None."""
    t = unicodedata.normalize("NFKC", token).strip(_QUOTES + "()[],;:. ").lower()
    return t if is_room_token(t) else None


def _expand_range(a: str, b: str) -> list[str] | None:
    if not (a.isdigit() and b.isdigit()) or len(a) != len(b):
        return None
    lo, hi = int(a), int(b)
    if not (0 < hi - lo <= _MAX_RANGE):
        return None
    return [str(n).zfill(len(a)) for n in range(lo, hi + 1)]


def room_lists(text: str) -> list[tuple[int, int, list[str]]]:
    """Room lists introduced by «пом.»/«помещения»/«№» in ``text``: (start, end, tokens as printed)."""
    out: list[tuple[int, int, list[str]]] = []
    for m in _ROOM_LIST_RE.finditer(text):
        span = m.group(0)
        tokens: list[str] = []
        body_start = m.start(1) - m.start()
        body = span[body_start:]
        pos = 0
        for rm in _RANGE_RE.finditer(body):
            expanded = _expand_range(rm.group(1), rm.group(2))
            before = body[pos : rm.start()]
            tokens.extend(t.group(1) for t in _ITEM_RE.finditer(before))
            if expanded:
                tokens.extend(expanded)
            else:
                tokens.extend([rm.group(1), rm.group(2)])
            pos = rm.end()
        tokens.extend(t.group(1) for t in _ITEM_RE.finditer(body[pos:]))
        tokens = [t.lower() for t in tokens]
        uniq = list(dict.fromkeys(tokens))
        if uniq:
            out.append((m.start(), m.end(), uniq))
    return out


_NEGATION_RE = re.compile(r"\bне\s+(?:предусм|выполн|устанавл|требу)|\bотсутств|\bисключ|\bне\s+допуска")


def is_negated(text: str) -> bool:
    """«не предусмотрен», «отсутствует», «исключены» in a sentence about an element."""
    return bool(_NEGATION_RE.search(norm_text(text)))


_PROSE_WORD = re.compile(r"^[А-ЯЁа-яё]+$")
_PROSE_NUMBER = re.compile(r"^[+\-−]?\d+(?:[.,]\d+)*[а-я]?$")
_PROSE_STRIP = "()[]{}«»“”„\"'.,;:!?…"


def is_prose(text: str) -> bool:
    """A sentence rather than a table row or a drawing's label soup. Russian words must dominate the code-like
    tokens (Latin, mixed letters and digits, symbols); plain numbers such as room lists are neutral up to three per
    word. «В помещениях … (пом. 267, 270, 271, 272) предусмотрена система подогрева полов» passes; «Подвесная
    канальная -50/40R.2D WNP 100 6000 6600 (480) 1245 2850 U=3x380 …» (an equipment table row) does not."""
    words = numbers = other = 0
    for raw in text.split():
        t = raw.strip(_PROSE_STRIP)
        if not t or not any(ch.isalnum() for ch in t):
            continue
        if _PROSE_WORD.match(t):
            words += 1
        elif _PROSE_NUMBER.match(t):
            numbers += 1
        else:
            other += 1
    return words >= 3 and words >= 2 * other and numbers <= 3 * words


_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[А-ЯЁA-Z«\"(])")


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of running text; abbreviations like «пом. 267» are not split (lowercase/digit next)."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENTENCE_SPLIT.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


# ───────────────────────────────────────────── Numbers ─────────────────────────────────────────────────

_NUMBER_RE = re.compile(
    r"^[+\-\u2212]?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?$|^[+\-\u2212]?\d+(?:[.,]\d+)?$"
)


def parse_number(raw: object) -> float | None:
    """«2797,27», «1 079,9», «−5», 12 → float; anything else → None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return None if isinstance(raw, float) and math.isnan(raw) else float(raw)
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    s = re.sub(r"\s*(м²|м2|кв\.?\s*м\.?|м³|м|мм|%)$", "", s, flags=re.IGNORECASE).strip()
    if not _NUMBER_RE.match(s):
        return None
    s = re.sub(r"[ \u00a0\u202f]", "", s.replace("\u2212", "-")).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def decimals_of(raw: object) -> int:
    """Number of decimals as printed («134.0» → 1, «2797,27» → 2, 12 → 0)."""
    if raw is None or isinstance(raw, bool):
        return 0
    s = str(raw).strip()
    m = re.search(r"[.,](\d+)\s*\D*$", s)
    return len(m.group(1)) if m else 0


def fmt_number(value: float, decimals: int | None = None) -> str:
    """Russian display: decimal comma, minus sign «−», no thousands grouping («2797,27», «30,4», «12»)."""
    text = f"{abs(value):.3f}".rstrip("0").rstrip(".") if decimals is None else f"{abs(value):.{decimals}f}"
    text = text.replace(".", ",")
    return f"−{text}" if value < 0 and text.strip("0,") else text


# ───────────────────────────────────────────── Document codes ──────────────────────────────────────────

_CODE_RE = re.compile(r"(?<![\w/])([A-ZА-ЯЁ][A-ZА-ЯЁ0-9]*(?:[/\-.][A-ZА-ЯЁ0-9.]+){1,8})(?![\w])")
_REVISION_RE = re.compile(r"изм(?:енение)?\.?\s*№?\s*(\d{1,2})", re.IGNORECASE)
_STAGE_PART = {"Р": "Р", "РД": "Р", "П": "П", "ПД": "П"}


@dataclass(frozen=True, slots=True)
class CodeRef:
    raw: str
    key: str
    revision: int | None
    stage_hint: str | None = None  # RD / PD from the stage part of the code («-Р-», «-РД-», «-П-»)


def fold_latin(token: str) -> str:
    """Latin look-alike capitals → Cyrillic («T21» → «Т21», «B2.1» → «В2.1»), as OCR often returns them."""
    return token.translate(_LAT_TO_CYR)


def code_stage_hint(code: str) -> str | None:
    """«RD» for codes with a «Р»/«РД» part, «PD» for «П»/«ПД», else None."""
    s = unicodedata.normalize("NFKC", code).upper().translate(_LAT_TO_CYR)
    parts = {_STAGE_PART.get(p) for p in re.split(r"[\s/\-_.]+", _REVISION_RE.sub("", s)) if p}
    if "Р" in parts:
        return "RD"
    if "П" in parts:
        return "PD"
    return None


def code_key(code: str) -> str:
    """Comparable key of a document code: Latin look-alikes → Cyrillic, stage «РД»/«Р» unified, separators dropped."""
    s = unicodedata.normalize("NFKC", code).upper().translate(_LAT_TO_CYR)
    s = _REVISION_RE.sub("", s)
    parts = [p for p in re.split(r"[\s/\-_.]+", s) if p]
    return "".join(_STAGE_PART.get(p, p) for p in parts)


_NUMBER_SIGN_RE = re.compile(r"(?<![\w/])(?:№|No\.?|N°)\s*(?=[А-ЯЁ])")


def document_codes(text: str) -> list[CodeRef]:
    """Document codes cited in a text (АОСР «п. 2», title blocks), each with its «изм. N» when given."""
    out: list[CodeRef] = []
    # a number sign glued to the code («NoАНО/150321/1-РД-ОВ2.1», «№АНО…») is not part of it
    norm = _NUMBER_SIGN_RE.sub("", unicodedata.normalize("NFKC", text))
    folded = norm.upper().translate(_LAT_TO_CYR)
    if len(folded) != len(norm):  # a case mapping changed the length: match on the original text
        folded = norm
    for m in _CODE_RE.finditer(folded):
        raw = norm[m.start() : m.end()]
        if not re.search(r"\d", raw) or len(re.sub(r"[/\-.]", "", raw)) < 6:
            continue
        tail = norm[m.end() : m.end() + 24]
        rev = _REVISION_RE.search(tail)
        out.append(
            CodeRef(
                raw=raw,
                key=code_key(raw),
                revision=int(rev.group(1)) if rev else None,
                stage_hint=code_stage_hint(raw),
            )
        )
    return out


def revision_number(text: str | None) -> int | None:
    if not text:
        return None
    m = _REVISION_RE.search(text) or re.fullmatch(r"\s*(\d{1,2})\s*", text)
    return int(m.group(1)) if m else None
