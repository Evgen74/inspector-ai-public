"""Synthetic objects for inspector_compare tests (no organizer data needed).

Object ids and file ids are synthetic (OBJ-SYN-*, F90xx); layouts follow the ``layout_artifacts`` contract. Tests
that need the organizer package are marked ``data`` and use the ``data_paths`` fixture (skipped without data).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from inspector_common.settings import Settings
from inspector_compare.config import default_config
from inspector_compare.objectctx import InputDirs, ObjectContext, build_context

OBJ = "OBJ-SYN-1"


def sha(n: int) -> str:
    return f"{n:064x}"


def manifest_row(
    file_id: str, stage: str, section: str, path: str, pages: int | None = 100, **extra: Any
) -> dict[str, Any]:
    row = {
        "schema_version": "0.1.0",
        "file_id": file_id,
        "object_id": extra.pop("object_id", OBJ),
        "corpus": "Синтетический объект",
        "dataset_role": "UNLABELED_POOL",
        "split": "TRAIN_PUBLIC",
        "relative_path": path,
        "extension": extra.pop("extension", ".pdf"),
        "size_bytes": 1000,
        "sha256": sha(int(file_id[1:])),
        "stage": stage,
        "section": section,
        "pdf_pages": pages,
        "annotation_status": extra.pop("annotation_status", "UNLABELED"),
        "exclusion_reason": None,
        "duplicate_group": None,
        "distribution_status": "INCLUDE",
        "label_visibility": "PUBLIC_TRAIN",
    }
    row.update(extra)
    return row


def default_rows() -> list[dict[str, Any]]:
    return [
        manifest_row("F9001", "PD", "OV", "syn/ПД/5.4 Отопление, вентиляция/Том 5.4.2 ОВ.pdf", 200),
        manifest_row("F9002", "RD_ID_MIXED", "OV", "syn/РД/Полные разделы/SYN-РД-ОВ1.pdf", 100),
        manifest_row("F9003", "RD_ID_MIXED", "OV", "syn/РД/Полные разделы/SYN-РД-ОВ2.pdf", 50),
        manifest_row("F9004", "PD", "KR", "syn/ПД/4 Конструктивные решения/Том 4.pdf", 30),
        manifest_row("F9005", "RD_ID_MIXED", "OV", "syn/ИД/АОСР №1 ОВ.pdf", 3),
        manifest_row(
            "F9006",
            "UNKNOWN",
            "OTHER",
            "syn/Перечень нарушений.txt",
            None,
            extension=".txt",
            annotation_status="GROUND_TRUTH_INDEX",
        ),
    ]


def box(x: float, y: float) -> list[float]:
    return [round(x - 0.01, 4), round(y - 0.01, 4), round(x + 0.01, 4), round(y + 0.01, 4)]


def room(
    token: str,
    page: int,
    source: str = "PLAN_LABEL",
    name: str | None = None,
    xy: tuple[float, float] = (0.5, 0.5),
) -> dict[str, Any]:
    out: dict[str, Any] = {"room_token": token, "pdf_page_number": page, "bbox": box(*xy), "source": source}
    if name:
        out["name"] = name
    return out


def tag(
    raw: str, kind: str, page: int, room_token: str, xy: tuple[float, float] = (0.5, 0.5), conf: float = 1.0
) -> dict[str, Any]:
    return {
        "tag": raw,
        "tag_kind": kind,
        "pdf_page_number": page,
        "bbox": box(*xy),
        "room_token": room_token,
        "room_link": "INSIDE",
        "provenance": {"text_source": "TEXT_LAYER", "confidence": conf},
    }


def title(page: int, sheet: int, text: str, code: str | None = None, stage: str = "RD") -> dict[str, Any]:
    out: dict[str, Any] = {
        "pdf_page_number": page,
        "sheet_number": sheet,
        "sheet_title": text,
        "stage": stage,
    }
    if code:
        out["document_code"] = code
    return out


def layout(
    file_id: str,
    stage: str,
    *,
    titles: Iterable[dict] = (),
    rooms: Iterable[dict] = (),
    tags: Iterable[dict] = (),
    clouds: Iterable[dict] = (),
    object_id: str = OBJ,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "file_id": file_id,
        "object_id": object_id,
        "file_sha256": sha(int(file_id[1:])),
        "stage": stage,
        "pipeline_version": "test",
        "generated_at": "2026-09-28T00:00:00Z",
        "pages_total": 200,
        "title_blocks": list(titles),
        "rooms": list(rooms),
        "tags": list(tags),
        "revision_clouds": list(clouds),
    }


def write_layouts(directory: Path, layouts: Iterable[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for doc in layouts:
        (directory / f"{doc['file_id']}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
    return directory


def explication(
    file_id: str, stage: str, page: int, rooms: Iterable[tuple[str, str]], object_id: str = OBJ
) -> dict[str, Any]:
    """A TableArtifacts document with one EXPLICATION table (room number, name) on ``page``."""
    return {
        "schema_version": 1,
        "file_id": file_id,
        "object_id": object_id,
        "file_sha256": sha(int(file_id[1:])),
        "stage": stage,
        "pipeline_version": "test",
        "generated_at": "2026-09-28T00:00:00Z",
        "tables": [
            {
                "table_id": f"{file_id}-p{page}-EXPLICATION-1",
                "table_type": "EXPLICATION",
                "pages": [page],
                "columns": [{"key": "room_no"}, {"key": "name"}],
                "rows": [
                    {
                        "row_no": n,
                        "kind": "DATA",
                        "cells": {"room_no": {"raw": token}, "name": {"raw": name}},
                        "pdf_page_number": page,
                    }
                    for n, (token, name) in enumerate(rooms, start=1)
                ],
            }
        ],
    }


def make_context(
    tmp_path: Path,
    layouts: Iterable[dict[str, Any]] = (),
    rows: list[dict[str, Any]] | None = None,
    values: Iterable[dict[str, Any]] = (),
    local_status: str | None = "PRESENT",
    tables: Iterable[dict[str, Any]] = (),
) -> ObjectContext:
    layout_dir = write_layouts(tmp_path / "layout", layouts)
    tables_dir = write_layouts(tmp_path / "tables", tables)
    values_path = tmp_path / "values.jsonl"
    values_path.write_text(
        "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in values), encoding="utf-8"
    )
    rows = rows if rows is not None else default_rows()
    ctx = build_context(
        OBJ,
        rows,
        split="TRAIN_PUBLIC",
        name="Синтетический объект",
        excluded=frozenset({"F0999"}),
        inputs=InputDirs(layout_dir, tables_dir, values_path, None, "test"),
        not_citable={
            r["file_id"]: ["служебный файл разметки"]
            for r in rows
            if r["annotation_status"] == "GROUND_TRUTH_INDEX"
        },
    )
    if local_status is not None:
        import dataclasses

        ctx.files = {k: dataclasses.replace(v, local_status=local_status) for k, v in ctx.files.items()}
    return ctx


VENT_PD = "Принципиальная схема систем общеобменной вентиляции"
VENT_RD = "План 1-го этажа (вентиляция)"


def ventilation_layouts() -> list[dict[str, Any]]:
    """PD schematic p10 vs RD plan p5/p7: 101 missing, 102/202/203 changed, 103 renumbered, 104 unresolved,
    105 added, 201 kept + added (В5.1 → В5.1, В5.2: an addition, directional trigger)."""
    pd = layout(
        "F9001",
        "PD",
        titles=[title(10, 10, VENT_PD, stage="PD")],
        rooms=[
            room(t, 10, "SCHEMATIC_LABEL") for t in ("101", "102", "103", "104", "105", "201", "202", "203")
        ],
        tags=[
            tag("В1.1", "VENT_SYSTEM", 10, "101"),
            tag("В1.2", "VENT_SYSTEM", 10, "101"),
            tag("В1.3", "VENT_SYSTEM", 10, "102"),
            tag("В2.1", "VENT_SYSTEM", 10, "103"),
            tag("В2.2", "VENT_SYSTEM", 10, "103"),
            tag("В3.1", "VENT_SYSTEM", 10, "104"),
            tag("В5.1", "VENT_SYSTEM", 10, "201"),
            tag("В5.2", "VENT_SYSTEM", 10, "202"),
            tag("В5.3", "VENT_SYSTEM", 10, "203"),
            tag("В5.4", "VENT_SYSTEM", 10, "203"),
        ],
    )
    rd = layout(
        "F9002",
        "RD",
        titles=[
            title(5, 5, VENT_RD, "SYN/1-РД-ОВ1"),
            title(7, 7, "План 2-го этажа (вентиляция)", "SYN/1-РД-ОВ1"),
        ],
        rooms=[room(t, 5) for t in ("101", "102", "103", "105", "201", "202")] + [room("203", 7)],
        tags=[
            tag("П1/ВЕ ±400 м³/ч", "AIR_TERMINAL", 5, "101"),
            tag("B1.4", "VENT_SYSTEM", 5, "102"),
            tag("В1.5 −150 м³/ч", "VENT_SYSTEM", 5, "102"),
            tag("В2.5,6", "VENT_SYSTEM", 5, "103"),
            tag("В4.1", "VENT_SYSTEM", 5, "105"),
            tag("В5.1", "VENT_SYSTEM", 5, "201"),
            tag("В5.2", "VENT_SYSTEM", 5, "201"),
            tag("В5.7", "VENT_SYSTEM", 5, "202"),
            tag("В5.8", "VENT_SYSTEM", 5, "202"),
            tag("В5.9", "VENT_SYSTEM", 7, "203"),
        ],
    )
    return [pd, rd]


@pytest.fixture()
def cfg():
    """Defaults without the installed AG-07 hook (engine tests stay independent of inspector_hypothesis)."""
    import dataclasses

    return dataclasses.replace(default_config(), free_hook=False)


@pytest.fixture()
def syn() -> SimpleNamespace:
    """The synthetic builders of this module (test modules cannot import conftest under importlib mode)."""
    return SimpleNamespace(
        OBJ=OBJ,
        VENT_PD=VENT_PD,
        VENT_RD=VENT_RD,
        sha=sha,
        manifest_row=manifest_row,
        default_rows=default_rows,
        box=box,
        room=room,
        tag=tag,
        title=title,
        layout=layout,
        write_layouts=write_layouts,
        explication=explication,
        make_context=make_context,
        ventilation_layouts=ventilation_layouts,
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def data_paths(settings: Settings):
    paths = settings.paths
    if not paths.has_package():
        pytest.skip(f"organizer data not found under {paths.data_root}")
    return paths
