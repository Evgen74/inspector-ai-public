"""Integrity checker for any submission plus manifest: R1–R15 and packaging rules P1–P6."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from inspector_common.contracts.loader import contracts_dir
from inspector_common.exitcodes import ExitCode
from inspector_common.hashing import input_manifest_hash
from inspector_eval import cli, integrity
from inspector_eval.data import InputError


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _sidecar(object_id: str, manifest: list[dict], **file_overrides: dict) -> dict:
    example = contracts_dir() / "examples" / "submission_sidecar" / "valid" / "tyumen_export.json"
    doc = json.loads(example.read_text(encoding="utf-8"))
    rows = [r for r in manifest if r["object_id"] == object_id]
    entry = doc["objects"][0]
    entry.update(object_id=object_id, split="TRAIN_PUBLIC", input_manifest_hash=input_manifest_hash(rows))
    entry.update(files_total=len(rows), files_present=len(rows), missing_on_disk=[], artifacts={})
    template = doc["files"][0]
    doc["files"] = []
    for row in rows:
        f = {
            **template,
            "file_id": row["file_id"],
            "object_id": object_id,
            "sha256": row["sha256"],
            "manifest_stage": row["stage"],
            "stage_resolved": row["stage"] if row["stage"] in ("PD", "RD", "ID") else "RD",
            "pdf_pages": row["pdf_pages"],
        }
        f.update(file_overrides.get(row["file_id"], {}))
        doc["files"].append(f)
    doc.pop("stage_config_hashes", None)
    return doc


@pytest.fixture()
def answer(gold, h) -> dict:
    return h.as_submission(gold, "OBJ-A")


def test_a_clean_answer_passes_and_missing_companions_are_not_evaluated(answer, ctx, tmp_path) -> None:
    report = integrity.check_document(answer, ctx, path=tmp_path / "OBJ-A.json")
    assert report.ok and report.expected_split == "TRAIN_PUBLIC" and not report.hidden
    status = {r: integrity.result_rule(report, r).status for r in (*integrity.PACKAGING_IDS, "R9", "R15")}
    assert status["P1"] == "PASS"
    assert {status[r] for r in ("P2", "P3", "P4", "P5")} == {"NOT_EVALUATED"}
    assert status["R9"] == "NOT_EVALUATED" and status["R15"] == "PASS"
    # the exporter's gate needs both companions
    strict_gate = integrity.check_document(answer, ctx, path=tmp_path / "OBJ-A.json", require_packaging=True)
    assert not strict_gate.ok and strict_gate.failed_rules == ["P2", "P4"]


def test_p1_file_name_must_be_the_object(answer, ctx, tmp_path) -> None:
    report = integrity.check_document(answer, ctx, path=tmp_path / "answer.json")
    assert report.failed_rules == ["P1"]


def test_sidecar_rules(answer, ctx, h) -> None:
    good = _sidecar("OBJ-A", h.MANIFEST)
    report = integrity.check_document(answer, ctx, sidecar=good)
    assert [integrity.result_rule(report, r).status for r in ("P2", "P3", "P5", "P6")] == ["PASS"] * 4

    stale = copy.deepcopy(good)
    stale["objects"][0]["input_manifest_hash"] = "f" * 64
    assert integrity.check_document(answer, ctx, sidecar=stale).failed_rules == ["P3"]

    other = _sidecar("OBJ-B", h.MANIFEST)
    failed = integrity.check_document(answer, ctx, sidecar=other).failed_rules
    assert "P2" in failed and "P5" in failed  # other object; the cited files were never processed

    missing = _sidecar("OBJ-A", h.MANIFEST, F0001={"local_status": "MISSING_ON_DISK"})
    assert integrity.check_document(answer, ctx, sidecar=missing).failed_rules == ["P5"]

    as_id = _sidecar("OBJ-A", h.MANIFEST, F0002={"stage_resolved": "ID"})
    report = integrity.check_document(answer, ctx, sidecar=as_id)
    assert report.failed_rules == ["P6"]  # R7 accepts RD for RD_ID_MIXED, P6 wants the resolved stage
    assert integrity.result_rule(report, "R7").status == "PASS"

    invalid = copy.deepcopy(good)
    del invalid["config_hash"]
    assert "P2" in integrity.check_document(answer, ctx, sidecar=invalid).failed_rules


def test_p6_falls_back_to_the_inventory_stages_then_warns(answer, ctx) -> None:
    assert (
        integrity.result_rule(
            integrity.check_document(answer, ctx, resolved_stages={"F0002": "RD"}), "P6"
        ).status
        == "PASS"
    )
    report = integrity.check_document(answer, ctx, resolved_stages={"F0002": "ID"})
    assert report.failed_rules == ["P6"]
    # the synthetic path «syn/F0002.pdf» carries no stage signal: unresolved is a warning, not a failure
    unresolved = integrity.check_document(answer, ctx)
    assert integrity.result_rule(unresolved, "P6").status == "WARN" and unresolved.ok


def test_strict_variant_rules(answer, ctx) -> None:
    strict = integrity.strict_projection(answer)
    assert (
        integrity.result_rule(integrity.check_document(answer, ctx, strict_document=strict), "P4").status
        == "PASS"
    )
    changed = copy.deepcopy(strict)
    changed["checks"][1]["location"] = "999"
    report = integrity.check_document(answer, ctx, strict_document=changed)
    assert report.failed_rules == ["P4"]
    assert report.packaging["P4"].violations[0].check_index == 1
    shorter = {**strict, "checks": strict["checks"][:-1]}
    assert integrity.check_document(answer, ctx, strict_document=shorter).failed_rules == ["P4"]
    extended = copy.deepcopy(strict)
    extended["checks"][0]["confidence"] = 0.9  # not allowed in the strict schema
    assert "P4" in integrity.check_document(answer, ctx, strict_document=extended).failed_rules


def test_integrity_rules_fire_on_any_manifest(answer, ctx) -> None:
    broken = copy.deepcopy(answer)
    broken["checks"][0]["evidence"].append(
        {"stage": "PD", "file_id": "F0999", "pdf_page_number": 1}
    )  # excluded
    broken["checks"][1]["evidence"][0]["pdf_page_number"] = 500  # out of range
    broken["checks"].append(copy.deepcopy(broken["checks"][2]))  # duplicate key
    report = integrity.check_document(broken, ctx)
    assert {"R3", "R4", "R5", "R6", "R10"} <= set(report.failed_rules)
    assert report.integrity.share < 1.0 and not report.ok


def test_expected_split_defaults_to_the_objects_own_split(ctx, h) -> None:
    doc = {"object_id": "OBJ-NEW", "checks": []}
    report = integrity.check_document(doc, ctx)
    assert report.expected_split == "TRAIN_PUBLIC" and "R2" in report.failed_rules


def test_hidden_answers_are_always_redacted(ctx, h) -> None:
    hidden = {
        "object_id": "OBJ-Z",
        "checks": [
            {
                "parameter_code": "KR-055",
                "location": "SECRET-LOCATION",
                "pd_value": "SECRET-VALUE",
                "rd_value": None,
                "id_value": None,
                "violation_label": "VIOLATION_PRESENT",
                "protocol_status": "WARNING",  # wrong on purpose: R13 fails
                "criticality": "Критическое (приостановка работ)",
                "evidence": [{"stage": "PD", "file_id": "F0900", "pdf_page_number": 99}],
            }
        ],
    }
    report = integrity.check_document(hidden, ctx, path=Path("/tmp/OBJ-Z.json"))
    assert report.hidden and report.expected_split == "TEST_HIDDEN"
    out = report.as_dict()
    text = json.dumps(out, ensure_ascii=False)
    assert out["redacted"] and out["path"] is None
    for secret in ("SECRET-LOCATION", "SECRET-VALUE", "KR-055", "F0900", "99"):
        assert secret not in text.replace('"violations_count": 99', "")
    rules = {r["rule"]: r for r in out["integrity"]["rules"]}
    assert rules["R13"]["status"] == "FAIL" and rules["R13"]["violations_count"] == 1
    assert rules["R6"]["status"] == "FAIL" and "violations" not in rules["R6"]
    assert "SECRET" not in integrity.render(out)


def test_discover_a_run_directory(answer, tmp_path, h) -> None:
    run = tmp_path / "runs" / "r1"
    _write(run / "submission" / "OBJ-A.json", answer)
    _write(run / "submission" / "OBJ-A.sidecar.json", _sidecar("OBJ-A", h.MANIFEST))
    _write(run / "submission-strict" / "OBJ-A.json", integrity.strict_projection(answer))
    _write(run / "inventory" / "OBJ-A.json", {"files": [{"file_id": "F0002", "stage_resolved": "RD"}]})
    found = integrity.discover(run)
    assert len(found) == 1 and found[0].object_id == "OBJ-A"
    assert found[0].sidecar and found[0].strict and found[0].inventory
    assert integrity.inventory_stages(found[0].inventory) == {"F0002": "RD"}
    lone = integrity.discover(run / "submission" / "OBJ-A.json")
    assert lone[0].sidecar is not None and lone[0].strict is not None
    with pytest.raises(InputError):
        integrity.discover(tmp_path / "nowhere")


def test_cli_integrity_on_a_run_directory(fake_data_root, answer, tmp_path, h, capsys) -> None:
    run = tmp_path / "runs" / "r1"
    _write(run / "submission" / "OBJ-A.json", answer)
    _write(run / "submission-strict" / "OBJ-A.json", integrity.strict_projection(answer))
    sidecar = _sidecar("OBJ-A", h.MANIFEST)
    manifest = fake_data_root / "ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0" / "data" / "document_manifest.jsonl"
    from inspector_common.hashing import sha256_file

    sidecar["inputs"]["manifest_sha256"] = sha256_file(manifest)
    _write(run / "submission" / "OBJ-A.sidecar.json", sidecar)
    base = ["integrity", "--data-root", str(fake_data_root)]
    out = tmp_path / "out"
    assert cli.main([*base, "--pred", str(run), "--require-packaging", "--out", str(out)]) == ExitCode.OK
    assert "целостность в порядке" in capsys.readouterr().out
    written = json.loads((out / "integrity.json").read_text(encoding="utf-8"))
    assert written["objects"][0]["ok"] and written["superseded_known"] is False

    sidecar["inputs"]["manifest_sha256"] = "0" * 64  # another package version
    _write(run / "submission" / "OBJ-A.sidecar.json", sidecar)
    assert cli.main([*base, "--pred", str(run), "--json"]) == ExitCode.SCHEMA_INVALID
    assert json.loads(capsys.readouterr().out)[0]["failed_rules"] == ["P3"]

    superseded = _write(tmp_path / "superseded.json", {"superseded_file_ids": ["F0001"]})
    code = cli.main(
        [*base, "--pred", str(run / "submission" / "OBJ-A.json"), "--superseded", str(superseded), "--json"]
    )
    assert code == ExitCode.SCHEMA_INVALID
    assert "R9" in json.loads(capsys.readouterr().out)[0]["failed_rules"]


def test_cli_integrity_refuses_a_hidden_answer_without_the_frozen_run(
    fake_data_root, tmp_path, capsys
) -> None:
    pred = _write(tmp_path / "OBJ-Z.json", {"object_id": "OBJ-Z", "checks": []})
    base = ["integrity", "--data-root", str(fake_data_root), "--pred", str(pred)]
    assert cli.main(base) == ExitCode.HIDDEN_TEST_REFUSED
    assert cli.main([*base, "--hidden-final"]) == ExitCode.HIDDEN_TEST_REFUSED  # no frozen manifest
    assert "OBJ-Z" not in capsys.readouterr().out


def test_cli_integrity_no_answer(fake_data_root, tmp_path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert (
        cli.main(["integrity", "--data-root", str(fake_data_root), "--pred", str(empty)])
        == ExitCode.DATA_MISSING
    )
    assert "Ответ для оценки не найден" in capsys.readouterr().err


@pytest.mark.data
def test_real_t_gold_answer_passes_r1_r15_and_p6(real_ctx, real_gold) -> None:
    from inspector_eval.fixtures import T_GOLD_OBJECT, perfect_submission

    answer = perfect_submission(real_gold, T_GOLD_OBJECT)
    report = integrity.check_document(answer, real_ctx, path=Path(f"{T_GOLD_OBJECT}.json"))
    assert report.ok and report.integrity.share == 1.0
    assert integrity.result_rule(report, "P6").status == "PASS"  # F0201/F0202 resolve to RD by name
    wrong = copy.deepcopy(answer)
    wrong["checks"][0]["evidence"][1]["stage"] = "ID"  # F0201 is RD_ID_MIXED: R7 passes, P6 does not
    wrong["checks"][1]["evidence"].append({"stage": "PD", "file_id": "F0149", "pdf_page_number": 1})
    report = integrity.check_document(wrong, real_ctx)
    assert set(report.failed_rules) == {"R3", "R4", "R5", "P6"}  # F0149 is excluded and not in the manifest
