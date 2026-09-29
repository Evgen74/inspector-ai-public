"""Fixed dispatch table of inspector-batch subcommands (owner of this file: AG-00).

Each entry points at ``<module>.add_<name>_arguments`` / ``<module>.run_<name>`` in the owner's
package (protocol: inspector_common.batch). Changing a command's implementation never requires
editing this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HiddenPolicy = Literal["allow", "confirm", "refuse"]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    module: str
    owner: str
    help_ru: str
    # Hidden-test policy (97 §2.17): "allow" = inventory/format/speed checks only; "confirm" = only in
    # the single frozen hidden run with --hidden-run; "refuse" = never on TEST_HIDDEN objects.
    hidden_policy: HiddenPolicy


COMMANDS: dict[str, CommandSpec] = {
    spec.name: spec
    for spec in (
        CommandSpec(
            "inventory",
            "inspector_registry.batch",
            "AG-01",
            "Инвентаризация: манифест, наличие файлов, sha256, стадии, архивы",
            "allow",
        ),
        CommandSpec(
            "recognize",
            "inspector_docproc.batch",
            "AG-02A",
            "Распознавание: текстовый слой, OCR, штампы, таблицы, извлечение значений",
            "confirm",
        ),
        CommandSpec(
            "layout",
            "inspector_layout.batch",
            "AG-02B",
            "Разметка чертежей: штампы и QR, соответствие лист↔страница, помещения, марки, слои САПР, облака изменений",
            "confirm",
        ),
        CommandSpec(
            "tables",
            "inspector_tables.batch",
            "AG-02C",
            "Типизированные таблицы (экспликации, ТЭП, спецификации, АОСР, реестры ИД) и извлечение значений",
            "confirm",
        ),
        CommandSpec(
            "compare",
            "inspector_compare.batch",
            "AG-04",
            "Сравнение ПД/РД/ИД по матрице 132 параметров и свободный поиск",
            "confirm",
        ),
        CommandSpec(
            "export",
            "inspector_compare.batch",
            "AG-04",
            "Выгрузка: ответ (полный и строгий), sidecar, протокол по Приложению 2",
            "confirm",
        ),
        CommandSpec(
            "score",
            "inspector_eval.batch",
            "AG-10",
            "Локальная оценка ответа: 60/15/15/10 и гейт критических нарушений",
            "refuse",
        ),
        CommandSpec(
            "bench", "inspector_docproc.batch", "AG-02A", "Бенчмарк распознавания и скорости", "allow"
        ),
        CommandSpec(
            "run",
            "inspector_batch.pipeline",
            "AG-00",
            "Сквозной прогон по обучающим объектам: recognize → layout → tables → compare → export → score",
            "refuse",
        ),
    )
}
