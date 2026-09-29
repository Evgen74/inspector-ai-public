"""Build the hand-made Тюменская LayoutArtifacts fixture (AG-04 development fixture, not recognition output).

Every token and page below comes from docs/analysis/95_tyumen_dev_fixtures.json (page_facts, markup_zone_bboxes)
and 95 §3.3; boxes are the registered markup zones or ±0.008 around the measured label points. The PD half is
checked against the real text layer by tests/test_compare_tyumen.py (data test).

    cd services/ml && uv run --locked python \
        packages/inspector_compare/src/inspector_compare/fixtures/tyumen/build_layout.py \
        packages/inspector_compare/src/inspector_compare/fixtures/tyumen/layout
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
OBJ = "OBJ-TYUMENSKAYA-5-GOLD-SEED"
GEN = "2026-09-28T00:00:00Z"
PIPE = "fixture-ag04-tyumen-1"
SHA = {
    "F0171": "a9070055b75adeea0d47651cf9dca3ca818ca5f54ac7ce9ddcd86efc817db7dc",
    "F0198": "094753524e656f6a4d1cc95f5a26e194309e91f81bb5495dc88aed145892bc3e",
    "F0201": "0c398d7bca356455568413a6fc3b14044b7e538a902251b80e2a5574d80184fd",
    "F0202": "632379a0e541f0c81e6b03e5528946730b4433939c796db4fdc1e5c3fc8b71ee",
}
PAGES = {"F0171": 177, "F0198": 1, "F0201": 676, "F0202": 36}


def box(x: float, y: float, dx: float = 0.008, dy: float = 0.006) -> list[float]:
    return [
        round(max(0.0, x - dx), 4),
        round(max(0.0, y - dy), 4),
        round(min(1.0, x + dx), 4),
        round(min(1.0, y + dy), 4),
    ]


def spread(zone: list[float], i: int, n: int) -> list[float]:
    """Deterministic position of the i-th of n tags inside a zone."""
    x0, y0, x1, y1 = zone
    cols = max(1, min(n, 4))
    rows = (n + cols - 1) // cols
    cx = x0 + (x1 - x0) * (0.5 + i % cols) / cols
    cy = y0 + (y1 - y0) * (0.5 + i // cols) / max(rows, 1)
    return box(cx, cy, 0.006, 0.004)


def prov(source: str, conf: float, layer: str | None = None) -> dict:
    out = {"text_source": source, "confidence": conf}
    if layer:
        out["layer"] = layer
    return out


def room(
    token: str,
    page: int,
    xy: tuple[float, float],
    source: str = "SCHEMATIC_LABEL",
    name: str | None = None,
    text_source: str = "TEXT_LAYER",
) -> dict:
    out = {
        "room_token": token,
        "pdf_page_number": page,
        "bbox": box(*xy),
        "source": source,
        "provenance": prov(text_source, 1.0),
    }
    if name:
        out["name"] = name
    return out


def tag(
    raw: str,
    kind: str,
    page: int,
    room_token: str,
    bbox: list[float],
    link: str = "INSIDE",
    source: str = "TEXT_LAYER",
    conf: float = 1.0,
    layer: str | None = None,
) -> dict:
    return {
        "tag": raw,
        "tag_kind": kind,
        "pdf_page_number": page,
        "bbox": bbox,
        "room_token": room_token,
        "room_link": link,
        "provenance": prov(source, conf, layer),
    }


def base(file_id: str, stage: str) -> dict:
    return {
        "schema_version": 1,
        "file_id": file_id,
        "object_id": OBJ,
        "file_sha256": SHA[file_id],
        "stage": stage,
        "pipeline_version": PIPE,
        "generated_at": GEN,
        "pages_total": PAGES[file_id],
        "ext": {
            "fixture": "AG-04 hand-made development fixture (not recognition output)",
            "sources": [
                "docs/analysis/95_tyumen_dev_fixtures.json page_facts, markup_zone_bboxes",
                "docs/analysis/95_corpus_train_objects.md §3.3",
            ],
        },
    }


# ── F0171 (ПД, Том 5.4.2 ОВ) ────────────────────────────────────────────────────────────────────
# Title-block cells of the PD sheets, as printed in the text layer of p88/p99/p104 (checked by the data test).
PD_CODE = "АНО/150321/1-П-ИОС5.4.2"
OBJECT_NAME = "Школа на 600 мест, р-н Богородское, ул. Тюменская, влд. 5"
f0171 = base("F0171", "PD")
f0171["title_blocks"] = [
    {
        "pdf_page_number": 88,
        "sheet_number": 10,
        "stage_raw": "П",
        "stage": "PD",
        "sheet_title": "Принципиальная схема систем общеобменной вентиляции (продолжение №3)",
        "document_code_raw": PD_CODE,
        "document_code": PD_CODE,
        "object_name": OBJECT_NAME,
        "provenance": prov("TEXT_LAYER", 1.0),
    },
    {
        "pdf_page_number": 99,
        "sheet_number": 21,
        "stage_raw": "П",
        "stage": "PD",
        "sheet_title": "Принципиальная схема системы отопления",
        "document_code_raw": PD_CODE,
        "document_code": PD_CODE,
        "object_name": OBJECT_NAME,
        "provenance": prov("TEXT_LAYER", 1.0),
    },
    {
        "pdf_page_number": 104,
        "sheet_number": 26,
        "stage_raw": "П",
        "stage": "PD",
        "sheet_title": "Принципиальная схема системы теплоснабжения приточных установок",
        "document_code_raw": PD_CODE,
        "document_code": PD_CODE,
        "object_name": OBJECT_NAME,
        "provenance": prov("TEXT_LAYER", 1.0),
    },
]
f0171["sheet_page_map"] = [
    {"pdf_page_number": p, "sheet_number": s, "basis": "TITLE_BLOCK", "confidence": 1.0}
    for p, s in ((88, 10), (99, 21), (104, 26))
]
zone_012_pd = [0.6971, 0.2742, 0.8884, 0.5741]
f0171["rooms"] = [
    # p104: section band of rooms 006/007/012; 012 = vent chamber
    room("012", 104, (0.863, 0.323), name="Венткамера"),
    room("006", 104, (0.30, 0.323)),
    room("007", 104, (0.60, 0.323)),
    # p88: vent schematic, rooms as columns (95 §3.3); 012 and 141 also appear here without local exhausts
    room("142", 88, (0.168, 0.655)),
    room("140", 88, (0.221, 0.655)),
    room("141", 88, (0.26, 0.655)),
    room("147", 88, (0.322, 0.665)),
    room("198", 88, (0.709, 0.665)),
    room("314", 88, (0.757, 0.361)),
    room("012", 88, (0.10, 0.85)),
    # p99: heating schematic, labels «267, 270» / «271, 272» (Раздевальная и санузел для МГН)
    room("267", 99, (0.293, 0.42)),
    room("270", 99, (0.297, 0.43)),
    room("271", 99, (0.313, 0.42)),
    room("272", 99, (0.317, 0.43)),
    room("012", 99, (0.72, 0.80)),
    # p11: ПЗ text «… (пом. 267, 270, 271, 272) предусмотрена система подогрева полов (теплые полы)…»
    *[
        room(t, 11, (0.3 + 0.04 * i, 0.5), source="TEXT_MENTION")
        for i, t in enumerate(("267", "270", "271", "272"))
    ],
]
pd_units = ["П2", "П2.1", "П3", "П8", "П9", "П10", "П15", "П17", "П18"]
f0171["tags"] = [
    *[
        tag(
            u, "EQUIPMENT", 104, "012", spread(zone_012_pd, i, len(pd_units)), layer="ОВ-Теплоснабжение-Текст"
        )
        for i, u in enumerate(pd_units)
    ],
    tag("П20", "EQUIPMENT", 104, "007", box(0.63, 0.414)),
]
pd_exhaust = {
    "142": (["В2.4", "В2.5", "В2.6"], [0.1671, 0.5751, 0.2637, 0.6884]),
    "140": (["В2.7", "В2.8", "В2.9"], [0.1671, 0.5751, 0.2637, 0.6884]),
    "147": (["В2.10"], [0.3177, 0.575, 0.3856, 0.6808]),
    "198": (["В2.2", "В2.3"], [0.6932, 0.5685, 0.7542, 0.6857]),
    "314": (["В3.1", "В3.2"], [0.7117, 0.2917, 0.7815, 0.4138]),
}
for rtok, (labels, zone) in pd_exhaust.items():
    for i, lab in enumerate(labels):
        f0171["tags"].append(tag(lab, "VENT_SYSTEM", 88, rtok, spread(zone, i, len(labels)), link="NEAREST"))
f0171["tags"] += [
    tag("М.О. поз.169", "EQUIPMENT", 88, "142", box(0.17, 0.60)),
    tag("М.О. поз.169", "EQUIPMENT", 88, "140", box(0.22, 0.60)),
    # p99: warm-floor loops on layer «ОВ-Отопление-Схема» inside the МГН rooms, leader to the Multibox regulator
    *[
        tag(
            "Контур тёплого пола",
            "HEATING_SYSTEM",
            99,
            t,
            spread([0.2832, 0.3502, 0.3406, 0.5082], i, 4),
            layer="ОВ-Отопление-Схема",
        )
        for i, t in enumerate(("267", "270", "271", "272"))
    ],
    tag(
        "Регулятор для системы “теплый пол” Multibox C/RTL",
        "EQUIPMENT",
        99,
        "267",
        box(0.332, 0.392),
        link="LEADER",
    ),
    tag(
        "Регулятор для системы “теплый пол” Multibox C/RTL",
        "EQUIPMENT",
        99,
        "271",
        box(0.332, 0.392),
        link="LEADER",
    ),
]
f0171["cad_layers"] = [
    {
        "name": "ОВ-Отопление-Схема",
        "pages": [99],
        "is_text_layer": False,
        "is_revision_layer": False,
        "discipline_hint": "ОВ",
    },
]

# ── F0201 (РД ОВ1 изм. 4) ───────────────────────────────────────────────────────────────────────
f0201 = base("F0201", "RD")
code_ov1 = "АНО/150321/1-РД-ОВ1"
f0201["title_blocks"] = [
    {
        "pdf_page_number": p,
        "sheet_number": s,
        "sheets_total": None,
        "document_code_raw": code_ov1,
        "document_code": code_ov1,
        "stage_raw": "Р",
        "stage": "RD",
        "sheet_title": t,
        "revision": "4",
        "change_rows": [
            {"change_no": "4", "count": None, "sheet": None, "doc_no": "839-24", "date": "11.08.2024"}
        ],
        "provenance": prov("OCR_LAYER_ISOLATED", 0.93),
    }
    for p, s, t in (
        (17, 4, "План подвала (вентиляция)"),
        (18, 5, "План 1-го этажа (вентиляция)"),
        (20, 7, "План 3-го этажа (вентиляция)"),
        (32, 17, "План венткамеры в осях 16-18 / К-Н (М1:50)"),
    )
]
f0201["sheet_page_map"] = [
    {
        "pdf_page_number": p,
        "sheet_number": s,
        "document_code": code_ov1,
        "basis": "TITLE_BLOCK",
        "confidence": 0.95,
    }
    for p, s in ((17, 4), (18, 5), (20, 7), (32, 17))
]
zone_012_rd = [0.8093, 0.4748, 0.9508, 0.604]
f0201["rooms"] = [
    room("012", 17, (0.867, 0.543), source="PLAN_LABEL", name="Венткамера"),
    room("012", 32, (0.50, 0.50), source="PLAN_LABEL", name="Венткамера"),
    room("140", 18, (0.922, 0.194), source="PLAN_LABEL"),
    room("142", 18, (0.906, 0.139), source="PLAN_LABEL"),
    room("141", 18, (0.915, 0.165), source="PLAN_LABEL"),
    room("147", 18, (0.907, 0.292), source="PLAN_LABEL"),
    room("198", 18, (0.705, 0.142), source="PLAN_LABEL"),
    room("314", 20, (0.725, 0.081), source="PLAN_LABEL"),
]
rd_units_p17 = ["П9", "П15", "П17.1, 17.2", "П18"]
f0201["tags"] = [
    *[
        tag(
            u,
            "EQUIPMENT",
            17,
            "012",
            spread(zone_012_rd, i, 5),
            source="OCR_LAYER_ISOLATED",
            conf=0.9,
            layer="ОВ-Вентиляция-Выноски",
        )
        for i, u in enumerate(rd_units_p17)
    ],
    tag("B2.1", "VENT_SYSTEM", 17, "012", spread(zone_012_rd, 4, 5), source="OCR_LAYER_ISOLATED", conf=0.88),
    tag(
        "Пароувлажнитель (П2)", "EQUIPMENT", 17, "012", box(0.84, 0.58), source="OCR_LAYER_ISOLATED", conf=0.9
    ),
    tag(
        "Пароувлажнитель (П2)", "EQUIPMENT", 17, "012", box(0.88, 0.58), source="OCR_LAYER_ISOLATED", conf=0.9
    ),
    *[
        tag(u, "EQUIPMENT", 32, "012", box(0.3 + 0.05 * i, 0.55), source="OCR_LAYER_ISOLATED", conf=0.92)
        for i, u in enumerate(["П2", "П2.1", "П3", "П8", "П9", "П10", "П15", "П17.1", "П17.2", "П18"])
    ],
    tag(
        "Пароувлажнитель (П2/П3)",
        "EQUIPMENT",
        32,
        "012",
        box(0.6, 0.6),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    # p18: 140/142 only general exchange «П2/ВЕ ±400 м³/ч»; В2.7–2.9 moved to 141; 147 and 198 re-composed
    tag("П2/ВЕ ±400 м³/ч", "AIR_TERMINAL", 18, "140", box(0.93, 0.20), source="OCR_LAYER_ISOLATED", conf=0.9),
    tag(
        "П2/ВЕ ±400 м³/ч", "AIR_TERMINAL", 18, "142", box(0.91, 0.145), source="OCR_LAYER_ISOLATED", conf=0.9
    ),
    tag(
        "В2.7,8,9 −950 м³/ч", "VENT_SYSTEM", 18, "141", box(0.92, 0.17), source="OCR_LAYER_ISOLATED", conf=0.9
    ),
    tag(
        "В2.2",
        "VENT_SYSTEM",
        18,
        "147",
        spread([0.8358, 0.2626, 0.9364, 0.322], 0, 4),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "В2.3",
        "VENT_SYSTEM",
        18,
        "147",
        spread([0.8358, 0.2626, 0.9364, 0.322], 1, 4),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "В2.4",
        "VENT_SYSTEM",
        18,
        "147",
        spread([0.8358, 0.2626, 0.9364, 0.322], 2, 4),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "В2.3,4 −150 м³/ч",
        "VENT_SYSTEM",
        18,
        "147",
        spread([0.8358, 0.2626, 0.9364, 0.322], 3, 4),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "В2.8",
        "VENT_SYSTEM",
        18,
        "198",
        spread([0.6915, 0.128, 0.8047, 0.1784], 0, 5),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "В2.9",
        "VENT_SYSTEM",
        18,
        "198",
        spread([0.6915, 0.128, 0.8047, 0.1784], 1, 5),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "В2.10",
        "VENT_SYSTEM",
        18,
        "198",
        spread([0.6915, 0.128, 0.8047, 0.1784], 2, 5),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "М.О. поз.159/162",
        "EQUIPMENT",
        18,
        "198",
        spread([0.6915, 0.128, 0.8047, 0.1784], 3, 5),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag(
        "П2/ВЕ ±150",
        "AIR_TERMINAL",
        18,
        "198",
        spread([0.6915, 0.128, 0.8047, 0.1784], 4, 5),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    # p20: 314 keeps one branch В3.1 (−600 м³/ч) and П3/ВЕ ±350
    tag(
        "В3.1 −600 м³/ч (над 3D-принтером, поз.133)",
        "VENT_SYSTEM",
        20,
        "314",
        box(0.72, 0.07),
        source="OCR_LAYER_ISOLATED",
        conf=0.9,
    ),
    tag("П3/ВЕ ±350", "AIR_TERMINAL", 20, "314", box(0.75, 0.09), source="OCR_LAYER_ISOLATED", conf=0.9),
]
f0201["qr_links"] = [
    {
        "pdf_page_number": p,
        "payload": f"exon 3eb2aa9d/1/wd/{p}",
        "doc_key": "3eb2aa9d",
        "doc_page": p,
        "target_file_id": "F0201",
        "target_pdf_page_number": p,
    }
    for p in (17, 18, 20)
]

# ── F0202 (РД ОВ2.1 изм. 3) ─────────────────────────────────────────────────────────────────────
f0202 = base("F0202", "RD")
code_ov21 = "АНО/150321/1-РД-ОВ2.1"
f0202["title_blocks"] = [
    {
        "pdf_page_number": 17,
        "sheet_number": 4,
        "document_code_raw": code_ov21,
        "document_code": code_ov21,
        "stage_raw": "Р",
        "stage": "RD",
        "sheet_title": "План 2-го этажа (отопление)",
        "revision": "3",
        "change_rows": [{"change_no": "3", "count": None, "sheet": "4", "doc_no": "861-24", "date": None}],
        "provenance": prov("OCR_LAYER_ISOLATED", 0.93),
    },
]
f0202["sheet_page_map"] = [
    {
        "pdf_page_number": 17,
        "sheet_number": 4,
        "document_code": code_ov21,
        "basis": "TITLE_BLOCK",
        "confidence": 0.95,
    }
]
f0202["rooms"] = [
    room(t, 17, xy, source="PLAN_LABEL")
    for t, xy in (
        ("267", (0.359, 0.675)),
        ("270", (0.355, 0.701)),
        ("271", (0.394, 0.675)),
        ("272", (0.392, 0.701)),
    )
]
f0202["tags"] = [
    tag(
        "PRADO Universal 22-500-700",
        "EQUIPMENT",
        17,
        t,
        box(x, y + 0.012),
        source="OCR_LAYER_ISOLATED",
        conf=0.88,
    )
    for t, (x, y) in (
        ("267", (0.359, 0.675)),
        ("270", (0.355, 0.701)),
        ("271", (0.394, 0.675)),
        ("272", (0.392, 0.701)),
    )
]
f0202["cad_layers"] = [
    {
        "name": "ОВ-Отопление-Изм. №3",
        "pages": [17],
        "visible_default": True,
        "is_text_layer": False,
        "is_revision_layer": True,
        "revision_label": "Изм. №3",
        "discipline_hint": "ОВ",
    },
]
f0202["revision_clouds"] = [
    {
        "pdf_page_number": 17,
        "bbox": [0.337, 0.687, 0.423, 0.73],
        "source": "OCG_LAYER",
        "layer": "ОВ-Отопление-Изм. №3",
        "revision_label": "Изм. №3",
        "rooms_covered": ["270", "272"],
        "confidence": 0.9,
    },
]
f0202["qr_links"] = [
    {
        "pdf_page_number": 17,
        "payload": "exon 87cc1a16/1/wd/17",
        "doc_key": "87cc1a16",
        "doc_page": 17,
        "target_file_id": "F0202",
        "target_pdf_page_number": 17,
    }
]

# ── F0198 (ИД: исполнительный чертёж = F0202 p17 by QR) ─────────────────────────────────────────
f0198 = base("F0198", "ID")
f0198["title_blocks"] = [
    {
        "pdf_page_number": 1,
        "sheet_number": 4,
        "document_code": code_ov21,
        "stage_raw": "Р",
        "stage": "ID",
        "sheet_title": "План 2-го этажа (отопление). Исполнительный чертёж",
        "revision": "3",
        "provenance": prov("OCR_LAYER_ISOLATED", 0.9),
    },
]
f0198["rooms"] = [
    room(t, 1, xy, source="PLAN_LABEL")
    for t, xy in (
        ("267", (0.359, 0.675)),
        ("270", (0.355, 0.701)),
        ("271", (0.394, 0.675)),
        ("272", (0.392, 0.701)),
    )
]
f0198["tags"] = [
    tag(
        "PRADO Universal 22-500-700",
        "EQUIPMENT",
        1,
        t,
        box(x, y + 0.012),
        source="OCR_LAYER_ISOLATED",
        conf=0.88,
    )
    for t, (x, y) in (
        ("267", (0.359, 0.675)),
        ("270", (0.355, 0.701)),
        ("271", (0.394, 0.675)),
        ("272", (0.392, 0.701)),
    )
]
f0198["qr_links"] = [
    {
        "pdf_page_number": 1,
        "payload": "exon 87cc1a16/1/wd/17",
        "doc_key": "87cc1a16",
        "doc_page": 17,
        "target_file_id": "F0202",
        "target_pdf_page_number": 17,
    }
]

OUT.mkdir(parents=True, exist_ok=True)
for doc in (f0171, f0198, f0201, f0202):
    (OUT / f"{doc['file_id']}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
print("written", sorted(p.name for p in OUT.glob("*.json")))
