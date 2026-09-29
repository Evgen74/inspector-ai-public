"""Submission validation: JSON Schemas (organizer, strict, extended) and integrity rules R1–R15 (93 §4.6).

The organizer schema (vendored byte-identical, sha256-pinned in packages/contracts/vendored.yaml) decides
R1: a prediction that fails it scores 0 on every component (93 §4.2). The strict and extended schemas
are ours; their failures are reported for the exporter but do not change the score.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from inspector_common.contracts.codes import ParameterCodeError, is_canonical_code, parse_free_code
from inspector_common.contracts.loader import enum_mappings, load_enums, validation_errors
from inspector_common.contracts.status import is_consistent
from inspector_eval.config import ScoreConfig
from inspector_eval.data import ScoringContext
from inspector_eval.normalize import (
    normalize_code,
    normalize_criticality,
    normalize_location,
)

SCHEMAS: dict[str, str] = {
    "organizer": "submission.organizer",
    "strict": "submission.strict",
    "extended": "submission.extended",
}

RuleStatus = Literal["PASS", "FAIL", "WARN", "NOT_EVALUATED"]

# Rule id → Russian title (user-facing, shown in reports).
RULE_TITLES: dict[str, str] = {
    "R1": "Ответ соответствует схеме организаторов",
    "R2": "Объект ответа входит в ожидаемую выборку",
    "R3": "Файлы доказательств есть в манифесте",
    "R4": "Файлы доказательств относятся к тому же объекту",
    "R5": "Не цитируются исключённые и нецитируемые файлы",
    "R6": "Доказательство — PDF, номер страницы в пределах документа",
    "R7": "Стадия доказательства согласована со стадией файла в манифесте",
    "R8": "Дубликаты цитируются только через основной файл группы",
    "R9": "Не цитируются устаревшие редакции",
    "R10": "Нет повторяющихся ключей (код параметра, место)",
    "R11": "Коды параметров из каталога или вида FREE-<ТЕМА>-<NNN>",
    "R12": "Критичность совпадает с каталогом",
    "R13": "Статус протокола согласован с меткой и критичностью",
    "R14": "Нет файлов другой выборки",
    "R15": "Место записано по принятой грамматике (предупреждение)",
}
RULE_IDS: tuple[str, ...] = tuple(RULE_TITLES)
WARNING_ONLY_RULES = frozenset({"R15"})
# The 8 rules of the 93 §2.3 prototype (reproduces its case H exactly).
PROTO8_RULES = frozenset({"R2", "R3", "R4", "R5", "R6", "R7", "R10", "R11"})


@dataclass(slots=True)
class Violation:
    detail_ru: str
    check_index: int | None = None
    parameter_code: str | None = None
    location: str | None = None
    file_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "check_index": self.check_index,
                "parameter_code": self.parameter_code,
                "location": self.location,
                "file_id": self.file_id,
                "detail_ru": self.detail_ru,
            }.items()
            if v is not None
        }


@dataclass(slots=True)
class RuleResult:
    rule: str
    status: RuleStatus = "PASS"
    counted: bool = True
    violations: list[Violation] = field(default_factory=list)
    note_ru: str | None = None

    @property
    def title_ru(self) -> str:
        return RULE_TITLES[self.rule]

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "title_ru": self.title_ru,
            "status": self.status,
            "counted": self.counted,
            "violations": [v.as_dict() for v in self.violations],
        }
        if self.note_ru:
            out["note_ru"] = self.note_ru
        return out


@dataclass(slots=True)
class SchemaReport:
    errors: dict[str, list[str]]

    @property
    def organizer_valid(self) -> bool:
        return not self.errors["organizer"]

    def as_dict(self) -> dict[str, Any]:
        return {name: {"valid": not errs, "errors": errs[:50]} for name, errs in self.errors.items()}


@dataclass(slots=True)
class IntegrityReport:
    rules: dict[str, RuleResult]
    share: float
    hard: float
    rule_set: str

    def value(self, mode: str) -> float:
        return self.hard if mode == "hard" else self.share

    @property
    def failed(self) -> list[str]:
        return [r for r, res in self.rules.items() if res.status == "FAIL"]

    def as_dict(self) -> dict[str, Any]:
        counted = [r for r in self.rules.values() if r.counted and r.status in ("PASS", "FAIL")]
        return {
            "rule_set": self.rule_set,
            "share": self.share,
            "hard": self.hard,
            "passed": sum(1 for r in counted if r.status == "PASS"),
            "counted": len(counted),
            "failed": self.failed,
            "rules": [r.as_dict() for r in self.rules.values()],
        }


def validate_schemas(document: Any) -> SchemaReport:
    return SchemaReport({name: validation_errors(schema, document) for name, schema in SCHEMAS.items()})


# ── helpers ──────────────────────────────────────────────────────────────────────────────────


def _checks(document: Any) -> list[Mapping[str, Any]]:
    if isinstance(document, Mapping) and isinstance(document.get("checks"), list):
        return [c for c in document["checks"] if isinstance(c, Mapping)]
    return []


def _evidence(check: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    ev = check.get("evidence")
    return [e for e in ev if isinstance(e, Mapping)] if isinstance(ev, list) else []


def _duplicate_representatives(
    manifest: Mapping[str, Mapping[str, Any]], excluded: frozenset[str]
) -> dict[str, str]:
    """file_id → representative file_id for members of a duplicate group (duplicate_group or equal sha256)."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for file_id, row in manifest.items():
        if row.get("duplicate_group"):
            groups[("group", str(row["duplicate_group"]))].append(file_id)
        if row.get("sha256"):
            groups[("sha256", str(row["sha256"]))].append(file_id)
    representative: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        kept = sorted(m for m in members if m not in excluded) or sorted(members)
        for member in members:
            representative.setdefault(member, kept[0])
    return representative


