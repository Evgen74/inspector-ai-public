"""CHANGE_LOG: change registers of a document set.

Two printed forms feed the same contract table:

* «Разрешение на внесение изменений» (ГОСТ Р 21.101 прил. Л; the RD binders F0201–F0204 p5–6):
  Изм. | Лист | Содержание изменения | Код | Примечание, plus the permit number and the document code above;
* «Таблица регистрации изменений» (ГОСТ Р 21.101): Изм. | Номера листов (измененных, замененных, новых,
  аннулированных) | Всего листов | Номер док. | Подп. | Дата.

Contract columns: change_no, sheets_changed, sheets_replaced, sheets_new, sheets_cancelled, total_sheets,
doc_no (the permit / notice number), signature, date, note. The permit's «Содержание изменения» and «Код» have
no column of their own yet (requested from AG-00): the note carries «<содержание> [код N]; <примечание>».
A title-block stamp (Изм. | Кол.уч | Лист | № док. | Подп. | Дата) is not a change register (AG-02B reads it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.grid import ColumnSpec, RawTable, TableSpec, find_tables
from inspector_tables.pagesource import PageData
from inspector_tables.text import fold, squash

SPEC = TableSpec(
    table_type="CHANGE_LOG",
    anchor=r"^содержани|^заменен|^аннулир",
    columns=(
        ColumnSpec("change_no", (r"^изм",)),
        ColumnSpec("sheets_changed", (r"^лист$", r"^номера? лист", r"измененн")),
        ColumnSpec("sheets_replaced", (r"замененн",)),
        ColumnSpec("sheets_new", (r"^новых",)),
        ColumnSpec("sheets_cancelled", (r"аннулир",)),
        ColumnSpec("total_sheets", (r"^всего",)),
        ColumnSpec("_content", (r"^содержани",)),
        ColumnSpec("_code", (r"^код$",)),
        ColumnSpec("doc_no", (r"номер док|^№ ?док|^n ?док",)),
        ColumnSpec("signature", (r"^подп",)),
        ColumnSpec("date", (r"^дата",)),
        ColumnSpec("note", (r"примечан",)),
    ),
    required=frozenset({"change_no"}),
    key_column="_content",
    content_keys=(("change_no", "int"),),
)
PARSER_VERSION = "changelog-1"
_PERMIT = re.compile(r"^разрешени")
_CODE_LINE = re.compile(r"^(обозначение|шифр)$")


@dataclass(slots=True)
class ChangeRow:
    cells: dict[str, str]
    raw: object
    page_no: int


@dataclass(slots=True)
class LogicalChangeLog:
    parts: list[RawTable]
    rows: list[ChangeRow] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    permit_no: str | None = None
    document_code: str | None = None
    caption: str | None = None


def _permit_header(page: PageData, top: float) -> tuple[str | None, str | None]:
    """Permit number (in the cell under «Разрешение») and document code (right of «Обозначение»)."""
    permit = code = None
    above = [w for w in page.words if w.cy < top]
    for w in above:
        f = fold(w.text)
        if permit is None and _PERMIT.match(f):
            col = [
                x
                for x in above
                if x.cy > w.cy + 1 and x.cy - w.cy < 80 and x.x1 > w.x0 - 20 and x.x0 < w.x1 + 20
            ]
            cand = sorted((x for x in col if re.fullmatch(r"\d{1,5}[-/]\d{2,4}", x.text)), key=lambda x: x.cy)
            permit = cand[0].text if cand else None
        if code is None and _CODE_LINE.match(f):
            right = [x for x in above if abs(x.cy - w.cy) < max(w.h, 4) and x.x0 > w.x1]
            cand = [
                x.text
                for x in sorted(right, key=lambda x: x.x0)
                if re.search(r"[/\-]", x.text) and re.search(r"\d", x.text)
            ]
            code = cand[0] if cand else None
    return permit, code


_STAMP = re.compile(r"^(изм внес|изм внес|составил|гип|утвердил|утв|н контр|разработал|проверил)")


def parse_page(page: PageData) -> list[LogicalChangeLog]:
    out = []
    for t in find_tables(page, SPEC, allow_aligned=False):
        keys = set(t.keys)
        is_permit = "_content" in keys
        is_gost = bool(keys & {"sheets_replaced", "sheets_new", "sheets_cancelled", "total_sheets"})
        if not (is_permit or is_gost):
            continue
        permit, code = _permit_header(page, t.box.y0) if is_permit else (None, None)
        lg = LogicalChangeLog([t], permit_no=permit, document_code=code, caption=t.caption)
        for r in t.rows:
            cells = {k: squash(r.text(k)) for k in (c.key for c in t.columns if c.key)}
            if not any(cells.values()) or (r.merged and not cells.get("change_no")):
                continue
            if cells.get("change_no") and not re.fullmatch(r"\d{1,3}", cells["change_no"]):
                if _STAMP.match(fold(cells["change_no"])) or not lg.rows:
                    break  # the title block under the register
                continue
            if (
                all(re.fullmatch(r"\d{1,2}", v) for v in cells.values() if v)
                and sum(1 for v in cells.values() if v) >= 4
            ):
                continue  # column-number row
            content, ccode, remark = cells.pop("_content", ""), cells.pop("_code", ""), cells.get("note", "")
            parts = [content + (f" [код {ccode}]" if ccode else "")] if content else []
            if (remark and remark not in ("-//-", "—", "-")) or (remark and parts):
                parts.append(remark)
            cells["note"] = "; ".join(p for p in parts if p)
            if permit and not cells.get("doc_no"):
                cells["doc_no"] = permit
            if not cells.get("change_no") and lg.rows and not cells.get("sheets_changed"):
                prev = lg.rows[-1].cells
                prev["note"] = squash(prev.get("note", "") + " " + cells["note"])
                continue
            lg.rows.append(ChangeRow(cells, r, t.page_no))
        if lg.rows:
            nums = {r.cells.get("change_no") for r in lg.rows if r.cells.get("change_no")}
            lg.checks.append({"kind": "ROW_COUNT", "passed": True, "expected": None, "actual": len(lg.rows),
                              "detail": f"Изменения: {', '.join(sorted(nums))}; разрешение {permit or '—'}"})  # fmt: skip
            out.append(lg)
    return out
