"""Fire-safety (ППМ) parameter values from labelled prose, equipment lists and drawing labels (PPM-102…114).

Each fact is a value printed next to its own label, bound to the element the parameter is keyed on (04 §3.5):

* PPM-102 — area of a fire compartment («площадь пожарного отсека № 2 – 2 400 м²»), location = the compartment;
* PPM-103 — EI limit of a fire door printed right after its mark («Д-6 EI30»), location = the door mark;
* PPM-104 / PPM-105 — a *design* width of an evacuation passage / of an outer exit door («ширина … – 1,2 м»); a
  normative bound («не менее 0,9 м») is never a design value;
* PPM-107 — class КМ of the finishing of a room group («для коридоров и холлов – КМ3»), location = surface + room group;
* PPM-109 — fire index of a СПЗ cable («ВВГнг(А)-FRLS 3х1,5»), location = cable family + section;
* PPM-111 — EI limit of fire dampers of a system («клапаны для систем ПД1, ВД1 приняты … EI60»), location = system tag;
* PPM-112 — air flow of a smoke-control system («ВД1 (L=13000 м3/ч, Pc=500 Па)»), location = system tag;
* PPM-113 — internal fire water: number of jets and flow per jet («2 струи по 2,6 л/с», «2 х 2,5 = 5 л/с»);
* PPM-114 — external fire-fighting flow («наружное пожаротушение – 110 л/с»), object level.

Nothing here decides a violation: facts go to ``values/<object>.jsonl`` (fact keys ``ppm.*``, catalog ``param_code``)
and the generic value comparator (PAIRWISE_DELTA / ORDINAL_COMPARE) evaluates them per the parameter's own rule.
Conservative by construction: a stray number is never taken, several tags sharing one value are bound only when the
printed grammar says so, and ``resolve_ambiguity`` drops every (parameter, element, stage) that prints several
different values without a clear winner (AbstainReason AMBIGUOUS_VALUE).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

PARSER_VERSION = "ppm-1"
PPM_CODES = (
    "PPM-102", "PPM-103", "PPM-104", "PPM-105", "PPM-107", "PPM-109", "PPM-111", "PPM-112", "PPM-113", "PPM-114",
)  # fmt: skip

# ordinal scales (higher = better): EI minutes; КМ0…КМ5; cable fire index (fire-resistant FR* over the rest)
KM_RANK = {f"КМ{n}": float(5 - n) for n in range(6)}
CABLE_RANK = {"FRLSLTx": 2.0, "FRLS": 2.0, "FRHF": 2.0, "LSLTx": 1.0, "LS": 1.0, "HF": 1.0, "LTx": 1.0}

HINT = re.compile(
    r"отсек|[EЕ][IІ]|КМ\s?\d|нг\(?[АA]?\)?[-‐–]|L\s?=|стру|наружн|ширин|пожаротуш|ВПВ|л\s?/\s?(?:с|сек)", re.I
)


@dataclass(slots=True)
class PpmFact:
    code: str
    kind: str  # fact-key suffix: compartment_area, door_ei, evac_width, exit_width, km, cable_index, damper_ei, …
    location: str | None  # printed element key; None = object level
    raw: str
    value: Any
    vtype: str  # number | enum
    unit: str | None
    rank: float | None
    confidence: float
    context: str

    @property
    def fact_key(self) -> str:
        return f"ppm.{self.kind}"


def normalize_text(text: str) -> str:
    """One line: NBSP/newlines → space, «ё» → «е», word-break hyphens joined («огне- стойкости»)."""
    t = (text or "").replace(" ", " ").replace(" ", " ").replace("ё", "е").replace("Ё", "Е")
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"(?<=[а-я])- (?=[а-я])", "", t)


def _num(raw: str) -> float | None:
    try:
        return float(raw.replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _ctx(t: str, m: re.Match[str]) -> str:
    return t[max(0, m.start() - 50) : min(len(t), m.end() + 60)].strip()


_LAT2CYR = str.maketrans({"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У"})  # fmt: skip
_CYR2LAT = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "І": "I", "Ѕ": "S"})  # fmt: skip


def norm_ei(raw: str) -> tuple[str, float] | None:
    """«EI 60», «EI-60», «ЕI60» (Cyrillic Е), «EIS 30» → («EI 60», 60.0); the class letter S/W/M is dropped."""
    t = re.sub(r"\s+", "", raw).translate(_CYR2LAT).upper()
    m = re.fullmatch(r"EI[SWM]{0,3}-?(15|30|45|60|90|120|150|180|240)", t)
    if not m:
        return None
    return f"EI {m.group(1)}", float(m.group(1))


# ── PPM-112: smoke-control system air flow ────────────────────────────────────────────────────────

_SYS = r"(?:ДУ|ДВ|ПД|ВД|КД)\d{1,2}(?:\.\d{1,2})?(?:\(\d\))?"
_P112 = re.compile(
    rf"(?<![\w.\-])(?P<sys>{_SYS})\s*[:(\-–—]?\s*(?:[^()\d]{{0,12}}?)?(?<![A-Za-z])L\s*=\s*"
    r"(?P<l>\d{1,3}(?: \d{3})+|\d+(?:[.,]\d+)?)\s*м\s?(?:³|3)\s*/\s*(?:ч|час)(?![\wа-я])"
)
_LIST_BEFORE = re.compile(rf"(?:{_SYS})\s*(?:,|и)\s*$")


# ── PPM-113 / 114: fire water ─────────────────────────────────────────────────────────────────────

_JET = r"(?P<n>[1-4])\s*стру[яиеь]\w*\s*[,:]?\s*(?:(?:по|на)\s+|с\s+расходом\s+(?:по\s+)?)?"
_P113_JETS = re.compile(rf"(?<![\d.,x×х]){_JET}(?P<q>\d+(?:[.,]\d+)?)\s*л\s?/\s?с", re.I)
_P113_MUL = re.compile(
    r"(?<![\d.,])(?P<n>[1-4])\s*[хx×]\s*(?P<q>\d+(?:[.,]\d+)?)\s*(?:=\s*\d+(?:[.,]\d+)?\s*)?л\s?/\s?с", re.I
)
_P113_CTX = re.compile(
    r"ВПВ|внутренн\w*\s+(?:противопожарн\w*\s+водопровод|пожаротушени)|пожарн\w*\s+кран", re.I
)
_P113_NORM_AFTER = re.compile(r"^\s*[–—-]\s*для\b|^\s*для\s+каждой")

_P114 = re.compile(
    r"наружн\w+\s+(?:противопожарн\w+\s+водоснабжени\w+|пожаротушени\w+)(?P<gap>[^\d\n]{0,50}?)"
    r"(?<![\d.,])(?P<v>\d+(?:[.,]\d+)?)\s*л\s?/\s?(?:с|сек)(?![\wа-я])",
    re.I,
)
_P114_NET = re.compile(
    r"обеспечивающ\w*|сет[ьи]|сетей|водопроводн\w+\s+сет", re.I
)  # network capacity, not the design flow
_P114_BAD = re.compile(r"внутренн|спринклер|дренчер|таблиц|табл\.|свыше|при\s|если|на\s+одн|каждый", re.I)


# ── PPM-111: fire dampers ─────────────────────────────────────────────────────────────────────────

_TAGLIST = rf"(?P<tags>{_SYS}(?:\s*(?:,|и)\s*{_SYS})*)"
_EI_TOK = r"(?P<ei>[EЕ][IІ][SWM]?\s?-?\s?\d{2,3})"
_P111_FOR = re.compile(
    rf"клапан\w*\s+для\s+систем\w*\s+{_TAGLIST}\s+(?:приняты|принят|принято|применяются|применяется|предусмотрены)"
    rf"\s+(?:нормально\s+\w+\s+)?с\s+пределом\s+огнестойкости\s+(?:не\s+менее\s+)?{_EI_TOK}",
    re.I,
)
_P111_SYS_ROLE = re.compile(
    rf"для\s+системы\s+[^.()]{{0,60}}\((?P<tag>{_SYS})\)\s+применяется\s+(?:нормально\s+\w+\s+(?:\([^)]{{1,8}}\)\s+)?)?"
    rf"клапан\w*\s+с\s+пределом\s+огнестойкости\s+(?:не\s+менее\s+)?{_EI_TOK}",
    re.I,
)


# ── PPM-103: fire doors by mark ───────────────────────────────────────────────────────────────────

_P103 = re.compile(rf"(?<![\w\-–])(?P<mark>Д[-–]?\s?\d{{1,3}}[а-я]?)\s+{_EI_TOK}(?![\d\w])")


# ── PPM-109: СПЗ cables ───────────────────────────────────────────────────────────────────────────

_P109 = re.compile(
    r"(?<![\w])(?P<mark>[A-Za-zА-Яа-я]{2,12}?)нг\(?[АA]?\)?[-‐–](?P<idx>FRLSLTx|FRLS|FRHF|LSLTx|LS|HF|LTx)"
    r"(?![A-Za-z])(?:\s*(?P<sec>\d{1,2}\s?[хxХX×]\s?\d{1,3}(?:[.,]\d+)?))?"
)


# ── PPM-107: finishing classes ────────────────────────────────────────────────────────────────────

_SURFACES = (
    (re.compile(r"стен\w*\s+и\s+потолк|потолк\w*\s+и\s+стен|стен|потолк", re.I), "стены и потолки"),
    (re.compile(r"покрыти\w*\s+пол|пол(?:ов|ы|а)\b", re.I), "полы"),
)
_ROOM_GROUPS = (
    (re.compile(r"лестничн", re.I), "лестничные клетки"),
    (re.compile(r"вестибюл", re.I), "вестибюли"),
    (re.compile(r"лифтов\w*\s+холл", re.I), "лифтовые холлы"),
    (re.compile(r"коридор", re.I), "коридоры"),
    (re.compile(r"(?<![а-я])(?:холл|фойе)", re.I), "холлы и фойе"),
)
_P107 = re.compile(r"(?P<pre>для\s+[^–—;:]{3,110}?)\s*[–—]\s*КМ\s?(?P<n>[0-5])(?![\d\w])")
_KM_BOUND = re.compile(r"(?:не\s+(?:выше|более|ниже|менее)|до)\s*(?:чем\s+)?$", re.I)


# ── PPM-102: fire compartment area ────────────────────────────────────────────────────────────────

_AREA = r"(?P<v>\d{1,3}(?: \d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*м\s?[²2](?![\w³])"
_P102_A = re.compile(
    rf"площад\w+\s+пожарн\w+\s+отсек\w*\s*(?:(?:№|N|номер)\s*(?P<id>\d{{1,2}})\s*)?(?:[–—:=-]|составляет|равн\w+)\s*{_AREA}",
    re.I,
)
_P102_B = re.compile(
    rf"пожарн\w+\s+отсек\w*\s*(?:(?:№|N|номер)\s*(?P<id>\d{{1,2}})\s*)?[^.\d;]{{0,30}}?площад\w+\s*"
    rf"(?:[–—:=-]|составляет|равн\w+)\s*{_AREA}",
    re.I,
)
_BOUND_WORDS = re.compile(
    r"не\s+(?:более|менее|выше|ниже)|до\s+\d|допустим|нормируем|норматив|максимальн|предельн", re.I
)


# ── PPM-104 / 105: design widths ──────────────────────────────────────────────────────────────────

_W_VAL = r"(?P<v>\d+(?:[.,]\d+)?)\s*(?P<u>мм|м)(?![а-яА-Я²³\w])"
_P104 = re.compile(
    r"ширин\w+\s+(?P<noun>эвакуационн\w+\s+проход\w*|эвакуационн\w+\s+коридор\w*|путей\s+эвакуации|пути\s+эвакуации)"
    rf"(?P<gap>[^\d\n.]{{0,30}}?){_W_VAL}",
    re.I,
)
_P105 = re.compile(
    r"ширин\w+\s+(?:в\s+свету\s+)?(?P<noun>(?:наружн\w+\s+(?:эвакуационн\w+\s+)?двер\w+|"
    r"эвакуационн\w+\s+выход\w*\s+наружу|наружн\w+\s+эвакуационн\w+\s+выход\w*|наружн\w+\s+выход\w*))"
    rf"(?P<gap>[^\d\n.]{{0,30}}?){_W_VAL}",
    re.I,
)
_W_BAD = re.compile(
    r"не\s+(?:менее|более|ниже|выше)|менее|более|минимальн|норматив|нормам|требуе|допустим|для\s+МГН|инвалид",
    re.I,
)


def _width_m(m: re.Match[str]) -> float | None:
    v = _num(m.group("v"))
    if v is None:
        return None
    return round(v / 1000.0, 6) if m.group("u").lower() == "мм" else v


def _lemma(noun: str) -> str:
    """The printed element noun in its base form («эвакуационного прохода» → «эвакуационный проход»)."""
    n = noun.lower()
    for key, lemma in (("двер", "наружная дверь"), ("выход", "наружный выход"), ("проход", "эвакуационный проход"),
                       ("коридор", "эвакуационный коридор"), ("эвакуации", "путь эвакуации")):  # fmt: skip
        if key in n:
            return lemma
    return re.sub(r"\s+", " ", n)


def _tags(raw: str) -> list[str]:
    return [re.sub(r"\s+", "", x).upper() for x in re.findall(_SYS, raw)]


def _cable_key(mark: str, sec: str | None) -> str | None:
    if not sec:
        return None
    base = mark.upper().translate(_LAT2CYR)
    s = re.sub(r"\s+", "", sec).lower().replace("x", "х").replace("×", "х").replace(",", ".")
    s = re.sub(r"(?<=\d)\.0+(?!\d)", "", s)
    return f"{base} {s}"


def extract(text: str) -> list[PpmFact]:
    """Every labelled ППМ value of one page's text (deduplicated per page)."""
    t = normalize_text(text)
    if not t or not HINT.search(t):
        return []
    out: list[PpmFact] = []
    seen: set[tuple[Any, ...]] = set()

    def add(f: PpmFact) -> None:
        key = (f.code, f.kind, f.location, f.value, f.unit)
        if key not in seen:
            seen.add(key)
            out.append(f)

    # PPM-112 — «ВД1 (L=13000 м3/ч, Pc=500 Па)»; a tag list before «(L=…)» is shared by several fans: skipped
    for m in _P112.finditer(t):
        if _LIST_BEFORE.search(t[max(0, m.start() - 12) : m.start()]):
            continue
        v = _num(m.group("l"))
        if v is None or v <= 0:
            continue
        tag = re.sub(r"\s+", "", m.group("sys")).upper()
        add(
            PpmFact(
                "PPM-112", "air_flow", tag, f"{m.group('l')} м³/ч", v, "number", "м³/ч", None, 0.9, _ctx(t, m)
            )
        )

    # PPM-113 — jets × flow per jet, only near a ВПВ / fire-crane context; a per-section norm list is not a design
    for rx, conf in ((_P113_JETS, 0.9), (_P113_MUL, 0.8)):
        for m in rx.finditer(t):
            if rx is _P113_MUL and (
                not _P113_CTX.search(t[max(0, m.start() - 120) : m.start()])
                or _P113_NORM_AFTER.search(t[m.end() : m.end() + 20])
            ):
                continue
            n, q = _num(m.group("n")), _num(m.group("q"))
            if n is None or q is None or q <= 0:
                continue
            add(
                PpmFact(
                    "PPM-113",
                    "vpv_jets",
                    "число струй",
                    m.group("n"),
                    n,
                    "number",
                    None,
                    None,
                    conf,
                    _ctx(t, m),
                )
            )
            add(PpmFact("PPM-113", "vpv_flow", "расход на струю", f"{m.group('q')} л/с", q, "number", "л/с", None, conf, _ctx(t, m)))  # fmt: skip

    # PPM-114 — external fire-fighting flow of the object
    for m in _P114.finditer(t):
        if _P114_BAD.search(m.group("gap")) or _P114_NET.search(t[max(0, m.start() - 90) : m.start()]):
            continue
        v = _num(m.group("v"))
        if v is None or v <= 0:
            continue
        add(
            PpmFact(
                "PPM-114",
                "external_flow",
                None,
                f"{m.group('v')} л/с",
                v,
                "number",
                "л/с",
                None,
                0.85,
                _ctx(t, m),
            )
        )

    # PPM-111 — damper EI per system tag
    for rx in (_P111_FOR, _P111_SYS_ROLE):
        for m in rx.finditer(t):
            ei = norm_ei(m.group("ei"))
            if ei is None:
                continue
            tags = _tags(m.group("tags")) if "tags" in rx.groupindex else [m.group("tag").upper()]
            for tag in tags:
                add(PpmFact("PPM-111", "damper_ei", tag, m.group("ei").strip(), ei[0], "enum", None, ei[1], 0.85, _ctx(t, m)))  # fmt: skip

    # PPM-103 — door mark followed by its EI
    for m in _P103.finditer(t):
        ei = norm_ei(m.group("ei"))
        if ei is None:
            continue
        mark = re.sub(r"\s+", "", m.group("mark")).replace("–", "-")
        add(
            PpmFact(
                "PPM-103", "door_ei", mark, m.group("ei").strip(), ei[0], "enum", None, ei[1], 0.8, _ctx(t, m)
            )
        )

    # PPM-109 — cable family + section with its fire index
    for m in _P109.finditer(t):
        key = _cable_key(m.group("mark"), m.group("sec"))
        idx = m.group("idx")
        if key is None or idx not in CABLE_RANK:
            continue
        add(PpmFact("PPM-109", "cable_index", key, idx, idx, "enum", None, CABLE_RANK[idx], 0.8, _ctx(t, m)))

    # PPM-107 — finishing class per surface and room group
    for sent in re.split(r"(?<=[.;])\s", t):
        surface: str | None = None
        for m in _P107.finditer(sent):
            if _KM_BOUND.search(sent[max(0, m.start() - 20) : m.start()]):
                continue
            pre = m.group("pre")
            for rx, name in _SURFACES:
                if rx.match(pre[len("для ") :]):
                    surface = name
                    break
            if surface is None:
                continue
            km = f"КМ{m.group('n')}"
            for g in [g for rx, g in _ROOM_GROUPS if rx.search(pre)]:
                add(
                    PpmFact(
                        "PPM-107",
                        "km",
                        f"{surface}: {g}",
                        km,
                        km,
                        "enum",
                        None,
                        KM_RANK[km],
                        0.75,
                        _ctx(sent, m),
                    )
                )

    # PPM-102 — fire compartment area
    for rx in (_P102_A, _P102_B):
        for m in rx.finditer(t):
            if _BOUND_WORDS.search(t[max(0, m.start() - 40) : m.start()]) or _BOUND_WORDS.search(m.group(0)):
                continue
            v = _num(m.group("v"))
            if v is None or v <= 0:
                continue
            loc = f"Пожарный отсек {m.group('id')}" if m.group("id") else "Пожарный отсек"
            add(
                PpmFact(
                    "PPM-102",
                    "compartment_area",
                    loc,
                    f"{m.group('v')} м²",
                    v,
                    "number",
                    "м²",
                    None,
                    0.8,
                    _ctx(t, m),
                )
            )

    # PPM-104 / 105 — design widths (a normative bound is not a design value)
    for code, rx, kind in (("PPM-104", _P104, "evac_width"), ("PPM-105", _P105, "exit_width")):
        for m in rx.finditer(t):
            if _W_BAD.search(m.group("gap")) or _W_BAD.search(t[max(0, m.start() - 40) : m.start()]):
                continue
            w = _width_m(m)
            if w is None or not 0.3 <= w <= 20:
                continue
            noun = _lemma(m.group("noun"))
            add(
                PpmFact(
                    code,
                    kind,
                    noun,
                    f"{m.group('v')} {m.group('u')}",
                    w,
                    "number",
                    "м",
                    None,
                    0.8,
                    _ctx(t, m),
                )
            )
    return out