_ROOM = re.compile(r"^-?\d+(?:[.\-]\d+)*[а-яa-z]?$", re.IGNORECASE)
_LOCATION_GRAMMAR = (
    _ROOM,
    re.compile(r"^OBJECT$"),
    re.compile(r"^Корпус [^,]+(?:, этаж -?\d+)?(?:, оси .+)?$"),
    re.compile(r"^Этаж -?\d+(?:, оси .+)?$"),
    re.compile(r"^Подземная автостоянка(?:, этаж -?\d+)?(?:, оси .+)?$"),
    re.compile(r"^(?:Оси|оси) .+$"),
)
_FORBIDDEN_LOCATION_PREFIX = re.compile(r"^\s*(?:пом\.?|помещение|№)", re.IGNORECASE)


def location_grammar_problem(location: Any) -> str | None:
    """None when the location follows 93 §2.7; otherwise a Russian explanation (R15, warning only)."""
    if not isinstance(location, str) or not location:
        return "место не указано"
    if location != location.strip():
        return "пробелы в начале или конце"
    if _FORBIDDEN_LOCATION_PREFIX.match(location):
        return "лишний префикс («пом.», «помещение», «№»); нужен номер как напечатан"
    if not any(p.match(location) for p in _LOCATION_GRAMMAR):
        return "не соответствует грамматике мест (номер помещения, Корпус/Этаж/оси, OBJECT)"
    return None


# ── integrity rules ──────────────────────────────────────────────────────────────────────────


