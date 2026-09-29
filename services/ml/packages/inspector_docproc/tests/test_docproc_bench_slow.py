"""Recognition quality gates on the real-page benchmark (97 §3.6). Slow: ~2 min with CoreML, ~6 min on CPU.

Run: ``make test-slow`` (all slow tests) or ``make bench-ocr`` (the same suites with a printed report).
"""

from __future__ import annotations

import pytest

from inspector_common.settings import Settings

pytestmark = [pytest.mark.slow, pytest.mark.data]


@pytest.fixture(scope="module")
def bench_report():
    import pymupdf

    from inspector_docproc.batch import _bench_once
    from inspector_docproc.bench.suites import load_benchmark
    from inspector_docproc.config import ExecutionConfig, RecognitionConfig
    from inspector_docproc.testing import models_available

    paths = Settings().paths
    if not paths.has_package() or not paths.documents_root.is_dir():
        pytest.skip("organizer data not found")
    if not models_available():
        pytest.skip("OCR models not found")
    pymupdf.TOOLS.mupdf_display_errors(False)
    return _bench_once(
        "ocr",
        RecognitionConfig(),
        ExecutionConfig(providers="auto", threads=4),
        load_benchmark(),
        paths,
        300,
        None,
    )


def test_gate_vector_character_accuracy(bench_report) -> None:
    ca = bench_report["vector"]["ca"]["strict"]
    assert ca["n_units"] == 30 and ca["n_chars"] == 32263
    assert ca["ca"] >= 0.965 and ca["ci_low"] >= 0.95, ca


def test_gate_scans_and_outlined_character_accuracy(bench_report) -> None:
    """GT v1 (history: the 2026-09-27 hand GT of 6 pages, superseded by GT v2 below)."""
    ca = bench_report["scans"]["ca_raw"]["strict"]
    assert ca["n_units"] == 6 and ca["n_chars"] == 7316
    assert ca["ca"] >= 0.965, ca


def test_gate_orientation(bench_report) -> None:
    o = bench_report["orientation"]
    assert o["n"] == 48 and o["accuracy"] == 1.0, o["misses"]


def test_key_fields(bench_report) -> None:
    kf = bench_report["scans"]["key_fields"]
    assert kf["n"] == 42 and kf["em_relaxed"] >= 0.93 and kf["em_strict"] >= 0.93, kf  # M0 strict 0.905
    codes = bench_report["vector"]["key_fields"]["CODE"]
    assert codes["n"] == 11 and codes["em_corrected"] >= 0.9, codes  # 0.95 needs the registry prior (AG-02B)


def test_gate_drawings_routing_and_title_blocks(bench_report) -> None:
    d = bench_report["drawings"]
    assert d["routes"]["ok"] == d["routes"]["n"] == 11, d["routes"]["cases"]
    # ≥ 90 % of the lines a full-page OCR finds in the text-layer gaps of the gold RD sheets (97 §3.6)
    assert d["text_gaps"]["recall"] >= 0.9, d["text_gaps"]
    # every gold room drawn on its cited page is found; room 314 is cited on F0201 p18 but drawn on p20
    missing = [(p["id"], k) for p in d["pages"] for k, v in (p.get("gold_rooms") or {}).items() if not v]
    assert missing in ([], [("A04", "314")]), missing
    tb = d["title_block"]
    # M1: the script context reads the D04 stage «Р» as Cyrillic (M0: Latin «P», strict 18/19)
    assert tb["n"] == 19 and tb["em_strict"] == 1.0 and tb["em_relaxed"] == 1.0, tb


# ── GT v2 (ocr_gt_v2.json: two independent transcriptions + adjudication, 14 pages) ──────────────


def test_gate_scans_and_outlined_gt_v2(bench_report) -> None:
    """97 §3.6 «scans + outlined text CA ≥ 0.965» on the adjudicated GT v2, production output (PageTokens
    text after post-correction); the raw recogniser output is kept as a regression floor."""
    v2 = bench_report["scans_v2"]
    prod, raw = v2["ca_corrected"]["strict"], v2["ca_raw"]["strict"]
    assert prod["n_units"] == 14 and prod["n_chars"] == 46914
    assert prod["ca"] >= 0.965, prod
    assert raw["ca"] >= 0.94, raw
    assert v2["ca_corrected"]["relaxed"]["ca"] >= 0.965
    assert prod["ins_rate"] <= 0.005  # excluded zones mask insertions only


def test_key_fields_gt_v2(bench_report) -> None:
    kf = bench_report["scans_v2"]["key_fields"]
    assert kf["n"] == 77 and kf["em_relaxed"] >= 0.84, kf


def test_zones_against_gt_v2(bench_report) -> None:
    """R-10: seals, QR codes and colour handwriting found where GT v2 marks excluded zones (IoU ≥ 0.3)."""
    z = bench_report["scans_v2"]["zones"]
    assert z["QR"]["hit"] == z["QR"]["n_gt"] == 9 and z["QR"]["false_alarm"] == 0, z["QR"]
    assert z["SEAL"]["n_gt"] == 8 and z["SEAL"]["hit"] >= 7 and z["SEAL"]["false_alarm"] == 0, z["SEAL"]
    # black-ink signatures on grey scans have no colour cue (zones.py docstring): recall is partial
    assert z["HANDWRITING"]["n_gt"] == 25 and z["HANDWRITING"]["hit"] >= 12, z["HANDWRITING"]
    assert z["HANDWRITING"]["false_alarm"] <= 4, z["HANDWRITING"]
