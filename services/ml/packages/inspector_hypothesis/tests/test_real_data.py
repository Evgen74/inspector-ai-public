"""Organizer data (train object Тюменская and the ТЗ pilot markup): real text layers and real tables.

Only TRAIN_PUBLIC files and the public ТЗ pilot are read. The PD warm-floor assertion, the anchor pages and the gold
parity of FREE-HEATING-001 are checked on the real PDF text layers. The RD absence proof needs OCR of the outlined
RD pages; here it is taken from the recognition fixture RT-06 (95_tyumen_dev_fixtures.json: no «тепл* пол» /
Multibox in the text layer or the OCR of F0202), and it is measured end to end on real PageTokens by
``python -m inspector_hypothesis`` (reported by AG-07).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from inspector_common.paths import repo_root
from inspector_hypothesis import HypothesisConfig, HypothesisInputs, MemoryPageSource, run_hypotheses
from inspector_hypothesis.facts import FactBuilder
from inspector_hypothesis.inputs import DocumentInfo, PageText, Word
from inspector_hypothesis.rules import RuleEngine, load_seed_rules
from inspector_hypothesis.testing import OBJECT_ID, table_artifacts, typed_table
from inspector_hypothesis.textmatch import norm_word

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.data

NUM = re.compile(r"^\d+[.,]\d+$")


def _manifest(data_paths) -> dict[str, dict]:
    rows = {}
    with open(data_paths.manifest_path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["object_id"] == OBJECT_ID:
                rows[r["file_id"]] = r
    return rows


def _pdf(data_paths, rows, file_id):
    path = data_paths.documents_root / rows[file_id]["relative_path"]
    if not path.is_file():
        pytest.skip(f"{file_id} not on disk")
    return pymupdf.open(path)


def _page_text(pdf, file_id: str, page_no: int) -> PageText:
    """The real text layer of one page as PageText, through the recognition core's extractor (boxes in the visible
    rotated page space, as in PageTokens; invisible scanner layers dropped)."""
    from inspector_docproc.textlayer import extract_text_layer

    pg = pdf[page_no - 1]
    layer = extract_text_layer(pg)
    words: list[Word] = []
    lines: dict[tuple[int, int], list[int]] = {}
    for w in layer.visible_words:
        key = (w.block, w.line)
        if key not in lines:
            lines[key] = []
        words.append(Word(w.text, norm_word(w.text), tuple(w.bbox), list(lines).index(key)))
        lines[key].append(len(words) - 1)
    return PageText(file_id, page_no, pg.rect.width, pg.rect.height, words, list(lines.values()))


def _rows(pg, region, *, area_x, room_x, cluster):
    """Test-only explication reader: rows anchored on the area column, other words joined to the nearest row."""
    w_pt, h_pt = pg.rect.width, pg.rect.height
    x_lo, x_hi, y_lo, y_hi = region
    ws = []
    for x0, y0, _x1, _y1, text, *_ in pg.get_text("words"):
        x, y = x0 / w_pt, y0 / h_pt
        if x_lo <= x <= x_hi and y_lo <= y <= y_hi:
            ws.append((x, y, text))
    anchors = sorted((y, text) for x, y, text in ws if x >= area_x and NUM.match(text))
    rows = [{"y": y, "area": a, "room": None, "name": []} for y, a in anchors]
    for x, y, text in sorted(ws, key=lambda w: (w[1], w[0])):
        if x >= area_x and (NUM.match(text) or text in ("м²", "м2")):
            continue
        best = min(rows, key=lambda r: abs(r["y"] - y))
        if abs(best["y"] - y) > cluster:
            continue
        if x < room_x and best["room"] is None and re.fullmatch(r"[0-9А-Я]{1,3}", text):
            best["room"] = text
        else:
            best["name"].append(text)
    out = []
    for r in rows:
        name = " ".join(r["name"])
        if re.match(r"(?i)(общий итог|итого)", name):
            out.append({"name": name, "area_m2": r["area"], "_kind": "TOTAL"})
        elif r["room"] is None and out and "том числе" in str(out[-1].get("name", "")):
            out.append({"name": name, "area_m2": r["area"], "_kind": "SUBZONE", "_parent": len(out)})
        else:
            out.append({"room_no": r["room"], "name": name, "area_m2": r["area"], "_kind": "DATA"})
    return out


def _run_rule(rows, file_id, stage, page_no, rule_code):
    t = typed_table(f"{file_id}-p{page_no}", "EXPLICATION", rows, page_no=page_no)
    docs = {file_id: DocumentInfo(file_id, stage, "OV", 1)}
    inputs = HypothesisInputs(
        OBJECT_ID, docs, MemoryPageSource(), tables={file_id: table_artifacts(file_id, stage, [t])}
    )
    facts = FactBuilder(inputs).build()
    return RuleEngine([load_seed_rules().get(rule_code)]).evaluate(facts)


def test_hr_log_005_on_the_real_alt79b_pilot_explication():
    path = repo_root() / "ТЗ" / "Комплект_предметной_разметки.pdf"
    if not path.is_file():
        pytest.skip("ТЗ pilot markup not present")
    pg = pymupdf.open(path)[1]
    rows = _rows(pg, (0.78, 1.0, 0.125, 0.34), area_x=0.86, room_x=0.815, cluster=0.004)
    assert sum(1 for r in rows if r["_kind"] == "DATA") == 24
    [o] = _run_rule(rows, "PILOT", "PD", 2, "HR-LOG-005")
    assert o.status == "EMITTED"
    assert (round(o.values["sum_rows"], 2), round(o.values["total"], 2), round(o.values["delta"], 2)) == (
        2795.04,
        2797.27,
        2.23,
    )


def test_hr_log_011_on_the_real_tyumen_f0201_p18_explication(data_paths):
    rows_m = _manifest(data_paths)
    pg = _pdf(data_paths, rows_m, "F0201")[17]
    rows = _rows(pg, (0.0, 0.17, 0.775, 0.92), area_x=0.14, room_x=0.04, cluster=0.006)
    kinds = [r["_kind"] for r in rows]
    assert kinds.count("DATA") == 19 and kinds.count("SUBZONE") == 1 and kinds[-1] == "TOTAL"
    [o11] = _run_rule(rows, "F0201", "RD", 18, "HR-LOG-011")
    [o05] = _run_rule(rows, "F0201", "RD", 18, "HR-LOG-005")
    assert o11.status == "EMITTED" and o05.status == "SATISFIED"
    assert (
        round(o11.values["sum_rows"], 1),
        round(o11.values["sum_sub"], 1),
        round(o11.values["total"], 1),
    ) == (
        1049.5,
        30.4,
        1079.9,
    )


def _gold_free(data_paths) -> list[dict]:
    path = Path(data_paths.package_data_dir) / "public_train_checks.jsonl"
    with open(path, encoding="utf-8") as fh:
        return [r for r in map(json.loads, fh) if r["parameter_code"].startswith("FREE-")]


def test_free_heating_001_matches_the_gold_on_real_text_layers(data_paths):
    rows_m = _manifest(data_paths)
    f0171, f0202 = _pdf(data_paths, rows_m, "F0171"), _pdf(data_paths, rows_m, "F0202")
    pages = MemoryPageSource(_page_text(f0171, "F0171", p) for p in range(1, f0171.page_count + 1))
    for p in range(1, f0202.page_count + 1):
        pages.add(_page_text(f0202, "F0202", p))  # usable: absence of warm floors in F0202 per RT-06
    docs = {
        fid: DocumentInfo(fid, st, "OV", rows_m[fid]["pdf_pages"], file_sha256=rows_m[fid]["sha256"])
        for fid, st in (("F0171", "PD"), ("F0202", "RD"))
    }
    r = run_hypotheses(
        HypothesisInputs(OBJECT_ID, docs, pages, run_id="data-test"), HypothesisConfig(enable_rules=False)
    )
    [g] = r.free_groups
    gold = _gold_free(data_paths)
    assert sorted(x["location"] for x in gold) == g.locations
    by_loc = {f.location: f for f in r.free_findings}
    for gc in gold:
        f = by_loc[gc["location"]]
        for key in (
            "parameter_code",
            "pd_value",
            "rd_value",
            "id_value",
            "violation_label",
            "protocol_status",
            "criticality",
            "comparison_result",
            "matrix_scope",
            "document_status",
        ):
            got = getattr(f, key)
            assert (str(got) if got is not None else None) == gc[key], key
        assert [(str(e.stage), e.file_id, e.pdf_page_number) for e in f.evidence] == [
            (e["stage"], e["file_id"], e["pdf_page_number"]) for e in gc["evidence"]
        ]
    # the ПЗ sentence of p11 is the assertion; p136 (specification) supports it
    assert {(a.file_id, a.page_no) for a in r.free_candidates[0].assertions} == {("F0171", 11)}


@pytest.mark.slow
def test_free_heating_001_end_to_end_on_real_page_tokens(data_paths):
    """Real PageTokens (text layer + OCR) of a recognise run: INSPECTOR_HYP_E2E_RUN=runs/<run_id> (F0171 and F0202
    recognised in full). Documents and stages come from the registry, as in the batch run."""
    import os

    run = os.environ.get("INSPECTOR_HYP_E2E_RUN")
    if not run:
        pytest.skip("set INSPECTOR_HYP_E2E_RUN to a run directory with F0171/F0202 PageTokens")
    run_dir = Path(run) if Path(run).is_absolute() else repo_root() / run
    inputs = HypothesisInputs.from_run(run_dir, OBJECT_ID)
    r = run_hypotheses(inputs)
    [g] = [g for g in r.free_groups if g.parameter_code == "FREE-HEATING-001"]
    gold = _gold_free(data_paths)
    assert g.locations == sorted(x["location"] for x in gold)
    assert [(str(a.stage), a.file_id, a.pdf_page_number) for a in g.anchor_evidence] == [
        (e["stage"], e["file_id"], e["pdf_page_number"]) for e in gold[0]["evidence"]
    ]
    assert r.free_candidates[0].absence in ("DOCUMENT", "COUNTERPART")
