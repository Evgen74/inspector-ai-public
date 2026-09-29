"""Energy-efficiency facts from prose (ПД «Мероприятия по энергоэффективности», АР/КР general data and build-ups):
building energy class (ZU-124), insulation thickness of walls (ZU-125) and roofs (ZU-128), thermal conductivity λ of
the insulation (ZU-126) and the reduced heat-transfer resistance Ro of windows (ZU-127).

Conservative by construction (a wrong finding costs more than a missed one):

* every fact is a *labelled* value: the class follows «класс энергетической эффективности», λ follows «λ =», a
  thickness sits next to an insulation noun («утеплитель», «минеральная вата», «XPS», …) or beside a printed
  λ ≤ 0,06 (an insulating layer, never the gas-concrete or the reinforced-concrete layer of the same section);
* a thickness is bound to a wall or a roof by the *last* marker before it («Кровля», «Пароизоляция», «наружные
  стены», «сэндвич-панель», …); no marker within reach → the value is dropped;
* every fact carries the insulation *material group* as its location, so PD and RD are compared only within one
  material («Пенополистирол (XPS/EPS)» to itself), never a wall panel against a plinth board;
* the passport row of Ro/окон with two numbers (normative + design) is skipped — which column is which is unknown.

Nothing here decides a violation: facts go to ``values/<object>.jsonl`` (fact keys ``ee.*``); the generic value
comparator of AG-04 (PAIRWISE_DELTA / ORDINAL_COMPARE / LAYER_STACK) reads them per catalog parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PARSER_VERSION = "energy-1"

# Ordinal scale ENERGY_CLASS (приказ Минстроя № 399/пр): a higher rank is a better class.
CLASS_RANK: dict[str, float] = {
    "A++": 10, "A+": 9, "A": 8, "B+": 7, "B": 6, "C+": 5, "C": 4, "C-": 3, "D": 2, "E": 1,
}  # fmt: skip
_CYR2LAT = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "Д": "D"})

# fact kind → (fact key, catalog param code, unit)
KINDS: dict[str, tuple[str, str, str | None]] = {
    "class": ("ee.class", "ZU-124", None),
    "wall_thickness": ("ee.wall_insulation_thickness", "ZU-125", "мм"),
    "lambda": ("ee.insulation_lambda", "ZU-126", "Вт/(м·°С)"),
    "window_ro": ("ee.window_ro", "ZU-127", "м²·°С/Вт"),
    "roof_thickness": ("ee.roof_insulation_thickness", "ZU-128", "мм"),
}

HINT = re.compile(
    r"класс\w*\s+энерг|утеплител|минерал\w*\s*ват|минераловат|стекловат|пенополист|пенополистер|теплоизоляц|"
    r"теплопроводн|λ|\bxps\b|\beps\b|\bpir\b|сэндвич|сопротивлени\w*\s+теплопередач|\bR\s?[оo0]\b",
    re.I,
)

_ENVELOPE_SRC = re.compile(
    r"энергетическ\w*\s+эффективност|(?<![а-яa-z])ээ(?![а-яa-z])|архитектурн|(?<![а-яa-z])(?:ар|ac)\d*(?![а-яa-z])|"
    r"конструктивн|(?<![а-яa-z])(?:кр|кж)\d*(?![а-яa-z])|(?<![а-яa-z])п[-_ ]ар(?![а-яa-z])",
    re.I,
)


def is_envelope_source(relative_path: str) -> bool:
    """A PD/RD file that can carry wall/roof build-ups: ЭЭ, АР or КР by its name or folder."""
    return bool(
        _ENVELOPE_SRC.search((relative_path or "").replace("\\", "/").replace("ё", "е").replace("Ё", "Е"))
    )


@dataclass(slots=True)
class EnergyFact:
    kind: str
    value: float | str  # number (мм, Вт/(м·°С), м²·°С/Вт) or the class letter
    raw: str  # printed form: «B+», «100+50», «0.041»
    rank: float
    material: str | None  # location: insulation material group (thickness, λ); None for the class / Ro
    clause: str
    confidence: float
    detail: str | None = None  # printed condition («λБ»), layer sum, …
    ctx_at: int | None = (
        None  # non-space characters of ``clause`` before the value (which «С» of the clause it is)
    )

    @property
    def param_code(self) -> str:
        return KINDS[self.kind][1]


def _flat(text: str) -> str:
    """Page text with one layer/sentence per line: a line that continues a wrapped one (starts with a lower-case
    letter or λ/δ) is joined to it; other newlines stay, so a thickness is looked for on the line of its noun."""
    t = (text or "").replace("ё", "е").replace("Ё", "Е")
    t = re.sub(r"-\n(?=[а-я])", "", t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n(?=\s*[a-zа-яλδ])", " ", t)
    return re.sub(r"\n\s*", "\n", t)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _clause(flat: str, start: int, end: int) -> str:
    return re.sub(r"\s+", " ", flat[max(0, start - 60) : min(len(flat), end + 60)]).strip()


# ── class ─────────────────────────────────────────────────────────────────────────────────────────

_CLASS = re.compile(
    r"(?i:класс\w*\s+(?:энергетическ\w*\s+эффективности|энергосбережения)\s*(?:здания\s*)?"
    r"(?:(?:присвоен\w*|присваивается|определен\w*|принят\w*|установлен\w*)\s*)?[-–—:=]{0,2}\s*)"
    r"[«\"“]?\s*(?P<v>[AА]\+\+|[AА]\+|[BВ]\+|[CС][+-]|[A-EАВСДЕ])[»\"”]?"
    r"(?=\s*(?:[(),.;:]|\d|$|(?i:нормальн|высок|очень|понижен|низк|повышен)))"
)


def class_facts(flat: str) -> list[EnergyFact]:
    out: list[EnergyFact] = []
    for m in _CLASS.finditer(flat):
        letter = m.group("v").translate(_CYR2LAT)
        rank = CLASS_RANK.get(letter)
        if rank is None:
            continue
        at = sum(1 for ch in flat[max(0, m.start() - 60) : m.start("v")] if not ch.isspace())
        out.append(
            EnergyFact(
                "class", letter, m.group("v"), rank, None, _clause(flat, m.start(), m.end()), 0.85, ctx_at=at
            )
        )
    return out


# ── insulation material, wall/roof context ────────────────────────────────────────────────────────

_MATERIAL: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Пенополистирол (XPS/EPS)", re.compile(r"пенополистир|пенополистер|пеноплэкс|penoplex|(?<![a-zа-я])(?:xps|eps|epps)(?![a-zа-я])|carbon\s+(?:prof|eco)")),
    ("PIR", re.compile(r"(?<![a-zа-я])(?:pir|пир)(?![a-zа-я])|полиизоцианурат")),
    ("Минеральная вата / сэндвич-панель", re.compile(r"минерал\w*\s*ват|минераловат|минеральн\w*\s+стекловат|стекловат|базальтов|каменн\w*\s+ват|сэндвич|rockwool|isover|knauf")),
)  # fmt: skip
GENERIC_MATERIAL = "Утеплитель (материал не указан)"
_ROOF = re.compile(r"кровл|покрыти|пароизоляц|кровельн|чердач|контруклон|клинь|парапет")
_WALL = re.compile(r"наружн\w*\s+стен|стеновой|стеновая|стеновы|сэндвич|фасад|цоколь|навесн")
_NOUN = re.compile(
    r"утеплител\w*|минерал\w*\s*ват\w*|минераловат\w*|стекловат\w*|пенополистир\w*|пенополистер\w*|теплоизоляц\w*|"
    r"(?<![a-zа-я])(?:xps|eps|pir|epps)(?![a-zа-я])"
)
_THK = re.compile(r"(?<![\d.,])(\d{2,3}(?:\s*\+\s*\d{2,3})*)\s*мм")
_DELTA = re.compile(
    r"δ\s*\d?\s*=\s*(0[.,]\d{1,3})\s*м(?![а-яa-z])(?P<tail>[^;\n]{0,110}?)λ\S{0,4}\s*=\s*(0[.,]0\d{1,3})"
)
_DIM = re.compile(
    r"[аahlbв]\s*=\s*$"
)  # «А=310 мм», «h=150 мм»: a fitting/section dimension, not a layer thickness
_SKIP_BEFORE = re.compile(r"огнезащит|контруклон|штукатурн|клеев|крепеж|дюбел|саморез|пленк|мембран")


def _last(rx: re.Pattern[str], low: str, lo: int, hi: int) -> int:
    pos = -1
    for m in rx.finditer(low, lo, hi):
        pos = m.start()
    return pos


def material_of(low: str, pos: int, reach: int = 140) -> str:
    """Insulation material group named last within ``reach`` characters before ``pos`` (or just after it)."""
    best, best_pos = GENERIC_MATERIAL, -1
    lo = max(0, pos - reach)
    for label, rx in _MATERIAL:
        p = _last(rx, low, lo, min(len(low), pos + 24))
        if p > best_pos:
            best, best_pos = label, p
    return best


def element_of(low: str, pos: int, end: int) -> str | None:
    """«wall» or «roof»: the last marker in the 500 characters up to the end of the match; None when no marker."""
    lo = max(0, pos - 500)
    roof, wall = _last(_ROOF, low, lo, end), _last(_WALL, low, lo, end)
    if roof < 0 and wall < 0:
        return None
    return "roof" if roof > wall else "wall"


def thickness_facts(flat: str) -> list[EnergyFact]:
    low = flat.lower()
    if len(low) != len(flat):  # a case fold that changed the length breaks offsets: give up on this page
        return []
    out: list[EnergyFact] = []
    seen: set[tuple[str, str, float]] = set()

    def add(pos: int, end: int, total: float, raw: str, detail: str | None) -> None:
        if not 30 <= total <= 600:
            return
        element = element_of(low, pos, end)
        if element is None:
            return
        kind = f"{element}_thickness"
        material = material_of(low, pos)
        key = (kind, material, total)
        if key in seen:
            return
        seen.add(key)
        out.append(EnergyFact(kind, total, raw, total, material, _clause(flat, pos, end), 0.8, detail))

    for m in _NOUN.finditer(low):
        if _SKIP_BEFORE.search(low[max(0, m.start() - 45) : m.start() + 1]):
            continue
        eol = low.find("\n", m.end())
        t = _THK.search(low, m.end(), min(len(low), m.end() + 110, eol if eol >= 0 else len(low)))
        if (
            t is None
            or ";" in low[m.end() : t.start()]
            or _DIM.search(low[max(0, t.start() - 4) : t.start()])
        ):
            continue
        parts = [int(p) for p in re.findall(r"\d+", t.group(1))]
        add(
            m.start(),
            t.end(),
            float(sum(parts)),
            t.group(1).replace(" ", ""),
            "sum" if len(parts) > 1 else None,
        )
    for m in _DELTA.finditer(low):
        if _num(m.group(3)) > 0.06:
            continue
        add(m.start(), m.end(), round(_num(m.group(1)) * 1000, 1), m.group(1), "δ, м")
    return out


# ── λ of the insulation ───────────────────────────────────────────────────────────────────────────

_LAMBDA = re.compile(
    r"λ\s*(?P<cond>[а-яa-z]?\d?)\s*=\s*(?P<v>0[.,]0\d{1,3})(?!\d)|теплопроводност\w*[^\d;]{0,25}?(?P<v2>0[.,]0\d{1,3})(?!\d)"
)


def lambda_facts(flat: str) -> list[EnergyFact]:
    low = flat.lower()
    if len(low) != len(flat):
        return []
    out: list[EnergyFact] = []
    seen: set[tuple[str, float]] = set()
    for m in _LAMBDA.finditer(low):
        raw = m.group("v") or m.group("v2")
        v = _num(raw)
        if not 0.015 <= v <= 0.06:  # an insulating layer, not concrete/brick/gas-concrete
            continue
        material = material_of(low, m.start(), 160)
        if (material, v) in seen:
            continue
        seen.add((material, v))
        cond = (m.group("cond") or "").strip() or None
        out.append(EnergyFact("lambda", v, raw, v, material, _clause(flat, m.start(), m.end()), 0.8, cond))
    return out


# ── Ro of windows ─────────────────────────────────────────────────────────────────────────────────

_WIN = r"(?:окон\w*|светопрозрачн\w*|остеклен\w*|витраж\w*|оконн\w*)"
_RO = r"(?:r\s*[оo0]\s*[,.]?\s*(?:ок|окон)?\w{0,3}|r\s*пр\b|сопротивлени\w*\s+теплопередач\w*)"
_RO_TEXT = re.compile(_WIN + r"[^;\n]{0,90}?" + _RO + r"[^\d;\n]{0,25}?(?P<v>\d[.,]\d{1,3})(?![\d.,])")
_RO_LABEL = re.compile(r"r\s*[оo0]\s*,\s*ок\s*\d?\s*(?P<nums>(?:\d[.,]\d{1,3}\s*){1,3})")
_NORMATIVE = re.compile(r"нормируем|требуем|не\s+менее|не\s+ниже|минимальн|норматив")


def window_ro_facts(flat: str) -> list[EnergyFact]:
    low = flat.lower()
    if len(low) != len(flat):
        return []
    out: list[EnergyFact] = []
    seen: set[float] = set()

    def add(m: re.Match[str], raw: str) -> None:
        v = _num(raw)
        if not 0.2 <= v <= 1.5 or v in seen:  # windows: Ro of 0,2…1,5 m²·°С/Вт
            return
        if _NORMATIVE.search(low[max(0, m.start() - 40) : m.end()]):
            return
        seen.add(v)
        out.append(EnergyFact("window_ro", v, raw, v, None, _clause(flat, m.start(), m.end()), 0.8))

    for m in _RO_TEXT.finditer(low):
        add(m, m.group("v"))
    for m in _RO_LABEL.finditer(low):
        nums = re.findall(r"\d[.,]\d{1,3}", m.group("nums"))
        if len(nums) == 1:  # a passport row with normative + design values is ambiguous: skipped
            add(m, nums[0])
    return out


# ── page entry point ──────────────────────────────────────────────────────────────────────────────


def facts_from_text(text: str, *, envelope: bool, thickness: bool = True) -> list[EnergyFact]:
    """Facts of one page of prose. ``envelope``: the file is a ЭЭ/АР/КР file (λ, Ro, thicknesses are read only there);
    the energy class is read from any PD/RD/ИД page. ``thickness`` False (ИД) skips wall/roof thicknesses."""
    flat = _flat(text)
    out = class_facts(flat)
    if envelope:
        out.extend(lambda_facts(flat))
        out.extend(window_ro_facts(flat))
        if thickness:
            out.extend(thickness_facts(flat))
    return out
