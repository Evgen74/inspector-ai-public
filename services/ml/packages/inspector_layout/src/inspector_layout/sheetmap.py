"""Sheet ↔ page map of one PDF file (95 R5, 96 §7.3; gate «sheet = stamp ≥ 0.95»).

Inputs are what the title-block reader and the QR decoder found per page. The map is built per document
(one file often holds several: F0202 has «…-РД-СП», «…-РД-ОВ2.1» and «…-РД-ОВ2.1.С», each numbering its
sheets from 1):

1. **Groups.** Consecutive pages with the same document code (compared by :func:`codes.code_key`) form a
   group; a page without a readable code joins its neighbours' group when they agree.
   A first sheet («Лист 1» or a blank «Лист» with «Листов» printed) after numbered sheets of the same code
   opens a new group: a specification bound after the drawings under the same шифр (F0204 p15); so does a
   restart at «1» after higher sheets (a text-layer «1», or an OCR «1» followed by «2»).
2. **Support.** A reading is *supported* when a page of the same group within 3 pages continues it linearly
   (sheet difference = page difference).
3. **Smoothing.** An unsupported OCR reading or a missing one between two supported pages a < p < b of a
   linear run (r(b) − r(a) = b − a) becomes r(a) + (p − a), basis ``SEQUENCE_SMOOTHED`` (F0202 p19 once read
   as «9» between 5 and 7 → 6). A text-layer reading is exact and is never overridden. A missing reading with a QR page of the same Exon document is filled from the group's
   constant (sheet − QR page), basis ``QR``.
4. **One-sheet documents.** ГОСТ Р 21.101 leaves «Лист» blank on a document of one sheet and prints «Листов 1»
   (a «Содержание» or «Гарантийная запись» of a PD volume): such a page is sheet 1 of its document, basis
   ``TITLE_BLOCK``; the title block itself keeps the blank as printed.
5. **Duplicates.** A (group, sheet) printed on several pages is kept on every page, the later ones with
   ``duplicate_of_page`` (F0201 p29/p30 repeat sheets 14/15 of p27/p28). Never dropped.

The sheet number is what the stamp prints. Gold data is never consulted: the organizers' gold for F0201 numbers
sheets one lower than the stamps (95 §0.4), so localisation always uses the PDF page, never the sheet number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inspector_layout.codes import code_key

SUPPORT_WINDOW = 3


@dataclass(slots=True)
class PageSheet:
    """Per-page input of the map."""

    page: int
    sheet: int | str | None = None  # as read from the stamp (int when numeric)
    code: str | None = None
    confidence: float = 0.0
    title_block: bool = False
    sheet_title: str | None = None
    qr_key: str | None = None
    qr_page: int | None = None
    trusted: bool = False  # read from the text layer: exact, never overridden by smoothing
    sheets_total: int | None = None  # «Листов»


@dataclass(slots=True)
class _Row:
    ps: PageSheet
    group: int = -1
    value: int | str | None = None
    basis: str | None = None
    confidence: float = 0.0
    supported: bool = False
    duplicate_of: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _groups(rows: list[_Row]) -> None:
    keys = [code_key(r.ps.code) if r.ps.code else None for r in rows]
    # fill unknown codes from agreeing neighbours (nearest known before and after), unless the page's sheet
    # number is already printed on a coded page of that document (a cover «Лист 1 / Листов 1» before
    # sheet 1 of the document is not one of its sheets)
    n = len(rows)
    filled = list(keys)
    sheets_of: dict[str, set[str]] = {}
    for r, k in zip(rows, keys, strict=True):
        if k is not None and r.ps.sheet is not None:
            sheets_of.setdefault(k, set()).add(str(r.ps.sheet))
    for i in range(n):
        if filled[i] is not None:
            continue
        prev = next((keys[j] for j in range(i - 1, -1, -1) if keys[j] is not None), None)
        nxt = next((keys[j] for j in range(i + 1, n) if keys[j] is not None), None)
        cand = None
        if prev is not None and (nxt is None or nxt == prev):
            cand = prev
        elif prev is None and nxt is not None:
            cand = nxt
        s = rows[i].ps.sheet
        if cand is not None and (s is None or str(s) not in sheets_of.get(cand, set())):
            filled[i] = cand
        elif cand is not None:
            filled[i] = f"\x00page{rows[i].ps.page}"  # its own group
    gid = -1
    last: str | None = object()  # type: ignore[assignment]
    last_page = None
    seen = False  # the current group already holds a first sheet or a numbered sheet
    top = 0  # highest sheet number of the current group
    for i, (r, k) in enumerate(zip(rows, filled, strict=True)):
        # numbering restarts at 1 after higher sheets of the same шифр (Новослободская F0104: the drawings
        # «1…30» after the text part «1…11», no «Листов» printed): only a text-layer «1», or one followed by «2»
        nxt = rows[i + 1].ps.sheet if i + 1 < n and filled[i + 1] == k else None
        restart = r.ps.sheet == 1 and top >= 2 and k == last and (r.ps.trusted or nxt == 2)
        # A first sheet («Лист 1» or blank, with «Листов») after numbered sheets of the same шифр opens a new
        # document: a specification bound after the drawings under the same code restarts at 1 (F0204), the
        # drawings of a PD volume after its text part (F0190 p17 «1 / 4» after sheets 3–6).
        first = r.ps.title_block and r.ps.sheets_total is not None and r.ps.sheet in (1, None)
        new_doc = (first and seen and k == last) or restart
        if k != last or new_doc or (last_page is not None and r.ps.page - last_page > SUPPORT_WINDOW + 5):
            gid += 1
            last = k
            seen = False
            top = 0
        seen = seen or first or isinstance(r.ps.sheet, int)
        if isinstance(r.ps.sheet, int):
            top = max(top, r.ps.sheet)
        r.group = gid
        last_page = r.ps.page


def build_sheet_map(pages: list[PageSheet]) -> list[dict[str, Any]]:
    """SheetPageEntry dicts (contract ``layout_artifacts#/$defs/SheetPageEntry``), ordered by page."""
    rows = [_Row(ps) for ps in sorted(pages, key=lambda p: p.page)]
    if not rows:
        return []
    _groups(rows)
    by_group: dict[int, list[_Row]] = {}
    for r in rows:
        by_group.setdefault(r.group, []).append(r)

    for grp in by_group.values():
        nums = {r.ps.page: r.ps.sheet for r in grp if isinstance(r.ps.sheet, int)}
        # 2. support
        for r in grp:
            s = r.ps.sheet
            if not isinstance(s, int):
                continue
            for q, sq in nums.items():
                if q != r.ps.page and abs(q - r.ps.page) <= SUPPORT_WINDOW and sq - s == q - r.ps.page:
                    r.supported = True
                    break
        supported = [r for r in grp if r.supported]
        # 3. smoothing between supported neighbours of one linear run
        for r in grp:
            s = r.ps.sheet
            if r.supported:
                r.value, r.basis, r.confidence = s, "TITLE_BLOCK", r.ps.confidence
                continue
            before = [a for a in supported if a.ps.page < r.ps.page]
            after = [b for b in supported if b.ps.page > r.ps.page]
            a = before[-1] if before else None
            b = after[0] if after else None
            if (
                a is not None
                and b is not None
                and isinstance(a.ps.sheet, int)
                and isinstance(b.ps.sheet, int)
                and b.ps.sheet - a.ps.sheet == b.ps.page - a.ps.page
            ):
                want = a.ps.sheet + (r.ps.page - a.ps.page)
                if s == want or (s is not None and r.ps.trusted):
                    r.value, r.basis, r.confidence = s, "TITLE_BLOCK", r.ps.confidence
                else:
                    r.value, r.basis = want, "SEQUENCE_SMOOTHED"
                    r.confidence = 0.75 if s is None else 0.7
                    if s is not None:
                        r.extra["read"] = s
                continue
            if s is not None:
                r.value, r.basis = s, "TITLE_BLOCK"
                r.confidence = r.ps.confidence * (0.85 if isinstance(s, int) and len(grp) > 2 else 1.0)
        # 3b. QR constant (sheet − QR page) of the group's supported pages
        offsets = {
            r.value - r.ps.qr_page
            for r in grp
            if r.supported and isinstance(r.value, int) and r.ps.qr_page is not None
        }
        qr_keys = {r.ps.qr_key for r in grp if r.supported and r.ps.qr_key}
        if len(offsets) == 1 and len(qr_keys) == 1 and supported:
            off = offsets.pop()
            key = qr_keys.pop()
            lo, hi = supported[0].ps.page, supported[-1].ps.page
            for r in grp:
                # only pages with a stamp, or pages inside the group's span: an unstamped appendix after the
                # last sheet (manufacturer data sheets of F0201 p173+) carries the same QR key but no sheet
                inside = r.ps.title_block or lo < r.ps.page < hi
                ok = r.value is None and inside and r.ps.qr_page is not None and r.ps.qr_key == key
                if ok and r.ps.qr_page + off >= 1:
                    r.value, r.basis, r.confidence = r.ps.qr_page + off, "QR", 0.8
        # 4. one-sheet documents: «Лист» blank, «Листов 1»
        for r in grp:
            if r.value is None and r.ps.sheet is None and r.ps.sheets_total == 1 and r.ps.title_block:
                r.value, r.basis, r.confidence = 1, "TITLE_BLOCK", 0.9
        # 5. duplicates
        first: dict[Any, int] = {}
        for r in grp:
            if r.value is None:
                continue
            k = str(r.value)
            if k in first:
                r.duplicate_of = first[k]
            else:
                first[k] = r.ps.page

    out: list[dict[str, Any]] = []
    for r in rows:
        if r.value is None:
            continue
        code = r.ps.code
        if code is None:
            codes = [x.ps.code for x in by_group[r.group] if x.ps.code]
            code = max(set(codes), key=codes.count) if codes else None
        out.append(
            {
                "pdf_page_number": r.ps.page,
                "sheet_number": r.value,
                "document_code": code,
                "basis": r.basis,
                "confidence": round(min(1.0, max(0.0, r.confidence)), 4),
                "duplicate_of_page": r.duplicate_of,
                "sheet_title": r.ps.sheet_title,
            }
        )
    return out
