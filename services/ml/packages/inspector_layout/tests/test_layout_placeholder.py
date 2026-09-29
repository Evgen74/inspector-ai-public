"""AG-00 skeleton tests for inspector_layout (AG-02B replaces/extends them)."""

from __future__ import annotations

import argparse

import inspector_layout
from inspector_common.contracts import loader
from inspector_layout import batch


def test_package_imports_and_owner() -> None:
    assert inspector_layout.__version__
    assert batch.OWNER == "AG-02B"


def test_layout_arguments_parse_with_defaults() -> None:
    parser = argparse.ArgumentParser()
    batch.add_layout_arguments(parser)
    args = parser.parse_args(["--file", "F0201"])
    assert args.files == ["F0201"] and args.workers == 3


def test_output_contract_is_available() -> None:
    assert "layout_artifacts" in loader.schema_names()
