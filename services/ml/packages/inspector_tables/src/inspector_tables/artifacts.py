"""Contract output: parsed tables → TableArtifacts (schemas/table_artifacts.schema.json).

Only canonical column keys of the table type leave this module (enums.yaml TableType ``columns``); the
parsers' internal keys (``_row_no``, ``_content``…) never do. Every cell keeps the printed string (``raw``)
next to its parsed ``value``, its normalized box and page; rows keep their kind, parent and section.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from inspector_common.contracts.models import table_columns
from inspector_tables.grid import RawCell, RawRow, RawTable
from inspector_tables.text import Box, norm_unit, number_value, parse_number, squash

TABLES_VERSION = "tables-0.1.0"
NUMERIC_KEYS = {"area_m2", "value", "quantity", "mass", "total_sheets", "sheets", "pages"}


def _cell(raw_cell: RawCell | None, text: str | None, rt: RawTable | None, *, numeric: bool = False,
          unit: str | None = None, value: Any = "__auto__") -> dict[str, Any]:  # fmt: skip
    raw = squash(text) if text is not None else (raw_cell.text if raw_cell else None)
    out: dict[str, Any] = {"raw": raw if raw else None}
    if value == "__auto__":
        if numeric:
            v = parse_number(raw)
            out["value"] = number_value(v) if v is not None else None
        else:
            out["value"] = raw if raw else None
    else:
        out["value"] = value
    if unit:
        out["unit"] = unit
    if raw_cell is not None and raw_cell.box is not None and rt is not None and rt.page is not None:
        out["bbox"] = rt.page.norm_bbox(raw_cell.box)
        out["pdf_page_number"] = rt.page_no
        confs = [w.conf for w in raw_cell.words]
        if confs:
            out["confidence"] = round(min(confs), 4)
    return out


def _row_geometry(raw: RawRow | None, rt: RawTable | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if raw is None or rt is None:
        return out
    out["pdf_page_number"] = rt.page_no
    b = raw.box
    if b is not None and rt.page is not None:
        out["bbox"] = rt.page.norm_bbox(b)
    return out


def _columns(
    table_type: str, parts: list[RawTable], extra_headers: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    allowed = table_columns(table_type)
    headers: dict[str, str] = {}
    for p in parts:
        for c in p.columns:
            if c.key in allowed and c.key not in headers:
                headers[c.key] = c.header
    headers.update({k: v for k, v in (extra_headers or {}).items() if k in allowed})
    cols = []
    for key in allowed:
        if key in headers:
            col: dict[str, Any] = {"key": key, "header_raw": headers[key] or None}
            if key == "area_m2":
                col["unit"] = "м²"
            cols.append(col)
    return cols or [{"key": allowed[0], "header_raw": None}]


def _bboxes(parts: list[RawTable]) -> list[dict[str, Any]]:
    out = []
    for p in parts:
        if p.page is not None:
            out.append({"pdf_page_number": p.page_no, "bbox": p.page.norm_bbox(p.box)})
    return out


def _text_source(parts: Iterable[RawTable]) -> str:
    n_ocr = n = 0
    for p in parts:
        for r in p.rows:
            for w in r.all_words:
                n += 1
                n_ocr += not w.source.startswith("TEXT_LAYER")
    return "OCR" if n and n_ocr / n > 0.5 else "TEXT_LAYER"


def _confidence(parts: Iterable[RawTable]) -> float:
    confs = [w.conf for p in parts for r in p.rows for w in r.all_words]
    return round(sum(confs) / len(confs), 4) if confs else 1.0


def table_id(file_id: str, table_type: str, page: int, n: int) -> str:
    return f"{file_id}-p{page}-{table_type}-{n}"[:96]


def _base(table_type: str, tid: str, title: str | None, parts: list[RawTable], parser_version: str,
          checks: list[dict] | None, document_code: str | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "table_id": tid,
        "table_type": table_type,
        "title": title,
        "pages": sorted({p.page_no for p in parts}),
        "bboxes": _bboxes(parts),
        "columns": [],
        "rows": [],
        "checks": [_check(c) for c in (checks or [])],
        "sheet_number": None,
        "document_code": document_code,
        "text_source": _text_source(parts),
        "confidence": _confidence(parts),
        "parser_version": parser_version,
    }


def _check(c: dict) -> dict[str, Any]:
    out = {"kind": c["kind"], "passed": bool(c["passed"])}
    for k in ("expected", "actual", "rows", "detail"):
        if c.get(k) is not None:
            out[k] = c[k]
    return out


def _part_of(parts: list[RawTable], raw: RawRow | None) -> RawTable | None:
    if raw is None:
        return None
    for p in parts:
        if raw in p.rows:
            return p
    return None


# ── per type ──────────────────────────────────────────────────────────────────────────────────────


def explication_table(le, file_id: str, n: int) -> dict[str, Any]:
    from inspector_tables.explication import PARSER_VERSION

    parts = le.parts
    t = _base(
        "EXPLICATION",
        table_id(file_id, "EXPLICATION", parts[0].page_no, n),
        le.caption,
        parts,
        PARSER_VERSION,
        le.checks,
    )
    t["columns"] = _columns(
        "EXPLICATION",
        parts,
        {"area_m2": next((c.header for p in parts for c in p.columns if c.key == "area"), "")},
    )
    for i, r in enumerate(le.rows, 1):
        rt = _part_of(parts, r.raw)
        cells: dict[str, Any] = {}
        if r.kind == "SECTION_HEADER":
            cells["name"] = _cell(None, r.name, rt)
        else:
            if r.room_raw or r.room_no:
                cells["room_no"] = _cell(
                    r.raw.cells.get("room_no"), r.room_raw or r.room_no, rt, value=r.room_no
                )
            if r.name:
                cells["name"] = _cell(r.raw.cells.get("name"), r.name, rt)
            if r.area_raw or r.area is not None:
                cells["area_m2"] = _cell(r.raw.cells.get("area"), r.area_raw, rt,
                                         value=number_value(r.area) if r.area is not None else None, unit="м²")  # fmt: skip
            if r.category_raw:
                cells["category"] = _cell(r.raw.cells.get("category"), r.category_raw, rt, value=r.category)
        row: dict[str, Any] = {"row_no": i, "cells": cells, "kind": r.kind, **_row_geometry(r.raw, rt)}
        if r.parent is not None:
            row["parent_row_no"] = r.parent + 1
        if r.section and r.kind != "SECTION_HEADER":
            row["section"] = r.section
        t["rows"].append(row)
    return t


def tep_table(lt, file_id: str, n: int) -> dict[str, Any]:
    from inspector_tables.tep import PARSER_VERSION

    parts = lt.parts
    t = _base(
        "TEP", table_id(file_id, "TEP", parts[0].page_no, n), lt.caption, parts, PARSER_VERSION, lt.checks
    )
    t["columns"] = _columns("TEP", parts)
    for i, r in enumerate(lt.rows, 1):
        rt = _part_of(parts, r.raw)
        cells: dict[str, Any] = {"indicator": _cell(r.raw.cells.get("indicator") if r.raw else None,
                                                    ((r.row_no + " ") if r.row_no else "") + r.indicator, rt, value=r.indicator)}  # fmt: skip
        if r.unit:
            cells["unit"] = _cell(r.raw.cells.get("unit"), r.unit, rt, value=norm_unit(r.unit) or r.unit)
        if r.value_raw:
            cells["value"] = _cell(r.raw.cells.get("value"), r.value_raw, rt,
                                   value=number_value(r.value) if r.value is not None else r.value_raw, unit=norm_unit(r.unit))  # fmt: skip
        if r.limit_raw:
            cells["note"] = _cell(r.raw.cells.get("note"), r.limit_raw, rt,
                                  value=number_value(r.limit) if r.limit is not None else r.limit_raw)  # fmt: skip
        row: dict[str, Any] = {"row_no": i, "cells": cells, "kind": r.kind, **_row_geometry(r.raw, rt)}
        if r.parent is not None:
            row["parent_row_no"] = r.parent + 1
        t["rows"].append(row)
    return t


def spec_table(ls, file_id: str, n: int) -> dict[str, Any]:
    from inspector_tables.spec21110 import KEYS, PARSER_VERSION

    parts = ls.parts
    t = _base(
        "SPEC_21110",
        table_id(file_id, "SPEC_21110", parts[0].page_no, n),
        ls.caption,
        parts,
        PARSER_VERSION,
        ls.checks,
    )
    t["columns"] = _columns("SPEC_21110", parts)
    for i, it in enumerate(ls.items, 1):
        raw0 = it.raws[0] if it.raws else None
        rt = _part_of(parts, raw0)
        cells: dict[str, Any] = {}
        for k in KEYS:
            v = it.cells.get(k)
            if v:
                rc = raw0.cells.get(k) if raw0 is not None else None
                if k in ("quantity", "mass"):
                    cells[k] = _cell(
                        rc,
                        v,
                        rt,
                        numeric=True,
                        unit=norm_unit(it.cells.get("unit")) if k == "quantity" else "кг",
                    )
                else:
                    cells[k] = _cell(rc, v, rt)
        row: dict[str, Any] = {"row_no": i, "cells": cells, "kind": it.kind, **_row_geometry(raw0, rt)}
        if it.section and it.kind != "SECTION_HEADER":
            row["section"] = it.section
        boxes = [r.box for r in it.raws if r.box is not None]
        if boxes and rt is not None and rt.page is not None:
            b = boxes[0]
            for o in boxes[1:]:
                b = b.union(o)
            row["bbox"] = rt.page.norm_bbox(b)
        t["rows"].append(row)
    return t


def changelog_table(lg, file_id: str, n: int) -> dict[str, Any]:
    from inspector_tables.changelog import PARSER_VERSION

    parts = lg.parts
    t = _base("CHANGE_LOG", table_id(file_id, "CHANGE_LOG", parts[0].page_no, n), lg.caption, parts, PARSER_VERSION,
              lg.checks, lg.document_code)  # fmt: skip
    extra = {"note": "Содержание изменения; Код; Примечание"}
    if lg.permit_no:
        extra["doc_no"] = "Разрешение"
    t["columns"] = _columns("CHANGE_LOG", parts, extra)
    allowed = set(table_columns("CHANGE_LOG"))
    for i, r in enumerate(lg.rows, 1):
        rt = _part_of(parts, r.raw)
        cells = {}
        for k, v in r.cells.items():
            if k in allowed and v:
                rc = r.raw.cells.get(k) if r.raw is not None else None
                cells[k] = _cell(rc if k not in ("note", "doc_no") else None, v, rt,
                                 numeric=k in ("total_sheets",))  # fmt: skip
        t["rows"].append({"row_no": i, "cells": cells, "kind": "DATA", **_row_geometry(r.raw, rt)})
    return t


def deviation_table(ld, file_id: str, n: int) -> tuple[dict[str, Any], dict[int, dict]]:
    """TypedTable plus, per row number, the evaluation (computed deviation, tolerance verdict) for the values."""
    from inspector_tables.deviation import KEYS, PARSER_VERSION

    parts = ld.parts
    t = _base(
        "DEVIATION",
        table_id(file_id, "DEVIATION", parts[0].page_no, n),
        ld.caption,
        parts,
        PARSER_VERSION,
        ld.checks,
    )
    t["columns"] = _columns("DEVIATION", parts)
    evals: dict[int, dict] = {}
    for i, r in enumerate(ld.rows, 1):
        rt = _part_of(parts, r.raw)
        cells = {}
        for k in KEYS:
            v = r.cells.get(k)
            if v:
                cells[k] = _cell(
                    r.raw.cells.get(k), v, rt, numeric=k in ("design_value", "actual_value", "deviation")
                )
        t["rows"].append({"row_no": i, "cells": cells, "kind": "DATA", **_row_geometry(r.raw, rt)})
        evals[i] = {
            "computed_deviation": r.computed,
            "within_tolerance": r.within,
            "deviation_consistent": r.consistent,
        }
    return t, evals


def registry_table(reg, file_id: str, n: int) -> dict[str, Any]:
    from inspector_tables.registry import KEYS, PARSER_VERSION

    parts = reg.parts
    t = _base(
        "ID_REGISTRY",
        table_id(file_id, "ID_REGISTRY", parts[0].page_no, n),
        reg.caption,
        parts,
        PARSER_VERSION,
        reg.checks,
    )
    t["columns"] = _columns("ID_REGISTRY", parts, {"doc_date": "№ …, от (дата)"})
    for i, r in enumerate(reg.rows, 1):
        rt = _part_of(parts, r.raw)
        cells: dict[str, Any] = {}
        if r.kind == "SECTION_HEADER":
            cells["doc_name"] = _cell(None, r.cells.get("doc_name"), rt)
        else:
            for k in KEYS:
                v = r.cells.get(k)
                if not v:
                    continue
                rc = r.raw.cells.get(k) if r.raw is not None else None
                if k == "doc_no":
                    cells[k] = _cell(rc, v, rt, value=r.doc_no)
                else:
                    cells[k] = _cell(rc, v, rt, numeric=k in ("sheets", "pages"))
            if r.doc_date and "doc_date" not in cells:
                cells["doc_date"] = {"raw": None, "value": r.doc_date}
        row: dict[str, Any] = {"row_no": i, "cells": cells, "kind": r.kind, **_row_geometry(r.raw, rt)}
        if r.section and r.kind != "SECTION_HEADER":
            row["section"] = r.section
        t["rows"].append(row)
    return t


def aosr_table(
    acts: list[tuple[int, Any]], file_id: str, n: int, page_box: dict[int, list[float]] | None = None
) -> dict[str, Any]:
    """One AOSR table per file: a row per act (the text form has no grid; the row box is the page)."""
    from inspector_tables.aosr import PARSER_VERSION

    allowed = table_columns("AOSR")
    pages = sorted({pg for pg, _ in acts})
    t: dict[str, Any] = {
        "table_id": table_id(file_id, "AOSR", pages[0], n),
        "table_type": "AOSR",
        "title": "Акт освидетельствования скрытых работ",
        "pages": pages,
        "bboxes": [
            {"pdf_page_number": pg, "bbox": (page_box or {}).get(pg, [0.0, 0.0, 1.0, 1.0])} for pg in pages
        ],
        "columns": [{"key": k, "header_raw": None} for k in allowed],
        "rows": [],
        "checks": [],
        "sheet_number": None,
        "document_code": None,
        "text_source": "TEXT_LAYER",
        "confidence": 1.0,
        "parser_version": PARSER_VERSION,
    }
    for i, (pg, act) in enumerate(acts, 1):
        cells = {k: {"raw": v, "value": v} for k, v in act.cells.items() if k in allowed and v}
        t["rows"].append({"row_no": i, "cells": cells, "kind": "DATA", "pdf_page_number": pg})
        t["checks"].append({"kind": "HEADER_MATCHED", "passed": act.fields_found >= 7, "expected": 9, "actual": act.fields_found,
                            "rows": [i], "detail": f"Акт №{act.cells.get('act_no', '—')}: распознано полей {act.fields_found} из 9"})  # fmt: skip
    return t


def table_artifacts(file_id: str, object_id: str, sha256: str, stage: str | None, tables: list[dict], *,
                    generated_at: str, warnings: list[str] | None = None, timings_ms: dict[str, float] | None = None,
                    ext: dict | None = None) -> dict[str, Any]:  # fmt: skip
    doc: dict[str, Any] = {
        "schema_version": 1,
        "file_id": file_id,
        "object_id": object_id,
        "file_sha256": sha256,
        "stage": stage,
        "pipeline_version": TABLES_VERSION,
        "generated_at": generated_at,
        "tables": tables,
    }
    if warnings:
        doc["warnings"] = sorted(set(warnings))
    if timings_ms:
        doc["timings_ms"] = {k: round(v, 1) for k, v in timings_ms.items()}
    if ext:
        doc["ext"] = ext
    return doc


def box_of(rows: list[RawRow]) -> Box | None:
    boxes = [r.box for r in rows if r.box is not None]
    if not boxes:
        return None
    b = boxes[0]
    for o in boxes[1:]:
        b = b.union(o)
    return b
