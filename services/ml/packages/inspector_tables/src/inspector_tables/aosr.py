"""AOSR: «Акт освидетельствования скрытых работ» form fields (95 R13; RD-11-02 form, п.1–7).

The acts are Word/Aspose PDFs with a clean text layer (95: 80/80 Новослободская acts, 9/9 fields); scanned
acts go through PageTokens. Fields → contract AOSR columns: act_no, act_date, work_name (п.1), rd_refs
(п.2 — design documents with «изм. N»), materials (п.3), quality_docs (п.4 — executive schemes, protocols),
start_date / end_date (п.5, ISO), next_works (п.7), deviations (only when «Дополнительные сведения» mention
deviations). ``doc_refs`` splits п.2/п.4 into (code, revision) pairs for the revision-currency and cipher
checks (RT-10: F0196 п.4 cites «АНО1301211-Р-ОВ1», a cipher typo of АНО/150321/1-РД-ОВ1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.text import squash

PARSER_VERSION = "aosr-1"
MONTHS = {m: i for i, m in enumerate(
    ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"], 1)}  # fmt: skip

_HINT = (
    r"\(\s*(?:наименовани|номер,|исполнительные\s+схемы|наименования\s+и\s+структурные|наименования?\s+работ)"
)
FIELDS: tuple[tuple[str, str], ...] = (
    ("work_name", r"1\.\s*К\s+освидетельствованию\s+предъявлены\s+следующие\s+работы\s*:\s*(.+?)" + _HINT),
    ("rd_refs", r"2\.\s*Работы\s+выполнены\s+по\s+проектной\s+документации\s*(.+?)" + _HINT),
    ("materials", r"3\.\s*При\s+выполнении\s+работ\s+применены\s*:\s*(.+?)" + _HINT),
    ("quality_docs", r"4\.\s*Предъявлены\s+документы[^:]*:\s*(.+?)" + _HINT),
    ("norms", r"6\.\s*Работы\s+выполнены\s+в\s+соответствии\s+с\s*(.+?)" + _HINT),
    ("next_works", r"7\.\s*Разрешается\s+производство\s+последующих\s+работ\s*(.+?)" + _HINT),
    ("extra", r"Дополнительные\s+сведения\s*(.+?)\s*Акт\s+составлен"),
)
_ACT = re.compile(r"освидетельствования\s+скрытых\s+работ\s*№\s*([^\s«][^\n«]{0,40}?)\s*(?:«|\n|$)", re.I)
_DATE_RU = re.compile(r"«?\s*(\d{1,2})\s*»?\s*([а-я]+)\s+(\d{4})", re.I)


def _iso(d: str, month: str, y: str) -> str | None:
    m = MONTHS.get(month.lower())
    return f"{y}-{m:02d}-{int(d):02d}" if m else None


@dataclass(slots=True)
class AosrAct:
    cells: dict[str, str]
    doc_refs: list[dict] = field(default_factory=list)
    fields_found: int = 0


def parse_act_text(text: str) -> AosrAct | None:
    """The act fields from the text of its first pages; None when the text is not an АОСР."""
    t = text.replace(" ", " ")
    m = _ACT.search(t)
    if not m:
        return None
    cells: dict[str, str] = {"act_no": squash(m.group(1)).rstrip(".")}
    after = t[m.end() - 1 : m.end() + 200]
    dm = _DATE_RU.search(after)
    if dm:
        cells["act_date"] = _iso(dm.group(1), dm.group(2), dm.group(3)) or ""
    flat = re.sub(r"\s+", " ", t)
    found = 1
    for key, rx in FIELDS:
        fm = re.search(rx, flat, re.S | re.I)
        if fm:
            val = squash(fm.group(1))
            val = re.sub(r"\s\d{1,3}\s*$", "", val)  # page-number stamp caught at the end
            cells[key] = val
            found += 1
    dates = re.search(
        r"5\.\s*Даты\s*:\s*начала\s+работ\s*(.+?)окончания\s+работ\s*(.+?)(?:6\.|$)", flat, re.S | re.I
    )
    if dates:
        s = _DATE_RU.search(dates.group(1))
        e = _DATE_RU.search(dates.group(2))
        if s:
            cells["start_date"] = _iso(*s.groups()) or ""
        if e:
            cells["end_date"] = _iso(*e.groups()) or ""
        found += 1
    extra = cells.pop("extra", "")
    if extra and re.search(r"отклонени", extra, re.I):
        cells["deviations"] = extra
    cells.pop("norms", None)
    act = AosrAct({k: v for k, v in cells.items() if v}, fields_found=found)
    act.doc_refs = doc_refs(cells.get("rd_refs", ""), "rd_refs") + doc_refs(
        cells.get("quality_docs", ""), "quality_docs"
    )
    return act


def doc_refs(text: str, source: str) -> list[dict]:
    """Document codes cited in a field with their «изм. N» when printed: «АНО/150321/1-РД-ОВ1 - изм. 3»,
    «17_ПД/25-СВГ», «АНО1301211-Р-ОВ1». Axis notation («1-2.8/А-1.Л») is not a code: a code has a letter
    segment of two or more letters."""
    from inspector_docproc.codefix import is_code_like

    out: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r"[^\s,;«»\"()]+", text or ""):
        tok = m.group(0).strip(".:№")
        if (
            not is_code_like(tok)
            or not re.search(r"[A-Za-zА-Яа-яЁё]{2,}", tok)
            or re.fullmatch(r"[\d.\-/]+", tok)
        ):
            continue
        if tok in seen:
            continue
        rev = re.match(r"\s*[-–]\s*изм\.?\s*(\d+)", text[m.end() : m.end() + 20], re.I)
        out.append({"code": tok, "revision": int(rev.group(1)) if rev else None, "source": source})
        seen.add(tok)
    return out
