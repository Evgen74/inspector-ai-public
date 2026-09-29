"""Synthetic CAD-like sheets for the room/CAD tests (no organizer data needed).

:func:`vent_plan_pdf` draws a 1 190 × 842 pt «План 1-го этажа (вентиляция)» with CAD layers (OCG):

- ``АР-Стены``: outer walls and partitions → rooms 101 (left), 102 (right, door gap in the partition) and 012
  (bottom strip); numbers inside ⌀20 pt circles on ``АР_мебель``, text on ``АР-Марки``;
- ``ОВ-Вентиляция-Выноски``: «В2.4» on a shelf **in room 101** with a leader ending **in room 102**; «П1» in
  101 without a leader; «М.О.» in 102;
- ``DUCT-Вытяжка-TEXT``: «В2.7,8,9» (a list) in 012;
- ``ОВ-Изм. №2``: a revision cloud of 12 arcs around the label of room 102;
- the explication table «Экспликация помещений» (101, 102, 012, 103 with names and areas).

Everything is real text (font «tiro», Cyrillic), so the text-layer path of the pipeline reads it without OCR.
"""

from __future__ import annotations

import math
from itertools import pairwise
from pathlib import Path

W, H = 1190.0, 842.0
ROOMS = {"101": (160, 200), "102": (460, 200), "012": (310, 430)}  # label centres (displayed pt)


def vent_plan_pdf(path: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    walls = doc.add_ocg("АР-Стены", on=True)
    marks = doc.add_ocg("АР-Марки", on=True)
    furn = doc.add_ocg("АР_мебель", on=True)
    lead = doc.add_ocg("ОВ-Вентиляция-Выноски", on=True)
    duct = doc.add_ocg("DUCT-Вытяжка-TEXT", on=True)
    rev = doc.add_ocg("ОВ-Изм. №2", on=True)
    font = pymupdf.Font("tiro")

    def wall(x0: float, y0: float, x1: float, y1: float) -> None:
        page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), fill=(0, 0, 0), width=0.5, oc=walls)

    t = 6.0
    wall(60, 80, 640, 80 + t)  # top
    wall(60, 560 - t, 640, 560)  # bottom
    wall(60, 80, 60 + t, 560)  # left
    wall(640 - t, 80, 640, 560)  # right
    wall(60, 320, 640, 320 + t)  # 101/102 | 012
    wall(310, 80, 310 + t, 230)  # partition 101|102 with a door gap 230…280
    wall(310, 280, 310 + t, 320)

    def text(x: float, y: float, s: str, size: float, oc: int) -> None:
        tw = pymupdf.TextWriter(page.rect)
        tw.append((x, y), s, font=font, fontsize=size)
        tw.write_text(page, oc=oc)

    for room, (cx, cy) in ROOMS.items():
        page.draw_circle((cx, cy), 10, color=(0, 0, 0), width=0.4, oc=furn)
        text(cx - 8.5, cy + 3.5, room, 10, marks)

    # «В2.4» on a shelf in room 101, leader to a point inside room 102
    text(200, 150, "В2.4", 10, lead)
    page.draw_line((198, 153), (232, 153), color=(0, 0, 0), width=0.3, oc=lead)
    page.draw_line((232, 153), (420, 260), color=(0, 0, 0), width=0.3, oc=lead)
    text(120, 270, "П1", 10, lead)  # no leader: INSIDE 101
    text(520, 280, "М.О.", 10, lead)  # INSIDE 102
    text(250, 470, "В2.7,8,9", 10, duct)  # INSIDE 012 (a list)

    # revision cloud around the label of 102
    shape = page.new_shape()
    cx, cy, rx, ry, n = 460.0, 200.0, 45.0, 30.0, 12
    pts = [
        (cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n))
        for k in range(n + 1)
    ]
    for (x0, y0), (x1, y1) in pairwise(pts):
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ox, oy = (mx - cx) * 0.35, (my - cy) * 0.35  # bulge outwards: scallops
        shape.draw_bezier((x0, y0), (x0 + ox, y0 + oy), (x1 + ox, y1 + oy), (x1, y1))
    shape.finish(color=(0, 0, 1), width=0.4, oc=rev)
    shape.commit()

    # explication table
    text(700, 110, "Экспликация помещений", 12, marks)
    rows = [("101", "Кабинет", "20,5"), ("102", "Лаборантская", "15,0"), ("012", "Венткамера", "30,1"),
            ("103", "Коридор", "10,0")]  # fmt: skip
    for i, (num, name, area) in enumerate(rows):
        y = 140 + i * 18
        text(700, y, num, 10, marks)
        text(740, y, name, 10, marks)
        text(880, y, area, 10, marks)
    text(700, 780, "План 1-го этажа (вентиляция)", 16, marks)
    doc.save(path)
    doc.close()
    return path
