"""inspector_tables package basics: owner, CLI arguments, output contracts."""

from __future__ import annotations

import argparse

import inspector_tables
from inspector_common.contracts import loader
from inspector_common.contracts.models import table_columns
from inspector_tables import batch


def test_package_imports_and_owner() -> None:
    assert inspector_tables.__version__
    assert batch.OWNER == "AG-02C"


def test_tables_arguments_parse_with_defaults() -> None:
    parser = argparse.ArgumentParser()
    batch.add_tables_arguments(parser)
    args = parser.parse_args(["--table-type", "EXPLICATION", "--tokens-from", "r1", "--pages", "1-3"])
    assert args.table_types == ["EXPLICATION"] and args.workers == 3 and args.tokens_from == ["r1"]
    assert args.cache_tokens is True and args.pages == "1-3"


def test_output_contract_is_available() -> None:
    assert "table_artifacts" in loader.schema_names()
    assert table_columns("EXPLICATION")[:3] == ("room_no", "name", "area_m2")
    # every table type the command writes is a contract TableType
    types = {v.code for v in loader.load_enums()["TableType"].values}
    assert set(batch.TABLE_TYPES) <= types
