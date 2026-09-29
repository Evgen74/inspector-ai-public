"""Development fixtures of the comparison engine (hand-made layout/table artifacts that follow the contracts).

They let ``compare``/``export`` run end to end before the real extractors (AG-02B layout, AG-02C tables) land:

    inspector-batch compare --object OBJ-TYUMENSKAYA-5-GOLD-SEED --fixture tyumen

A fixture is never a recognition result: its artifacts say so in ``ext.fixture``, compare records the source
in the findings trace, and fixtures exist only for TRAIN objects (never for the hidden test, 97 §2.17).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Fixture:
    name: str
    object_id: str
    layout_dir: Path
    tables_dir: Path | None
    description_ru: str


FIXTURES: dict[str, Fixture] = {
    "tyumen": Fixture(
        name="tyumen",
        object_id="OBJ-TYUMENSKAYA-5-GOLD-SEED",
        layout_dir=_HERE / "tyumen" / "layout",
        tables_dir=_HERE / "tyumen" / "tables",
        description_ru=(
            "Тюменская 5: разметка листов F0171 (ПД ОВ), F0201 (РД ОВ1), F0202 (РД ОВ2.1), F0198 (ИД) "
            "по фактам страниц отчёта 95 и зарегистрированным зонам разметки организаторов; экспликации "
            "помещений F0201 с. 17–18 и F0202 с. 17 из текстового слоя"
        ),
    ),
}


def get_fixture(name: str) -> Fixture:
    try:
        return FIXTURES[name]
    except KeyError:
        raise KeyError(f"unknown compare fixture {name!r}; known: {sorted(FIXTURES)}") from None
