"""ИГС: executive geodetic schemes (исполнительные геодезические схемы) that print deviations as drawing
annotations and the tolerance as a note on the same sheet (pilot OKT103: «Допуски на листе: 15 мм, ±12 мм и
20 мм. Факт: +491/+552, +980/+537 и +201/+349 мм»).

Two kinds of facts per scheme page, both evidence on that one ИД page:

* **tolerance notes** — a line that names a tolerance («допуск», «допускаемое / допустимое / предельное
  отклонение») followed, within the same clause, by numbers in millimetres (or signed «±N»). Each number is
  one tolerance; its kind comes from the clause (PLAN: оси, в плане, смещение; ELEVATION: отметка, высота;
  THICKNESS: толщина);
* **measured deviations** — explicitly signed millimetre annotations («+491», «−8», «+491/+552» as an X/Y
  pair), integers or one decimal, |d| ≤ 3000 mm. Tokens on the tolerance lines, temperatures («−15 °С»),
  elevations (three decimals) and tokens followed by a word are not deviations.

A page counts only when it is an executive scheme («исполнительная [геодезическая] схема», «исполнительная
съемка») and not an act (АОСР pages cite their schemes). The verdict (deviation vs tolerance) is AG-04's
(``inspector_compare.tolerance``); this module only reads what the sheet prints. The element on the scheme
(ELEMENT_KINDS) is read from the whole page text and travels as a qualifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.pagesource import PageData
from inspector_tables.text import Box, Word, group_lines, squash

PARSER_VERSION = "igs-1"

SCHEME = re.compile(
    r"исполнительн[а-я]*?\s*(?:геодезическ[а-я]*?\s*)?(?:схем|съемк|чертеж)"
    r"|геодезическ[а-я]*?\s*исполнительн[а-я]*?\s*схем"
)  # OCR glues words («Исполнительнаясхемаармированной»)
# act / registry content (a scheme is often «Приложение к акту освидетельствования…», so the act title alone is
# not enough to exclude a page)
ACT = re.compile(
    r"предъявлен\w*\s+к\s+освидетельствовани|разрешается\s+производство|на\s+основании\s+изложенного"
    r"|реестр\s+исполнительн"
)
_TOL_KEY = re.compile(
    r"(допуст[а-я]*\s*(?:отклонени|погрешн)[а-я]*|допускаем[а-я]*\s*отклонени[а-я]*|предельн[а-я]*\s*отклонени[а-я]*"
    r"|допуск[а-я]*)"
)  # letters only: a glued «допуск15мм» keeps its number in the clause
# one tolerance number inside the clause: «15 мм», «±12 мм», «± 12», «+/-12мм», «12,5 мм»
_TOL_NUM = re.compile(
    r"(±|\+\s*/?\s*[-−–]|\+-)?\s*(?<![\d.,])(\d{1,3}(?:[.,]\d)?)(?!\d)(?![.,]\d)\s*(мм|mm)?"
)
_DEV = re.compile(r"^([+\-−–])(\d{1,4}(?:[.,]\d)?)(?:мм|mm)?[;,.]?$")
_DEV_PAIR = re.compile(r"^([+\-−–])(\d{1,4}(?:[.,]\d)?)[/\\|]([+\-−–])(\d{1,4}(?:[.,]\d)?)(?:мм|mm)?[;,.]?$")
_TEMP_NEXT = re.compile(r"^(°|º|о?с$|град|°с|0с)", re.I)
MAX_DEV_MM = 3000.0

ELEMENT_KINDS: tuple[tuple[str, str], ...] = (
    ("FOUNDATION_SLAB", r"фундаментн\w*\s+плит|плит\w*\s+фундамент|ростверк"),
    ("FLOOR_SLAB", r"плит\w*\s+(?:перекрыти|покрыти)|перекрыти\w*|покрыти\w*\s+плит"),
    ("WALL", r"\bстен\w*|пилон\w*|диафрагм\w*|ядр\w*\s+жесткост"),
    ("COLUMN", r"колонн\w*"),
    ("PILE", r"\bсва[йия]\w*"),
    ("AXES", r"разбивк\w*\s+ос|\bосей\b|оси\s+здания|вынос\w*\s+ос"),
)


@dataclass(slots=True)
class Tolerance:
    value: float
    raw: str
    kind: str | None  # PLAN | ELEVATION | THICKNESS | None (not said)
    line: str
    box: Box | None
    conf: float = 1.0


@dataclass(slots=True)
class Deviation:
    value: float
    raw: str
    box: Box | None
    pair: str | None = None  # "x" | "y" for the components of «+491/+552»
    conf: float = 1.0


@dataclass(slots=True)
class IgsPage:
    page_no: int
    title: str
    element_kind: str | None
    tolerances: list[Tolerance] = field(default_factory=list)
    deviations: list[Deviation] = field(default_factory=list)
    axes: str | None = None


def _norm_text(text: str) -> str:
    return squash(text).lower().replace("ё", "е")


def is_scheme(text: str) -> bool:
    """An executive scheme page (not an act that cites one)."""
    t = _norm_text(text)
    return bool(SCHEME.search(t)) and not ACT.search(t)


def _kind(clause: str) -> str | None:
    if re.search(r"толщин", clause):
        return "THICKNESS"
    if re.search(r"отмет|высот|нивелир", clause):
        return "ELEVATION"
    if re.search(r"в плане|\bос[ьиея]\w*|смещени|разбивочн|вертикал|привязк", clause):
        return "PLAN"
    return None


def _num(raw: str) -> float:
    return float(raw.replace(",", "."))


def tolerances_of_line(line: str) -> list[tuple[float, str, str | None]]:
    """(value, raw, kind) for every tolerance number of one printed line; [] when the line names none."""
    t = _norm_text(line)
    out: list[tuple[float, str, str | None]] = []
    for m in _TOL_KEY.finditer(t):
        clause = t[m.end() : m.end() + 120]
        clause = re.split(r"(?<!\d)[.;](?!\d)", clause, maxsplit=1)[0]
        kind = _kind(t[max(0, m.start() - 60) : m.end()] + " " + clause)
        for n in _TOL_NUM.finditer(clause):
            sign, num, unit = n.group(1), n.group(2), n.group(3)
            if not (unit or sign):
                continue  # a bare number («табл. 5.10», «п. 3») is not a tolerance
            v = _num(num)
            if 0 < v <= 200:
                out.append((v, n.group(0).strip(), kind))
    return out


def deviation_of_token(text: str) -> list[tuple[float, str, str | None]]:
    """Signed millimetre annotation(s) of one token: «+491» → [(491, …)], «+491/+552» → two components."""
    s = squash(text).replace(" ", "")
    m = _DEV_PAIR.match(s)
    if m:
        a = _num(m.group(2)) * (-1 if m.group(1) != "+" else 1)
        b = _num(m.group(4)) * (-1 if m.group(3) != "+" else 1)
        return [(a, s, "x"), (b, s, "y")] if abs(a) <= MAX_DEV_MM and abs(b) <= MAX_DEV_MM else []
    m = _DEV.match(s)
    if m:
        v = _num(m.group(2)) * (-1 if m.group(1) != "+" else 1)
        return [(v, s, None)] if abs(v) <= MAX_DEV_MM else []
    return []


def _element_kind(text: str) -> str | None:
    t = _norm_text(text)
    for kind, pat in ELEMENT_KINDS:
        if re.search(pat, t):
            return kind
    return None


def _axes(text: str) -> str | None:
    m = re.search(
        r"в\s+осях\s+([0-9A-ZА-Я][0-9A-ZА-Яа-я.,\-–/ ]{1,30}?)(?=\s+(?:на|с|по|от)\b|[;:)\n]|$)", squash(text)
    )
    return squash(m.group(1)).rstrip(",.") if m else None


def _box(words: list[Word]) -> Box | None:
    return Box.of_words(words) if words else None


def parse_page(page: PageData, text: str | None = None) -> IgsPage | None:
    """The ИГС facts of one page, or None when the page is not a scheme or prints no tolerance."""
    full = text if text is not None else page.text
    if not is_scheme(full):
        return None
    lines = group_lines(page.words)
    tol_words: set[int] = set()
    out = IgsPage(page.page_no, _title(full), _element_kind(full), axes=_axes(full))
    for ln in lines:
        found = tolerances_of_line(ln.text)
        if not found:
            continue
        tol_words.update(id(w) for w in ln.words)
        conf = min((w.conf for w in ln.words), default=1.0)
        for v, raw, kind in found:
            out.tolerances.append(Tolerance(v, raw, kind, squash(ln.text)[:200], _box(ln.words), conf))
    if not out.tolerances:
        return None
    for ln in lines:
        ws = ln.words
        for i, w in enumerate(ws):
            if id(w) in tol_words:
                continue
            devs = deviation_of_token(w.text)
            if not devs:
                continue
            nxt = ws[i + 1] if i + 1 < len(ws) else None
            if nxt is not None and nxt.x0 - w.x1 < 1.5 * max(w.h, 1e-6):
                nt = nxt.text.strip().lower()
                if _TEMP_NEXT.match(nt) or (re.match(r"^[а-яa-z]{3,}", nt) and not nt.startswith("мм")):
                    continue  # «−15 °С», «+5 градусов», «-1 этаж»: not a measured deviation
            for v, raw, comp in devs:
                out.deviations.append(Deviation(v, raw, Box(w.x0, w.y0, w.x1, w.y1), comp, w.conf))
    # vertical OCR words (rotated annotations) are outside group_lines: read them as tokens too
    for w in page.words:
        if w.angle in (0, 180):
            continue
        for v, raw, comp in deviation_of_token(w.text):
            out.deviations.append(Deviation(v, raw, Box(w.x0, w.y0, w.x1, w.y1), comp, w.conf))
    return out


def _title(text: str) -> str:
    m = re.search(r"исполнительн\w*\s+(?:геодезическ\w*\s+)?схем\w*[^\n]{0,80}", squash(text), re.I)
    return squash(m.group(0))[:120] if m else ""
