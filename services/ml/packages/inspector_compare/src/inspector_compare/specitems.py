"""ЭОМ/ВК specification items PD↔RD (ГОСТ 21.110 ``spec.item`` values of AG-02C): cable cross-section decreases
(IOS1-069.a) and pipe diameter decreases (IOS2-071 water В1/Т3, IOS3-074 sewer К1/К2).

The same position is not the same line across stages by itself, so the rule is deliberately strict:

* both items come from files of the discipline (ЭОМ for cables, ВК for pipes) on PD and RD;
* the items share the printed position («Поз.») **and** the product stem (cable brand and core count, e.g.
  «ВВГнг(А)-LS 5×»; the pipe's name without numbers);
* the RD section/diameter is smaller than the PD one **and** the PD size of that stem appears nowhere in the RD
  specification (the larger cable/pipe really disappeared, not a renumbered position);
* signal cables (pairs «1×2×0,5»), heating/refrigerant pipes and items without a system are skipped.

One finding per code at location OBJECT (the pair with the largest relative decrease); values print as
«5×10 мм²» / «Ду 50».
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from inspector_common.contracts.models import ExtractedValue
from inspector_compare.objectctx import FileInfo
from inspector_compare.valuecmp import ValueDiff

_CABLE = re.compile(r"кабел|провод", re.I)
_CABLE_SKIP = re.compile(
    r"коробк|лоток|кабельн\w*\s+(ввод|канал|лот)|муфт|наконечн|сальник|труб|\d\s*[xх×]\s*\d+\s*[xх×]", re.I
)
_SECTION = re.compile(r"(?<![\dxх×.,])(\d{1,2})\s*[xх×]\s*(\d{1,3}(?:[.,]\d{1,2})?)(?![\dxх×])")
_BRAND = re.compile(r"(?<![А-Яа-яA-Za-z])([А-ЯA-Z]{2,}[а-яa-z]{0,3}(?:\([АA]\))?(?:-[A-Za-zА-Яа-я]+)*)")
_BRAND_SKIP = {"ГОСТ", "ТУ", "IP", "ITK", "VRF", "UTP", "PVCLS", "ЖЗ"}
_PIPE = re.compile(r"труб", re.I)
_PIPE_SKIP = re.compile(
    r"отоплен|теплоснаб|теплов\w*\s+сет|холодоснаб|хладо|фреон|медн|гильз|футляр|изоляц", re.I
)
_DN = re.compile(r"(?:\bду|\bdn)\s*=?\s*(\d{2,4})|[∅ø⌀Ø]\s*(\d{2,4})|\bd\s*=?\s*(\d{2,4})\b", re.I)
_SEWER = re.compile(r"канализ|водоотвед|\bк[123]\b|выпуск", re.I)
_WATER = re.compile(r"водопровод|водоснабж|\bв[12]\b|\bт[34]\b|\bхвс\b|\bгвс\b|питьев", re.I)


@dataclass(slots=True)
class Item:
    value: ExtractedValue
    code: str
    position: str
    stem: str
    size: float
    label: str


def _q(v: ExtractedValue) -> dict:
    return dict(v.value_norm.qualifiers or {})


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _fmt(x: float) -> str:
    return (f"{x:g}").replace(".", ",")


def parse_item(v: ExtractedValue, marks: tuple[str, ...]) -> Item | None:
    q = _q(v)
    pos = str(q.get("position") or "").strip()
    text = " ".join(str(q.get(k) or "") for k in ("name", "type_mark")).strip()
    context = f"{q.get('section') or ''} {text}"
    if not pos or not text:
        return None
    if "ЭОМ" in marks and _CABLE.search(text) and not _CABLE_SKIP.search(text):
        m = _SECTION.search(text)
        brands = [b for b in _BRAND.findall(text) if b not in _BRAND_SKIP]
        if not m or not brands:
            return None
        cores, section = m.group(1), _num(m.group(2))
        return Item(
            v, "IOS1-069", pos, f"{brands[0].upper()} {cores}×", section, f"{cores}×{_fmt(section)} мм²"
        )
    if "ВК" in marks and _PIPE.search(text) and not _PIPE_SKIP.search(context):
        code = "IOS3-074" if _SEWER.search(context) else ("IOS2-071" if _WATER.search(context) else None)
        m = _DN.search(text)
        if code is None or not m:
            return None
        dn = _num(next(g for g in m.groups() if g))
        stem = re.sub(r"[^а-яa-z]+", " ", _DN.sub(" ", text).lower()).strip()[:60]
        return Item(v, code, pos, stem, dn, f"Ду {_fmt(dn)}")
    return None


def spec_diffs(values: Iterable[ExtractedValue], files: dict[str, FileInfo]) -> list[ValueDiff]:
    items: dict[str, list[Item]] = defaultdict(list)  # stage → items
    for v in values:
        if v.fact_key != "spec.item":
            continue
        stage = str(v.stage.value if hasattr(v.stage, "value") else v.stage)
        if stage not in ("PD", "RD"):
            continue
        info = files.get(v.file_id)
        it = parse_item(v, info.marks if info is not None else ())
        if it is not None:
            items[stage].append(it)
    rd_sizes: dict[tuple[str, str], set[float]] = defaultdict(set)
    rd_by_key: dict[tuple[str, str, str], list[Item]] = defaultdict(list)
    for it in items["RD"]:
        rd_sizes[(it.code, it.stem)].add(it.size)
        rd_by_key[(it.code, it.position, it.stem)].append(it)
    best: dict[str, tuple[float, Item, Item]] = {}
    for pd in items["PD"]:
        rds = rd_by_key.get((pd.code, pd.position, pd.stem)) or []
        if not rds or pd.size in rd_sizes[(pd.code, pd.stem)]:
            continue
        if max(r.size for r in rds) >= pd.size:
            continue
        rd = max(rds, key=lambda r: r.size)
        rel = (pd.size - rd.size) / pd.size
        if pd.code not in best or rel > best[pd.code][0]:
            best[pd.code] = (rel, pd, rd)
    out = []
    for code, (rel, pd, rd) in sorted(best.items()):
        out.append(
            ValueDiff(
                code=code,
                sub_id="IOS1-069.a" if code == "IOS1-069" else None,
                axis="PD_RD",
                room="OBJECT",
                location_type="OBJECT",
                outcome="VIOLATION",
                discrepancy_type="VALUE_DECREASED",
                expected_stage="PD",
                actual_stage="RD",
                expected=pd.value,
                actual=rd.value,
                delta_abs=round(rd.size - pd.size, 3),
                delta_rel=round(rel, 4),
                unit="мм²" if code == "IOS1-069" else "мм",
                confidence=round(min(pd.value.confidence, rd.value.confidence) * 0.8, 3),
                mode="SPEC_ITEM",
                texts={"pd_value": pd.label, "rd_value": rd.label},
            )
        )
    return out
