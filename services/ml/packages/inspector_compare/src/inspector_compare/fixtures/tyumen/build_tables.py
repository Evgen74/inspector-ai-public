"""Build the hand-made Тюменская TableArtifacts fixture (AG-04 development fixture, not recognition output).

Explication rows («Экспликация помещений») printed in the text layer of the RD plans that anchor the gold: F0201 p17
(basement, vent chamber 012), F0201 p18 (1st floor: rooms 140–147 and 198 of «пункт 3», and the «в том числе»
sub-zone of 102 that 97 §1.5 names as a double count) and F0202 p17 (2nd floor: warm-floor rooms 267–272). Cells,
row boxes and page numbers were read from the PDF text layer (PyMuPDF blocks, normalised to the visible page); the
data test tests/test_compare_tyumen.py checks every DATA row against the text layer again.

    cd services/ml && uv run --locked python \
        packages/inspector_compare/src/inspector_compare/fixtures/tyumen/build_tables.py \
        packages/inspector_compare/src/inspector_compare/fixtures/tyumen/tables
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
OBJ = "OBJ-TYUMENSKAYA-5-GOLD-SEED"
GEN = "2026-09-28T00:00:00Z"
PIPE = "fixture-ag04-tyumen-tables-1"
SHA = {
    "F0201": "0c398d7bca356455568413a6fc3b14044b7e538a902251b80e2a5574d80184fd",
    "F0202": "632379a0e541f0c81e6b03e5528946730b4433939c796db4fdc1e5c3fc8b71ee",
}
CODE = {"F0201": "АНО/150321/1-РД-ОВ1", "F0202": "АНО/150321/1-РД-ОВ2.1"}
COLUMNS = [
    {"key": "room_no", "header_raw": "Номер помещения"},
    {"key": "name", "header_raw": "Наименование"},
    {"key": "area_m2", "header_raw": "Площадь", "unit": "м²"},
    {"key": "category", "header_raw": "Категория"},
]

# (room_no, name, area as printed, category or None, row bbox [x0, y0, x1, y1] of the visible page)
Row = tuple[str | None, str, str, str | None, list[float]]


def cells(room_no: str | None, name: str, area: str | None, category: str | None) -> dict:
    out: dict = {}
    if room_no is not None:
        out["room_no"] = {"raw": room_no, "value": room_no}
    out["name"] = {"raw": name, "value": name}
    if area is not None:
        out["area_m2"] = {"raw": area, "value": float(area.replace(",", ".")), "unit": "м²"}
    if category is not None:
        out["category"] = {"raw": category, "value": category}
    return out


def row(n: int, page: int, r: Row, kind: str = "DATA", **extra: object) -> dict:
    room_no, name, area, category, bbox = r
    out = {
        "row_no": n,
        "kind": kind,
        "cells": cells(room_no, name, area, category),
        "pdf_page_number": page,
        "bbox": bbox,
    }
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def table(file_id: str, page: int, sheet: int, title: str, rows: list[dict], bbox: list[float]) -> dict:
    return {
        "table_id": f"{file_id}-p{page}-EXPLICATION-1",
        "table_type": "EXPLICATION",
        "title": title,
        "pages": [page],
        "bboxes": [{"pdf_page_number": page, "bbox": bbox}],
        "columns": COLUMNS,
        "rows": rows,
        "sheet_number": sheet,
        "document_code": CODE[file_id],
        "text_source": "TEXT_LAYER",
        "confidence": 1.0,
        "parser_version": PIPE,
    }


def doc(file_id: str, tables: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "file_id": file_id,
        "object_id": OBJ,
        "file_sha256": SHA[file_id],
        "stage": "RD",
        "pipeline_version": PIPE,
        "generated_at": GEN,
        "tables": tables,
        "ext": {
            "fixture": "AG-04 hand-made development fixture (not recognition output)",
            "sources": ["PDF text layer of F0201 p17, p18 and F0202 p17 (explication blocks)"],
            "complete": False,
            "note": "Only the rows around the gold rooms are listed; totals are not reproduced.",
        },
    }


# ── F0201 p17: «Экспликация помещений подвала на отм. -2,950» ─────────────────────────────────────
p17 = [
    ("011", "Лестница Л-3", "26.5", None, [0.0376, 0.9888, 0.2564, 0.9949]),
    ("012", "Венткамера", "99.7", "В2", [0.3354, 0.924, 0.6001, 0.9304]),
    ("013", "Форкамера", "15.89", None, [0.3354, 0.9334, 0.5558, 0.9405]),
]
t17 = table(
    "F0201",
    17,
    4,
    "Экспликация помещений подвала на отм. -2,950",
    [row(i, 17, r) for i, r in enumerate(p17, start=1)],
    [0.0376, 0.8221, 0.6001, 0.9949],
)

# ── F0201 p18: «Экспликация помещений 1 этажа» ────────────────────────────────────────────────────
LAB_A = (
    "Специализированный учебный кабинет естествознания (тип А: физика+химия+биология) с возможностью деления "
    "трансформируемыми перегородками на зоны:"
)
p18_rows: list[dict] = []
n = 0


def add(r: Row, kind: str = "DATA", **extra: object) -> None:
    global n
    n += 1
    p18_rows.append(row(n, 18, r, kind, **extra))


add(("101", "Тамбур", "8.6", None, [0.0312, 0.7832, 0.1576, 0.7867]))
add(
    (
        "102",
        "Вестибюль со стойкой для зарядки мобильных устройств, в том числе:",
        "134.0",
        None,
        [0.031, 0.7889, 0.1592, 0.7959],
    )
)
vestibule = n
add(
    (
        None,
        "зона ожидания для посетителей со стойкой зарядки мобильных устройств",
        "30.4",
        None,
        [0.0447, 0.7977, 0.1586, 0.8046],
    ),
    "SUBZONE",
    parent_row_no=vestibule,
)
add(("138", "Коридор", "82.4", None, [0.1915, 0.8006, 0.3191, 0.8041]))
add(("139", "Рекреация коридорного типа", "267.1", None, [0.1915, 0.8064, 0.3196, 0.8099]))
add((None, LAB_A, None, None, [0.1884, 0.8123, 0.3036, 0.8233]), "SECTION_HEADER")
for r in (
    ("140", "моделирования и конструирования", "50.4", None, [0.1914, 0.8258, 0.3191, 0.8293]),
    ("141", "биолого-химического практикума", "53.0", None, [0.1916, 0.8316, 0.319, 0.8351]),
    ("142", "астрономии и физики", "52.9", None, [0.1914, 0.8373, 0.319, 0.8408]),
    ("143", "физического эксперимента", "51.4", None, [0.1914, 0.8431, 0.3189, 0.8466]),
):
    add(r, section=LAB_A)
add(("144", "Лаборантская тип А", "18.0", "В3", [0.1912, 0.8488, 0.3371, 0.8523]))
add(
    (
        "145",
        "Учебный кабинет универсального назначения (5-9 класы)",
        "62.8",
        None,
        [0.1914, 0.8548, 0.319, 0.8582],
    )
)
add(
    (
        "146",
        "Учебный кабинет универсального назначения (5-9 класы)",
        "63.0",
        None,
        [0.1914, 0.8607, 0.319, 0.8641],
    )
)
add(("147", "Лаборантская тип АВ", "19.6", "В3", [0.1914, 0.8664, 0.3371, 0.8699]))
add(("197", "Универсальный учебный кабинет (10-11 классы)", "71.2", None, [0.1915, 0.9624, 0.3187, 0.9658]))
add(("198", "Лаборантская тип АВ", "21.1", "В3", [0.1915, 0.9681, 0.3371, 0.9716]))
t18 = table("F0201", 18, 5, "Экспликация помещений 1 этажа", p18_rows, [0.031, 0.7513, 0.3371, 0.9774])

# ── F0202 p17: «Экспликация помещений 2 этажа» ────────────────────────────────────────────────────
p17b = [
    ("267", "Раздевальная для МГН", "13.7", None, [0.5117, 0.8739, 0.6328, 0.8769]),
    ("270", "Санузел с душем для МГН", "5.9", None, [0.5117, 0.8789, 0.6322, 0.8822]),
    ("271", "Раздевальная для МГН", "12.4", None, [0.512, 0.8846, 0.6329, 0.8875]),
    ("272", "Санузел с душем для МГН", "7.2", None, [0.5117, 0.8896, 0.6322, 0.8928]),
    ("268", "Пожаро-безопасная зона", "16.2", None, [0.5117, 0.904, 0.6328, 0.9072]),
    ("269", "Лестница", "25.8", None, [0.5117, 0.9099, 0.633, 0.913]),
]
t17b = table(
    "F0202",
    17,
    4,
    "Экспликация помещений 2 этажа",
    [row(i, 17, r) for i, r in enumerate(p17b, start=1)],
    [0.5117, 0.8341, 0.636, 0.9249],
)

OUT.mkdir(parents=True, exist_ok=True)
for d in (doc("F0201", [t17, t18]), doc("F0202", [t17b])):
    (OUT / f"{d['file_id']}.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
print("written", sorted(p.name for p in OUT.glob("*.json")))
