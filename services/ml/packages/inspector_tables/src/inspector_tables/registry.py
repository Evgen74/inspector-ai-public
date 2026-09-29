"""ID_REGISTRY: «Реестр приложений к акту АОСР» / «Реестр исполнительной документации» (95 R13, 97 §2.13).

Printed form (Новослободская АОСР, p. 3–5 of each act file): a header block «№ п/п | Наименование документа
| № чертежа, акта, разрешения, журнала и др. | Организация, составившая документ» with a column-number row,
then one ruled block per section under a bold title («Исполнительные геодезические схемы», «Результаты
лабораторных исследований…», «Документы, подтверждающие качество…»), continued on the next page without a
header. Contract columns: row_no, doc_name, doc_no, doc_date (split from «№ 284 от 20.02.2026»), sheets,
pages, note (the issuing organisation — a dedicated column is requested from AG-00).

The registry is the table of contents of an ИД binder: its sections and rows are what binder segmentation
(:mod:`inspector_tables.binder`) reconciles the page-level document types against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.grid import ColumnSpec, RawTable, TableSpec, find_continuation, find_tables
from inspector_tables.pagesource import PageData
from inspector_tables.text import fold, join_lines, squash

SPEC = TableSpec(
    table_type="ID_REGISTRY",
    anchor=r"^наименовани",
    columns=(
        ColumnSpec("row_no", (r"^№( п п)?$", r"^n п п$", r"^п п$", r"^№ пп$")),
        ColumnSpec("doc_name", (r"наименование документ", r"^наименовани")),
        ColumnSpec("doc_no", (r"чертежа", r"реквизит", r"номер документ", r"^№ документ", r"^номер$")),
        ColumnSpec("doc_date", (r"^дата",)),
        ColumnSpec("sheets", (r"листов", r"^кол во лист")),
        ColumnSpec("pages", (r"^стр", r"страниц")),
        ColumnSpec("note", (r"организаци", r"составивш", r"примечан")),
    ),
    required=frozenset({"doc_name"}),
    key_column="doc_name",
    caption=r"реестр",
)
PARSER_VERSION = "registry-1"
_NO_DATE = re.compile(r"№\s*(?P<no>[^\s].*?)\s+от\s+(?P<d>\d{1,2})[.\s](?P<m>\d{1,2})[.\s](?P<y>\d{4})")
_DATE = re.compile(r"(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})")
KEYS = ("row_no", "doc_name", "doc_no", "doc_date", "sheets", "pages", "note")

# registry section title → binder document kind (AG-03 seed doc_kind codes)
SECTION_KINDS: tuple[tuple[str, str], ...] = (
    (r"геодезическ\w* схем|исполнительн\w* схем|исполнительн\w* чертеж", "ISP_GEO_SCHEME"),
    (r"лабораторн|испытани|заключени|экспертиз", "LAB_OR_MEASUREMENT"),
    (r"качеств|сертификат|паспорт|декларац", "QUALITY_DOCS"),
    (r"акт", "AOSR"),
)


def section_kind(title: str | None) -> str | None:
    f = fold(title or "")
    for pat, kind in SECTION_KINDS:
        if re.search(pat, f):
            return kind
    return None


@dataclass(slots=True)
class RegistryRow:
    kind: str
    cells: dict[str, str]
    raw: object
    page_no: int
    section: str | None = None
    doc_no: str | None = None
    doc_date: str | None = None  # ISO


@dataclass(slots=True)
class LogicalRegistry:
    parts: list[RawTable]
    rows: list[RegistryRow] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    caption: str | None = None


def split_no_date(text: str) -> tuple[str | None, str | None]:
    """«№ 1А от 17.02.2026» → («1А», «2026-02-17»); «№004301 от 19.01.2026» → («004301», …)."""
    m = _NO_DATE.search(text or "")
    if m:
        return m.group("no").strip(), f"{m.group('y')}-{int(m.group('m')):02d}-{int(m.group('d')):02d}"
    m = _DATE.search(text or "")
    no = re.sub(r"^№\s*", "", text or "").strip() or None
    return (no, f"{m.group('y')}-{int(m.group('m')):02d}-{int(m.group('d')):02d}") if m else (no, None)


def _append_rows(reg: LogicalRegistry, t: RawTable, section: str | None) -> str | None:
    for r in t.rows:
        cells = {k: squash(r.text(k)) for k in KEYS}
        if not any(cells.values()):
            continue
        if (
            all(re.fullmatch(r"\d{1,2}", v) for v in cells.values() if v)
            and sum(1 for v in cells.values() if v) >= 3
        ):
            continue  # the «1 2 3 4» column-number row
        if r.merged:
            section = squash(r.merged_text)
            reg.rows.append(RegistryRow("SECTION_HEADER", {"doc_name": section}, r, t.page_no))
            continue
        if not cells["row_no"] and reg.rows and reg.rows[-1].kind == "DATA":
            prev = reg.rows[-1]
            for k, v in cells.items():
                if v:
                    prev.cells[k] = join_lines(prev.cells.get(k, ""), v)
            prev.doc_no, prev.doc_date = split_no_date(prev.cells.get("doc_no", ""))
            continue
        row = RegistryRow("DATA", cells, r, t.page_no, section)
        row.doc_no, row.doc_date = split_no_date(cells.get("doc_no", ""))
        if not row.doc_date and cells.get("doc_date"):
            _, row.doc_date = split_no_date(cells["doc_date"])
        reg.rows.append(row)
    return section


def parse_page(page: PageData, prev: LogicalRegistry | None = None) -> list[LogicalRegistry]:
    """Registries starting on this page; ``prev`` (the registry open at the end of the previous page) is
    extended in place when this page continues it."""
    out: list[LogicalRegistry] = []
    if prev is not None:
        section = next((r.cells["doc_name"] for r in reversed(prev.rows) if r.kind == "SECTION_HEADER"), None)
        below = 0.0
        while True:
            cont = find_continuation(page, prev.parts[-1], below=below)
            if cont is None:
                break
            if cont.caption:
                section = squash(cont.caption)
                prev.rows.append(RegistryRow("SECTION_HEADER", {"doc_name": section}, None, page.page_no))
            prev.parts.append(cont)
            section = _append_rows(prev, cont, section)
            below = cont.box.y1 + 1
    for t in find_tables(page, SPEC, allow_aligned=False):
        if not (t.caption and re.search(r"реестр", fold(t.caption))):
            continue
        reg = LogicalRegistry([t], caption=t.caption)
        section = _append_rows(reg, t, None)
        below = t.box.y1 + 1
        while True:
            cont = find_continuation(page, t, below=below)
            if cont is None:
                break
            if cont.caption:
                section = squash(cont.caption)
                reg.rows.append(RegistryRow("SECTION_HEADER", {"doc_name": section}, None, page.page_no))
            reg.parts.append(cont)
            section = _append_rows(reg, cont, section)
            below = cont.box.y1 + 1
        out.append(reg)
    return out


def finalize(reg: LogicalRegistry) -> None:
    data = [r for r in reg.rows if r.kind == "DATA"]
    nums = [r.cells.get("row_no") for r in data]
    reg.checks = [{"kind": "ROW_COUNT", "passed": True, "expected": None, "actual": len(data),
                   "detail": f"Документов в реестре: {len(data)}; разделов: {sum(1 for r in reg.rows if r.kind == 'SECTION_HEADER')}"}]  # fmt: skip
    if len(reg.parts) > 1:
        reg.checks.append({"kind": "CONTINUATION_JOINED", "passed": True, "expected": None, "actual": len(reg.parts),
                           "detail": f"Частей таблицы: {len(reg.parts)}, страницы {sorted({p.page_no for p in reg.parts})}"})  # fmt: skip
    # numbering restarts in every section: 1..n per section
    ok = True
    expect = 1
    for r in reg.rows:
        if r.kind == "SECTION_HEADER":
            expect = 1
            continue
        if (r.cells.get("row_no") or "").rstrip(".") != str(expect):
            ok = False
        expect += 1
    if nums:
        reg.checks.append({"kind": "ROW_COUNT", "passed": ok, "expected": None, "actual": None,
                           "detail": "Нумерация строк по разделам последовательна" if ok else "Нумерация строк реестра нарушена"})  # fmt: skip
