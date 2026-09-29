"""Hidden-test integrity guard for inspector-batch (97 §2.17, 93 §4.9).

The TEST_HIDDEN object ids come from the organizers' split_policy.json at runtime; no hidden-object
identifier is written in code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from inspector_batch.commands import CommandSpec


class HiddenTestRefusedError(RuntimeError):
    def __init__(self, object_id: str, reason: str) -> None:
        self.object_id = object_id
        self.reason = reason
        super().__init__(f"{object_id}: {reason}")


@dataclass(frozen=True, slots=True)
class SplitPolicy:
    train: tuple[str, ...]
    hidden: tuple[str, ...]
    excluded_file_ids: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> SplitPolicy:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            train=tuple(raw.get("TRAIN_PUBLIC", [])),
            hidden=tuple(raw.get("TEST_HIDDEN", [])),
            excluded_file_ids=tuple(raw.get("excluded_file_ids", [])),
        )


def resolve_objects(requested: list[str], policy: SplitPolicy, all_objects: bool = False) -> tuple[str, ...]:
    """Explicit objects as given; ``--all`` = every split_policy object (TRAIN, then hidden); with neither,
    the TRAIN objects only (never hidden by default). The hidden policy is checked afterwards."""
    if all_objects:
        if requested:
            raise ValueError("укажите либо --object, либо --all")
        return tuple(dict.fromkeys((*policy.train, *policy.hidden)))
    if requested:
        known = set(policy.train) | set(policy.hidden)
        unknown = [o for o in requested if o not in known]
        if unknown:
            raise ValueError(f"объекты отсутствуют в split_policy.json: {', '.join(unknown)}")
        return tuple(dict.fromkeys(requested))
    return policy.train


def check_hidden_policy(
    spec: CommandSpec, objects: tuple[str, ...], policy: SplitPolicy, hidden_run: bool
) -> bool:
    """Return True when the run touches a hidden object; raise when the command may not."""
    touched = [o for o in objects if o in policy.hidden]
    if not touched:
        return False
    if spec.hidden_policy == "refuse":
        raise HiddenTestRefusedError(
            touched[0], f"команда «{spec.name}» запрещена для скрытой тестовой выборки"
        )
    if spec.hidden_policy == "confirm" and not hidden_run:
        raise HiddenTestRefusedError(
            touched[0],
            f"команда «{spec.name}» по скрытой выборке выполняется только в замороженном прогоне с флагом --hidden-run",
        )
    return True
