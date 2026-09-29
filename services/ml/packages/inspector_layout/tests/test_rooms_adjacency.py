"""Adjacent-number override of a leader link (rooms/tags.assign_rooms) on synthetic geometry."""

from __future__ import annotations

from types import SimpleNamespace

from inspector_layout.rooms.grammar import TagMatch
from inspector_layout.rooms.labels import PageLabels, RoomLabel
from inspector_layout.rooms.tags import TagHit, assign_rooms


def _label(room: str, x: float, y: float) -> RoomLabel:
    return RoomLabel(
        rooms=(room,), token_ids=[], box=(x, y, x + 12.0, y + 10.0), source="SCHEMATIC_LABEL",
        confidence=0.9, text_source="TEXT_LAYER", seed=(x + 6, y + 5),
    )  # fmt: skip


class _Zones:
    def __init__(self, at: int | None) -> None:
        self.at = at

    def label_at(self, x: float, y: float) -> int | None:
        return 0 if x < 100 else self.at  # the leader tip is in room 006's zone; the mark is in ``at``


class _Leaders:
    """Every mark has one long leader ending at label 0."""

    def follow(self, box, th):
        return [SimpleNamespace(x=10.0, y=15.0, length=300.0)]


def _run(zone_label: int | None) -> TagHit:
    labels = PageLabels(plan_labels=[_label("006", 5, 10), _label("002", 400, 400), _label("001", 700, 400)])
    hit = TagHit(
        match=TagMatch(tag="В1.1", tag_norm="В1.1", tag_kind="VENT_SYSTEM", span=(0, 4)),
        token_ids=[], box=(414.0, 416.0, 428.0, 426.0), conf=1.0, text_source="TEXT_LAYER", layer=None,
    )  # fmt: skip
    assign_rooms([hit], labels, _Zones(zone_label), _Leaders(), {})
    return hit


def test_adjacent_number_overrides_stray_leader() -> None:
    hit = _run(None)
    assert (hit.room_token, hit.room_link) == ("002", "NEAREST")
    assert _run(1).room_token == "002"  # zone of the adjacent room agrees


def test_adjacent_number_does_not_override_when_mark_is_in_another_zone() -> None:
    hit = _run(2)  # the mark lies inside room 001's zone: the number beside it is not evidence
    assert (hit.room_token, hit.room_link) == ("006", "LEADER")
