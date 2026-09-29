"""Labelled numeric / class values of assorted sections, read from prose (wave-2 «mix» parameters).

ODI-116 (corridor width on МГН routes), ODI-117 (door width on МГН routes), ODI-119 (universal cabin size),
ODI-121 / SPZU-038 (parking places for disabled), SPZU-030 (fire-passage width), SPZU-031 (turning radius),
AR-045 (roof slope), AR-049 (railing height), AR-050 (finishing fire class КМ), KR-066 (fire protection: required
limit R, layer thickness, composition type) and ZU-131 (specific heat consumption for heating and ventilation).

The same discipline as ``pzparams``: a value is taken only when it stands next to its own label (the catalog
``regex_pattern`` tightened), never from a stray number. Two more rules keep it conservative:

* a *norm* statement is not a design value: «не менее 1,5 м», «более 1,5%», «допускается», «нормируемое» in the gap
  between the label and the number drop the fact (the projects quote SP clauses all the time);
* sizes are normalised to metres (мм / см converted; the printed decimals of the *normalised* form drive the
  SOURCE_PRECISION tolerance), slopes to per cent, the cabin to its shorter side.

Facts go to ``values/<object>.jsonl`` with fact key ``tx.value``. Sub-check specific facts (AR-045.a slope, KR-066.a
limit R / .b thickness / .c composition) carry the qualifier ``sub_id`` so the generic comparator evaluates only the
sub-check they belong to. ``resolve_ambiguity`` marks a (parameter, location, stage) that prints several different
values without a dominating one as ambiguous (no finding; the in-stage conflict is a suspicion elsewhere).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from inspector_tables.pzparams import normalize_text

PARSER_VERSION = "textparams-1"
FACT_KEY = "tx.value"

TX_CODES = (
    "ODI-116",
    "ODI-117",
    "ODI-119",
    "ODI-121",
    "SPZU-030",
    "SPZU-031",
    "SPZU-038",
    "AR-045",
    "AR-049",
    "AR-050",
    "KR-066",
    "ZU-131",
)

# ordinal scale of the finishing fire hazard class (КМ0 = non-combustible = best)
KM_RANK = {f"КМ{n}": float(6 - n) for n in range(6)}

# ── source gating by file name / folder ──────────────────────────────────────────────────────────

_B = r"(?<![а-яa-z])"
_E = r"(?![а-яa-z])"
_SRC: dict[str, re.Pattern[str]] = {
    "ODI": re.compile(rf"{_B}(?:оди|odi){_E}|доступн\w*\s+сред|мгн|маломобильн"),
    "AR": re.compile(rf"архитектурн|{_B}(?:ар|ac)\d*{_E}|{_B}п[-_ ]ар{_E}"),
    "KR": re.compile(rf"конструктивн|{_B}(?:кр|кж|км|кд)\d*{_E}|{_B}п[-_ ](?:кр|кж|км){_E}"),
    "GP": re.compile(rf"планировочн|{_B}(?:пзу|спзу|спозу|гп|ген\.?\s?план)\d*{_E}|{_B}п[-_ ]пзу{_E}"),
    "PZ": re.compile(rf"пояснительн|{_B}(?:пз|опз){_E}|{_B}п[-_ ](?:пз|опз){_E}"),
    "EE": re.compile(rf"энергетическ\w*\s+эффективност|{_B}ээ{_E}|энергопаспорт|энергетическ\w*\s+паспорт"),
    "OV": re.compile(rf"отоплен|вентиляц|{_B}(?:ов|ити|ов\d)\d*{_E}|{_B}иос\s?4{_E}|{_B}ос{_E}"),
}


def source_flags(relative_path: str) -> frozenset[str]:
    """Discipline flags of a file by its name or folder (ODI, AR, KR, GP, PZ, EE, OV); a file with no flag is
    still read for the strictly labelled parameters (ZU-131, KR-066, AR-049, AR-045)."""
    p = (relative_path or "").replace("\\", "/").replace("ё", "е").replace("Ё", "Е").lower()
    return frozenset(k for k, rx in _SRC.items() if rx.search(p))


HINT = re.compile(
    r"коридор|пут\w+\s+движени|дверн|проем|полотн|кабин|санузл|мгн|инвалид|проезд|радиус|уклон|ограждени|"
    r"огнезащит|антикоррози|км\s?[0-5]|удельн\w+\s+(?:годов\w+\s+)?(?:расход|характеристик)",
    re.I,
)


@dataclass(slots=True)
class TextFact:
    code: str
    raw: str  # normalised printed form («1,8 м», «КМ1», «R90», «3»)
    value: Any  # number or the canonical class
    vtype: str  # number | enum
    unit: str | None
    rank: float | None
    confidence: float
    context: str
    location: str | None = None  # element (ELEMENT) or None → OBJECT
    sub_id: str | None = None
    kind: str | None = None
    printed: str | None = None  # the value as printed («i=0,01») when ``raw`` is a normalised form («1 %»)


# ── number helpers ────────────────────────────────────────────────────────────────────────────────

_NUM = r"\d+(?:[.,]\d+)?"
_NORM = re.compile(
    r"не\s+(?:менее|более|ниже|выше|уже|шире|меньше|больше|превыш)|(?<![а-я])(?:менее|более|свыше)(?![а-я])|"
    r"[≥≤<>]|нормируем|требуем|минимальн|максимальн|допускается|допустим|рекомендуе|по\s+нормам|согласно\s+нормам|"
    r"не\s+нормируется|\bmin\b|\bmax\b",
    re.I,
)
_RANGE_AFTER = re.compile(r"^\s*(?:до|[-–—]|÷|…)\s*\d", re.I)
_ALT_BEFORE = re.compile(r"(?:от|до)\s*$", re.I)


def _f(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _ru(v: float, decimals: int) -> str:
    return f"{v:.{decimals}f}".replace(".", ",")


def to_metres(raw: str, unit: str) -> tuple[float, str] | None:
    """(metres, normalised printed form): 1800 мм → (1.8, «1,8 м»); the decimals of the normalised form are the
    ones the source needs (1250 мм → «1,25 м»)."""
    n = _f(raw)
    if n is None:
        return None
    u = unit.lower()
    v = n / 1000.0 if u == "мм" else (n / 100.0 if u == "см" else n)
    v = round(v, 4)
    dec = max(1, len(f"{v:.4f}".rstrip("0").split(".")[1]))
    return v, f"{_ru(v, dec)} м"


def _ctx(t: str, m: re.Match[str]) -> str:
    return t[max(0, m.start() - 40) : min(len(t), m.end() + 60)].strip()


def _is_norm(gap: str, pre: str = "") -> bool:
    return bool(_NORM.search(gap) or _NORM.search(pre[-25:]))


def _length_fact(
    code: str,
    m: re.Match[str],
    t: str,
    lo: float,
    hi: float,
    *,
    location: str | None = None,
    sub_id: str | None = None,
    conf: float = 0.85,
    kind: str | None = None,
) -> TextFact | None:
    if _is_norm(m.group("gap") or "", t[max(0, m.start() - 25) : m.start()]):
        return None
    tail = t[m.end() : m.end() + 14]
    if _RANGE_AFTER.match(tail) or _ALT_BEFORE.search(t[max(0, m.start("v") - 4) : m.start("v")]):
        return None  # «от 6 до 23 м»: a range is not a single value
    got = to_metres(m.group("v"), m.group("u"))
    if got is None or not lo <= got[0] <= hi:
        return None
    return TextFact(code, got[1], got[0], "number", "м", None, conf, _ctx(t, m), location, sub_id, kind)


_LEN_U = r"(?P<u>мм|см|м)(?![а-яa-z²³/])"
_GAP = r"(?P<gap>[^\d\n;]{0,45}?)"
_LIFT = re.compile(r"лифт", re.I)
_MGN = re.compile(r"мгн|инвалид|маломобильн|колясоч|кресл\w*[- ]коляс", re.I)


def _mgn_near(t: str, m: re.Match[str], reach: int = 220) -> bool:
    return bool(_MGN.search(t[max(0, m.start() - reach) : m.end() + reach]))


# ── ODI-116 / ODI-117 / ODI-119 / ODI-121 / SPZU-038 ─────────────────────────────────────────────

_P116 = re.compile(
    rf"(?:ширин\w*\s+(?:(?:основн\w+|внутренн\w+)\s+)?(?:коридор\w*|пут\w+\s+движени\w+(?:\s+\S+){{0,2}}?)|"
    rf"коридор\w*\s+шириной){_GAP}(?<![\d.,])(?P<v>{_NUM})\s*{_LEN_U}",
    re.I,
)
_P117 = re.compile(
    rf"(?:ширин\w*\s+(?:в\s+свету\s+)?(?:дверн\w+\s+)?(?:проем\w*|полотн\w*)|дверн\w+\s+проем\w*\s+шириной)"
    rf"(?:\s+в\s+свету)?{_GAP}(?<![\d.,])(?P<v>{_NUM})\s*{_LEN_U}",
    re.I,
)
_DIM = r"(?:\d{3,4}|\d[.,]\d{1,2})"
_P119 = re.compile(
    rf"(?:универсальн\w+\s+кабин\w*|санузл\w*\s+(?:для\s+)?(?:мгн|инвалид\w*)|сантехкабин\w*\s+для\s+мгн)"
    rf"(?P<gap>[^\d\n;]{{0,40}}?)(?<![\d.,])(?P<a>{_DIM})\s*(?:м\s*)?[xх×*]\s*(?P<b>{_DIM})\s*(?P<u>мм|м)?(?![\d.,а-яa-z²³])",
    re.I,
)
_PARK_LBL = (
    r"(?:(?:машино[- ]?)?мест\w*|м/м|машино[- ]?мест\w*)\s+для\s+"
    r"(?:(?:автотранспорт\w*|транспорт\w*|автомобил\w*)\s+)?(?:мгн|инвалид\w*|маломобильн\w+\s+групп\w*)"
)
_PARK_UNIT = r"(?:м/м|машино[- ]?мест\w*|мест\w*|шт)(?![а-яa-z])"
_P_PARK_A = re.compile(
    rf"{_PARK_LBL}(?P<gap>[^\d\n;]{{0,40}}?)(?<![\d.,/])(?P<v>\d{{1,3}})\s*{_PARK_UNIT}", re.I
)
_P_PARK_B = re.compile(
    r"(?<![\d.,/\-А-Яа-яA-Za-z])(?P<v>\d{1,3})\s*(?:м/м|машино[- ]?мест\w*|мест\w*)\s+для\s+"
    r"(?:(?:автотранспорт\w*|транспорт\w*)\s+)?(?:мгн|инвалид\w*|маломобильн\w+\s+групп\w*)",
    re.I,
)


def _extract_odi(t: str, flags: frozenset[str], out: list[TextFact]) -> None:
    if flags & {"ODI", "AR", "PZ"} or not flags:
        for m in _P116.finditer(t):
            if _mgn_near(t, m) or re.search(r"пут\w+\s+движени", m.group(0), re.I):
                f = _length_fact("ODI-116", m, t, 0.6, 6.0)
                if f:
                    out.append(f)
        for m in _P117.finditer(t):
            if _mgn_near(t, m) and not _LIFT.search(t[max(0, m.start() - 90) : m.end() + 60]):
                f = _length_fact("ODI-117", m, t, 0.5, 2.6)
                if f:
                    out.append(f)
        for m in _P119.finditer(t):
            if _is_norm(m.group("gap"), t[max(0, m.start() - 25) : m.start()]):
                continue
            dims = []
            for k in ("a", "b"):
                raw = m.group(k)
                got = to_metres(raw, m.group("u") or ("мм" if len(raw) >= 3 and raw.isdigit() else "м"))
                dims.append(got)
            if None in dims or not all(1.0 <= d[0] <= 4.0 for d in dims if d):  # type: ignore[index]
                continue
            short = min(dims, key=lambda d: d[0])  # type: ignore[arg-type,return-value]
            assert short is not None
            out.append(
                TextFact(
                    "ODI-119", short[1], short[0], "number", "м", None, 0.8, _ctx(t, m), None, None, "cabin"
                )
            )
    park_code = None
    if flags & {"GP"}:
        park_code = "SPZU-038"
    elif flags & {"ODI", "AR", "PZ"}:
        park_code = "ODI-121"
    if park_code:
        for rx in (_P_PARK_A, _P_PARK_B):
            for m in rx.finditer(t):
                gap = m.groupdict().get("gap") or ""
                if _is_norm(gap, t[max(0, m.start() - 25) : m.start()]) or re.search(
                    r"в\s+т\.?\s?ч|из\s+них", gap
                ):
                    continue
                v = int(m.group("v"))
                if 1 <= v <= 300:
                    out.append(
                        TextFact(
                            park_code,
                            str(v),
                            float(v),
                            "number",
                            None,
                            None,
                            0.8,
                            _ctx(t, m),
                            None,
                            None,
                            "count",
                        )
                    )


# ── SPZU-030 / SPZU-031 ───────────────────────────────────────────────────────────────────────────

_P030 = re.compile(
    rf"(?:ширин\w*\s+(?:пожарн\w+\s+)?(?:проезд\w*|подъезд\w*)|(?:пожарн\w+\s+)?проезд\w*\s+шириной){_GAP}"
    rf"(?<![\d.,])(?P<v>{_NUM})\s*{_LEN_U}",
    re.I,
)
_P031 = re.compile(
    rf"радиус\w*\s+(?:поворота|закруглени\w*|разворота)(?:\s+(?:проезд\w*|дорог\w*|пожарн\w+\s+проезд\w*))?{_GAP}"
    rf"(?<![\d.,])(?P<v>{_NUM})\s*{_LEN_U}",
    re.I,
)


def _extract_spzu(t: str, flags: frozenset[str], out: list[TextFact]) -> None:
    if flags & {"GP", "PZ"} or not flags:
        for m in _P030.finditer(t):
            f = _length_fact("SPZU-030", m, t, 2.5, 20.0)
            if f:
                out.append(f)
        for m in _P031.finditer(t):
            f = _length_fact("SPZU-031", m, t, 3.0, 60.0)
            if f:
                out.append(f)


# ── AR-045 / AR-049 / AR-050 ──────────────────────────────────────────────────────────────────────

_P045 = re.compile(
    rf"уклон\w*\s+(?:кровл\w+|покрыти\w+)(?P<gap>\s*(?:принят\w*|составляет|равен\w*|[-–—:=])?\s*(?:в\s+сторону\s+\S+\s+)?)"
    rf"(?:(?P<i>(?<![a-zа-я])[iі])\s*=\s*)?(?<![\d.,])(?P<v>{_NUM})\s*(?P<u>%|‰|°|градус\w*)?",
    re.I,
)
_RAIL_KIND = (
    (re.compile(r"кровл|террас|парапет"), "Ограждение кровли"),
    (re.compile(r"балкон|лоджи"), "Ограждение балконов"),
    (re.compile(r"лестниц|лестничн"), "Ограждение лестниц"),
)
_P049_A = re.compile(
    rf"огражден\w+\s+(?P<kind>кровл\w+|террас\w*|парапет\w*|балкон\w*|лоджи\w*|лестниц\w*|лестничн\w+\s+\w+){_GAP}"
    rf"(?:высот\w+|на\s+высоте|h\s*=)\s*(?<![\d.,])(?P<v>{_NUM})\s*{_LEN_U}",
    re.I,
)
_P049_B = re.compile(
    rf"(?P<kind>кровл\w+|балкон\w*|лоджи\w*|террас\w*|лестничн\w+\s+марш\w*|лестниц\w+)[^\d\n;.]{{0,30}}?огражден\w+"
    rf"(?P<gap>\s*)(?:высотой|на\s+высоте|h\s*=)\s*(?<![\d.,])(?P<v>{_NUM})\s*{_LEN_U}",
    re.I,
)
_P050 = re.compile(r"(?<![\w\-–./])КМ\s?(?P<v>[0-5])(?![\w.\-–])")
_KM_CTX = re.compile(
    r"отделк|облицовк|материал|покрыти|класс\w*\s+(?:пожарной\s+)?(?:опасности|пожарн)|пожарн\w+\s+опасност",
    re.I,
)
_ZONE = (
    (re.compile(r"лестничн\w+\s+клет"), "Лестничные клетки"),
    (re.compile(r"вестибюл"), "Вестибюли"),
    (re.compile(r"холл"), "Холлы"),
    (re.compile(r"коридор"), "Коридоры"),
    (re.compile(r"пут\w+\s+эвакуаци|эвакуационн"), "Пути эвакуации"),
)
_SURF = (
    (re.compile(r"потолк"), "потолки"),
    (re.compile(r"стен|стенов"), "стены"),
    (re.compile(r"(?<![а-я])пол(?:а|ов|ы|у|е)?(?![а-я])|покрыти\w+\s+пол"), "полы"),
)


def _last_hit(pairs: tuple[tuple[re.Pattern[str], str], ...], low: str) -> str | None:
    best, pos = None, -1
    for rx, label in pairs:
        for m in rx.finditer(low):
            if m.start() >= pos:
                best, pos = label, m.start()
    return best


def _slope_fact(m: re.Match[str], t: str) -> TextFact | None:
    if _is_norm(m.group("gap") or "", t[max(0, m.start() - 25) : m.start()]):
        return None
    v = _f(m.group("v"))
    if v is None:
        return None
    unit = (m.group("u") or "").lower()
    if unit == "%":
        pct = v
    elif unit == "‰":
        pct = v / 10.0
    elif unit.startswith("°") or unit.startswith("градус"):
        import math

        pct = math.tan(math.radians(v)) * 100.0
    elif m.group("i") and 0 < v < 0.5:  # «i = 0,01»: a dimensionless slope
        pct = v * 100.0
    else:
        return None
    pct = round(pct, 2)
    if not 0.3 <= pct <= 60:
        return None
    dec = max(0, len(f"{pct:.2f}".rstrip("0").split(".")[1]))
    return TextFact(
        "AR-045",
        f"{_ru(pct, dec)} %",
        pct,
        "number",
        "%",
        None,
        0.85,
        _ctx(t, m),
        None,
        "AR-045.a",
        "roof_slope",
        printed=t[
            (m.start("i") if m.group("i") else m.start("v")) : (m.end("u") if m.group("u") else m.end("v"))
        ].strip(),
    )


def _extract_ar(t: str, flags: frozenset[str], out: list[TextFact]) -> None:
    if not flags or flags & {"AR", "KR", "PZ", "ODI"}:
        for m in _P045.finditer(t):
            f = _slope_fact(m, t)
            if f:
                out.append(f)
    for rx in (_P049_A, _P049_B):
        for m in rx.finditer(t):
            kind = m.group("kind").lower()
            if kind.startswith("парапет") and "огражден" not in m.group(0).lower():
                continue
            loc = _last_hit(_RAIL_KIND, kind)
            if loc is None:
                continue
            f = _length_fact("AR-049", m, t, 0.5, 3.0, location=loc, conf=0.85, kind="railing")
            if f:
                out.append(f)
    if not flags or flags & {"AR", "PZ", "ODI"}:
        low = t.lower()
        for m in _P050.finditer(t):
            if not _KM_CTX.search(t[max(0, m.start() - 90) : m.start()]):
                continue
            head = low[max(0, m.start() - 200) : m.start()]
            cut = max(
                head.rfind(";"),
                head.rfind("."),
                (list(re.finditer(r"км\s?[0-5]", head)) or [None])[-1].end()
                if re.search(r"км\s?[0-5]", head)
                else -1,
            )
            head = head[cut + 1 :]
            if _NORM.search(t[max(0, m.start() - 200) : m.start()]):
                continue  # a quoted requirement («не более, чем: класс КМ1 …»), not the design value
            zones = {label for rx, label in _ZONE if rx.search(head)}
            surfs = {label for rx, label in _SURF if rx.search(head)}
            if len(zones) != 1 or len(surfs) > 1:
                continue  # several zones/surfaces in one clause: which one carries this class is unknown
            val = f"КМ{m.group('v')}"
            loc = next(iter(zones)) + (f": {next(iter(surfs))}" if surfs else "")
            out.append(
                TextFact(
                    "AR-050", val, val, "enum", None, KM_RANK[val], 0.8, _ctx(t, m), loc, None, "finishing"
                )
            )


# ── KR-066 ────────────────────────────────────────────────────────────────────────────────────────

_R_LIMIT = re.compile(
    r"(?i:огнезащит)\w+(?P<gap>[^.;\n]{0,110}?)(?<![a-zа-яA-ZА-Я])(?:REI|R|Р)\s?(?P<r>15|30|45|60|90|120|150|180)(?!\d)(?![.,]\d)"
)
_R_BAD = re.compile(r"воздуховод|кабел|трубопровод|клапан|проход\w*\s+через|\bei\s?\d", re.I)
_ELEMENT = (
    (re.compile(r"колонн|стойк"), "Колонны"),
    (re.compile(r"балк|ригел"), "Балки"),
    (re.compile(r"ферм"), "Фермы"),
    (re.compile(r"связ"), "Связи"),
    (re.compile(r"перекрыти"), "Перекрытия"),
    (re.compile(r"покрыти\w+\s+(?:здани|кровл)|кровл"), "Покрытие"),
    (re.compile(r"лестничн\w+\s+(?:марш|площад)|марш"), "Лестницы"),
    (re.compile(r"металлоконструкц|стальн\w+\s+конструкц|несущ\w+\s+конструкц"), "Металлоконструкции"),
)
_COMPOSITION = (
    (re.compile(r"вспучивающ|интумесцент"), "вспучивающийся состав"),
    (re.compile(r"штукатурк"), "штукатурка"),
    (re.compile(r"обмазк"), "обмазка"),
    (re.compile(r"плитн|плитами|плиты|плит\b"), "плитная облицовка"),
)
_P_THK = re.compile(
    rf"(?P<lbl>огнезащит\w+|антикоррози\w+)(?P<gap>[^.;\n\d]{{0,80}}?)толщин\w+(?:\s+(?:сухого\s+)?(?:слоя|покрыти\w+))?"
    rf"\s*(?P<pre>[^.;\n\d]{{0,12}}?)(?<![\d.,])(?P<v>{_NUM})\s*(?P<u>мкм|мм)(?![а-яa-z])",
    re.I,
)


def _extract_kr(t: str, flags: frozenset[str], out: list[TextFact]) -> None:
    low = t.lower()
    for m in _R_LIMIT.finditer(t):
        window = t[max(0, m.start() - 60) : m.end() + 30]
        if _R_BAD.search(window):
            continue
        around = low[max(0, m.start("r") - 90) : m.end() + 55]
        elems = {label for rx, label in _ELEMENT if rx.search(around)}
        if len(elems) != 1:
            continue  # no element, or several: the limit cannot be bound to one
        elem = next(iter(elems))
        r = int(m.group("r"))
        out.append(
            TextFact(
                "KR-066",
                f"R{r}",
                f"R{r}",
                "enum",
                None,
                float(r),
                0.85,
                _ctx(t, m),
                elem,
                "KR-066.a",
                "fire_limit",
            )
        )
        comp = {label for rx, label in _COMPOSITION if rx.search(low[max(0, m.start() - 90) : m.end() + 90])}
        if len(comp) == 1:
            label = next(iter(comp))
            out.append(
                TextFact(
                    "KR-066",
                    label,
                    label,
                    "string",
                    None,
                    None,
                    0.7,
                    _ctx(t, m),
                    elem,
                    "KR-066.c",
                    "composition",
                )
            )
    for m in _P_THK.finditer(t):
        if _is_norm(m.group("gap") + (m.group("pre") or ""), t[max(0, m.start() - 25) : m.start()]):
            continue
        v = _f(m.group("v"))
        if v is None:
            continue
        unit = m.group("u").lower()
        loc = (
            "Огнезащитное покрытие"
            if m.group("lbl").lower().startswith("огнезащит")
            else "Антикоррозионное покрытие"
        )
        dec = len(m.group("v").split(",")[-1]) if "," in m.group("v") else 0
        out.append(
            TextFact(
                "KR-066",
                f"{_ru(v, dec)} {unit}",
                v,
                "number",
                unit,
                None,
                0.8,
                _ctx(t, m),
                loc,
                "KR-066.b",
                "thickness",
            )
        )


# ── ZU-131 ────────────────────────────────────────────────────────────────────────────────────────

_ZU_UNIT = (
    r"(?P<u>кВт\s?[·.*⋅]?\s?ч\s?/\s?\(?\s?м\s?[²2]|Вт\s?/\s?\(\s?м\s?[³3]\s?[·.*⋅]?\s?°?\s?[СCcс]?\s?\)?)"
)
_ZU_LBL = (
    r"(?P<q>расчетн\w+\s+|нормируем\w+\s+|требуем\w+\s+|базов\w+\s+|проектн\w+\s+)?"
    r"удельн\w+\s+(?:годов\w+\s+)?(?:расход\w*|характеристик\w+(?:\s+расхода)?)\s+(?:тепловой\s+энерги\w+|тепла)\s+на\s+отоплени\w+"
    r"(?:\s+и\s+вентиляци\w+)?(?:\s+здани\w+)?(?:\s+за\s+отопительн\w+\s+период)?"
)
_P131_A = re.compile(rf"{_ZU_LBL}(?P<gap>[^\d\n]{{0,45}}?)(?<![\d.,])(?P<v>{_NUM})\s*{_ZU_UNIT}", re.I)
_P131_B = re.compile(
    rf"{_ZU_LBL}[^\d\n]{{0,45}}?{_ZU_UNIT}\s*(?P<v>{_NUM})(?![\d.,])(?P<after>\s*\d+[.,]\d+)?", re.I
)


_ZU_BAD = re.compile(r"(?<![а-я])тр(?![а-я])|по\s+отношению|процент|снижени", re.I)


def zu_unit(raw: str) -> str:
    return "кВт·ч/м²" if raw.lower().startswith("квт") else "Вт/(м³·°С)"


def _extract_zu(t: str, out: list[TextFact]) -> None:
    seen: set[tuple[str, str]] = set()
    for rx in (_P131_B, _P131_A):
        for m in rx.finditer(t):
            q = (m.group("q") or "").strip().lower()
            if q and not q.startswith(("расчетн", "проектн")):
                continue
            if _ZU_BAD.search(t[max(0, m.start() - 80) : m.start()] + " " + (m.groupdict().get("gap") or "")):
                continue  # «на 20 процентов по отношению к…», «q от тр» (required): a derived limit, not the design value
            if rx is _P131_A and _is_norm(m.group("gap")):
                continue
            if rx is _P131_B and m.group("after"):
                continue  # «0,178 0,212»: design and normative side by side, which is which is unknown
            v = _f(m.group("v"))
            if v is None:
                continue
            unit = zu_unit(m.group("u"))
            if (unit == "Вт/(м³·°С)" and not 0.05 <= v <= 1.5) or (unit == "кВт·ч/м²" and not 5 <= v <= 400):
                continue
            key = (m.group("v"), unit)
            if key in seen:
                continue
            seen.add(key)
            dec = (
                len(m.group("v").replace(".", ",").split(",")[-1]) if re.search(r"[.,]", m.group("v")) else 0
            )
            out.append(
                TextFact(
                    "ZU-131",
                    f"{_ru(v, dec)} {unit}",
                    v,
                    "number",
                    unit,
                    None,
                    0.85,
                    _ctx(t, m),
                    None,
                    None,
                    "specific",
                )
            )


# ── entry point ───────────────────────────────────────────────────────────────────────────────────


def extract(text: str, flags: frozenset[str] = frozenset()) -> list[TextFact]:
    """Every labelled value of the mix parameters on one page's text (deduplicated per page)."""
    t = normalize_text(text)
    if not HINT.search(t):
        return []
    found: list[TextFact] = []
    _extract_odi(t, flags, found)
    _extract_spzu(t, flags, found)
    _extract_ar(t, flags, found)
    _extract_kr(t, flags, found)
    _extract_zu(t, found)
    out: list[TextFact] = []
    for f in found:
        if not any(
            o.code == f.code and o.value == f.value and o.location == f.location and o.sub_id == f.sub_id
            for o in out
        ):
            out.append(f)
    return out


