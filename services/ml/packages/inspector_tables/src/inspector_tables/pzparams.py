"""Object-level ПЗ parameters from prose and labelled lines (PZ-013…018, PZ-021…023).

Each parameter is a value printed next to its own label («Степень огнестойкости здания – II», «Рр = 462,5 кВт»,
«школа на 600 мест»); a stray number is never taken. The recognised label is the same as the catalog
``regex_pattern`` / ``semantic_anchors`` of the parameter (packages/contracts/seed/params.json), tightened where the
seed pattern would read a sub-system or another water/heat kind (an ordinary line of the document is not the
building's value).

Facts go to ``values/<object>.jsonl`` (fact key ``pz.value``, location OBJECT) and are compared by the generic value
comparator of AG-04 per the parameter's own ``comparison_rule``. Ordinal scales carry ``rank`` (higher = better, 02
§3.12.3), so a lower class at the later stage is a downgrade and a higher one an improvement (97 §2.10).

``resolve_ambiguity`` runs over the whole object: when one stage prints several different values for a parameter
(several buildings, several ТУ, several sub-systems) and none clearly dominates, none of them is compared.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

PARSER_VERSION = "pzparams-1"
FACT_KEY = "pz.value"

PZ_CODES = ("PZ-013", "PZ-014", "PZ-015", "PZ-016", "PZ-017", "PZ-018", "PZ-021", "PZ-022", "PZ-023")

# ordinal scales: value → rank (higher = better)
SCALES: dict[str, dict[str, float]] = {
    "PZ-015": {"особая группа I": 4, "I": 3, "II": 2, "III": 1},  # RELIABILITY_CATEGORY
    "PZ-021": {
        "A++": 10,
        "A+": 9,
        "A": 8,
        "B+": 7,
        "B": 6,
        "C+": 5,
        "C": 4,
        "C-": 3,
        "D": 2,
        "E": 1,
    },  # ENERGY_CLASS
    "PZ-022": {"I": 5, "II": 4, "III": 3, "IV": 2, "V": 1},  # FIRE_RESISTANCE_DEGREE
    "PZ-023": {"C0": 4, "C1": 3, "C2": 2, "C3": 1},  # CONSTRUCTIVE_FIRE_HAZARD_CLASS
}
SCALE_NAMES = {
    "PZ-015": "RELIABILITY_CATEGORY",
    "PZ-021": "ENERGY_CLASS",
    "PZ-022": "FIRE_RESISTANCE_DEGREE",
    "PZ-023": "CONSTRUCTIVE_FIRE_HAZARD_CLASS",
}
UNITS = {"PZ-014": "кВт", "PZ-016": "м³/сут", "PZ-017": "Гкал/ч", "PZ-018": "м³/ч"}

_NUM = r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_HINT = re.compile(
    r"огнестойкост|конструктивной пожарной|энерг\w* ?(?:эффективност|сбережен)|энергоэффективност|надежност|"
    r"расчетн|[рp]\s?[рp]\s*=|водопотреблен|расход\w* (?:природного )?(?:воды|газа)|газопотреблен|теплов\w* нагрузк|"
    r"теплопотреблен|вместимост|мощност|\bна \d+ (?:мест|учащ|обуч|дет|посещ|коек)",
    re.I,
)


@dataclass(slots=True)
class PzFact:
    code: str
    raw: str  # as printed («II», «462,5 кВт»)
    value: Any  # number or the canonical enum code
    vtype: str  # number | enum
    unit: str | None
    rank: float | None
    confidence: float
    context: str
    kind: str | None = None  # capacity kind, water kind …
    ctx_at: int | None = (
        None  # non-space characters of ``context`` before the value (which «С» of the context it is)
    )


# ── enum normalisers ──────────────────────────────────────────────────────────────────────────────

_I_LIKE = set("IlІΙ|")


def roman_degree(tok: str) -> str | None:
    """«II», «l» (OCR of I), «1-й», «IV», «5» → I…V; None when not a clean degree."""
    t = tok.strip().rstrip("-йи")
    if not t:
        return None
    if all(c in _I_LIKE for c in t) and len(t) <= 3:
        return "I" * len(t)
    if t in ("IV", "1V", "lV", "ІV", "IУ"):
        return "IV"
    if t in ("V", "V"):
        return "V"
    if re.fullmatch(r"[1-5]", t):
        return ("I", "II", "III", "IV", "V")[int(t) - 1]
    return None


def reliability_category(tok: str) -> str | None:
    t = tok.strip().lower().rstrip("-йи")
    words = {"первая": "I", "вторая": "II", "третья": "III", "первой": "I", "второй": "II", "третьей": "III"}
    if t in words:
        return words[t]
    if re.fullmatch(r"особая группа i", re.sub(r"\s+", " ", t)):
        return "особая группа I"
    if re.fullmatch(r"[1-3]", t):
        return ("I", "II", "III")[int(t) - 1]
    if re.fullmatch(r"[iіι]{1,3}", t):
        return "I" * len(t)
    return None


_CYR2LAT = str.maketrans({"А": "A", "В": "B", "С": "C", "Д": "D", "Е": "E", "а": "A", "в": "B", "с": "C"})


def energy_class(tok: str) -> str | None:
    t = re.sub(r"\s+", "", tok).translate(_CYR2LAT)
    t = t.replace("+", "+")
    return t if t in SCALES["PZ-021"] else None


def fire_hazard_class(tok: str) -> str | None:
    t = re.sub(r"\s+", "", tok)
    m = re.fullmatch(r"[СCсc]([0-3OОoо])", t)
    if not m:
        return None
    d = m.group(1)
    return "C" + ("0" if d in "OОoо" else d)


def normalize_enum(code: str, raw: str) -> tuple[str, float] | None:
    """(canonical value, rank) of a printed class/category/degree of one of the ordinal parameters."""
    fn = {
        "PZ-015": reliability_category,
        "PZ-021": energy_class,
        "PZ-022": roman_degree,
        "PZ-023": fire_hazard_class,
    }.get(code)
    if fn is None:
        return None
    v = fn(raw)
    if v is None:
        return None
    return v, SCALES[code][v]


# ── patterns ──────────────────────────────────────────────────────────────────────────────────────

_OBJ_WORDS = r"(?:здания|объекта|корпуса|сооружения|комплекса|проектируемого\s+здания|жилого\s+(?:дома|здания|комплекса)|школы)"
_SEP = r"\s*(?:[-–—:=]|принята|принимается|составляет|соответствует)?\s*"

_ROMAN_TOK = r"(?P<v>[IlІΙ|]{1,3}|[1I]V|IV|V|[1-5])"
_P22_LABEL = re.compile(rf"степен\w+\s+огнестойкости(?:\s+{_OBJ_WORDS})?{_SEP}{_ROMAN_TOK}(?![\w])", re.I)
_P22_VALUE = re.compile(
    r"(?<![\w-])(?P<v>[IlІΙ|]{1,3}|[1I]V|IV|V|[1-5])\s*(?:-?[йи]\s+)?степен\w+\s+огнестойкости", re.I
)
_P22_VALUE_PRE_BAD = re.compile(
    r"(?:для\s+(?:\w+\s+)?(?:здани\w+|объект\w+)|не\s+(?:ниже|менее|выше|более)|до|от)\s*$", re.I
)

_HZ = r"(?P<v>[СCсc]\s?[0-3OОoо])"
_P23_LABEL = re.compile(
    rf"класс\w*\s+конструктивной\s+пожарной\s+опасности(?:\s+{_OBJ_WORDS})?{_SEP}{_HZ}(?![\w])", re.I
)
_P23_VALUE = re.compile(rf"(?<![\w-]){_HZ}\s+(?:класс\w*\s+)?конструктивной\s+пожарной\s+опасности", re.I)

_EN = r"(?P<v>[AА]\s?\+\+|[AА]\s?\+|[BВ]\s?\+|[CС]\s?[+-]|[A-EАВСДЕ])"
_P21_LABEL = re.compile(
    rf"класс\w*\s+(?:энерг\w*\s+(?:эффективности|сбережения)|энергоэффективности|энергосбережения)(?:\s+{_OBJ_WORDS})?{_SEP}(?:[«\"]\s?)?(?-i:{_EN})(?![\w+-])",
    re.I,
)

_RC = r"(?P<v>I{1,3}|[1-3]|первая|вторая|третья|особая\s+групп\w+\s+I)"
_P15_LABEL = re.compile(
    rf"категори[яи]\s+(?:по\s+)?надежности\s+(?:электроснабжения|электропитания)(?:\s+\S+){{0,3}}?\s*(?:принята|составляет|[-–—:=])\s*[-–—:]?\s*{_RC}(?![\w])",
    re.I,
)
_P15_VALUE = re.compile(
    r"(?<![\w-])(?P<v>I{1,3}|[1-3])\s*(?:-?й\s+)?категори[яи]\s+(?:по\s+)?надежности\s+электроснабжения", re.I
)
_P15_PRE_BAD = re.compile(
    r"потребител|электроприемник|электроприемник|спз|систем|оборудован|относятся|нагрузк|отдельн|группу|группа|часть|насос|"
    r"кроме|исключени|противопожар|противодым|аупт|аппаратур|щит",
    re.I,
)

_P14 = re.compile(
    rf"(?:(?<![а-яa-z])[рp]\s?[рp](?:\s?(?:общ|расч|сумм)\.?)?\s*=|расчетн\w*\s+(?:электрическ\w*\s+)?(?:мощност\w*|нагрузк\w*)(?:\s+(?:объекта|здания|дома|комплекса|жилого\s+\w+))?)"
    rf"[^\d\n]{{0,25}}?(?<![\d.,])(?P<v>{_NUM})\s*(?P<u>[кМм]вт)(?![\wа-я·])",
    re.I,
)
_P16 = re.compile(
    rf"(?:водопотреблени\w*|расход\w*\s+воды)(?P<gap>[^\d\n]{{0,60}}?)(?<![\d.,])(?P<v>{_NUM})\s*(?:м\s?[³3]|куб\.?\s?м)\s*/\s*сут",
    re.I,
)
_P16_BAD = re.compile(
    r"пожаротуш|полив|горяч|гвс|канализ|водоотвед|сток|техническ|дожд|дренаж|производствен|охлажд|подпитк|на\s+одн",
    re.I,
)
_P17 = re.compile(
    rf"(?:тепловая\s+нагрузка|теплопотреблени\w*|(?<![a-z])Q\s*общ\.?)(?P<gap>[^\d\n]{{0,60}}?)(?<![\d.,])(?P<v>{_NUM})\s*(?P<u>гкал\s*/\s*ч(?:ас)?|квт|мвт)(?![\wа-я])",
    re.I,
)
_P17_BAD = re.compile(
    r"отоплен|вентиляц|гвс|горяч|технолог|кондиц|холод|теплоснабж|на\s+нужды|с\s+коэф", re.I
)
_P18 = re.compile(
    rf"(?:расход\w*\s+(?:природного\s+)?газа|газопотреблени\w*)(?P<gap>[^\d\n]{{0,60}}?)(?<![\d.,])(?P<v>{_NUM})\s*н?м\s?[³3]\s*/\s*(?:ч|час)(?![\wа-я])",
    re.I,
)
_P18_BAD = re.compile(r"на\s+одн|на\s+1\s|котел|горелк|плит|каждый|один\s", re.I)

_CAP_UNITS = r"(?P<u>мест|учащихся|обучающихся|детей|посещений(?:\s+в\s+смену)?|коек)(?![\wа-я])"
_P13_LABEL = re.compile(
    rf"(?:вместимост\w*|мощност\w*)\s+(?:(?:объекта|здания|учреждения|школы|детского\s+сада|образовательн\w+\s+\w+|комплекса)\s*)?(?:проектн\w+\s+)?(?:[-–—:]\s*|составляет\s+)?(?P<v>\d{{1,6}})\s*{_CAP_UNITS}",
    re.I,
)
_P13_NOUN = re.compile(
    rf"(?<![а-яa-z])(?:школ\w*|детск\w+\s+сад\w*|гимнази\w*|лице\w*|общеобразовательн\w+\s+\w+|поликлиник\w*|больниц\w*|учреждени\w+|доу|сош)"
    rf"(?:\s+\S+){{0,4}}?\s+на\s+(?P<v>\d{{1,6}})\s*{_CAP_UNITS}",
    re.I,
)
_P13_PRE_BAD = re.compile(r"автостоянк|парковк|паркинг|машино|гараж|лифт|переодеван|раздевал|шкаф", re.I)


def normalize_text(text: str) -> str:
    """One line: NBSP/newlines → space, «ё» → «е», word-break hyphens joined («электро- снабжения»)."""
    t = text.replace(" ", " ").replace(" ", " ").replace("ё", "е").replace("Ё", "Е")
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(?<=[а-я])- (?=[а-я])", "", t)
    return t


def _num(raw: str) -> float | None:
    s = raw.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _ctx(t: str, m: re.Match[str]) -> str:
    return t[max(0, m.start() - 40) : min(len(t), m.end() + 60)].strip()


def ctx_at(t: str, ctx_start: int, value_start: int) -> int:
    """Non-space characters between the context start and the value: stable under strip and whitespace collapsing."""
    return sum(1 for ch in t[ctx_start:value_start] if not ch.isspace())


def _enum_fact(code: str, m: re.Match[str], t: str, conf: float) -> PzFact | None:
    got = normalize_enum(code, m.group("v"))
    if got is None:
        return None
    v = m.group("v")
    at = ctx_at(t, max(0, m.start() - 40), m.start("v") + len(v) - len(v.lstrip()))
    return PzFact(code, v.strip(), got[0], "enum", None, got[1], conf, _ctx(t, m), ctx_at=at)


def extract(text: str) -> list[PzFact]:
    """Every labelled ПЗ parameter value of one page's text (deduplicated per page)."""
    t = normalize_text(text)
    if not _HINT.search(t):
        return []
    out: list[PzFact] = []

    def add(f: PzFact | None) -> None:
        if f is not None and not any(
            o.code == f.code and o.value == f.value and o.unit == f.unit for o in out
        ):
            out.append(f)

    for m in _P22_LABEL.finditer(t):
        add(_enum_fact("PZ-022", m, t, 0.9))
    for m in _P22_VALUE.finditer(t):
        if not _pre_bad_22(t, m):
            add(_enum_fact("PZ-022", m, t, 0.85))
    for m in _P23_LABEL.finditer(t):
        add(_enum_fact("PZ-023", m, t, 0.9))
    for m in _P23_VALUE.finditer(t):
        add(_enum_fact("PZ-023", m, t, 0.85))
    for m in _P21_LABEL.finditer(t):
        add(_enum_fact("PZ-021", m, t, 0.9))
    for m in _P15_LABEL.finditer(t):
        add(_enum_fact("PZ-015", m, t, 0.85))
    for m in _P15_VALUE.finditer(t):
        if not _P15_PRE_BAD.search(t[max(0, m.start() - 60) : m.start()]):
            add(_enum_fact("PZ-015", m, t, 0.75))
    for m in _P14.finditer(t):
        v = _num(m.group("v"))
        if v is None:
            continue
        mult = 1000.0 if m.group("u").lower().startswith("м") else 1.0
        add(
            PzFact(
                "PZ-014",
                f"{m.group('v')} {m.group('u')}",
                round(v * mult, 6),
                "number",
                "кВт",
                None,
                0.85,
                _ctx(t, m),
            )
        )
    for m in _P16.finditer(t):
        v = _num(m.group("v"))
        if v is not None and not _P16_BAD.search(m.group("gap")):
            add(PzFact("PZ-016", f"{m.group('v')} м³/сут", v, "number", "м³/сут", None, 0.85, _ctx(t, m)))
    for m in _P17.finditer(t):
        v = _num(m.group("v"))
        if v is None or _P17_BAD.search(m.group("gap")):
            continue
        u = m.group("u").lower()
        unit, mult = (
            ("Гкал/ч", 1.0) if u.startswith("гкал") else (("кВт", 1.0) if u == "квт" else ("кВт", 1000.0))
        )
        add(
            PzFact(
                "PZ-017",
                f"{m.group('v')} {m.group('u')}",
                round(v * mult, 6),
                "number",
                unit,
                None,
                0.85,
                _ctx(t, m),
            )
        )
    for m in _P18.finditer(t):
        v = _num(m.group("v"))
        if v is not None and not _P18_BAD.search(m.group("gap")):
            add(PzFact("PZ-018", f"{m.group('v')} м³/ч", v, "number", "м³/ч", None, 0.85, _ctx(t, m)))
    for rx, conf in ((_P13_LABEL, 0.85), (_P13_NOUN, 0.8)):
        for m in rx.finditer(t):
            if _P13_PRE_BAD.search(t[max(0, m.start() - 60) : m.start()]):
                continue
            add(PzFact("PZ-013", f"{m.group('v')} {m.group('u')}", float(m.group("v")), "number", None, None, conf,
                       _ctx(t, m), kind=m.group("u").split()[0].lower()))  # fmt: skip
    return out


