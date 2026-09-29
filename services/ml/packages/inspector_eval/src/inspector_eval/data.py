"""Inputs of inspector-score: organizer package files (read-only) and the prediction files.

Everything is read from local files; nothing is written next to the organizer data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import enum_mappings, load_enums, validation_errors
from inspector_common.hashing import sha256_file
from inspector_common.paths import DataPaths

WEIGHT_KEYS: tuple[str, ...] = (
    "finding_detection_f1",
    "source_localization_exact_file_page",
    "normalized_value_and_status_accuracy",
    "document_integrity_and_split_handling",
)
DEFAULT_GATE_CAP = 59.0
_CAP_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*из\s*100")


class InputError(RuntimeError):
    """An input file is missing or unreadable; ``message_ru`` is shown to the user."""

    def __init__(self, message_ru: str) -> None:
        self.message_ru = message_ru
        super().__init__(message_ru)


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputError(f"Файл не найден: {path}") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InputError(f"Файл не является корректным JSON: {path} ({exc})") from None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InputError(f"Файл не найден: {path}") from None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise InputError(f"Строка {lineno} файла {path} не является корректным JSON ({exc})") from None
    return rows


@dataclass(frozen=True, slots=True)
class SplitPolicy:
    """split_policy.json. Hidden object ids are only ever read from here, never hard-coded."""

    splits: Mapping[str, tuple[str, ...]]
    excluded_file_ids: frozenset[str]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SplitPolicy:
        splits = {
            name: tuple(raw.get(name, ()))
            for name in load_enums()["ManifestSplit"].codes
            if isinstance(raw.get(name, ()), list | tuple)
        }
        return cls(splits=splits, excluded_file_ids=frozenset(raw.get("excluded_file_ids", ())))

    @property
    def hidden(self) -> frozenset[str]:
        return frozenset(self.splits.get("TEST_HIDDEN", ()))

    @property
    def train(self) -> frozenset[str]:
        return frozenset(self.splits.get("TRAIN_PUBLIC", ()))

    def split_of(self, object_id: str) -> str | None:
        for name, objects in self.splits.items():
            if object_id in objects:
                return name
        return None


@dataclass(frozen=True, slots=True)
class ScoringContext:
    """Reference data every scoring call needs (manifest, catalog, split policy, weights)."""

    manifest: Mapping[str, Mapping[str, Any]]
    catalog: Mapping[str, Mapping[str, Any]]
    split_policy: SplitPolicy
    weights: Mapping[str, float]
    gate_cap: float = DEFAULT_GATE_CAP
    superseded_file_ids: frozenset[str] | None = None  # R9 input (revision resolver); None = not evaluated
    input_hashes: Mapping[str, str] = field(default_factory=dict)

    @property
    def free_criticality(self) -> str:
        return str(enum_mappings()["free_search"]["criticality_string"])

    def catalog_criticality(self, code: str) -> str | None:
        row = self.catalog.get(code)
        return None if row is None else row.get("criticality")

    def section_of(self, code: str) -> str:
        row = self.catalog.get(code)
        if row is not None:
            return str(row.get("pd_section"))
        if code.startswith("FREE-"):
            return "СВОБОДНЫЙ ПОИСК"
        return "НЕИЗВЕСТНЫЙ КОД"


def parse_gate_cap(text: str | None) -> float:
    """«… ограничивается 59 из 100» → 59.0 (falls back to 59 when the text has no number)."""
    if text:
        match = _CAP_PATTERN.search(text)
        if match:
            return float(match.group(1).replace(",", "."))
    return DEFAULT_GATE_CAP


def _keyed(rows: list[dict[str, Any]], key: str, path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or not row.get(key):
            raise InputError(f"Строка {index} файла {path} не содержит поле {key}")
        out[str(row[key])] = row
    return out


def load_weights(path: Path) -> tuple[dict[str, float], float]:
    raw = read_json(path)
    weights = raw.get("weights_points", {}) if isinstance(raw, dict) else {}
    missing = [k for k in WEIGHT_KEYS if k not in weights]
    if missing:
        raise InputError(f"В {path} нет весов: {', '.join(missing)}")
    return {k: float(weights[k]) for k in WEIGHT_KEYS}, parse_gate_cap(raw.get("critical_miss_gate"))


def load_context(
    paths: DataPaths,
    *,
    manifest_path: Path | None = None,
    catalog_path: Path | None = None,
    split_policy_path: Path | None = None,
    weights_path: Path | None = None,
    superseded_path: Path | None = None,
    require_weights: bool = True,
) -> ScoringContext:
    """Reference data from the organizer package (or explicit paths).

    ``require_weights=False`` (integrity checks need no weights) tolerates a missing scoring summary: the
    weights are then empty and the gate cap is the default.
    """
    manifest_path = manifest_path or paths.manifest_path
    catalog_path = catalog_path or paths.catalog_path
    split_policy_path = split_policy_path or paths.split_policy_path
    weights_path = weights_path or paths.scoring_summary_path
    manifest = _keyed(read_jsonl(manifest_path), "file_id", manifest_path)
    catalog = _keyed(read_jsonl(catalog_path), "parameter_code", catalog_path)
    raw_policy = read_json(split_policy_path)
    if not isinstance(raw_policy, dict):
        raise InputError(f"Файл {split_policy_path} должен быть JSON-объектом")
    policy = SplitPolicy.from_dict(raw_policy)
    if require_weights or Path(weights_path).is_file():
        weights, cap = load_weights(weights_path)
    else:
        weights, cap = {}, DEFAULT_GATE_CAP
    superseded = None
    if superseded_path is not None:
        raw = read_json(superseded_path)
        ids = raw.get("superseded_file_ids", raw) if isinstance(raw, dict) else raw
        superseded = frozenset(str(x) for x in ids)
    hashes = {
        "manifest_sha256": sha256_file(manifest_path),
        "catalog_sha256": sha256_file(catalog_path),
        "split_policy_sha256": sha256_file(split_policy_path),
    }
    if Path(weights_path).is_file():
        hashes["scoring_summary_sha256"] = sha256_file(weights_path)
    if paths.submission_schema_path.is_file():
        hashes["package_submission_schema_sha256"] = sha256_file(paths.submission_schema_path)
    return ScoringContext(
        manifest=manifest,
        catalog=catalog,
        split_policy=policy,
        weights=weights,
        gate_cap=cap,
        superseded_file_ids=superseded,
        input_hashes=hashes,
    )


# ── gold ──────────────────────────────────────────────────────────────────────────────────────


def validate_gold(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Contract errors of gold rows (schemas/gold_check.schema.json), prefixed with the row number."""
    problems: list[str] = []
    for index, row in enumerate(rows, start=1):
        problems.extend(f"строка {index}: {msg}" for msg in validation_errors("gold_check", row))
    return problems


