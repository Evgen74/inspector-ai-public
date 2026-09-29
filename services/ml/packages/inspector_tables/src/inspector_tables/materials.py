"""Structural materials and thicknesses from prose (КР/КЖ general notes, ПЗ, АОСР п.3): concrete class B, frost
and water marks F/W, rebar class A, element thickness — each bound to a structural element family.

Sources:

* PD/RD pages: the page text is cut into clauses (``;`` and sentence ends); a clause that names an element
  family («стена в грунте», «фундаментная плита», «сваи», …) and prints a class/mark binds the value to the
  family mentioned last before it (a mention after «кроме» never binds). A clause with a value but no family
  inherits the family of the previous clause of the same page (lower confidence), unless the clause names an
  excluded family.
* ИД: every АОСР of a binder (not just the first act of a file): the family comes from п.1 (work name), the
  values from п.3 (materials).

Nothing here decides a violation: facts go to ``values/<object>.jsonl`` (fact keys ``kr.*``), AG-04's materials
comparator compares them per family and stage (directional: a lower class is a downgrade, a higher one is not).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PARSER_VERSION = "materials-2"

# (canonical family label, pattern on the folded text) — order matters: specific before generic.
FAMILIES: tuple[tuple[str, str], ...] = (
    ("Стена в грунте", r"стен\w*\s+в\s+грунте|\bсвг\b"),
    ("Форшахта", r"форшахт"),
    ("Обвязочный пояс", r"обвязочн\w*\s+(?:ж\.?\s?б\.?\s+|железобетонн\w*\s+)?(?:пояс|балк)"),
    ("Бетонная подготовка", r"бетонн\w*\s+подготовк|\bподготовк\w*\s+(?:из|под)\b"),
    ("Сваи", r"\bсва[июяей]\w*|\bбсс\b|буросекущ|\bсваи-"),
    ("Ростверк", r"ростверк"),
    (
        "Фундаментная плита",
        r"фундаментн\w*\s+(?:ж\.?\s?б\.?\s+|железобетонн\w*\s+|монолитн\w*\s+)?плит|плит\w*\s+фундамент|фундамент\w*\s+(?:\S+\s+){0,8}?плит",
    ),
    ("Плиты перекрытий", r"перекрыти"),
    ("Плита покрытия", r"плит\w*\s+покрыти"),
    ("Колонны", r"колонн|пилон"),
    ("Балки", r"\bбалк|ригел"),
    ("Лестницы", r"лестниц|лестничн\w*\s+марш"),
    ("Монолитные стены", r"\bстен(?:ы|а|ам|ами|е)?\b(?!\s+в\s+грунте)"),
)
_FAMILY_RX = [(label, re.compile(p)) for label, p in FAMILIES]
_EXCLUDE = re.compile(r"кроме\s+(?:\S+\s+){0,2}$")

CONCRETE_CLASSES = {
    3.5,
    5,
    7.5,
    10,
    12.5,
    15,
    20,
    22.5,
    25,
    27.5,
    30,
    35,
    40,
    45,
    50,
    55,
    60,
    70,
    80,
    90,
    100,
}
FROST_MARKS = {25, 35, 50, 75, 100, 150, 200, 300, 400, 500, 600, 700, 800, 1000}
WATER_MARKS = {2, 4, 6, 8, 10, 12, 14, 16, 18, 20}
REBAR_ROMAN = {"I": 240, "II": 300, "III": 400, "IV": 600}

_B = re.compile(r"(?<![А-Яа-яЁёA-Za-z0-9])[BВ]\s?(\d{1,3}(?:[.,]5)?)(?![\d.,]\d)")
_F = re.compile(r"(?<![А-Яа-яЁёA-Za-z])F\s?(?:\(\s?I{1,2}\s?\)\s?)?(\d{2,4})(?:\s?\(\s?I{1,2}\s?\))?(?!\d)")
_W = re.compile(r"(?<![А-Яа-яЁёA-Za-z])W\s?(\d{1,2})(?!\d)")
_A = re.compile(r"(?<![А-Яа-яЁёA-Za-z0-9])[AА]\s?-?\s?(240|300|400|500|600)\s?([СC])?(?![\d])")
_A_OLD = re.compile(r"(?<![А-Яа-яЁёA-Za-z0-9])[AА]\s?-\s?(IV|III|II|I)(?![A-Za-z])")
_THICK = re.compile(
    r"толщин\w*\s*(?:[-–—:=]\s*)?(?:не\s+менее\s+|от\s+)?(\d{2,4})((?:\s*(?:и|,|/)\s*\d{2,4})*)\s*мм"
)
_CONCRETE_CTX = re.compile(r"бетон|\bбст\b|\bбсг\b|\bтяж[её]л")
_REBAR_CTX = re.compile(r"арматур|каркас|стержн|прокат")
_CLAUSE_SPLIT = re.compile(r";|(?<=[^\sА-ЯЁA-Z]\S)\.\s+(?=[А-ЯЁA-Z0-9«\"])|\n{2,}")

# kind → (fact key, catalog param code or None, ordinal scale)
KINDS: dict[str, tuple[str, str | None, str | None]] = {
    "concrete_class": ("kr.concrete_class", "KR-055", "CONCRETE_B"),
    "concrete_frost": ("kr.concrete_frost", None, None),
    "concrete_water": ("kr.concrete_water", None, None),
    "rebar_class": ("kr.rebar_class", "KR-057", "REBAR_CLASS"),
    "thickness": ("kr.thickness", None, None),
    # KR-056 / KR-060 / KR-062: value = display text, rank = yield-strength number / area mm² / diameter mm
    "steel_grade": ("kr.steel_grade", "KR-056", "STEEL_GRADE"),
    "column_section": ("kr.column_section", "KR-060", None),
    "column_rebar_dia": ("kr.column_rebar_diameter", "KR-062", None),
}
# thickness → catalog parameter by family (KR-058 фундаментная плита, KR-059 перекрытия, KR-061 стены)
THICKNESS_PARAM = {
    "Фундаментная плита": "KR-058",
    "Плиты перекрытий": "KR-059",
    "Плита покрытия": "KR-059",
    "Монолитные стены": "KR-061",
    "Стена в грунте": "KR-061",
}


@dataclass(slots=True)
class MaterialFact:
    kind: str
    family: str
    value: str  # display form: «B25», «F200», «W8», «A500С», «600»
    rank: float
    clause: str
    confidence: float
    inherited: bool = False
    act_no: str | None = None

    @property
    def param_code(self) -> str | None:
        if self.kind == "thickness":
            return THICKNESS_PARAM.get(self.family)
        return KINDS[self.kind][1]


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("ё", "е").replace("Ё", "Е")).strip().lower()


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _fmt_b(v: float) -> str:
    return ("B" + (f"{v:g}".replace(".", ","))) if v else "B"


def family_mentions(clause: str) -> list[tuple[int, str, bool]]:
    """(position, family, excluded) of every family mention in a clause (folded text)."""
    low = fold(clause)
    out: list[tuple[int, str, bool]] = []
    taken: list[tuple[int, int]] = []
    for label, rx in _FAMILY_RX:
        for m in rx.finditer(low):
            if any(s <= m.start() < e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            out.append((m.start(), label, bool(_EXCLUDE.search(low[: m.start()]))))
    return sorted(out)


def family_of(text: str) -> str | None:
    """The first (non-excluded) family named in a text (АОСР work name)."""
    for _, label, excluded in family_mentions(text):
        if not excluded:
            return label
    return None


def values_in(clause: str, *, concrete_context: bool | None = None) -> list[tuple[int, str, str, float]]:
    """(position in folded clause, kind, display value, rank) of every class/mark/thickness in one clause."""
    flat = re.sub(r"\s+", " ", clause or "")
    low = fold(flat)
    ctx_concrete = bool(_CONCRETE_CTX.search(low)) if concrete_context is None else concrete_context
    ctx_rebar = bool(_REBAR_CTX.search(low))
    out: list[tuple[int, str, str, float]] = []
    for m in _B.finditer(flat):
        v = _num(m.group(1))
        tail = flat[m.end() : m.end() + 16]
        marked = bool(re.match(r"\s?[,;]?\s?(?:П\d|F|W)", tail))
        if v in CONCRETE_CLASSES and (ctx_concrete or marked) and (" " not in m.group(0) or ctx_concrete):
            out.append((m.start(), "concrete_class", _fmt_b(v), v))
    if ctx_concrete or re.search(r"[BВ]\s?\d", flat):
        for m in _F.finditer(flat):
            v = int(m.group(1))
            if v in FROST_MARKS:
                out.append((m.start(), "concrete_frost", f"F{v}", float(v)))
        for m in _W.finditer(flat):
            v = int(m.group(1))
            if v in WATER_MARKS:
                out.append((m.start(), "concrete_water", f"W{v}", float(v)))
    for m in _A.finditer(flat):
        v = int(m.group(1))
        if ctx_rebar or m.group(2):
            out.append((m.start(), "rebar_class", f"A{v}" + ("С" if m.group(2) else ""), float(v)))
    if ctx_rebar:
        for m in _A_OLD.finditer(flat):
            v = REBAR_ROMAN[m.group(1)]
            out.append((m.start(), "rebar_class", f"A-{m.group(1)}", float(v)))
    for m in _THICK.finditer(low):
        nums = [m.group(1), *re.findall(r"\d{2,4}", m.group(2) or "")]
        for n in nums:
            v = int(n)
            if 50 <= v <= 3000:
                out.append((m.start(), "thickness", str(v), float(v)))
    return sorted(out)


def split_clauses(text: str) -> list[str]:
    flat = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    flat = re.sub(r"-\n(?=[а-яё])", "", flat)  # soft hyphen at a line end
    flat = flat.replace("\n", " ")
    return [c.strip() for c in _CLAUSE_SPLIT.split(flat) if c and c.strip()]


# how far a family mention may be from the value it binds (folded characters)
NEAR_BEFORE = 160
NEAR_AFTER = 60
THICK_BEFORE = 80
NO_REBAR = {"Бетонная подготовка"}


def _bind(mentions: list[tuple[int, str, bool]], pos: int, kind: str) -> str | None:
    """The family a value at ``pos`` binds to: the nearest mention before it (within reach), else the first one
    shortly after it; an excluded mention («кроме …») binds nothing."""
    reach = THICK_BEFORE if kind == "thickness" else NEAR_BEFORE
    before = [m for m in mentions if m[0] <= pos and pos - m[0] <= reach]
    if before:
        last = before[-1]
        return None if last[2] else last[1]
    after = [m for m in mentions if pos < m[0] <= pos + NEAR_AFTER]
    if after:
        first = after[0]
        return None if first[2] else first[1]
    return None


def facts_from_text(text: str) -> list[MaterialFact]:
    """Family-bound facts of one page of prose (PD/RD). Values without a family are dropped."""
    out: list[MaterialFact] = []
    prev_family: str | None = None
    seen: set[tuple[str, str, str]] = set()
    for clause in split_clauses(text):
        vals = values_in(clause)
        mentions = family_mentions(clause)
        usable = [m for m in mentions if not m[2]]
        for pos, kind, disp, rank in vals:
            fam = _bind(mentions, pos, kind)
            inherited = False
            if (
                fam is None
                and not mentions
                and prev_family is not None
                and kind != "thickness"
                and len(clause) < 300
            ):
                fam, inherited = prev_family, True
            if fam is None:
                continue
            if kind == "thickness" and fam not in THICKNESS_PARAM:
                continue
            if kind == "rebar_class" and fam in NO_REBAR:
                continue
            key = (kind, fam, disp)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                MaterialFact(kind, fam, disp, rank, clause[:300], 0.65 if inherited else 0.85, inherited)
            )
        if usable:
            prev_family = usable[-1][1]
        elif mentions:
            prev_family = None
    return out


def facts_from_act(work_name: str, materials: str, act_no: str | None = None) -> list[MaterialFact]:
    """Facts of one АОСР: family from п.1, classes/marks from п.3 (concrete context implied by the act)."""
    fam = family_of(work_name or "")
    if fam is None or not materials:
        return []
    out: list[MaterialFact] = []
    seen: set[tuple[str, str]] = set()
    for _, kind, disp, rank in values_in(
        materials, concrete_context=bool(_CONCRETE_CTX.search(fold(materials)))
    ):
        if kind == "thickness" or (kind, disp) in seen:
            continue
        seen.add((kind, disp))
        out.append(MaterialFact(kind, fam, disp, rank, (materials or "")[:300], 0.8, False, act_no))
    if fam == "Колонны":  # KR-062: executed longitudinal diameters of a column reinforcement act
        for _, kind, disp, rank in column_dia_in(materials):
            if (kind, disp) not in seen:
                seen.add((kind, disp))
                out.append(MaterialFact(kind, fam, disp, rank, (materials or "")[:300], 0.75, False, act_no))
    return out


_ACT_HEAD = re.compile(r"освидетельствовани\w*\s+скрыт|скрытых\s+работ", re.I)
_WORKS = re.compile(r"следующие\s+работ\w*\s*:?\s*(.{0,300})", re.I | re.S)


def act_family(text: str, work_name: str | None) -> str | None:
    """Element family of an АОСР: from п.1 when the act parsed, else from the words after «следующие работы»."""
    if work_name:
        return family_of(work_name)
    m = _WORKS.search(text or "")
    return family_of(m.group(1)) if m else None


def is_act_page(text: str) -> bool:
    return bool(_ACT_HEAD.search(text or ""))


# --- KR-056 steel grade, KR-060 column section, KR-062 column rebar diameter --------------------------------------
# Steel families are their own list: a steel clause names trusses, beams, stairs, … which the concrete families
# do not know, and adding them there would change the concrete/rebar binding.
STEEL_FAMILIES: tuple[tuple[str, str], ...] = (
    ("Фермы", r"\bферм"),
    ("Колонны", r"колонн|пилон"),
    ("Балки", r"\bбалк|ригел"),
    ("Связи", r"\bсвяз"),
    ("Лестницы", r"лестниц|лестничн"),
)
_STEEL_FAMILY_RX = [(label, re.compile(p)) for label, p in STEEL_FAMILIES]
GENERIC_STEEL = "Стальные конструкции"
# GOST 27772 grades (yield strength, MPa) — the printed number is the ordinal rank
STEEL_GRADES = {235, 245, 255, 275, 285, 345, 355, 375, 390, 440, 550, 590}
_STEEL = re.compile(
    r"(?<![А-ЯЁа-яёA-Za-z\d])[СC]\s?(235|245|255|275|285|345|355|375|390|440|550|590)(?:\s?[-–]?\s?[1-6]|К)?(?![\d.,]\d|\d)"
)
_STEEL_CTX = re.compile(
    r"стал[ьи]|стальн|металлоконструкц|металлопрокат|прокат|27772|гост\s+103\b|гост\s+19903"
)
_SHAPE_BEFORE = re.compile(
    r"(?:двутавр|швеллер|уголок|труба|пластина|лист|полоса|\bбалка|колонна)[^;]{0,40}$"
)
_STEEL_REACH = 90

_COL_NOUN = r"(?:колонн\w*|пилон\w*)"
_MARK = r"(?<![А-ЯЁа-яёA-Za-z\d])(?:Кн|Пн|Пл|Кл|К)\s?-?\d{1,3}(?![\d.,]|\s?[xх×])"
# b×h: not part of a longer chain («360х490х20» is a plate, not a section) and not a decimal
_DIMS = r"(?<![\d.,xх×])(\d{3,4})\s*[xх×]\s*(\d{3,4})(?!\d|[.,]\d|\s?[xх×]\s?\d)"
_COL_MARK_SECTION = re.compile(rf"({_MARK})([^\n;]{{0,30}}?){_DIMS}")
# «колонны сечением 400х400», «колонна – 400х400»: the size follows the noun directly or after «сечение/размер»
_COL_NOUN_SECTION = re.compile(
    rf"{_COL_NOUN}((?:\s+[а-яёА-ЯЁ]+){{0,3}}?\s*(?:сечени\w*|размер\w*|[-–:])\s*(?:\w{{1,3}}\s+)?){_DIMS}",
    re.I,
)
# a rolled shape / plate between the mark and the size means the size belongs to that part, not to the column
_NOT_SECTION = re.compile(r"пластин|лист|плит|прокат|уголок|труб|база|базе|швеллер|двутавр", re.I)
_COL_MARK_ANY = re.compile(_MARK)
_COL_DIA = re.compile(
    r"(?:[Ø⌀ø∅Ф]\s?|(?<![\d.,]))(6|8|10|12|14|16|18|20|22|25|28|32|36|40)\s?[АA]\s?(240|400|500\s?[СC]?|600)(?!\d)"
)
_LONGITUDINAL = re.compile(r"продольн|рабоч|вертикальн|основн\w*\s+арматур")
_TRANSVERSE = re.compile(r"хомут|поперечн|шаг|спирал")
_COL_ANCHOR = re.compile(_COL_NOUN)


def _col_mark(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw)


def steel_family_mentions(clause: str) -> list[tuple[int, str, bool]]:
    low = fold(clause)
    out: list[tuple[int, str, bool]] = []
    for label, rx in _STEEL_FAMILY_RX:
        for m in rx.finditer(low):
            out.append((m.start(), label, bool(_EXCLUDE.search(low[: m.start()]))))
    return sorted(out)


def steel_in(clause: str) -> list[tuple[int, str, str, float]]:
    """Steel grades of one clause that sit in a steel context (a steel word in the clause, or a rolled shape
    right before the value); «С 245» inside «сп 245» / distances / dimensions never qualifies."""
    flat = re.sub(r"\s+", " ", clause or "")
    low = fold(flat)
    ctx = bool(_STEEL_CTX.search(low))
    out: list[tuple[int, str, str, float]] = []
    for m in _STEEL.finditer(flat):
        if flat[m.end() : m.end() + 3].strip().lower().startswith(("мм", "м ", "шт", "кг")):
            continue
        if not ctx and not _SHAPE_BEFORE.search(low[max(0, m.start() - 60) : m.start()]):
            continue
        v = int(m.group(1))
        out.append((len(fold(flat[: m.start()])), "steel_grade", f"С{v}", float(v)))
    return out


def _bind_steel(mentions: list[tuple[int, str, bool]], pos: int, ctx_generic: bool) -> str | None:
    before = [m for m in mentions if m[0] <= pos and pos - m[0] <= _STEEL_REACH]
    if before:
        return None if before[-1][2] else before[-1][1]
    return GENERIC_STEEL if ctx_generic and not mentions else None


def column_sections_in(clause: str) -> list[tuple[str, str, float]]:
    """(location, display «500×600», area mm²) of every column section of one clause: bound to the column mark
    printed right before the size («К1 … 500х600»), else to «колонны» in general (a noun within 40 chars). A size
    that is neither is a stray dimension and never returned."""
    flat = re.sub(r"\s+", " ", clause or "")
    out: list[tuple[str, str, float]] = []
    taken: list[tuple[int, int]] = []

    def add(mark: str | None, b: str, h: str, span: tuple[int, int]) -> None:
        bi, hi = int(b), int(h)
        if not (150 <= bi <= 2500 and 150 <= hi <= 2500) or any(s <= span[0] < e for s, e in taken):
            return
        taken.append(span)
        out.append((f"Колонна {mark}" if mark else "Колонны", f"{bi}×{hi}", float(bi * hi)))

    for m in _COL_MARK_SECTION.finditer(flat):
        if _NOT_SECTION.search(m.group(2)):
            continue
        add(_col_mark(m.group(1)), m.group(3), m.group(4), m.span())
    for m in _COL_NOUN_SECTION.finditer(flat):
        if _NOT_SECTION.search(m.group(1)):
            continue
        add(None, m.group(2), m.group(3), m.span())
    return out


def column_dia_in(clause: str) -> list[tuple[int, str, str, float]]:
    """Longitudinal (working) rebar diameters of a clause: Ø + diameter + class. Stirrups (Ø8 А240, «шаг»,
    «хомуты») never count: a diameter is taken when the clause says «продольная/рабочая», or is ≥ 12 mm of
    class A400+ and the clause is not about stirrups."""
    flat = re.sub(r"\s+", " ", clause or "")
    low = fold(flat)
    longi = bool(_LONGITUDINAL.search(low))
    out: list[tuple[int, str, str, float]] = []
    for m in _COL_DIA.finditer(flat):
        d, cls = int(m.group(1)), re.sub(r"\s", "", m.group(2))
        tail = low[m.end() : m.end() + 12]
        if re.match(r"\s*(?:шаг|\()", tail) and not longi:
            continue
        working = longi or (d >= 12 and cls != "240")
        if (
            not working
            or (cls == "240" and not longi)
            or _TRANSVERSE.search(low[max(0, m.start() - 25) : m.start()])
        ):
            continue
        out.append((len(fold(flat[: m.start()])), "column_rebar_dia", f"Ø{d}", float(d)))
    return out


def facts_from_kr_text(text: str) -> list[MaterialFact]:
    """KR-056/060/062 facts of one page of PD/RD prose (steel grade per steel family, column section per column
    mark, longitudinal column rebar diameter)."""
    out: list[MaterialFact] = []
    seen: set[tuple[str, str, str]] = set()

    def keep(kind: str, fam: str, disp: str, rank: float, clause: str, conf: float) -> None:
        if (kind, fam, disp) in seen:
            return
        seen.add((kind, fam, disp))
        out.append(MaterialFact(kind, fam, disp, rank, clause[:300], conf))

    for clause in split_clauses(text):
        low = fold(clause)
        steel = steel_in(clause)
        if steel:
            mentions = steel_family_mentions(clause)
            generic = bool(_STEEL_CTX.search(low))
            for pos, kind, disp, rank in steel:
                fam = _bind_steel(mentions, pos, generic)
                if fam is not None:
                    keep(kind, fam, disp, rank, clause, 0.8)
        if _COL_ANCHOR.search(low) or _COL_MARK_ANY.search(clause):
            for loc, disp, area in column_sections_in(clause):
                keep("column_section", loc, disp, area, clause, 0.85 if loc != "Колонны" else 0.75)
        if _COL_ANCHOR.search(low):
            mentions = family_mentions(clause)
            for pos, kind, disp, rank in column_dia_in(clause):
                if _bind(mentions, pos, kind) == "Колонны":
                    keep(kind, "Колонны", disp, rank, clause, 0.8)
    return out


HINT = re.compile(r"бетон|арматур|толщин|стал[ьи]|прокат|колонн|пилон|27772")
_STRUCT_ABBR = re.compile(r"(?<![А-ЯЁA-Z])(?:КР|КЖ|КМ|КМД|КЖИ|СВГ)(?![а-яё])")
_STRUCT_WORD = re.compile(r"конструктив|ограждени\w*\s+котлован|стена\s+в\s+грунте|фундамент", re.I)


def is_structural(relative_path: str) -> bool:
    """A PD/RD file of the structural section by its name (КР, КЖ, КМ, СВГ, «конструктивные решения», …)."""
    name = (relative_path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return bool(_STRUCT_ABBR.search(name) or _STRUCT_WORD.search(name))


ID_HINT = re.compile(
    r"бетон|\bБСТ\b|[BВ]\s?\d{1,2}(?:[.,]5)?\s?П\d|F\s?\(\s?I|\bW\s?\d|арматур|[AА]\s?(?:240|400|500)\s?[СC]",
    re.I,
)


def facts_from_id_page(text: str, family: str, act_no: str | None = None) -> list[MaterialFact]:
    """Facts of one ИД page (act п.3, registry rows, passports) bound to the element family of the current act. A
    value whose clause names another family (an RD sheet copied into the binder, «плита B30, стены B25») is that
    family's, not the act's: it is skipped rather than misattributed."""
    out: list[MaterialFact] = []
    seen: set[tuple[str, str]] = set()
    for clause in split_clauses(text):
        mentions = family_mentions(clause)
        for pos, kind, disp, rank in values_in(clause):
            if kind == "thickness" or (kind, disp) in seen:
                continue
            if kind == "rebar_class" and family in NO_REBAR:
                continue
            bound = _bind(mentions, pos, kind)
            if bound is not None and bound != family:
                continue
            if bound is None and any(m[1] != family for m in mentions if not m[2]):
                continue
            seen.add((kind, disp))
            out.append(MaterialFact(kind, family, disp, rank, clause[:300], 0.75, False, act_no))
        if family == "Колонны":
            for _, kind, disp, rank in column_dia_in(clause):
                if (kind, disp) not in seen:
                    seen.add((kind, disp))
                    out.append(MaterialFact(kind, family, disp, rank, clause[:300], 0.7, False, act_no))
    return out