def _pre_bad_22(t: str, m: re.Match[str]) -> bool:
    return bool(_P22_VALUE_PRE_BAD.search(t[max(0, m.start() - 30) : m.start()]))


# ── ambiguity over the whole object ───────────────────────────────────────────────────────────────


def _key(v: dict[str, Any]) -> tuple[Any, Any]:
    n = v["value_norm"]
    return (n.get("value"), n.get("unit"))


def resolve_ambiguity(values: list[dict[str, Any]]) -> dict[str, int]:
    """Mark every ``pz.value`` of a (parameter, stage) that prints several different values as ambiguous unless one
    value dominates (mentioned ≥ 3 times and ≥ 2× the runner-up); the dominating value stays comparable and the rest
    are set aside. Conservative on purpose: no finding beats a false one (AbstainReason AMBIGUOUS_VALUE)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for v in values:
        if (
            v.get("fact_key") in (FACT_KEY, "tep.value")
            and v.get("param_code") in PZ_CODES
            and (v["value_norm"].get("qualifiers") or {}).get("basis") != "ГПЗУ"
        ):
            groups[(v["param_code"], v["stage"])].append(v)
    stats = {"groups": len(groups), "ambiguous_groups": 0, "dominant_groups": 0, "agreed_groups": 0}
    by_param: dict[str, dict[str, set[tuple[Any, Any]]]] = defaultdict(lambda: defaultdict(set))
    for (code, stage), vs in groups.items():
        by_param[code][stage] = {_key(v) for v in vs}
    for (code, stage), vs in groups.items():
        counts = Counter(_key(v) for v in vs)
        if len(counts) == 1:
            continue
        ranked = counts.most_common()
        top, second = ranked[0][1], ranked[1][1]
        keep = ranked[0][0] if top >= 3 and top >= 2 * second else None
        # a reading that another stage prints too is the one both stages agree on: keeping it can only yield EQUAL
        others = set().union(*(k for s, k in by_param[code].items() if s != stage))
        agreed = {k for k in counts if k in others}
        if keep is None and agreed:
            stats["agreed_groups"] += 1
        else:
            stats["dominant_groups" if keep is not None else "ambiguous_groups"] += 1
        for v in vs:
            if keep is not None and _key(v) == keep:
                v["value_norm"].setdefault("qualifiers", {})["dominant_of"] = len(counts)
                continue
            if keep is None and _key(v) in agreed:
                v["value_norm"].setdefault("qualifiers", {})["agreed_across_stages"] = True
                continue
            v["is_ambiguous"] = True
            v["value_norm"].setdefault("qualifiers", {})["distinct_values"] = len(counts)
    return stats
