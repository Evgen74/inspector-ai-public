"""CAD layers kept as PDF optional content (OCG): listing, classes, isolated renders, token attribution (95 R2/R4).

42 of 57 Тюменская PDFs and 83 of 126 Новослободская PDFs keep their CAD layers; one file can carry the
same layer name in many OCGs (F0202: 1 913 OCGs, 127 names — one set per referenced drawing). Here a layer
is its **name**; ``xref`` is the first OCG with that name.

Layer classes are decided by the name only (regex on the folded, lower-cased name) — they steer:

- ``WALL``/``DOOR``/``WINDOW``: the barrier render for room regions (:mod:`inspector_layout.rooms.zones`);
- ``TEXT``/``LEADER``/``AIRFLOW``: leaders and label layers (:mod:`inspector_layout.cad.leaders`); the TEXT
  pattern equals AG-02A's layer-isolation pattern (``RecognitionConfig.text_layer_pattern``);
- ``REVISION``: change clouds (:mod:`inspector_layout.cad.clouds`); ``revision_label`` → «Изм. №3»;
- ``DUCT``/``HEATING``/``FURNITURE``/``AXIS``/``DIMENSION``/``FRAME``: provenance and filters.

Renders switch layers through the document's layer UI configuration and always restore it (text extraction
honours visibility too). Content outside any OCG (frames, stamps) stays visible in every render.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from inspector_layout.cad.geometry import DrawingIndex, PageFrame
from inspector_layout.rooms.grammar import fold

# AG-02A's pattern for text-like layers (inspector_docproc.config.RecognitionConfig.text_layer_pattern).
TEXT_LAYER_PATTERN = r"(-TEXT$|Выноск|Текст|Text|Подпис|Надпис|Воздухообмен|Маркировк|Теплопотер|Нагрузк)"

_CLASS_RULES: tuple[tuple[str, str], ...] = (
    (
        "REVISION",
        r"изм\.?\s*№?\s*\d|(?:^|[^а-я])изм(?:енени[ея])?(?:$|[^а-я])|\brev(?:ision)?\b|revcloud|облак",
    ),
    ("LEADER", r"выноск|leader|-anno|anno-|воздухообмен|подпис|маркировк|надпис|-text$"),
    ("AIRFLOW", r"воздухообмен"),
    ("TEXT", TEXT_LAYER_PATTERN.lower()),
    (
        "WALL",
        r"архитект|стен[аы]?\b|стены|перегород|монолит|кирпич|газобл|a-wall|s_перег|бетон|колонн|пилон|"
        r"внешний контур|^контур|a-flor|s-strs$|structure",
    ),
    ("DOOR", r"door|двер"),
    ("WINDOW", r"окн|витраж|glass|window"),
    ("DUCT", r"duct|воздуховод|вентиляц|шахт|дым"),
    ("HEATING", r"отоплен|теплоснаб|heating|радиатор|теплый|тёплый"),
    ("PLUMBING", r"^вк\b|водопров|канализ|сантех|трап|к\d\b"),
    ("AXIS", r"(?:^|[_\s-])оси$|^оси|axis|grid|s_оси"),
    ("DIMENSION", r"размер|dimension|dims?\b|отметк"),
    ("FURNITURE", r"мебел|furn|оборудование_ар|ар_отделка"),
    ("FRAME", r"штамп|рамк|оформлен|border|формат|лист_"),
    ("EQUIPMENT", r"оборудован|equipment|eqpm|component|device"),
    ("CATEGORY", r"категор"),
)
_COMPILED = tuple((name, re.compile(rx, re.IGNORECASE)) for name, rx in _CLASS_RULES)
_REV_NO = re.compile(r"изм\.?\s*№?\s*(\d+)", re.IGNORECASE)
_DISCIPLINES = frozenset(
    {"ОВ", "ВК", "АР", "АС", "ЭОМ", "ЭМ", "ЭО", "СС", "КЖ", "КР", "КМ", "ТХ", "ПБ", "ГП", "ТС", "АОВ", "ПТ", "АПС",
     "ОВК", "ИТП", "НВК", "ВВ"}
)  # fmt: skip


@lru_cache(maxsize=4096)
def layer_classes(name: str) -> frozenset[str]:
    raw = name.strip().lower()
    folded = fold(name).strip().lower()  # «DUCT-Вытяжка-TEXT» must match Latin rules unfolded
    return frozenset(cls for cls, rx in _COMPILED if rx.search(raw) or rx.search(folded))


def is_revision_layer(name: str) -> bool:
    return "REVISION" in layer_classes(name)


def revision_label(name: str) -> str | None:
    """«ОВ-Отопление-Изм. №3» → «Изм. №3»; «…Изм.2» → «Изм. №2»; other names → None."""
    m = _REV_NO.search(fold(name))
    return f"Изм. №{int(m.group(1))}" if m else None


def discipline_hint(name: str) -> str | None:
    """Printed discipline prefix of a layer name: «ОВ-Текст» → «ОВ», «0 ОВ_текст ОД» → «ОВ», «DUCT-…» → None."""
    for part in re.split(r"[-_\s.]+", fold(name).strip()):
        up = part.upper()
        if up in _DISCIPLINES:
            return up
        if part and not part.isdigit():
            return None
    return None


def is_text_layer(name: str) -> bool:
    return bool(re.search(TEXT_LAYER_PATTERN, name, re.IGNORECASE))


# ── document layers ──────────────────────────────────────────────────────────────────────────


def document_ocgs(doc) -> dict[int, dict]:
    try:
        return doc.get_ocgs() or {}
    except Exception:
        return {}


@dataclass(slots=True)
class LayerCatalog:
    """All OCG names of a document with the pages that reference them."""

    names: dict[str, dict[str, Any]]  # name → {xref, visible_default}
    pages: dict[str, set[int]]

    def cad_layers(self) -> list[dict[str, Any]]:
        """Contract ``CadLayer`` dicts (layout_artifacts.schema.json), sorted by name."""
        out = []
        for name in sorted(self.names):
            info = self.names[name]
            out.append(
                {
                    "name": name,
                    "xref": info["xref"],
                    "visible_default": info["visible_default"],
                    "pages": sorted(self.pages.get(name, ())),
                    "is_text_layer": is_text_layer(name),
                    "is_revision_layer": is_revision_layer(name),
                    "revision_label": revision_label(name) if is_revision_layer(name) else None,
                    "discipline_hint": discipline_hint(name),
                }
            )
        return out


def layer_catalog(doc, page_layers: dict[int, Iterable[str]] | None = None) -> LayerCatalog:
    """Layer names of ``doc``; ``page_layers`` maps 1-based pages to the layer names seen on them."""
    names: dict[str, dict[str, Any]] = {}
    for xref, info in sorted(document_ocgs(doc).items()):
        name = str(info.get("name") or "").strip()
        if not name:
            continue
        cur = names.setdefault(name, {"xref": int(xref), "visible_default": bool(info.get("on", True))})
        cur["visible_default"] = cur["visible_default"] or bool(info.get("on", True))
    pages: dict[str, set[int]] = defaultdict(set)
    for pno, layer_names in (page_layers or {}).items():
        for n in layer_names:
            if n in names:
                pages[n].add(int(pno))
    return LayerCatalog(names, dict(pages))


# ── isolated renders ─────────────────────────────────────────────────────────────────────────


@contextmanager
def only_layers(doc, keep: Callable[[str], bool]) -> Iterator[int]:
    """Switch off every visible, unlocked OCG whose name ``keep`` rejects; restore on exit.

    Yields the number of layers switched off (0 = the document has no usable layer configuration).
    """
    try:
        ui = doc.layer_ui_configs()
    except Exception:
        ui = []
    done: list[int] = []
    try:
        for item in ui:
            if item.get("type") != "checkbox" or not item.get("on") or item.get("locked"):
                continue
            if not keep(str(item.get("text", ""))):
                doc.set_layer_ui_config(int(item["number"]), 2)
                done.append(int(item["number"]))
        yield len(done)
    finally:
        for number in done:
            doc.set_layer_ui_config(number, 0)


def render_gray(page, scale: float, clip=None) -> np.ndarray:
    """Grey render (uint8, displayed orientation) at ``scale`` pixels per point."""
    import pymupdf

    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), clip=clip, colorspace=pymupdf.csGRAY, alpha=False
    )
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()


def render_layers(page, keep: Callable[[str], bool], scale: float) -> tuple[np.ndarray, int]:
    """Render only the layers ``keep`` accepts (plus content without a layer). Returns (image, layers_off)."""
    with only_layers(page.parent, keep) as off:
        img = render_gray(page, scale)
    return img, off


def keep_classes(*classes: str, exclude: Iterable[str] = ()) -> Callable[[str], bool]:
    want, drop = set(classes), set(exclude)

    def keep(name: str) -> bool:
        cls = layer_classes(name)
        return bool(cls & want) and not (cls & drop)

    return keep


# ── token → layer attribution ────────────────────────────────────────────────────────────────


def text_span_layers(page, frame: PageFrame) -> list[tuple[tuple[float, float, float, float], str]]:
    """(displayed bbox, layer) of every text-layer span that carries an OCG."""
    out = []
    try:
        trace = page.get_texttrace()
    except Exception:
        return out
    for span in trace:
        layer = span.get("layer") or ""
        if layer:
            out.append((frame.rect(span["bbox"]), layer))
    return out


def attribute_tokens(
    tokens: list, drawings: DrawingIndex, spans: list[tuple[tuple[float, float, float, float], str]]
) -> dict[int, tuple[str, float]]:
    """Layer of each token: text-layer tokens by the span that holds them, OCR tokens (outlined text) by the
    majority layer of the small vector paths inside their box. Returns token id → (layer, share)."""
    out: dict[int, tuple[str, float]] = {}
    # grid of small path centres
    cell = 20.0
    grid: dict[tuple[int, int], list[tuple[float, float, str]]] = defaultdict(list)
    for layer, centres in drawings.small_centres.items():
        if not layer:
            continue
        for x, y in centres:
            grid[(int(x // cell), int(y // cell))].append((x, y, layer))
    span_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (b, _) in enumerate(spans):
        for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
            for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                span_grid[(gx, gy)].append(i)
    for t in tokens:
        cx, cy = (t.x0 + t.x1) / 2, (t.y0 + t.y1) / 2
        if t.source.startswith("TEXT_LAYER"):
            for i in span_grid.get((int(cx // cell), int(cy // cell)), ()):
                b, layer = spans[i]
                if b[0] - 0.5 <= cx <= b[2] + 0.5 and b[1] - 0.5 <= cy <= b[3] + 0.5:
                    out[t.id] = (layer, 1.0)
                    break
            continue
        votes: dict[str, int] = defaultdict(int)
        for gx in range(int(t.x0 // cell), int(t.x1 // cell) + 1):
            for gy in range(int(t.y0 // cell), int(t.y1 // cell) + 1):
                for x, y, layer in grid.get((gx, gy), ()):
                    if t.x0 <= x <= t.x1 and t.y0 <= y <= t.y1:
                        votes[layer] += 1
        total = sum(votes.values())
        if total:
            layer, n = max(votes.items(), key=lambda kv: (kv[1], kv[0]))
            out[t.id] = (layer, round(n / total, 3))
    return out
