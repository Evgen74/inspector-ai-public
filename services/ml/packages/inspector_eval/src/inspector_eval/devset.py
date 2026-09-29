"""Dev-set registry for calibration (95 §5.1, 93 §4.8): T-GOLD (organizer train gold) and N-GOLD (team labels).

- T-GOLD: ``public_train_checks.jsonl`` of the organizer package, pinned by the file sha256.
- N-GOLD: our labels of the unlabeled train object, in the format of
  ``docs/analysis/95_novoslob_label_seed.json`` (``{"meta": …, "candidates": [ {id, parameter_code, location,
  pd_value, rd_value, id_value, evidence[], label, label_comment, …} ]}``). ``label`` is a ViolationLabel or
  ``UNSURE``; UNSURE and unlabeled items are listed but excluded from metrics (95 §5.3). Once frozen, the
  labels are pinned by a canonical hash; relabelling after the freeze fails loudly (TEST_SET_HASH_MISMATCH).

The registry never holds a TEST_HIDDEN object: loading refuses one (split_policy.json decides).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.contracts.codes import ParameterCodeError, is_free_code, parse_parameter_code
from inspector_common.contracts.loader import load_enums, validation_errors
from inspector_common.contracts.status import (
    criticality_level_for_string,
    missing_document_status,
    violation_protocol_status,
)
from inspector_common.errors import InspectorError
from inspector_common.hashing import sha256_file, sha256_json
from inspector_common.paths import DataPaths
from inspector_eval.data import InputError, ScoringContext, SplitPolicy, read_json, read_jsonl

DEVSET_DIR = Path(__file__).resolve().parent / "devsets"
REGISTRY_PATH = DEVSET_DIR / "registry.json"
UNSURE = "UNSURE"
TEAM_LABEL_FROZEN = "TEAM_LABEL_FROZEN"  # GoldStatus code for frozen team labels (enums.yaml, owner AG-10)
STAGE_VALUE_FIELDS = {"PD": "pd_value", "RD": "rd_value", "ID": "id_value"}


@dataclass(frozen=True, slots=True)
class DevSet:
    id: str
    object_id: str
    split: str
    format: str  # gold_checks_jsonl | label_seed_json
    path_base: str  # package_data | devsets | repo
    path: str
    badge_ru: str
    positives_only: bool
    frozen: bool
    labels_sha256: str | None
    groups_path: str | None = None
    folds: Mapping[str, Sequence[str]] | None = None  # code-prefix groups for within-object folds
    frozen_at: str | None = None
    file_sha256: str | None = None  # sha256 of the label file at freeze time (label_seed_json sets)

    def resolve(self, paths: DataPaths, relative: str | None = None) -> Path:
        rel = relative or self.path
        if Path(rel).is_absolute():
            return Path(rel)
        if self.path_base == "package_data":
            return paths.package_data_dir / rel
        if self.path_base == "devsets":
            return DEVSET_DIR / rel
        from inspector_common.paths import repo_root

        return repo_root() / rel

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DevSet:
        return cls(
            id=str(raw["id"]),
            object_id=str(raw["object_id"]),
            split=str(raw.get("split", "TRAIN_PUBLIC")),
            format=str(raw["format"]),
            path_base=str(raw["path"]["base"]),
            path=str(raw["path"]["relative"]),
            badge_ru=str(raw.get("badge_ru", "")),
            positives_only=bool(raw.get("positives_only", False)),
            frozen=bool(raw.get("frozen", False)),
            labels_sha256=raw.get("labels_sha256"),
            groups_path=(raw.get("groups_path") or {}).get("relative"),
            folds=raw.get("folds"),
            frozen_at=raw.get("frozen_at"),
            file_sha256=raw.get("file_sha256"),
        )


@dataclass(slots=True)
class DevSetRows:
    devset: DevSet
    gold_rows: list[dict[str, Any]]
    excluded: list[dict[str, Any]] = field(default_factory=list)  # UNSURE / unlabeled items (listed only)
    labels_sha256: str | None = None
    hash_ok: bool | None = None  # None when the set is not frozen
    file_sha256: str | None = None
    file_hash_ok: bool | None = None  # None when the set is not frozen or no file hash was pinned

    @property
    def positives(self) -> int:
        return sum(1 for r in self.gold_rows if r.get("violation_label") == "VIOLATION_PRESENT")

    def summary(self) -> dict[str, Any]:
        d = self.devset
        return {
            "id": d.id,
            "object_id": d.object_id,
            "badge_ru": d.badge_ru,
            "format": d.format,
            "rows": len(self.gold_rows),
            "positives": self.positives,
            "excluded_items": len(self.excluded),
            "positives_only": d.positives_only,
            "frozen": d.frozen,
            "labels_sha256": self.labels_sha256,
            "hash_ok": self.hash_ok,
            "file_sha256": self.file_sha256,
            "file_hash_ok": self.file_hash_ok,
            "folds": dict(d.folds) if d.folds else None,
        }


def load_registry(path: Path = REGISTRY_PATH, policy: SplitPolicy | None = None) -> list[DevSet]:
    raw = read_json(path)
    devsets = [DevSet.from_dict(item) for item in raw.get("devsets", [])]
    ids = [d.id for d in devsets]
    if len(set(ids)) != len(ids):
        raise InputError(f"В реестре наборов {path} повторяются идентификаторы: {ids}")
    if policy is not None:
        for d in devsets:
            if d.object_id in policy.hidden:
                raise InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id=d.object_id)
    return devsets


def get_devset(devset_id: str, path: Path = REGISTRY_PATH, policy: SplitPolicy | None = None) -> DevSet:
    for d in load_registry(path, policy):
        if d.id == devset_id:
            return d
    raise InputError(f"Набор {devset_id!r} не найден в реестре {path}")


# ── seed-format labels → gold rows ───────────────────────────────────────────────────────────

_ROOM_TOKEN = re.compile(r"^-?\d+(?:[.\-]\d+)*[а-яa-z]?$", re.IGNORECASE)


def location_type_for(location: str) -> str:
    """Heuristic LocationType of a labelled location (93 §2.7 grammar); not used for scoring."""
    text = location.strip()
    low = text.casefold()
    if text == "OBJECT":
        return "OBJECT"
    if _ROOM_TOKEN.match(text):
        return "ROOM"
    if "оси" in low or "в/о" in low:
        return "AXES"
    if "этаж" in low:
        return "FLOOR"
    if low.startswith("корпус") or "автостоянка" in low:
        return "BUILDING"
    return "ELEMENT"


def labelled_items(document: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """(scorable items with a ViolationLabel, excluded items: UNSURE, unlabeled or ``scorable: false``)."""
    labels = set(load_enums()["ViolationLabel"].codes)
    used, excluded = [], []
    for item in document.get("candidates", []):
        ok = item.get("label") in labels and item.get("scorable", True) is not False
        (used if ok else excluded).append(item)
    return used, excluded


def labels_hash(items: Sequence[Mapping[str, Any]]) -> str:
    """Canonical hash of the labelled items (order-independent, by id)."""
    return sha256_json(sorted((dict(i) for i in items), key=lambda i: str(i.get("id"))))


def seed_item_to_gold(
    item: Mapping[str, Any], object_id: str, split: str, ctx: ScoringContext, *, frozen: bool = False
) -> dict[str, Any]:
    """One labelled seed item → a gold_check row (validated against the contract).

    Rows of a frozen set carry ``gold_status = TEAM_LABEL_FROZEN`` (GoldStatus, owner AG-10); rows of a set
    that is still being labelled carry no gold_status. The scorer treats both as approved for the gate
    simulation (``scoring.is_approved_checkpoint``); they are never organizer gold.
    """
    raw_code = str(item["parameter_code"]).strip()
    if is_free_code(raw_code.upper()):
        code = raw_code.upper()
        param_id = None
        matrix_scope = "FREE_SEARCH"
        criticality = ctx.free_criticality
    else:
        try:
            parsed = parse_parameter_code(raw_code)
        except ParameterCodeError as exc:
            raise InputError(f"{item.get('id')}: {exc}") from None
        code, param_id, matrix_scope = parsed.canonical, parsed.param_id, "MATRIX"
        criticality = ctx.catalog_criticality(code)
        if criticality is None:
            raise InputError(f"{item.get('id')}: код {code} отсутствует в каталоге")
    label = str(item["label"])
    status = item.get("protocol_status")
    if status is None:
        if label == "VIOLATION_PRESENT":
            status = violation_protocol_status(criticality_level_for_string(criticality) or "")
        elif label == "NO_VIOLATION":
            status = "OK"
        elif label == "COMPARISON_IMPOSSIBLE":
            status = "COMPARISON_IMPOSSIBLE"
        else:  # MISSING_DOCUMENT: stages without a value and without evidence are the missing ones
            cited = {e.get("stage") for e in item.get("evidence", [])}
            missing = [s for s, f in STAGE_VALUE_FIELDS.items() if item.get(f) is None and s not in cited]
            if not missing:
                raise InputError(f"{item.get('id')}: для MISSING_DOCUMENT укажите protocol_status")
            status = missing_document_status(missing)
    location = str(item["location"])
    row: dict[str, Any] = {
        "check_id": str(item["id"]),
        "finding_group_id": str(item.get("finding_group_id") or item["id"]),
        "object_id": object_id,
        "split": split,
        "matrix_scope": matrix_scope,
        "parameter_id": param_id,
        "parameter_code": code,
        "location_type": item.get("location_type") or location_type_for(location),
        "location": location,
        "pd_value": item.get("pd_value"),
        "rd_value": item.get("rd_value"),
        "id_value": item.get("id_value"),
        "comparison_result": item.get("comparison_result"),
        "violation_label": label,
        "protocol_status": status,
        "criticality": criticality,
        "score_eligible": True,
        "evidence": [
            {"stage": e["stage"], "file_id": e["file_id"], "pdf_page_number": e["pdf_page_number"]}
            for e in item.get("evidence", [])
        ],
    }
    if frozen:
        row["gold_status"] = TEAM_LABEL_FROZEN
    errors = validation_errors("gold_check", row)
    if errors:
        raise InputError(f"{item.get('id')}: метка не соответствует контракту gold_check: {errors[0]}")
    return row


def load_devset(devset: DevSet, paths: DataPaths, ctx: ScoringContext, *, verify: bool = True) -> DevSetRows:
    """Gold rows of one dev set. A frozen set whose hash changed raises TEST_SET_HASH_MISMATCH."""
    if devset.object_id in ctx.split_policy.hidden:
        raise InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id=devset.object_id)
    source = devset.resolve(paths)
    if devset.format == "gold_checks_jsonl":
        digest = sha256_file(source) if source.is_file() else None
        rows = [r for r in read_jsonl(source) if r.get("object_id") == devset.object_id]
        excluded: list[dict[str, Any]] = []
    elif devset.format == "label_seed_json":
        document = read_json(source)
        used, skipped = labelled_items(document)
        digest = labels_hash(used)
        rows = [seed_item_to_gold(i, devset.object_id, devset.split, ctx, frozen=devset.frozen) for i in used]
        excluded = [
            {"id": i.get("id"), "label": i.get("label"), "parameter_code": i.get("parameter_code")}
            for i in skipped
        ]
    else:
        raise InputError(f"Неизвестный формат набора {devset.id}: {devset.format}")
    file_digest = sha256_file(source) if source.is_file() else None
    hash_ok = file_ok = None
    if devset.frozen:
        hash_ok = digest == devset.labels_sha256
        if devset.file_sha256 is not None:
            # Any byte change of a frozen label file (even of an unscored item) is a change of the test set.
            file_ok = file_digest == devset.file_sha256
        if verify and not (hash_ok and file_ok is not False):
            raise InspectorError("TEST_SET_HASH_MISMATCH", test_set=devset.id)
    return DevSetRows(devset, rows, excluded, digest, hash_ok, file_digest, file_ok)


def load_all(
    paths: DataPaths, ctx: ScoringContext, registry: Path = REGISTRY_PATH, *, verify: bool = True
) -> list[DevSetRows]:
    return [load_devset(d, paths, ctx, verify=verify) for d in load_registry(registry, ctx.split_policy)]


def freeze(
    devset_id: str, paths: DataPaths, ctx: ScoringContext, registry: Path = REGISTRY_PATH, *, now: str
) -> str:
    """Pin the current labels of a dev set (writes ``frozen``, ``labels_sha256``, ``file_sha256``, ``frozen_at``).

    A team label set with UNRESOLVED items (labellers of one kind disagree) cannot be frozen.
    """
    raw = read_json(registry)
    for item in raw.get("devsets", []):
        if item.get("id") != devset_id:
            continue
        devset = DevSet.from_dict(item)
        if devset.frozen:
            raise InputError(f"Набор {devset_id} уже заморожен ({devset.labels_sha256})")
        rows = load_devset(devset, paths, ctx, verify=False)
        if devset.format == "label_seed_json":
            unresolved = [
                str(i.get("id"))
                for i in read_json(devset.resolve(paths)).get("candidates", [])
                if (i.get("adjudication") or {}).get("method") == "UNRESOLVED"
            ]
            if unresolved:
                raise InputError(f"Набор {devset_id}: спорные метки не разрешены ({', '.join(unresolved)})")
        if not rows.gold_rows:
            raise InputError(f"Набор {devset_id} пуст: замораживать нечего")
        item.update(
            frozen=True, labels_sha256=rows.labels_sha256, file_sha256=rows.file_sha256, frozen_at=now
        )
        registry.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(rows.labels_sha256)
    raise InputError(f"Набор {devset_id!r} не найден в реестре {registry}")
