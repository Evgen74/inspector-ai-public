"""Text primitives shared by the table parsers: words, rulings, normalisation and Russian numbers.

Geometry is kept in *displayed page points* (after /Rotate, origin top-left, y down): tolerances such as
«half a line height» or «0.8 pt between collinear segments» are physical, so they must not depend on the
page aspect ratio. Contract output converts to normalized [0, 1] boxes (``PageData.norm_bbox``).
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass, field

# ── words and rulings ─────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Word:
    """One word (text-layer word or OCR token) in displayed page points."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    source: str = "TEXT_LAYER"  # TextSource code
    conf: float = 1.0
    angle: int = 0  # reading direction, clockwise, multiple of 90
    size: float = 0.0  # font size in pt (0 when unknown, e.g. OCR)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def w(self) -> float:
        return self.x1 - self.x0


@dataclass(slots=True, frozen=True)
class Ruling:
    """An axis-aligned table line. ``pos`` is x for vertical rulings and y for horizontal ones;
    ``lo``/``hi`` is the extent along the line."""

    vertical: bool
    pos: float
    lo: float
    hi: float
    width: float = 0.0

    @property
    def length(self) -> float:
        return self.hi - self.lo

    def covers(self, v: float, tol: float = 0.0) -> bool:
        return self.lo - tol <= v <= self.hi + tol


