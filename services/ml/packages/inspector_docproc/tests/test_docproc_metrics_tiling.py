"""Benchmark metrics (96 §1.3) and tiling/seam-merge helpers on toy data."""

from __future__ import annotations

import numpy as np
import pytest

from inspector_docproc.bench import metrics as M
from inspector_docproc.ocr.pipeline import merge_seam_boxes, tile_origins


def _line(x0, y0, x1, y1, text, score=0.9):
    return {"poly": np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float), "text": text, "score": score}


def _glyphs(text, x0, y, step=10, sid=0):
    return [{"c": c, "x": x0 + i * step + 5, "y": y, "sid": sid} for i, c in enumerate(text)]


def test_text_layer_ca_counts_edits_and_deletions() -> None:
    gt = _glyphs("ABCDE", 0, 5) + _glyphs("XYZ", 0, 45, sid=1)
    lines = [_line(0, 0, 50, 10, "ABCDF")]  # one substitution; «XYZ» not returned
    res = M.score_text_layer(gt, lines, None)
    assert res["strict"] == {"N": 8, "ed": 1, "dele": 3, "ins": 0}
    assert M.ca(res["strict"]) == pytest.approx(1 - 4 / 8)


def test_low_score_lines_count_as_not_returned() -> None:
    gt = _glyphs("ABC", 0, 5)
    res = M.score_text_layer(gt, [_line(0, 0, 30, 10, "ABC", score=0.4)], None)
    assert res["strict"]["dele"] == 3 and M.ca(res["strict"]) == 0.0


def test_relaxed_folds_homoglyphs_and_dashes() -> None:
    assert M.norm_relaxed("AHO – 1") == M.norm_relaxed("АНО-1")
    assert M.norm_strict("A B") == "AB"


def test_semi_global_distance() -> None:
    assert M.semi_global("abc", "xxabcxx") == 0
    assert M.semi_global("abc", "xxabxx") == 1
    assert M.semi_global("", "abc") == 0
    assert M.semi_global("abc", "") == 3


def test_line_gt_scoring_with_excluded_zone() -> None:
    gt = {
        "lines": [
            {"bbox": [0, 0, 100, 10], "text": "Протокол 25"},
            {"bbox": [0, 50, 100, 60], "text": "Печать"},
        ],
        "excluded_zones": [{"bbox": [0, 45, 100, 65], "type": "SEAL"}],
    }
    res, worst = M.score_line_gt(gt, [_line(0, 0, 100, 10, "Протокол 26")])
    assert res["strict"]["N"] == len("Протокол25")
    assert M.ca(res["strict"]) == pytest.approx(1 - 1 / 10)
    assert worst and worst[0][2] == 1


def test_bootstrap_ci_is_deterministic_and_brackets_the_estimate() -> None:
    a = M.bootstrap_ci([0.9, 0.95, 1.0], [100, 200, 300])
    b = M.bootstrap_ci([0.9, 0.95, 1.0], [100, 200, 300])
    assert a == b
    assert a[1] <= a[0] <= a[2]


def test_token_em_word_boundaries() -> None:
    lines = [_line(0, 0, 100, 10, "класс бетона В25, прочность 22,6МПа")]
    assert M.token_em("В25", [0, 0, 100, 10], lines, relaxed=False)
    assert M.token_em("22,6", [0, 0, 100, 10], lines, relaxed=False)  # unit letters may follow numbers
    assert not M.token_em("2", [0, 0, 100, 10], lines, relaxed=False)  # inside a number
    assert not M.token_em("В2", [0, 0, 100, 10], lines, relaxed=False)
    assert M.token_em("B25", [0, 0, 100, 10], lines, relaxed=True)


def test_tile_origins_match_the_prototype_grid() -> None:
    assert tile_origins(3000, 3200, 400) == [0]
    assert tile_origins(3508, 3200, 400) == [0, 2800]
    assert tile_origins(9362, 3200, 400) == [0, 2800, 5600, 8400]


def test_seam_merge_joins_a_line_cut_by_a_tile_seam() -> None:
    left = np.array([[100, 50], [3200, 50], [3200, 80], [100, 80]], np.float32)
    right = np.array([[2800, 51], [3400, 51], [3400, 79], [2800, 79]], np.float32)
    other = np.array([[100, 500], [300, 500], [300, 530], [100, 530]], np.float32)
    out = merge_seam_boxes([left, right, other], [0, 1, 0])
    assert len(out) == 2
    merged = max(out, key=lambda q: q[:, 0].max() - q[:, 0].min())
    assert merged[:, 0].min() == 100 and merged[:, 0].max() == 3400


def test_seam_merge_keeps_boxes_of_the_same_tile_and_different_rows() -> None:
    a = np.array([[0, 0], [100, 0], [100, 20], [0, 20]], np.float32)
    b = np.array([[50, 0], [150, 0], [150, 20], [50, 20]], np.float32)
    assert len(merge_seam_boxes([a, b], [0, 0])) == 2  # same tile: never merged
    c = np.array([[50, 30], [150, 30], [150, 50], [50, 50]], np.float32)
    assert len(merge_seam_boxes([a, c], [0, 1])) == 2  # no overlap
