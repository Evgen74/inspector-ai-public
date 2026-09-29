"""The fact sheet Logical_Rules are evaluated on (07 §3.3.1): one JSON-like document per object.

Facts carry their provenance (``evidence``: stage, file_id, pdf_page_number, geometry) so a rule outcome can be
bound to pages. Every fact that cannot be established is simply absent, which IAI-Logic reads as UNKNOWN.

Sources (contract artifacts only):

- ``tables``: TableArtifacts (AG-02C). EXPLICATION tables become *sum blocks* — the DATA rows closed by one
  SUBTOTAL/TOTAL row, with the «в том числе» SUBZONE rows kept apart (HR-LOG-005, HR-LOG-011). DEVIATION rows
  (executive schemes, ИГС) carry deviation, tolerance and the element family's route (HR-LOG-008). AOSR rows
  become one fact per cited document code (HR-LOG-002, -009, -010). TEP rows fill object indicators.
- ``params``: ExtractedValue rows (AG-02C) by catalog code and stage (best candidate).
- ``documents``: the registry codes and current revisions of each stage (title blocks from AG-02B, «Состав
  проекта» tables), for the ИД rules.
- ``elements``: three-valued presence of the element families the active rules ask about (:mod:`elements`).
- ``id_works``: families with an UNDOCUMENTED_WORK route present in the ИД (HR-LOG-007).
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from inspector_common.contracts.models import ExtractedValue, TableArtifacts, TypedTable
from inspector_hypothesis.elements import ElementIndex, load_families
from inspector_hypothesis.inputs import HypothesisInputs
from inspector_hypothesis.logic import UNKNOWN
from inspector_hypothesis.textmatch import (
    CodeRef,
    PhraseMatcher,
    code_key,
    decimals_of,
    document_codes,
    norm_text,
    parse_number,
    revision_number,
)

_TOTAL_RE = re.compile(r"\b(итог[а-я]*|всего)\b", re.IGNORECASE)
_SUBZONE_RE = re.compile(r"в\s+т(?:ом)?\.?\s*ч(?:исле)?\.?", re.IGNORECASE)
_FLOOR_RE = re.compile(
    r"(-?\d{1,2})\s*(?:-?го|-?ого)?\s*этаж|этаж[а-я]*\s*(-?\d{1,2})|подвал|цокол|антресол|кровл|мансард",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")

# ТЭП indicator names → object fact keys (for facts that are not catalog parameters, e.g. the plot area).
TEP_INDICATORS: dict[str, tuple[str, ...]] = {
    "plot_area_m2": ("площадь участка", "площадь земельного участка", "площадь территории"),
    "building_area_m2": ("площадь застройки",),
    "total_area_m2": ("общая площадь здания", "общая площадь"),
    "floors": ("этажность", "количество этажей"),
    "height_m": ("высота здания",),
    "apartments": ("количество квартир",),
    "building_density_pct": ("коэффициент застройки",),
}
_TEP_PARAM = {
    "building_area_m2": "PZ-001",
    "total_area_m2": "PZ-002",
    "floors": "PZ-007",
    "height_m": "PZ-008",
    "apartments": "PZ-010",
    "building_density_pct": "PZ-019",
}


def parse_date(raw: object) -> str | None:
    """«07.04.2025» / «11.08.24» / ISO «2025-04-07» (AG-02C writes acts' dates so) → ISO «2025-04-07»
    (string-comparable in IAI-Logic)."""
    if raw is None:
        return None
    iso = _ISO_DATE_RE.search(str(raw))
    if iso:
        y, mth, d = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
    else:
        m = _DATE_RE.search(str(raw))
        if not m:
            return None
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, mth, d).isoformat()
    except ValueError:
        return None


def _cell(row: Any, key: str) -> tuple[Any, str | None]:
    """(value or raw, raw text) of a table cell."""
    c = row.cells.get(key)
    if c is None:
        return None, None
    return (c.value if c.value is not None else c.raw), c.raw


def _row_kind(row: Any) -> str:
    if row.kind is not None:
        return str(row.kind)
    name = " ".join(str(c.raw or "") for c in row.cells.values())
    if _TOTAL_RE.search(name):
        return "TOTAL"
    if row.parent_row_no is not None or _SUBZONE_RE.search(name):
        return "SUBZONE"
    return "DATA"


def _evidence(
    stage: str | None, file_id: str, page: int | None, bbox: Any = None, sheet: Any = None
) -> dict[str, Any]:
    ev: dict[str, Any] = {"stage": stage, "file_id": file_id, "pdf_page_number": page}
    if bbox is not None:
        ev["geometry"] = {"boxes": [list(bbox)]}
    if sheet is not None:
        ev["document_sheet_number"] = sheet
    return ev


@dataclass(slots=True)
class _BlockAcc:
    rows: list[dict[str, Any]]
    subzones: list[dict[str, Any]]
    decimals: int
    pages: set[int]

    @classmethod
    def new(cls) -> _BlockAcc:
        return cls([], [], 0, set())


_PLOT_TEP_RE = re.compile(r"участ|территори")
_ENUM_PREFIX_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})*\.?\s+")
_GRAND_LABEL_RE = re.compile(r"этаж|всего|общ|здани|секци|корпус", re.IGNORECASE)


def _is_open(table: TypedTable) -> bool:
    """The table's last row is a data row: its sum block continues in the next table (a column split)."""
    kinds = [_row_kind(r) for r in sorted(table.rows, key=lambda r: r.row_no)]
    kinds = [k for k in kinds if k not in ("NOTE", "SECTION_HEADER")]
    return bool(kinds) and kinds[-1] in ("DATA", "SUBZONE")


def explication_chains(tables: Sequence[TypedTable]) -> list[list[TypedTable]]:
    """EXPLICATION tables of one file grouped into continuation chains: a table whose rows run on without a total
    continues in the next table of the same title on the same or the next page (the basement explication of F0201
    p17 is recognised as two tables side by side; its «ИТОГО: 524,0» closes the rows of both)."""
    chains: list[list[TypedTable]] = []
    for t in sorted(tables, key=lambda t: (t.pages[0], t.table_id)):
        prev = chains[-1][-1] if chains else None
        if (
            prev is not None
            and _is_open(prev)
            and norm_text(prev.title or "") == norm_text(t.title or "")
            and t.pages[0] in (prev.pages[-1], prev.pages[-1] + 1)
        ):
            chains[-1].append(t)
        else:
            chains.append([t])
    return chains


def explication_blocks(
    tables: TypedTable | Sequence[TypedTable], *, file_id: str, stage: str | None, sheet: Any = None
) -> list[dict[str, Any]]:
    """Sum blocks of one EXPLICATION table (or a continuation chain of them): every SUBTOTAL closes the DATA rows
    since the previous (sub)total, every TOTAL closes all DATA rows since the previous TOTAL; SUBZONE («в том числе»)
    rows are kept apart.

    A TOTAL that does not match its own rows but follows closed group totals is a higher-level total («ИТОГО 1-ый
    этаж» over the group totals, when its label names a floor or it is far larger than its rows): it becomes a
    GRAND block whose rows are the group totals; when the group totals do not add up to it either, the block is
    marked ``hierarchy_unresolved`` (the table structure is not understood, so no sum rule applies)."""
    chain = [tables] if isinstance(tables, TypedTable) else list(tables)
    first = chain[0]
    blocks: list[dict[str, Any]] = []
    since_total, since_sub = _BlockAcc.new(), _BlockAcc.new()
    closed: list[
        dict[str, Any]
    ] = []  # TOTAL blocks since the last grand total (candidates for a higher level)
    section_label: str | None = None
    for table in chain:
        default_page = table.pages[0]
        for row in sorted(table.rows, key=lambda r: r.row_no):
            kind = _row_kind(row)
            page = row.pdf_page_number or default_page
            if kind == "SECTION_HEADER":
                section_label = " ".join(str(c.raw) for c in row.cells.values() if c.raw) or section_label
                continue
            if kind == "NOTE":
                continue
            area_val, area_raw = _cell(row, "area_m2")
            area = parse_number(area_val)
            room, _ = _cell(row, "room_no")
            name, _ = _cell(row, "name")
            rec = {
                "row_no": row.row_no,
                "room_no": None if room is None else str(room),
                "name": None if name is None else str(name),
                "area_m2": area if area is not None else UNKNOWN,
            }
            if kind == "DATA":
                for acc in (since_total, since_sub):
                    acc.rows.append(rec)
                    acc.decimals = max(
                        acc.decimals, decimals_of(area_raw if area_raw is not None else area_val)
                    )
                    acc.pages.add(page)
            elif kind == "SUBZONE":
                rec["parent_row_no"] = row.parent_row_no
                for acc in (since_total, since_sub):
                    acc.subzones.append(rec)
                    acc.decimals = max(
                        acc.decimals, decimals_of(area_raw if area_raw is not None else area_val)
                    )
                    acc.pages.add(page)
            elif kind in ("SUBTOTAL", "TOTAL"):
                acc = since_sub if kind == "SUBTOTAL" else since_total
                label_raw = " ".join(str(c.raw) for k, c in row.cells.items() if c.raw and k != "area_m2")
                total = parse_number(area_val)
                dec = max(acc.decimals, decimals_of(area_raw if area_raw is not None else area_val))
                block: dict[str, Any] | None = None
                if acc.rows:
                    n = len(acc.rows) + len(acc.subzones)
                    block = {
                        "block_id": f"{table.table_id}#{row.row_no}",
                        "table_id": table.table_id,
                        "continued_from": [t.table_id for t in chain[: chain.index(table)]],
                        "file_id": file_id,
                        "stage": stage,
                        "page": page,
                        "sheet_number": sheet if sheet is not None else first.sheet_number,
                        "document_code": first.document_code,
                        "title": first.title,
                        "section": section_label,
                        "label": section_label or first.title or f"стр. {page}",
                        "total_kind": kind,
                        "level": "GROUP",
                        "hierarchy_unresolved": False,
                        "total_label": label_raw,
                        "total": total if total is not None else UNKNOWN,
                        "rows": list(acc.rows),
                        "subzones": list(acc.subzones),
                        "n_rows": len(acc.rows),
                        "n_subzones": len(acc.subzones),
                        "decimals": dec,
                        "rounding_tolerance": round(0.5 * 10 ** (-dec) * math.sqrt(max(n, 1)), 6),
                        "pages": sorted(acc.pages | {page}),
                        "confidence": first.confidence if first.confidence is not None else 1.0,
                        "evidence": [_evidence(stage, file_id, page, row.bbox, sheet if sheet is not None else first.sheet_number)],
                    }  # fmt: skip
                if kind == "TOTAL" and block is not None and total is not None:
                    block = _resolve_level(block, closed, label_raw)
                if block is not None:
                    blocks.append(block)
                since_sub = _BlockAcc.new()
                if kind == "TOTAL":
                    if block is not None and block["level"] == "GRAND":
                        closed = []
                    elif block is not None and block["total"] is not UNKNOWN:
                        closed.append(block)
                    since_total = _BlockAcc.new()
                    section_label = None
    return blocks


def _resolve_level(block: dict[str, Any], closed: list[dict[str, Any]], label: str) -> dict[str, Any]:
    """A TOTAL over group totals (see :func:`explication_blocks`), or the plain group block."""
    total = block["total"]
    own = sum(r["area_m2"] for r in block["rows"] if r["area_m2"] is not UNKNOWN)
    own_sub = own + sum(r["area_m2"] for r in block["subzones"] if r["area_m2"] is not UNKNOWN)
    tol = max(0.05, block["rounding_tolerance"])
    if not closed or abs(total - own) <= tol or abs(total - own_sub) <= tol:
        return block
    if not (_GRAND_LABEL_RE.search(label) or total > 1.5 * own_sub):
        return block
    groups = [
        {"row_no": b["block_id"], "room_no": None, "name": b["label"], "area_m2": b["total"]} for b in closed
    ]
    rows = groups + list(block["rows"])
    grand = sum(g["area_m2"] for g in groups) + own
    return {
        **block,
        "level": "GRAND",
        "hierarchy_unresolved": abs(total - grand) > max(tol, 0.05 * len(groups)),
        "rows": rows,
        "n_rows": len(rows),
        "pages": sorted({p for b in closed for p in b["pages"]} | set(block["pages"])),
    }


def _floor_of(text: str | None) -> str | None:
    if not text:
        return None
    m = _FLOOR_RE.search(text)
    if not m:
        return None
    return (m.group(1) or m.group(2) or m.group(0)).lower()


class FactBuilder:
    """Builds the fact sheet of one object; element presence is computed only for the families the rules name."""

    def __init__(self, inputs: HypothesisInputs, index: ElementIndex | None = None):
        self.inputs = inputs
        self.index = index or ElementIndex(inputs)

    def build(self, element_families: Iterable[str] = ()) -> dict[str, Any]:
        facts: dict[str, Any] = {
            "object": {
                "object_id": self.inputs.object_id,
                "stages": sorted({d.stage for d in self.inputs.documents.values() if d.stage}),
            },
            "params": self._params(),
            "tables": self._tables(),
            "documents": self._documents(),
        }
        facts["tables"]["AOSR_REFS"] = self._aosr_refs(facts["tables"].pop("_AOSR_ACTS"), facts["documents"])
        self._tep_into_params(facts)
        facts["stage_facts"] = self._stage_facts(facts)
        facts["elements"] = self._elements(element_families)
        facts["id_works"] = self._id_works()
        return facts

    def _stage_facts(self, facts: Mapping[str, Any]) -> list[dict[str, Any]]:
        """One item per stage with the object indicators the ТЭП rules compare (HR-LOG-003/004/006/012)."""
        params = facts["params"]
        tep = facts["tables"]["TEP"]
        areas = self._areas(facts["tables"]["EXPLICATION_BLOCKS"])
        apartments = self._apartments()
        stages = sorted(
            {s for code in params.values() for s in code if s in ("PD", "RD", "ID")}
            | set(tep)
            | set(areas)
            | set(apartments)
        )
        out: list[dict[str, Any]] = []
        for st in stages:
            item: dict[str, Any] = {"stage": st}
            evidence: list[dict[str, Any]] = []
            for key, code in _TEP_PARAM.items():
                v = params.get(code, {}).get(st)
                if v is not None:
                    item[key] = v
                    evidence.extend(params[code].get(f"{st}_evidence", [])[:1])
            if "plot_area_m2" in tep.get(st, {}):
                item["plot_area_m2"] = tep[st]["plot_area_m2"]
                evidence.extend(tep[st].get("plot_area_m2_evidence", [])[:1])
            if st in areas:
                item.update({k: v for k, v in areas[st].items() if k != "evidence"})
                evidence.extend(areas[st]["evidence"][:1])
            if st in apartments:
                item["apartment_types"] = apartments[st]["types"]
            item["evidence"] = _dedup_evidence(evidence)
            out.append(item)
        return out

    # values -----------------------------------------------------------------------------------------
    def _best_values(self) -> dict[tuple[str, str], ExtractedValue]:
        best: dict[tuple[str, str], ExtractedValue] = {}
        for v in self.inputs.values:
            if v.param_code is None or v.is_ambiguous or v.quality_flag == "ABSTAIN":
                continue
            if v.location not in (None, "OBJECT"):
                continue
            key = (str(v.param_code), str(v.stage))
            cur = best.get(key)
            rank = (v.candidate_rank or 1, -v.confidence)
            if cur is None or rank < ((cur.candidate_rank or 1), -cur.confidence):
                best[key] = v
        return best

    def _params(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = defaultdict(dict)
        for (code, stage), v in self._best_values().items():
            value = v.value_norm.value
            num = parse_number(value) if not isinstance(value, bool) else None
            out[code][stage] = num if num is not None else value
            out[code][f"{stage}_evidence"] = [_evidence(stage, v.file_id, v.page_no)]
        return dict(out)

    def _apartments(self) -> dict[str, Any]:
        by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for v in self.inputs.values:
            if str(v.param_code) != "PZ-011" or v.is_ambiguous or not v.location:
                continue
            n = parse_number(v.value_norm.value)
            if n is not None:
                by_stage[str(v.stage)].append({"type": v.location, "count": n})
        return {s: {"types": rows} for s, rows in by_stage.items()}

    # tables -----------------------------------------------------------------------------------------
    def _stage_of(self, file_id: str, ta: TableArtifacts) -> str | None:
        doc = self.inputs.documents.get(file_id)
        if doc is not None and doc.stage:
            return doc.stage
        return ta.stage.value if ta.stage is not None else None

    def _tables(self) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = []
        deviations: list[dict[str, Any]] = []
        acts: list[dict[str, Any]] = []
        tep: dict[str, dict[str, Any]] = defaultdict(dict)
        families = load_families()
        for fid in sorted(self.inputs.tables):
            ta = self.inputs.tables[fid]
            stage = self._stage_of(fid, ta)
            for t in ta.tables:
                ttype = str(t.table_type)
                sheet = (
                    t.sheet_number
                    if t.sheet_number is not None
                    else self.inputs.sheet_number(fid, t.pages[0])
                )
                if ttype == "EXPLICATION":
                    continue  # by continuation chains, below
                elif ttype == "DEVIATION":
                    deviations.extend(self._deviation_rows(t, fid, stage, sheet, families))
                elif ttype == "AOSR":
                    acts.extend(self._aosr_rows(t, fid, stage))
                elif ttype == "TEP" and stage:
                    for row in t.rows:
                        if row.kind is not None and str(row.kind) not in ("DATA", "TOTAL"):
                            continue  # «в том числе» parts are not the object's indicators
                        ind, _ = _cell(row, "indicator")
                        val, _ = _cell(row, "value")
                        key = self._tep_key(ind, t.title)
                        num = parse_number(val)
                        if key and num is not None and key not in tep[stage]:
                            tep[stage][key] = num
                            tep[stage][f"{key}_evidence"] = [
                                _evidence(stage, fid, row.pdf_page_number or t.pages[0], row.bbox, sheet)
                            ]
        for fid in sorted(self.inputs.tables):
            ta = self.inputs.tables[fid]
            stage = self._stage_of(fid, ta)
            explications = [t for t in ta.tables if str(t.table_type) == "EXPLICATION"]
            for chain in explication_chains(explications):
                t0 = chain[0]
                sheet = (
                    t0.sheet_number
                    if t0.sheet_number is not None
                    else self.inputs.sheet_number(fid, t0.pages[0])
                )
                blocks.extend(explication_blocks(chain, file_id=fid, stage=stage, sheet=sheet))
        return {
            "EXPLICATION_BLOCKS": blocks,
            "DEVIATION_ROWS": deviations,
            "_AOSR_ACTS": acts,
            "TEP": dict(tep),
        }

    @staticmethod
    def _tep_key(indicator: Any, title: str | None = None) -> str | None:
        """The object fact of a ТЭП row. In the plot's ТЭП («Технико-экономические показатели земельного участка»)
        «Общая площадь» is the plot area, not the building's total area (F0154 p13: 13060,00 м²)."""
        if indicator is None:
            return None
        text = _ENUM_PREFIX_RE.sub("", norm_text(str(indicator)))  # «1 Общая площадь», «2.1. Здание школы»
        plot_table = bool(title and _PLOT_TEP_RE.search(norm_text(title)))
        for key, names in TEP_INDICATORS.items():
            if any(text.startswith(norm_text(n)) for n in names):
                if plot_table and key == "total_area_m2":
                    return "plot_area_m2"
                return key
        return None

    def _tep_into_params(self, facts: dict[str, Any]) -> None:
        """ТЭП indicators fill catalog parameters not already extracted, and object-only facts (plot area)."""
        params = facts["params"]
        for stage, ind in facts["tables"]["TEP"].items():
            for key, code in _TEP_PARAM.items():
                if key in ind and stage not in params.get(code, {}):
                    params.setdefault(code, {})[stage] = ind[key]
                    params[code][f"{stage}_evidence"] = ind.get(f"{key}_evidence", [])

    def _deviation_rows(
        self, t: TypedTable, fid: str, stage: str | None, sheet: Any, families: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        matchers = {
            name: PhraseMatcher(fam.anchors)
            for name, fam in families.items()
            if fam.route("TOLERANCE_EXCEEDED") is not None
        }
        out: list[dict[str, Any]] = []
        for row in t.rows:
            if row.kind is not None and str(row.kind) != "DATA":
                continue
            design, _ = _cell(row, "design_value")
            actual, _ = _cell(row, "actual_value")
            dev_raw, _ = _cell(row, "deviation")
            tol_raw, _ = _cell(row, "tolerance")
            dev = parse_number(dev_raw)
            d_n, a_n = parse_number(design), parse_number(actual)
            if dev is None and d_n is not None and a_n is not None:
                dev = a_n - d_n
            tol = _tolerance(tol_raw)
            element, parameter = _cell(row, "element")[0], _cell(row, "parameter")[0]
            label = " ".join(str(x) for x in (element, parameter) if x)
            # the measured parameter («Отметка верха») decides the family before the element («Плита перекрытия»)
            family = next(
                (
                    n
                    for text in (parameter, element)
                    if text
                    for n, m in matchers.items()
                    if m.search_text(str(text))
                ),
                None,
            )
            route = families[family].route("TOLERANCE_EXCEEDED") if family else None
            inc = families[family].route("VALUE_INCREASED") if family else None
            out.append(
                {
                    "row_no": row.row_no,
                    "label": label or None,
                    "axes": _cell(row, "axes")[0],
                    "deviation": dev if dev is not None else UNKNOWN,
                    "tolerance": tol if tol is not None else UNKNOWN,
                    "unit": _cell(row, "unit")[0],
                    "family": family,
                    "matrix_code": route.parameter_code if route is not None and not route.is_free else None,
                    "matrix_mapped": bool(route is not None and not route.is_free and route.parameter_code),
                    "free_route": bool(route is not None and route.is_free),
                    "increase_is_context": bool(inc is not None and not inc.emit),
                    "file_id": fid,
                    "stage": stage,
                    "page": row.pdf_page_number or t.pages[0],
                    "evidence": [_evidence(stage, fid, row.pdf_page_number or t.pages[0], row.bbox, sheet)],
                }
            )
        return out

    def _aosr_rows(self, t: TypedTable, fid: str, stage: str | None) -> list[dict[str, Any]]:
        """Acts with the document codes they cite: every code of п.2 (project documentation), and of п.4
        (executive schemes, protocols, certificates) only project ciphers — codes with a stage part «Р»/«РД»/«П»
        («Исполнительные чертежи АНО1301211-Р-ОВ1», F0196) — since certificate numbers there are not documents of
        the set."""
        out: list[dict[str, Any]] = []
        for row in t.rows:
            refs_raw, _ = _cell(row, "rd_refs")
            quality_raw, _ = _cell(row, "quality_docs")
            act_no, _ = _cell(row, "act_no")
            act_date, _ = _cell(row, "act_date")
            end_date, _ = _cell(row, "end_date")
            work, _ = _cell(row, "work_name")
            page = row.pdf_page_number or t.pages[0]
            refs: list[tuple[CodeRef, str]] = []
            if refs_raw is not None:
                refs += [(r, "п. 2") for r in document_codes(str(refs_raw))]
            if quality_raw is not None:
                refs += [(r, "п. 4") for r in document_codes(str(quality_raw)) if r.stage_hint]
            # one citation per cipher and revision; a bare mention adds nothing next to one with «изм. N»
            by_key: dict[str, list[tuple[CodeRef, str]]] = {}
            for r, f in refs:
                cited = by_key.setdefault(r.key, [])
                if any(x.revision == r.revision for x, _ in cited) or (r.revision is None and cited):
                    continue
                if r.revision is not None:
                    cited[:] = [(x, g) for x, g in cited if x.revision is not None]
                cited.append((r, f))
            refs = [c for cited in by_key.values() for c in cited]
            out.append(
                {
                    "act_no": None if act_no is None else str(act_no),
                    "act_date": parse_date(act_date) or parse_date(end_date),
                    "work_name": None if work is None else str(work),
                    "rd_refs_raw": None if refs_raw is None else str(refs_raw),
                    "refs": refs,
                    "file_id": fid,
                    "stage": stage,
                    "page": page,
                    "evidence": [_evidence(stage, fid, page, row.bbox)],
                }
            )
        return out

    # documents --------------------------------------------------------------------------------------
    def _documents(self) -> dict[str, Any]:
        """Per stage: known document code keys, and per key the current revision and its dates.

        A PDF may bundle several documents (F0201: the drawings «…-РД-ОВ1» and the specification «…-РД-ОВ1.С»), so
        every code of a file's title blocks is registered with its own revisions («Изм.» rows, sheet revisions). A
        title block whose code was not read belongs to the document of the nearest preceding page with a code
        (documents occupy contiguous page ranges). A code in the file name proves membership only, never a revision
        (97 §2.12)."""
        out: dict[str, Any] = {}
        by_stage: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        missing_code: Counter[str] = Counter()

        def register(
            stage: str,
            code: str,
            file_id: str,
            source: str,
            revs: list[int],
            dates: dict[int, str],
            pages: dict[int, int] | None = None,
        ) -> None:
            key = code_key(code)
            cur = max(revs) if revs else None
            entry = by_stage[stage].get(key)
            rev_pages = {str(k): v for k, v in sorted((pages or {}).items())}
            if entry is None:
                by_stage[stage][key] = {
                    "code": code,
                    "file_id": file_id,
                    "source": source,
                    "current_revision": cur,
                    "revision_dates": {str(k): v for k, v in sorted(dates.items())},
                    "revision_pages": rev_pages,  # revision → the page of its «Изм.» row (evidence)
                }
                return
            if cur is not None and (entry["current_revision"] is None or cur > entry["current_revision"]):
                entry.update(
                    code=code, file_id=file_id, source=source, current_revision=cur, revision_pages=rev_pages
                )
            for k, v in dates.items():
                if str(k) not in entry["revision_dates"] or v > entry["revision_dates"][str(k)]:
                    entry["revision_dates"][str(k)] = v

        for doc in sorted(self.inputs.documents.values(), key=lambda d: d.file_id):
            if not doc.stage or not doc.citable:
                continue
            layout = self.inputs.layouts.get(doc.file_id)
            per_code: dict[str, dict[str, Any]] = {}
            blocks = sorted(layout.title_blocks or [], key=lambda tb: tb.pdf_page_number) if layout else []
            first_code = next((tb.document_code for tb in blocks if tb.document_code), None)
            current = first_code
            for tb in blocks:
                current = tb.document_code or current
                if current is None:
                    continue
                acc = per_code.setdefault(
                    code_key(current), {"codes": Counter(), "revs": [], "dates": {}, "pages": {}}
                )
                if tb.document_code:
                    acc["codes"][tb.document_code] += 1
                r = revision_number(tb.revision)
                if r is not None:
                    acc["revs"].append(r)
                    acc["pages"].setdefault(r, tb.pdf_page_number)
                for cr in tb.change_rows or []:
                    n = revision_number(cr.change_no)
                    d = parse_date(cr.date)
                    if n is not None:
                        acc["revs"].append(n)
                        if d and (n not in acc["dates"] or d > acc["dates"][n]):
                            acc["dates"][n] = d
                            acc["pages"][n] = tb.pdf_page_number  # the row that dates the revision
                        else:
                            acc["pages"].setdefault(n, tb.pdf_page_number)
            if not per_code and doc.document_code:
                rev = revision_number(doc.revision) if doc.revision else None
                per_code[code_key(doc.document_code)] = {
                    "codes": Counter({doc.document_code: 1}),
                    "revs": [rev] if rev is not None else [],
                    "dates": {},
                    "pages": {},
                }
            for acc in per_code.values():
                register(doc.stage, acc["codes"].most_common(1)[0][0], doc.file_id, "TITLE_BLOCK", acc["revs"],
                         acc["dates"], acc["pages"])  # fmt: skip
            # membership fallback: a code in the file name proves the document exists, never its revision
            # «АНО-150321-1-РД-ОВ2.1_изм. 3_в1.pdf»: underscores separate the cipher from the rest of the name
            named = document_codes(doc.name.replace("_", " ")) if doc.name else []
            if named and named[0].key not in per_code:
                register(doc.stage, named[0].raw, doc.file_id, "FILE_NAME", [], {})
            if not per_code and not named:
                missing_code[doc.stage] += 1
        # «Состав проекта» tables list codes of the stage too (revision column when present)
        for fid, ta in self.inputs.tables.items():
            stage = self._stage_of(fid, ta)
            for t in ta.tables:
                if str(t.table_type) != "PROJECT_COMPOSITION":
                    continue
                for row in t.rows:
                    des, _ = _cell(row, "designation")
                    if not des:
                        continue
                    for ref in document_codes(str(des)):
                        rev = revision_number(str(_cell(row, "revision")[0] or "")) or ref.revision
                        tgt = by_stage[ref.stage_hint or stage or "RD"].setdefault(
                            ref.key,
                            {
                                "code": ref.raw,
                                "file_id": None,
                                "source": "PROJECT_COMPOSITION",
                                "current_revision": rev,
                                "revision_dates": {},
                                "revision_pages": {},
                            },
                        )
                        if rev is not None and (
                            tgt["current_revision"] is None or rev > tgt["current_revision"]
                        ):
                            tgt["current_revision"] = rev
        for stage in sorted(set(by_stage) | set(missing_code)):
            entries = by_stage.get(stage, {})
            out[stage] = {
                "code_keys": sorted(entries),
                "by_key": dict(sorted(entries.items())),
                "complete": missing_code[stage] == 0 and bool(entries),
            }
        return out

    def _aosr_refs(self, acts: list[dict[str, Any]], documents: Mapping[str, Any]) -> list[dict[str, Any]]:
        """One fact per (act, cited document code), joined with the registry of the code's stage."""
        from rapidfuzz import process
        from rapidfuzz.distance import Levenshtein

        out: list[dict[str, Any]] = []
        for act in acts:
            for ref, field in act["refs"]:
                stages = [ref.stage_hint] if ref.stage_hint else ["RD", "PD"]
                registry = [documents.get(st, {}) for st in stages]
                entry = next((r["by_key"][ref.key] for r in registry if ref.key in r.get("by_key", {})), None)
                if entry is not None:
                    in_registry: Any = True
                elif all(r.get("complete") for r in registry):
                    in_registry = False
                else:
                    in_registry = UNKNOWN
                closest = None
                if entry is None:
                    keys = [k for r in registry for k in r.get("code_keys", [])]
                    best = (
                        process.extractOne(ref.key, keys, scorer=Levenshtein.normalized_similarity)
                        if keys
                        else None
                    )
                    if best is not None and best[1] >= 0.75:
                        closest = next(
                            r["by_key"][best[0]]["code"] for r in registry if best[0] in r.get("by_key", {})
                        )
                cited_date = (
                    entry["revision_dates"].get(str(ref.revision))
                    if entry and ref.revision is not None
                    else None
                )
                cur = entry["current_revision"] if entry is not None else None
                cur_date = (
                    entry["revision_dates"].get(str(cur)) if entry is not None and cur is not None else None
                )
                # the RD page carrying the current revision's «Изм.» row is evidence too (it shows the newer edition)
                evidence = list(act["evidence"])
                cur_page = (
                    (entry.get("revision_pages") or {}).get(str(cur)) if entry and cur is not None else None
                )
                if cur_page is not None and entry.get("file_id"):
                    evidence.append(_evidence(ref.stage_hint or "RD", entry["file_id"], cur_page))
                out.append(
                    {
                        "act_no": act["act_no"],
                        "act_date": act["act_date"] or UNKNOWN,
                        "work_name": act["work_name"],
                        "code": ref.raw,
                        "key": ref.key,
                        "field_ru": field,
                        "stage_hint": ref.stage_hint,
                        "revision": ref.revision if ref.revision is not None else UNKNOWN,
                        "in_registry": in_registry,
                        "current_revision": cur if cur is not None else UNKNOWN,
                        "current_revision_date": cur_date or UNKNOWN,
                        "cited_revision_date": cited_date or UNKNOWN,
                        "closest_code": closest,
                        "file_id": act["file_id"],
                        "stage": act["stage"],
                        "page": act["page"],
                        "evidence": evidence,
                    }
                )
        return out

    # areas ------------------------------------------------------------------------------------------
    @staticmethod
    def _areas(blocks: list[dict[str, Any]]) -> dict[str, Any]:
        """Per stage: floor totals from explication TOTAL rows that name a floor («Итого по этажу»)."""
        out: dict[str, Any] = {}
        per_stage: dict[str, dict[str, float]] = defaultdict(dict)
        evid: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for b in blocks:
            if b["total_kind"] != "TOTAL" or b["total"] is UNKNOWN or not b["stage"]:
                continue
            label = " ".join(x for x in (b["total_label"], b["title"], b["section"]) if x)
            if "этаж" not in label.lower():
                continue
            floor = _floor_of(b["title"]) or _floor_of(b["section"]) or _floor_of(b["total_label"])
            if floor is None or floor in per_stage[b["stage"]]:
                continue
            per_stage[b["stage"]][floor] = b["total"]
            evid[b["stage"]].extend(b["evidence"])
        for stage, floors in per_stage.items():
            out[stage] = {
                "floor_totals": [{"floor": f, "total": v} for f, v in sorted(floors.items())],
                "floor_count": len(floors),
                "evidence": evid[stage][:3],
            }
        return out

    # elements ---------------------------------------------------------------------------------------
    def _elements(self, families: Iterable[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        known = self.index.families
        for fam in sorted(set(families)):
            if fam not in known:
                continue
            out[fam] = {st: self.index.presence(fam, st).as_fact() for st in ("PD", "RD", "ID")}
        return out

    def _id_works(self) -> list[dict[str, Any]]:
        """Works that the ИД documents (UNDOCUMENTED_WORK routes): presence in ИД (positive evidence, any section)
        against presence in РД and ПД of the family's discipline (absence only with full coverage)."""
        out: list[dict[str, Any]] = []
        for fam in load_families().values():
            route = fam.route("UNDOCUMENTED_WORK")
            if route is None or not route.emit:
                continue
            id_docs = self.inputs.docs("ID", set(fam.manifest_sections) | {"OTHER"})
            id_hits = self.index.hits(fam.family, id_docs)
            if not id_hits:
                continue
            rd = self.index.presence(fam.family, "RD")
            pd = self.index.presence(fam.family, "PD")
            out.append(
                {
                    "family": fam.family,
                    "label": fam.label_ru,
                    "parameter_code": route.parameter_code,
                    "id_present": True,
                    "rd_present": rd.value,
                    "pd_present": pd.value,
                    "rd_coverage": round(rd.coverage, 4),
                    "rd_pages_read": rd.pages_read,
                    "stage": "ID",
                    "evidence": [
                        {
                            "stage": "ID",
                            "file_id": h.file_id,
                            "pdf_page_number": h.page_no,
                            "geometry": {"boxes": [list(h.bbox)]},
                        }
                        for h in id_hits[:2]
                    ],
                    "phrase": id_hits[0].phrase,
                }
            )
        return out


def _dedup_evidence(evidence: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for e in evidence:
        k = (e.get("stage"), e.get("file_id"), e.get("pdf_page_number"))
        if k not in seen:
            seen.add(k)
            out.append(dict(e))
    return out


def _tolerance(raw: Any) -> float | None:
    """«±12», «15», «+10/-5» → the largest absolute tolerance."""
    if raw is None:
        return None
    nums = [abs(float(x.replace(",", "."))) for x in re.findall(r"\d+(?:[.,]\d+)?", str(raw))]
    return max(nums) if nums else None


def referenced_families(expressions: Iterable[Any]) -> set[str]:
    """Element families named by ``elements.<FAMILY>.<STAGE>…`` vars in rule expressions."""
    out: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "var":
                    path = v[0] if isinstance(v, list) and v else v
                    if isinstance(path, str):
                        parts = path.lstrip("^").split(".")
                        if len(parts) >= 2 and parts[0] == "elements":
                            out.add(parts[1])
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    for e in expressions:
        walk(e)
    return out
