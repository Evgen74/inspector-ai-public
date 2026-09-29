"""Synthetic drawing sheets with a ГОСТ Р 21.101 stamp, for tests (no organizer data involved).

``make_stamp_pdf`` draws the stamp grid (form 3: 185 × 55 mm; form 6: 185 × 15 mm) in the bottom-right corner
inside a 20/5/5/5 mm frame, writes the labels and values as a text layer (font «tiro», which has Cyrillic),
optionally as an image only (an «outlined» stamp for OCR tests), and optionally places a QR code image.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

MM = 72.0 / 25.4


@dataclass(slots=True)
class StampSpec:
    form: str = "3"  # "3" or "6"
    code: str = "АНО/150321/1-РД-ОВ1"
    sheet: str = "4"
    sheets: str = ""
    stage: str = "Р"
    object_name: str = "Школа на 600 мест"
    section: str = "Отопление и вентиляция"
    title: str = "План 1-го этажа"
    org: str = "ООО «Проект»"
    change_rows: Sequence[tuple[str, str, str, str, str]] = field(
        default_factory=lambda: (
            ("2", "-", "Зам.", "690-23", "20.03.24"),
            ("1", "-", "Зам.", "582-23", "27.11.23"),
        )
    )
    split_sheet_label: bool = False  # «Лис» / «т» on two lines (narrow cell)
    header: bool = True


def _grid(page, x0: float, y0: float, spec: StampSpec) -> None:
    """Rulings of the stamp in mm (x0, y0 = top-left of the stamp)."""
    shape = page.new_shape()

    def line(xa: float, ya: float, xb: float, yb: float) -> None:
        shape.draw_line((xa * MM, ya * MM), (xb * MM, yb * MM))

    h = 55.0 if spec.form == "3" else 15.0
    line(x0, y0, x0 + 185, y0)
    line(x0, y0 + h, x0 + 185, y0 + h)
    line(x0, y0, x0, y0 + h)
    line(x0 + 185, y0, x0 + 185, y0 + h)
    for dx in (10, 20, 30, 40, 55, 65):
        line(x0 + dx, y0, x0 + dx, y0 + (h if spec.form == "6" else 55))
    for k in range(1, int(h // 5)):
        line(x0, y0 + 5 * k, x0 + 65, y0 + 5 * k)
    if spec.form == "3":
        line(x0 + 65, y0 + 15, x0 + 185, y0 + 15)
        line(x0 + 65, y0 + 30, x0 + 185, y0 + 30)
        line(x0 + 65, y0 + 45, x0 + 185, y0 + 45)
        line(x0 + 135, y0 + 30, x0 + 135, y0 + 55)
        line(x0 + 135, y0 + 35, x0 + 185, y0 + 35)
        line(x0 + 150, y0 + 30, x0 + 150, y0 + 45)
        line(x0 + 165, y0 + 30, x0 + 165, y0 + 45)
    else:
        line(x0 + 175, y0, x0 + 175, y0 + 15)
        line(x0 + 175, y0 + 7, x0 + 185, y0 + 7)
    shape.finish(color=(0, 0, 0), width=0.6)
    shape.commit()


def _texts(x0: float, y0: float, spec: StampSpec) -> list[tuple[float, float, str, float]]:
    """(x mm, baseline y mm, text, font size pt)."""
    t: list[tuple[float, float, str, float]] = []
    hdr_y = y0 + 54.0 if spec.form == "3" else y0 + 14.0  # baseline of the header row
    if spec.form == "3":
        hdr_y = y0 + 29.0  # header row 25–30 mm from the top of the stamp
    labels = (("Изм.", 1), ("Кол.уч", 10.6), ("Лист", 21), ("№ док.", 30.8), ("Подп.", 42), ("Дата", 56))
    if spec.header:
        for text, dx in labels:
            t.append((x0 + dx, hdr_y, text, 7.0))
    for k, row in enumerate(spec.change_rows, start=1):
        y = hdr_y - 5.0 * k
        for text, dx in zip(row, (4, 14, 21, 31, 56), strict=True):
            t.append((x0 + dx, y, text, 7.0))
    if spec.form == "3":
        t.append((x0 + 80, y0 + 10, spec.code, 14.0))
        t.append((x0 + 70, y0 + 24, spec.object_name, 10.0))
        for text, dx in (("Разраб.", 1), ("Иванов", 21), ("04.23", 56)):
            t.append((x0 + dx, y0 + 34, text, 7.0))
        for text, dx in (("Стадия", 137), ("Лист", 154), ("Листов", 169)):
            t.append((x0 + dx, y0 + 34, text, 7.0))
        t.append((x0 + 141, y0 + 41.5, spec.stage, 10.0))
        t.append((x0 + 156, y0 + 41.5, spec.sheet, 10.0))
        if spec.sheets:
            t.append((x0 + 172, y0 + 41.5, spec.sheets, 10.0))
        t.append((x0 + 68, y0 + 38, spec.section, 10.0))
        t.append((x0 + 68, y0 + 51, spec.title, 10.0))
        t.append((x0 + 140, y0 + 51, spec.org, 10.0))
    else:
        t.append((x0 + 90, y0 + 10, spec.code, 14.0))
        if spec.split_sheet_label:
            t.append((x0 + 177, y0 + 3.2, "Лис", 7.0))
            t.append((x0 + 178.5, y0 + 6.2, "т", 7.0))
        else:
            t.append((x0 + 176.5, y0 + 5, "Лист", 7.0))
        t.append((x0 + 178.5, y0 + 13, spec.sheet, 10.0))
    return t


def qr_png(payload: str, module_px: int = 6) -> bytes:
    import cv2

    enc = cv2.QRCodeEncoder.create()
    img = enc.encode(payload)
    img = cv2.resize(img, None, fx=module_px, fy=module_px, interpolation=cv2.INTER_NEAREST)
    img = cv2.copyMakeBorder(
        img, 2 * module_px, 2 * module_px, 2 * module_px, 2 * module_px, cv2.BORDER_CONSTANT, value=255
    )
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def make_stamp_pdf(
    path: Path,
    specs: Sequence[StampSpec | None],
    *,
    size_mm: tuple[float, float] = (420.0, 297.0),
    qr_payloads: Sequence[str | None] | None = None,
    outlined: bool = False,
    extra_text: Sequence[tuple[float, float, str, float]] = (),
) -> Path:
    """One page per spec (``None`` = a page with the frame only). Text in mm; ``outlined`` stamps are images."""
    import pymupdf

    doc = pymupdf.open()
    font = pymupdf.Font("tiro")
    for i, spec in enumerate(specs):
        page = doc.new_page(width=size_mm[0] * MM, height=size_mm[1] * MM)
        w, h = size_mm
        shape = page.new_shape()
        shape.draw_rect(pymupdf.Rect(20 * MM, 5 * MM, (w - 5) * MM, (h - 5) * MM))
        shape.finish(color=(0, 0, 0), width=1.0)
        shape.commit()
        if extra_text:
            tw = pymupdf.TextWriter(page.rect)
            for x, y, text, fs in extra_text:
                tw.append((x * MM, y * MM), text, font=font, fontsize=fs)
            tw.write_text(page)
        if spec is not None:
            sh = 55.0 if spec.form == "3" else 15.0
            x0, y0 = w - 5 - 185, h - 5 - sh
            if outlined:
                # draw the stamp on a scratch page, rasterise it, place it as an image (no text layer)
                tmp = pymupdf.open()
                tp = tmp.new_page(width=size_mm[0] * MM, height=size_mm[1] * MM)
                _grid(tp, x0, y0, spec)
                tw = pymupdf.TextWriter(tp.rect)
                for x, y, text, fs in _texts(x0, y0, spec):
                    tw.append((x * MM, y * MM), text, font=font, fontsize=fs)
                tw.write_text(tp)
                clip = pymupdf.Rect((x0 - 2) * MM, (y0 - 2) * MM, (w - 3) * MM, (h - 3) * MM)
                pix = tp.get_pixmap(dpi=300, clip=clip)
                page.insert_image(clip, stream=pix.tobytes("png"))
                tmp.close()
            else:
                _grid(page, x0, y0, spec)
                tw = pymupdf.TextWriter(page.rect)
                for x, y, text, fs in _texts(x0, y0, spec):
                    tw.append((x * MM, y * MM), text, font=font, fontsize=fs)
                tw.write_text(page)
        if qr_payloads and i < len(qr_payloads) and qr_payloads[i]:
            qx, qy = w - 5 - 185 + 66, h - 5 - 14
            page.insert_image(
                pymupdf.Rect(qx * MM, qy * MM, (qx + 13) * MM, (qy + 13) * MM), stream=qr_png(qr_payloads[i])
            )
    doc.save(path)
    doc.close()
    return path
