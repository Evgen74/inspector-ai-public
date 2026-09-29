"""The T-GOLD must-pass gate and the RT-01…RT-10 regression checks, on synthetic run directories."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from inspector_common.contracts.loader import contracts_dir
from inspector_common.exitcodes import ExitCode
from inspector_common.hashing import input_manifest_hash
from inspector_eval import cli, integrity, rtcheck, tgold_gate


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _sidecar(object_id: str, manifest: list[dict]) -> dict:
    example = contracts_dir() / "examples" / "submission_sidecar" / "valid" / "tyumen_export.json"
    doc = json.loads(example.read_text(encoding="utf-8"))
    rows = [r for r in manifest if r["object_id"] == object_id]
    doc["objects"][0].update(
        object_id=object_id,
        input_manifest_hash=input_manifest_hash(rows),
        files_total=len(rows),
        files_present=len(rows),
        artifacts={},
    )
    template = doc["files"][0]
    doc["files"] = [
        {
            **template,
            "file_id": r["file_id"],
            "object_id": object_id,
            "sha256": r["sha256"],
            "manifest_stage": r["stage"],
            "stage_resolved": r["stage"] if r["stage"] in ("PD", "RD", "ID") else "RD",
            "pdf_pages": r["pdf_pages"],
        }
        for r in rows
    ]
    doc["inputs"].pop("manifest_sha256", None)
    doc["inputs"]["manifest_sha256"] = "0" * 64
    return doc


def _run(tmp_path: Path, answer: dict, manifest: list[dict], *, name: str = "run") -> Path:
    run = tmp_path / name
    object_id = answer["object_id"]
    _write(run / "submission" / f"{object_id}.json", answer)
    _write(run / "submission-strict" / f"{object_id}.json", integrity.strict_projection(answer))
    _write(run / "submission" / f"{object_id}.sidecar.json", _sidecar(object_id, manifest))
    _write(run / "pipeline_summary.json", {"run_id": name, "steps": [{"step": "export", "status": "ok"}]})
    return run


@pytest.fixture()
def gctx(ctx):
    # the sidecar's manifest_sha256 is a placeholder: P3 compares it only when the context knows the file hash
    return ctx


def _gate(run: Path, ctx, gold, **kw) -> tgold_gate.GateResult:
    return tgold_gate.evaluate(run, ctx, gold, object_id="OBJ-A", **kw)


# ── the gate ─────────────────────────────────────────────────────────────────────────────────


def test_perfect_run_passes_every_hard_criterion(gctx, gold, h, tmp_path) -> None:
    run = _run(tmp_path, h.as_submission(gold, "OBJ-A"), h.MANIFEST)
    result = _gate(run, gctx, gold, runtime_s=12.5)
    assert result.hard_ok(("G1", "G2", "G3", "G4", "G5", "G6", "G7"))
    assert result.criteria["G8"].status == "NOT_EVALUATED"  # RT checks exist only for T-GOLD
    assert result.status == "INCOMPLETE"
    assert result.score["total"] == pytest.approx(100.0)
    assert result.criteria["G9"].status == "PASS" and result.criteria["G9"].measured["wall_s"] == 12.5
    path = tgold_gate.write(result, run)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "INCOMPLETE"
    assert "Приёмка T-GOLD" in tgold_gate.render(result)


def test_a_dropped_room_fails_keys_pages_gate_and_status(gctx, gold, h, tmp_path) -> None:
    answer = h.as_submission(gold, "OBJ-A")
    answer["checks"] = [c for c in answer["checks"] if c["location"] != "142"]
    result = _gate(_run(tmp_path, answer, h.MANIFEST), gctx, gold)
    status = {c: result.criteria[c].status for c in ("G2", "G3", "G4", "G5", "G6", "G7")}
    assert status == {"G2": "FAIL", "G3": "FAIL", "G4": "FAIL", "G5": "FAIL", "G6": "PASS", "G7": "PASS"}
    assert "IOS4-078 · 142" in result.criteria["G2"].details[0]
    assert result.status == "FAIL" and result.score["gate_triggered"]


def test_wrong_page_fails_g3_and_the_strict_gate(gctx, gold, h, tmp_path) -> None:
    answer = h.as_submission(gold, "OBJ-A")
    for check in answer["checks"]:
        if check["location"] == "012":
            check["evidence"] = [{"stage": "PD", "file_id": "F0001", "pdf_page_number": 11}]
    result = _gate(_run(tmp_path, answer, h.MANIFEST), gctx, gold)
    assert result.criteria["G2"].status == "PASS"
    assert result.criteria["G3"].status == "FAIL" and "012" in result.criteria["G3"].details[0]
    assert result.criteria["G4"].status == "FAIL" and "строгий" in result.criteria["G4"].details[0]


def test_extra_positive_keys_are_capped(gctx, gold, h, tmp_path) -> None:
    answer = h.as_submission(gold, "OBJ-A")
    template = answer["checks"][0]
    for n, count in ((5, "PASS"), (6, "FAIL")):
        doc = copy.deepcopy(answer)
        for i in range(n):
            extra = copy.deepcopy(template)
            extra["location"] = f"9{i:02d}"
            doc["checks"].append(extra)
        result = _gate(_run(tmp_path, doc, h.MANIFEST, name=f"run{n}"), gctx, gold)
        assert result.criteria["G6"].status == count
        assert result.criteria["G6"].measured["extra_positive_keys"] == n


def test_wrong_status_and_missing_companions(gctx, gold, h, tmp_path) -> None:
    answer = h.as_submission(gold, "OBJ-A")
    answer["checks"][0]["protocol_status"] = "WARNING"
    run = _run(tmp_path, answer, h.MANIFEST)
    (run / "submission-strict" / "OBJ-A.json").unlink()
    result = _gate(run, gctx, gold)
    assert result.criteria["G5"].status == "FAIL"
    assert set(result.criteria["G7"].measured["failed_rules"]) == {"R13", "P4"}


def test_missing_answer_fails_everything_but_rt_and_runtime(gctx, gold, tmp_path) -> None:
    result = _gate(tmp_path / "empty", gctx, gold)
    assert all(result.criteria[c].status == "FAIL" for c in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"))
    assert result.criteria["G9"].status == "WARN" and result.score is None


def test_rt_not_evaluated_escalates_when_the_producing_step_ran(ctx, gold, h, tmp_path) -> None:
    run = _run(tmp_path, h.as_submission(gold, "OBJ-A"), h.MANIFEST)
    _write(run / "pipeline_summary.json", {"steps": [{"step": "layout", "status": "ok"}]})
    result = _gate(run, ctx, gold, with_rt=True)
    g8 = result.criteria["G8"]
    assert g8.status == "FAIL" and any("RT-01" in d and "layout" in d for d in g8.details)


def test_pipeline_stub_detection() -> None:
    from inspector_common.batch import CommandNotImplementedError

    def stub(args, ctx):
        """Docstring is ignored."""
        raise CommandNotImplementedError("x", "AG-00")

    def real(args, ctx):
        if args:
            raise CommandNotImplementedError("x", "AG-00")
        return 0

    assert tgold_gate._is_stub(stub) and not tgold_gate._is_stub(real)
    stubs = tgold_gate.pipeline_stubs()
    assert set(stubs) <= set(tgold_gate.PIPELINE_STEPS) and "score" not in stubs


def _pin_manifest(run: Path, object_id: str, fake_data_root: Path) -> None:
    from inspector_common.hashing import sha256_file

    manifest = fake_data_root / "ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0" / "data" / "document_manifest.jsonl"
    path = run / "submission" / f"{object_id}.sidecar.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["inputs"]["manifest_sha256"] = sha256_file(manifest)
    _write(path, doc)


def test_cli_tgold_gate(fake_data_root, gold, h, tmp_path, capsys) -> None:
    run = _run(tmp_path, h.as_submission(gold, "OBJ-A"), h.MANIFEST)
    _pin_manifest(run, "OBJ-A", fake_data_root)
    base = ["tgold-gate", "--data-root", str(fake_data_root), "--object", "OBJ-A"]
    assert cli.main([*base, "--run-dir", str(run), "--json"]) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)["status"] == "INCOMPLETE"
    assert (run / "score" / tgold_gate.GATE_FILE).is_file()
    answer = h.as_submission(gold, "OBJ-A")
    answer["checks"] = answer["checks"][1:]  # drops IOS4-079 · 012, a checkpoint
    broken = _run(tmp_path, answer, h.MANIFEST, name="broken")
    _pin_manifest(broken, "OBJ-A", fake_data_root)
    assert cli.main([*base, "--run-dir", str(broken)]) == ExitCode.GATE_TRIGGERED
    assert "НЕ ПРОЙДЕН" in capsys.readouterr().out
    assert cli.main([*base, "--run-dir", str(tmp_path / "nope")]) == ExitCode.DATA_MISSING
    assert cli.main([*base, "--object", "OBJ-Z", "--run-dir", str(run)]) == ExitCode.HIDDEN_TEST_REFUSED


# ── RT checks ────────────────────────────────────────────────────────────────────────────────


def _tok(text: str, x: float, y: float, source: str = "OCR") -> dict:
    return {
        "id": 0,
        "text": text,
        "bbox": [x - 0.004, y - 0.002, x + 0.004, y + 0.002],
        "conf": 0.9,
        "source": source,
    }


def _page(run: Path, file_id: str, page: int, tokens: list[dict], page_class: str = "VECTOR") -> None:
    path = run / "tokens" / file_id / f"p{page:05d}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump({"file_id": file_id, "page_no": page, "page_class": page_class, "tokens": tokens}, fh)


def _full_rt_run(run: Path) -> None:
    _page(
        run,
        "F0201",
        17,
        [_tok(t, 0.85, 0.45 + i * 0.02) for i, t in enumerate(["П9", "П15", "П17.1,", "П18", "B2.1"])],
    )
    tags18 = ["B2.2", "B2.3,4", "B2.7,8,9", "B2.10", "П2/BE"]
    _page(
        run,
        "F0201",
        18,
        [_tok(t, 0.9, 0.12 + i * 0.03) for i, t in enumerate(tags18)]
        + [_tok(r, 0.92, 0.2, "TEXT_LAYER") for r in ("140", "142", "147")],
    )
    _page(
        run,
        "F0171",
        11,
        [
            _tok(w, 0.5, 0.5, "TEXT_LAYER")
            for w in ("(пом.", "267,", "270,", "271,", "272)", "предусмотрена", "система", "(теплые", "полы)")
        ],
    )
    for p in range(1, 37):
        cls = "VECTOR_OUTLINED_TEXT" if p >= 19 else "VECTOR"
        _page(run, "F0202", p, [_tok("Радиатор", 0.5, 0.5, "OCR" if p >= 19 else "TEXT_LAYER")], cls)
    _page(run, "F0171", 104, [_tok(t, x, 0.4, "TEXT_LAYER") for t, x in (
        ("П2", 0.707), ("П2.1", 0.76), ("П3", 0.702), ("П8", 0.763), ("П9", 0.755), ("П10", 0.749),
        ("П15", 0.821), ("П17", 0.82), ("П18", 0.817), ("П20", 0.633))])  # fmt: skip
    sheet_map = [{"pdf_page_number": p, "sheet_number": s, "basis": "TITLE_BLOCK"} for p, s in (
        *((p, p - 13) for p in range(14, 29)), (29, 14), (30, 15), *((p, p - 15) for p in range(31, 35)))]  # fmt: skip
    sheet_map[29 - 14]["duplicate_of_page"] = 27
    sheet_map[30 - 14]["duplicate_of_page"] = 28
    _write(run / "layout" / "F0201.json", {"file_id": "F0201", "sheet_page_map": sheet_map})
    _write(
        run / "layout" / "F0202.json",
        {
            "file_id": "F0202",
            "revision_clouds": [
                {
                    "pdf_page_number": 17,
                    "bbox": [0.34, 0.69, 0.42, 0.73],
                    "source": "CAD_LAYER",
                    "layer": "ОВ-Отопление-Изм. №3",
                }
            ],
            "rooms": [
                {
                    "room_token": "270",
                    "pdf_page_number": 17,
                    "bbox": [0.35, 0.70, 0.36, 0.705],
                    "source": "TEXT_LAYER",
                },
                {
                    "room_token": "272",
                    "pdf_page_number": 17,
                    "bbox": [0.39, 0.70, 0.40, 0.705],
                    "source": "TEXT_LAYER",
                },
            ],
        },
    )
    _write(
        run / "layout" / "F0198.json",
        {"qr_links": [{"pdf_page_number": 1, "payload": "https://exon/87cc1a16/1/wd/17", "doc_page": 17,
                        "target_file_id": "F0202", "target_pdf_page_number": 17}]},
    )  # fmt: skip
    for p in [*range(1, 32), *range(147, 176)]:
        text = ["АНО/150321/1-П-ПЗ1.2"] if p == 1 else ["текст"]
        _page(run, "F0146", p, [_tok(t, 0.5, 0.5, "TEXT_LAYER_REPAIRED") for t in text], "BROKEN_ENCODING")

    def aosr(text: str) -> dict:
        return {
            "tables": [{"table_type": "AOSR", "rows": [{"row_no": 1, "cells": {"rd_refs": {"raw": text}}}]}]
        }

    _write(run / "tables" / "F0195.json", aosr("АНО/150321/1-РД-ОВ2.1 – изм. 3"))
    _write(
        run / "tables" / "F0196.json",
        aosr("АНО/150321/1-РД-ОВ1 - изм. 3; п.4: АНО1301211-Р-ОВ1 от 09.01.2025"),
    )


def test_rt_checks_pass_on_a_complete_synthetic_run(tmp_path) -> None:
    run = tmp_path / "run"
    _full_rt_run(run)
    results = rtcheck.run_checks(run)
    assert [(r.rt_id, r.status) for r in results if r.status != "PASS"] == []
    assert rtcheck.summary(results)["status"] == "PASS" and len(results) == 10


def test_rt_checks_report_failures_and_missing_artifacts(tmp_path) -> None:
    run = tmp_path / "run"
    _full_rt_run(run)
    _page(run, "F0201", 17, [_tok(t, 0.85, 0.5) for t in ("П15", "П17.1", "П18", "B2.1")])  # П9 lost
    _page(run, "F0202", 20, [_tok("теплый", 0.5, 0.5), _tok("пол", 0.52, 0.5)], "VECTOR_OUTLINED_TEXT")
    _page(run, "F0202", 21, [_tok("x", 0.5, 0.5, "TEXT_LAYER")], "VECTOR_OUTLINED_TEXT")  # outlined, no OCR
    (run / "layout" / "F0198.json").unlink()
    by_id = {r.rt_id: r for r in rtcheck.run_checks(run)}
    assert by_id["RT-02"].status == "FAIL" and "п9" in by_id["RT-02"].details[0]
    assert by_id["RT-06"].status == "FAIL" and "[20]" in by_id["RT-06"].details[0]
    assert "[21]" in by_id["RT-06"].details[1]
    assert by_id["RT-07"].status == "NOT_EVALUATED"
    assert {r for r, x in by_id.items() if x.status == "PASS"} >= {
        "RT-01",
        "RT-03",
        "RT-05",
        "RT-09",
        "RT-10",
    }


def test_rt_sheet_map_and_cloud_failures(tmp_path) -> None:
    run = tmp_path / "run"
    _full_rt_run(run)
    layout = json.loads((run / "layout" / "F0201.json").read_text(encoding="utf-8"))
    for e in layout["sheet_page_map"]:
        e.pop("duplicate_of_page", None)
        if e["pdf_page_number"] == 32:
            e["sheet_number"] = 19
    _write(run / "layout" / "F0201.json", layout)
    cloud = json.loads((run / "layout" / "F0202.json").read_text(encoding="utf-8"))
    cloud["revision_clouds"][0]["bbox"] = [0.10, 0.10, 0.15, 0.15]
    _write(run / "layout" / "F0202.json", cloud)
    by_id = {r.rt_id: r for r in rtcheck.run_checks(run, only=["RT-01", "RT-04"])}
    assert set(by_id) == {"RT-01", "RT-04"}
    assert by_id["RT-01"].status == "FAIL" and "с.32" in by_id["RT-01"].details[0]
    assert any("дубликаты" in d for d in by_id["RT-01"].details)
    assert by_id["RT-04"].status == "FAIL" and by_id["RT-04"].measured["iou"] == 0.0


def test_fold_and_tag_parsing() -> None:
    assert rtcheck.fold("B2.1 –  Изм. №3") == "в2.1 - изм. №3"
    assert rtcheck.tags_in(["в2.7,8,9", "п17.1,", "п2/ве"]) >= {"в2.7", "в2.8", "в2.9", "п17.1", "п2/ве"}


@pytest.mark.data
def test_real_t_gold_perfect_run_passes_g1_to_g7(real_ctx, real_gold, real_paths, tmp_path) -> None:
    from inspector_common.hashing import sha256_file
    from inspector_eval.fixtures import T_GOLD_OBJECT, perfect_submission

    manifest = list(real_ctx.manifest.values())
    answer = perfect_submission(real_gold, T_GOLD_OBJECT)
    run = _run(tmp_path, answer, manifest)
    sidecar_path = run / "submission" / f"{T_GOLD_OBJECT}.sidecar.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["inputs"]["manifest_sha256"] = sha256_file(real_paths.manifest_path)
    _write(sidecar_path, sidecar)
    result = tgold_gate.evaluate(run, real_ctx, real_gold, runtime_s=1.0)
    assert result.hard_ok(("G1", "G2", "G3", "G4", "G5", "G6", "G7")), tgold_gate.render(result)
    assert result.criteria["G8"].status == "NOT_EVALUATED" and result.status == "INCOMPLETE"
    assert result.score["total"] == pytest.approx(100.0)
