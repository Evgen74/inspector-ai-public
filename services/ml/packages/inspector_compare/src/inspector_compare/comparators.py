"""Per-room element comparators (97 §2.10, 95 §3.4, 04 §3.5.7): multiset / presence-absence per room.

For one element family and one axis (expected stage → actual stage, e.g. PD → RD), every room token seen on
either side gets an outcome:

- ``ELEMENT_MISSING``: expected elements, and the room is drawn on a relevant actual sheet with none of them;
- ``CONFIGURATION_CHANGED``: both sides have elements and the family's comparison key differs
  (a PD label missing or split for units; the branch count per system prefix for branches);
- ``ELEMENT_ADDED``: only the actual side has elements, or the actual side keeps every expected label and adds
  others (context, never a violation: directional triggers);
- ``RENUMBERED``: same count per system, other labels (context: RD renumbers branches);
- ``RELOCATED``: units (label multiset) whose missing marks the actual stage shows in another room of the family
  (a unit moved to another vent chamber: context, 97 §2.10);
- ``EQUAL``: verified negative for this room;
- ``UNRESOLVED``: expected elements but the room is not drawn on any relevant actual sheet (abstain,
  AbstainReason ELEMENT_KEY_UNRESOLVED — absence is never concluded without coverage); on a stable-mark axis
  (``CompareConfig.stable_mark_axes``, RD→ИД) also a violation whose missing marks are all printed elsewhere on the
  room's actual sheet (note ``MARK_ELSEWHERE_ON_SHEET``, AbstainReason AMBIGUOUS_VALUE).

A violating outcome must also hold without the *ambiguous* tag instances (one instance linked to two or more
rooms); otherwise the room keeps the outcome of its firmly attributed elements and the diff carries the note
``AMBIGUOUS_ATTRIBUTION`` (abstain, AbstainReason AMBIGUOUS_VALUE).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from inspector_compare.config import CompareConfig, FamilyRule
from inspector_compare.observe import Observations, PageRef, RoomObservation
from inspector_compare.tags import system_prefix
from inspector_compare.values import natural_key

Outcome = Literal[
    "ELEMENT_MISSING",
    "CONFIGURATION_CHANGED",
    "ELEMENT_ADDED",
    "RENUMBERED",
    "RELOCATED",
    "EQUAL",
    "UNRESOLVED",
]
VIOLATING: frozenset[str] = frozenset({"ELEMENT_MISSING", "CONFIGURATION_CHANGED"})
AXIS_STAGES: dict[str, tuple[str, str]] = {
    "PD_RD": ("PD", "RD"),
    "RD_ID": ("RD", "ID"),
    "PD_ID": ("PD", "ID"),
    "NORM_ID": ("ID", "ID"),  # ИД-internal tolerance check: both anchors on the one ИД sheet (tolerance)
}

# Base confidence by outcome and comparator mode (deterministic; lowered by the recognition provenance).
_BASE_CONFIDENCE: dict[tuple[str, str], float] = {
    ("ELEMENT_MISSING", "LABEL_MULTISET"): 0.80,
    ("ELEMENT_MISSING", "SYSTEM_COUNT"): 0.82,
    ("ELEMENT_MISSING", "PRESENCE"): 0.82,
    ("CONFIGURATION_CHANGED", "LABEL_MULTISET"): 0.74,
    ("CONFIGURATION_CHANGED", "SYSTEM_COUNT"): 0.72,
    ("CONFIGURATION_CHANGED", "PRESENCE"): 0.60,
}
REVISION_CLOUD_BONUS = 0.08
# RoomDiff.note when the violation read on all tags vanished on the firmly attributed ones.
AMBIGUOUS_ATTRIBUTION = "AMBIGUOUS_ATTRIBUTION"
# RoomDiff.note (outcome UNRESOLVED) on a stable-mark axis: every expected mark the room lacks is printed elsewhere
# on the room's actual sheet, so the difference is in the room attribution, not in the design.
MARK_ELSEWHERE = "MARK_ELSEWHERE_ON_SHEET"
# RoomDiff.note (outcome UNRESOLVED): the expected marks are absent from the room, but the actual room still shows
# the element by the family's anchor phrase («М.О.» — местный отсос): the element is there, its mark is not
# printed, so neither the absence nor the count per system can be concluded.
ANCHOR_PRESENT = "ANCHOR_PRESENT"


@dataclass(slots=True)
class RoomDiff:
    axis: str
    family: str
    mode: str
    room: str
    outcome: Outcome
    expected_stage: str
    actual_stage: str
    expected: Counter[str]
    actual: Counter[str]
    expected_obs: RoomObservation | None
    actual_obs: RoomObservation | None
    confidence: float = 0.0
    revision_cloud_pages: list[PageRef] = field(default_factory=list)
    revision_labels: list[str] = field(default_factory=list)
    note: str | None = None

    @property
    def is_violation(self) -> bool:
        return self.outcome in VIOLATING

    @property
    def discrepancy_type(self) -> str:
        """DiscrepancyType of the outcome (routing key of the change map)."""
        return {
            "ELEMENT_MISSING": "ELEMENT_MISSING",
            "CONFIGURATION_CHANGED": "CONFIGURATION_CHANGED",
            "ELEMENT_ADDED": "ELEMENT_ADDED",
            "RENUMBERED": "POSITION_SHIFTED",
            "RELOCATED": "POSITION_SHIFTED",
        }.get(self.outcome, "")

    def expected_pages(self) -> list[PageRef]:
        return self.expected_obs.element_pages if self.expected_obs else []

    def actual_pages(self) -> list[PageRef]:
        """Pages proving the actual side: element pages when elements exist, else the coverage pages."""
        if self.actual_obs is None:
            return []
        if self.outcome == "ELEMENT_MISSING":
            return sorted(self.actual_obs.drawn_on)
        pages = self.actual_obs.element_pages
        return pages or sorted(self.actual_obs.drawn_on)


def _system_counts(counts: Counter[str]) -> Counter[str]:
    out: Counter[str] = Counter()
    for label, n in counts.items():
        out[system_prefix(label)] += n
    return out


def compare_room(rule: FamilyRule, expected: Counter[str], actual: Counter[str]) -> Outcome:
    """The outcome for one room whose actual side is covered (see module docstring)."""
    if not expected and not actual:
        return "EQUAL"
    if expected and not actual:
        return "ELEMENT_MISSING"
    if actual and not expected:
        return "ELEMENT_ADDED"
    if rule.mode == "PRESENCE":
        return "EQUAL"
    if expected == actual:
        return "EQUAL"
    # Directional trigger (97 §2.10): the actual side keeping every expected element and adding others is an
    # addition (context, never a violation), for units and branches alike. Branches are renumbered in RD, so
    # when labels are not kept the count per system prefix decides; kept labels prove the PD branches survive.
    if not (expected - actual):
        return "ELEMENT_ADDED"
    if rule.mode == "SYSTEM_COUNT":
        if _system_counts(expected) != _system_counts(actual):
            return "CONFIGURATION_CHANGED"
        return "RENUMBERED"
    # Units: a PD unit that is gone or split (П17 → П17.1 + П17.2) is a changed configuration.
    return "CONFIGURATION_CHANGED"


def compare_family(obs: Observations, family: str, axis: str, cfg: CompareConfig) -> list[RoomDiff]:
    """Every room outcome of one family on one axis (rooms in natural order)."""
    rule = cfg.families[family]
    exp_stage, act_stage = AXIS_STAGES[axis]
    exp_view = obs.views.get((exp_stage, family))
    act_view = obs.views.get((act_stage, family))
    if exp_view is None or act_view is None:
        return []
    rooms = sorted(set(exp_view.rooms) | set(act_view.rooms), key=natural_key)
    bridge = cfg.bridged_axes.get(axis)
    mid_view = obs.views.get((bridge, family)) if bridge else None
    out: list[RoomDiff] = []
    for room in rooms:
        if mid_view is not None and room in mid_view.rooms and mid_view.rooms[room].covered:
            continue  # compared on the axes through the intermediate stage (PD→RD, RD→ИД)
        e_obs = exp_view.rooms.get(room)
        a_obs = act_view.rooms.get(room)
        expected = e_obs.combined() if e_obs else Counter()
        actual = a_obs.combined() if a_obs else Counter()
        if not expected and not actual:
            continue
        note: str | None = None
        if expected and (a_obs is None or not a_obs.covered):
            outcome: Outcome = "UNRESOLVED"
        elif actual and not expected and (e_obs is None or not e_obs.covered):
            continue  # the room is not on any relevant expected sheet: nothing to say
        else:
            outcome = compare_room(rule, expected, actual)
            ambiguous = (e_obs is not None and e_obs.ambiguous_labels) or (
                a_obs is not None and a_obs.ambiguous_labels
            )
            if outcome in VIOLATING and ambiguous:
                # A violation must also hold on the firmly attributed elements: a tag instance the layout links
                # to two rooms (one leader read for both) is evidence for neither.
                firm = compare_room(
                    rule,
                    e_obs.combined_firm() if e_obs else Counter(),
                    a_obs.combined_firm() if a_obs else Counter(),
                )
                if firm not in VIOLATING:
                    outcome, note = firm, AMBIGUOUS_ATTRIBUTION
            if (
                outcome == "ELEMENT_MISSING"
                and obs.specs[family].patterns
                and a_obs is not None
                and obs.anchor_pages(act_stage, family, room) & set(a_obs.coverage_pages())
            ):
                outcome, note = "UNRESOLVED", ANCHOR_PRESENT
            if outcome in VIOLATING and rule.mode == "LABEL_MULTISET":
                # Units carry their identity in the mark: a PD unit that the actual stage shows in another room of
                # the family (another vent chamber) was moved, and relocations are context (97 §2.10).
                missing = set(expected) - set(actual)
                elsewhere: set[str] = set()
                for other, other_obs in act_view.rooms.items():
                    if other != room:
                        elsewhere |= set(other_obs.combined())
                if missing and missing <= elsewhere:
                    outcome = "RELOCATED"
            if outcome in VIOLATING and axis in cfg.stable_mark_axes and a_obs is not None:
                # ИД copies the RD sheet with the same marks: a mark missing from this room but printed on the
                # same actual sheet(s) was linked to another room by the layout — no evidence of absence.
                missing = set(expected) - set(actual)
                if missing and missing <= obs.sheet_labels(a_obs.coverage_pages(), family):
                    outcome, note = "UNRESOLVED", MARK_ELSEWHERE
        diff = RoomDiff(
            axis=axis,
            family=family,
            mode=rule.mode,
            room=room,
            outcome=outcome,
            expected_stage=exp_stage,
            actual_stage=act_stage,
            expected=expected,
            actual=actual,
            expected_obs=e_obs,
            actual_obs=a_obs,
            note=note,
        )
        if diff.is_violation:
            _score(diff, obs)
        out.append(diff)
    return out


def _score(diff: RoomDiff, obs: Observations) -> None:
    base = _BASE_CONFIDENCE.get((diff.outcome, diff.mode), 0.6)
    provenance = min(
        diff.expected_obs.min_confidence if diff.expected_obs else 1.0,
        diff.actual_obs.min_confidence if diff.actual_obs and diff.actual_obs.element_pages else 1.0,
    )
    confidence = base * (0.5 + 0.5 * provenance)
    for ref in diff.actual_pages():
        info = obs.pages.get(ref)
        if info is not None and diff.room in info.revision_cloud_rooms:
            diff.revision_cloud_pages.append(ref)
            diff.revision_labels.extend(sorted(info.revision_labels))
    if diff.revision_cloud_pages:
        confidence += REVISION_CLOUD_BONUS
    diff.revision_labels = list(dict.fromkeys(diff.revision_labels))
    diff.confidence = round(max(0.05, min(0.99, confidence)), 3)
