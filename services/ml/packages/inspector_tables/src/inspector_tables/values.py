"""Contract output: typed facts → ExtractedValue (schemas/extracted_value.schema.json), one JSONL per object.

Fact keys (``fact_key``; parameter-bound values also carry ``param_code``/``param_id``):

* ``room.area``, ``room.name``, ``room.category`` — explication rows (location = the printed room number);
* ``pz.value`` — labelled object-level ПЗ values (PZ-013…018, 021…023; pzparams);
* ``tx.value`` — labelled prose values of the mix parameters (ODI-116/117/119/121, SPZU-030/031/038, AR-045/049/050,
  KR-066, ZU-131; textparams);
* ``tep.value`` — ТЭП rows (value per ПД; the ГПЗУ limit as a second value with qualifier basis=ГПЗУ);
* ``spec.item`` — specification items (value = quantity);
* ``id.registry_doc`` — «Реестр приложений» rows; ``aosr.<field>`` and ``aosr.doc_ref`` — act fields;
* ``pd.element_room`` — element–room assertions (value = true; qualifiers: family, channel, anchor, tags);
* ``pd.room_systems`` — air-exchange rows (value = the system tags of one role for one room);
* ``id.page_kind`` / ``id.segment`` — binder typing.

Qualifiers carry the join keys other agents need (``room_key`` — the room number with surplus leading
zeros removed, «0012» → «012» — table_id, row, family…); ``location`` stays the exact printed token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from inspector_tables.pzparams import SCALES, normalize_enum
from inspector_tables.text import norm_unit, number_value

PIPELINE = "tables-0.1.0"


def room_key(room: str | None) -> str | None:
    """Join key of a printed room number: surplus leading zeros dropped («0012» → «012», «001.1» kept)."""
    if not room:
        return None
    return re.sub(r"^0+(?=\d{3})", "", room)


@dataclass(slots=True)
class ValueSink:
    file_id: str
    object_id: str
    sha256: str
    stage: str
    values: list[dict[str, Any]] = field(default_factory=list)
    _n: int = 0

    def add(self, *, page: int, fact_key: str, value_raw: str, vtype: str, value: Any, method: str,
            confidence: float = 1.0, quality: str = "OK", unit: str | None = None, unit_raw: str | None = None,
            location: str | None = None, location_type: str | None = None, param_code: str | None = None,
            bbox: list[float] | None = None, table_ref: dict | None = None, qualifiers: dict | None = None,
            text_source: str | None = "TEXT_LAYER", context: str | None = None, anchor: str | None = None) -> None:  # fmt: skip
        self._n += 1
        v: dict[str, Any] = {
            "value_id": f"{self.file_id}-p{page:05d}-{fact_key}-{self._n:05d}",
            "object_id": self.object_id,
            "file_id": self.file_id,
            "file_sha256": self.sha256,
            "stage": self.stage,
            "page_no": page,
            "page_basis": "PDF_NATIVE",
            "fact_key": fact_key,
            "value_raw": value_raw if value_raw is not None else "",
            "value_norm": {"type": vtype, "value": value},
            "method": method,
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "quality_flag": quality,
            "pipeline_version": PIPELINE,
        }
        if unit:
            v["value_norm"]["unit"] = unit
        if qualifiers:
            v["value_norm"]["qualifiers"] = qualifiers
        if unit_raw:
            v["unit_raw"] = unit_raw
        if location:
            v["location"] = location
            v["location_type"] = location_type or "ROOM"
        elif location_type:
            v["location"] = "OBJECT" if location_type == "OBJECT" else None
            v["location_type"] = location_type
            if v["location"] is None:
                del v["location"]
        if param_code:
            from inspector_common.params import get_param

            v["param_code"] = param_code
            v["param_id"] = get_param(param_code).param_id
        if bbox:
            v["geometry"] = {"boxes": [bbox]}
            v["geometry_space"] = "PDF_VISIBLE_ROTATED_TL_V1"
        if table_ref:
            v["table_ref"] = table_ref
        if text_source:
            v["text_source"] = text_source
        if context:
            v["context_text"] = context[:500]
        if anchor:
            v["anchor"] = {"text": anchor[:200]}
        self.values.append(v)


_INCL_ROW = re.compile(r"в\s*т\.?\s*ч\.?|в\s+том\s+числе", re.I)
_DEC = re.compile(r"^\d+,\d+$")


def _incl_total(indicator: str, raw: str) -> tuple[str, float] | None:
    """A «в т.ч.» row whose cell glued the total and its components («11618,27 11114,27 504,0»): the first
    number is the total. Only when every part is a decimal-comma number (no thousands-group ambiguity)."""
    parts = raw.split()
    if len(parts) < 2 or not _INCL_ROW.search(indicator or "") or not all(_DEC.match(p) for p in parts):
        return None
    return parts[0], float(parts[0].replace(",", "."))


def _cell_box(cell: dict) -> list[float] | None:
    return cell.get("bbox")


def from_table(sink: ValueSink, t: dict[str, Any], param_codes: dict[int, str] | None = None,
               extra: dict[int, dict] | None = None) -> None:  # fmt: skip
    """Facts of one contract table (TypedTable dict); ``param_codes`` maps TEP row numbers to catalog codes,
    ``extra`` carries per-row evaluations (DEVIATION tolerance verdicts)."""
    param_codes = param_codes or {}
    tt = t["table_type"]
    ts = t.get("text_source") or "TEXT_LAYER"
    method = "TABLE"
    for row in t["rows"]:
        cells = row["cells"]
        page = row.get("pdf_page_number") or t["pages"][0]
        ref = {"table_id": t["table_id"], "table_type": tt, "row": row["row_no"]}
        kind = row.get("kind") or "DATA"
        if tt == "EXPLICATION" and kind in ("DATA", "SUBZONE"):
            room = (cells.get("room_no") or {}).get("value")
            base_q = {
                "table_id": t["table_id"],
                "row_kind": kind,
                "room_key": room_key(room),
                "section": row.get("section"),
            }
            if kind == "SUBZONE" and row.get("parent_row_no"):
                base_q["parent_row_no"] = row["parent_row_no"]
            area = cells.get("area_m2")
            if area and area.get("value") is not None:
                sink.add(page=page, fact_key="room.area", value_raw=area["raw"] or "", vtype="number", value=area["value"],
                         unit="м²", method=method, location=room, location_type="ROOM" if room else None,
                         bbox=_cell_box(area) or row.get("bbox"), table_ref=ref, qualifiers=base_q, text_source=ts,
                         context=(cells.get("name") or {}).get("raw"))  # fmt: skip
            name = cells.get("name")
            if name and name.get("value") and room:
                sink.add(page=page, fact_key="room.name", value_raw=name["raw"] or "", vtype="string", value=name["value"],
                         method=method, location=room, location_type="ROOM", bbox=_cell_box(name) or row.get("bbox"),
                         table_ref=ref, qualifiers=base_q, text_source=ts)  # fmt: skip
            cat = cells.get("category")
            if cat and cat.get("value") and room:
                sink.add(page=page, fact_key="room.category", value_raw=cat["raw"] or "", vtype="enum", value=cat["value"],
                         method=method, location=room, location_type="ROOM", bbox=_cell_box(cat), table_ref=ref,
                         qualifiers=base_q, text_source=ts)  # fmt: skip
        elif tt == "TEP" and kind in ("DATA", "SUBZONE"):
            ind = (cells.get("indicator") or {}).get("value") or ""
            location_type, location = ("OBJECT", None)
            m = re.match(r"^корпус\s*(\S+)", ind, re.I)
            if m:
                location_type, location = "BUILDING", f"Корпус {m.group(1)}"
            unit_raw = (cells.get("unit") or {}).get("raw")
            q = {"indicator": ind, "table_id": t["table_id"], "row_kind": kind, "basis": "ПД"}
            if row.get("parent_row_no"):
                q["parent_row_no"] = row["parent_row_no"]
            code = param_codes.get(row["row_no"])
            val = cells.get("value")
            rank = None
            # an ordinal ПЗ parameter (class/category/degree) is read through its scale or not at all
            if code in SCALES:
                got = normalize_enum(code, (val or {}).get("raw") or "")
                if got is None:
                    code = None
                else:
                    val = {**val, "value": got[0]}
                    rank = got[1]
            if val and val.get("raw") and not isinstance(val.get("value"), (int, float)):
                first = _incl_total(ind, val["raw"])
                if first is not None:  # «11618,27 11114,27 504,0» of a «…, в т.ч.:» row → the total
                    val = {**val, "raw": first[0], "value": first[1]}
                    q["glued_components"] = True
            if val and val.get("raw"):
                is_num = isinstance(val.get("value"), (int, float))
                sink.add(page=page, fact_key="tep.value", value_raw=val["raw"],
                         vtype="enum" if rank is not None else ("number" if is_num else "string"),
                         value=val["value"], unit=norm_unit(unit_raw) if is_num else None, unit_raw=unit_raw, method=method,
                         location=location, location_type=location_type, param_code=code, bbox=_cell_box(val),
                         table_ref=ref, qualifiers=q, text_source=ts, anchor=ind)  # fmt: skip
                if rank is not None:
                    sink.values[-1]["value_norm"]["rank"] = rank
            lim = cells.get("note")
            if lim and lim.get("raw") and lim["raw"] not in ("-", "—"):
                is_num = isinstance(lim.get("value"), (int, float))
                sink.add(page=page, fact_key="tep.value", value_raw=lim["raw"], vtype="number" if is_num else "string",
                         value=lim["value"], unit=norm_unit(unit_raw) if is_num else None, unit_raw=unit_raw, method=method,
                         location=location, location_type=location_type, param_code=code, bbox=_cell_box(lim), table_ref=ref,
                         qualifiers={**q, "basis": "ГПЗУ"}, text_source=ts, anchor=ind)  # fmt: skip
        elif tt == "SPEC_21110" and kind == "DATA":
            qty = cells.get("quantity")
            name = (cells.get("name") or {}).get("value") or ""
            q = {"position": (cells.get("position") or {}).get("value"), "name": name,
                 "type_mark": (cells.get("type_mark") or {}).get("value"), "table_id": t["table_id"], "section": row.get("section")}  # fmt: skip
            if qty and qty.get("value") is not None:
                sink.add(page=page, fact_key="spec.item", value_raw=qty["raw"] or "", vtype="number", value=qty["value"],
                         unit=qty.get("unit"), unit_raw=(cells.get("unit") or {}).get("raw"), method=method,
                         bbox=row.get("bbox"), table_ref=ref, qualifiers=q, text_source=ts, context=name)  # fmt: skip
        elif tt == "ID_REGISTRY" and kind == "DATA":
            no = cells.get("doc_no") or {}
            q = {"doc_name": (cells.get("doc_name") or {}).get("value"), "doc_date": (cells.get("doc_date") or {}).get("value"),
                 "organization": (cells.get("note") or {}).get("value"), "section": row.get("section"), "table_id": t["table_id"]}  # fmt: skip
            sink.add(page=page, fact_key="id.registry_doc", value_raw=no.get("raw") or "", vtype="string", value=no.get("value"),
                     method=method, bbox=row.get("bbox"), table_ref=ref, qualifiers=q, text_source=ts,
                     context=q["doc_name"])  # fmt: skip
        elif tt == "DEVIATION" and kind == "DATA":
            val = cells.get("deviation") or cells.get("actual_value") or {}
            ev = (extra or {}).get(row["row_no"], {})
            q = {"element": (cells.get("element") or {}).get("value"), "axes": (cells.get("axes") or {}).get("value"),
                 "parameter": (cells.get("parameter") or {}).get("value"), "design": (cells.get("design_value") or {}).get("value"),
                 "actual": (cells.get("actual_value") or {}).get("value"), "tolerance": (cells.get("tolerance") or {}).get("raw"),
                 "table_id": t["table_id"], **ev}  # fmt: skip
            is_num = isinstance(val.get("value"), (int, float))
            sink.add(page=page, fact_key="id.deviation", value_raw=val.get("raw") or "", vtype="number" if is_num else "string",
                     value=val.get("value"), unit=norm_unit((cells.get("unit") or {}).get("raw")), method=method,
                     location=(cells.get("axes") or {}).get("value"), location_type="AXES" if cells.get("axes") else None,
                     bbox=row.get("bbox"), table_ref=ref, qualifiers=q, text_source=ts)  # fmt: skip
        elif tt == "AOSR":
            for k, c in cells.items():
                vtype = "string"
                sink.add(page=page, fact_key=f"aosr.{k}", value_raw=c.get("raw") or "", vtype=vtype, value=c.get("value"),
                         method="REGEX", table_ref=ref, text_source=ts)  # fmt: skip


def from_materials(sink: ValueSink, page: int, facts: list, source: str) -> None:
    """Structural material facts (inspector_tables.materials) → ``kr.*`` values, location = the element family."""
    from inspector_tables.materials import KINDS

    for f in facts:
        fact_key, _, scale = KINDS[f.kind]
        is_num = f.kind == "thickness"
        q = {"family": f.family, "kind": f.kind, "source": source, "inherited": f.inherited}
        if scale:
            q["scale"] = scale
        if f.act_no:
            q["act_no"] = f.act_no
        sink.add(page=page, fact_key=fact_key, value_raw=f.value, vtype="number" if is_num else "enum",
                 value=f.rank if is_num else f.value, method="REGEX", confidence=f.confidence,
                 unit="мм" if is_num else None, location=f.family, location_type="ELEMENT",
                 param_code=f.param_code, qualifiers=q, context=f.clause)  # fmt: skip
        sink.values[-1]["value_norm"]["rank"] = f.rank


def from_pz(sink: ValueSink, page: int, facts: list, text_source: str = "TEXT_LAYER") -> None:
    """Labelled object-level ПЗ values (inspector_tables.pzparams) → ``pz.value``, location OBJECT."""
    from inspector_tables.pzparams import PARSER_VERSION, SCALE_NAMES

    for f in facts:
        q = {"parser": PARSER_VERSION}
        if f.kind:
            q["kind"] = f.kind
        if f.rank is not None:
            q["scale"] = SCALE_NAMES[f.code]
        if getattr(f, "ctx_at", None) is not None:
            q["ctx_at"] = f.ctx_at
        sink.add(page=page, fact_key="pz.value", value_raw=f.raw, vtype=f.vtype, value=f.value, unit=f.unit, method="REGEX",
                 confidence=f.confidence * (0.9 if text_source.startswith("OCR") else 1.0), location_type="OBJECT",
                 param_code=f.code, qualifiers=q, text_source=text_source, context=f.context)  # fmt: skip
        if f.rank is not None:
            sink.values[-1]["value_norm"]["rank"] = f.rank


def from_textparams(sink: ValueSink, page: int, facts: list, text_source: str = "TEXT_LAYER") -> None:
    """Labelled mix-parameter values (inspector_tables.textparams) → ``tx.value``. The location is the bound element
    (ELEMENT: railing kind, protected element, finishing zone) or the object; ``sub_id`` pins a fact to one
    sub-check of the catalog rule (AR-045.a, KR-066.a/.b/.c)."""
    from inspector_tables.textparams import FACT_KEY, PARSER_VERSION

    for f in facts:
        q: dict[str, Any] = {"parser": PARSER_VERSION}
        if f.kind:
            q["kind"] = f.kind
        if f.sub_id:
            q["sub_id"] = f.sub_id
        if getattr(f, "printed", None) and f.printed != f.raw:
            q["printed"] = f.printed
        sink.add(page=page, fact_key=FACT_KEY, value_raw=f.raw, vtype=f.vtype, value=f.value, unit=f.unit, method="REGEX",
                 confidence=f.confidence * (0.9 if text_source.startswith("OCR") else 1.0),
                 location=f.location, location_type="ELEMENT" if f.location else "OBJECT", param_code=f.code,
                 qualifiers=q, text_source=text_source, context=f.context)  # fmt: skip
        if f.rank is not None:
            sink.values[-1]["value_norm"]["rank"] = f.rank


def from_energy(sink: ValueSink, page: int, facts: list, source: str) -> None:
    """Energy-efficiency facts (inspector_tables.energy) → ``ee.*`` values bound to a catalog parameter. The class is
    an object-level enum with its ordinal rank; thickness/λ carry the insulation material group as the location
    (ELEMENT), so the comparator meets PD and RD only within one material; Ro of windows is object-level."""
    from inspector_tables.energy import KINDS, PARSER_VERSION

    for f in facts:
        fact_key, code, unit = KINDS[f.kind]
        is_num = f.kind != "class"
        q = {"kind": f.kind, "source": source, "parser": PARSER_VERSION}
        if f.material:
            q["material"] = f.material
        if f.detail:
            q["detail"] = f.detail
        if getattr(f, "ctx_at", None) is not None:
            q["ctx_at"] = f.ctx_at
        sink.add(page=page, fact_key=fact_key, value_raw=f.raw, vtype="number" if is_num else "enum",
                 value=f.value, method="REGEX", confidence=f.confidence, unit=unit,
                 location=f.material, location_type="ELEMENT" if f.material else "OBJECT", param_code=code,
                 qualifiers=q, context=f.clause)  # fmt: skip
        if not is_num:
            sink.values[-1]["value_norm"]["rank"] = f.rank


def from_igs(sink: ValueSink, igs_page, norm, text_source: str = "OCR") -> None:
    """ИГС scheme facts (inspector_tables.igs) → ``id.tolerance`` (the printed допуск) and ``id.deviation``
    (a signed measured deviation, qualifier source=IGS_ANNOTATION), both on the scheme page, in millimetres."""
    from inspector_tables.igs import PARSER_VERSION

    base = {"source": "IGS_ANNOTATION", "parser": PARSER_VERSION, "scheme": igs_page.title or None,
            "element_kind": igs_page.element_kind, "axes": igs_page.axes}  # fmt: skip
    pg = igs_page.page_no
    for t in igs_page.tolerances:
        sink.add(page=pg, fact_key="id.tolerance", value_raw=t.raw, vtype="number", value=number(t.value), unit="мм",
                 method="REGEX", confidence=t.conf, location_type="OBJECT",
                 bbox=norm(pg, t.box) if t.box is not None else None,
                 qualifiers={**base, "kind": t.kind}, text_source=text_source, context=t.line)  # fmt: skip
    for d in igs_page.deviations:
        sink.add(page=pg, fact_key="id.deviation", value_raw=d.raw, vtype="number", value=number(d.value), unit="мм",
                 method="TOKEN_GRAMMAR", confidence=d.conf, location_type="OBJECT",
                 bbox=norm(pg, d.box) if d.box is not None else None,
                 qualifiers={**base, "component": d.pair}, text_source=text_source)  # fmt: skip


def from_aosr_refs(sink: ValueSink, page: int, act) -> None:
    for ref in act.doc_refs:
        sink.add(page=page, fact_key="aosr.doc_ref", value_raw=ref["code"], vtype="string", value=ref["code"], method="REGEX",
                 qualifiers={"revision": ref["revision"], "field": ref["source"], "act_no": act.cells.get("act_no")})  # fmt: skip


def from_assertions(sink: ValueSink, assertions: list, norm) -> None:
    """ElementAssertion → pd.element_room (one value per room; SPEC items are object-level)."""
    method_of = {"TEXT": "REGEX", "LABEL": "TOKEN_GRAMMAR", "SPEC": "TABLE", "TABLE": "TABLE"}
    for a in assertions:
        bbox = norm(a.page_no, a.box) if a.box is not None else None
        q = {
            "family": a.family,
            "channel": a.channel,
            "anchor": a.anchor,
            "rooms": a.rooms,
            **({"tags": a.tags} if a.tags else {}),
        }
        if a.quantity is not None:
            q["quantity"] = a.quantity
        if a.extra:
            q.update({k: v for k, v in a.extra.items() if k in ("role", "leaders", "unit")})
        if a.rooms:
            for r in a.rooms:
                sink.add(page=a.page_no, fact_key="pd.element_room", value_raw=a.text[:300], vtype="boolean", value=True,
                         method=method_of[a.channel], confidence=a.confidence, location=r, location_type="ROOM", bbox=bbox,
                         qualifiers={**q, "room_key": room_key(r)}, context=a.text, anchor=a.anchor)  # fmt: skip
        else:
            sink.add(page=a.page_no, fact_key="pd.element_room", value_raw=a.text[:300], vtype="boolean", value=True,
                     method=method_of[a.channel], confidence=a.confidence, location_type="OBJECT", bbox=bbox, qualifiers=q,
                     context=a.text, anchor=a.anchor)  # fmt: skip


def from_room_systems(sink: ValueSink, rooms: list, norm, text_source: str = "OCR") -> None:
    for r in rooms:
        for role, tags in r.systems.items():
            raw = r.raw.get(role) or ""
            if not raw:
                continue
            sink.add(page=r.page_no, fact_key="pd.room_systems", value_raw=raw, vtype="string", value=", ".join(tags) if tags else raw,
                     method="TABLE", confidence=0.85 if tags else 0.5, location=r.room_no, location_type="ROOM",
                     bbox=norm(r.page_no, r.box) if r.box is not None else None,
                     qualifiers={"role": role, "tags": tags, "room_key": room_key(r.room_no), "room_name": r.name},
                     text_source=text_source)  # fmt: skip


def from_binder(sink: ValueSink, kinds: list, segs: list) -> None:
    for k in kinds:
        sink.add(page=k.page_no, fact_key="id.page_kind", value_raw=k.title[:200], vtype="enum", value=k.kind, method="REGEX",
                 confidence=k.confidence, quality="OK" if k.kind not in ("UNREAD",) else "ABSTAIN",
                 text_source=None if k.source == "NONE" else ("OCR" if k.source == "TOKENS" else "TEXT_LAYER"))  # fmt: skip
    for s in segs:
        sink.add(page=s.start, fact_key="id.segment", value_raw=s.title[:200], vtype="enum", value=s.kind, method="REGEX",
                 confidence=0.8 if s.kind not in ("UNKNOWN", "UNREAD") else 0.3,
                 qualifiers={"start_page": s.start, "end_page": s.end, "pages": len(s.pages)}, text_source=None)  # fmt: skip


def number(v: float | None) -> Any:
    return number_value(v) if v is not None else None
