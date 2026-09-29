"""T-GOLD fixture: the perfect submission built from the organizers' train gold and the 93 §2.3
perturbation cases, with their expected scores under the H1 defaults.

Expected values are exact analytic numbers (the formulas of scoring.py applied to the 10 public checks);
``report_93`` is the rounded figure printed in 93 §2.3. The self-test and the regression tests require
|measured − expected| ≤ ``TOLERANCE`` (float rounding only) and |measured − report_93| ≤ ``TOLERANCE_93``
(93 printed one or two decimals).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from inspector_common.contracts.models import SubmissionCheck
from inspector_eval.config import DEFAULT_CONFIG, ScoreConfig
from inspector_eval.data import ScoringContext, gold_for_object
from inspector_eval.scoring import ObjectScore, score_object

TOLERANCE = 1e-6
TOLERANCE_93 = 0.05
T_GOLD_OBJECT = "OBJ-TYUMENSKAYA-5-GOLD-SEED"
EVIDENCE_FIELDS = ("stage", "file_id", "pdf_page_number")


def perfect_submission(gold_rows: Sequence[Mapping[str, Any]], object_id: str) -> dict[str, Any]:
    """The organizer-schema projection of the gold rows (strict fields only, evidence without extras)."""
    checks = []
    for g in gold_for_object(gold_rows, object_id):
        row = {name: copy.deepcopy(g.get(name)) for name in SubmissionCheck.STRICT_FIELDS}
        row["evidence"] = [{k: e[k] for k in EVIDENCE_FIELDS} for e in g.get("evidence", [])]
        checks.append(row)
    return {"object_id": object_id, "checks": checks}


Builder = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    title_ru: str
    build: Builder
    expected_total: float
    expected_uncapped: float
    expected_gate: bool
    report_93: float | None = None  # rounded total printed in 93 §2.3 (None: not in 93)
    config_changes: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""


def _copy(doc: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(doc)


def _drop_314(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    s["checks"] = [c for c in s["checks"] if c["location"] != "314"]
    return s


def _warm_floor_to_ios4_077(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    for c in s["checks"]:
        if c["parameter_code"] == "FREE-HEATING-001":
            c.update(
                parameter_code="IOS4-077",
                criticality="Критическое (приостановка работ)",
                protocol_status="CRITICAL",
            )
    return s


def _room_314_own_page(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    for c in s["checks"]:
        if c["location"] == "314":
            for e in c["evidence"]:
                if e["stage"] == "RD":
                    e["pdf_page_number"] = 20
    return s


def _vent_chamber_wrong_code(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    for c in s["checks"]:
        if c["parameter_code"] == "IOS4-079":
            c["parameter_code"] = "IOS4-078"
    return s


def _hedge_both_codes(doc: dict[str, Any]) -> dict[str, Any]:
    s = _vent_chamber_wrong_code(doc)
    original = next(c for c in doc["checks"] if c["parameter_code"] == "IOS4-079")
    s["checks"].append(copy.deepcopy(original))
    return s


def _generic_values(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    for c in s["checks"]:
        c["pd_value"] = "Предусмотрено по ПД"
        c["rd_value"] = "Изменено в РД"
    return s


def _wrong_stage_and_excluded_file(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    s["checks"][0]["evidence"][1]["stage"] = "ID"
    s["checks"][1]["evidence"].append({"stage": "PD", "file_id": "F0149", "pdf_page_number": 1})
    return s


def _room_prefix(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    for c in s["checks"]:
        c["location"] = "пом. " + c["location"]
    return s


def _strip_leading_zero(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    for c in s["checks"]:
        c["location"] = c["location"].lstrip("0")
    return s


def _empty(doc: dict[str, Any]) -> dict[str, Any]:
    return {"object_id": doc["object_id"], "checks": []}


_ALIASES = {"IOS4-079": "ИОС4-79", "IOS4-078": "M-078"}


def _alias_codes(doc: dict[str, Any]) -> dict[str, Any]:
    s = _copy(doc)
    for c in s["checks"]:
        c["parameter_code"] = _ALIASES.get(c["parameter_code"], c["parameter_code"])
    return s


# F1 of 18/19 (B), 20/21 (F); integrity 10/13 (H with R1–R14 minus R9), 12/13 (L strict: R11 fails).
_F1_B = 2 * 1.0 * 0.9 / 1.9
_F1_F = 2 * (10 / 11) * 1.0 / (10 / 11 + 1.0)

CASES: tuple[Case, ...] = (
    Case("A", "Идеальная копия эталона", _copy, 100.0, 100.0, False, 100.0),
    Case(
        "B",
        "Пропущено помещение 314 (критическое)",
        _drop_314,
        59.0,
        60 * _F1_B + 13.5 + 13.5 + 10,
        True,
        59.0,
    ),
    Case(
        "C",
        "Тёплый пол отнесён к IOS4-077 (старая маршрутизация M-077)",
        _warm_floor_to_ios4_077,
        64.0,
        64.0,
        False,
        64.0,
    ),
    Case(
        "D",
        "Помещение 314: собственная страница РД 20 вместо групповой 18",
        _room_314_own_page,
        99.25,
        99.25,
        False,
        99.25,
    ),
    Case("E", "Венткамера 012: IOS4-078 вместо IOS4-079", _vent_chamber_wrong_code, 59.0, 91.0, True, 59.0),
    Case(
        "F",
        "Страховка: 012 под обоими кодами IOS4-078 и IOS4-079",
        _hedge_both_codes,
        60 * _F1_F + 40,
        60 * _F1_F + 40,
        False,
        97.1,
    ),
    Case(
        "G",
        "Шаблонные значения («Предусмотрено по ПД» / «Изменено в РД»)",
        _generic_values,
        95.0,
        95.0,
        False,
        95.0,
    ),
    Case(
        "H",
        "Неверная стадия + ссылка на исключённый файл F0149 (правила R1–R14)",
        _wrong_stage_and_excluded_file,
        60 + 14.25 + 15 + 10 * 10 / 13,
        60 + 14.25 + 15 + 10 * 10 / 13,
        False,
        None,
        note="93 printed 95.5 with its 8-rule prototype; see case H8",
    ),
    Case(
        "H8",
        "То же, набор из 8 правил прототипа 93",
        _wrong_stage_and_excluded_file,
        95.5,
        95.5,
        False,
        95.5,
        {"integrity_rules": "proto8"},
    ),
    Case("I", "Место «пом. 012» (нормализация light)", _room_prefix, 100.0, 100.0, False, 100.0),
    Case(
        "I-strict",
        "Место «пом. 012» без нормализации (strict)",
        _room_prefix,
        10.0,
        10.0,
        True,
        None,
        {"location_norm": "strict"},
        note="93: «0 if their scorer does not normalise»; integrity still earns 10",
    ),
    Case("J", "Место «12» вместо «012» (light)", _strip_leading_zero, 59.0, 91.0, True, 59.0),
    Case(
        "J-relaxed",
        "Место «12» вместо «012» (relaxed)",
        _strip_leading_zero,
        100.0,
        100.0,
        False,
        None,
        {"location_norm": "relaxed"},
    ),
    Case("K", "Пустой ответ", _empty, 0.0, 0.0, True, None, note="93 §4.10"),
    Case(
        "L", "Коды-синонимы (ИОС4-79, M-078), light", _alias_codes, 100.0, 100.0, False, None, note="93 §4.10"
    ),
    Case(
        "L-strict",
        "Коды-синонимы (ИОС4-79, M-078), strict",
        _alias_codes,
        60 * 0.4 + 15 * 0.4 + 15 * 0.4 + 10 * 12 / 13,
        60 * 0.4 + 15 * 0.4 + 15 * 0.4 + 10 * 12 / 13,
        True,
        None,
        {"code_norm": "strict"},
        note="93 §4.10: aliases fail in strict",
    ),
)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: Case
    score: ObjectScore

    @property
    def ok(self) -> bool:
        return (
            abs(self.score.total - self.case.expected_total) <= TOLERANCE
            and abs(self.score.total_uncapped - self.case.expected_uncapped) <= TOLERANCE
            and self.score.gate_triggered == self.case.expected_gate
            and (self.case.report_93 is None or abs(self.score.total - self.case.report_93) <= TOLERANCE_93)
        )

    def as_dict(self) -> dict[str, Any]:
        comps = self.score.components
        return {
            "case": self.case.case_id,
            "title_ru": self.case.title_ru,
            "config_changes": dict(self.case.config_changes),
            "f1": comps["finding_detection_f1"],
            "localisation": comps["source_localization_exact_file_page"],
            "value_status": comps["normalized_value_and_status_accuracy"],
            "integrity": comps["document_integrity_and_split_handling"],
            "gate_triggered": self.score.gate_triggered,
            "missed_checkpoints": [f"{c.parameter_code}/{c.location}" for c in self.score.gate.missed],
            "total_uncapped": self.score.total_uncapped,
            "total": self.score.total,
            "expected_total": self.case.expected_total,
            "report_93": self.case.report_93,
            "ok": self.ok,
            "note": self.case.note,
        }


def run_cases(
    gold_rows: Sequence[Mapping[str, Any]],
    ctx: ScoringContext,
    base: ScoreConfig = DEFAULT_CONFIG,
    object_id: str = T_GOLD_OBJECT,
    cases: Sequence[Case] = CASES,
) -> list[CaseResult]:
    gold = gold_for_object(gold_rows, object_id)
    perfect = perfect_submission(gold, object_id)
    results = []
    for case in cases:
        cfg = base.replace(**case.config_changes) if case.config_changes else base
        doc = case.build(perfect)
        results.append(CaseResult(case, score_object(gold, doc, ctx, cfg, object_id=object_id, extras=False)))
    return results
