"""Verbatim Приложение 2 strings and Russian formatting (93 §5.1–5.4).

Percentages: decimal comma, «%» without a space. Rows that partition the 132 parameters are rounded half-up to one
decimal and then balanced to exactly 100 % by moving 0,1 at a time to the rows with the largest *relative* rounding
error; this reproduces the sample's «84,8% / 13,6% / 1,6%» for 112 / 18 / 2 of 132 (plain rounding gives 1,5 % and a
99,9 % total, plain largest-remainder gives 84,9 %). Other rows are rounded half-up.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

TITLE_PREFIX = "ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № "
HEADER_LABELS = {
    "object": "Объект:",
    "address": "Адрес:",
    "case": "Номер надзорного дела:",
    "customer": "Застройщик:",
    "contractor": "Подрядчик:",
    "date": "Дата формирования:",
    "version": "Версия протокола:",
    "status": "Статус:",
    "scenario": "Тип проверки:",
}
STATUS_LINES = {
    "READY": "⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)",
    "VERIFYING": "🔄 ВЕРИФИКАЦИЯ В ПРОЦЕССЕ (дозагрузка возможна)",
    "COMPLETED": "☑️ ВЕРИФИКАЦИЯ ЗАВЕРШЕНА, ПРОТОКОЛ НЕ ФИНАЛИЗИРОВАН (дозагрузка возможна)",
    "FINALIZED": "🔒 ПРОТОКОЛ ФИНАЛИЗИРОВАН (дозагрузка невозможна)",
}
RECHECK_SUFFIX = " · выполняется инкрементальная проверка"

SECTION_TITLES = {
    1: "РАЗДЕЛ 1. СТАТУС ЗАГРУЗКИ ДОКУМЕНТОВ",
    2: "РАЗДЕЛ 2. СВОДНАЯ СТАТИСТИКА (С ПРОЦЕНТАМИ)",
    3: "РАЗДЕЛ 3. ПАРАМЕТРЫ, НЕ ПРОВЕРЕННЫЕ ИЗ-ЗА ОТСУТСТВИЯ ИД — {n}",
    4: "РАЗДЕЛ 4. КРИТИЧЕСКИЕ НАРУШЕНИЯ — {n}",
    5: "РАЗДЕЛ 5. СУЩЕСТВЕННЫЕ НАРУШЕНИЯ — {n}",
    6: "РАЗДЕЛ 6. ПОДОЗРЕНИЯ ИИ — {n}",
    7: "РАЗДЕЛ 7. РЕЗОЛЮТИВНАЯ ЧАСТЬ",
}
SUBSECTION_71 = "7.1. По критическим нарушениям"
SUBSECTION_72 = "7.2. По существенным нарушениям"

COLUMNS = {
    1: ("Тип документа", "Статус", "Загружено файлов", "Ожидается", "Комментарий"),
    2: ("Показатель", "Количество", "% от общего"),
    3: ("№", "Код", "Раздел", "Параметр", "Отсутствующий файл"),
    4: ("№", "Раздел", "Параметр (код)", "ПД", "РД", "ИД", "Отклонение", "Решение инспектора"),
    6: (
        "№",
        "Метод",
        "Описание",
        "ПД",
        "РД",
        "ИД",
        "Решение инспектора",
        "Причина отклонения",
        "Комментарий ИИ",
    ),
    71: ("№", "Вид работ", "Конкретная рекомендация"),
    72: ("№", "Вид нарушения", "Конкретная рекомендация"),
}

LOAD_STATUS_RU = {
    "UPLOADED": "✅ Полностью",
    "PARTIAL": "🟡 Частично",
    "MISSING": "❌ Отсутствует",
}
DECISION_RU = {
    "PENDING": "⏳ Ожидает",
    "CONFIRMED_VIOLATION": "✅ Подтверждено",
    "NEGATIVE_VERIFIED": "❌ Отклонено",
    "CLARIFICATION_REQUIRED": "❓ Требует уточнения",
}
NOT_APPLICABLE_CELL = "—"
NO_DATA_CELL = "нет данных"
DISCLAIMER = (
    "До подтверждения инспектором расхождения являются кандидатами и не являются основанием для приостановки "
    "работ или выдачи предписания (п. 9.2 ТЗ)"
)
SCENARIO_FOOTNOTE = "с учётом сценария {scenario}: сравнение выполнено по доступным стадиям"
# Body of a section (3–7, 7.1, 7.2) without rows: the heading keeps its «— 0», the text says so explicitly.
EMPTY_SECTION = "Не выявлено."


def scenario_line(scenario: str, scenario_ru: str) -> str:
    """«Тип проверки: Полный комплект (ПД, РД, ИД)» — the Russian label only, never the enum code."""
    return f"{HEADER_LABELS['scenario']} {scenario_ru or scenario}"


# Basis codes printed as «Основание» when a row has no free-text reason (enums.yaml CompletenessBasis has no labels).
COMPLETENESS_BASIS_RU = {
    "REGISTRY_MISSING": "Реестр документов не представлен",
    "REGISTRY_ROW_INVALID": "Строка реестра некорректна",
    "REGISTRY_HASH_MISMATCH": "Контрольная сумма файла не совпадает с реестром",
    "FILE_NOT_LISTED": "Файл отсутствует в реестре",
    "OBJECT_MISMATCH": "Документ относится к другому объекту",
    "REVISION_UNRESOLVED": "Актуальная редакция не определена",
    "APPROVAL_MISSING": "Нет отметки об утверждении",
    "SUPERSEDED_ONLY": "Представлены только замещённые редакции",
    "MANDATORY_SOURCE_MISSING": "Отсутствует обязательный источник данных",
    "DECLARED_NOT_RECEIVED": "Заявлен, но не получен",
    "CURRENT_REVISION_NOT_UPLOADED": "Актуальная редакция не загружена",
    "FILE_REJECTED": "Файл отклонён при загрузке",
    "SOURCE_UNREADABLE": "Источник не читается",
    "FILE_NOT_PROCESSED": "Файл не обработан",
    "VALUE_ABSTAINED": "Значение параметра не извлечено",
    "LOW_CONFIDENCE_SEMANTIC": "Низкая уверенность распознавания",
    "PARAM_DEACTIVATED": "Параметр отключён в версии Матрицы",
}
DOC_STAGE_LONG_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}
MANIFEST_STAGE_RU = {
    "PD": "ПД",
    "RD": "РД",
    "ID": "ИД",
    "RD_ID_MIXED": "РД/ИД (смешанный)",
    "UNKNOWN": "Не определена",
    "NONE": "Не определена",
}
SERVICE_STAGE_RU = "Служебный файл (вне стадий)"
NO_MISSING_STAGE_RU = "Все стадии представлены"


def basis_ru(code: Any) -> str:
    return COMPLETENESS_BASIS_RU.get(str(code), "—") if code else "—"


def file_stage_ru(stage: Any, manifest_stage: Any) -> str:
    """Stage cell of Приложение В: the resolved stage; for an unresolved one the manifest label
    («РД/ИД (смешанный)») or, for a service file, «Служебный файл»."""
    if stage:
        return DOC_STAGE_LONG_RU.get(str(stage), str(stage))
    if manifest_stage in (None, "", "UNKNOWN", "NONE"):
        return SERVICE_STAGE_RU
    return MANIFEST_STAGE_RU.get(str(manifest_stage), str(manifest_stage))


BANNER_TZ92 = "Не являются нарушениями до решения инспектора"
APPENDIX_TITLES = {
    "A": "ПРИЛОЖЕНИЕ А. РАЗДЕЛЬНЫЕ ТАБЛИЦЫ (п. 9.2 ТЗ)",
    "A1": "А.1. Комплектность и сопоставимость",
    "A2": "А.2. Предварительные кандидаты",
    "A3": "А.3. Подтверждённые инспектором нарушения",
    "A4": "А.4. Проверенные отрицательные результаты",
    "A5": "А.5. Гипотезы свободного поиска",
    "B": "ПРИЛОЖЕНИЕ Б. КАРТОЧКИ ДОКАЗАТЕЛЬСТВ",
    "V": "ПРИЛОЖЕНИЕ В. РЕЕСТР ВХОДНЫХ ФАЙЛОВ И ВЕРСИИ",
}


def ru_date(value: dt.date | dt.datetime) -> str:
    """«1 июля 2026 г.»"""
    return f"{value.day} {MONTHS_GENITIVE[value.month - 1]} {value.year} г."


def _q1(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def percent_text(value: Decimal | float) -> str:
    """«84,8%», «100%», «0%» (integral values without a decimal)."""
    d = _q1(Decimal(str(value)))
    if d == d.to_integral_value():
        return f"{int(d)}%"
    return f"{d:f}".replace(".", ",") + "%"


def percent_half_up(count: int, total: int) -> Decimal:
    if total <= 0:
        return Decimal(0)
    return _q1(Decimal(count) * 100 / Decimal(total))


def partition_percents(counts: Sequence[int], total: int) -> list[Decimal]:
    """Half-up per row, then balanced to 100,0 % (module docstring)."""
    return partition_percents_ex(counts, total)[0]


def partition_percents_ex(counts: Sequence[int], total: int) -> tuple[list[Decimal], list[int]]:
    """(percents, indices of the rows that carry a ±0,1 adjustment).

    One rule: round half-up; rows with the same count always get the same percent; the residual to 100,0 % is
    moved 0,1 at a time to the count group with the largest relative rounding error whose whole group fits the
    residual (so a tie of equal counts is never split). When no group fits, the row with the largest count takes it.
    """
    if total <= 0:
        return [Decimal(0) for _ in counts], []
    exact = [Decimal(c) * 100 / Decimal(total) for c in counts]
    rounded = [_q1(x) for x in exact]
    step = Decimal("0.1")
    residual = Decimal(100) - sum(rounded)
    adjusted: set[int] = set()
    guard = 0
    while residual != 0 and guard < 1000:
        guard += 1
        sign = 1 if residual > 0 else -1
        groups: dict[int, list[int]] = {}
        for i, c in enumerate(counts):
            if c > 0:
                groups.setdefault(c, []).append(i)
        if not groups:
            break
        fitting = {c: idx for c, idx in groups.items() if step * len(idx) <= abs(residual)}
        if fitting:

            def rel_err(c: int, fitting: dict[int, list[int]] = fitting) -> Decimal:
                i = fitting[c][0]
                return (exact[i] - rounded[i]) / exact[i]

            pick_count = max(fitting, key=lambda c: (sign * rel_err(c), -fitting[c][0]))
            picks = fitting[pick_count]
        else:
            picks = [max(range(len(counts)), key=lambda i: (counts[i], -i))]
        for i in picks:
            rounded[i] += sign * step
            residual -= sign * step
            adjusted.add(i)
    return rounded, sorted(adjusted)


ROUNDING_FOOTNOTE = (
    "Округление: проценты округлены до 0,1% (половина вверх), одинаковые количества дают одинаковый процент; "
    "для суммы строк разделов ровно 100% поправка {sign}0,1 п.п. отнесена к строке «{label}»"
)


SOURCE_ROLE_RU = {
    "EXPECTED": "ожидаемое",
    "ACTUAL": "фактическое",
    "SUPPORTING_EXPECTED": "дополнительно к ожидаемому",
    "SUPPORTING_ACTUAL": "дополнительно к фактическому",
}
STAGE_RU_SHORT = {"PD": "ПД", "RD": "РД", "ID": "ИД"}
MAX_BOXES_SHOWN = 4


def _num(value: float) -> str:
    return f"{float(value):.3f}".replace(".", ",")


def source_lines(sources: list[dict[str, Any]] | None) -> str:
    """Sources of an evidence card, one line each, with every field ТЗ §9.2 п.4 asks for: stage and role, file_id
    and name, page and sheet, шифр, редакция, approval status, SHA-256 of the file and the regions (bbox in
    normalised page coordinates x0 y0 x1 y1, top-left origin)."""
    lines = []
    for s in sources or []:
        stage = STAGE_RU_SHORT.get(str(s.get("stage")), str(s.get("stage")))
        role = SOURCE_ROLE_RU.get(str(s.get("role")), "")
        parts = [f"{stage}{f' ({role})' if role else ''}: {s.get('file_id')}"]
        if s.get("file_name"):
            parts[0] += f" «{s['file_name']}»"
        page = f"с. {s.get('pdf_page_number')}"
        if s.get("sheet_number") is not None:
            page += f", лист {s['sheet_number']}"
        parts.append(page)
        parts.append(f"шифр {s.get('document_code') or 'нет данных'}")
        parts.append(f"изм. {s.get('revision') or 'нет данных'}")
        approval = s.get("approval_status") or "нет данных"
        if s.get("approval_date"):
            approval += f" ({s['approval_date']})"
        parts.append(f"статус утверждения: {approval}")
        if s.get("file_sha256"):
            parts.append(f"SHA-256 {s['file_sha256']}")
        boxes = ((s.get("geometry") or {}).get("boxes")) or []
        if boxes:
            shown = "; ".join("[" + " ".join(_num(v) for v in b) + "]" for b in boxes[:MAX_BOXES_SHOWN])
            more = f" и ещё {len(boxes) - MAX_BOXES_SHOWN}" if len(boxes) > MAX_BOXES_SHOWN else ""
            parts.append(f"области ({len(boxes)}): {shown}{more}")
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def enum_ru(enum: str, code: Any) -> str:
    """The contract's Russian label of an enum code («HIGH» → «Высокий»); the code itself when unlabeled."""
    if code in (None, ""):
        return "—"
    from inspector_common.contracts.loader import load_enums

    try:
        value = load_enums()[enum].value(str(code))
    except (KeyError, ValueError):
        return str(code)
    return value.label_ru or str(code)


def risk_priority(risk: Any, priority: Any) -> str:
    return f"{enum_ru('RiskLevel', risk)} / {enum_ru('ReviewPriority', priority)}"


def a1_cells(r: dict[str, Any]) -> tuple[str, str, str]:
    """(status, missing stage, basis) cells of Приложение А.1, all in Russian."""
    status = enum_ru("ProtocolParamStatus", r.get("protocol_status"))
    stage = r.get("missing_stage")
    stage_cell = STAGE_RU_SHORT.get(str(stage), str(stage)) if stage else NO_MISSING_STAGE_RU
    basis = r.get("reason_ru") or basis_ru(r.get("completeness_basis"))
    return status, stage_cell, basis


def section_ru(code: Any) -> str:
    """Section cell of Приложение В: the ManifestSection label («КР», «Прочее»)."""
    return enum_ru("ManifestSection", code)
