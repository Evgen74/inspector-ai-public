"""Engineering-system parameters compared through specification items (ГОСТ 21.110 ``spec.item`` of AG-02C):

* IOS1-068 — protection device ratings In, А (ВРУ/ГРЩ/щиты; ЭОМ specifications): any change for the same position
  and device family;
* IOS2-073 — pump characteristics Q, м³/ч / H, м / N, кВт: a decrease for the same position and pump kind;
* IOS4-076 — heating pipe diameters (Т1/Т2, Ду/Ø): any change for the same position, system and pipe kind;
* IOS4-077 — radiators/convectors: a smaller printed power (.b) or a smaller quantity (.a) of the same mark;
* IOS5-080 — fire alarm composition (АПС): a smaller quantity of the same detector / control panel type (.a).

The rule is the one of the cable/pipe comparison (``specitems``): a pure set difference without a shared mark is not
a finding. Two rows are the same element only when they share the printed position (or the printed mark for
radiators/АПС) **and** the product stem; the size that "changed" must not exist anywhere in the other stage for that
stem (a renumbered position is not a change); ambiguous rows (one key, several values in a stage) are dropped. One
finding per code and axis at location OBJECT (the pair with the largest relative change); printed values are the
attribute lists of the chosen pair.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from inspector_common.contracts.models import ExtractedValue
from inspector_compare.objectctx import FileInfo
from inspector_compare.valuecmp import AXIS_OF, ValueDiff

CODES = ("IOS1-068", "IOS2-073", "IOS4-076", "IOS4-077", "IOS5-080")

# Latin look-alikes → Cyrillic so «ВА», «BA», «А»/«A» compare equal.
_LOOK = str.maketrans("ABCEHKMOPTXYaceopxy", "АВСЕНКМОРТХУасеорху")


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_LOOK).replace("ё", "е").replace("Ё", "Е")).strip().lower()


def _num(s: str) -> float:
    return float(s.replace(",", ".").replace(" ", ""))


def _fmt(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _text(v: ExtractedValue) -> tuple[str, str, str]:
    q = dict(v.value_norm.qualifiers or {})
    name = str(q.get("name") or "")
    mark = str(q.get("type_mark") or "")
    return name, mark, str(q.get("section") or "")


def _position(v: ExtractedValue) -> str:
    q = dict(v.value_norm.qualifiers or {})
    pos = str(q.get("position") or "").strip().rstrip(".").strip()
    return "" if pos in ("", "-", "—", "–") else pos


# ── item recognisers ────────────────────────────────────────────────────────────────────────────────────────────

_BREAKER_HEAD = re.compile(
    r"^\W*(?:модульн\w+\s+)?(?:автоматическ\w+\s+выключател|выключател\w*\s+автоматическ|диф\w*\.?\s*автомат|"
    r"автомат\w*\s+защит|автоматы?\b|авдт|узо\b|ва\s?\d)",
    re.I,
)
_AMP = re.compile(r"(?<![\d.,\-/])(\d{1,4})\s*а(?![а-яa-z0-9])")
_BRAND = re.compile(r"(?<![\dА-Яа-яA-Za-z])([А-Яа-яA-Za-z]{2,6})\s?-?(\d{1,3}(?:-\d{1,3})?)(?![\d,.])")
_BRAND_SKIP = {"ip", "ка", "ма", "кв", "гост", "ту", "ип", "din"}
_POLES = re.compile(r"(?<![\d,.])([1-4])\s*(?:р|п)(?![а-я])|(одно|двух|трех|четырех)полюс")

_PUMP_HEAD = re.compile(
    r"^\W*(?:[а-я\-]+\s+){0,2}(?:насос|насосн\w+\s+(?:установк|агрегат|станц))",
    re.I,
)
_PUMP_SKIP = re.compile(r"конденсат|вакуум|ручн|шкаф|щит|диспетчер|кабел|люк|крышк|датчик", re.I)
_Q = re.compile(
    r"(?:(?<![а-яa-z])[qg]|подач[а-я]*|расход[а-я]*)\s*=?\s*(\d+(?:[.,]\d+)?)\s*м(?:³|3)\s*/\s*ч", re.I
)
_QLS = re.compile(
    r"(?:(?<![а-яa-z])[qg]|подач[а-я]*|расход[а-я]*)\s*=?\s*(\d+(?:[.,]\d+)?)\s*л\s*/\s*с", re.I
)
_H = re.compile(r"(?:(?<![а-яa-z])[нh]|напор\w*)\s*=?\s*(\d+(?:[.,]\d+)?)\s*м(?![а-яa-z²³])", re.I)
_N = re.compile(r"(?:(?<![а-яa-z])[nн№]\w{0,3}\.?|мощност\w*)\s*=?\s*(\d+(?:[.,]\d+)?)\s*квт", re.I)

_HEAT = re.compile(r"отоплен|(?<![а-яa-z\d])т(?:1|2|11|21)(?![\d,.])", re.I)
_HEAT_TAG = re.compile(r"(?<![а-яa-z\d])(т(?:11|21|1|2))(?![\d,.])", re.I)
_PIPE = re.compile(r"труб", re.I)
_PIPE_SKIP = re.compile(r"гильз|футляр|изоляц|отвод|переход|тройник|заглушк|фланец", re.I)
_DN = re.compile(
    r"(?:(?<![а-я])ду|\bdn)\s*=?\s*(\d{2,4})|[∅ø⌀]\s*(\d{2,4})|(?<![a-zа-я])d\s*=?\s*(\d{2,4})(?!\d)", re.I
)

_RAD_HEAD = re.compile(r"^\W*(?:[а-я\-\"«»]+\s+){0,3}(?:радиатор|конвектор|отопительн\w+\s+прибор)", re.I)
_RAD_SKIP = re.compile(
    r"^\W*(?:клапан|набор|узел|кран|вентил|кронштейн|термо|головк|заглушк|пробк|комплект)", re.I
)
_RAD_SIZE = re.compile(r"(?<![\d.,-])(\d{2}-\d{3}-\d{3,4})(?![\d-])")
_RAD_MODEL = re.compile(r"[\"«“„]\s*([^\"«»“”„]{2,30}?)\s*[\"»”“]")
_RAD_CODE = re.compile(r"(?<![а-яa-z])[а-яa-z]{2,5}\s?\d{1,3}(?:[.\-]\d{1,3}){1,3}(?![\d.\-])")
_WATT = re.compile(r"(?<![\d.,])(\d{2,5})\s*вт(?![а-я/])", re.I)

_APS_DETECTOR = re.compile(r"^\W*извещател\w*\s+(?:пожарн|дымов|тепловой|ручн|пламен|газов)", re.I)
_APS_PANEL = re.compile(r"^\W*(?:прибор\s+приемно-контрольн\w+\s+(?:и\s+управлен\w+\s+)?(?:пожар|охранно-пожар)|"
                        r"прибор\s+(?:пожарный\s+)?управлен\w+|контроллер\s+двухпроводной)", re.I)  # fmt: skip
_APS_SKIP = re.compile(r"охранн|кожух|оповещат|сот\b|системы охранной", re.I)


@dataclass(slots=True)
class Rec:
    v: ExtractedValue
    code: str
    sub_id: str | None
    pos: str  # printed position/mark part of the pairing key
    stem: str
    attrs: dict[str, float]
    labels: dict[str, str]
    system: str = ""
    file_id: str = ""
    qty: float | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.pos, self.stem, self.system)


def _qty(v: ExtractedValue) -> float | None:
    val = v.value_norm.value
    return float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else None


def _single(rx: re.Pattern[str], text: str, conv: float = 1.0) -> float | None:
    vals = {round(_num(m.group(1)) * conv, 4) for m in rx.finditer(text)}
    return next(iter(vals)) if len(vals) == 1 else None


def parse_breaker(v: ExtractedValue) -> Rec | None:
    name, mark, _ = _text(v)
    text = _fold(f"{name} {mark}")
    if not _BREAKER_HEAD.search(text):
        return None
    ratings = {int(m.group(1)) for m in _AMP.finditer(text)}
    if len(ratings) != 1:
        return None
    (rating,) = ratings
    # a rating range («0,63-1,0А») or a setting interval is not one nominal
    if re.search(r"\d\s*[-–]\s*\d[\d,.]*\s*а(?![а-я])", text):
        return None
    brands = [f"{a}{b}" for a, b in _BRAND.findall(text) if a not in _BRAND_SKIP]
    poles = _POLES.search(text)
    pole = (
        (poles.group(1) or {"одно": "1", "двух": "2", "трех": "3", "четырех": "4"}[poles.group(2)])
        if poles
        else ""
    )
    stem = f"{brands[0] if brands else re.sub(r'[\d,.]+', '', text)[:40]}|{pole}"
    return Rec(
        v,
        "IOS1-068",
        None,
        _position(v),
        stem,
        {"In": float(rating)},
        {"In": f"{rating} А"},
        file_id=v.file_id,
    )


def parse_pump(v: ExtractedValue) -> Rec | None:
    name, mark, _ = _text(v)
    text = _fold(f"{name} {mark}")
    if not _PUMP_HEAD.search(text) or _PUMP_SKIP.search(text):
        return None
    attrs: dict[str, float] = {}
    labels: dict[str, str] = {}
    q = _single(_Q, text)
    if q is None:
        ls = _single(_QLS, text, 3.6)
        q = ls
    if q is not None:
        attrs["Q"], labels["Q"] = q, f"Q={_fmt(q)} м³/ч"
    h = _single(_H, text)
    if h is not None and h > 0:
        attrs["H"], labels["H"] = h, f"H={_fmt(h)} м"
    n = _single(_N, text)
    if n is not None and n > 0:
        attrs["N"], labels["N"] = n, f"N={_fmt(n)} кВт"
    if not attrs:
        return None
    words = []
    for w in re.split(r"\s+", text):
        if re.search(r"[\d=]|[a-z]", w):
            break
        words.append(w.strip(",;"))
    stem = " ".join(words[:6])
    return Rec(v, "IOS2-073", None, _position(v), stem, attrs, labels, file_id=v.file_id)


def parse_heating_pipe(v: ExtractedValue) -> Rec | None:
    name, mark, section = _text(v)
    text = _fold(f"{name} {mark}")
    context = _fold(f"{section} {text}")
    if not _PIPE.search(text) or _PIPE_SKIP.search(text) or not _HEAT.search(context):
        return None
    m = _DN.search(text)
    pos = _position(v)
    if not m or not pos:
        return None
    dn = _num(next(g for g in m.groups() if g))
    tag = _HEAT_TAG.search(context)
    system = tag.group(1) if tag else "отопление"
    stem = re.sub(r"[^а-яa-z]+", " ", _DN.sub(" ", text)).strip()[:60]
    return Rec(v, "IOS4-076", None, pos, stem, {"Ду": dn}, {"Ду": f"Ду {_fmt(dn)}"}, system, v.file_id)


def parse_radiator(v: ExtractedValue) -> Rec | None:
    name, mark, _ = _text(v)
    text = _fold(name)
    if not _RAD_HEAD.search(text) or _RAD_SKIP.search(text):
        return None
    size = _RAD_SIZE.search(text)
    quoted = _RAD_MODEL.search(name)
    model = _fold(quoted.group(1) if quoted else "")
    code = _RAD_CODE.search(text)
    if not size and not code:  # a mark is the model with its size/catalog code; a bare type is not a mark
        return None
    mark_key = f"{model or _fold(mark)}|{size.group(1) if size else ''}|{code.group(0) if code else ''}"
    attrs: dict[str, float] = {}
    labels: dict[str, str] = {}
    w = _single(_WATT, text)
    if w is not None:
        attrs["Вт"], labels["Вт"] = w, f"{_fmt(w)} Вт"
    qty = _qty(v)
    label = (quoted.group(1).strip() if quoted else mark.strip() or name.strip()[:30]) + (
        f" {size.group(1)}" if size else ""
    )
    if qty is not None:
        labels["qty"] = f"{label}: {_fmt(qty)} шт."
    return Rec(
        v,
        "IOS4-077",
        "IOS4-077.b" if attrs else "IOS4-077.a",
        mark_key,
        "",
        attrs,
        labels,
        "",
        v.file_id,
        qty,
    )


def parse_aps(v: ExtractedValue) -> Rec | None:
    name, mark, section = _text(v)
    text = _fold(f"{name} {mark}")
    if (
        _APS_SKIP.search(text)
        or re.search(r"сотс|охранн|аупт|соуэ", _fold(section))
        or not (_APS_DETECTOR.search(text) or _APS_PANEL.search(text))
    ):
        return None
    qty = _qty(v)
    if qty is None:
        return None
    stem = re.sub(r"\s+", " ", re.sub(r"[,;(].*$", "", text))[:80]
    model = re.sub(r"\s+", "", text)[-30:]
    return Rec(v, "IOS5-080", "IOS5-080.a", "", f"{stem}|{model}", {}, {"qty": f"{name.strip()[:60]}: {_fmt(qty)} шт."},
               "", v.file_id, qty)  # fmt: skip


_PARSERS = {
    "ЭОМ": (parse_breaker,),
    "ВК": (parse_pump,),
    "ОВ": (parse_pump, parse_heating_pipe, parse_radiator),
    "СС": (parse_aps,),
    "ПБ": (parse_aps,),
}


def parse_item(v: ExtractedValue, marks: tuple[str, ...]) -> list[Rec]:
    """Records of one spec item, by the discipline of its file (files without marks are not read)."""
    seen: dict[int, None] = {}
    out: list[Rec] = []
    for mark in marks:
        for fn in _PARSERS.get(mark, ()):
            if id(fn) in seen:
                continue
            seen[id(fn)] = None
            r = fn(v)
            if r is not None:
                out.append(r)
    return out


# ── comparison ─────────────────────────────────────────────────────────────────────────────────────────────────

_RULE = {  # code → (attribute, direction) list; direction ANY | DECREASE
    "IOS1-068": (("In", "ANY"),),
    "IOS2-073": (("Q", "DECREASE"), ("H", "DECREASE"), ("N", "DECREASE")),
    "IOS4-076": (("Ду", "ANY"),),
    "IOS4-077": (("Вт", "DECREASE"),),
}
_UNIT = {"IOS1-068": "А", "IOS2-073": "м³/ч", "IOS4-076": "мм", "IOS4-077": "Вт", "IOS5-080": "шт."}
_PAIRS = (("PD", "RD"), ("RD", "ID"))


@dataclass(slots=True)
class _Hit:
    rel: float
    exp: Rec
    act: Rec
    attr: str
    exp_val: float
    act_val: float
    sub_id: str | None
    changes: list[str] = field(default_factory=list)


def _unique(recs: Iterable[Rec]) -> dict[tuple[str, str, str], Rec | None]:
    """key → the record; ``None`` when one key is printed with different values in the stage (ambiguous)."""
    out: dict[tuple[str, str, str], Rec | None] = {}
    for r in recs:
        if not r.pos and r.code in ("IOS1-068", "IOS2-073", "IOS4-076"):
            continue
        sig = (tuple(sorted(r.attrs.items())), r.qty)
        if r.key in out:
            prev = out[r.key]
            if prev is None or (tuple(sorted(prev.attrs.items())), prev.qty) != sig:
                out[r.key] = None
            continue
        out[r.key] = r
    return out


def _attr_hits(code: str, exp: list[Rec], act: list[Rec]) -> list[_Hit]:
    hits: list[_Hit] = []
    e_map, a_map = _unique(exp), _unique(act)
    a_by_stem: dict[tuple[str, str], set[tuple[str, float]]] = defaultdict(set)
    e_by_stem: dict[tuple[str, str], set[tuple[str, float]]] = defaultdict(set)
    for r in act:
        for k, x in r.attrs.items():
            a_by_stem[(r.stem, r.system)].add((k, x))
    for r in exp:
        for k, x in r.attrs.items():
            e_by_stem[(r.stem, r.system)].add((k, x))
    for key, e in e_map.items():
        a = a_map.get(key)
        if e is None or a is None:
            continue
        changes: list[_Hit] = []
        for attr, direction in _RULE.get(code, ()):
            if attr not in e.attrs or attr not in a.attrs:
                continue
            ev, av = e.attrs[attr], a.attrs[attr]
            if av == ev or (direction == "DECREASE" and av > ev):
                continue
            stem_key = (e.stem, e.system)
            if (attr, ev) in a_by_stem[
                stem_key
            ]:  # the expected size still exists in the other stage: renumbering
                continue
            if direction == "ANY" and (attr, av) in e_by_stem[stem_key]:
                continue
            changes.append(_Hit(abs(ev - av) / ev if ev else 1.0, e, a, attr, ev, av, e.sub_id))
        if changes:
            best = max(changes, key=lambda h: h.rel)
            best.changes = [f"{h.exp.labels[h.attr]}→{h.act.labels[h.attr]}" for h in changes]
            hits.append(best)
    return hits


def _count_hits(code: str, exp: list[Rec], act: list[Rec]) -> list[_Hit]:
    """Quantity of the same mark/type: a decrease, only when exactly one file per stage prints the mark."""
    per: dict[str, dict[str, dict[tuple[str, str, str], float]]] = {
        "e": defaultdict(dict),
        "a": defaultdict(dict),
    }
    recs: dict[tuple[str, tuple[str, str, str]], Rec] = {}
    for tag, rs in (("e", exp), ("a", act)):
        for r in rs:
            if r.qty is None or r.sub_id not in ("IOS4-077.a", "IOS4-077.b", "IOS5-080.a"):
                continue
            files = per[tag][r.file_id]
            files[r.key] = files.get(r.key, 0.0) + r.qty
            recs.setdefault((tag, r.key), r)
    hits: list[_Hit] = []
    keys = {k for f in per["e"].values() for k in f} & {k for f in per["a"].values() for k in f}
    for key in keys:
        efiles = [f[key] for f in per["e"].values() if key in f]
        afiles = [f[key] for f in per["a"].values() if key in f]
        if len(efiles) != 1 or len(afiles) != 1 or afiles[0] >= efiles[0]:
            continue
        e, a = recs[("e", key)], recs[("a", key)]
        hits.append(
            _Hit(
                (efiles[0] - afiles[0]) / efiles[0],
                e,
                a,
                "qty",
                efiles[0],
                afiles[0],
                "IOS5-080.a" if code == "IOS5-080" else "IOS4-077.a",
            )
        )
    return hits


def _verified_pair(code: str, exp: list[Rec], act: list[Rec]) -> tuple[Rec, Rec] | None:
    """One unambiguous pair of the same key that shares a compared attribute (or a quantity) in both stages."""
    e_map, a_map = _unique(exp), _unique(act)
    for key, e in e_map.items():
        a = a_map.get(key)
        if e is None or a is None:
            continue
        if any(attr in e.attrs and attr in a.attrs for attr, _ in _RULE.get(code, ())):
            return e, a
        if code in ("IOS4-077", "IOS5-080") and e.qty is not None and a.qty is not None:
            return e, a
    return None


def spec_param_diffs(
    values: Iterable[ExtractedValue], files: Mapping[str, FileInfo], axes: Iterable[str] = ("PD_RD", "RD_ID")
) -> list[ValueDiff]:
    by_stage: dict[str, dict[str, list[Rec]]] = defaultdict(lambda: defaultdict(list))
    for v in values:
        if v.fact_key != "spec.item":
            continue
        stage = str(v.stage.value if hasattr(v.stage, "value") else v.stage)
        if stage not in ("PD", "RD", "ID"):
            continue
        info = files.get(v.file_id)
        if info is None or not info.marks:
            continue
        for r in parse_item(v, info.marks):
            by_stage[r.code][stage].append(r)
    allowed = set(axes)
    out: list[ValueDiff] = []
    for code in CODES:
        stages = by_stage.get(code)
        if not stages:
            continue
        for exp_stage, act_stage in _PAIRS:
            axis = AXIS_OF[(exp_stage, act_stage)]
            if axis not in allowed or not stages.get(exp_stage) or not stages.get(act_stage):
                continue
            exp, act = stages[exp_stage], stages[act_stage]
            hits = _attr_hits(code, exp, act)
            if code == "IOS5-080" or code == "IOS4-077":
                hits += _count_hits(code, exp, act)
            if not hits:
                pair = _verified_pair(code, exp, act)
                if pair is not None:  # compared and equal (or the change is a renumbering): verified coverage
                    out.append(
                        ValueDiff(
                            code=code, sub_id=None, axis=axis, room="OBJECT", location_type="OBJECT",
                            outcome="EQUAL", discrepancy_type=None, expected_stage=exp_stage,
                            actual_stage=act_stage, expected=pair[0].v, actual=pair[1].v, unit=_UNIT[code],
                            confidence=round(min(pair[0].v.confidence, pair[1].v.confidence) * 0.8, 3),
                            mode="SPEC_ITEM",
                        )
                    )  # fmt: skip
                continue
            h = max(hits, key=lambda x: x.rel)
            if h.attr == "qty":
                pd_txt, act_txt = h.exp.labels["qty"], h.act.labels["qty"]
            else:
                pd_txt = "; ".join(c.split("→")[0] for c in h.changes)
                act_txt = "; ".join(c.split("→")[1] for c in h.changes)
            if code == "IOS1-068":
                pos = h.exp.pos
                pd_txt, act_txt = f"Поз. {pos}: {pd_txt}", f"Поз. {pos}: {act_txt}"
            out.append(
                ValueDiff(
                    code=code,
                    sub_id=h.sub_id,
                    axis=axis,
                    room="OBJECT",
                    location_type="OBJECT",
                    outcome="VIOLATION",
                    discrepancy_type="VALUE_DECREASED" if h.act_val < h.exp_val else "VALUE_INCREASED",
                    expected_stage=exp_stage,
                    actual_stage=act_stage,
                    expected=h.exp.v,
                    actual=h.act.v,
                    delta_abs=round(h.act_val - h.exp_val, 3),
                    delta_rel=round(h.rel, 4),
                    unit=_UNIT[code],
                    confidence=round(min(h.exp.v.confidence, h.act.v.confidence) * 0.8, 3),
                    mode="SPEC_ITEM",
                    texts={f"{exp_stage.lower()}_value": pd_txt, f"{act_stage.lower()}_value": act_txt},
                )
            )
    return out
