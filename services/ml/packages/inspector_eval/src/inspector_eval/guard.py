"""Hidden-test guard of inspector-score (93 §4.9, 97 §2.17, CLAUDE.md rule 4).

Nothing about a TEST_HIDDEN object is scored or displayed unless BOTH hold:
1. the caller passes the explicit ``--hidden-final`` switch, and
2. the run carries the frozen flag: a RunManifest (``run_manifest.json`` or the submission sidecar,
   schemas/run_manifest.schema.json) that validates, lists the object, has a ``config_hash`` and a
   non-empty ``freeze_tag`` that exists as a git tag in this repository (e.g. «hidden-run-freeze»).

Hidden object ids are read from split_policy.json at runtime; no hidden identifier is written here.
The check runs on object ids only (``--objects``, gold rows, the prediction's ``object_id``), before any
other content is read or printed.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.paths import repo_root
from inspector_eval.data import InputError, SplitPolicy, read_json


class HiddenAccessRefusedError(RuntimeError):
    """Refused access to a TEST_HIDDEN object; ``reason_ru`` is shown to the user.

    ``code`` is the error-catalogue code: HIDDEN_TEST_ACCESS_DENIED when the explicit ``--hidden-final`` switch
    is missing (or the object is not in the frozen run), HIDDEN_FINAL_NOT_FROZEN when the switch is given but
    the frozen-run proof (a valid RunManifest with an existing ``freeze_tag``) is missing or invalid.
    """

    def __init__(self, object_id: str, reason_ru: str, code: str = "HIDDEN_TEST_ACCESS_DENIED") -> None:
        self.object_id = object_id
        self.reason_ru = reason_ru
        self.code = code
        super().__init__(f"{object_id}: {reason_ru}")

    def error(self):  # -> InspectorError (imported lazily: the guard stays import-light)
        from inspector_common.errors import InspectorError

        if self.code == "HIDDEN_FINAL_NOT_FROZEN":
            return InspectorError("HIDDEN_FINAL_NOT_FROZEN", reason=self.reason_ru)
        return InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id=self.object_id)


def git_tag_exists(tag: str, root: Path | None = None) -> bool:
    """True when ``tag`` is a tag of the repository (``git rev-parse --verify refs/tags/<tag>``)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root or repo_root()), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


@dataclass(frozen=True, slots=True)
class FrozenRun:
    run_id: str
    freeze_tag: str
    config_hash: str
    object_ids: tuple[str, ...]


def load_frozen_run(path: Path, tag_exists: Callable[[str], bool] = git_tag_exists) -> FrozenRun:
    """Read and check the frozen-run flag of a RunManifest; raises ``HiddenAccessRefusedError``-ready errors."""
    try:
        manifest = read_json(path)
    except InputError as exc:
        raise ValueError(exc.message_ru) from None
    errors = validation_errors("run_manifest", manifest)
    if errors:
        raise ValueError(f"манифест прогона {path} не соответствует контракту: {errors[0]}")
    tag = manifest.get("freeze_tag")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError(f"прогон {manifest.get('run_id')} не заморожен (в манифесте нет freeze_tag)")
    if not tag_exists(tag):
        raise ValueError(f"тег заморозки «{tag}» не найден в git-репозитории")
    return FrozenRun(
        run_id=str(manifest["run_id"]),
        freeze_tag=tag,
        config_hash=str(manifest["config_hash"]),
        object_ids=tuple(str(o["object_id"]) for o in manifest.get("objects", [])),
    )


def check_access(
    object_ids: Iterable[Any],
    policy: SplitPolicy,
    *,
    hidden_final: bool = False,
    run_manifest: Path | None = None,
    tag_exists: Callable[[str], bool] = git_tag_exists,
) -> FrozenRun | None:
    """Return None when no hidden object is involved, the FrozenRun when access is granted; else raise."""
    touched = sorted({str(o) for o in object_ids if o is not None} & policy.hidden)
    if not touched:
        return None
    first = touched[0]
    if not hidden_final:
        raise HiddenAccessRefusedError(
            first,
            "оценка и показ результатов по скрытой выборке запрещены; допускаются только после заморозки "
            "прогона с явным ключом --hidden-final",
        )
    if run_manifest is None:
        raise HiddenAccessRefusedError(
            first,
            "нужен манифест замороженного прогона (--run-manifest) с freeze_tag и config_hash",
            "HIDDEN_FINAL_NOT_FROZEN",
        )
    try:
        frozen = load_frozen_run(run_manifest, tag_exists)
    except ValueError as exc:
        raise HiddenAccessRefusedError(first, str(exc), "HIDDEN_FINAL_NOT_FROZEN") from None
    missing = [o for o in touched if o not in frozen.object_ids]
    if missing:
        raise HiddenAccessRefusedError(missing[0], f"объект не входит в замороженный прогон {frozen.run_id}")
    return frozen


def objects_in(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        str(r.get("object_id")) for r in rows if isinstance(r, Mapping) and r.get("object_id") is not None
    }
