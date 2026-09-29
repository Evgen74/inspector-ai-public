"""Protocol between the `inspector-batch` CLI (AG-00) and the packages that implement its commands.

The CLI owns argument parsing of the common options, logging, the run directory and the
hidden-test guard. Each command is implemented in its owner's package, in a module named
``batch`` with two functions per command:

    def add_<command>_arguments(parser: argparse.ArgumentParser) -> None: ...
    def run_<command>(args: argparse.Namespace, ctx: BatchContext) -> int: ...

Owners change only their own module; the dispatch table in ``inspector_batch.commands`` is fixed.
Import heavy dependencies (pymupdf, onnxruntime, …) inside ``run_<command>``, not at module level,
so that ``inspector-batch --help`` stays fast.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from inspector_common.settings import Settings


class CommandNotImplementedError(RuntimeError):
    """Raised by a stub command; the CLI prints the Russian catalogue message and exits 69."""

    def __init__(self, command: str, owner: str) -> None:
        self.command = command
        self.owner = owner
        super().__init__(f"command {command!r} is not implemented yet (owner {owner})")


@dataclass(frozen=True, slots=True)
class BatchContext:
    """What every command receives besides its parsed arguments."""

    settings: Settings
    run_id: str
    run_dir: Path
    objects: tuple[str, ...]
    hidden_run: bool
    log: logging.Logger
    extra: dict[str, object] = field(default_factory=dict)
