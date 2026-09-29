"""`inspector-eval` (ТЗ §14.3 harness skeleton): OCR CA on a run's PageTokens, detection/FPR, verdict."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from inspector_common.exitcodes import ExitCode
from inspector_eval import harness


def _tokens(
    run: Path, file_id: str, page: int, lines: list[tuple[list[float], str]], w=1000.0, h=500.0
) -> None:
    path = run / "tokens" / file_id / f"p{page:05d}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "file_id": file_id,
        "page_no": page,
        "page": {"width_pt": w, "height_pt": h, "rotate": 0},
        "lines": [
            {"id": i, "text": t, "bbox": b, "token_ids": [], "conf": 0.9} for i, (b, t) in enumerate(lines)
        ],
        "tokens": [],
    }
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)


GT = {
    "version": "2",
    "pages": {
        "X01": {
            "file_id": "F0001",
            "pdf_page_number": 3,
            "lines": [
                {"bbox": [100.0, 100.0, 300.0, 120.0], "text": "Бетон В25 F200 W8"},
                {"bbox": [100.0, 200.0, 300.0, 220.0], "text": "ø16x2,2"},
                {"bbox": [100.0, 300.0, 300.0, 320.0], "text": "СКРЫТО", "exclude_from_scoring": True},
            ],
        },
        "X02": {"file_id": "F0002", "pdf_page_number": 1, "lines": [{"bbox": [0, 0, 10, 10], "text": "abc"}]},
    },
}


def test_text_normalisation_and_edit_distance() -> None:
    assert harness.strict_text(" Ø16 × 2 ") == "ø16х2" and harness.strict_text("ø16x2,2") == "ø16х2,2"
    assert harness.semi_global("abc", "xxabcxx") == 0 and harness.semi_global("abc", "") == 3
    assert harness.semi_global("abd", "zzabc") == 1 and harness.semi_global("", "x") == 0
    lo, hi = harness.wilson(9, 10)
    assert lo < 0.9 < hi and harness.wilson(0, 0) is None


def test_ocr_on_a_run(tmp_path) -> None:
    run = tmp_path / "run"
    # page 1000×500 pt: normalised bboxes of the two scored lines; words split and out of order on line 1
    _tokens(run, "F0001", 3, [([0.2, 0.2, 0.25, 0.24], "F200 W8"), ([0.1, 0.2, 0.19, 0.24], "Бетон В25"),
                              ([0.1, 0.4, 0.3, 0.44], "⌀16х2,2")])  # fmt: skip
    result = harness.evaluate_ocr(run, GT)
    assert result["pages_scored"] == 1 and result["pages_missing"] == ["X02 F0002 с.1"]
    assert result["coverage"] == pytest.approx(0.5)
    page = result["per_page"][0]
    assert page["chars"] == len("БетонВ25F200W8") + len("ø16х2,2") and page["ca"] == pytest.approx(1.0)
    _tokens(
        run, "F0001", 3, [([0.1, 0.2, 0.3, 0.24], "Бетон В20 F200 W8")]
    )  # one substitution, line 2 missing
    page = harness.evaluate_ocr(run, GT)["per_page"][0]
    assert page["edits"] == 1 and page["deleted"] == len("ø16х2,2")
    assert (
        harness.evaluate_ocr(run, GT, frozenset({"F0001", "F0002"}))["pages_scored"] == 0
    )  # hidden files skipped


def test_verdict_statuses() -> None:
    det = {"tp": 9, "fp": 1, "fn": 1, "precision": 0.9, "recall": 0.9, "f1": 0.9, "negatives": 10, "fpr": 0.2}
    v = harness.verdict({"ca": 0.97, "chars": 1000}, det)
    status = {t["metric"]: t["status"] for t in v["thresholds"]}
    assert status["ocr_character_accuracy"] == "PASS" and status["detection_precision"] == "PASS"
    assert status["false_positive_rate"] == "FAIL" and v["failed"] == ["false_positive_rate"]
    assert set(v["not_evaluated"]) == {"key_fields_exact_match", "document_linkage", "evidence_localization"}
    assert not v["accepted"] and len(v["thresholds"]) == 8
    empty = harness.verdict(None, None)
    assert all(t["status"] == "NOT_EVALUATED" for t in empty["thresholds"])


def test_cli_ocr_exit_codes(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(harness, "_hidden_files", lambda: frozenset())
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps(GT, ensure_ascii=False), encoding="utf-8")
    run = tmp_path / "run"
    _tokens(
        run, "F0001", 3, [([0.1, 0.2, 0.3, 0.24], "Бетон В25 F200 W8"), ([0.1, 0.4, 0.3, 0.44], "ø16x2,2")]
    )
    assert harness.main(["ocr", "--run-dir", str(run), "--gt", str(gt)]) == ExitCode.OK
    assert "CA 1.0000" in capsys.readouterr().out
    _tokens(run, "F0001", 3, [([0.1, 0.2, 0.3, 0.24], "Бетон")])
    assert harness.main(["ocr", "--run-dir", str(run), "--gt", str(gt), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ca"] < 0.95
    assert (
        harness.main(["ocr", "--run-dir", str(run), "--gt", str(tmp_path / "none.json")])
        == ExitCode.DATA_MISSING
    )


@pytest.mark.data
def test_detection_on_t_gold_and_n_gold(real_paths, real_ctx, real_gold, tmp_path) -> None:
    from inspector_eval.fixtures import T_GOLD_OBJECT, perfect_submission

    pred = tmp_path / f"{T_GOLD_OBJECT}.json"
    pred.write_text(
        json.dumps(perfect_submission(real_gold, T_GOLD_OBJECT), ensure_ascii=False), encoding="utf-8"
    )
    det = harness.evaluate_detection(pred, "T-GOLD", paths=real_paths)
    assert (det["tp"], det["fp"], det["fn"]) == (10, 0, 0) and det["f1"] == pytest.approx(1.0)
    assert det["fpr"] is None and det["positives_only_set"]  # T-GOLD has no negatives
    v = harness.verdict(None, det)
    assert {t["metric"]: t["status"] for t in v["thresholds"]}["false_positive_rate"] == "NOT_EVALUATED"

    from inspector_eval import devset

    rows = devset.load_devset(
        devset.get_devset("N-GOLD"),
        real_paths,
        __import__("inspector_eval.data", fromlist=["x"]).load_context(real_paths),
    )
    trap = next(r for r in rows.gold_rows if r["check_id"] == "NS-C14")  # RD slab thicker: a directional trap
    wrong = {
        "object_id": "OBJ-NOVOSLOBODSKAYA",
        "checks": [
            {
                **{
                    k: trap[k]
                    for k in ("parameter_code", "location", "pd_value", "rd_value", "id_value", "criticality")
                },
                "violation_label": "VIOLATION_PRESENT",
                "protocol_status": "CRITICAL",
                "evidence": [
                    {k: e[k] for k in ("stage", "file_id", "pdf_page_number")} for e in trap["evidence"]
                ],
            }
        ],
    }
    pred_n = tmp_path / "OBJ-NOVOSLOBODSKAYA.json"
    pred_n.write_text(json.dumps(wrong, ensure_ascii=False), encoding="utf-8")
    det = harness.evaluate_detection(pred_n, "N-GOLD", paths=real_paths)
    assert det["fp_on_negatives"] == 1 and det["fpr"] == pytest.approx(1 / det["negatives"])
