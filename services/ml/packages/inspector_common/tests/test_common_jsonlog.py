from __future__ import annotations

import io
import json
import logging

from inspector_common.jsonlog import configure_logging, current_context, get_logger, log_context


def test_json_lines_carry_bound_context() -> None:
    stream = io.StringIO()
    configure_logging(level="DEBUG", fmt="json", stream=stream)
    log = get_logger("inspector.test")
    with log_context(run_id="r-1", object_id="OBJ-X"):
        with log_context(file_id="F0001"):
            log.info("inventory.file", extra={"pages": 18, "stage": "ID"})
        assert current_context() == {"run_id": "r-1", "object_id": "OBJ-X"}
    log.warning("outside")
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0]["event"] == "inventory.file"
    assert lines[0]["run_id"] == "r-1" and lines[0]["file_id"] == "F0001" and lines[0]["pages"] == 18
    assert lines[0]["level"] == "INFO" and lines[0]["ts"].endswith("Z")
    assert "run_id" not in lines[1]


def test_configure_is_idempotent_and_console_format() -> None:
    stream = io.StringIO()
    configure_logging(fmt="console", stream=stream)
    configure_logging(fmt="console", stream=stream)
    names = [h.get_name() for h in logging.getLogger().handlers]
    assert names.count("inspector") == 1
    get_logger("x").info("привет", extra={"k": 1})
    assert "привет" in stream.getvalue() and "k=1" in stream.getvalue()


def test_extra_keys_that_collide_with_logrecord_attributes_never_raise() -> None:
    stream = io.StringIO()
    configure_logging(fmt="json", stream=stream)
    get_logger("x.collide").info("bench.step", extra={"msg": "A 1/2", "name": "n", "files": 3})
    # A logger created with the stdlib before configure_logging() is upgraded too.
    logging.getLogger("x.plain.created.late").warning("w", extra={"args": [1]})
    first, second = (json.loads(line) for line in stream.getvalue().splitlines()[-2:])
    assert first["event"] == "bench.step" and first["msg_"] == "A 1/2" and first["name_"] == "n"
    assert first["files"] == 3 and first["logger"] == "x.collide"
    assert second["args_"] == [1]


def test_exception_is_serialised() -> None:
    stream = io.StringIO()
    configure_logging(fmt="json", stream=stream)
    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("x").exception("failed")
    record = json.loads(stream.getvalue().splitlines()[-1])
    assert record["exc_type"] == "ValueError" and "boom" in record["exc"]
