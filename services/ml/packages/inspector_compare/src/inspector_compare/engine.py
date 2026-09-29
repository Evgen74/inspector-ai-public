"""`compare` for one object: comparators → element-family router → finding groups → atomic findings → the
132-row precedence (97 §2.5–2.10, 93 §2.4–2.8).

Pipeline:

1. room observations from the layout artifacts (``observe``);
2. per family and axis, the room comparators (``comparators``): violations, context (additions, renumbering),
   abstentions (room not covered);
3. the element-family router (seed ``change_matrix_map``): family × DiscrepancyType → catalog code or
   FREE-<TOPIC>; non-emitting routes (improvements, additions) are context, never findings (directional triggers);
4. grouping by (axis, code, comparison result, family): one group per discrepancy, one atomic finding per room
   with the exact printed token («012»); a key (code, room) is emitted once (axis priority PD↔RD first);
5. the anchor-page rule: one page per stage per group — among the pages depicting the group's rooms, the page that
   depicts most rooms of the whole finding (axis × code × family: the organizers anchor both groups of «пункт 3»
   on RD p18, so room 314, drawn on p20, is anchored on p18 with 147/198/140/142), then most of the group's own
   rooms; per-room pages are kept in ``location_pages``;
6. FREE-* groups (router + AG-07 hook), evidence-bound only, capped, numbered per group (FREE-HEATING-001);
7. the bounded top-2 code hedge (runner-up p ≥ 0.1, hedges ≤ 20 % of emitted critical checks);
8. ids, evidence-card numbers in protocol order, recommendations;
9. the 132-row precedence: one OBJECT row per catalog parameter without a violation row.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from inspector_common.contracts.loader import enum_mappings, validation_errors
from inspector_common.contracts.status import violation_protocol_status
from inspector_common.jsonlog import get_logger
from inspector_common.params import ChangeMap, ParamRegistry, Route, load_change_map, load_params
from inspector_compare.comparators import (
    AMBIGUOUS_ATTRIBUTION,
    ANCHOR_PRESENT,
    AXIS_STAGES,
    MARK_ELSEWHERE,
    RoomDiff,
    compare_family,
)
from inspector_compare.config import CompareConfig
from inspector_compare.disciplines import plan_mark_of_name
from inspector_compare.materials import MATERIAL_KEYS, MarkFinding, compare_materials
from inspector_compare.objectctx import ObjectContext
from inspector_compare.observe import Observations, PageRef
from inspector_compare.precedence import ParamOutcome, evaluate_all
from inspector_compare.recommendations import TemplateSet, load_templates, render_texts
from inspector_compare.specitems import spec_diffs
from inspector_compare.specparams import spec_param_diffs
from inspector_compare.tags import family_specs
from inspector_compare.tolerance import id_value_text, tolerance_diffs
from inspector_compare.valuecmp import ValueDiff, compare_values, delta_text, format_value
from inspector_compare.values import natural_key, render_template, rooms_phrase
from inspector_compare.version import RULES_VERSION

log = get_logger(__name__)

CR_ABBR = {
    "CONFIGURATION_MISMATCH": "CFG",
    "MISSING_DESIGN_ELEMENT": "MISS",
    "VALUE_MISMATCH": "VAL",
    "MATERIAL_SUBSTITUTION": "MAT",
    "EXTRA_ELEMENT": "EXTRA",
    "TOLERANCE_EXCEEDED": "TOL",
}
AXIS_ID = {"PD_RD": "PDRD", "RD_ID": "RDID", "PD_ID": "PDID", "NORM_ID": "NORMID"}
PAIRWISE_DOCUMENT_STATUS = {
    "PD_RD": "PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK",
    "PD_ID": "PD_ID_AVAILABLE_RD_NOT_REQUIRED_FOR_PAIRWISE_CHECK",
    "RD_ID": "RD_ID_AVAILABLE_PD_NOT_REQUIRED_FOR_PAIRWISE_CHECK",
}
STAGE_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}
FREE_CRITICALITY = "Существенное (предписание) — требует утверждения"


# ── data ──────────────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class GroupDraft:
    axis: str
    family: str | None
    code: str  # catalog code, or «FREE-<TOPIC>» until numbered
    free_topic: str | None
    route: Route | None
    comparison_result: str
    discrepancy_type: str
    mapping_status: str
    diffs: list[RoomDiff] = field(default_factory=list)
    source: str = "ROOM_COMPARATOR"
    external: dict[str, Any] | None = None
    locations: list[str] = field(default_factory=list)
    anchors: dict[str, PageRef] = field(default_factory=dict)
    location_pages: dict[str, dict[str, PageRef]] = field(default_factory=dict)
    confidence: float = 0.0
    values: dict[str, str | None] = field(default_factory=dict)
    element_noun: str | None = None
    runner_up: str | None = None
    runner_up_p: float = 0.0
    hedge_kind: str | None = None
    hedge_of: GroupDraft | None = None
    group_id: str = ""
    card_no: str | None = None
    finding_ids: list[str] = field(default_factory=list)

    @property
    def is_free(self) -> bool:
        return self.code.startswith("FREE-")

    @property
    def expected_stage(self) -> str:
        return AXIS_STAGES[self.axis][0]

    @property
    def actual_stage(self) -> str:
        return AXIS_STAGES[self.axis][1]

    def diff_for(self, location: str) -> RoomDiff | None:
        return next((d for d in self.diffs if d.room == location), None)


@dataclass(slots=True)
class CompareResult:
    object_id: str
    groups: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    outcomes: list[ParamOutcome]
    trace: dict[str, Any]
    drafts: list[GroupDraft] = field(default_factory=list)

    @property
    def violation_findings(self) -> list[dict[str, Any]]:
        return [f for f in self.findings if f["violation_label"] == "VIOLATION_PRESENT"]


FreeHook = Callable[..., list[dict[str, Any]]]


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────


def _slug(text: str, limit: int = 24) -> str:
    slug = re.sub(r"[^0-9A-Za-zА-ЯЁа-яё.\-]+", "_", text).strip("_")
    if len(slug) <= limit and slug:
        return slug
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8].upper()


def _basis_key(route: Route | None) -> str:
    if route is None:
        return "ANALOGY"
    return (route.basis or "ANALOGY").split(":", 1)[0].upper()


def _is_approved_critical(criticality: str | None) -> bool:
    return (
        bool(criticality)
        and criticality.startswith("Критическое")
        and "требует утверждения" not in criticality
    )


def _sheet(obs: Observations, ref: PageRef | None) -> str | int | None:
    if ref is None:
        return None
    info = obs.pages.get(ref)
    return None if info is None else info.sheet_number


def _labels(counts: Counter[str]) -> str:
    items = []
    for label in sorted(counts, key=natural_key):
        n = counts[label]
        items.append(label if n == 1 else f"{label} ×{n}")
    return ", ".join(items)


# ── the engine ────────────────────────────────────────────────────────────────────────────────────


class CompareEngine:
    def __init__(
        self,
        ctx: ObjectContext,
        cfg: CompareConfig,
        *,
        params: ParamRegistry | None = None,
        change_map: ChangeMap | None = None,
        templates: TemplateSet | None = None,
        run_id: str | None = None,
        free_hook: FreeHook | None = None,
        config_hash: str | None = None,
    ) -> None:
        self.ctx = ctx
        self.config_hash = config_hash
        self.cfg = cfg
        self.params = params or load_params()
        self.change_map = change_map or load_change_map()
        self.templates = templates or load_templates()
        self.run_id = run_id
        self.free_hook = free_hook
        self.specs = family_specs(self.change_map.document["element_families"])
        self.family_labels = {
            f["family"]: f.get("label_ru") for f in self.change_map.document["element_families"]
        }
        self.obs = Observations(ctx, cfg, self.specs)
        self.context: list[dict[str, Any]] = []
        self.abstained: list[dict[str, Any]] = []
        self.compared: dict[str, int] = defaultdict(int)  # param code → rooms compared (verified coverage)
        # param code → stages whose printed value was compared (labelled prose values of parameters whose source
        # discipline has no file of its own, e.g. РД «Общие данные» of an АР/КЖ sheet set): such a stage is available
        self.value_stages: dict[str, set[str]] = defaultdict(set)
        self.value_equal: dict[str, dict[str, Any]] = defaultdict(dict)  # code → stage → agreeing value
        self.room_outcomes: Counter[str] = Counter()
        self.deactivated: Counter[str] = Counter()

    # 1–3 ─ comparators and router ─────────────────────────────────────────────────────────────

    def _emitting_codes(self, family: str) -> set[str]:
        fam = self.change_map.families.get(family) or {}
        return {
            str(r["parameter_code"])
            for r in fam.get("routes", [])
            if r.get("emit") and r.get("parameter_code") and not str(r["parameter_code"]).startswith("FREE-")
        }

    def _criticality_of(self, code: str) -> tuple[str, str]:
        if code.startswith("FREE-"):
            return FREE_CRITICALITY, "SUBSTANTIAL_ORDER"
        spec = self.params.get(code)
        return spec.criticality, str(spec.criticality_level)

    def run_comparators(self) -> list[GroupDraft]:
        groups: dict[tuple[str, str, str, str], GroupDraft] = {}
        for family in sorted(self.cfg.families):
            if family not in self.specs:
                self.abstained.append({"family": family, "reason": "FAMILY_NOT_IN_CHANGE_MAP"})
                continue
            for axis in self.cfg.axes:
                for diff in compare_family(self.obs, family, axis, self.cfg):
                    self.room_outcomes[f"{family}:{axis}:{diff.outcome}"] += 1
                    if diff.outcome == "UNRESOLVED" and diff.note == ANCHOR_PRESENT:
                        self.abstained.append(
                            {
                                "family": family,
                                "axis": axis,
                                "location": diff.room,
                                "reason": "AMBIGUOUS_VALUE",
                                "detail_ru": (
                                    f"Помещение {diff.room}: марки {_labels(diff.expected)} на листе "
                                    f"{STAGE_RU[diff.actual_stage]} не подписаны, но элемент показан "
                                    "(например, «М.О.») — отсутствие не доказано"
                                ),
                            }
                        )
                        continue
                    if diff.outcome == "UNRESOLVED" and diff.note == MARK_ELSEWHERE:
                        self.abstained.append(
                            {
                                "family": family,
                                "axis": axis,
                                "location": diff.room,
                                "reason": "AMBIGUOUS_VALUE",
                                "detail_ru": (
                                    f"Помещение {diff.room}: марки {_labels(diff.expected - diff.actual)} есть на том же "
                                    f"листе {STAGE_RU[diff.actual_stage]}, но отнесены к другому помещению — "
                                    "расхождение в привязке, а не в проекте"
                                ),
                            }
                        )
                        continue
                    if diff.outcome == "UNRESOLVED":
                        self.abstained.append(
                            {
                                "family": family,
                                "axis": axis,
                                "location": diff.room,
                                "reason": "ELEMENT_KEY_UNRESOLVED",
                                "detail_ru": f"Помещение {diff.room} не найдено на листах {STAGE_RU[diff.actual_stage]} этой системы",
                            }
                        )
                        continue
                    if diff.note == AMBIGUOUS_ATTRIBUTION:
                        self.abstained.append(
                            {
                                "family": family,
                                "axis": axis,
                                "location": diff.room,
                                "reason": "AMBIGUOUS_VALUE",
                                "detail_ru": (
                                    f"Помещение {diff.room}: марки, привязанные сразу к нескольким помещениям, "
                                    "меняют вывод; без них расхождение не подтверждается"
                                ),
                            }
                        )
                        continue
                    if diff.outcome in (
                        "EQUAL",
                        "RENUMBERED",
                        "RELOCATED",
                        "ELEMENT_MISSING",
                        "CONFIGURATION_CHANGED",
                    ):
                        for code in self._emitting_codes(family):
                            self.compared[code] += 1
                    if not diff.is_violation:
                        if diff.outcome in ("ELEMENT_ADDED", "RENUMBERED", "RELOCATED"):
                            self._context(
                                diff,
                                None,
                                "добавления, перенумерация и перенос в другое помещение — контекст, не нарушение "
                                "(97 §2.10)",
                            )
                        continue
                    try:
                        route = self.change_map.route(family, diff.discrepancy_type)
                    except KeyError:
                        self._context(diff, None, "нет маршрута в карте изменений")
                        continue
                    if not route.emit or not route.parameter_code:
                        self._context(
                            diff, route, route.data.get("reason") or "маршрут без выгрузки (контекст)"
                        )
                        continue
                    code = str(route.parameter_code)
                    _, level = self._criticality_of(code)
                    threshold = (
                        self.cfg.min_confidence_critical
                        if level == "CRITICAL_SUSPEND"
                        else self.cfg.min_confidence_substantial
                    )
                    if diff.confidence < threshold:
                        self.abstained.append(
                            {
                                "family": family,
                                "axis": axis,
                                "location": diff.room,
                                "reason": "LOW_CONFIDENCE",
                                "confidence": diff.confidence,
                            }
                        )
                        continue
                    cr = str(
                        route.comparison_result
                        or enum_mappings()["discrepancy_to_comparison_result"].get(diff.discrepancy_type)
                    )
                    key = (axis, code, cr, family)
                    g = groups.get(key)
                    if g is None:
                        g = groups[key] = GroupDraft(
                            axis=axis,
                            family=family,
                            code=code,
                            free_topic=code.removeprefix("FREE-") if code.startswith("FREE-") else None,
                            route=route,
                            comparison_result=cr,
                            discrepancy_type=diff.discrepancy_type,
                            mapping_status=str(
                                route.parameter_mapping_status or "PROVISIONAL_DOMAIN_MAPPING"
                            ),
                        )
                    g.diffs.append(diff)
        return list(groups.values())

    def run_value_comparators(self) -> list[GroupDraft]:
        """Extracted values (AG-02C) per matrix rule: one group per (axis, code, sub-check, location)."""
        drafts: list[GroupDraft] = []
        mapping = enum_mappings()["discrepancy_to_comparison_result"]
        plain = [v for v in self.ctx.values if v.fact_key not in MATERIAL_KEYS]
        mat_diffs, mark_findings = compare_materials(self.ctx.values, self.cfg.axes)
        drafts.extend(self._mark_drafts(mark_findings, mapping))
        tol_diffs, verdicts = tolerance_diffs(self.ctx.values)
        for v in verdicts:
            self.room_outcomes[
                f"TOLERANCE:NORM_ID:{'VIOLATION' if v.worst is not None else (v.reason or 'EQUAL')}"
            ] += 1
            if v.reason is not None:
                self.abstained.append(
                    {
                        "code": v.code,
                        "axis": "NORM_ID",
                        "location": f"{v.file_id} с. {v.page_no}",
                        "reason": v.reason,
                    }
                )
        spec_items = spec_diffs(self.ctx.values, self.ctx.files) if "PD_RD" in self.cfg.axes else []
        spec_items += spec_param_diffs(self.ctx.values, self.ctx.files, self.cfg.axes)
        plain_diffs = compare_values(plain, self.params, self.cfg.axes)
        for diff in [*plain_diffs, *mat_diffs, *tol_diffs, *spec_items]:
            self.room_outcomes[f"VALUE:{diff.axis}:{diff.outcome}"] += 1
            if diff.outcome in ("EQUAL", "IMPROVEMENT", "VIOLATION"):
                self.compared[diff.code] += 1
                if (
                    diff.expected is not None
                    and diff.actual is not None
                    and (
                        diff.expected.fact_key in ("pz.value", "tx.value")
                        or str(diff.expected.fact_key or "").startswith("ppm.")
                    )
                ):
                    self.value_stages[diff.code] |= {diff.expected_stage, diff.actual_stage}
                    if diff.outcome == "EQUAL":
                        self.value_equal[diff.code].setdefault(diff.expected_stage, diff.expected)
                        self.value_equal[diff.code].setdefault(diff.actual_stage, diff.actual)
            if diff.outcome == "IMPROVEMENT":
                self.context.append(
                    {
                        "family": None,
                        "code": diff.code,
                        "axis": diff.axis,
                        "location": diff.room,
                        "outcome": "IMPROVEMENT",
                        "expected": format_value(diff.expected),
                        "actual": format_value(diff.actual),
                        "reason_ru": "улучшение по направленному триггеру — не нарушение (97 §2.10)",
                    }
                )
                continue
            if diff.outcome == "ABSTAIN":
                self.abstained.append(
                    {"code": diff.code, "axis": diff.axis, "location": diff.room, "reason": diff.reason}
                )
                continue
            if not diff.is_violation or diff.discrepancy_type is None:
                continue
            _, level = self._criticality_of(diff.code)
            threshold = (
                self.cfg.min_confidence_critical
                if level == "CRITICAL_SUSPEND"
                else self.cfg.min_confidence_substantial
            )
            if diff.confidence < threshold:
                self.abstained.append(
                    {
                        "code": diff.code,
                        "axis": diff.axis,
                        "location": diff.room,
                        "reason": "LOW_CONFIDENCE",
                        "confidence": diff.confidence,
                    }
                )
                continue
            g = GroupDraft(
                axis=diff.axis,
                family=None,
                code=diff.code,
                free_topic=None,
                route=None,
                comparison_result=str(mapping.get(diff.discrepancy_type, "VALUE_MISMATCH")),
                discrepancy_type=diff.discrepancy_type,
                mapping_status="SOURCE_MATRIX",
                diffs=[diff],  # type: ignore[list-item]
                source="VALUE_COMPARATOR",
            )
            values: dict[str, str | None] = {"pd_value": None, "rd_value": None, "id_value": None}
            values[f"{diff.expected_stage.lower()}_value"] = format_value(diff.expected)
            values[f"{diff.actual_stage.lower()}_value"] = format_value(diff.actual)
            if diff.axis == "NORM_ID":  # the ИД sheet states both the tolerance and the fact
                values["id_value"] = id_value_text(diff)
            if diff.texts:
                values.update(diff.texts)
            g.values = values
            drafts.append(g)
        return drafts

    def _mark_drafts(self, marks: list[MarkFinding], mapping: Mapping[str, Any]) -> list[GroupDraft]:
        """F/W marks lower in ИД than in the design → one FREE-STRUCTURE group per family (evidence-bound)."""
        drafts = []
        for m in marks:
            self.room_outcomes[f"MATERIAL_MARK:{m.axis}:VIOLATION"] += 1
            g = GroupDraft(
                axis=m.axis,
                family=None,
                code="FREE-STRUCTURE",
                free_topic="STRUCTURE",
                route=None,
                comparison_result=str(mapping.get("CLASS_DOWNGRADED", "MATERIAL_SUBSTITUTION")),
                discrepancy_type="CLASS_DOWNGRADED",
                mapping_status="MATRIX_GAP_CONFIRMED",
                diffs=[m.diffs[0]],  # type: ignore[list-item]
                source="VALUE_COMPARATOR",
            )
            g.values = m.values()
            drafts.append(g)
        return drafts

    def _context(self, diff: RoomDiff, route: Route | None, reason: str) -> None:
        self.context.append(
            {
                "family": diff.family,
                "axis": diff.axis,
                "location": diff.room,
                "outcome": diff.outcome,
                "expected": _labels(diff.expected),
                "actual": _labels(diff.actual),
                "route_basis": route.basis if route else None,
                "reason_ru": reason,
            }
        )

    # 4 ─ dedupe keys ─────────────────────────────────────────────────────────────────────────

    def dedupe(self, groups: list[GroupDraft]) -> list[GroupDraft]:
        """One finding per key (code, room): the first axis wins, then the higher confidence."""
        axis_rank = {a: i for i, a in enumerate(self.cfg.axes)}
        entries = []
        for g in groups:
            for d in g.diffs:
                entries.append((axis_rank.get(g.axis, 99), -d.confidence, g.code, d.room, id(g), g, d))
        taken: set[tuple[str, str]] = set()
        keep: dict[int, list[RoomDiff]] = defaultdict(list)
        for _, _, code, room, gid, g, d in sorted(entries, key=lambda e: e[:5]):
            if (code, room) in taken:
                self.context.append(
                    {
                        "family": g.family,
                        "axis": g.axis,
                        "location": room,
                        "outcome": d.outcome,
                        "reason_ru": f"ключ ({code}, {room}) уже выявлен по более приоритетной оси",
                    }
                )
                continue
            taken.add((code, room))
            keep[gid].append(d)
        out = []
        for g in groups:
            g.diffs = sorted(keep.get(id(g), []), key=lambda d: natural_key(d.room))
            if g.diffs:
                g.locations = [d.room for d in g.diffs]
                g.confidence = round(min(d.confidence for d in g.diffs), 3)
                out.append(g)
        return out

    # 5 ─ anchor pages ────────────────────────────────────────────────────────────────────────

    def _page_strength(self, diff: RoomDiff, ref: PageRef, side: str) -> float:
        if isinstance(diff, ValueDiff):
            return 1.0
        if side == "expected":
            counts = diff.expected_obs.elements.get(ref) if diff.expected_obs else None
            return float(sum(counts.values())) if counts else 0.0
        strength = 0.0
        if diff.outcome == "CONFIGURATION_CHANGED" and diff.actual_obs is not None:
            page_counts = diff.actual_obs.elements.get(ref, Counter())
            strength += float(sum(((page_counts - diff.expected) + (diff.expected - page_counts)).values()))
        info = self.obs.pages.get(ref)
        if info is not None and diff.room in info.revision_cloud_rooms:
            strength += 0.5
        return strength

    def _purity(self, ref: PageRef, family: str | None) -> float:
        """Share of the page's system layers (CAD layers naming any configured topic) that belong to the family's
        topic: a ventilation plan (4/4) is a better ventilation anchor than a heating plan showing the units."""
        info = self.obs.pages.get(ref)
        spec = self.obs.specs.get(family or "")
        if info is None or spec is None or not info.layers:
            return 0.0
        topics = {t: re.compile(p) for t, p in self.cfg.topic_page_patterns.items()}
        folded = [layer.casefold().replace("ё", "е") for layer in info.layers]
        systemic = [layer for layer in folded if any(p.search(layer) for p in topics.values())]
        own = topics.get(spec.topic or "")
        if not systemic or own is None:
            return 0.0
        return sum(1 for layer in systemic if own.search(layer)) / len(systemic)

    def _best_page(
        self,
        pages: Mapping[PageRef, set[str]],
        strength: Mapping[PageRef, float],
        family: str | None,
        side: str = "expected",
        outcome: str | None = None,
        pool: Mapping[PageRef, set[str]] | None = None,
    ) -> PageRef | None:
        """Anchor choice (93 §2.8) among the pages depicting the group's rooms: most rooms of the finding first
        (``pool``: every group of the same axis × code × family, see ``CompareConfig.anchor_scope``), then most of
        the group's own rooms; then, on the expected side, the page showing most of the expected elements; on the
        actual side, the general plan (most rooms drawn) of the family's own system (layer purity) before the
        strength of the difference; then the sheet title, then page order."""
        if not pages:
            return None

        def key(ref: PageRef) -> tuple[Any, ...]:
            info = self.obs.pages.get(ref)
            rooms = len(info.rooms_drawn) if info else 0
            title = self.obs.title_score(ref, family) if family else 0
            purity = self._purity(ref, family)
            n, s = -len(pages[ref]), -strength.get(ref, 0.0)
            n_pool = -len(pages[ref] | (pool.get(ref, set()) if pool else set()))
            if side == "expected":
                return (n_pool, n, s, -purity, -title, ref.file_id, ref.page)
            if outcome == "ELEMENT_MISSING":
                return (n_pool, n, s, -purity, -rooms, -title, ref.file_id, ref.page)
            return (n_pool, n, -purity, -rooms, s, -title, ref.file_id, ref.page)

        return min(pages, key=key)

    def _side_pages(
        self, g: GroupDraft, side: str
    ) -> tuple[dict[PageRef, set[str]], dict[PageRef, float], dict[str, dict[PageRef, float]]]:
        """Pages of one side depicting the group's rooms: rooms per page, strength per page, per room."""
        pages: dict[PageRef, set[str]] = defaultdict(set)
        strength: dict[PageRef, float] = defaultdict(float)
        per_loc: dict[str, dict[PageRef, float]] = defaultdict(dict)
        for d in g.diffs:
            refs = d.expected_pages() if side == "expected" else d.actual_pages()
            for ref in refs:
                s = self._page_strength(d, ref, side)
                pages[ref].add(d.room)
                strength[ref] += s
                per_loc[d.room][ref] = s
        return pages, strength, per_loc

    def anchor_pools(
        self, groups: Iterable[GroupDraft]
    ) -> dict[tuple[str, str, str | None], dict[str, dict[PageRef, set[str]]]]:
        """Rooms per page of every finding (axis × code × family) and side, for ``anchor_scope == "system"``."""
        pools: dict[tuple[str, str, str | None], dict[str, dict[PageRef, set[str]]]] = {}
        if self.cfg.anchor_scope != "system":
            return pools
        for g in groups:
            pool = pools.setdefault((g.axis, g.code, g.family), {"expected": {}, "actual": {}})
            for side in ("expected", "actual"):
                for ref, rooms in self._side_pages(g, side)[0].items():
                    pool[side].setdefault(ref, set()).update(rooms)
        return pools

    def choose_anchors(
        self, g: GroupDraft, pool: Mapping[str, Mapping[PageRef, set[str]]] | None = None
    ) -> None:
        """One anchor page per stage (93 §2.8): among the pages depicting the group's rooms, the page covering
        most rooms of the finding (``pool``), then most of the group's own rooms."""
        for side, stage in (("expected", g.expected_stage), ("actual", g.actual_stage)):
            pages, strength, per_loc = self._side_pages(g, side)
            outcome = g.diffs[0].outcome if g.diffs else None
            anchor = self._best_page(pages, strength, g.family, side, outcome, (pool or {}).get(side))
            if anchor is not None:
                g.anchors[stage] = anchor
            for loc, loc_pages in per_loc.items():
                best = self._best_page({r: {loc} for r in loc_pages}, loc_pages, g.family, side, outcome)
                if best is not None:
                    g.location_pages.setdefault(loc, {})[stage] = best

    # 6 ─ values and texts ────────────────────────────────────────────────────────────────────

    def _template_values(self, g: GroupDraft, location: str | None) -> dict[str, Any]:
        exp_ref = g.anchors.get(g.expected_stage)
        act_ref = g.anchors.get(g.actual_stage)
        act_info = self.obs.pages.get(act_ref) if act_ref else None
        exp_info = self.obs.pages.get(exp_ref) if exp_ref else None
        return {
            "pd_sheet": _sheet(self.obs, exp_ref),
            "rd_sheet": _sheet(self.obs, act_ref),
            "rd_plan_mark": (act_info.plan_mark if act_info else None) or self._name_mark(act_ref),
            "pd_plan_mark": (exp_info.plan_mark if exp_info else None) or self._name_mark(exp_ref),
            "location": location if location is not None else ", ".join(g.locations),
        }

    def _name_mark(self, ref: PageRef | None) -> str | None:
        """The марка of the шифр in the file name when no title block gave one (display only)."""
        info = self.ctx.files.get(ref.file_id) if ref is not None else None
        return plan_mark_of_name(info.relative_path) if info is not None else None

    def _render_values(self, g: GroupDraft, location: str | None) -> dict[str, str | None]:
        templates = (g.route.data.get("value_templates") if g.route else None) or {}
        vals = self._template_values(g, location)
        exp_text = render_template(templates.get("pd"), vals)
        act_text = render_template(templates.get("rd"), vals)
        if g.axis != "PD_RD":
            exp_label, act_label = STAGE_RU[g.expected_stage], STAGE_RU[g.actual_stage]
            exp_text = exp_text.replace(" ПД", f" {exp_label}") if exp_text else exp_text
            act_text = act_text.replace(" РД", f" {act_label}") if act_text else act_text
        out: dict[str, str | None] = {"pd_value": None, "rd_value": None, "id_value": None}
        out[f"{g.expected_stage.lower()}_value"] = exp_text
        out[f"{g.actual_stage.lower()}_value"] = act_text
        return out

    def _element_noun(self, g: GroupDraft) -> str | None:
        fam_routes = (self.change_map.families.get(g.family or "") or {}).get("routes", [])
        for r in fam_routes:
            tpl = (r.get("value_templates") or {}).get("pd") or ""
            m = re.match(r"^(.+?) предусмотрен", tpl)
            if m and "{" not in m.group(1):
                return m.group(1)
        return self.family_labels.get(g.family or "")

    @staticmethod
    def _where(g: GroupDraft) -> str:
        """Location phrase: rooms «пом. 012, 014»; element families as printed («Сваи»); the object."""
        if g.locations == ["OBJECT"]:
            return "объект в целом"
        first = g.diffs[0] if g.diffs else None
        if isinstance(first, ValueDiff) and first.location_type == "ELEMENT":
            return ", ".join(g.locations)
        return rooms_phrase(g.locations)

    def _title(self, g: GroupDraft) -> str:
        where = self._where(g)
        if g.source == "VALUE_COMPARATOR" and g.is_free:
            exp = g.values.get(g.expected_stage.lower() + "_value")
            act = g.values.get(g.actual_stage.lower() + "_value")
            return f"Марки бетона по морозостойкости/водонепроницаемости понижены: {STAGE_RU[g.expected_stage]} {exp} → {STAGE_RU[g.actual_stage]} {act} ({where})"
        if g.source == "VALUE_COMPARATOR" and g.axis == "NORM_ID":
            spec = self.params.get(g.code)
            return f"{spec.short_name}: отклонение по исполнительной схеме {g.values.get('id_value')} (ИД)"
        if g.source == "VALUE_COMPARATOR":
            spec = self.params.get(g.code)
            return f"{spec.short_name}: {STAGE_RU[g.expected_stage]} {g.values.get(g.expected_stage.lower() + '_value')} → {STAGE_RU[g.actual_stage]} {g.values.get(g.actual_stage.lower() + '_value')} ({where})"
        noun = g.element_noun or self.family_labels.get(g.family or "") or g.code
        if g.comparison_result == "MISSING_DESIGN_ELEMENT":
            return f"{noun}: предусмотрено {STAGE_RU[g.expected_stage]}, отсутствует в {STAGE_RU[g.actual_stage]} ({where})"
        if g.comparison_result == "CONFIGURATION_MISMATCH":
            label = (self.family_labels.get(g.family or "") or noun).lower()
            return f"Изменена конфигурация: {label} ({where})"
        return f"{noun}: расхождение {STAGE_RU[g.expected_stage]}↔{STAGE_RU[g.actual_stage]} ({where})"

    def _rationale(self, g: GroupDraft) -> str:
        parts = []
        for d in g.diffs[:6]:
            exp_ref = g.location_pages.get(d.room, {}).get(g.expected_stage)
            act_ref = g.location_pages.get(d.room, {}).get(g.actual_stage)

            def where(ref: PageRef | None) -> str:
                if ref is None:
                    return ""
                sheet = _sheet(self.obs, ref)
                return f" ({ref.file_id}, с. {ref.page}" + (f", л. {sheet})" if sheet is not None else ")")

            exp_stage, act_stage = STAGE_RU[g.expected_stage], STAGE_RU[g.actual_stage]
            room = self._room_label(d.room)
            if isinstance(d, ValueDiff) and d.axis == "NORM_ID":
                parts.append(
                    f"исполнительная схема{where(act_ref)}: допуск на листе {format_value(d.expected)}, "
                    f"наибольшее отклонение {id_value_text(d)}"
                )
                continue
            if isinstance(d, ValueDiff):
                exp_text = (d.texts or {}).get(f"{d.expected_stage.lower()}_value") or format_value(
                    d.expected
                )
                act_text = (d.texts or {}).get(f"{d.actual_stage.lower()}_value") or format_value(d.actual)
                if d.mode == "SPEC_ITEM":
                    q = d.expected.value_norm.qualifiers or {} if d.expected else {}
                    exp_text = f"{exp_text} (спецификация, поз. {q.get('position')})"
                parts.append(
                    f"{d.room if d.room != 'OBJECT' else 'объект'}: {exp_stage}{where(exp_ref)} — {exp_text}; "
                    f"{act_stage}{where(act_ref)} — {act_text}"
                )
                continue
            if d.outcome == "ELEMENT_MISSING":
                if d.mode == "PRESENCE":
                    text = f"{room}: {exp_stage}{where(exp_ref)} предусматривает, {act_stage}{where(act_ref)} — отсутствует"
                else:
                    text = f"{room}: {exp_stage}{where(exp_ref)} — {_labels(d.expected)}; {act_stage}{where(act_ref)} — нет"
            else:
                text = f"{room}: {exp_stage}{where(exp_ref)} — {_labels(d.expected)}; {act_stage}{where(act_ref)} — {_labels(d.actual)}"
            if d.revision_labels:
                text += f"; зона облака изменений {', '.join(d.revision_labels)}"
            parts.append(text)
        more = f"; и ещё {len(g.diffs) - 6}" if len(g.diffs) > 6 else ""
        lead = "Сравнение значений: " if g.source == "VALUE_COMPARATOR" else "Сравнение по помещениям: "
        return lead + "; ".join(parts) + more + "."

    def _room_label(self, room: str) -> str:
        """«пом. 147 (Лаборантская тип АВ)» when the room index and explications name the room (``room_name``)."""
        name = self.obs.room_name(room)
        return f"пом. {room} ({name})" if name else f"пом. {room}"

    # 7 ─ FREE groups ─────────────────────────────────────────────────────────────────────────

    def collect_free(self, groups: list[GroupDraft]) -> list[GroupDraft]:
        """Router FREE groups plus AG-07's (hook), evidence-bound only, capped and numbered per group."""
        free = [g for g in groups if g.is_free]
        matrix = [g for g in groups if not g.is_free]
        taken = {(g.free_topic, loc) for g in free for loc in g.locations}
        for ext in self._external_free():
            topic = str(ext["parameter_code"]).split("-")[1]
            locs = [loc for loc in ext["locations"] if (topic, loc) not in taken]
            if not locs:
                continue
            g = GroupDraft(
                axis=str(ext.get("axis") or "PD_RD"),
                family=None,
                code=f"FREE-{topic}",
                free_topic=topic,
                route=None,
                comparison_result=str(ext["comparison_result"]),
                discrepancy_type=str(ext.get("discrepancy_type") or "ELEMENT_MISSING"),
                mapping_status="MATRIX_GAP_CONFIRMED",
                source="AG07_HOOK",
                external=ext,
                locations=sorted(locs, key=natural_key),
                confidence=float(ext.get("confidence") or 0.5),
            )
            for ev in ext.get("anchor_evidence") or []:
                g.anchors[str(ev["stage"])] = PageRef(
                    str(ev["stage"]), str(ev["file_id"]), int(ev["pdf_page_number"])
                )
            g.values = {k: ext.get(k) for k in ("pd_value", "rd_value", "id_value")}
            g.element_noun = ext.get("element_noun")
            free.append(g)
            taken.update((topic, loc) for loc in g.locations)
        bound = []
        for g in free:
            if g.expected_stage in g.anchors and g.actual_stage in g.anchors and g.locations:
                bound.append(g)
            else:
                self.abstained.append(
                    {"code": g.code, "locations": g.locations, "reason": "FREE_NOT_EVIDENCE_BOUND"}
                )
        bound.sort(key=lambda g: (-g.confidence, self._free_order(g)))
        kept, dropped = bound[: self.cfg.max_free_groups], bound[self.cfg.max_free_groups :]
        for g in dropped:
            self.abstained.append({"code": g.code, "locations": g.locations, "reason": "FREE_CAP"})
        # NNN per group within object and topic, ordered by (PD file, page, first location) (93 §3.7).
        counters: Counter[str] = Counter()
        for g in sorted(kept, key=self._free_order):
            counters[g.free_topic or "OTHER"] += 1
            g.code = f"FREE-{g.free_topic}-{counters[g.free_topic or 'OTHER']:03d}"
        return matrix + kept

    def _free_order(self, g: GroupDraft) -> tuple[Any, ...]:
        ref = g.anchors.get("PD") or g.anchors.get(g.expected_stage)
        return (
            ref.file_id if ref else "~",
            ref.page if ref else 0,
            natural_key(g.locations[0]) if g.locations else (),
        )

    def _external_free(self) -> list[dict[str, Any]]:
        """AG-07's FREE groups: an explicitly passed hook always runs; the installed one when ``free_hook``."""
        hook = self.free_hook
        if hook is None:
            if not self.cfg.free_hook:
                return []
            try:
                from inspector_hypothesis import compare_hook  # type: ignore[attr-defined]

                hook = getattr(compare_hook, "free_finding_groups", None)
            except ImportError:
                hook = None
        if hook is None:
            return []
        try:
            raw = list(
                hook(ctx=self.ctx, observations=self.obs, config=self.cfg, run_dir=self.ctx.run_dir) or []
            )
        except Exception as exc:  # AG-07's hook must never break the scored path
            log.warning("compare.free_hook_failed", extra={"detail": f"{type(exc).__name__}: {exc}"})
            return []
        out = []
        for item in raw:
            errors = validation_errors("finding_group", item)
            if errors:
                self.abstained.append({"reason": "FREE_HOOK_INVALID", "detail": errors[:3]})
                continue
            if item.get("matrix_scope") != "FREE_SEARCH" or item.get("evidence_bind_status") != "BOUND":
                continue
            out.append(item)
        return out

    # 8 ─ hedges ──────────────────────────────────────────────────────────────────────────────

    def _runner_up(self, g: GroupDraft) -> tuple[str | None, float]:
        """The runner-up code and its probability of being the gold code: the change-map route's hedge code
        (prior by route basis, + a bonus when the element family is ambiguous), or for a value finding the next
        code of the parameter's seed hedge group (prior by group kind)."""
        if g.is_free:
            return None, 0.0
        if g.route is not None and g.route.hedge_codes:
            prior = float(self.cfg.hedge.runner_up_prior.get(_basis_key(g.route), 0.25))
            ambiguous = any(len({f for f in self._families_of_room(d)}) > 1 for d in g.diffs)
            p = prior + (self.cfg.hedge.family_ambiguity_bonus if ambiguous else 0.0)
            return str(g.route.hedge_codes[0]), round(min(p, 0.5), 3)
        if g.source == "VALUE_COMPARATOR":
            for grp in self.params.document.get("hedge_groups", []):
                codes = [str(c) for c in grp.get("codes", [])]
                others = [c for c in codes if c != g.code]
                if g.code in codes and others:
                    p = float(self.cfg.hedge.group_kind_prior.get(str(grp.get("kind")), 0.0))
                    return others[0], round(min(p, 0.5), 3)
        return None, 0.0

    def _families_of_room(self, d: RoomDiff) -> set[str]:
        """Families of the same system (topic) that read the *differing* labels of this room on the expected side:
        more than one means the element family itself is ambiguous (a mark «В2.1» in a vent chamber is both an
        exhaust unit and an exhaust branch). A vent chamber that simply holds supply units and exhaust branches is
        not ambiguous: its differing supply marks (П17 → П17.1 + П17.2) belong to one family."""
        topic = self.specs[d.family].topic if d.family in self.specs else None
        differing = set((d.expected - d.actual) + (d.actual - d.expected)) or set(d.expected)
        out = {d.family}
        for family in self.cfg.families:
            spec = self.specs.get(family)
            view = self.obs.views.get((d.expected_stage, family))
            if spec is None or spec.topic != topic or view is None or d.room not in view.rooms:
                continue
            if differing & set(view.rooms[d.room].combined()):
                out.add(family)
        return out

    def apply_hedges(self, groups: list[GroupDraft]) -> list[GroupDraft]:
        """Top-2 hedge (97 §1.6): twins with the runner-up code when p ≥ min, within the budget share."""
        primary_keys = {(g.code, loc) for g in groups for loc in g.locations}
        critical = sum(
            len(g.locations)
            for g in groups
            if not g.is_free and _is_approved_critical(self._criticality_of(g.code)[0])
        )
        candidates = []
        for g in groups:
            code, p = self._runner_up(g)
            g.runner_up, g.runner_up_p = code, p
            if code and p >= self.cfg.hedge.min_runner_up_p:
                candidates.append(g)
        hedges = 0
        twins: list[GroupDraft] = []
        for g in sorted(candidates, key=lambda x: (-x.runner_up_p, x.code, natural_key(x.locations[0]))):
            code = g.runner_up or ""
            locs = [loc for loc in g.locations if (code, loc) not in primary_keys]
            if not locs:
                continue
            twin_critical = _is_approved_critical(self._criticality_of(code)[0])
            new_hedges = hedges + len(locs)
            new_critical = critical + (len(locs) if twin_critical else 0)
            if new_critical == 0 or new_hedges / new_critical > self.cfg.hedge.budget_share + 1e-9:
                self.abstained.append(
                    {"code": code, "hedge_of": g.code, "locations": locs, "reason": "HEDGE_BUDGET"}
                )
                continue
            hedges, critical = new_hedges, new_critical
            twin = GroupDraft(
                axis=g.axis,
                family=g.family,
                code=code,
                free_topic=None,
                route=g.route,
                comparison_result=g.comparison_result,
                discrepancy_type=g.discrepancy_type,
                mapping_status="PROVISIONAL_DOMAIN_MAPPING",
                diffs=[d for d in g.diffs if d.room in locs],
                source=g.source,
                locations=locs,
                anchors=dict(g.anchors),
                location_pages={k: v for k, v in g.location_pages.items() if k in locs},
                confidence=round(min(g.confidence, g.runner_up_p), 3),
                values=dict(g.values),
                element_noun=g.element_noun,
                hedge_kind=self._hedge_kind(g.code, code),
                hedge_of=g,
            )
            primary_keys.update((code, loc) for loc in locs)
            twins.append(twin)
        return groups + twins

    def _hedge_kind(self, a: str, b: str) -> str | None:
        for grp in self.params.document.get("hedge_groups", []):
            if a in grp["codes"] and b in grp["codes"]:
                return str(grp.get("kind"))
        return None

    # 9 ─ ids, cards, dicts ───────────────────────────────────────────────────────────────────

    def assign_ids(self, groups: list[GroupDraft]) -> None:
        oid = self.ctx.object_id
        seq: Counter[tuple[str, str]] = Counter()
        primaries = [g for g in groups if g.hedge_of is None]
        for g in sorted(primaries, key=self._protocol_order):
            if g.is_free:
                g.group_id = f"{oid}-G-{g.code}"
            else:
                key = (g.code, g.comparison_result)
                seq[key] += 1
                g.group_id = f"{oid}-G-{g.code}-{CR_ABBR.get(g.comparison_result, 'X')}-{seq[key]:02d}"
        for g in groups:
            if g.hedge_of is not None:
                g.group_id = f"{g.hedge_of.group_id}-H-{g.code}"
        for g in groups:
            g.finding_ids = [f"{oid}-{g.code}-{AXIS_ID[g.axis]}-{_slug(loc)}" for loc in g.locations]
        # Evidence cards Б.n in protocol order: section 4 (critical), 5 (substantial), 6 (FREE); twins share.
        for n, g in enumerate(sorted(primaries, key=self._protocol_order), start=1):
            g.card_no = f"Б.{n}"
        for g in groups:
            if g.hedge_of is not None:
                g.card_no = g.hedge_of.card_no

    def _protocol_order(self, g: GroupDraft) -> tuple[Any, ...]:
        if g.is_free:
            section = 6
            pid = 999
        else:
            spec = self.params.get(g.code)
            section = 4 if str(spec.criticality_level) == "CRITICAL_SUSPEND" else 5
            pid = spec.param_id
        return (section, pid, natural_key(g.locations[0]) if g.locations else (), g.comparison_result, g.code)

    def _evidence(
        self, g: GroupDraft, stage: str, ref: PageRef, role: str, rooms: Iterable[str], anchor: bool
    ) -> dict[str, Any]:
        info = self.obs.pages.get(ref)
        f = self.ctx.files.get(ref.file_id)
        boxes: list[list[float]] = []
        for loc in rooms:
            d = g.diff_for(loc)
            obs = None
            if isinstance(d, ValueDiff):
                both = d.expected_stage == d.actual_stage
                picked = (
                    [d.expected, d.actual]
                    if both
                    else [d.expected if stage == d.expected_stage else d.actual]
                )
                for value in picked:
                    for box in d.boxes(value):
                        if box not in boxes:
                            boxes.append(box)
                continue
            if d is not None:
                obs = d.expected_obs if role in ("EXPECTED",) else d.actual_obs
            if obs is not None:
                for box in obs.boxes.get(ref, []):
                    if box not in boxes:
                        boxes.append(box)
        ev: dict[str, Any] = {
            "stage": stage,
            "file_id": ref.file_id,
            "pdf_page_number": ref.page,
            "document_sheet_number": info.sheet_number if info else None,
            "file_sha256": f.sha256 if f else None,
            "page_basis": "PDF_NATIVE",
            "role": role,
            "is_anchor": anchor,
            "document_code": info.document_code if info else None,
            "revision": info.revision if info else None,
        }
        if ev["file_sha256"] is None:
            ev.pop("file_sha256")
        if boxes:
            ev["geometry"] = {"boxes": boxes[:12]}
            ev["geometry_space"] = "PDF_VISIBLE_ROTATED_TL_V1"
        return ev

    def _anchor_evidence(self, g: GroupDraft) -> list[dict[str, Any]]:
        out = []
        for stage in ("PD", "RD", "ID"):
            ref = g.anchors.get(stage)
            if ref is None:
                continue
            role = "EXPECTED" if stage == g.expected_stage and stage != g.actual_stage else "ACTUAL"
            rooms = [
                loc for loc in g.locations if g.location_pages.get(loc, {}).get(stage) == ref
            ] or g.locations
            out.append(self._evidence(g, stage, ref, role, rooms, True))
        return out

    def _atomic_evidence(self, g: GroupDraft, location: str) -> list[dict[str, Any]]:
        out = []
        for stage in ("PD", "RD", "ID"):
            ref = g.anchors.get(stage)
            if ref is None:
                continue
            role = "EXPECTED" if stage == g.expected_stage and stage != g.actual_stage else "ACTUAL"
            out.append(self._evidence(g, stage, ref, role, [location], True))
            own = g.location_pages.get(location, {}).get(stage)
            if self.cfg.add_location_pages and own is not None and own != ref:
                out.append(self._evidence(g, stage, own, "SUPPORTING_" + role, [location], False))
        return out

    def _texts(self, g: GroupDraft, location_phrase: str) -> Any:
        values = {
            "location": location_phrase,
            "pd_value": g.values.get("pd_value"),
            "rd_value": g.values.get("rd_value"),
            "id_value": g.values.get("id_value"),
            "actual_value": g.values.get("id_value") or g.values.get("rd_value"),
        }
        first = g.diffs[0] if g.diffs else None
        sign = None
        if isinstance(first, ValueDiff):
            tpl = self.templates.by_code.get(g.code) or {}
            values["delta"] = delta_text(first, tpl.get("delta_format"))
            sign = first.delta_abs
        return render_texts(
            g.code,
            g.discrepancy_type,
            values,
            free_topic=g.free_topic,
            element_noun=g.element_noun,
            templates=self.templates,
            sign=sign,
        )

    def group_dict(self, g: GroupDraft) -> dict[str, Any]:
        if g.external is not None and g.source == "AG07_HOOK":
            doc = dict(g.external)
            doc.update(
                {
                    "finding_group_id": g.group_id,
                    "object_id": self.ctx.object_id,
                    "run_id": self.run_id,
                    "parameter_code": g.code,
                    "locations": g.locations,
                    "finding_ids": g.finding_ids,
                    "card_no": g.card_no,
                }
            )
            for key, default in (
                ("risk_level", "MEDIUM"),
                ("criticality_level", "SUBSTANTIAL_ORDER"),
                ("finding_status", "SUSPICION"),
                ("axis", g.axis),
            ):
                if doc.get(key) is None:
                    doc[key] = default
            return doc
        criticality, level = self._criticality_of(g.code)
        texts = self._texts(g, self._where(g) if g.locations != ["OBJECT"] else rooms_phrase(g.locations))
        spec = None if g.is_free else self.params.get(g.code)
        protocol_status = "WARNING" if g.is_free else violation_protocol_status(level)
        steps = [
            {
                "step": "COMPLETENESS",
                "result": "PASS",
                "axis": g.axis,
                "document_status": PAIRWISE_DOCUMENT_STATUS.get(g.axis),
            },
            {
                "step": "COMPARE",
                "comparator": g.diffs[0].mode if g.diffs else None,
                "family": g.family,
                "outcomes": {d.room: d.outcome for d in g.diffs},
            },
            {
                "step": "ROUTE",
                "family": g.family,
                "discrepancy_type": g.discrepancy_type,
                "code": g.code,
                "basis": g.route.basis if g.route else None,
                "parameter_mapping_status": g.mapping_status,
            },
        ]
        if g.runner_up:
            steps.append(
                {
                    "step": "HEDGE",
                    "runner_up": g.runner_up,
                    "p": g.runner_up_p,
                    "min_p": self.cfg.hedge.min_runner_up_p,
                }
            )
        doc: dict[str, Any] = {
            "finding_group_id": g.group_id,
            "object_id": self.ctx.object_id,
            "run_id": self.run_id,
            "matrix_scope": "FREE_SEARCH" if g.is_free else "MATRIX",
            "parameter_code": g.code,
            "parameter_id": None if g.is_free else spec.param_id,
            "parameter_mapping_status": g.mapping_status,
            "alt_parameter_codes": [g.runner_up] if g.runner_up and g.hedge_of is None else [],
            "hedge_kind": g.hedge_kind,
            "hedge_of_group_id": g.hedge_of.group_id if g.hedge_of else None,
            "title": self._title(g),
            "element_noun": g.element_noun,
            "axis": g.axis,
            "comparison_result": g.comparison_result,
            "discrepancy_type": g.discrepancy_type,
            "location_type": self._location_type(g, g.locations[0] if g.locations else None),
            "locations": g.locations,
            "pd_value": g.values.get("pd_value"),
            "rd_value": g.values.get("rd_value"),
            "id_value": g.values.get("id_value"),
            "violation_label": "VIOLATION_PRESENT",
            "protocol_status": protocol_status,
            "criticality": criticality,
            "criticality_level": level,
            "finding_status": "SUSPICION" if g.is_free else "CANDIDATE",
            "risk_level": self._risk(g, spec),
            "confidence": g.confidence,
            "anchor_evidence": self._anchor_evidence(g),
            "evidence": self._all_evidence(g),
            "location_pages": {
                loc: [
                    PageRef(s, r.file_id, r.page).as_evidence() | {"is_anchor": g.anchors.get(s) == r}
                    for s, r in sorted(pages.items())
                ]
                for loc, pages in g.location_pages.items()
            },
            "finding_ids": g.finding_ids,
            "discovery_method": "GRAPHIC_DIFF" if g.is_free else None,
            "evidence_bind_status": "BOUND" if g.is_free else None,
            "rule_code": self._sub_id(g) or g.code,
            "rule_version": RULES_VERSION,
            "rationale": self._rationale(g),
            "recommendation": {
                "text": texts.recommendation,
                "template_id": texts.template_id,
                "text_origin": texts.text_origin,
                "work_type": texts.work_type_plain,
                "normative_refs": texts.normative_refs,
            },
            "card_no": g.card_no,
            "decision_trace": {
                "steps": steps,
                "context": [c for c in self.context if c.get("family") == g.family][:50],
                "abstained": [a for a in self.abstained if a.get("family") == g.family][:50],
                "compare_config_hash": self.config_hash,
                "inputs": self.ctx.layout_source,
            },
            "ext": {
                "deviation_text": texts.deviation_text,
                "deviation_direction": texts.deviation_direction,
                "work_type_row": texts.work_type,
                "violation_kind_row": texts.violation_kind,
                "revision_clouds": sorted({lbl for d in g.diffs for lbl in d.revision_labels}),
                "source": g.source,
            },
        }
        return doc

    def _all_evidence(self, g: GroupDraft) -> list[dict[str, Any]]:
        out = self._anchor_evidence(g)
        seen = {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in out}
        for loc in g.locations:
            for stage, ref in sorted(g.location_pages.get(loc, {}).items()):
                key = (stage, ref.file_id, ref.page)
                if key in seen:
                    continue
                seen.add(key)
                role = "SUPPORTING_EXPECTED" if stage == g.expected_stage else "SUPPORTING_ACTUAL"
                out.append(self._evidence(g, stage, ref, role, [loc], False))
        return out

    def _risk(self, g: GroupDraft, spec: Any) -> str:
        if g.is_free:
            return "MEDIUM"
        default = spec.data.get("risk_level_default") if spec is not None else None
        return str(default or ("HIGH" if str(spec.criticality_level) == "CRITICAL_SUSPEND" else "MEDIUM"))

    def finding_dicts(self, g: GroupDraft, group: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for loc, fid in zip(g.locations, g.finding_ids, strict=True):
            vals = (
                self._render_values(g, loc)
                if g.route is not None and g.source != "AG07_HOOK"
                else dict(g.values)
            )
            d = g.diff_for(loc)
            finding: dict[str, Any] = {
                "finding_id": fid,
                "finding_group_id": g.group_id,
                "object_id": self.ctx.object_id,
                "run_id": self.run_id,
                "matrix_scope": group["matrix_scope"],
                "parameter_code": g.code,
                "parameter_id": group.get("parameter_id"),
                "parameter_mapping_status": g.mapping_status,
                "alt_parameter_codes": list(group.get("alt_parameter_codes") or []),
                "hedge_of_finding_id": (
                    g.hedge_of.finding_ids[g.hedge_of.locations.index(loc)]
                    if g.hedge_of and loc in g.hedge_of.locations
                    else None
                ),
                "location": loc,
                "location_type": self._location_type(g, loc),
                "pd_value": vals.get("pd_value"),
                "rd_value": vals.get("rd_value"),
                "id_value": vals.get("id_value"),
                "axis": g.axis,
                "comparison_result": g.comparison_result,
                "discrepancy_type": g.discrepancy_type,
                "completeness_status": "COMPLETE",
                "finding_status": group.get("finding_status"),
                "inspector_status": "PENDING",
                "violation_label": "VIOLATION_PRESENT",
                "protocol_status": group["protocol_status"],
                "criticality": group["criticality"],
                "criticality_level": group.get("criticality_level"),
                "review_priority": None if g.is_free else str(self.params.get(g.code).review_priority),
                "risk_level": group.get("risk_level"),
                "document_status": PAIRWISE_DOCUMENT_STATUS.get(g.axis),
                "confidence": d.confidence if d is not None and g.hedge_of is None else g.confidence,
                "evidence": self._atomic_evidence(g, loc),
                "hedge_kind": g.hedge_kind,
                "element_noun": g.element_noun,
                "discovery_method": group.get("discovery_method"),
                "evidence_bind_status": group.get("evidence_bind_status"),
                "recommendation": group.get("recommendation"),
                "card_no": g.card_no,
                "rule_code": group.get("rule_code"),
                "rule_version": RULES_VERSION,
                "sub_id": self._sub_id(g),
                "delta": self._delta(d, group),
                "rationale": group.get("rationale"),
                "decision_trace": {"compare_config_hash": self.config_hash, "group": g.group_id},
            }
            if finding["review_priority"] is None:
                finding.pop("review_priority")
            out.append(finding)
        return out

    # 10 ─ the 132-row precedence ─────────────────────────────────────────────────────────────

    def object_rows(self, outcomes: list[ParamOutcome], violated: set[str]) -> list[dict[str, Any]]:
        rows = []
        for o in outcomes:
            if o.code in violated and self.cfg.object_row_when_violated == "omit":
                continue
            spec = self.params.get(o.code)
            label, status = o.violation_label, o.protocol_status
            if label == "VIOLATION_PRESENT":  # object_row_when_violated == "negative"
                label, status = (
                    ("MISSING_DOCUMENT", o.protocol_status) if o.missing else ("NO_VIOLATION", "OK")
                )
                if o.missing:
                    from inspector_common.contracts.status import missing_document_status

                    status = missing_document_status(o.missing)
            agreed = self.value_equal.get(o.code, {}) if label == "NO_VIOLATION" else {}
            evidence = [
                {
                    "stage": stage,
                    "file_id": v.file_id,
                    "pdf_page_number": v.page_no,
                    "page_basis": "PDF_NATIVE",
                    "role": "EXPECTED" if stage == "PD" else "ACTUAL",
                    "is_anchor": True,
                }
                for stage, v in sorted(agreed.items(), key=lambda kv: ("PD", "RD", "ID").index(kv[0]))
            ]
            shown = {f"{stage.lower()}_value": format_value(v) for stage, v in agreed.items()}
            rows.append(
                {
                    "finding_id": f"{self.ctx.object_id}-{o.code}-OBJ",
                    "finding_group_id": None,
                    "object_id": self.ctx.object_id,
                    "run_id": self.run_id,
                    "matrix_scope": "MATRIX",
                    "parameter_code": o.code,
                    "parameter_id": o.param_id,
                    "parameter_mapping_status": "SOURCE_MATRIX",
                    "location": "OBJECT",
                    "location_type": "OBJECT",
                    "pd_value": shown.get("pd_value"),
                    "rd_value": shown.get("rd_value"),
                    "id_value": shown.get("id_value"),
                    "completeness_status": o.completeness_status,
                    "completeness_basis": o.completeness_basis,
                    "finding_status": "NEGATIVE_VERIFIED" if label == "NO_VIOLATION" and o.verified else None,
                    "violation_label": label,
                    "protocol_status": status,
                    "criticality": spec.criticality,
                    "criticality_level": str(spec.criticality_level),
                    "review_priority": str(spec.review_priority),
                    "document_status": o.document_status,
                    "evidence": evidence,
                    "rule_version": RULES_VERSION,
                    "rationale": o.reason_ru,
                    "decision_trace": {
                        "precedence_rule": o.rule,
                        "required_stages": list(o.required),
                        "available_stages": list(o.available),
                        "missing_stages": list(o.missing),
                        "stage_files": o.stage_files,
                        "verified_by_comparator": o.verified,
                        "bucket": o.bucket,
                        "compare_config_hash": self.config_hash,
                    },
                }
            )
        return rows

    # run ─────────────────────────────────────────────────────────────────────────────────────

    def _location_type(self, g: GroupDraft, location: str | None) -> str:
        if g.external is not None and g.external.get("location_type"):
            return str(g.external["location_type"])
        d = g.diff_for(location) if location else None
        if isinstance(d, ValueDiff):
            return "OBJECT" if d.room == "OBJECT" else d.location_type
        return "OBJECT" if location == "OBJECT" else "ROOM"

    def _sub_id(self, g: GroupDraft) -> str | None:
        first = g.diffs[0] if g.diffs else None
        if isinstance(first, ValueDiff):
            return first.sub_id if first.code == g.code else None  # a hedge twin has no sub-check of its own
        return g.route.data.get("sub_check") if g.route else None

    @staticmethod
    def _delta(d: Any, group: Mapping[str, Any]) -> dict[str, Any] | None:
        if d is None:
            return None
        direction = (group.get("ext") or {}).get("deviation_direction")
        if isinstance(d, ValueDiff):
            return {"direction": direction, "abs": d.delta_abs, "rel": d.delta_rel, "unit": d.unit}
        return {"direction": direction, "expected": _labels(d.expected), "actual": _labels(d.actual)}

    def _drop_deactivated(self, drafts: list[GroupDraft]) -> list[GroupDraft]:
        """Module 8: a parameter switched off in the admin matrix emits no candidates. Its OBJECT row stays
        (precedence rule 0: NOT_APPLICABLE / PARAM_DEACTIVATED), so the 132 rows are never dropped."""
        keep: list[GroupDraft] = []
        for g in drafts:
            spec = None if g.is_free else self._spec_or_none(g.code)
            if spec is not None and not getattr(spec, "is_active", True):
                self.deactivated[g.code] += 1
                continue
            keep.append(g)
        return keep

    def _spec_or_none(self, code: str) -> Any:
        try:
            return self.params.get(code)
        except Exception:
            return None

    def run(self) -> CompareResult:
        self.deactivated: Counter[str] = Counter()
        drafts = self._drop_deactivated(self.dedupe(self.run_comparators() + self.run_value_comparators()))
        pools = self.anchor_pools(drafts)
        for g in drafts:
            self.choose_anchors(g, pools.get((g.axis, g.code, g.family)))
            g.element_noun = self._element_noun(g)
            if g.source != "VALUE_COMPARATOR":
                g.values = self._render_values(g, None)
        bound: list[GroupDraft] = []
        for g in drafts:
            if g.expected_stage in g.anchors and g.actual_stage in g.anchors:
                bound.append(g)
                continue
            # A difference without a page on one of its stages cannot be cited (evidence-bound only).
            self.abstained.append(
                {
                    "family": g.family,
                    "code": g.code,
                    "axis": g.axis,
                    "locations": list(g.locations),
                    "reason": "SHEETS_NOT_MATCHED",
                    "missing_stages": [s for s in (g.expected_stage, g.actual_stage) if s not in g.anchors],
                }
            )
        drafts = bound
        drafts = self.collect_free(drafts)
        drafts = self._drop_deactivated(self.apply_hedges(drafts))
        self.assign_ids(drafts)
        ordered = sorted(
            drafts, key=lambda g: (self._protocol_order(g.hedge_of or g), g.hedge_of is not None)
        )
        groups, findings = [], []
        for g in ordered:
            doc = self.group_dict(g)
            groups.append(doc)
            findings.extend(self.finding_dicts(g, doc))
        violated = {g.code for g in drafts if not g.is_free}
        verified = {code for code, n in self.compared.items() if n > 0} - violated
        outcomes = evaluate_all(
            self.ctx,
            self.params,
            violated=violated,
            verified=verified,
            unverified_status=self.cfg.unverified_status,
            value_stages=self.value_stages,
        )
        if self.cfg.emit_object_rows:
            findings.extend(self.object_rows(outcomes, violated))
        problems = []
        for doc in groups:
            problems += [f"{doc['finding_group_id']}: {e}" for e in validation_errors("finding_group", doc)]
        for doc in findings:
            problems += [f"{doc['finding_id']}: {e}" for e in validation_errors("finding", doc)]
        if problems:
            raise ValueError("compare produced contract-invalid artifacts: " + "; ".join(problems[:10]))
        trace = {
            "room_outcomes": dict(sorted(self.room_outcomes.items())),
            "context": self.context,
            "abstained": self.abstained,
            "compared_params": dict(sorted(self.compared.items())),
            "layout_files": sorted(self.ctx.layouts),
            "layout_source": self.ctx.layout_source,
            "input_warnings": self.ctx.warnings,
            "groups": len(groups),
            "hedges": sum(1 for g in drafts if g.hedge_of is not None),
            "matrix_version": self.params.matrix_version,
            "matrix_overrides": self.params.overrides if hasattr(self.params, "overrides") else None,
            "deactivated_params": dict(sorted(self.deactivated.items())),
            "free_groups": sum(1 for g in drafts if g.is_free),
        }
        return CompareResult(self.ctx.object_id, groups, findings, outcomes, trace, drafts)


def compare_object(ctx: ObjectContext, cfg: CompareConfig, **kwargs: Any) -> CompareResult:
    return CompareEngine(ctx, cfg, **kwargs).run()
