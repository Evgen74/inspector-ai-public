"""Structured JSON logging on top of the standard library.

One JSON object per line on stderr with a stable field set (ts, level, logger, event, plus the
bound context: run_id, object_id, file_id, page_no, request_id, …). Context is bound with
``log_context(...)`` and travels through contextvars, so it survives threads started inside it.

    configure_logging(level="INFO", fmt="json")
    log = get_logger(__name__)
    with log_context(run_id="r1", object_id="OBJ-…"):
        log.info("inventory.done", extra={"files": 58})
"""

from __future__ import annotations

import contextvars
import logging
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType
from typing import Any

import orjson

_CONTEXT: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "inspector_log_context", default=MappingProxyType({})
)

# Attributes every LogRecord has; anything else passed via `extra=` is emitted as a field.
_RESERVED = frozenset(
    vars(logging.LogRecord("x", logging.INFO, __file__, 0, "", None, None)).keys() | {"message", "asctime"}
)


class SafeLogger(logging.Logger):
    """A Logger whose ``extra=`` fields can never crash a run.

    The standard library raises ``KeyError`` when an ``extra`` key collides with a LogRecord attribute
    (``msg``, ``name``, ``args``, ``module``, …). A logging call must not stop a batch run (least of all the
    single frozen hidden run), so a colliding key is emitted with a trailing underscore instead
    (``extra={"msg": …}`` → field ``msg_``).
    """

    def makeRecord(
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        extra: Mapping[str, object] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        if extra:
            extra = {(f"{key}_" if key in _RESERVED else key): value for key, value in extra.items()}
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)


def _install_safe_loggers() -> None:
    """Make every logger (existing and future, except the root) a SafeLogger (idempotent)."""
    logging.setLoggerClass(SafeLogger)
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if type(logger) is logging.Logger:
            logger.__class__ = SafeLogger  # same layout: SafeLogger only overrides makeRecord


_install_safe_loggers()


def _utc_iso(created: float) -> str:
    seconds = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(created))
    return f"{seconds}.{int((created % 1) * 1000):03d}Z"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_iso(record.created),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(_CONTEXT.get())
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload, default=str, option=orjson.OPT_NON_STR_KEYS).decode("utf-8")


class ConsoleFormatter(logging.Formatter):
    """Human-readable single line for local runs."""

    def format(self, record: logging.LogRecord) -> str:
        fields = dict(_CONTEXT.get())
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                fields[key] = value
        tail = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"{_utc_iso(record.created)} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if tail:
            line = f"{line} | {tail}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str = "INFO", fmt: str = "json", stream: Any = None) -> None:
    """Install one handler on the root logger (idempotent)."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    handler.set_name("inspector")
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == "inspector":
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    _install_safe_loggers()  # loggers created with logging.getLogger() before this module was imported


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if type(logger) is logging.Logger:
        logger.__class__ = SafeLogger
    return logger


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind fields to every log line emitted inside the block."""
    merged = {**_CONTEXT.get(), **{k: v for k, v in fields.items() if v is not None}}
    token = _CONTEXT.set(merged)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current_context() -> dict[str, Any]:
    return dict(_CONTEXT.get())
