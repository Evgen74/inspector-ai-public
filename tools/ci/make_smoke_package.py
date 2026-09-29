#!/usr/bin/env python3
"""Build a tiny synthetic package for the Docker smoke test: a zip with folders «пд/» and «рд/», one PDF each.

    python make_smoke_package.py OUT.zip

Self-contained (PyMuPDF only), so it can be piped into the API container, which has PyMuPDF in its venv:
``docker compose exec -T api python - /tmp/smoke.zip < tools/ci/make_smoke_package.py``.
Every PDF has a real text layer (Cyrillic through MuPDF's built-in Noto fonts) and a few parameters the matrix knows
(concrete class, reinforcement class, address), so recognition, comparison and export all have something to do.
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

import pymupdf

PAGES = {
    "пд/ПД_пояснительная_записка.pdf": [
        (
            "Пояснительная записка. Проектная документация",
            [
                "Объект: жилой дом, г. Тюмень, ул. Тестовая, д. 5.",
                "Шифр проекта АНО/150321/1-ПЗ.",
                "Фундамент: монолитная плита, класс бетона по прочности на сжатие В25.",
                "Рабочая арматура класса А500С, диаметр 12 мм.",
            ],
        ),
        (
            "Конструктивные решения",
            [
                "Стены подвала из бетона класса В25, толщина 250 мм.",
                "Гидроизоляция обмазочная, два слоя.",
                "Этажность здания 5 этажей, высота этажа 3,0 м.",
            ],
        ),
    ],
    "рд/РД_конструкции_КР.pdf": [
        (
            "Рабочая документация. Раздел КР",
            [
                "Шифр проекта АНО/150321/1-КР.",
                "Плита фундамента выполняется из бетона класса В30.",
                "Арматура рабочая класса А500С, диаметр 14 мм.",
            ],
        ),
        (
            "Спецификация материалов",
            [
                "Бетон тяжелый класса В30 на цементе ЦЕМ I 42,5.",
                "Арматурная сталь класса А500С по ГОСТ 34028-2016.",
                "Количество этажей 5.",
            ],
        ),
    ],
}


def build_pdf(pages: list[tuple[str, list[str]]], out: Path) -> None:
    doc = pymupdf.open()
    for title, lines in pages:
        page = doc.new_page(width=595, height=842)
        body = "".join(f"<p>{line}</p>" for line in lines)
        html = f'<h2 style="font-size:16px">{title}</h2><div style="font-size:12px">{body}</div>'
        page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 700), html)
        if not page.get_text().strip():
            raise RuntimeError("the generated page has no text layer")
    doc.save(out)
    doc.close()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    target = Path(argv[1])
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, pages in PAGES.items():
            pdf = Path(tmp) / Path(name).name
            build_pdf(pages, pdf)
            archive.write(pdf, arcname=name)
    print(f"{target}: {target.stat().st_size} bytes, {len(PAGES)} PDF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
