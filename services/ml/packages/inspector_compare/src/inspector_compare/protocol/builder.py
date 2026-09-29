"""Findings of one object → the canonical protocol JSON (contract ``protocol``; 93 §5.1–5.6, 97 §2.11).

Body: Приложение 2 verbatim — header, status line, sections 1–7 (7.1/7.2) — plus the «Тип проверки» line and
the added summary rows of Раздел 2 (only when non-zero). Appendices: А (the five ТЗ §9.2 п.4 tables), Б (evidence
cards), В (input registry, versions, hashes). Rows carry machine codes and the rendered Russian cell text, so the
DOCX/HTML/PDF renderers never re-derive wording. In a preliminary protocol every recommendation carries the prefix
«Проект рекомендации (до подтверждения инспектором): » and every decision is «⏳ Ожидает» (batch mode has no
inspector decisions; they never flow into a submission).
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from inspector_common.contracts.loader import contract_version, load_enums
from inspector_common.hashing import sha256_json
from inspector_common.params import ParamRegistry, load_params, overrides_summary
from inspector_compare.objectctx import ObjectContext
from inspector_compare.protocol import texts as T
from inspector_compare.recommendations import PRELIMINARY_PREFIX, TemplateSet, load_templates
from inspector_compare.valuebox import ValueLocator
from inspector_compare.values import rooms_phrase
from inspector_compare.version import COMPARE_VERSION, PROTOCOL_VERSION, RULES_VERSION

STAGES = ("PD", "RD", "ID")
STAGE_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}
PARTITION_ORDER = (
    "CHECKED_OK",
    "NOT_CHECKED_NO_ID",
    "NOT_LOADED_TECH_ERRORS",
    "NOT_CHECKED_NO_PD_RD",
    "NOT_CHECKED_REVISION_CONFLICT",
    "NOT_APPLICABLE",
)
ALWAYS_SHOWN = {"CHECKED_OK", "NOT_CHECKED_NO_ID", "NOT_LOADED_TECH_ERRORS"}
TECH_FOOTNOTE = (
    "В строке «Не загружены документы (технические ошибки)» учтены также параметры, документы по которым "
    "представлены, но значение не извлечено автоматически (сравнение невозможно, п. 9.2 ТЗ)"
)


def _printed(v: Any) -> str:
    """The value as printed on the page (qualifier ``printed``, e.g. «i=0,01») for the highlight box; else value_raw
    (which may be a normalised form such as «1 %»)."""
    q = getattr(getattr(v, "value_norm", None), "qualifiers", None) or {}
    return str(q.get("printed") or v.value_raw)


def _box_query(v: Any) -> tuple[str, str | None, int | None]:
    """(printed value, context, position of the value in the context) for the value locator."""
    q = getattr(getattr(v, "value_norm", None), "qualifiers", None) or {}
    at = q.get("ctx_at")
    return _printed(v), v.context_text, at if isinstance(at, int) else None


@dataclass(frozen=True, slots=True)
class ObjectPassport:
    name: str | None = None
    address: str | None = None
    supervision_case_no: str | None = None
    customer: str | None = None
    contractor: str | None = None


# The address part of a title-block object name: «Школа на 600 мест, р-н Богородское, ул. Тюменская, влд. 5».
_ADDRESS_START = re.compile(
    r"(?:^|[,:]\s*)((?:г\.|город|р-н|район|ул\.|улица|пр-т|просп\.|проспект|пер\.|переулок|ш\.|шоссе|наб\.|"
    r"набережная|пл\.|площадь|б-р|бульвар|проезд|пос\.|поселение|мкр\.?|микрорайон|кв-л|квартал)\s.*)$",
    re.IGNORECASE,
)


def passport_from_context(ctx: ObjectContext) -> ObjectPassport:
    """Header of the protocol from the documents themselves: the object name printed most often in the title
    blocks (AG-02B), split into the name and the address; the manifest corpus name when no title block has one.
    Supervision case, developer and contractor are not printed in the documents (the web product fills them)."""
    votes: Counter[str] = Counter()
    for layout in ctx.layouts.values():
        for tb in layout.title_blocks or []:
            if tb.object_name and tb.object_name.strip():
                votes[" ".join(tb.object_name.strip().strip('«»"').split())] += 1
    if not votes:
        return ObjectPassport(name=ctx.name)
    full = min(votes, key=lambda n: (-votes[n], n))
    match = _ADDRESS_START.search(full)
    if match is None or match.start(1) == 0:
        return ObjectPassport(name=full, address=match.group(1) if match else None)
    name = re.sub(r"\s+(?:по адресу|расположенн\w+ по адресу)$", "", full[: match.start()].rstrip(" ,:"))
    return ObjectPassport(name=name or full, address=match.group(1).strip())


def _labels(enum: str) -> dict[str, str]:
    return {v.code: (v.label_ru or v.code) for v in load_enums()[enum].values}


def _attr(enum: str, attr: str) -> dict[str, Any]:
    return {v.code: v.attrs.get(attr) for v in load_enums()[enum].values}


def _cell(value: Any, applicable: bool) -> str:
    if not applicable:
        return T.NOT_APPLICABLE_CELL
    if value is None or (isinstance(value, str) and not value.strip()):
        return T.NO_DATA_CELL
    return str(value)


def _stage_status(stage: str, loaded: int, expected: int) -> str:
    if expected == 0 or loaded == 0:
        return f"{stage}_MISSING"
    return f"{stage}_UPLOADED" if loaded >= expected else f"{stage}_PARTIAL"


def _files_ru(n: int) -> str:
    """«1 файл», «3 файла», «5 файлов»."""
    word = (
        "файлов"
        if 11 <= n % 100 <= 14
        else {1: "файл", 2: "файла", 3: "файла", 4: "файла"}.get(n % 10, "файлов")
    )
    return f"{n} {word}"


def _stage_of(v: Any) -> str:
    return str(v.stage.value if hasattr(v.stage, "value") else v.stage)


class ProtocolBuilder:
    def __init__(
        self,
        ctx: ObjectContext,
        groups: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        submission: Mapping[str, Any],
        *,
        run_id: str | None,
        generated_at: dt.datetime | None = None,
        version: int = 1,
        passport: ObjectPassport | None = None,
        local_status: Mapping[str, str] | None = None,
        versions: Mapping[str, Any] | None = None,
        params: ParamRegistry | None = None,
        templates: TemplateSet | None = None,
        process_status: str = "READY",
    ) -> None:
        self.ctx = ctx
        self.groups = groups
        self.findings = findings
        self.submission = submission
        self.run_id = run_id
        self.generated_at = (generated_at or dt.datetime.now(dt.UTC)).replace(microsecond=0)
        self.version = version
        self.passport = passport or passport_from_context(ctx)
        self.local_status = dict(local_status or {})
        self.versions = dict(versions or {})
        self.params = params or load_params()
        self.templates = templates or load_templates()
        self.process_status = process_status
        self.primary = [g for g in groups if not g.get("hedge_of_group_id")]
        self.twins: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for g in groups:
            if g.get("hedge_of_group_id"):
                self.twins[g["hedge_of_group_id"]].append(g)
        self.object_rows = [f for f in findings if f.get("location") == "OBJECT"]
        self._ai_cache: dict[str, Any] | None = None
        self._locator = ValueLocator(getattr(ctx, "run_dir", None))
        self._values_by_page: dict[tuple[str, int], list[Any]] | None = None
        self.scenario = self._scenario()

    # ── value highlights ──────────────────────────────────────────────────────────────────────

    def _page_values(self, file_id: str, page: int) -> list[Any]:
        if self._values_by_page is None:
            idx: dict[tuple[str, int], list[Any]] = defaultdict(list)
            for v in getattr(self.ctx, "values", None) or []:
                idx[(v.file_id, int(v.page_no))].append(v)
            self._values_by_page = idx
        return self._values_by_page.get((file_id, int(page)), [])

    def _value_geometry(self, file_id: str, page: int, pairs: list[tuple[Any, ...]]) -> dict[str, Any] | None:
        """{"boxes": [...]} of the extracted values' words on the page, None when they are not found."""
        if not pairs:
            return None
        boxes = self._locator.boxes(file_id, page, pairs)
        return {"boxes": boxes} if boxes else None

    # ── header ────────────────────────────────────────────────────────────────────────────────

    def _scenario(self) -> str:
        present = {s for s in STAGES if self._stage_counts(s)[0] > 0}
        base = {
            frozenset(STAGES): "FULL",
            frozenset({"PD", "RD"}): "PD_RD_ONLY",
            frozenset({"PD", "ID"}): "PD_ID_ONLY",
            frozenset({"RD", "ID"}): "RD_ID_ONLY",
        }.get(frozenset(present), "SINGLE_ONLY")
        partial = any(self._stage_counts(s)[0] < self._stage_counts(s)[1] for s in present)
        return "PARTIALLY_LOADED" if partial else base

    def _scenario_base(self) -> str:
        present = {s for s in STAGES if self._stage_counts(s)[0] > 0}
        return {
            frozenset(STAGES): "FULL",
            frozenset({"PD", "RD"}): "PD_RD_ONLY",
            frozenset({"PD", "ID"}): "PD_ID_ONLY",
            frozenset({"RD", "ID"}): "RD_ID_ONLY",
            frozenset(): "NONE",
        }.get(frozenset(present), "SINGLE_ONLY")

    def _stage_counts(self, stage: str) -> tuple[int, int]:
        """(loaded, expected) citable files of a resolved stage: expected = manifest, loaded = present on disk."""
        files = [f for f in self.ctx.files.values() if f.stage == stage and f.citable]
        loaded = [
            f
            for f in files
            if self.local_status.get(f.file_id, f.local_status or "PRESENT") != "MISSING_ON_DISK"
        ]
        return len(loaded), len(files)

    def protocol_no(self) -> str:
        code = self.ctx.object_id.removeprefix("OBJ-")
        return f"{self.generated_at:%Y-%m-%d}-{code}-{self.version}"

    def header(self) -> dict[str, Any]:
        scenario_ru = _labels("LoadScenario").get(self.scenario, self.scenario)
        return {
            "title": T.TITLE_PREFIX + self.protocol_no(),
            "generated_at_ru": T.ru_date(self.generated_at),
            "version_line": f"{self.version} ({'окончательная' if self.process_status == 'FINALIZED' else 'предварительная'})",
            "status_line": T.STATUS_LINES.get(self.process_status, T.STATUS_LINES["READY"]),
            "scenario_line": T.scenario_line(self.scenario, scenario_ru),
            "recheck_running": False,
        }

    # ── Раздел 1 ──────────────────────────────────────────────────────────────────────────────

    def section1(self) -> dict[str, Any]:
        rows = []
        for stage in STAGES:
            loaded, expected = self._stage_counts(stage)
            status = _stage_status(stage, loaded, expected)
            kind = status.split("_", 1)[1]
            if kind == "MISSING":
                comment = (
                    "Документы стадии не представлены" if expected == 0 else f"Отсутствуют {expected} файлов"
                )
            elif kind == "PARTIAL":
                comment = f"Отсутствуют {expected - loaded} файлов"
            else:
                comment = "Все файлы загружены"
            rows.append(
                {
                    "stage": stage,
                    "stage_ru": STAGE_RU[stage],
                    "status": status,
                    "status_ru": T.LOAD_STATUS_RU[kind],
                    "files_loaded": loaded,
                    "files_loaded_text": str(loaded) if kind != "PARTIAL" else f"{loaded} из {expected}",
                    "files_expected": expected if expected else None,
                    "comment": comment,
                }
            )
        return {"rows": rows, "scenario_line": self.header()["scenario_line"]}

    # ── Разделы 4–7 (violations) ──────────────────────────────────────────────────────────────

    def _param(self, code: str) -> Any:
        return self.params.get(code)

    def _violation_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        critical, substantial = [], []
        for g in self.primary:
            if g["matrix_scope"] != "MATRIX":
                continue
            (critical if g.get("criticality_level") == "CRITICAL_SUSPEND" else substantial).append(g)
        rows4, rows5 = [], []
        n = 0
        for bucket, out in ((critical, rows4), (substantial, rows5)):
            for g in bucket:
                n += 1
                out.append(self._violation_row(n, g))
        return rows4, rows5

    def _parameter_label(self, g: Mapping[str, Any]) -> str:
        spec = self._param(g["parameter_code"])
        label = f"{spec.short_name} ({g['parameter_code']})"
        if g.get("location_type") != "OBJECT" and g.get("locations"):
            label += ", " + rooms_phrase(list(g["locations"]))
        twins = self.twins.get(g["finding_group_id"], [])
        if twins:
            label += " (альтернативный код: " + ", ".join(t["parameter_code"] for t in twins) + ")"
        return label + f" [карточка {g['card_no']}]"

    def _applicable(self, g: Mapping[str, Any]) -> dict[str, bool]:
        axis = g.get("axis") or "PD_RD"
        stages = set(axis.split("_"))
        return {s: s in stages for s in STAGES}

    def _violation_row(self, no: int, g: Mapping[str, Any]) -> dict[str, Any]:
        app = self._applicable(g)
        ext = g.get("ext") or {}
        return {
            "no": no,
            "section_ru": self._param(g["parameter_code"]).section,
            "parameter_label": self._parameter_label(g),
            "parameter_code": g["parameter_code"],
            "parameter_id": g.get("parameter_id"),
            "matrix_scope": g["matrix_scope"],
            "locations": list(g.get("locations") or []),
            "pd": _cell(g.get("pd_value"), app["PD"]),
            "rd": _cell(g.get("rd_value"), app["RD"]),
            "id": _cell(g.get("id_value"), app["ID"]),
            "deviation": {
                "direction": ext.get("deviation_direction"),
                "text": ext.get("deviation_text") or "🔄 Изменена конфигурация",
            },
            "inspector_status": "PENDING",
            "inspector_decision_ru": T.DECISION_RU["PENDING"],
            "card_ref": g["card_no"],
            "finding_group_id": g["finding_group_id"],
            "finding_ids": list(g["finding_ids"])
            + [fid for t in self.twins.get(g["finding_group_id"], []) for fid in t["finding_ids"]],
            "criticality_level": g.get("criticality_level"),
        }

    def _free_groups(self) -> list[dict[str, Any]]:
        return [g for g in self.primary if g["matrix_scope"] == "FREE_SEARCH"]

    def _free_description(self, g: Mapping[str, Any]) -> str:
        ext = g.get("ext") or {}
        kind = str(ext.get("violation_kind_row") or g.get("title") or "")
        suffix = f" ({g['parameter_code']})"
        if kind.endswith(suffix):
            kind = kind[: -len(suffix)]
        where = rooms_phrase(list(g.get("locations") or []))
        return f"{kind}, {where}" if where and where not in kind else kind

    def _ai_extra(self) -> dict[str, Any]:
        """Value-conflict suspicions (AG-07, ТЗ §9.5): rows of Раздел 6 / А.5 and their Б-cards, after the FREE
        groups. They never touch violations, checks or the submission."""
        if self._ai_cache is not None:
            return self._ai_cache
        empty: dict[str, Any] = {"section6_rows": [], "a5_rows": [], "suspicions": []}
        self._ai_cache = empty
        try:
            from inspector_hypothesis import compare_hook

            matrix_keys = {
                (str(code), str(loc))
                for g in self.groups
                if g.get("matrix_scope") != "FREE_SEARCH"
                for code in [g["parameter_code"], *(g.get("alt_parameter_codes") or [])]
                for loc in g.get("locations") or []
            }
            cards = [
                int(m.group(1))
                for g in self.primary
                if (m := re.match(r"Б\.(\d+)$", str(g.get("card_no") or "")))
            ]
            free = self._free_groups()
            extra = compare_hook.protocol_suspicions(
                ctx=self.ctx,
                run_dir=getattr(self.ctx, "run_dir", None),
                rendered_free_groups=free,
                start_no=len(free) + 1,
                first_card_no=max(cards, default=0) + 1,
                matrix_keys=matrix_keys,
                rule_codes=(compare_hook.VALUE_CONFLICT_RULE,),
            )
            if not extra.get("error"):
                self._ai_cache = extra
        except Exception:  # AG-07 must never break the protocol
            self._ai_cache = empty
        return self._ai_cache

    def section6(self) -> dict[str, Any]:
        method_ru = _labels("DiscoveryMethod")
        rows = []
        for n, g in enumerate(self._free_groups(), start=1):
            app = self._applicable(g)
            method = g.get("discovery_method") or "GRAPHIC_DIFF"
            rows.append(
                {
                    "no": n,
                    "method": method,
                    "method_ru": method_ru.get(method, method),
                    "description": self._free_description(g),
                    "pd": _cell(g.get("pd_value"), app["PD"]),
                    "rd": _cell(g.get("rd_value"), app["RD"]),
                    "id": _cell(g.get("id_value"), app["ID"]),
                    "parameter_code": g["parameter_code"],
                    "inspector_status": "PENDING",
                    "inspector_decision_ru": T.DECISION_RU["PENDING"],
                    "rejection_reason": "—",
                    "ai_comment": "—",
                    "confidence": g.get("confidence"),
                    "card_ref": g["card_no"],
                    "finding_group_id": g["finding_group_id"],
                }
            )
        rows += [dict(r) for r in self._ai_extra()["section6_rows"]]
        return {"count": len(rows), "rows": rows}

    def section7(self, rows4: list[dict[str, Any]], rows5: list[dict[str, Any]]) -> dict[str, Any]:
        by_id = {g["finding_group_id"]: g for g in self.primary}
        critical, substantial = [], []
        for n, row in enumerate(rows4, start=1):
            g = by_id[row["finding_group_id"]]
            ext, rec = g.get("ext") or {}, g.get("recommendation") or {}
            critical.append(
                {
                    "no": n,
                    "work_type": ext.get("work_type_row")
                    or f"{rec.get('work_type') or 'Работы'} ({g['parameter_code']})",
                    "recommendation": PRELIMINARY_PREFIX + str(rec.get("text") or ""),
                    "parameter_code": g["parameter_code"],
                    "is_draft": True,
                    "text_origin": rec.get("text_origin") or "AG03_DRAFT",
                    "template_id": rec.get("template_id"),
                    "source_row_no": row["no"],
                }
            )
        for n, row in enumerate(rows5, start=1):
            g = by_id[row["finding_group_id"]]
            ext, rec = g.get("ext") or {}, g.get("recommendation") or {}
            substantial.append(
                {
                    "no": n,
                    "violation_kind": ext.get("violation_kind_row")
                    or f"{row['deviation']['text']} ({g['parameter_code']})",
                    "recommendation": PRELIMINARY_PREFIX + str(rec.get("text") or ""),
                    "parameter_code": g["parameter_code"],
                    "is_draft": True,
                    "text_origin": rec.get("text_origin") or "AG03_DRAFT",
                    "template_id": rec.get("template_id"),
                    "source_row_no": row["no"],
                }
            )
        return {"critical": critical, "substantial": substantial}

    # ── Раздел 2–3 (parameter statuses) ───────────────────────────────────────────────────────

    def _buckets(self) -> dict[str, list[str]]:
        """Partition of the catalog parameters (Раздел 2) from the OBJECT rows and the violation groups."""
        out: dict[str, list[str]] = defaultdict(list)
        with_rows = set()
        for f in self.object_rows:
            bucket = (f.get("decision_trace") or {}).get("bucket")
            if not bucket:
                bucket = {
                    "NO_VIOLATION": "CHECKED_OK",
                    "MISSING_DOCUMENT": "NOT_CHECKED_NO_ID"
                    if f.get("protocol_status") == "ID_MISSING"
                    else "NOT_CHECKED_NO_PD_RD",
                }.get(f["violation_label"], "NOT_LOADED_TECH_ERRORS")
            out[bucket].append(f["parameter_code"])
            with_rows.add(f["parameter_code"])
        for p in self.params:
            if p.code not in with_rows:
                violated = any(g["parameter_code"] == p.code for g in self.groups)
                out["CHECKED_OK" if violated else "NOT_LOADED_TECH_ERRORS"].append(p.code)
        return out

    def section2(self, n4: int, n5: int, n6: int) -> dict[str, Any]:
        labels = _labels("ProtocolSummaryRow")
        total = len(self.params)
        buckets = self._buckets()
        shown = [k for k in PARTITION_ORDER if k in ALWAYS_SHOWN or buckets.get(k)]
        counts = [len(buckets.get(k, [])) for k in shown]
        percents, adjusted = T.partition_percents_ex(counts, total)
        rows = [
            {
                "key": "TOTAL_PARAMS",
                "label_ru": labels["TOTAL_PARAMS"],
                "count": total,
                "percent": 100,
                "percent_text": "100%",
            }
        ]
        for key, count, pct in zip(shown, counts, percents, strict=True):
            rows.append(
                {
                    "key": key,
                    "label_ru": labels[key],
                    "count": count,
                    "percent": float(pct),
                    "percent_text": T.percent_text(pct),
                }
            )

        def plain(key: str, count: int) -> dict[str, Any]:
            pct = T.percent_half_up(count, total)
            return {
                "key": key,
                "label_ru": labels[key],
                "count": count,
                "percent": float(pct),
                "percent_text": T.percent_text(pct),
            }

        rows += [
            plain("VIOLATIONS_TOTAL", n4 + n5),
            plain("VIOLATIONS_CRITICAL", n4),
            plain("VIOLATIONS_SUBSTANTIAL", n5),
        ]
        rows.append(plain("AI_SUSPICIONS", n6))
        footnotes = []
        if self.scenario != "FULL":
            footnotes.append(T.SCENARIO_FOOTNOTE.format(scenario=self.scenario))
        if buckets.get("NOT_LOADED_TECH_ERRORS"):
            footnotes.append(TECH_FOOTNOTE)
        for i in adjusted:
            delta = percents[i] - T.percent_half_up(counts[i], total)
            footnotes.append(
                T.ROUNDING_FOOTNOTE.format(sign="+" if delta > 0 else "−", label=labels[shown[i]])
            )
        footnotes.append(T.DISCLAIMER)
        return {"rows": rows, "footnotes": footnotes}

    def _missing_document(self, code: str, stage: str) -> str:
        spec = self._param(code)
        docs = (spec.data.get("source_docs") or {}).get(stage.lower()) or []
        raws = [str(d.get("raw")) for d in docs if d.get("raw")]
        if raws:
            return "; ".join(dict.fromkeys(raws))
        fallback = {"PD": "source_pd", "RD": "source_rd", "ID": "source_id"}[stage]
        return str(spec.data.get(fallback) or f"Документы {STAGE_RU[stage]}")

    def section3(self) -> dict[str, Any]:
        codes = set(self._buckets().get("NOT_CHECKED_NO_ID", []))
        rows = []
        for spec in sorted((self._param(c) for c in codes), key=lambda s: s.param_id):
            rows.append(
                {
                    "no": len(rows) + 1,
                    "parameter_code": spec.code,
                    "parameter_id": spec.param_id,
                    "section_ru": spec.section,
                    "parameter_name": spec.short_name,
                    "missing_document": self._missing_document(spec.code, "ID"),
                }
            )
        return {"count": len(rows), "rows": rows}

    # ── Приложение А ──────────────────────────────────────────────────────────────────────────

    def tz92_tables(self) -> dict[str, Any]:
        actions = _attr("ProtocolParamStatus", "action_ru")
        a1 = []
        for f in sorted(self.object_rows, key=lambda r: r.get("parameter_id") or 999):
            if f["violation_label"] == "NO_VIOLATION":
                continue
            trace = f.get("decision_trace") or {}
            missing = list(trace.get("missing_stages") or [])
            spec = self._param(f["parameter_code"])
            a1.append(
                {
                    "parameter_code": f["parameter_code"],
                    "parameter_name": spec.short_name,
                    "section_ru": spec.section,
                    "protocol_status": f["protocol_status"],
                    "completeness_status": f.get("completeness_status") or "MISSING_EVIDENCE",
                    "completeness_basis": f.get("completeness_basis"),
                    "missing_stage": missing[0] if missing else None,
                    "document": self._missing_document(f["parameter_code"], missing[0]) if missing else None,
                    "reason_ru": f.get("rationale"),
                    "action_ru": actions.get(f["protocol_status"]),
                }
            )
        a2 = []
        for g in self.groups:
            if g["matrix_scope"] != "MATRIX":
                continue
            spec = self._param(g["parameter_code"])
            label = f"{spec.short_name} ({g['parameter_code']})"
            if g.get("hedge_of_group_id"):
                label += " — альтернативный код (страховка выбора параметра)"
            a2.append(
                {
                    "card_ref": g["card_no"],
                    "finding_group_id": g["finding_group_id"],
                    "finding_ids": list(g["finding_ids"]),
                    "parameter_code": g["parameter_code"],
                    "parameter_label": label,
                    "locations": list(g.get("locations") or []),
                    "expected": g.get("pd_value")
                    if g.get("axis", "PD_RD").startswith("PD")
                    else g.get("rd_value"),
                    "actual": g.get("id_value")
                    if g.get("axis", "PD_RD").endswith("ID")
                    else g.get("rd_value"),
                    "deviation_text": (g.get("ext") or {}).get("deviation_text"),
                    "criticality_level": g.get("criticality_level"),
                    "risk_level": g.get("risk_level") or "MEDIUM",
                    "confidence": g.get("confidence") if g.get("confidence") is not None else 0.5,
                    "inspector_status": "PENDING",
                }
            )
        a4 = []
        for f in self.object_rows:
            if f["violation_label"] == "NO_VIOLATION" and f.get("finding_status") == "NEGATIVE_VERIFIED":
                spec = self._param(f["parameter_code"])
                a4.append(
                    {
                        "parameter_code": f["parameter_code"],
                        "parameter_label": f"{spec.short_name} ({f['parameter_code']})",
                        "locations": ["OBJECT"],
                        "decided_by": "SYSTEM",
                        "reason_code": None,
                        "reason_ru": f.get("rationale"),
                        "comment": None,
                        "ai_comment": None,
                        "decided_at": None,
                    }
                )
        method_ru = _labels("DiscoveryMethod")
        a5 = []
        for g in self._free_groups():
            topic = g["parameter_code"].split("-")[1]
            tpl = self.templates.free_topics.get(topic) or {}
            refs = list(tpl.get("norm_refs") or [])
            method = g.get("discovery_method") or "GRAPHIC_DIFF"
            a5.append(
                {
                    "card_ref": g["card_no"],
                    "finding_group_id": g["finding_group_id"],
                    "parameter_code": g["parameter_code"],
                    "method": method,
                    "description": f"{method_ru.get(method, method)}: {self._free_description(g)}",
                    "confidence": g.get("confidence") if g.get("confidence") is not None else 0.5,
                    "normative_base": "; ".join(refs) or None,
                    "evidence_bind_status": g.get("evidence_bind_status"),
                    "inspector_status": "PENDING",
                }
            )
        a5 += [dict(r) for r in self._ai_extra()["a5_rows"]]
        return {
            "a1_completeness": a1,
            "a2_candidates": a2,
            "a3_confirmed": [],
            "a4_negative_verified": a4,
            "a5_hypotheses": a5,
            "banner_ru": T.BANNER_TZ92,
        }

    # ── Приложение Б ──────────────────────────────────────────────────────────────────────────

    def evidence_cards(self) -> list[dict[str, Any]]:
        cards = []
        for g in self.primary:
            spec = None if g["matrix_scope"] == "FREE_SEARCH" else self._param(g["parameter_code"])
            label = (
                f"{spec.short_name} ({g['parameter_code']})"
                if spec
                else f"{self._free_description(g)} ({g['parameter_code']})"
            )
            sources = []
            for ev in g.get("evidence") or g.get("anchor_evidence") or []:
                f = self.ctx.files.get(ev["file_id"])
                src = {
                    "role": ev.get("role"),
                    "stage": ev["stage"],
                    "file_id": ev["file_id"],
                    "file_name": f.name if f else None,
                    "file_sha256": ev.get("file_sha256") or (f.sha256 if f else None),
                    "document_code": ev.get("document_code"),
                    "revision": ev.get("revision"),
                    "approval_status": None,
                    "approval_date": None,
                    "pdf_page_number": ev["pdf_page_number"],
                    "sheet_number": ev.get("document_sheet_number"),
                }
                if ev.get("geometry"):
                    src["geometry"] = ev["geometry"]
                    src["geometry_space"] = ev.get("geometry_space") or "PDF_VISIBLE_ROTATED_TL_V1"
                else:
                    codes = {g["parameter_code"], *(g.get("alt_parameter_codes") or [])}
                    locs = {str(x) for x in g.get("locations") or []} or {"OBJECT"}
                    pairs = [
                        _box_query(v)
                        for v in self._page_values(ev["file_id"], int(ev["pdf_page_number"]))
                        if v.param_code in codes
                        and _stage_of(v) == ev["stage"]
                        and str(v.location or "OBJECT") in locs
                        and v.quality_flag == "OK"
                    ]
                    geom = self._value_geometry(ev["file_id"], int(ev["pdf_page_number"]), pairs)
                    if geom:
                        src["geometry"] = geom
                        src["geometry_space"] = "PDF_VISIBLE_ROTATED_TL_V1"
                if src["role"] is None:
                    src.pop("role")
                sources.append(src)
            app = self._applicable(g)
            expected = g.get("pd_value") if app["PD"] else g.get("rd_value")
            actual = g.get("id_value") if app["ID"] else g.get("rd_value")
            finding_ids = list(g["finding_ids"]) + [
                fid for t in self.twins.get(g["finding_group_id"], []) for fid in t["finding_ids"]
            ]
            cards.append(
                {
                    "card_no": g["card_no"],
                    "finding_group_id": g["finding_group_id"],
                    "finding_ids": finding_ids,
                    "parameter_code": g["parameter_code"],
                    "parameter_label": label,
                    "rule_version": g.get("rule_version") or RULES_VERSION,
                    "locations": list(g.get("locations") or []),
                    "expected_value": expected,
                    "actual_value": actual,
                    "delta": None,
                    "rationale": g.get("rationale"),
                    "risk_level": g.get("risk_level") or "MEDIUM",
                    "review_priority": str(spec.review_priority) if spec else "MEDIUM",
                    "criticality": g.get("criticality"),
                    "approved_change_ref": None,
                    "sources": sources,
                    "inspector": {"status": "PENDING"},
                    "ai_verdict": None,
                    "ai_comment": None,
                }
            )
        cards += self._suspicion_cards()
        return cards

    def _suspicion_cards(self) -> list[dict[str, Any]]:
        cards = []
        for s in self._ai_extra()["suspicions"]:
            expl = s.get("explanation") or {}
            code = str(expl.get("matrix_parameter_code") or "")
            if not code:
                continue
            spec = self._param(code)
            sources = []
            page_values: dict[tuple[str, str, int], list[str]] = {}
            page_raws: dict[tuple[str, str, int], list[str]] = {}
            codes = {code, *(str(c) for c in expl.get("twin_parameter_codes") or [])}
            stage_values: dict[str, str | None] = {}
            for st, clusters in (expl.get("values") or {}).items():
                ordered = sorted(clusters, key=lambda c: (-int(c.get("files") or 0), str(c.get("value"))))
                stage_values[st] = (
                    "; ".join(f"{c['value']} ({_files_ru(int(c.get('files') or 0))})" for c in ordered)
                    or None
                )
                for c in clusters:
                    for m in c.get("mentions") or []:
                        texts = page_values.setdefault((st, m["file_id"], int(m["page"])), [])
                        if str(c["value"]) not in texts:
                            texts.append(str(c["value"]))
                        raws = page_raws.setdefault((st, m["file_id"], int(m["page"])), [])
                        if m.get("raw") and m["raw"] not in raws:
                            raws.append(m["raw"])
            for ev in s.get("evidence") or []:
                f = self.ctx.files.get(ev["file_id"])
                src = {
                    "stage": ev["stage"],
                    "file_id": ev["file_id"],
                    "file_name": f.name if f else None,
                    "file_sha256": ev.get("file_sha256") or (f.sha256 if f else None),
                    "document_code": ev.get("document_code"),
                    "revision": ev.get("revision"),
                    "approval_status": None,
                    "approval_date": None,
                    "pdf_page_number": ev["pdf_page_number"],
                    "sheet_number": ev.get("document_sheet_number"),
                }
                page = int(ev["pdf_page_number"])
                own = [
                    v
                    for v in self._page_values(ev["file_id"], page)
                    if _stage_of(v) == ev["stage"] and v.param_code in codes
                ]
                # The explanation lists at most 8 mentions per value; a page beyond them shows its own values.
                texts = page_values.get((ev["stage"], ev["file_id"], page)) or list(
                    dict.fromkeys(str(getattr(v.value_norm, "value", None) or v.value_raw) for v in own)
                )
                if texts:
                    src["value_text"] = "; ".join(texts)
                if ev.get("geometry"):
                    src["geometry"] = ev["geometry"]
                    src["geometry_space"] = ev.get("geometry_space") or "PDF_VISIBLE_ROTATED_TL_V1"
                else:
                    ctx_of = {v.value_raw: _box_query(v) for v in own}
                    raws = page_raws.get((ev["stage"], ev["file_id"], page)) or list(ctx_of)
                    pairs = [ctx_of.get(r, (r, None)) for r in raws]
                    geom = self._value_geometry(ev["file_id"], page, pairs)
                    if geom:
                        src["geometry"] = geom
                        src["geometry_space"] = "PDF_VISIBLE_ROTATED_TL_V1"
                sources.append(src)
            if not sources:
                continue
            cells = s.get("stage_cells") or {}
            cards.append(
                {
                    "card_no": s["card_ref"],
                    "finding_group_id": None,
                    "finding_ids": [],
                    "parameter_code": code,
                    "parameter_label": f"{spec.short_name} ({code}): противоречие значений",
                    "rule_version": s.get("rule_version"),
                    "locations": [str(expl.get("location") or "OBJECT")],
                    "expected_value": None,
                    "actual_value": None,
                    "delta": None,
                    "rationale": s["description"],
                    "risk_level": "MEDIUM",
                    "review_priority": str(s.get("review_priority") or "MEDIUM"),
                    "criticality": spec.criticality,
                    "approved_change_ref": None,
                    "sources": sources,
                    "inspector": {"status": "PENDING"},
                    "ai_verdict": None,
                    "stage_values": {st: stage_values.get(st) for st in ("PD", "RD", "ID")},
                    "ai_comment": f"ПД: {cells.get('PD', '—')}; РД: {cells.get('RD', '—')}; ИД: {cells.get('ID', '—')}",
                }
            )
        return cards

    # ── Приложение В ──────────────────────────────────────────────────────────────────────────

    def input_registry(self) -> dict[str, Any]:
        cited = {e["file_id"] for c in self.submission.get("checks", []) for e in c.get("evidence", [])}
        read_from_evidence: dict[str, dict[str, Any]] = {}
        for g in self.groups:
            for ev in g.get("evidence") or []:
                read_from_evidence.setdefault(ev["file_id"], ev)
        rows = []
        for f in sorted(self.ctx.files.values(), key=lambda x: x.file_id):
            ev = read_from_evidence.get(f.file_id, {})
            rows.append(
                {
                    "file_id": f.file_id,
                    "file_name": f.name,
                    "stage": f.stage,
                    "manifest_stage": f.manifest_stage,
                    "section": f.section,
                    "document_code": ev.get("document_code"),
                    "revision": ev.get("revision"),
                    "approval_status": None,
                    "pages": f.pdf_pages,
                    "sha256": f.sha256,
                    "local_status": self.local_status.get(f.file_id, f.local_status or "PRESENT"),
                    "used": f.file_id in cited,
                    "exclusion_reason": "; ".join(f.not_citable_reasons) or None,
                }
            )
        return {
            "files": rows,
            "parser_versions": {
                "inspector_compare": COMPARE_VERSION,
                "compare_rules": RULES_VERSION,
                "protocol": PROTOCOL_VERSION,
                "recommendation_templates": (self.templates.sha256 or "params-seed")[:16],
            },
        }

    # ── assemble ──────────────────────────────────────────────────────────────────────────────

    def build(self) -> dict[str, Any]:
        rows4, rows5 = self._violation_rows()
        s6 = self.section6()
        versions = {
            "pipeline_version": str(self.versions.get("pipeline_version") or COMPARE_VERSION),
            "matrix_version": self.params.matrix_version,
            "model_version": RULES_VERSION,
            "code_version": self.versions.get("code_version"),
            "contract_version": contract_version(),
            "engine_versions": {
                "inspector_compare": COMPARE_VERSION,
                "protocol": PROTOCOL_VERSION,
                "matrix_overrides": overrides_summary(self.params.overrides),
            },
        }
        doc: dict[str, Any] = {
            "schema_version": 1,
            "protocol_no": self.protocol_no(),
            "run_id": self.run_id,
            "object": {
                "object_id": self.ctx.object_id,
                "name": self.passport.name,
                "address": self.passport.address,
                "supervision_case_no": self.passport.supervision_case_no,
                "customer": self.passport.customer,
                "contractor": self.passport.contractor,
            },
            "version": self.version,
            "is_final": self.process_status == "FINALIZED",
            "status": "PROTOCOL_FINALIZED" if self.process_status == "FINALIZED" else "IN_VERIFICATION",
            "process_status": self.process_status,
            "generated_at": self.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scenario": self.scenario,
            "scenario_base": self._scenario_base(),
            "upload_status": {s.lower(): _stage_status(s, *self._stage_counts(s)) for s in STAGES},
            "versions": versions,
            "input_manifest_hash": self.ctx.input_manifest_hash,
            "content_sha256": None,
            "header": self.header(),
            "appendix2": {
                "section1_load_status": self.section1(),
                "section2_summary": self.section2(len(rows4), len(rows5), s6["count"]),
                "section3_not_checked_no_id": self.section3(),
                "section4_critical": {"count": len(rows4), "rows": rows4},
                "section5_substantial": {"count": len(rows5), "rows": rows5},
                "section6_ai_suspicions": s6,
                "section7_resolution": self.section7(rows4, rows5),
                "footnotes": [],
            },
            "tz92_tables": self.tz92_tables(),
            "evidence_cards": self.evidence_cards(),
            "input_registry": self.input_registry(),
            "signature": None,
            "submission_checks": list(self.submission.get("checks", [])),
            "ext": {
                "protocol_version": PROTOCOL_VERSION,
                "recommendation_templates": self.templates.source,
                "hedge_twins": {k: [t["parameter_code"] for t in v] for k, v in self.twins.items()},
            },
        }
        doc["content_sha256"] = content_sha256(doc)
        return doc


def content_sha256(doc: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON without the volatile fields (dates, protocol number, run id, the hash itself and
    the signature): same inputs and versions give the same hash (04 §3.6)."""
    body = {
        k: v
        for k, v in doc.items()
        if k not in {"generated_at", "content_sha256", "signature", "protocol_no", "run_id"}
    }
    header = dict(body.get("header") or {})
    header.pop("generated_at_ru", None)
    header.pop("title", None)
    body["header"] = header
    return sha256_json(body)


def build_protocol(
    ctx: ObjectContext,
    groups: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    submission: Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    return ProtocolBuilder(ctx, groups, findings, submission, **kwargs).build()


def counts_by_label(rows: Iterable[Mapping[str, Any]]) -> Counter[str]:
    return Counter(r["violation_label"] for r in rows)
