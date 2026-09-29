"""Argument helpers shared by `inspector-score` and `inspector-batch score` (import-light on purpose:
`inspector-batch --help` builds every command parser)."""

from __future__ import annotations

import argparse

from inspector_eval.config import CHOICES, DEFAULT_CONFIG, ScoreConfig


def parse_bool(text: str) -> bool:
    low = text.strip().lower()
    if low in ("true", "1", "yes", "да"):
        return True
    if low in ("false", "0", "no", "нет"):
        return False
    raise argparse.ArgumentTypeError("ожидается true или false")


def add_variant_arguments(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("варианты оценки (по умолчанию гипотеза H1, отчёт 93 §2.2)")
    d = DEFAULT_CONFIG
    g.add_argument(
        "--key",
        choices=CHOICES["key"],
        default=d.key,
        help="Единица F1: k1 ключ, k3 группа, k4 ключ и страница",
    )
    g.add_argument(
        "--group-rule",
        choices=CHOICES["group_rule"],
        default=d.group_rule,
        help="Правило найденной группы для k3",
    )
    g.add_argument(
        "--loc-metric", choices=CHOICES["loc_metric"], default=d.loc_metric, help="Метрика локализации"
    )
    g.add_argument(
        "--with-stage",
        type=parse_bool,
        default=d.loc_with_stage,
        metavar="true|false",
        help="Сравнивать страницы доказательств вместе со стадией",
    )
    g.add_argument(
        "--value-threshold", type=float, default=d.value_threshold, help="Порог сходства текстовых значений"
    )
    g.add_argument(
        "--value-norm", choices=CHOICES["value_norm"], default=d.value_norm, help="Нормализация значений"
    )
    g.add_argument(
        "--location-norm",
        choices=CHOICES["location_norm"],
        default=d.location_norm,
        help="Нормализация места",
    )
    g.add_argument(
        "--code-norm", choices=CHOICES["code_norm"], default=d.code_norm, help="Нормализация кода параметра"
    )
    g.add_argument(
        "--criticality-norm",
        choices=CHOICES["criticality_norm"],
        default=d.criticality_norm,
        help="Нормализация критичности",
    )
    g.add_argument("--gate", choices=CHOICES["gate"], default=d.gate, help="Вариант гейта критических точек")
    g.add_argument(
        "--integrity", choices=CHOICES["integrity"], default=d.integrity, help="Доля правил или жёсткий режим"
    )
    g.add_argument(
        "--integrity-rules",
        choices=CHOICES["integrity_rules"],
        default=d.integrity_rules,
        help="Набор правил целостности",
    )


def config_from_args(args: argparse.Namespace, expected_split: str = "TRAIN_PUBLIC") -> ScoreConfig:
    return ScoreConfig(
        key=args.key,
        group_rule=args.group_rule,
        loc_metric=args.loc_metric,
        loc_with_stage=args.with_stage,
        value_threshold=args.value_threshold,
        value_norm=args.value_norm,
        location_norm=args.location_norm,
        code_norm=args.code_norm,
        criticality_norm=args.criticality_norm,
        gate=args.gate,
        integrity=args.integrity,
        integrity_rules=args.integrity_rules,
        expected_split=expected_split,
    )
