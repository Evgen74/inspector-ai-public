"""Deterministic document-code corrector (96 §7.2, R-06): Latin/digit look-alikes → Cyrillic in шифр contexts.

PP-OCR reads Cyrillic capitals of document codes as Latin letters or digits («AHO/150321/1-PД-OB1» for
«АНО/150321/1-РД-ОВ1»). The corrector touches only *code-shaped* tokens: at least two ``-``/``/``
separators, letters and digits present. Inside such a token, each letter segment is mapped:

1. Latin look-alikes ``A B C E H K M O P T X Y`` → Cyrillic (a segment without Cyrillic letters that has
   any Latin letter without a Cyrillic twin, such as ``RU``, ``FRLS`` or ``KGV``, stays Latin);
2. ``0`` → ``О`` and ``3`` → ``З`` between Cyrillic letters;
3. a leading/trailing ``0``/``3`` glued to letters becomes ``О``/``З`` only when the result is a known
   discipline/organisation abbreviation (``DISCIPLINES`` + registry extras).

The raw string is always kept by the caller (``Token.text_raw``); the corrected value is the match key.
:func:`registry_match` implements the registry prior (manifest code known → accept within distance 1).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

LAT2CYR = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "C": "С",
        "E": "Е",
        "H": "Н",
        "K": "К",
        "M": "М",
        "O": "О",
        "P": "Р",
        "T": "Т",
        "X": "Х",
        "Y": "У",
    }
)
_LOOKALIKE = set("ABCEHKMOPTXY")

DISCIPLINES = frozenset(
    {
        "ПЗ", "ПЗУ", "СПЗУ", "АР", "АС", "КР", "КЖ", "КМ", "КМД", "ОВ", "ОВиК", "ВК", "НВК", "ЭОМ", "ЭМ", "ЭО",
        "ЭС", "ЭН", "ЭГ", "СС", "ИОС", "ТХ", "ТС", "ПОС", "ПОД", "ООС", "ПБ", "МПБ", "ППМ", "ОДИ", "ЭЭ", "ТБЭ",
        "ГП", "ГЧ", "ТЧ", "РД", "П", "Р", "ИД", "ИС", "ИРД", "ВОР", "СП", "ОК", "ДР", "АТЗ", "ОПЗ", "ИИ", "ИГИ",
        "ИГДИ", "ИЭИ", "СМ", "ПОКР", "АК", "АТХ", "ГСН", "НК", "НВ", "ТМ", "АОВ", "ОВ1", "ОВ2",
    }
)  # fmt: skip

_CODE_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё][0-9A-Za-zА-Яа-яЁё./_\-]{4,}")
_SEP = re.compile(r"([-/._\s])")


def is_code_like(token: str) -> bool:
    return (
        (token.count("-") + token.count("/")) >= 2
        and bool(re.search(r"\d", token))
        and bool(re.search(r"[A-Za-zА-Яа-яЁё]", token))
    )


# Capitals the recogniser reads as Latin letters that are *not* visual twins (Д → D, П → N). They are
# mapped only when the whole letter head of the segment then spells a known abbreviation (rule 4), e.g.
# «PD» → «РД» in «AHO/150321/1-PD-OB2.1»; «RU», «LS», «FRLS» stay Latin.
_CONFUSABLE = {"D": "Д", "N": "П"}
_HEAD_TAIL = re.compile(r"^([A-Za-zА-Яа-яЁё]+)([0-9.]*)$")


def _dictionary_variant(seg: str, known: frozenset[str] | set[str]) -> str | None:
    """Rule 4: look-alikes plus confusables → a known abbreviation head (+ unchanged digit tail)."""
    m = _HEAD_TAIL.match(seg)
    if not m:
        return None
    head, tail = m.group(1), m.group(2)
    if not any(c in _CONFUSABLE for c in head):
        return None
    mapped = []
    for c in head:
        if c in _CONFUSABLE:
            mapped.append(_CONFUSABLE[c])
        elif c in _LOOKALIKE:
            mapped.append(c.translate(LAT2CYR))
        elif re.match(r"[А-ЯЁ]", c):
            mapped.append(c)
        else:
            return None  # another Latin letter: a genuinely Latin segment
    cand = "".join(mapped)
    return cand + tail if cand in known else None


def fix_segment(seg: str, extra: Iterable[str] = ()) -> str:
    if not re.search(r"[A-Za-zА-Яа-яЁё]", seg):
        return seg
    latin = [c for c in seg if "A" <= c <= "Z" or "a" <= c <= "z"]
    if latin and any(c not in _LOOKALIKE for c in latin):
        alt = _dictionary_variant(seg, DISCIPLINES | set(extra))
        if alt is not None:
            return alt
        if not re.search(r"[А-Яа-яЁё]", seg):
            return seg  # a genuinely Latin segment («RU», «FRLS», «KGV»): letters with no Cyrillic twin
    s = seg.translate(LAT2CYR)
    s = re.sub(r"(?<=[А-ЯЁ])0(?=[А-ЯЁ])", "О", s)
    s = re.sub(r"(?<=[А-ЯЁ])3(?=[А-ЯЁ])", "З", s)
    known = DISCIPLINES | set(extra)
    m = re.match(r"^([А-ЯЁ]+)([03])([0-9.]*)$", s)
    if m:
        cand = m.group(1) + {"0": "О", "3": "З"}[m.group(2)]
        if cand in known or any(d.startswith(cand) for d in known):
            s = cand + m.group(3)
    m = re.match(r"^([03])([А-ЯЁ]+.*)$", s)
    if m:
        cand = {"0": "О", "3": "З"}[m.group(1)] + m.group(2)
        head = re.match(r"^[А-ЯЁ]+", cand)
        if head and head.group(0) in known:
            s = cand
    return s


def fix_code(token: str, extra: Iterable[str] = ()) -> str:
    parts = _SEP.split(token)
    return "".join(fix_segment(p, extra) if i % 2 == 0 else p for i, p in enumerate(parts))


def fix_text(text: str, extra: Iterable[str] = ()) -> str:
    """Correct every code-shaped token of a text; other tokens are returned unchanged."""
    extra = tuple(extra)

    def rep(m: re.Match[str]) -> str:
        t = m.group(0)
        return fix_code(t, extra) if is_code_like(t) else t

    return _CODE_TOKEN.sub(rep, text)


_LOOKALIKE_ANY = str.maketrans(
    {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
     "X": "Х", "Y": "У", "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у"}
)  # fmt: skip
_LATIN = re.compile(r"[A-Za-z]")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def fold_mixed_script(token: str) -> str:
    """Latin look-alikes → Cyrillic inside an OCR token that already contains Cyrillic letters.

    PP-OCR returns «PД», «TCП», «BД1», «П1/BЕ» for «РД», «ТСП», «ВД1», «П1/ВЕ». A token is folded only
    when every Latin letter in it has a Cyrillic twin; tokens with other Latin letters («ВВГнг(А)-LS»,
    «В15П4F(I)150W6», «Д-RU.РА01») and all-Latin tokens («AMP-K», «EI30», «HW-10KGV») are unchanged.
    Applied to OCR tokens only: a text layer is what the document says.
    """
    if not _CYRILLIC.search(token):
        return token
    latin = _LATIN.findall(token)
    if not latin or any(c not in _LOOKALIKE and c not in "acepoxy" for c in latin):
        return token
    return token.translate(_LOOKALIKE_ANY)


def post_correct(
    text: str, extra: Iterable[str] = (), *, code: bool = True, fold: bool = True
) -> tuple[str, str | None]:
    """F5 post-correction of OCR text: code corrector, then the mixed-script fold (per whitespace token).

    Returns (text, corrector) where ``corrector`` names what changed it (``Token.corrected_by``).
    """
    fixed = fix_text(text, extra) if code else text
    by: list[str] = ["code_corrector"] if fixed != text else []
    folded = " ".join(fold_mixed_script(t) for t in fixed.split(" ")) if fold else fixed
    if folded != fixed:
        by.append("homoglyph_fold")
    return folded, ("+".join(by) or None)


# ── Line/page script context (M1, GT v2 conventions) ─────────────────────────────────────────
#
# The recogniser cannot see the script of a homoglyph («T11» / «Т11», «°C» / «°С», «B25» / «В25»): the GT v2
# convention (ocr_gt_v2.json stats.conventions) is the reader's one — letters follow the script of their
# context. Three rules on OCR words, each validated on the 14 GT v2 pages (bench ``scans_v2``):
#
# 1. diameter: Greek «φ» / Cyrillic «ф» glued to a number is the diameter sign «Ø» (``DIAMETER``: «φ15»,
#    «ф16х2,2»); upper-case «Ф1» stays (foundation marks);
# 2. script context: a word whose letters all have a twin in the other script («T11», «C», «B», «OOO»)
#    takes the script of its line (unambiguous letters of the other words), else of its page (``page_script``);
#    a word with unambiguous letters of one script gets that script's twins («НW-10KGV» → «HW-10KGV»);
# 3. italic Cyrillic (ГОСТ 2.304 type B on drawings) read as Latin: «т» → «m», «п» → «n», «и» → «u»,
#    «д» → «g», «г» → «r», «ш» → «w», «к» → «k». In a word with Cyrillic letters they are always misreads
#    («noм.» → «пом.»); an all-Latin letter run in a Cyrillic context is transliterated only when the result
#    is a lexicon word («Cm15» → «Ст15», «Pacxog» → «Расход», «KBm» → «КВт»), and never for Latin units
#    (``LATIN_KEEP``). «m» is «т» in italic (prior 1) and rarely «м» (prior ``ITALIC_M_AS_EM``); ties go to
#    the word's document frequency in the TRAIN lexicon.

CYR_TWINS = "АВСЕНКМОРТХУасеорхуі"  # «і» (U+0456) is not Russian: always the Latin «i» misread
LAT_TWINS = "ABCEHKMOPTXYaceopxy"
_TO_CYR = str.maketrans(LAT_TWINS, CYR_TWINS[:-1])
_TO_LAT = str.maketrans(CYR_TWINS, LAT_TWINS + "i")
_DIGIT_IN_WORD = re.compile(r"(?<=[А-Яа-яЁё])[30](?=[А-Яа-яЁё])")  # «И3м.» → «Изм.», «К0д» → «Код»
_TWIN_BETWEEN_DIGITS = re.compile(r"\d[ABCEАВСЕ]\d")  # «19C7»: a hex serial (certificates), not a word
_OOO = re.compile(r"^[0OО]{3}$")
ITALIC = {"m": "тм", "n": "п", "u": "и", "g": "д", "r": "тг", "w": "ш", "k": "к"}
ITALIC_M_AS_EM = 0.1
LATIN_KEEP = frozenset({"mm", "cm", "km", "kg", "mg", "ml", "um", "nm", "kn", "mk"})
DIAMETER = "Ø"
_DIAM = re.compile(r"(?<![A-Za-zА-Яа-яЁё])[φф](?=\d)")
_LAT_RUN = re.compile(r"[A-Za-z]+")


def _is_cyr(c: str) -> bool:
    return "А" <= c <= "я" or c in "Ёё"


def _is_lat(c: str) -> bool:
    return ("A" <= c <= "Z") or ("a" <= c <= "z")


def script_counts(text: str) -> tuple[int, int]:
    """(unambiguous Cyrillic, unambiguous Latin) letters of ``text``; twins and italic look-alikes are neutral."""
    cyr = lat = 0
    for c in text:
        if _is_cyr(c):
            cyr += c not in CYR_TWINS
        elif _is_lat(c):
            lat += c not in LAT_TWINS and c not in ITALIC
    return cyr, lat


def script_of(cyr: int, lat: int, *, share: float = 0.75, minimum: int = 1) -> str | None:
    """«cyr» / «lat» when one script has at least ``share`` of the unambiguous letters (and ``minimum``)."""
    n = cyr + lat
    if n < minimum:
        return None
    if cyr >= share * n:
        return "cyr"
    if lat >= share * n:
        return "lat"
    return None


def page_script(words: Iterable[str]) -> str | None:
    """Script prior of a page from all its OCR words (≥ 20 unambiguous letters, ≥ 60 % one script: drawing
    sheets carry Latin model codes next to Russian text)."""
    cyr = lat = 0
    for w in words:
        c, lt = script_counts(w)
        cyr, lat = cyr + c, lat + lt
    return script_of(cyr, lat, share=0.6, minimum=20)


def _digit_to_letter(m: re.Match[str]) -> str:
    s, i = m.string, m.start()
    upper = s[i - 1].isupper() and (i + 1 >= len(s) or s[i + 1].isupper())
    return {"3": "З" if upper else "з", "0": "О" if upper else "о"}[m.group(0)]


def _italic_run(
    run: str, lexicon: frozenset[str] | set[str] | None, freq: dict[str, int] | None, need_word: bool
) -> str | None:
    """Cyrillic reading of a Latin letter run made of twins and italic look-alikes, or None.

    ``need_word``: the reading must be a lexicon word (all-Latin runs); otherwise (runs inside a Cyrillic
    word) the best lexicon reading wins and the plain italic reading is the fallback."""
    if any(c not in LAT_TWINS and c not in ITALIC for c in run):
        return None
    options: list[tuple[str, float]] = [("", 1.0)]
    for c in run:
        if c in ITALIC:
            alts = ITALIC[c]
            options = [
                (p + a, w * (ITALIC_M_AS_EM if (c == "m" and a == "м") else 1.0))
                for p, w in options
                for a in alts
            ]
        else:
            options = [(p + c.translate(_TO_CYR), w) for p, w in options]
    best: tuple[float, str] | None = None
    if lexicon:
        for cand, prior in options:
            key = cand.lower().replace("ё", "е")
            if key in lexicon:
                score = prior * (1 + (freq or {}).get(key, 1))
                if best is None or score > best[0]:
                    best = (score, cand)
    if best is not None:
        return best[1]
    return None if need_word else options[0][0]


def resolve_script(
    word: str,
    context: str | None,
    lexicon: frozenset[str] | set[str] | None = None,
    freq: dict[str, int] | None = None,
) -> str:
    """Rules 2–3 above for one OCR word; ``context`` is the line's script, else the page's (or None)."""
    letters = [c for c in word if c.isalpha()]
    if not letters:
        return word
    has_cyr = any(_is_cyr(c) for c in letters)
    ucyr = any(_is_cyr(c) and c not in CYR_TWINS for c in letters)
    hard_lat = [c for c in letters if _is_lat(c) and c not in LAT_TWINS and c not in ITALIC]
    italic = any(c in ITALIC for c in letters)
    if hard_lat:
        # a Latin word (unambiguous Latin letters): Cyrillic twins inside it are misreads («НW» → «HW»)
        return word.translate(_TO_LAT) if (has_cyr and not ucyr) else word
    if ucyr:
        # a Cyrillic word: Latin twins and italic look-alikes inside it are misreads («PД», «noм.»), and so are
        # «3»/«0» between its letters
        if italic:
            word = _LAT_RUN.sub(
                lambda m: _italic_run(m.group(0), lexicon, freq, need_word=False) or m.group(0), word
            )
        return _DIGIT_IN_WORD.sub(_digit_to_letter, word.translate(_TO_CYR))
    # every letter is a twin (or an italic look-alike): the context decides
    if _TWIN_BETWEEN_DIGITS.search(word) and not italic:
        return word  # a serial or hex number («19C7»); «х» between digits is folded by the metric anyway
    if context == "cyr":
        if not italic:
            return word.translate(_TO_CYR)

        def rep(m: re.Match[str]) -> str:
            run = m.group(0)
            if len(run) < 2 or run in LATIN_KEEP:  # exact case: «cm» is a unit, «Cm» is «Ст»
                return run
            return _italic_run(run, lexicon, freq, need_word=True) or run

        return _LAT_RUN.sub(rep, word).translate(_TO_CYR) if has_cyr else _LAT_RUN.sub(rep, word)
    if context == "lat" and not italic:
        return word.translate(_TO_LAT)
    if has_cyr and not italic:
        return word.translate(
            _TO_CYR
        )  # no context: a mixed word of twins folds to Cyrillic (fold_mixed_script)
    return word


def post_correct_line(
    words: list[str],
    extra: Iterable[str] = (),
    *,
    page: str | None = None,
    code: bool = True,
    fold: bool = True,
    context: bool = True,
    diameter: bool = True,
    lexicon: frozenset[str] | set[str] | None = None,
    freq: dict[str, int] | None = None,
) -> list[tuple[str, str | None]]:
    """F5 post-correction of the OCR words of one line: code corrector, diameter sign, script (rules above).

    ``page`` is the page script prior (:func:`page_script`); ``context=False`` falls back to the per-word
    mixed-script fold of :func:`post_correct`. Returns (text, corrector) per word (``Token.corrected_by``)."""
    extra = tuple(extra)
    line_ctx = (
        script_of(*map(sum, zip(*(script_counts(w) for w in words), strict=True)), minimum=2)
        if words
        else None
    )
    ctx = line_ctx or page
    out: list[tuple[str, str | None]] = []
    for k, raw in enumerate(words):
        text = fix_text(raw, extra) if code else raw
        by: list[str] = ["code_corrector"] if text != raw else []
        nxt = words[k + 1] if k + 1 < len(words) else ""
        if (
            context
            and fold
            and ctx != "lat"
            and _OOO.match(text)
            and nxt[:1] in "«\"“„'" + "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ"
            and nxt
        ):
            text, by = "ООО", [*by, "script_context"]  # «000 «ТСП»» → «ООО «ТСП»» (legal form before a name)
            out.append((text, "+".join(by)))
            continue
        if diameter:
            d = _DIAM.sub(DIAMETER, text)
            if d != text:
                by.append("diameter_sign")
                text = d
        if fold:
            f = " ".join(
                (resolve_script(t, ctx, lexicon, freq) if context else fold_mixed_script(t))
                for t in text.split(" ")
            )
            if f != text:
                by.append("script_context" if context else "homoglyph_fold")
                text = f
        out.append((text, "+".join(by) or None))
    return out


def dictionary_from_names(names: Iterable[str]) -> frozenset[str]:
    """Cyrillic capital runs (2–5 letters) of document file names: the object's own organisation and
    discipline abbreviations («АНО», «НВС», «РД», «ВК») for rule 3. Derived at run time from the inputs
    of the object being processed, never from a fixed list of object names."""
    out: set[str] = set()
    for name in names:
        for m in re.finditer(r"(?<![А-ЯЁа-яё])[А-ЯЁ]{2,5}(?![а-яё])", name):
            out.add(m.group(0))
    return frozenset(out)


_HOMO_FOLD = str.maketrans(
    {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
     "X": "Х", "Y": "У", "0": "О", "3": "З", "N": "П", ".": "/", "_": "/"}
)  # fmt: skip


def homoglyph_key(code: str) -> str:
    """Fold look-alikes and separators so that OCR variants of one code compare equal."""
    return re.sub(r"\s+", "", code.upper()).translate(_HOMO_FOLD)


def registry_match(ocr_code: str, known_codes: Iterable[str], max_distance: int = 1) -> str | None:
    """Registry prior (96 §7.2): the known code within homoglyph-aware edit distance ≤ ``max_distance``."""
    from rapidfuzz.distance import Levenshtein

    key = homoglyph_key(ocr_code)
    best: tuple[int, str] | None = None
    for code in known_codes:
        d = Levenshtein.distance(key, homoglyph_key(code), score_cutoff=max_distance)
        if d <= max_distance and (best is None or d < best[0]):
            best = (d, code)
    return best[1] if best else None