# ── ambiguity over the whole object ───────────────────────────────────────────────────────────────


def _key(v: dict[str, Any]) -> tuple[Any, Any]:
    n = v["value_norm"]
    return (n.get("value"), n.get("unit"))


def resolve_ambiguity(values: list[dict[str, Any]]) -> dict[str, int]:
    """Per (parameter, element, stage): several different printed values without a clear winner are all set aside
    (``is_ambiguous``); a value another stage prints too is kept (the agreed reading), a value mentioned ≥ 3 times and
    ≥ 2× the runner-up dominates. No finding beats a false one (AbstainReason AMBIGUOUS_VALUE)."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for v in values:
        if str(v.get("fact_key") or "").startswith("ppm.") and v.get("param_code") in PPM_CODES:
            groups[(v["param_code"], v.get("location") or "OBJECT", v["stage"])].append(v)
    stats = {"groups": len(groups), "ambiguous_groups": 0, "dominant_groups": 0, "agreed_groups": 0}
    by_elem: dict[tuple[str, str], dict[str, set[tuple[Any, Any]]]] = defaultdict(lambda: defaultdict(set))
    for (code, loc, stage), vs in groups.items():
        by_elem[(code, loc)][stage] = {_key(v) for v in vs}
    for (code, loc, stage), vs in groups.items():
        counts = Counter(_key(v) for v in vs)
        if len(counts) == 1:
            continue
        ranked = counts.most_common()
        top, second = ranked[0][1], ranked[1][1]
        keep = ranked[0][0] if top >= 3 and top >= 2 * second else None
        others = set().union(*(k for s, k in by_elem[(code, loc)].items() if s != stage))
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


# ── contract output ───────────────────────────────────────────────────────────────────────────────


def from_ppm(sink: Any, page: int, facts: list[PpmFact], text_source: str = "TEXT_LAYER") -> None:
    """Facts → ``ppm.*`` values bound to their catalog parameter (ELEMENT location, or OBJECT for object-level)."""
    for f in facts:
        sink.add(page=page, fact_key=f.fact_key, value_raw=f.raw, vtype=f.vtype, value=f.value, unit=f.unit,
                 method="REGEX", confidence=f.confidence * (0.9 if text_source.startswith("OCR") else 1.0),
                 location=f.location, location_type="ELEMENT" if f.location else "OBJECT", param_code=f.code,
                 qualifiers={"kind": f.kind, "parser": PARSER_VERSION}, text_source=text_source,
                 context=f.context)  # fmt: skip
        if f.rank is not None:
            sink.values[-1]["value_norm"]["rank"] = f.rank