# ── ambiguity over the whole object ───────────────────────────────────────────────────────────────


def _key(v: dict[str, Any]) -> tuple[Any, Any]:
    n = v["value_norm"]
    return (n.get("value"), n.get("unit"))


def resolve_ambiguity(values: list[dict[str, Any]]) -> dict[str, int]:
    """Mark every ``tx.value`` of a (parameter, sub-check, location, stage) that prints several different values as
    ambiguous unless one value dominates (≥ 3 mentions and ≥ 2× the runner-up) or another stage prints the same
    reading (the reading both stages agree on stays comparable; the rest is set aside)."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for v in values:
        if v.get("fact_key") == FACT_KEY and v.get("param_code") in TX_CODES:
            q = v["value_norm"].get("qualifiers") or {}
            groups[
                (v["param_code"], q.get("sub_id") or "", v.get("location") or "OBJECT", v["stage"])
            ].append(v)
    stats = {"groups": len(groups), "ambiguous_groups": 0, "dominant_groups": 0, "agreed_groups": 0}
    by_slot: dict[tuple[str, str, str], dict[str, set[tuple[Any, Any]]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for (code, sub, loc, stage), vs in groups.items():
        by_slot[(code, sub, loc)][stage] = {_key(v) for v in vs}
    for (code, sub, loc, stage), vs in groups.items():
        counts = Counter(_key(v) for v in vs)
        if len(counts) == 1:
            continue
        ranked = counts.most_common()
        top, second = ranked[0][1], ranked[1][1]
        keep = ranked[0][0] if top >= 3 and top >= 2 * second else None
        others = set().union(*(k for s, k in by_slot[(code, sub, loc)].items() if s != stage))
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
