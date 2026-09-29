"""inspector_hypothesis — Module 5 «свободный поиск гипотез» (owner AG-07).

- FREE-<TOPIC>-<NNN> findings: evidence-bound element changes outside the matrix (:mod:`free`).
- Logical_Rules in IAI-Logic v1, three-valued (:mod:`logic`, :mod:`rules`, 12 seed rules in ``data/``).
- SUSPICION records per ТЗ §9.5 and their protocol rows (:mod:`suspicion`).

Entry point: :func:`run_hypotheses` (see :mod:`engine`).
"""

from __future__ import annotations

__version__ = "1.0.0"

from inspector_hypothesis.engine import HypothesisConfig, HypothesisResult, run_hypotheses
from inspector_hypothesis.free import FreeConfig
from inspector_hypothesis.inputs import (
    DocumentInfo,
    HypothesisInputs,
    MemoryPageSource,
    PageText,
    RunPageSource,
    page_text_from_tokens,
)
from inspector_hypothesis.suspicion import Suspicion

__all__ = [
    "DocumentInfo",
    "FreeConfig",
    "HypothesisConfig",
    "HypothesisInputs",
    "HypothesisResult",
    "MemoryPageSource",
    "PageText",
    "RunPageSource",
    "Suspicion",
    "__version__",
    "page_text_from_tokens",
    "run_hypotheses",
]
