"""Frozen configuration of the comparison engine and the exporter (its hash goes into the sidecar).

Defaults follow 97 §1.6 / §2.5–2.10 and the AG-03 seed policy (``change_matrix_map.json → policy``): the seed
values (hedge threshold, hedge budget, FREE cap) are read from the seed so AG-03 stays authoritative; a config
file (``--config``, JSON or YAML) may override any field. Every number here is a declared rule, never tuned on
the hidden object (97 §2.17).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from inspector_common.hashing import sha256_json
from inspector_compare.version import COMPARE_VERSION, PROTOCOL_VERSION, RULES_VERSION

ComparatorMode = Literal["LABEL_MULTISET", "SYSTEM_COUNT", "PRESENCE"]
Axis = Literal["PD_RD", "RD_ID", "PD_ID"]


@dataclass(frozen=True, slots=True)
class FamilyRule:
    """How the room-element comparator reads one element family of the change map (97 §2.10).

    - ``LABEL_MULTISET``: the multiset of printed labels per room (vent-chamber units П2, П17 → П17.1 + П17.2);
    - ``SYSTEM_COUNT``: the count of branches per system prefix per room (В2: 3 vs 1); tag identity is not the key
      because RD renumbers branches (95 §3.4, seed note on IOS4-078.b);
    - ``PRESENCE``: presence of the element by the family anchors (warm floors: «тёплый пол», Multibox).
    """

    mode: ComparatorMode
    tag_kinds: tuple[str, ...]
    # Tag kinds accepted only in rooms whose name (on any stage) matches ``room_name_pattern``: a system mark
    # («П2», VENT_SYSTEM) is a unit inside a vent chamber, but only a duct label in a corridor.
    room_kinds: tuple[str, ...] = ()
    room_name_pattern: str | None = None
    # Rooms whose name (on any stage) matches this pattern are not read for the family at all: in a vent chamber
    # the marks «В9.1», «П2» are the units standing there (compared by the unit families), not local branches.
    exclude_room_name_pattern: str | None = None


@dataclass(frozen=True, slots=True)
class HedgePolicy:
    """Bounded top-2 code hedge (97 §1.6, agreed with the user): runner-up p ≥ min, hedges ≤ budget share of the
    emitted approved-critical checks (hedges counted like inspector-score: extra codes at one location)."""

    min_runner_up_p: float = 0.1
    budget_share: float = 0.2
    # Probability that the runner-up code is the gold one, by the basis of the route (seed `basis` prefix):
    # routes learned from the organizers' gold or stated by the matrix are near-certain; analogies are not.
    runner_up_prior: Mapping[str, float] = field(
        default_factory=lambda: {"GOLD": 0.05, "MATRIX": 0.05, "USER": 0.05, "ANALOGY": 0.25, "CONTEXT": 0.0}
    )
    # Added to the runner-up p when the element family itself is ambiguous (mixed tag evidence).
    family_ambiguity_bonus: float = 0.15
    # Value findings (no change-map route): the runner-up is the next code of the seed hedge group of the
    # parameter (params.json hedge_groups: the matrix's near-duplicates, 97 §2.10), its p by the group kind —
    # a DUPLICATE measures the same quantity under another code, so the gold may well use either.
    group_kind_prior: Mapping[str, float] = field(
        default_factory=lambda: {"DUPLICATE": 0.30, "PARTIAL_DUPLICATE": 0.15, "SAME_SYSTEM": 0.05}
    )


VENT_CHAMBER = r"венткамер|вент\w*\s+камер|вентиляционн\w*\s+камер"

DEFAULT_FAMILIES: dict[str, FamilyRule] = {
    # Units standing in a vent chamber: label multiset (G-TR-001).
    "VENT_SUPPLY_UNIT": FamilyRule("LABEL_MULTISET", ("EQUIPMENT",), ("VENT_SYSTEM",), VENT_CHAMBER),
    "VENT_EXHAUST_UNIT": FamilyRule("LABEL_MULTISET", ("EQUIPMENT",), ("VENT_SYSTEM",), VENT_CHAMBER),
    # Local exhaust branches per room: count per system prefix (G-TR-003, G-TR-004). Branch marks are system
    # marks on ducts (VENT_SYSTEM / AIR_TERMINAL); equipment (units) never counts as a branch.
    "VENT_EXHAUST_BRANCH": FamilyRule(
        "SYSTEM_COUNT", ("VENT_SYSTEM", "AIR_TERMINAL"), exclude_room_name_pattern=VENT_CHAMBER
    ),
    # Warm floors: presence by anchors (G-TR-002 → FREE-HEATING).
    "WARM_FLOOR": FamilyRule("PRESENCE", ("HEATING_SYSTEM", "EQUIPMENT", "OTHER")),
}

# Sheet-title vocabulary per change-map topic: a page is relevant to a family when its title names the system.
DEFAULT_TOPIC_PAGE_PATTERNS: dict[str, str] = {
    "VENTILATION": r"вентиляц|приточн|вытяжн|венткамер|воздухообмен",
    # Not a change-map topic: it only separates air-conditioning sheets from ventilation sheets (layer purity).
    "CONDITIONING": r"кондиц",
    "HEATING": r"отоплен|теплоснабж|тепл\w*\s+пол|напольн\w*\s+отоплен",
    "WATER": r"водоснабж|водопровод",
    "SEWER": r"канализац|водоотвед",
    "ELECTRICAL": r"электроснабж|электрооборуд|силов",
    "LIGHTING": r"освещен",
    "FIRE": r"пожар|дымоудал|подпор",
}


@dataclass(frozen=True, slots=True)
class CompareConfig:
    families: Mapping[str, FamilyRule] = field(default_factory=lambda: dict(DEFAULT_FAMILIES))
    topic_page_patterns: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_TOPIC_PAGE_PATTERNS))
    # Room occurrences that prove a room is drawn on the compared (actual) sheet.
    actual_room_sources: tuple[str, ...] = ("PLAN_LABEL", "SCHEMATIC_LABEL", "EXPLICATION_TABLE")
    # Axes in priority order; a key (code, location) found on several axes keeps the first (97 §2.10: ИД≠РД only
    # in the violating direction; gold keeps id_value null for PD↔RD checks).
    axes: tuple[Axis, ...] = ("PD_RD", "RD_ID", "PD_ID")
    hedge: HedgePolicy = field(default_factory=HedgePolicy)
    max_free_groups: int = 5
    # 132-row precedence (97 §2.6): one OBJECT row per catalog parameter without a violation row.
    emit_object_rows: bool = True
    object_row_when_violated: Literal["omit", "negative"] = "omit"
    # A parameter whose stages are present but that no comparator verified (fragment-level MISSING_EVIDENCE).
    unverified_status: Literal["COMPARISON_IMPOSSIBLE", "NO_VIOLATION"] = "COMPARISON_IMPOSSIBLE"
    # Evidence: one anchor page per stage per group; optionally the location's own page as a second item.
    add_location_pages: bool = False
    # Majority pool of the anchor rule (93 §2.8): "system" counts the rooms of every group of the same finding
    # (axis × code × element family) — the organizers anchor both groups of «пункт 3» (G-TR-003 missing, G-TR-004
    # changed) on RD p18 although room 314 is drawn on p20; "group" counts the group's own rooms only. Either way
    # the anchor is a page that depicts at least one of the group's own rooms.
    anchor_scope: Literal["system", "group"] = "system"
    # Axes whose two stages print the *same* marks for the same element (the ИД executive drawing is a copy of the
    # RD sheet: marks are not renumbered). On these axes a mark that is missing from the room but printed elsewhere
    # on the room's actual sheet is a room-attribution disagreement, not an absence (abstain AMBIGUOUS_VALUE).
    # PD→RD is not listed: RD renumbers branches by design (G-TR-003/004), so a PD mark reused on another RD room
    # says nothing about this room.
    stable_mark_axes: tuple[Axis, ...] = ("RD_ID",)
    # The sheet title is authoritative for coverage: a sheet whose title names configured topics proves absence
    # only for those topics (a heating plan with a vent-shaft layer or a stray vent mark does not prove that a
    # room has no ventilation). Sheets without a title, or with a topic-neutral title, fall back to layers/tags.
    title_authoritative_coverage: bool = True
    # Axes that skip the intermediate stage (PD→ИД over RD): compared for a room only when the intermediate stage
    # does not cover the room for the family. With RD present, a PD→ИД difference is either a design change (PD→RD)
    # or an as-built deviation (RD→ИД) and is reported on that axis; the direct PD→ИД comparison would count the RD
    # renumbering twice.
    bridged_axes: Mapping[str, str] = field(default_factory=lambda: {"PD_ID": "RD"})
    # A family's elements and coverage are read only from documents of its disciplines (change map
    # ``element_families[].disciplines``; file marks from title blocks, manifest section and name): an automation
    # plan (СС) showing the fans of a vent chamber is not the ventilation design. Files without marks are read.
    discipline_scoped_families: bool = True
    # Gate-aware emission thresholds (97 §1.6): recall-first on Критическое, precision-first otherwise.
    min_confidence_critical: float = 0.30
    min_confidence_substantial: float = 0.50
    # AG-07 FREE-* groups through inspector_hypothesis (optional hook).
    free_hook: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "families": {k: dataclasses.asdict(v) for k, v in sorted(self.families.items())},
            "topic_page_patterns": dict(sorted(self.topic_page_patterns.items())),
            "actual_room_sources": list(self.actual_room_sources),
            "axes": list(self.axes),
            "hedge": {
                "min_runner_up_p": self.hedge.min_runner_up_p,
                "budget_share": self.hedge.budget_share,
                "runner_up_prior": dict(sorted(self.hedge.runner_up_prior.items())),
                "family_ambiguity_bonus": self.hedge.family_ambiguity_bonus,
                "group_kind_prior": dict(sorted(self.hedge.group_kind_prior.items())),
            },
            "max_free_groups": self.max_free_groups,
            "emit_object_rows": self.emit_object_rows,
            "object_row_when_violated": self.object_row_when_violated,
            "unverified_status": self.unverified_status,
            "add_location_pages": self.add_location_pages,
            "anchor_scope": self.anchor_scope,
            "stable_mark_axes": list(self.stable_mark_axes),
            "title_authoritative_coverage": self.title_authoritative_coverage,
            "bridged_axes": dict(sorted(self.bridged_axes.items())),
            "discipline_scoped_families": self.discipline_scoped_families,
            "min_confidence_critical": self.min_confidence_critical,
            "min_confidence_substantial": self.min_confidence_substantial,
            "free_hook": self.free_hook,
        }

    def describe(self, seed_hashes: Mapping[str, str] | None = None) -> dict[str, Any]:
        """The frozen config with versions and seed hashes; ``config_hash`` is over exactly this body."""
        body = {
            "compare_version": COMPARE_VERSION,
            "rules_version": RULES_VERSION,
            "config": self.as_dict(),
            "seed": dict(sorted((seed_hashes or {}).items())),
        }
        return {**body, "config_hash": sha256_json(body)}


@dataclass(frozen=True, slots=True)
class ExportConfig:
    emit_negatives: Literal["all", "none"] = "all"
    protocol: bool = True
    protocol_formats: tuple[str, ...] = ("json", "docx", "pdf")
    # PDF engine: "auto" = headless Chromium when found, else the PyMuPDF Story renderer.
    pdf_engine: Literal["auto", "chromium", "pymupdf", "none"] = "auto"
    # Evidence-card thumbnails (page crops with blue/red frames) embedded in the DOCX and PDF views.
    thumbnails: bool = True
    freeze_tag: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "emit_negatives": self.emit_negatives,
            "protocol": self.protocol,
            "protocol_formats": list(self.protocol_formats),
            "pdf_engine": self.pdf_engine,
            "thumbnails": self.thumbnails,
            "protocol_version": PROTOCOL_VERSION,
        }

    def config_hash(self) -> str:
        return sha256_json({"compare_version": COMPARE_VERSION, "export": self.as_dict()})


def _seed_policy() -> dict[str, Any]:
    from inspector_common.params import load_change_map

    return dict(load_change_map().document.get("policy") or {})


def default_config() -> CompareConfig:
    """Defaults with the AG-03 seed policy applied (hedge threshold, hedge budget, FREE cap)."""
    policy = _seed_policy()
    hedge = HedgePolicy(
        min_runner_up_p=float(policy.get("hedge_min_runner_up_p", 0.1)),
        budget_share=float(policy.get("hedge_budget_share_of_critical", 0.2)),
    )
    return CompareConfig(hedge=hedge, max_free_groups=int(policy.get("max_free_groups_per_object", 5)))


class ConfigError(ValueError):
    """The comparison config file is malformed (unknown key or bad value)."""


def _family(value: Mapping[str, Any]) -> FamilyRule:
    unknown = set(value) - {
        "mode",
        "tag_kinds",
        "room_kinds",
        "room_name_pattern",
        "exclude_room_name_pattern",
    }
    if unknown:
        raise ConfigError(f"неизвестные поля семейства: {sorted(unknown)}")
    mode = value.get("mode")
    if mode not in ("LABEL_MULTISET", "SYSTEM_COUNT", "PRESENCE"):
        raise ConfigError(f"недопустимый режим сравнения семейства: {mode!r}")
    return FamilyRule(
        mode,
        tuple(value.get("tag_kinds") or ()),
        tuple(value.get("room_kinds") or ()),
        value.get("room_name_pattern"),
        value.get("exclude_room_name_pattern"),
    )


def apply_overrides(base: CompareConfig, overrides: Mapping[str, Any]) -> CompareConfig:
    """Merge a JSON/YAML mapping into ``base``; unknown keys are an error (a typo must not pass silently)."""
    known = {f.name for f in dataclasses.fields(CompareConfig)}
    unknown = set(overrides) - known
    if unknown:
        raise ConfigError(f"неизвестные ключи конфигурации сравнения: {sorted(unknown)}")
    changes: dict[str, Any] = {}
    for key, value in overrides.items():
        if key == "families":
            fams = dict(base.families)
            for name, spec in (value or {}).items():
                if spec is None:
                    fams.pop(name, None)
                else:
                    fams[name] = _family(spec)
            changes[key] = fams
        elif key == "bridged_axes":
            changes[key] = dict(value or {})
        elif key == "topic_page_patterns":
            changes[key] = {**base.topic_page_patterns, **(value or {})}
        elif key == "hedge":
            hedge_known = {f.name for f in dataclasses.fields(HedgePolicy)}
            bad = set(value or {}) - hedge_known
            if bad:
                raise ConfigError(f"неизвестные ключи политики страховки кода: {sorted(bad)}")
            hv = dict(value or {})
            if "runner_up_prior" in hv:
                hv["runner_up_prior"] = {**base.hedge.runner_up_prior, **hv["runner_up_prior"]}
            if "group_kind_prior" in hv:
                hv["group_kind_prior"] = {**base.hedge.group_kind_prior, **hv["group_kind_prior"]}
            changes[key] = dataclasses.replace(base.hedge, **hv)
        elif key in ("actual_room_sources", "axes", "stable_mark_axes"):
            changes[key] = tuple(value)
        else:
            changes[key] = value
    cfg = dataclasses.replace(base, **changes)
    if not 0 < cfg.hedge.budget_share < 1:
        raise ConfigError("hedge.budget_share должен быть в (0, 1)")
    if cfg.object_row_when_violated not in ("omit", "negative"):
        raise ConfigError("object_row_when_violated: omit | negative")
    if cfg.unverified_status not in ("COMPARISON_IMPOSSIBLE", "NO_VIOLATION"):
        raise ConfigError("unverified_status: COMPARISON_IMPOSSIBLE | NO_VIOLATION")
    if cfg.anchor_scope not in ("system", "group"):
        raise ConfigError("anchor_scope: system | group")
    return cfg


def load_config(path: str | Path | None) -> CompareConfig:
    """Defaults, then the overrides of ``path`` (JSON or YAML) when given."""
    base = default_config()
    if path is None:
        return base
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text) if str(path).endswith(".json") else yaml.safe_load(text)
    if data is None:
        return base
    if not isinstance(data, Mapping):
        raise ConfigError("файл конфигурации должен содержать объект (словарь)")
    return apply_overrides(base, data)
