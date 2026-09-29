"""CAD layers (PDF optional content, OCG) for recognition (97 §2.13 F2, 95 R2): layer-isolated renders.

CAD exports keep their layers as OCGs (42 of 57 Тюменская PDFs, 83 of 126 Новослободская PDFs). Text drawn
as curves usually sits on text-like layers (``*-TEXT``, ``*Выноски``, ``*Текст``, ``*Подписи`` …), under a
dense tangle of ducts, walls and hatches on the other layers. Rendering with only the text-like layers
switched on (content without a layer stays visible, e.g. frames and stamps) gives the detector clean
labels: on the gold RD sheet F0201 p17 it recovers «П9» that the full render loses under a leader line.

Visibility is switched through the document's layer UI configuration and **always restored**: text
extraction honours visibility too, so the text layer must be read in the document's own configuration.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

_XREF = re.compile(r"(\d+)\s+0\s+R")


@dataclass(frozen=True, slots=True)
class LayerPlan:
    """UI layer entries of a document: which to switch off for a text-only render."""

    off: tuple[int, ...]  # UI config numbers of visible non-text layers
    text_layers: tuple[str, ...]  # names of the text-like layers (visible ones)

    @property
    def usable(self) -> bool:
        return bool(self.off) and bool(self.text_layers)


def layer_plan(doc, pattern: str) -> LayerPlan:
    """Text-like vs other layers of ``doc`` (``pattern``: case-insensitive regex on the layer name)."""
    try:
        ui = doc.layer_ui_configs()
    except Exception:  # damaged OCProperties: no isolation
        return LayerPlan((), ())
    rx = re.compile(pattern, re.IGNORECASE)
    off: list[int] = []
    text: set[str] = set()
    for item in ui:
        if item.get("type") != "checkbox" or not item.get("on"):
            continue
        name = str(item.get("text", ""))
        if rx.search(name):
            text.add(name)
        elif not item.get("locked"):
            off.append(int(item["number"]))
    return LayerPlan(tuple(off), tuple(sorted(text)))


@contextmanager
def text_layers_only(doc, plan: LayerPlan) -> Iterator[None]:
    """Switch the non-text layers off for the duration of the block, then restore them."""
    done: list[int] = []
    try:
        for number in plan.off:
            doc.set_layer_ui_config(number, 2)  # 2 = set OFF
            done.append(number)
        yield
    finally:
        for number in done:
            doc.set_layer_ui_config(number, 0)  # 0 = set ON (only visible layers were switched off)


def document_ocgs(doc) -> dict[int, dict]:
    """``doc.get_ocgs()`` or an empty dict for documents without (or with damaged) optional content."""
    try:
        return doc.get_ocgs() or {}
    except Exception:
        return {}


def page_layer_names(page, ocgs: dict[int, dict] | None = None, limit: int = 400) -> list[str]:
    """Names of the OCGs referenced by the page (its /Properties and those of its form XObjects).

    Best effort and cheap (no content parsing); OCMDs and nested forms beyond one level are ignored.
    ``ocgs`` is :func:`document_ocgs` of the page's document (pass it to avoid recomputing per page).
    """
    doc = page.parent
    if ocgs is None:
        ocgs = document_ocgs(doc)
    if not ocgs:
        return []
    names: set[str] = set()

    def props_of(res_holder: int) -> list[int]:
        kind, val = doc.xref_get_key(res_holder, "Resources")
        res_xref = None
        if kind == "xref":
            m = _XREF.search(val)
            res_xref = int(m.group(1)) if m else None
        out: list[int] = []
        for key in ("Properties", "XObject"):
            if res_xref is not None:
                k2, v2 = doc.xref_get_key(res_xref, key)
            else:
                k2, v2 = doc.xref_get_key(res_holder, f"Resources/{key}")
            if k2 == "xref":
                m = _XREF.search(v2)
                if m:
                    v2 = doc.xref_object(int(m.group(1)), compressed=True)
            refs = [int(x) for x in _XREF.findall(v2 or "")]
            if key == "Properties":
                names.update(ocgs[r]["name"] for r in refs if r in ocgs)
            else:
                out.extend(refs)
        return out

    try:
        forms = props_of(page.xref)
        for xref in forms[:limit]:
            if doc.xref_get_key(xref, "Subtype")[1] == "/Form":
                props_of(xref)
    except Exception:
        return sorted(names)
    return sorted(names)
