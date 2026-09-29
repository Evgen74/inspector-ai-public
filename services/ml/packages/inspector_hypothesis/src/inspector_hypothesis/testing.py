"""Synthetic inputs for tests (ours and AG-04's): pages, tables and a Тюменская-like warm-floor scenario.

The scenario mirrors the public train gold G-TR-002 (95_tyumen_dev_fixtures.json coordinates): PD F0171 states warm
floors in rooms 267/270/271/272 (ПЗ text p11, heating schematic p99, specification p136); RD F0202 (heating) p17 shows
the rooms without warm floors; RD F0201 (ventilation) p19 shows the same rooms on a ventilation plan. Everything is
synthetic text placed at the measured positions; no organizer file is read.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from inspector_common.contracts.models import TableArtifacts
from inspector_hypothesis.inputs import DocumentInfo, HypothesisInputs, MemoryPageSource, PageText, Word
from inspector_hypothesis.textmatch import norm_word

OBJECT_ID = "OBJ-TYUMENSKAYA-5-GOLD-SEED"
A4 = (595.0, 842.0)
A3_LANDSCAPE = (1191.0, 842.0)
A0_PORTRAIT = (2384.0, 3370.0)
PD_SCHEME = (4212.0, 1191.0)
SHA = {
    fid: f"{i:064x}"
    for i, fid in enumerate(["F0171", "F0201", "F0202", "F0198", "F0156", "F0203", "F0197"], 1)
}


def page(
    file_id: str,
    page_no: int,
    size: tuple[float, float],
    lines: Sequence[Sequence[tuple[str, float, float]] | str | tuple[str, float, float]],
    *,
    usable: bool = True,
    char_w: float | None = None,
) -> PageText:
    """A page from lines. A line is a string (laid out at the top-left, one per row), a word list
    [(text, x, y), …] with normalised word origins, or one (text, x, y) tuple split into words from x."""
    w_pt, h_pt = size
    cw = char_w if char_w is not None else 6.0 / w_pt  # ~6 pt per character
    lh = 10.0 / h_pt
    words: list[Word] = []
    out_lines: list[list[int]] = []
    auto_y = 0.02
    for line in lines:
        items: list[tuple[str, float, float]]
        if isinstance(line, str):
            items = _split(line, 0.05, auto_y, cw, lh)
            auto_y = max(y for _, _, y in items) + 1.5 * lh if items else auto_y + 1.5 * lh
        elif isinstance(line, tuple):
            items = _split(line[0], line[1], line[2], cw, lh)
        else:
            items = list(line)
        idxs = []
        for text, x, y in items:
            words.append(
                Word(
                    text,
                    norm_word(text),
                    (x, y, min(1.0, x + cw * len(text)), min(1.0, y + lh)),
                    len(out_lines),
                )
            )
            idxs.append(len(words) - 1)
        out_lines.append(idxs)
    return PageText(file_id, page_no, w_pt, h_pt, words, out_lines, usable=usable)


def _split(text: str, x: float, y: float, cw: float, lh: float = 0.012) -> list[tuple[str, float, float]]:
    """Words of a text from (x, y), wrapped to the next row before the right page edge."""
    out = []
    x0 = x
    for token in text.split():
        width = cw * len(token)
        if x + width > 0.98 and x > x0:
            x, y = x0, min(0.97, y + 1.2 * lh)
        out.append((token, x, y))
        x += cw * (len(token) + 1)
    return out


def filler(
    file_id: str, page_no: int, size: tuple[float, float] = A4, text: str = "Общие данные. Ведомость листов"
) -> PageText:
    return page(file_id, page_no, size, [text])


def doc(file_id: str, stage: str, section: str, pages: int, **kw: object) -> DocumentInfo:
    return DocumentInfo(
        file_id=file_id, stage=stage, section=section, pages_total=pages, file_sha256=SHA.get(file_id), **kw
    )  # type: ignore[arg-type]


# ── real table rows, transcribed from the text layer (values as printed) ─────────────────────────────

# Real rows: pilot ALT79B ПД «Спецификация помещений 1-го этажа» (ТЗ «Комплект предметной разметки», p. 2).
ALT79B_ROOMS = [
    ("1", "Зона мойки", "165.05"),
    ("2", "Зона выдачи", "69.10"),
    ("3", "Сан.узел МГН", "5.35"),
    ("4", "Сан.узел", "4.33"),
    ("5", "Зал ожидания", "231.17"),
    ("6", "Тамбур", "17.32"),
    ("7", "Торговый зал", "577.22"),
    ("8", "Зона тех.обслуживания", "1284.27"),
    ("9", "Зона выгрузки", "73.82"),
    ("10", "Зона выгрузки", "32.70"),
    ("11", "Сан.узел", "1.93"),
    ("12", "Сан.узел", "1.72"),
    ("13", "ПУИ", "2.14"),
    ("14", "Кабинет", "23.89"),
    ("15", "Приемная", "11.16"),
    ("16", "Кабинет", "43.69"),
    ("17", "Электрощитовая", "6.95"),
    ("18", "Тех.помещение", "10.15"),
    ("19", "Насосная", "51.76"),
    ("20", "ИТП", "72.85"),
    ("21", "Инструментальная", "40.50"),
    ("23", "Помещение", "19.41"),
    ("А", "Лестничная клетка", "24.51"),
    ("Б", "Лестничный марш", "24.05"),
]
# Real rows: Тюменская РД F0201 p18, «Экспликация помещений 1 этажа», group «Группа начальных классов».
TYUMEN_P18_ROOMS = [
    ("101", "Тамбур", "8.6"),
    ("102", "Вестибюль со стойкой для зарядки мобильных устройств, в том числе:", "134.0"),
    ("103", "Санузел МГН для посетителей", "5.0"),
    ("104", "Комната охраны с диспетчерским пунктом", "15.2"),
    ("107", "Гардероб начальной школы", "80.0"),
    ("108", "Рекреация коридорного типа", "236.2"),
    ("109", "Учебный кабинет (1-е классы)", "71.9"),
    ("110", "Учебный кабинет (1-е классы)", "69.4"),
    ("111", "Игровая с возможностью организ. спальных мест", "125.5"),
    ("112", "Административный кабинет", "20.9"),
    ("113", "Универсальное помещение", "76.0"),
    ("114", "ПУИ", "6.2"),
    ("115", "Санузел для персонала", "6.0"),
    ("116", "Санузел для девочек", "18.1"),
    ("117", "Санузел для МГН", "5.0"),
    ("118", "Санузел для мальчиков", "15.9"),
    ("120", "Лестничная клетка", "26.5"),
    ("122", "Кабинет иностранного языка", "91.3"),
    ("123", "Коридор", "37.8"),
]
TYUMEN_P18_SUBZONE = [(1, "зона ожидания для посетителей со стойкой зарядки мобильных устройств", "30.4")]


# ── the Тюменская-like warm-floor scenario ─────────────────────────────────────────────────────────


@dataclass
class Scenario:
    documents: dict[str, DocumentInfo]
    pages: MemoryPageSource
    tables: dict[str, TableArtifacts]
    values: list[Any] = field(default_factory=list)  # ExtractedValue rows (AG-02C)

    def inputs(self, run_id: str = "test-run") -> HypothesisInputs:
        return HypothesisInputs(
            OBJECT_ID,
            dict(self.documents),
            self.pages,
            tables=dict(self.tables),
            values=list(self.values),
            run_id=run_id,
        )

    def drop_page(self, file_id: str, page_no: int) -> None:
        self.pages._pages.pop((file_id, page_no), None)

    def replace(self, p: PageText) -> None:
        self.pages.add(p)


PD_P11_TEXT = [
    "Отопление. В качестве нагревательных приборов приняты стальные радиаторы в гигиеническом исполнении “ PRADO”) или аналоги.",
    "Все применяемые приборы должны быть выполнены в травмобезопасном исполнении.",
    "В помещениях раздевальных, санузлов и душевых для МГН (пом. 267, 270,",
    "271, 272) предусмотрена система подогрева полов (теплые полы) совмещенная с",
    "системой радиаторного отопления. Регулирование температуры пола",
    "осуществляется регуляторами оснащенными устройствами для ограничения",
    "максимальной температуры обратного потока теплоносителя “Multibox C/RTL”",
    "фирмы “IMI HEIMEIER” или аналогичными.",
]


def pd_p99() -> PageText:
    """Heating schematic, л.21 (measured label positions of F0171 p99)."""
    return page(
        "F0171",
        99,
        PD_SCHEME,
        [
            [("267,", 0.293, 0.42), ("270", 0.298, 0.42)],
            [("271,", 0.313, 0.42), ("272", 0.317, 0.42)],
            [("Раздевальная", 0.293, 0.43), ("МГН", 0.304, 0.44)],
            [("Раздевальная", 0.313, 0.43), ("МГН", 0.324, 0.44)],
            [("277", 0.333, 0.443)],
            [("268", 0.275, 0.434)],
            [("266", 0.294, 0.381)],
            [
                ("Регулятор", 0.300, 0.392),
                ("для", 0.318, 0.392),
                ("систы", 0.324, 0.392),
                ("“теплый", 0.332, 0.392),
                ("пол”", 0.342, 0.392),
            ],
            [("Multibox", 0.332, 0.402), ("C/RTL", 0.345, 0.402)],
            [("Т11", 0.2, 0.5), ("Т21", 0.21, 0.5)],
            ("Принципиальная схема системы отопления", 0.80, 0.93),
        ],
    )


def pd_p136() -> PageText:
    return page(
        "F0171",
        136,
        A3_LANDSCAPE,
        [
            "Набор для подкоючения радиатора, 16 мм с гайкой 3/4“ 269 AQUATHERM арт. 83006 шт",
            "Регулятор для системы “теплый пол” IMI HEIMEIER компл. 2 Multibox C/RTL шт",
        ],
    )


def rd_heating_p17(extra: Iterable[tuple[str, float, float]] = ()) -> PageText:
    """RD ОВ2.1 heating plan of floor 2 (F0202 p17): rooms, radiators, no warm floors."""
    lines: list = [
        [("267", 0.359, 0.675)],
        [("270", 0.355, 0.701)],
        [("271", 0.394, 0.675)],
        [("272", 0.392, 0.701)],
        [("PRADO", 0.36, 0.69), ("Universal", 0.37, 0.69), ("22-500-700", 0.38, 0.69)],
        [("+22", 0.40, 0.72), ("°C", 0.41, 0.72), ("700/690", 0.42, 0.72), ("Вт", 0.44, 0.72)],
        [("Т1", 0.30, 0.60), ("Т2", 0.31, 0.60)],
        ("План 2 эт. отопл.", 0.80, 0.97),
    ]
    lines.extend([list(extra)] if extra else [])
    return page("F0202", 17, A0_PORTRAIT, lines)


def rd_vent_p19() -> PageText:
    """RD ОВ1 ventilation plan of floor 2 (F0201 p19): the same rooms, ventilation tags only."""
    return page(
        "F0201",
        19,
        A0_PORTRAIT,
        [
            [("267", 0.36, 0.67)],
            [("270", 0.35, 0.70)],
            [("271", 0.39, 0.67)],
            [("272", 0.39, 0.70)],
            [("П3", 0.37, 0.68), ("В2.1", 0.38, 0.69)],
            ("План 2-го этажа (вентиляция)", 0.80, 0.97),
        ],
    )


def tyumen_warm_floor(*, rd_heating_pages: int = 20, rd_vent_pages: int = 20) -> Scenario:
    """PD F0171 (3 relevant pages), RD F0202 heating (fully read), RD F0201 ventilation (fully read)."""
    documents = {
        "F0171": doc("F0171", "PD", "OV", 177, name="V2_01-05-04-02-07_Том 5.4.2 ОВ (1).pdf"),
        "F0202": doc("F0202", "RD", "OV", rd_heating_pages, name="АНО-150321-1-РД-ОВ2.1_изм. 3_в1.pdf"),
        "F0201": doc("F0201", "RD", "OV", rd_vent_pages, name="АНО-150321-1-РД-ОВ1 изм. 4_в1 (1).pdf"),
    }
    pages = MemoryPageSource(
        [
            page("F0171", 11, A4, PD_P11_TEXT),
            pd_p99(),
            pd_p136(),
            rd_heating_p17(),
            rd_vent_p19(),
        ]
    )
    for p in range(1, rd_heating_pages + 1):
        if p != 17:
            pages.add(filler("F0202", p, text="Отопление. Общие данные"))
    for p in range(1, rd_vent_pages + 1):
        if p != 19:
            pages.add(filler("F0201", p, text="Вентиляция. Общие данные"))
    return Scenario(documents, pages, {})


# ── contract tables and layouts ────────────────────────────────────────────────────────────────────

from inspector_common.contracts.models import (  # noqa: E402
    ChangeRow,
    ExtractedValue,
    LayoutArtifacts,
    TableCell,
    TableColumn,
    TableRow,
    TitleBlock,
    TypedTable,
)
from inspector_common.contracts.models import TableArtifacts as _TableArtifacts  # noqa: E402

GENERATED_AT = "2026-09-28T00:00:00Z"


def typed_table(
    table_id: str,
    table_type: str,
    rows: Sequence[dict[str, object]],
    *,
    page_no: int = 1,
    title: str | None = None,
) -> TypedTable:
    """Rows as dicts: cell keys of the table type plus optional «_kind», «_parent», «_page»."""
    keys: list[str] = []
    out_rows = []
    for n, r in enumerate(rows, 1):
        cells = {}
        for k, v in r.items():
            if k.startswith("_"):
                continue
            if k not in keys:
                keys.append(k)
            cells[k] = TableCell(raw=None if v is None else str(v))
        out_rows.append(
            TableRow(
                row_no=n,
                cells=cells,
                kind=r.get("_kind"),  # type: ignore[arg-type]
                parent_row_no=r.get("_parent"),  # type: ignore[arg-type]
                pdf_page_number=r.get("_page", page_no),  # type: ignore[arg-type]
                bbox=[0.1, 0.1 + 0.01 * n, 0.3, 0.11 + 0.01 * n],
            )
        )
    return TypedTable(
        table_id=table_id,
        table_type=table_type,  # type: ignore[arg-type]
        title=title,
        pages=[page_no],
        columns=[TableColumn(key=k) for k in keys],
        rows=out_rows,
        confidence=1.0,
    )


def table_artifacts(file_id: str, stage: str, tables: Sequence[TypedTable]) -> _TableArtifacts:
    return _TableArtifacts(
        file_id=file_id,
        object_id=OBJECT_ID,
        file_sha256=SHA.get(file_id, "0" * 64),
        stage=stage,  # type: ignore[arg-type]
        pipeline_version="test",
        generated_at=GENERATED_AT,
        tables=list(tables),
    )


def explication(
    table_id: str,
    rooms: Sequence[tuple[str, str, str]],
    total: tuple[str, str],
    *,
    subzones: Sequence[tuple[int, str, str]] = (),
    page_no: int = 1,
    title: str | None = "Экспликация помещений 1 этажа",
) -> TypedTable:
    """rooms: (room_no, name, area); subzones: (index of the parent in rooms, name, area); total: (label, area)."""
    rows: list[dict[str, object]] = []
    for i, (no, name, area) in enumerate(rooms):
        rows.append({"room_no": no, "name": name, "area_m2": area, "_kind": "DATA"})
        for parent, sname, sarea in subzones:
            if parent == i:
                rows.append({"name": sname, "area_m2": sarea, "_kind": "SUBZONE", "_parent": len(rows)})
    rows.append({"name": total[0], "area_m2": total[1], "_kind": "TOTAL"})
    return typed_table(table_id, "EXPLICATION", rows, page_no=page_no, title=title)


def layout(file_id: str, stage: str, pages_total: int, title_blocks: Sequence[TitleBlock]) -> LayoutArtifacts:
    return LayoutArtifacts(
        file_id=file_id,
        object_id=OBJECT_ID,
        file_sha256=SHA.get(file_id, "0" * 64),
        stage=stage,  # type: ignore[arg-type]
        pipeline_version="test",
        generated_at=GENERATED_AT,
        pages_total=pages_total,
        title_blocks=list(title_blocks),
    )


def title_block(page_no: int, code: str, sheet: int, changes: Sequence[tuple[str, str]] = ()) -> TitleBlock:
    return TitleBlock(
        pdf_page_number=page_no,
        document_code=code,
        sheet_number=sheet,
        change_rows=[ChangeRow(change_no=n, date=d) for n, d in changes] or None,
    )


def element_room_values(
    file_id: str,
    page_no: int,
    rooms: Sequence[str],
    text: str,
    *,
    family: str = "WARM_FLOOR",
    channel: str = "TEXT",
    anchor: str = "теплые полы",
    bbox: Sequence[float] = (0.1, 0.3, 0.9, 0.36),
) -> list[ExtractedValue]:
    """AG-02C ``pd.element_room`` values as ``inspector_tables.values.from_assertions`` writes them: one per room
    (location = the printed token), or one object-level value when there is no room (SPEC)."""
    method = {"TEXT": "REGEX", "LABEL": "TOKEN_GRAMMAR", "SPEC": "TABLE", "TABLE": "TABLE"}[channel]
    q = {"family": family, "channel": channel, "anchor": anchor, "rooms": list(rooms)}
    out: list[ExtractedValue] = []
    for n, room in enumerate(list(rooms) or [None], 1):
        v: dict[str, object] = {
            "value_id": f"{file_id}-p{page_no:05d}-pd.element_room-{n:05d}",
            "object_id": OBJECT_ID,
            "file_id": file_id,
            "file_sha256": SHA.get(file_id, "0" * 64),
            "stage": "PD",
            "page_no": page_no,
            "page_basis": "PDF_NATIVE",
            "fact_key": "pd.element_room",
            "value_raw": text[:300],
            "value_norm": {
                "type": "boolean",
                "value": True,
                "qualifiers": {**q, **({"room_key": room} if room else {})},
            },
            "method": method,
            "confidence": 0.9,
            "quality_flag": "OK",
            "pipeline_version": "tables-test",
            "geometry": {"boxes": [list(bbox)]},
            "geometry_space": "PDF_VISIBLE_ROTATED_TL_V1",
            "text_source": "TEXT_LAYER",
            "context_text": text[:500],
            "anchor": {"text": anchor},
        }
        if room:
            v["location"], v["location_type"] = room, "ROOM"
        else:
            v["location_type"] = "OBJECT"
        out.append(ExtractedValue.model_validate(v))
    return out
