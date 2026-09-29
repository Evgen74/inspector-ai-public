"""Process exit codes shared by the CLIs (inspector-batch, inspector-score, tools)."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1  # unexpected failure
    USAGE = 2  # bad arguments (argparse also exits 2)
    GATE_TRIGGERED = 3  # inspector-score: a missed approved critical checkpoint (93 §4.1)
    SCHEMA_INVALID = 4  # an artifact failed its contract schema
    HIDDEN_TEST_REFUSED = 5  # a scoring/tuning action was refused on TEST_HIDDEN (93 §4.9)
    DATA_MISSING = 6  # organizer data or models not found
    NOT_IMPLEMENTED = 69  # EX_UNAVAILABLE: the command is a stub owned by another agent
