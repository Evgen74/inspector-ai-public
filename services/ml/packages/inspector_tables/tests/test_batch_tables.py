"""`inspector-batch tables` end to end on small real TRAIN files: contract-valid artifacts and values."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspector_common.contracts.loader import validate
from inspector_common.contracts.models import ExtractedValue, TableArtifacts
from inspector_tables.testing import train_path

pytestmark = pytest.mark.data
OBJ = "OBJ-TYUMENSKAYA-5-GOLD-SEED"


def test_tables_command_writes_contract_valid_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if train_path("F0154") is None:
        pytest.skip("organizer data not found")
    from inspector_batch import cli
    from inspector_common.settings import Settings

    code = cli.main(["--data-root", str(Settings().data_root), "--runs-root", str(tmp_path / "runs"), "--log-format", "console",
                     "--run-id", "t", "tables", "--object", OBJ, "--file", "F0154", "--file", "F0196", "--file", "F0198",
                     "--workers", "1", "--no-cache-tokens", "--table-type", "TEP", "--table-type", "AOSR",
                     "--table-type", "EXPLICATION", "--table-type", "BINDER"])  # fmt: skip
    assert code == 0
    run = tmp_path / "runs" / "t"
    out = capsys.readouterr().out
    assert "Таблицы: файлов 3" in out
    arts = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (run / "tables").glob("*.json")}
    assert set(arts) == {"F0154", "F0196", "F0198"}
    for a in arts.values():
        validate("table_artifacts", a)
        TableArtifacts.model_validate(a)
    assert arts["F0198"]["stage"] == "ID"  # RD_ID_MIXED resolved per file by AG-01's rules, never guessed
    assert arts["F0196"]["stage"] == "ID"
    types = {t["table_type"] for t in arts["F0154"]["tables"]}
    assert types == {"TEP"}
    assert [t["table_type"] for t in arts["F0196"]["tables"]] == ["AOSR"]
    values = [
        json.loads(line)
        for line in (run / "values" / f"{OBJ}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for v in values:
        validate("extracted_value", v)
        ExtractedValue.model_validate(v)
    tep = [v for v in values if v["fact_key"] == "tep.value" and v.get("param_code") == "SPZU-027"]
    assert [(v["value_norm"]["value"], v["value_norm"]["unit"], v["page_no"]) for v in tep] == [
        (3158.02, "м²", 13)
    ]
    refs = {v["value_raw"] for v in values if v["fact_key"] == "aosr.doc_ref"}
    assert refs == {"АНО/150321/1-РД-ОВ1", "АНО1301211-Р-ОВ1"}
    index = json.loads((run / "artifacts.json").read_text(encoding="utf-8"))
    kinds = {a["kind"] for a in index["artifacts"]}
    assert {"TABLES", "EXTRACTED_VALUES"} <= kinds
