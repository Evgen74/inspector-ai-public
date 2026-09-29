"""`inspector-batch run --workers N` (upload jobs cap the shared host at 2 workers)."""

from __future__ import annotations

from inspector_batch.cli import build_parser


def test_run_accepts_workers() -> None:
    args = build_parser().parse_args(["run", "--workers", "2", "--steps", "inventory,recognize"])
    assert args.workers == 2
    assert args.steps == ["inventory", "recognize"]


def test_run_workers_default_is_unset() -> None:
    assert build_parser().parse_args(["run"]).workers is None
