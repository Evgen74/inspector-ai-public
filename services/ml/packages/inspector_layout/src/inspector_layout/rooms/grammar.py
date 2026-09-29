"""Grammar of room numbers and drawing marks (96 R-15, 95 R3/R8; owner AG-02B).

Room tokens are kept **exactly as printed**: «012» is not «12» (the scorer's gate compares the location token
literally, 93 §2.3 case J). A token is a room number only in a label context (a number in a circle on a plan,
the first word of a schematic room label «142 Астрономии…», the number column of an explication); the grammar
here only says what *can* be a room token.

Marks (tags) on ventilation and heating sheets:

- vent systems and branches: «П1», «В2.4», «ПВ3», «ВЕ13», «П2/ВЕ»; lists expand: «В2.7,8,9» → В2.7, В2.8,
  В2.9; «П17.1, 17.2» → П17.1, П17.2; «П2.1, П8, П18» → П2.1, П8, П18;
- air terminals «АМН-К 400x150», «АМР-К», «РСН-К», equipment «М.О. поз.169», «Зонт», humidifiers, radiators
  «PRADO Universal 22-500-700»; risers «Ст19»; pipelines «Т11»; warm floors;
- air flows «−950 м³/ч», «L 400» and duct sizes «400x150», «Ø200» (``tag_kind`` OTHER until AG-00 ratifies
  the proposed AIR_FLOW / DUCT_SIZE kinds; ``tag_norm`` carries the parsed value: «L=-950», «400×150»);
- level marks «±0.000», «-2.950».

OCR of outlined CAD text returns Cyrillic capitals as Latin look-alikes («B2.9», «AMH-K», «M.O.», «no3.169»)
and the diameter sign as a zero («0200»); :func:`fold` and the parsers undo that. The closed-vocabulary
spotter (:class:`Vocabulary`) repairs the few remaining OCR slips («B22» → «В2.2», «82.1» → «В2.1») only when
the repaired tag is known from a trusted source (text layers of the same object).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

# ── folding ──────────────────────────────────────────────────────────────────────────────────

LAT2CYR_UPPER = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
    "X": "Х", "Y": "У",
}  # fmt: skip
LAT2CYR_LOWER = {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у"}
_DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-"}
_FOLD = str.maketrans({**LAT2CYR_UPPER, **LAT2CYR_LOWER, **_DASHES})
_DASH_ONLY = str.maketrans(_DASHES)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def fold(text: str) -> str:
    """Latin look-alikes → Cyrillic, dashes → «-» (for tags and words, never for room numbers)."""
    return nfc(text).translate(_FOLD)


def dashes(text: str) -> str:
    return nfc(text).translate(_DASH_ONLY)


# ── room tokens ──────────────────────────────────────────────────────────────────────────────

# «012», «140», «1109», «012.1», «258.1», «1.109», «1.05», «2.2.1» (floor.section.room, ГОСТ Р 21.101); an
# optional Cyrillic letter suffix («101а»).
# Signed or zero-led decimals are level marks («-0.014», «0.150»), never rooms.
ROOM_CORE = r"(?:\d{1,2}\.\d{1,2}\.\d{1,3}|[1-9]\d?\.\d{2,3}|\d{3,4}(?:\.\d{1,2})?)[а-яё]?"
ROOM_RE = re.compile(rf"^{ROOM_CORE}$")
_ROOM_LIST = re.compile(rf"^\s*({ROOM_CORE}(?:\s*,\s*{ROOM_CORE})*)(?:\s+(.*))?$")
# Words that follow a number but make it a quantity, not a room («на 600 мест», «400 мм», «700 Вт»).
_UNIT_WORDS = re.compile(
    r"^(?:(?:мест[аo]?|мм|см|м|м2|м²|м3|м³|вт|квт|шт|кг|т|л|ч|сут|чел|pa|па|руб|x|х)(?![А-Яа-яЁёA-Za-z])"
    r"|[°×/*=+%-])",
    re.IGNORECASE,
)


def is_room_token(text: str) -> bool:
    return bool(ROOM_RE.match(text.strip()))


def split_room_list(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


@dataclass(frozen=True, slots=True)
class RoomLabelText:
    rooms: tuple[str, ...]
    name: str | None


def parse_room_label(line: str) -> RoomLabelText | None:
    """A label line that starts with room numbers: «142 Астрономии», «267, 270», «174, 176 Обеденный зал», «012».

    The remainder (if any) must start with a word (the room name), never with a unit or an operator.
    """
    text = nfc(line).strip()
    m = _ROOM_LIST.match(text)
    if not m:
        return None
    rooms = tuple(split_room_list(m.group(1)))
    rest = (m.group(2) or "").strip()
    if rest:
        if _UNIT_WORDS.match(rest) or not re.match(r"^[«\"(]?[А-ЯЁа-яё]", rest):
            return None
        return RoomLabelText(rooms, rest)
    return RoomLabelText(rooms, None)


def floor_from_room_number(token: str) -> str | None:
    """Weak hint from the numbering scheme: the first digit is the floor («142» → «1»), a leading zero the basement («012» → «0»)."""
    t = token.strip()
    if re.match(r"^0\d{2}", t):
        return "0"
    if re.match(r"^[1-9]\d{2}(?:\.\d)?[а-яё]?$", t):
        return t[0]
    m = re.match(r"^(\d{1,2})\.\d{2,3}[а-яё]?$", t)  # «1.109», «2.05»: floor.room (ГОСТ Р 21.101)
    if m:
        return str(int(m.group(1)))
    return None


# ── floors from sheet titles ─────────────────────────────────────────────────────────────────

_ORD = r"(?<![\d])([-−]?\d{1,2})\s*(?:-?\s*(?:го|ого|й|ой|ий))?\s*этаж"
_FLOOR_PATTERNS: tuple[tuple[re.Pattern[str], str | None], ...] = (
    (re.compile(r"(?:подвал|цокольн)", re.IGNORECASE), "подвал"),
    (re.compile(r"техн?\.?\s*подпол", re.IGNORECASE), "техподполье"),
    (re.compile(r"кровл", re.IGNORECASE), "кровля"),
    (re.compile(r"(?:чердак|техническ\w+\s+этаж)", re.IGNORECASE), "техэтаж"),
    (re.compile(_ORD, re.IGNORECASE), None),
)


def floor_from_title(text: str) -> str | None:
    """«План 1-го этажа (вентиляция)» → «1»; «План подвала» → «подвал»; «Экспликация … 2 этажа» → «2»."""
    t = fold(text)
    if not re.search(r"(?:план|экспликац|схема\s+располож)", t, re.IGNORECASE):
        return None
    m = re.search(_ORD, t, re.IGNORECASE)
    if m:
        return str(int(m.group(1).replace("−", "-")))
    for rx, value in _FLOOR_PATTERNS[:-1]:
        if rx.search(t):
            return value
    return None


# ── tags ─────────────────────────────────────────────────────────────────────────────────────

VENT_PREFIXES = ("ПВ", "ПЕ", "ВЕ", "ВД", "ПД", "ДУ", "ВЗ", "П", "В")
_VP = "|".join(VENT_PREFIXES)
_NUM = r"\d{1,3}(?:\.\d{1,3})?"
_VENT = re.compile(
    rf"(?<![А-ЯЁа-яё\w])(?P<prefix>{_VP})(?P<first>{_NUM})"
    rf"(?P<more>(?:\s*,\s*(?:{_VP})?{_NUM}(?![\d]))*)"
    rf"(?![\d])(?!\s*[xх×]\s*\d)(?!\s*(?:мм|шт|кВт|Вт|°))"
)
_VENT_PART = re.compile(rf"^(?P<prefix>{_VP})?(?P<num>{_NUM})$")
_VENT_BARE = re.compile(r"(?<![А-ЯЁа-яё\w])(?P<prefix>ВЕ|ПЕ)(?![А-ЯЁа-яё\w])")
_RISER = re.compile(r"(?<![А-ЯЁа-яё\w])(?:Ст|С[тm]|Cт|Cm)\.?\s?(?P<num>\d{1,3}[а-я]?|[ТT]\d{1,2})(?![\d])")
# Pipelines «Т1», «Т11», «Т21» (ГОСТ 21.206): as a whole word anywhere in a line — side by side («Т11 Т21»),
# glued by OCR («T11T21»), with a temperature («Т11=+85 °С») or cut by the pipe drawn through them («-T21-»).
_PIPE = re.compile(r"(?:(?<=Т\d)|(?<=Т\d\d)|(?<![\w.,]))(?P<code>Т\d{1,2})(?=$|[\s=/,;:)\-]|Т\d)")
# «12/BE» is «П2/ВЕ»: a supply system paired with natural exhaust; OCR reads the outlined «П» as «1»/«N».
_PAIR_HEAD = re.compile(r"(?<![\w])[1NЛn](?=\d{1,2}\s*/\s*ВЕ(?![А-ЯЁа-яё\w]))")
_WARM_FLOOR = re.compile(
    r"(?:т[её]пл\w*\s+пол\w*|подогрев\w*\s+пол\w*|(?<![А-ЯЁа-яё])ТП\d{0,2}(?![\dА-ЯЁа-яё]))", re.IGNORECASE
)
_TERMINAL = re.compile(
    r"(?<![А-ЯЁа-яё\w])(?P<name>\d?А[МДРП][НРПК](?:-[КМ])?|РС[НР]-К|ДПУ(?:-[МК])?|ДКУ|СТД|АРС|ПРМ|РВ-\d)"
    r"(?:\s+(?P<w>\d{2,4})\s?[xх×*]\s?(?P<h>\d{2,4}))?"
)
_MO = re.compile(r"(?<![А-ЯЁа-яё\w])М\.?\s?О\.?(?![А-ЯЁа-яё])(?:\s*(?:поз|п)\.?\s*(?P<pos>\d{1,4}))?")
_POS = re.compile(r"(?<![А-ЯЁа-яё\w])поз\.?\s*(?P<pos>\d{1,4}(?:[.,]\d{1,3})?)")
_EQUIP_WORDS = re.compile(
    r"(?<![А-ЯЁа-яё])(?P<word>Зонт|Пароувлажнитель|Увлажнитель|Обеззараживатель|Вентилятор|Воздухонагреватель|"
    r"Шумоглушитель|Кондиционер|Фанкойл|Коллектор|Конвектор|Радиатор|Регулятор|Multibox|ЭПГ-\d{2,3}(?:-[А-Я]{1,3})?)",
    re.IGNORECASE,
)
_LATIN_EQUIP = re.compile(r"(?<![A-Za-z])(?P<word>Multibox|SBOW|Danfoss|Vaillant)(?![A-Za-z])", re.IGNORECASE)
_RADIATOR = re.compile(
    r"(?P<brand>PRADO|Kermi|Purmo|Buderus|Rifar|Royal|Arbonia|Zehnder|КЗТО|Сантехпром)\s*"
    r"(?P<model>[A-Za-zА-Яа-я]+)?\s*(?P<type>\d{2})-(?P<height>\d{3})-(?P<length>\d{3,4})",
    re.IGNORECASE,
)
_RAD_MODEL = re.compile(
    r"(?<![\d-])(?P<type>1[01]|2[012]|3[03])-(?P<height>[2-9]\d{2})-(?P<length>\d{3,4})(?![\d-])"
)
_HEAT = re.compile(r"(?<![\d.,\w])(?P<val>\d{2,5})\s?(?:Вт|Вm|Bт|Bm|W)(?!\w)")
_TEMP = re.compile(r"(?<![\d])(?P<val>[+]\d{1,2})\s?°?\s?[CС](?![А-Яа-яA-Za-z])")
_SIZE = re.compile(r"(?<![\d.,])(?P<w>\d{2,4})\s?[xх×*X]\s?(?P<h>\d{2,4})(?![\d])")
_DIAM = re.compile(r"(?:[Øø⌀∅Ф]\s?)(?P<d>\d{2,4})(?:\s?[xх×]\s?(?P<t>\d+(?:[.,]\d+)?))?")
_DIAM_OCR = re.compile(r"^0(?P<d>\d{3})$")  # «0200» = «Ø200» (the recogniser reads Ø as 0)
_FLOW = re.compile(
    r"(?P<sign>[+\-±]?)\s?(?P<val>\d{2,5})\s?(?:м\s?[³3]\s?/\s?[чh]|м[³3]/?ч?|[mм](?:[³3])?(?:/[чh4])?)(?![А-Яа-я\d])"
)
_FLOW_L = re.compile(r"(?<![А-ЯЁа-яё\w])[LЛ]\s?=?\s?(?P<val>\d{2,5})(?![\d])")
_LEVEL = re.compile(r"(?<![\d\w])(?P<v>[±+\-]\d{1,2}[.,]\d{3})(?![\d])")


@dataclass(slots=True)
class TagMatch:
    """One mark found in a text line: ``span`` indexes the (folded) line string."""

    tag: str  # as printed (the line substring)
    tag_norm: str
    tag_kind: str  # contract TagKind
    span: tuple[int, int]
    system_code: str | None = None
    subkind: str = ""  # finer class for inventories: branch, system, terminal, local_exhaust, flow, size …
    value: float | None = None
    repaired: bool = False


def _vent_parts(prefix: str, first: str, more: str) -> list[str]:
    out = [f"{prefix}{first}"]
    major = first.split(".")[0]
    cur_prefix = prefix
    had_sub = "." in first
    for part in [p.strip() for p in more.split(",") if p.strip()]:
        m = _VENT_PART.match(part)
        if not m:
            continue
        if m.group("prefix"):
            cur_prefix = m.group("prefix")
            num = m.group("num")
            major = num.split(".")[0]
            had_sub = "." in num
            out.append(f"{cur_prefix}{num}")
            continue
        num = m.group("num")
        if "." in num:
            major = num.split(".")[0]
            out.append(f"{cur_prefix}{num}")
        elif had_sub:
            out.append(f"{cur_prefix}{major}.{num}")  # «В2.7,8,9»: the continuation is a branch number
        else:
            out.append(f"{cur_prefix}{num}")  # «П1,2»
    return out


def vent_subkind(tag_norm: str) -> str:
    """«В2.4» → branch (ответвление), «В2» → system, «ВЕ» → natural (без номера)."""
    if re.match(rf"^(?:{_VP})\d{{1,3}}\.\d", tag_norm):
        return "branch"
    if re.match(rf"^(?:{_VP})\d", tag_norm):
        return "system"
    return "natural"


def system_of(tag_norm: str) -> str | None:
    m = re.match(rf"^((?:{_VP})\d{{1,3}})", tag_norm)
    if m:
        return m.group(1)
    m = re.match(rf"^({_VP})$", tag_norm)
    return m.group(1) if m else None


LIST_SEP = ", "  # the elements of one printed vent list in TagInstance.tag_norm: «В2.7, В2.8, В2.9»


def mark_elements(tag_norm: str | None, tag_kind: str | None) -> list[str]:
    """The elements a TagInstance stands for: a vent list is one printed mark but several branches."""
    if not tag_norm:
        return []
    if tag_kind == "VENT_SYSTEM":
        return [p for p in tag_norm.split(LIST_SEP) if p]
    return [tag_norm]


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(span[0] < b and a < span[1] for a, b in taken)


def parse_tags(line: str, *, vent: bool = True, heating: bool = True) -> list[TagMatch]:
    """Every mark in one text line (after :func:`fold`). ``vent``/``heating`` gate the system grammars."""
    line = nfc(line)
    u = line.translate(_DASH_ONLY)  # Latin brand names («PRADO», «Multibox») are matched unfolded
    s = line.translate(_FOLD)
    s = re.sub(r"(?<![А-ЯЁа-яё])(?:nо|no|пo|п0|по)[3з]\.", "поз.", s)  # OCR «no3.169» → «поз.169»
    heads = [m.start() for m in _PAIR_HEAD.finditer(s)]
    if heads:  # «12/BE» → «П2/BE»: same length, so spans still index ``line``; the print reads «П2» too
        s = _PAIR_HEAD.sub("П", s)
        line = "".join("П" if i in heads else ch for i, ch in enumerate(line))
        u = "".join("П" if i in heads else ch for i, ch in enumerate(u))
    concrete = bool(re.search(r"(?<![А-ЯЁA-Za-z])[FW]\d{1,3}\b", u))  # «B25 F150 W6»: a concrete class
    out: list[TagMatch] = []
    taken: list[tuple[int, int]] = []

    def add(m: TagMatch) -> None:
        out.append(m)
        taken.append(m.span)

    for m in _RADIATOR.finditer(u):
        model = (m.group("model") or "").strip()
        norm = " ".join(
            x
            for x in (m.group("brand"), model, f"{m.group('type')}-{m.group('height')}-{m.group('length')}")
            if x
        )
        add(TagMatch(line[m.start() : m.end()], norm, "EQUIPMENT", m.span(), subkind="radiator"))
    for m in _TERMINAL.finditer(s):
        if _overlaps(m.span(), taken):
            continue
        norm = m.group("name")
        if m.group("w"):
            norm += f" {m.group('w')}×{m.group('h')}"
        add(TagMatch(line[m.start() : m.end()], norm, "AIR_TERMINAL", m.span(), subkind="terminal"))
    for m in _MO.finditer(s):
        if _overlaps(m.span(), taken):
            continue
        norm = "М.О." + (f" поз.{m.group('pos')}" if m.group("pos") else "")
        add(TagMatch(line[m.start() : m.end()], norm, "EQUIPMENT", m.span(), subkind="local_exhaust"))
    for m in list(_EQUIP_WORDS.finditer(s)) + list(_LATIN_EQUIP.finditer(u)):
        if _overlaps(m.span(), taken):
            continue
        word = m.group("word")
        sub = "warm_floor" if word.lower() == "multibox" else "equipment"
        if word.lower() == "зонт":
            sub = "local_exhaust"
        add(TagMatch(line[m.start():m.end()], word[0].upper() + word[1:].lower() if not word.startswith("ЭПГ") else word,
                     "EQUIPMENT", m.span(), subkind=sub))  # fmt: skip
    if heating:
        for m in _WARM_FLOOR.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            printed = line[m.start() : m.end()]
            norm = "тёплый пол" if not printed.upper().startswith("ТП") else fold(printed).upper()
            add(TagMatch(printed, norm, "HEATING_SYSTEM", m.span(), system_code=norm if norm != "тёплый пол" else None,
                         subkind="warm_floor"))  # fmt: skip
        for m in _RISER.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            num = fold(m.group("num"))
            norm = f"Ст{'.' if num.startswith('Т') else ''}{num}"
            add(
                TagMatch(
                    line[m.start() : m.end()], norm, "PIPE_RISER", m.span(), system_code=norm, subkind="riser"
                )
            )
    if vent and not concrete:
        for m in _VENT.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            parts = _vent_parts(m.group("prefix"), m.group("first"), m.group("more") or "")
            printed = line[m.start() : m.end()]
            for norm in parts:
                out.append(TagMatch(printed, norm, "VENT_SYSTEM", m.span(), system_code=system_of(norm),
                                    subkind=vent_subkind(norm)))  # fmt: skip
            taken.append(m.span())
        for m in _VENT_BARE.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            norm = m.group("prefix")
            add(
                TagMatch(
                    line[m.start() : m.end()],
                    norm,
                    "VENT_SYSTEM",
                    m.span(),
                    system_code=norm,
                    subkind="natural",
                )
            )
        for m in _FLOW.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            sign = {"±": "±", "+": "+", "-": "-"}.get(m.group("sign"), "")
            val = float(m.group("val"))
            add(TagMatch(line[m.start():m.end()], f"L={sign}{m.group('val')}", "OTHER", m.span(), subkind="flow",
                         value=-val if sign == "-" else val))  # fmt: skip
        for m in _FLOW_L.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            add(TagMatch(line[m.start():m.end()], f"L={m.group('val')}", "OTHER", m.span(), subkind="flow",
                         value=float(m.group("val"))))  # fmt: skip
    if heating:
        for m in _RAD_MODEL.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            norm = f"{m.group('type')}-{m.group('height')}-{m.group('length')}"
            add(TagMatch(line[m.start() : m.end()], norm, "EQUIPMENT", m.span(), subkind="radiator"))
        for m in _HEAT.finditer(line):
            if _overlaps(m.span(), taken):
                continue
            add(TagMatch(line[m.start():m.end()], f"Q={m.group('val')} Вт", "OTHER", m.span(), subkind="heat",
                         value=float(m.group("val"))))  # fmt: skip
        for m in _TEMP.finditer(line):
            if _overlaps(m.span(), taken):
                continue
            add(TagMatch(line[m.start():m.end()], f"t={m.group('val')} °C", "OTHER", m.span(), subkind="temperature",
                         value=float(m.group("val"))))  # fmt: skip
    for m in _SIZE.finditer(s):
        if _overlaps(m.span(), taken):
            continue
        add(
            TagMatch(
                line[m.start() : m.end()], f"{m.group('w')}×{m.group('h')}", "OTHER", m.span(), subkind="size"
            )
        )
    for m in _DIAM.finditer(s):
        if _overlaps(m.span(), taken):
            continue
        norm = f"Ø{m.group('d')}" + (f"×{m.group('t')}" if m.group("t") else "")
        add(TagMatch(line[m.start() : m.end()], norm, "OTHER", m.span(), subkind="size"))
    if heating:
        for m in _PIPE.finditer(s):
            if _overlaps(m.span(), taken):
                continue
            code = m.group("code")
            add(TagMatch(line[m.start():m.end()], code, "HEATING_SYSTEM", m.span(), system_code=code,
                         subkind="pipeline"))  # fmt: skip
    for m in _LEVEL.finditer(s):
        if _overlaps(m.span(), taken):
            continue
        add(
            TagMatch(
                line[m.start() : m.end()],
                m.group("v").replace(",", "."),
                "LEVEL_MARK",
                m.span(),
                subkind="level",
            )
        )
    for m in _POS.finditer(s):
        if _overlaps(m.span(), taken):
            continue
        add(
            TagMatch(
                line[m.start() : m.end()], f"поз.{m.group('pos')}", "OTHER", m.span(), subkind="position"
            )
        )
    out.sort(key=lambda t: t.span)
    return out


def ocr_diameter(token: str) -> str | None:
    """«0200» (OCR of «Ø200») → «Ø200»; three-digit tokens are never diameters (they may be rooms: «012»)."""
    m = _DIAM_OCR.match(token.strip())
    return f"Ø{m.group('d')}" if m else None


def ocr_flow(token: str) -> float | None:
    """OCR of an air-flow cell without its unit: «950M», «+400m», «-140M» → the value (sign when printed)."""
    m = re.match(r"^(?P<sign>[+\-±]?)(?P<val>\d{2,5})[mMм][³3]?(?:/[чh4]?)?$", dashes(token.strip()))
    if not m:
        return None
    val = float(m.group("val"))
    return -val if m.group("sign") == "-" else val


# ── closed vocabulary ────────────────────────────────────────────────────────────────────────

_LEAD_FIX = {"8": "В", "6": "В", "в": "В", "N": "П", "n": "П", "Л": "П", "п": "П", "I1": "П", "Il": "П"}
# Weak heads: outlined ISOCPEUR «В» read as «3» («В2.1» → «32.1») and «П» as «11» («П9» → «119»). A token with
# such a head is also a plausible number (an area, a position), so these are tried only when the caller has
# independent evidence that the token is a mark (a vent label layer, or a low OCR confidence).
_WEAK_LEAD_FIX = {"3": "В", "11": "П"}


@dataclass(slots=True)
class Vocabulary:
    """Known system/branch tags of an object (from trusted text layers), for OCR repair and confidence."""

    tags: set[str] = field(default_factory=set)

    def add(self, tags: Iterable[str]) -> None:
        for t in tags:
            if t:
                self.tags.add(t)

    def __contains__(self, tag: str) -> bool:
        return tag in self.tags

    def __len__(self) -> int:
        return len(self.tags)

    def repair(self, token: str, *, weak_heads: bool = False) -> str | None:
        """An OCR token that is one slip away from a known vent tag: «B22» → «В2.2», «82.1» → «В2.1».

        ``weak_heads`` also tries «3» → «В» and «11» → «П» («32.1» → «В2.1», «119» → «П9»); the caller sets it
        only with independent evidence that the token is a mark (see :data:`_WEAK_LEAD_FIX`).
        """
        raw = fold(token.strip()).rstrip(",.;")
        if not raw or len(raw) > 8 or raw in self.tags:
            return None
        candidates: set[str] = set()
        heads = {raw}
        fixes = {**_LEAD_FIX, **_WEAK_LEAD_FIX} if weak_heads else _LEAD_FIX
        for bad, good in fixes.items():
            if raw.startswith(bad) and len(raw) > len(bad):
                heads.add(good + raw[len(bad) :])
        for h in heads:
            candidates.add(h)
            m = re.match(rf"^({_VP})(\d)(\d{{1,2}})$", h)
            if m:  # dot lost: «В22» → «В2.2»; «П171» → «П17.1»
                candidates.add(f"{m.group(1)}{m.group(2)}.{m.group(3)}")
                if len(m.group(3)) == 2:
                    candidates.add(f"{m.group(1)}{m.group(2)}{m.group(3)[0]}.{m.group(3)[1]}")
        hits = sorted(c for c in candidates if c in self.tags and c != raw)
        return hits[0] if len(hits) == 1 else None

    def repair_confusables(self, text: str) -> str:
        """Same-length repair of OCR-confusable marks inside one token: «П10/B1Q.3» → «П10/В10.3», «R6.3» → «В6.3».

        Each ``/``- or ``,``-separated part shaped like a mark (one or two head letters, then digits/dots) is
        rewritten only when the confusable-folded form (R→В, Q/O/D→0, l/I→1) is a mark of the closed vocabulary
        and the part itself is not; anything else is left untouched.
        """
        if not self.tags or not _CONF_PART_HINT.search(text):
            return text

        def fix(m: re.Match[str]) -> str:
            part = m.group(0)
            raw = fold(part)
            if raw in self.tags:
                return part
            cand = "".join(
                _CONF_HEAD.get(c, c) if i == 0 else _CONF_DIGIT.get(c, c) for i, c in enumerate(raw)
            )
            if cand != raw and cand in self.tags and len(cand) == len(part):
                return cand
            return part

        return _CONF_PART.sub(fix, text)


_CONF_PART = re.compile(r"(?<![\w.])[A-Za-zА-ЯЁа-яё]{1,2}[0-9OQDIl][0-9OQDIl.]*(?![\w])")
_CONF_PART_HINT = re.compile(r"[RQODIl]")
_CONF_HEAD = {"R": "В"}
_CONF_DIGIT = {"Q": "0", "O": "0", "D": "0", "I": "1", "l": "1"}