def check_integrity(
    document: Any,
    ctx: ScoringContext,
    cfg: ScoreConfig,
    *,
    schema: SchemaReport | None = None,
) -> IntegrityReport:
    """Evaluate R1–R15 on one submission document. Tolerates schema-invalid input (R1 FAIL)."""
    schema = schema or validate_schemas(document)
    rules = {rule: RuleResult(rule) for rule in RULE_IDS}
    active = PROTO8_RULES if cfg.integrity_rules == "proto8" else frozenset(RULE_IDS) - WARNING_ONLY_RULES
    for rule_id, result in rules.items():
        result.counted = rule_id in active
    rules["R15"].counted = False

    def fail(rule: str, violation: Violation) -> None:
        rules[rule].status = "FAIL"
        rules[rule].violations.append(violation)

    # R1 schema
    if not schema.organizer_valid:
        for message in schema.errors["organizer"][:20]:
            fail("R1", Violation(detail_ru=f"ошибка схемы: {message}"))

    object_id = document.get("object_id") if isinstance(document, Mapping) else None
    object_split = ctx.split_policy.split_of(object_id) if isinstance(object_id, str) else None

    # R2 object in the expected split
    if not isinstance(object_id, str) or object_id not in ctx.split_policy.splits.get(cfg.expected_split, ()):
        fail("R2", Violation(detail_ru=f"объект {object_id!r} не входит в выборку {cfg.expected_split}"))

    manifest = ctx.manifest
    excluded = ctx.split_policy.excluded_file_ids
    non_citable = {v.code for v in load_enums()["AnnotationStatus"].values if v.attrs.get("citable") is False}
    representatives = _duplicate_representatives(manifest, excluded)
    free_string = ctx.free_criticality
    seen_keys: dict[tuple[str, str], int] = {}

    checks = _checks(document)
    for index, check in enumerate(checks):
        raw_code = check.get("parameter_code")
        raw_location = check.get("location")
        code = normalize_code(raw_code, cfg.code_norm)
        where = {"check_index": index, "parameter_code": str(raw_code), "location": str(raw_location)}

        # evidence rules R3–R9, R14
        for ev in _evidence(check):
            file_id = ev.get("file_id")
            stage = ev.get("stage")
            page = ev.get("pdf_page_number")
            row = manifest.get(file_id) if isinstance(file_id, str) else None
            fid = str(file_id)
            if row is None:
                fail("R3", Violation(detail_ru=f"файл {fid} отсутствует в манифесте", file_id=fid, **where))
                fail(
                    "R4",
                    Violation(
                        detail_ru=f"файл {fid} не принадлежит объекту {object_id}", file_id=fid, **where
                    ),
                )
            elif row.get("object_id") != object_id:
                fail(
                    "R4",
                    Violation(
                        detail_ru=f"файл {fid} относится к объекту {row.get('object_id')}",
                        file_id=fid,
                        **where,
                    ),
                )
            if fid in excluded:
                fail("R5", Violation(detail_ru=f"файл {fid} исключён организаторами", file_id=fid, **where))
            elif row is not None and row.get("annotation_status") in non_citable:
                fail(
                    "R5",
                    Violation(
                        detail_ru=f"файл {fid} ({row.get('annotation_status')}) не может быть доказательством",
                        file_id=fid,
                        **where,
                    ),
                )
            if row is None:
                continue
            pages = row.get("pdf_pages")
            if row.get("extension") != ".pdf":
                fail(
                    "R6",
                    Violation(detail_ru=f"файл {fid} не PDF ({row.get('extension')})", file_id=fid, **where),
                )
            elif not isinstance(page, int) or not isinstance(pages, int) or not 1 <= page <= pages:
                fail(
                    "R6",
                    Violation(
                        detail_ru=f"страница {page} вне диапазона 1…{pages} файла {fid}", file_id=fid, **where
                    ),
                )
            manifest_stage = row.get("stage")
            stage_ok = stage == manifest_stage or (manifest_stage == "RD_ID_MIXED" and stage in ("RD", "ID"))
            if not stage_ok:
                fail(
                    "R7",
                    Violation(
                        detail_ru=f"стадия {stage} не согласована со стадией {manifest_stage} файла {fid}",
                        file_id=fid,
                        **where,
                    ),
                )
            rep = representatives.get(fid)
            if rep is not None and rep != fid:
                fail(
                    "R8",
                    Violation(
                        detail_ru=f"файл {fid} — дубликат, цитируйте основной файл {rep}",
                        file_id=fid,
                        **where,
                    ),
                )
            if ctx.superseded_file_ids is not None and fid in ctx.superseded_file_ids:
                fail("R9", Violation(detail_ru=f"файл {fid} — устаревшая редакция", file_id=fid, **where))
            if object_split is not None and row.get("split") != object_split:
                fail(
                    "R14",
                    Violation(
                        detail_ru=f"файл {fid} из выборки {row.get('split')}, объект — {object_split}",
                        file_id=fid,
                        **where,
                    ),
                )

        # R10 duplicate keys
        key = (code, normalize_location(raw_location, cfg.location_norm))
        if key in seen_keys:
            fail("R10", Violation(detail_ru=f"ключ повторяет проверку №{seen_keys[key]}", **where))
        else:
            seen_keys[key] = index

        # R11 codes
        known_matrix = is_canonical_code(code) and code in ctx.catalog
        known_free = False
        if code.startswith("FREE-"):
            try:
                parse_free_code(code)
                known_free = True
            except ParameterCodeError:
                known_free = False
        if not (known_matrix or known_free):
            fail(
                "R11", Violation(detail_ru=f"код {raw_code!r} не из каталога и не FREE-<ТЕМА>-<NNN>", **where)
            )
        elif str(raw_code) != code:
            rules["R11"].note_ru = "есть коды не в каноническом виде каталога (засчитаны по нормализации)"

        # R12 criticality
        criticality = check.get("criticality")
        expected_crit = (
            ctx.catalog_criticality(code) if known_matrix else (free_string if known_free else None)
        )
        if expected_crit is not None and normalize_criticality(
            criticality, cfg.criticality_norm
        ) != normalize_criticality(expected_crit, cfg.criticality_norm):
            fail(
                "R12",
                Violation(detail_ru=f"критичность {criticality!r}, по каталогу {expected_crit!r}", **where),
            )

        # R13 protocol status vs label (and criticality for violations)
        label = check.get("violation_label")
        status = check.get("protocol_status")
        mapping = enum_mappings()["protocol_status_by_label"]
        if label in mapping:
            if status is None or not is_consistent(label, status):
                fail("R13", Violation(detail_ru=f"статус {status!r} не согласован с меткой {label}", **where))
            elif label == "VIOLATION_PRESENT" and isinstance(criticality, str):
                wanted = (
                    "CRITICAL"
                    if normalize_criticality(criticality, "relaxed") == "критическое"
                    else "WARNING"
                )
                if status != wanted:
                    fail(
                        "R13",
                        Violation(
                            detail_ru=f"при критичности {criticality!r} ожидается статус {wanted}, указан {status}",
                            **where,
                        ),
                    )

        # R15 location grammar (warning only)
        problem = location_grammar_problem(raw_location)
        if problem is not None:
            rules["R15"].status = "WARN"
            rules["R15"].violations.append(Violation(detail_ru=problem, **where))

    if ctx.superseded_file_ids is None:
        rules["R9"].status = "NOT_EVALUATED"
        rules["R9"].note_ru = "нет данных о редакциях (передайте --superseded из реестра редакций)"

    counted = [r for r in rules.values() if r.counted and r.status in ("PASS", "FAIL")]
    passed = sum(1 for r in counted if r.status == "PASS")
    share = passed / len(counted) if counted else 0.0
    hard = 1.0 if counted and passed == len(counted) else 0.0
    if not checks:
        # 93 §4.10: an empty prediction scores 0; vacuous integrity is not rewarded.
        share = hard = 0.0
    return IntegrityReport(rules=rules, share=share, hard=hard, rule_set=cfg.integrity_rules)