def load_gold(path: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(path) if str(path).endswith(".jsonl") else read_json(path)
    if not isinstance(rows, list):
        raise InputError(f"Эталон {path} должен быть списком строк (JSONL или JSON-массив)")
    problems = validate_gold(rows)
    if problems:
        raise InputError(f"Эталон {path} не соответствует контракту gold_check: " + "; ".join(problems[:5]))
    return rows


def gold_for_object(rows: Iterable[Mapping[str, Any]], object_id: str) -> list[Mapping[str, Any]]:
    """Score-eligible gold rows of one object (``score_eligible`` absent counts as eligible)."""
    return [r for r in rows if r.get("object_id") == object_id and r.get("score_eligible", True) is not False]


# ── predictions ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Prediction:
    object_id: str | None
    document: Any
    path: Path | None
    sha256: str | None


def _prediction_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise InputError(f"Ответ не найден: {path}")
    base = path / "submission" if (path / "submission").is_dir() else path
    return sorted(p for p in base.glob("*.json") if not p.name.endswith(".sidecar.json"))


def peek_object_ids(path: Path) -> list[str | None]:
    """Only the ``object_id`` of each prediction file (for the hidden-test guard, before anything else)."""
    ids: list[str | None] = []
    for file in _prediction_files(path):
        doc = read_json(file)
        ids.append(doc.get("object_id") if isinstance(doc, dict) else None)
    return ids


def load_predictions(path: Path) -> list[Prediction]:
    out: list[Prediction] = []
    for file in _prediction_files(path):
        doc = read_json(file)
        object_id = doc.get("object_id") if isinstance(doc, dict) else None
        out.append(Prediction(object_id=object_id, document=doc, path=file, sha256=sha256_file(file)))
    return out