@dataclass(slots=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def union(self, other: Box) -> Box:
        return Box(
            min(self.x0, other.x0), min(self.y0, other.y0), max(self.x1, other.x1), max(self.y1, other.y1)
        )

    @staticmethod
    def of_words(words: list[Word]) -> Box | None:
        if not words:
            return None
        return Box(
            min(w.x0 for w in words),
            min(w.y0 for w in words),
            max(w.x1 for w in words),
            max(w.y1 for w in words),
        )


@dataclass(slots=True)
class TextLine:
    """Words of one visual line (same baseline band), left to right."""

    words: list[Word] = field(default_factory=list)

    @property
    def y0(self) -> float:
        return min(w.y0 for w in self.words)

    @property
    def y1(self) -> float:
        return max(w.y1 for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def text(self) -> str:
        return join_words(self.words)


# ── normalisation ─────────────────────────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")
LAT2CYR_UPPER = str.maketrans({"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О",
                               "P": "Р", "T": "Т", "X": "Х", "Y": "У"})  # fmt: skip
LAT2CYR_LOWER = str.maketrans({"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к",
                               "b": "б", "m": "м", "n": "п", "u": "и", "r": "г"})  # fmt: skip
_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT = re.compile(r"[A-Za-z]")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def squash(text: str) -> str:
    """NFC, non-breaking spaces to spaces, whitespace collapsed, stripped."""
    return _WS.sub(" ", nfc(text).replace(" ", " ").replace(" ", " ")).strip()


def fold(text: str) -> str:
    """Matching key for keyword search: lowercase, ё→е, Latin look-alikes→Cyrillic, soft hyphen joins
    («поме- щения» → «помещения»), punctuation dropped. Never used for output values."""
    t = squash(text).replace("ё", "е").replace("Ё", "Е")
    t = re.sub(r"(\w)-\s+(\w)", r"\1\2", t)
    t = t.translate(LAT2CYR_UPPER).lower().translate(LAT2CYR_LOWER)
    t = re.sub(r"[^\w%²³№]+", " ", t)
    return _WS.sub(" ", t).strip()


def join_words(words: list[Word]) -> str:
    """Words of one line joined left to right; a gap narrower than 0.12 em glues (split CAD glyph runs)."""
    if not words:
        return ""
    ws = sorted(words, key=lambda w: w.x0)
    out = [ws[0].text]
    for prev, cur in itertools.pairwise(ws):
        em = max(prev.h, cur.h, 1e-6)
        gap = cur.x0 - prev.x1
        out.append(cur.text if gap < 0.12 * em and not _both_numbers(prev.text, cur.text) else " " + cur.text)
    return squash("".join(out))


def _both_numbers(a: str, b: str) -> bool:
    return bool(re.fullmatch(r"[\d.,]+", a) and re.fullmatch(r"[\d.,]+", b))


def group_lines(words: list[Word], y_tol: float | None = None) -> list[TextLine]:
    """Cluster words into visual lines by vertical centre (horizontal words only, top to bottom)."""
    ws = sorted((w for w in words if w.angle in (0, 180)), key=lambda w: (w.cy, w.x0))
    lines: list[TextLine] = []
    for w in ws:
        tol = y_tol if y_tol is not None else max(w.h * 0.45, 0.5)
        if lines and abs(lines[-1].cy - w.cy) <= max(tol, (lines[-1].y1 - lines[-1].y0) * 0.45):
            lines[-1].words.append(w)
        else:
            lines.append(TextLine([w]))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
    return lines


def join_lines(a: str, b: str) -> str:
    """Join two wrapped lines of one cell. A line-end hyphen before a lowercase continuation is a soft
    hyphen when the glued word is a known word form («насад-»+«кой» → «насадкой»); otherwise it is kept
    («биолого-»+«химического» → «биолого-химического»)."""
    a, b = squash(a), squash(b)
    if not a:
        return b
    if not b:
        return a
    if a.endswith("-") and not a.endswith(" -") and b[:1].islower():
        head = re.search(r"([А-Яа-яЁё]+)-$", a)
        tail = re.match(r"([а-яё]+)", b)
        if head and tail:
            glued = (head.group(1) + tail.group(1)).lower().replace("ё", "е")
            try:
                known = glued in _lexicon()
            except Exception:
                known = False
            if known:
                return a[:-1] + b
        return a + b
    return a + " " + b


def lines_text(words: list[Word]) -> str:
    """Cell text: visual lines top to bottom, joined by :func:`join_lines`."""
    out = ""
    for ln in group_lines(words):
        out = join_lines(out, ln.text)
    return squash(out)


def cyrillic_code(text: str) -> str:
    """Letters of short codes (fire categories «В4», room suffixes «167а») to Cyrillic."""
    return text.translate(LAT2CYR_UPPER).translate(LAT2CYR_LOWER)


def mixed_script(text: str) -> bool:
    return bool(_CYR.search(text) and _LAT.search(text))


# ── numbers ───────────────────────────────────────────────────────────────────────────────────────

_NUM = re.compile(r"^[+\-−–]?\s*\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?$|^[+\-−–]?\s*\d+(?:[.,]\d+)?$")
_NUM_IN = re.compile(r"[+\-−–]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|[+\-−–]?\d+(?:[.,]\d+)?")


def parse_number(raw: str | None) -> float | None:
    """Russian-formatted number → float: «1 079,9», «8.6», «−12», «17 140,2». None when not a number."""
    if raw is None:
        return None
    s = squash(raw).rstrip(";:").rstrip()
    if s.endswith((".", ",")):
        s = s[:-1]
    if not _NUM.match(s):
        return None
    s = s.replace(" ", "").replace(" ", "").replace(" ", "").replace("−", "-").replace("–", "-")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def first_number(raw: str | None) -> tuple[float, str] | None:
    """The first number inside a string, with its printed form."""
    if not raw:
        return None
    m = _NUM_IN.search(raw)
    if not m:
        return None
    value = parse_number(m.group(0))
    return (value, m.group(0)) if value is not None else None


def number_value(value: float) -> float | int:
    """Integers stay integers in JSON («2» not «2.0»)."""
    return int(value) if float(value).is_integer() and abs(value) < 1e15 else round(value, 6)


# ── glued words (text layers that position words without a space character) ──────────────────────

_GLUE_TOKEN = re.compile(r"^([«\"(]?)([А-Яа-яЁё]{7,})([»\")]?[.,;:]?)$")
_SHORT_RIGHT = frozenset({"на", "в", "с", "и", "по", "от", "до", "из", "к", "за", "со"})


def _lexicon():
    from inspector_docproc.lexicon import load_lexicon

    return load_lexicon()


def resplit_glued(text: str) -> str:
    """«Обеденныйзал» → «Обеденный зал»: split a Cyrillic token that is not a known word form into two known
    ones (left ≥ 4 letters, right ≥ 3 or a preposition). Words the lexicon knows are never touched."""
    if not text:
        return text
    lx = _lexicon()
    if not len(lx):
        return text
    out = []
    for tok in text.split(" "):
        seg = segment_glued(tok)
        if seg != tok:
            out.append(seg)
            continue
        m = _GLUE_TOKEN.match(tok)
        if not m:
            out.append(tok)
            continue
        pre, word, post = m.groups()
        key = word.lower().replace("ё", "е")
        if key in lx:
            out.append(tok)
            continue
        best = None
        for i in range(4, len(key) - 1):
            left, right = key[:i], key[i:]
            if left in lx and right in lx and (len(right) >= 3 or right in _SHORT_RIGHT):
                score = min(len(left), len(right))
                if best is None or score > best[0]:
                    best = (score, i)
        if best is None:
            out.append(tok)
        else:
            i = best[1]
            out.append(f"{pre}{word[:i]} {word[i:]}{post}")
    return " ".join(out)


# ── units ─────────────────────────────────────────────────────────────────────────────────────────

_UNIT_MAP: tuple[tuple[str, str], ...] = (
    (r"^(кв\.?\s*м\.?|м\s*2|м²|m2|кв\.?\s*метр\w*)$", "м²"),
    (r"^(куб\.?\s*м\.?|м\s*3|м³|m3|куб\.?\s*метр\w*)$", "м³"),
    (r"^(тыс\.?\s*кв\.?\s*м\.?\s*/\s*га)$", "тыс. м²/га"),
    (r"^га$", "га"),
    (r"^(м|м\.|метр\w*)$", "м"),
    (r"^(мм|мм\.)$", "мм"),
    (r"^(эт\.?|этаж\w*)$", "эт."),
    (r"^(шт\.?|штук)$", "шт."),
    (r"^(компл\.?|комплект\w*)$", "компл."),
    (r"^(кг|кг\.)$", "кг"),
    (r"^(т|т\.|тонн\w*)$", "т"),
    (r"^(квт|kw|квт\.)$", "кВт"),
    (r"^(гкал/ч(ас)?\.?)$", "Гкал/ч"),
    (r"^(м3/ч|м³/ч|куб\.?\s*м/ч)$", "м³/ч"),
    (r"^(м3/сут|м³/сут|куб\.?\s*м/сут)$", "м³/сут"),
    (r"^(%|процент\w*)$", "%"),
    (r"^(п\.?\s*м\.?|пог\.?\s*м\.?)$", "п. м"),
)


def norm_unit(raw: str | None) -> str | None:
    """Printed unit → canonical form («кв. м» → «м²», «куб. м» → «м³»); None when unknown or empty."""
    if not raw:
        return None
    s = squash(raw).lower().replace("ё", "е")
    for pat, canon in _UNIT_MAP:
        if re.match(pat, s):
            return canon
    return None


def segments(words: list[Word], gap_em: float = 2.5) -> list[TextLine]:
    """Visual lines split at horizontal gaps wider than ``gap_em`` × the word height: the separate labels
    of a drawing that happen to share a baseline."""
    out: list[TextLine] = []
    for ln in group_lines(words):
        cur: list[Word] = []
        for w in ln.words:
            if cur and w.x0 - cur[-1].x1 > gap_em * max(w.h, cur[-1].h, 1.0):
                out.append(TextLine(cur))
                cur = []
            cur.append(w)
        if cur:
            out.append(TextLine(cur))
    return out


_SHORT_WORDS = frozenset(
    {"в", "с", "к", "и", "о", "у", "на", "по", "от", "до", "из", "за", "со", "во", "об", "не", "для", "при"}
)
_GLUE_PARTS = re.compile(r"[А-Яа-яЁё]+|\d+(?:[.,]\d+)?|[^\wА-Яа-яЁё\s]|[A-Za-z]+")


def _segment_run(run: str) -> list[str] | None:
    """Split a long letter run into known word forms (fewest pieces); None when no full split exists."""
    lx = _lexicon()
    key = run.lower().replace("ё", "е")
    n = len(key)
    best: list[tuple[int, int] | None] = [None] * (n + 1)  # (pieces, previous cut)
    best[0] = (0, -1)
    for i in range(n):
        if best[i] is None:
            continue
        for j in range(i + 1, min(n, i + 24) + 1):
            piece = key[i:j]
            if (len(piece) >= 3 and piece in lx) or piece in _SHORT_WORDS:
                cand = (best[i][0] + 1, i)
                if best[j] is None or cand[0] < best[j][0]:
                    best[j] = cand
    if best[n] is None or best[n][0] < 2:
        return None
    cuts = []
    j = n
    while j > 0:
        i = best[j][1]
        cuts.append((i, j))
        j = i
    return [run[i:j] for i, j in reversed(cuts)]


def segment_glued(token: str) -> str:
    """A long run glued by a condensed CAD font («Залдляпроведения…(на200мест)») → words, when every letter
    run of ≥ 14 characters that the lexicon does not know splits fully into known word forms."""
    if len(token) < 16 or not re.search(r"[А-Яа-яЁё]{14,}", token):
        return token
    lx = _lexicon()
    parts = _GLUE_PARTS.findall(token)
    words: list[str] = []
    changed = False
    for p in parts:
        if re.fullmatch(r"[А-Яа-яЁё]{14,}", p) and p.lower().replace("ё", "е") not in lx:
            seg = _segment_run(p)
            if seg is None:
                return token
            words.extend(seg)
            changed = True
        else:
            words.append(p)
    if not changed:
        return token
    out = ""
    for w in words:
        if not out:
            out = w
        elif w in (")", ",", ".", ";", ":") or out.endswith("("):
            out += w
        else:
            out += " " + w
    return out
