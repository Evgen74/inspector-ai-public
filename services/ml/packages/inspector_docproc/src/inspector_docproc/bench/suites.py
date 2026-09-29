"""Benchmark suites over ``recognition_benchmark.json`` (96 §1; R-01).

Suites:
- ``vector`` (group A): the OCR engine on renders of vector pages, scored against their own text layer
  (per region; regions with < 50 GT characters are skipped). Also exact match of document codes and
  room/number tokens found in the text layer of those regions.
- ``scans`` (groups B, D with hand GT): the production page path (router → orientation → OCR →
  post-correction) on real scans and outlined pages, scored against the hand transcriptions; key-field
  exact match on the benchmark's key fields.
- ``orientation``: content-orientation detection on the scan pages as they are and turned by 90/180/270.
- ``drawings`` (R-04 acceptance): on the gold RD sheets, recall of the text a full-page OCR finds where the
  text layer has gaps (word-level coverage routing must not lose it) and the gold room labels; outlined
  title-block key fields; the expected route of the routing-test pages (groups A drawings, C, D).
All numbers come from running the code; nothing is copied from the reports.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from inspector_docproc.bench import metrics as M
from inspector_docproc.codefix import post_correct
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.ocr.engine import OcrEngine
from inspector_docproc.ocr.pipeline import OcrLine
from inspector_docproc.orientation import detect_orientation, rotate_image
from inspector_docproc.recognize import OCR_SOURCES, PageRecognizer, ocr_with_fallback
from inspector_docproc.render import choose_dpi, image_facts, render_page

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BENCH = PACKAGE_ROOT / "tests" / "data" / "recognition_benchmark.json"

# Expected content rotation (clockwise) of the benchmark scan pages as displayed; checked visually.
ORIENTATION_EXPECTED = {
    "B01": 0, "B02": 0, "B03": 0, "B04": 90, "B05": 0, "B06": 0, "B07": 0, "B08": 0,
    "C01": 0, "C02": 0, "C04": 0, "D03": 0,
}  # fmt: skip


# Expected (page class, action) of the routing-test pages, from each page's benchmark description.
EXPECTED_ROUTES = {
    "A04": ("VECTOR", "text+coverage"), "A05": ("VECTOR", "text+coverage"), "A06": ("VECTOR", "text+coverage"),
    "C01": ("HYBRID", "ocr_full"),  # visible garbage scanner layer over a scan: not trusted
    "C02": ("RASTER_HIDDEN_OCR", "ocr_full"),
    "C03": ("VECTOR", "text"),
    "C04": ("RASTER_SCAN", "ocr_full"),
    "D01": ("VECTOR_OUTLINED_TEXT", "ocr_full"), "D02": ("VECTOR_OUTLINED_TEXT", "ocr_full"),
    "D03": ("VECTOR_OUTLINED_TEXT", "ocr_full"), "D04": ("VECTOR_OUTLINED_TEXT", "ocr_full"),
}  # fmt: skip
DRAWING_PAGES = ("A04", "A05", "A06")  # gold RD sheets: 65 % of their text lines are curves (96 §4.1)
TITLE_BLOCK_FIELDS = ("шифр", "стадия", "лист", "листов")
TITLE_BLOCK_MM = (210.0, 80.0)  # bottom-right search window: ГОСТ 21.101 stamp 185×55 mm + frame + margin


def load_benchmark(path: Path | None = None) -> dict[str, Any]:
    bench = json.loads((path or DEFAULT_BENCH).read_text(encoding="utf-8"))
    bench["_dir"] = str((path or DEFAULT_BENCH).resolve().parent)
    return bench


def load_gt_v2(bench: dict[str, Any]) -> dict[str, Any] | None:
    """The adjudicated line GT v2 (``gt_sets.v2``), sha256-checked against the benchmark; None if absent."""
    spec = (bench.get("gt_sets") or {}).get("v2")
    if not spec:
        return None
    path = Path(bench.get("_dir") or DEFAULT_BENCH.parent) / spec["file"]
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != spec["sha256"]:
        raise ValueError(f"{path.name}: sha256 {digest[:12]} differs from gt_sets.v2 ({spec['sha256'][:12]})")
    return json.loads(raw)


@dataclass(slots=True)
class BenchContext:
    documents_root: Path
    cfg: RecognitionConfig
    exec_cfg: ExecutionConfig
    engine: OcrEngine
    recognizer: PageRecognizer
    pages: dict[str, tuple[dict[str, Any], float, float]] = field(default_factory=dict)

    def open(self, rel: str):
        import pymupdf

        return pymupdf.open(self.documents_root / rel)

    def recognize(self, entry: dict[str, Any]) -> tuple[dict[str, Any], float, float]:
        """Production PageTokens of a benchmark page, computed once per run: (doc, wall s, CPU s)."""
        hit = self.pages.get(entry["id"])
        if hit is None:
            with self.open(entry["relative_path"]) as doc:
                t0, c0 = time.perf_counter(), time.process_time()
                out = self.recognizer.recognize_page(
                    doc, entry["pdf_page_number"], file_id=entry["file_id"], file_sha256=entry["file_sha256"]
                )
                hit = (out, time.perf_counter() - t0, time.process_time() - c0)
            self.pages[entry["id"]] = hit
        return hit


def gt_chars(page) -> list[dict[str, Any]]:
    """Visible text-layer glyphs (texttrace; render mode ≠ 3, opacity > 0, not white) in displayed pt."""
    import pymupdf

    rm = page.rotation_matrix
    out = []
    for si, sp in enumerate(page.get_texttrace()):
        if sp.get("type") == 3 or sp.get("opacity", 1) == 0:
            continue
        col = sp.get("color") or (0, 0, 0)
        if len(col) >= 3 and min(col[:3]) > 0.95:
            continue
        for ch in sp["chars"]:
            u = chr(ch[0]) if ch[0] >= 0 else ""
            if not u or u.isspace():
                continue
            r = pymupdf.Rect(ch[3]) * rm
            if r.is_empty or r.width <= 0 or r.height <= 0:
                o = pymupdf.Point(ch[2]) * rm
                r = pymupdf.Rect(o.x - 1, o.y - 2, o.x + 1, o.y)
            out.append({"c": u, "x": (r.x0 + r.x1) / 2, "y": (r.y0 + r.y1) / 2, "r": tuple(r), "sid": si})
    return out


def text_layer_fields(page, region: tuple[float, float, float, float]) -> list[tuple[str, str, list[float]]]:
    """Document codes and room/number tokens of the text layer inside a region (displayed pt)."""
    import pymupdf

    rm = page.rotation_matrix
    fields = []
    for w in page.get_text("words"):
        r = pymupdf.Rect(w[:4]) * rm
        t = w[4]
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if not (region[0] <= cx <= region[2] and region[1] <= cy <= region[3]):
            continue
        if M.is_code_field(t):
            fields.append(("CODE", t, [r.x0, r.y0, r.x1, r.y1]))
        elif M.ROOM_RE.match(t):
            fields.append(("ROOM_OR_NUM", t, [r.x0, r.y0, r.x1, r.y1]))
    return fields


def _lines_pt(
    lines: list[OcrLine],
    zoom: float,
    origin: tuple[float, float],
    corrected: bool,
    extras: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    out = []
    for ln in lines:
        text = post_correct(ln.text, extras)[0] if corrected else ln.text
        out.append({"poly": ln.quad / zoom + np.array(origin), "text": text, "score": ln.score})
    return out


# ── Suite: vector pages (group A) ────────────────────────────────────────────────────────────


def suite_vector(ctx: BenchContext, bench: dict[str, Any], dpi: int = 300, log=None) -> dict[str, Any]:
    import pymupdf

    units_raw: list[dict[str, Any]] = []
    fields: dict[str, dict[str, Any]] = {
        "CODE": {"n": 0, "raw": 0, "fixed": 0, "fixed_relaxed": 0, "misses": []},
        "ROOM_OR_NUM": {"n": 0, "raw": 0, "fixed": 0, "fixed_relaxed": 0, "misses": []},
    }
    per_region = []
    t_all = time.perf_counter()
    cpu_all = time.process_time()
    for entry in bench["pages"]:
        if entry["group"] != "A":
            continue
        with ctx.open(entry["relative_path"]) as doc:
            page = doc[entry["pdf_page_number"] - 1]
            gt = gt_chars(page)
            W, H = page.rect.width, page.rect.height
            for rname, rn in entry["regions_norm"].items():
                reg = (rn[0] * W, rn[1] * H, rn[2] * W, rn[3] * H)
                t0, c0 = time.perf_counter(), time.process_time()
                img = render_page(page, dpi, clip=pymupdf.Rect(*reg))
                lines, info = ocr_with_fallback(ctx.engine, img, ctx.cfg.ocr)
                wall, cpu = time.perf_counter() - t0, time.process_time() - c0
                zoom = img.shape[1] / (reg[2] - reg[0])
                raw = _lines_pt(lines, zoom, (reg[0], reg[1]), corrected=False)
                res = M.score_text_layer(gt, raw, reg)
                row = {
                    "id": entry["id"],
                    "region": rname,
                    "n_gt": res["strict"]["N"],
                    "ca_strict": round(M.ca(res["strict"]), 4),
                    "ca_relaxed": round(M.ca(res["relaxed"]), 4),
                    "wall_s": round(wall, 2),
                    "cpu_s": round(cpu, 2),
                    "megapixels": round(img.shape[0] * img.shape[1] / 1e6, 2),
                    "fallback_used": info["fallback_used"],
                    "scored": res["strict"]["N"] >= 50,
                }
                per_region.append(row)
                if log:
                    log(f"A {entry['id']}/{rname}: CA {row['ca_strict']:.3f} (N={row['n_gt']}) {wall:.1f}s")
                if res["strict"]["N"] >= 50:
                    units_raw.append(res)
                fixed = _lines_pt(
                    lines, zoom, (reg[0], reg[1]), corrected=True, extras=ctx.recognizer.code_extras
                )
                for kind, tok, box in text_layer_fields(page, reg):
                    f = fields[kind]
                    f["n"] += 1
                    f["raw"] += M.field_em(kind, tok, box, raw, False)
                    ok = M.field_em(kind, tok, box, fixed, False)
                    f["fixed"] += ok
                    f["fixed_relaxed"] += M.field_em(kind, tok, box, fixed, True)
                    if not ok:
                        f["misses"].append(f"{entry['id']}/{rname}:{tok}")
    wall_all = time.perf_counter() - t_all
    cpu_total = time.process_time() - cpu_all
    mp = sum(r["megapixels"] for r in per_region)
    return {
        "dpi": dpi,
        "ca": {mode: M.pooled(units_raw, mode) for mode in M.MODES},
        "key_fields": {
            k: {
                "n": v["n"],
                "em_raw": round(v["raw"] / max(v["n"], 1), 4),
                "em_corrected": round(v["fixed"] / max(v["n"], 1), 4),
                "em_corrected_relaxed": round(v["fixed_relaxed"] / max(v["n"], 1), 4),
                "misses": v["misses"][:40],
            }
            for k, v in fields.items()
        },
        "regions": per_region,
        "wall_s": round(wall_all, 1),
        "cpu_s": round(cpu_total, 1),
        "cpu_s_per_mp": round(cpu_total / max(mp, 1e-6), 3),
        "wall_s_per_region": round(wall_all / max(len(per_region), 1), 2),
    }


# ── Suite: scans and outlined pages (groups B, D with hand GT) ───────────────────────────────


def _page_lines(tokens_doc: dict[str, Any], corrected: bool) -> list[dict[str, Any]]:
    """OCR lines of a PageTokens document in displayed pt (raw = before post-correction)."""
    W, H = tokens_doc["page"]["width_pt"], tokens_doc["page"]["height_pt"]
    toks = tokens_doc["tokens"]
    out = []
    for ln in tokens_doc.get("lines", []):
        if ln.get("source") not in OCR_SOURCES:
            continue
        words = [toks[i] for i in ln["token_ids"]]
        text = " ".join((w["text"] if corrected else (w.get("text_raw") or w["text"])) for w in words)
        poly = np.array(
            ln.get("polygon")
            or [
                [ln["bbox"][0], ln["bbox"][1]],
                [ln["bbox"][2], ln["bbox"][1]],
                [ln["bbox"][2], ln["bbox"][3]],
                [ln["bbox"][0], ln["bbox"][3]],
            ],
            float,
        )
        out.append({"poly": poly * np.array([W, H]), "text": text, "score": float(ln.get("conf", 1.0))})
    return out


def suite_scans(ctx: BenchContext, bench: dict[str, Any], log=None) -> dict[str, Any]:
    hand = bench["hand_gt"]
    units: dict[str, list] = {"raw": [], "corrected": []}
    kf = {"n": 0, "strict": 0, "relaxed": 0, "misses": []}
    pages = []
    for entry in bench["pages"]:
        ref = entry.get("gt_ref")
        if not ref:
            continue
        gt = hand[ref.split(".", 1)[1]]
        out, wall, cpu = ctx.recognize(entry)
        row: dict[str, Any] = {
            "id": entry["id"],
            "page_class": out["page_class"],
            "render_dpi": out["page"].get("render_dpi"),
            "content_rotation": out["page"].get("content_rotation"),
            "fallback_used": out.get("ext", {}).get("ocr", {}).get("fallback_used"),
            "wall_s": round(wall, 2),
            "cpu_s": round(cpu, 2),
        }
        for variant, corrected in (("raw", False), ("corrected", True)):
            lines = _page_lines(out, corrected)
            res, worst = M.score_line_gt(gt, lines)
            units[variant].append(res)
            row[f"ca_{variant}"] = {m: round(M.ca(res[m]), 4) for m in M.MODES}
            row["n_gt"] = res["strict"]["N"]
            if variant == "raw":
                row["worst"] = [(g, o[:3], d) for g, o, d in sorted(worst, key=lambda x: -x[2])[:5]]
        fixed_lines = _page_lines(out, True)
        for tok in entry.get("key_fields") or []:
            box = M.find_token_box(gt, tok)
            if box is None:
                continue
            kf["n"] += 1
            s = M.token_em(tok, box, fixed_lines, relaxed=False)
            r = M.token_em(tok, box, fixed_lines, relaxed=True)
            kf["strict"] += s
            kf["relaxed"] += r
            if not r:
                kf["misses"].append(f"{entry['id']}:{tok}")
        pages.append(row)
        if log:
            log(
                f"{entry['id']}: CA {row['ca_raw']['strict']:.3f} (N={row['n_gt']}) {out['page_class']} rot={row['content_rotation']} dpi={row['render_dpi']} {wall:.1f}s"
            )
    return {
        "ca_raw": {mode: M.pooled(units["raw"], mode) for mode in M.MODES},
        "ca_corrected": {mode: M.pooled(units["corrected"], mode) for mode in M.MODES},
        "key_fields": {
            "n": kf["n"],
            "em_strict": round(kf["strict"] / max(kf["n"], 1), 4),
            "em_relaxed": round(kf["relaxed"] / max(kf["n"], 1), 4),
            "misses_relaxed": kf["misses"],
        },
        "pages": pages,
        "wall_s_per_page": round(sum(p["wall_s"] for p in pages) / max(len(pages), 1), 2),
        "cpu_s_per_page": round(sum(p["cpu_s"] for p in pages) / max(len(pages), 1), 2),
    }


# ── Suite: scans and outlined pages against the adjudicated GT v2 ─────────────────────────────


def _pooled_subset(
    units: dict[str, dict[str, dict[str, int]]], ids: list[str], mode: str
) -> dict[str, float]:
    return M.pooled([units[i] for i in ids if i in units], mode)


def suite_scans_v2(ctx: BenchContext, bench: dict[str, Any], log=None) -> dict[str, Any] | None:
    """The production page path on the 14 GT v2 pages (``ocr_gt_v2.json``), scored with
    :func:`metrics.score_line_gt_v2`; key fields v2; predicted zones against the GT excluded zones."""
    gt_all = load_gt_v2(bench)
    if gt_all is None:
        return None
    v1_ids = sorted(bench.get("hand_gt", {}))
    units: dict[str, dict[str, dict[str, dict[str, int]]]] = {"raw": {}, "corrected": {}}
    kf = {"n": 0, "strict": 0, "relaxed": 0, "misses": []}
    zones_total: dict[str, Counter[str]] = {f: Counter() for f in M.ZONE_FAMILIES}
    pages = []
    for entry in bench["pages"]:
        ref = entry.get("gt_ref_v2")
        if not ref:
            continue
        pid = entry["id"]
        gt = gt_all["pages"][ref.split(".", 1)[1]]
        out, wall, cpu = ctx.recognize(entry)
        row: dict[str, Any] = {
            "id": pid,
            "set": gt.get("set"),
            "page_class": out["page_class"],
            "render_dpi": out["page"].get("render_dpi"),
            "content_rotation": out["page"].get("content_rotation"),
            "wall_s": round(wall, 2),
            "cpu_s": round(cpu, 2),
        }
        for variant, corrected in (("raw", False), ("corrected", True)):
            res, worst, extras = M.score_line_gt_v2(gt, _page_lines(out, corrected))
            units[variant][pid] = res
            row[f"ca_{variant}"] = {m: round(M.ca(res[m]), 4) for m in M.MODES_V2}
            if variant == "raw":
                row.update(
                    n_gt=res["strict"]["N"],
                    ins_rate=round(res["strict"]["ins"] / max(res["strict"]["N"], 1), 4),
                    n_uncertain=extras["n_uncertain"],
                    chars_by_kind=extras["chars_by_kind"],
                    inserted_sample=extras["inserted_sample"],
                    worst=[(g, o[:3], d) for g, o, d in sorted(worst, key=lambda x: -x[2])[:5]],
                )
        fixed_lines = _page_lines(out, True)
        for tok in entry.get("key_fields_v2") or []:
            box = M.find_token_box(gt, tok)
            if box is None:
                continue
            kf["n"] += 1
            s = M.token_em(tok, box, fixed_lines, relaxed=False)
            r = M.token_em(tok, box, fixed_lines, relaxed=True)
            kf["strict"] += s
            kf["relaxed"] += r
            if not r:
                kf["misses"].append(f"{pid}:{tok}")
        zres = M.score_zones(out.get("zones") or [], gt.get("excluded_zones", []))
        row["zones"] = {f: v for f, v in zres.items() if v["n_gt"] or v["n_pred"]}
        for f, v in zres.items():
            zones_total[f].update(v)
        pages.append(row)
        if log:
            log(
                f"v2 {pid}: CA {row['ca_raw']['strict']:.3f} (N={row['n_gt']}) {out['page_class']} {wall:.1f}s"
            )
    ids = [p["id"] for p in pages]
    scans = [i for i in ids if not i.startswith("D")]
    outlined = [i for i in ids if i.startswith("D")]
    return {
        "gt": {"version": gt_all.get("version"), "pages": len(ids), "method": gt_all.get("method")},
        "ca_raw": {mode: _pooled_subset(units["raw"], ids, mode) for mode in M.MODES_V2},
        "ca_corrected": {mode: _pooled_subset(units["corrected"], ids, mode) for mode in M.MODES_V2},
        "ca_raw_v1_pages": {mode: _pooled_subset(units["raw"], v1_ids, mode) for mode in M.MODES_V2},
        "ca_raw_scans": {mode: _pooled_subset(units["raw"], scans, mode) for mode in M.MODES_V2},
        "ca_raw_outlined": {mode: _pooled_subset(units["raw"], outlined, mode) for mode in M.MODES_V2},
        # production output (PageTokens text after post-correction), the headline since M1
        "ca_corrected_v1_pages": {
            mode: _pooled_subset(units["corrected"], v1_ids, mode) for mode in M.MODES_V2
        },
        "ca_corrected_scans": {mode: _pooled_subset(units["corrected"], scans, mode) for mode in M.MODES_V2},
        "ca_corrected_outlined": {
            mode: _pooled_subset(units["corrected"], outlined, mode) for mode in M.MODES_V2
        },
        "key_fields": {
            "n": kf["n"],
            "em_strict": round(kf["strict"] / max(kf["n"], 1), 4),
            "em_relaxed": round(kf["relaxed"] / max(kf["n"], 1), 4),
            "misses_relaxed": kf["misses"],
        },
        "zones": {
            f: {
                **dict(c),
                "recall_iou03": round(c["hit"] / c["n_gt"], 4) if c["n_gt"] else None,
                "recall_covered": round(c["covered"] / c["n_gt"], 4) if c["n_gt"] else None,
            }
            for f, c in zones_total.items()
        },
        "pages": pages,
        "wall_s_per_page": round(sum(p["wall_s"] for p in pages) / max(len(pages), 1), 2),
    }


# ── Suite: orientation ───────────────────────────────────────────────────────────────────────


def suite_orientation(ctx: BenchContext, bench: dict[str, Any], log=None) -> dict[str, Any]:
    cases = []
    by_id = {e["id"]: e for e in bench["pages"]}
    for pid, expected in ORIENTATION_EXPECTED.items():
        entry = by_id.get(pid)
        if entry is None:
            continue
        with ctx.open(entry["relative_path"]) as doc:
            page = doc[entry["pdf_page_number"] - 1]
            facts = image_facts(page)
            dpi = choose_dpi("scan", facts.native_dpi, ctx.cfg.render)
            img = render_page(page, dpi)
        for turns in range(4):  # extra clockwise quarter turns applied to the render
            work = rotate_image(img, -turns)
            t0 = time.perf_counter()
            res = detect_orientation(ctx.engine, work, ctx.cfg.orientation)
            dt = time.perf_counter() - t0
            want = (expected + 90 * turns) % 360
            cases.append(
                {"id": pid, "turn": 90 * turns, "expected": want, "got": res.content_rotation,
                 "ok": res.content_rotation == want, "method": res.method, "margin": round(res.margin, 3),
                 "seconds": round(dt, 2)}
            )  # fmt: skip
            if log and res.content_rotation != want:
                log(
                    f"orientation miss {pid}+{90 * turns}: expected {want}, got {res.content_rotation} ({res.method})"
                )
    n_ok = sum(c["ok"] for c in cases)
    natural = [c for c in cases if c["turn"] == 0]
    return {
        "n": len(cases),
        "accuracy": round(n_ok / max(len(cases), 1), 4),
        "natural_n": len(natural),
        "natural_accuracy": round(sum(c["ok"] for c in natural) / max(len(natural), 1), 4),
        "misses": [c for c in cases if not c["ok"]],
        "methods": dict(Counter(c["method"] for c in cases).most_common()),
        # smallest score gap between the winning and the runner-up hypothesis (det_rec_probe decisions)
        "min_margin": round(
            min((c["margin"] for c in cases if c["method"] == "det_rec_probe"), default=0.0), 3
        ),
        "seconds_per_case": round(float(np.mean([c["seconds"] for c in cases])) if cases else 0.0, 2),
    }


# ── Suite: drawings, title blocks and routing (R-04 acceptance) ──────────────────────────────


def gold_rooms_by_page(train_checks_path: Path) -> dict[tuple[str, int], list[str]]:
    """Gold ROOM locations per RD evidence page of the public TRAIN gold (``public_train_checks.jsonl``)."""
    out: dict[tuple[str, int], list[str]] = {}
    if not train_checks_path.is_file():
        return out
    for line in train_checks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("location_type") != "ROOM":
            continue
        for ev in row.get("evidence") or []:
            if ev.get("stage") == "RD":
                key = (ev["file_id"], int(ev["pdf_page_number"]))
                if row["location"] not in out.setdefault(key, []):
                    out[key].append(row["location"])
    return out


def _token_centres(tokens: list[dict[str, Any]]) -> np.ndarray:
    tb = np.array([t["bbox"] for t in tokens], float) if tokens else np.zeros((0, 4))
    return (
        np.stack([(tb[:, 0] + tb[:, 2]) / 2, (tb[:, 1] + tb[:, 3]) / 2], 1) if len(tb) else np.zeros((0, 2))
    )


def text_gap_capture(ctx: BenchContext, page, out: dict[str, Any], max_err: float = 0.2) -> dict[str, Any]:
    """Recall of full-page OCR lines that lie in text-layer gaps, against the production PageTokens.

    Reference: OCR of the whole page at the vector dpi, lines with score ≥ the acceptance threshold whose
    box is less than ``covered_share`` covered by visible text-layer words. A line is captured when the
    production tokens (any source) centred in its box (± 0.3 of its smaller side), in reading order,
    contain its text within ``max_err`` relative edit distance (relaxed, case-folded).
    """
    from inspector_docproc.ocr.pipeline import ocr_image
    from inspector_docproc.recognize import coverage_of
    from inspector_docproc.textlayer import extract_text_layer
    from inspector_docproc.textnorm import norm_relaxed_ci

    img = render_page(page, ctx.cfg.render.vector_dpi)
    h, w = img.shape[:2]
    ref, _ = ocr_image(ctx.engine, img, ctx.cfg.ocr)
    ref = [ln for ln in ref if ln.score >= ctx.cfg.ocr.min_line_score and ln.text.strip()]
    words = [x.bbox for x in extract_text_layer(page).visible_words]
    boxes = (
        np.array([[*ln.quad.min(0) / (w, h), *ln.quad.max(0) / (w, h)] for ln in ref])
        if ref
        else np.zeros((0, 4))
    )
    cover = coverage_of(boxes, np.array(words) if words else np.zeros((0, 4)))
    gaps = [(ln, b) for ln, b, c in zip(ref, boxes, cover, strict=True) if c < ctx.cfg.router.covered_share]
    toks = out["tokens"]
    centres = _token_centres(toks)
    captured, misses = 0, []
    for ln, b in gaps:
        e = 0.3 * min(b[2] - b[0], b[3] - b[1])
        inside = np.where(
            (centres[:, 0] >= b[0] - e) & (centres[:, 0] <= b[2] + e) & (centres[:, 1] >= b[1] - e) & (centres[:, 1] <= b[3] + e)
        )[0] if len(centres) else np.zeros(0, int)  # fmt: skip
        horizontal = (b[2] - b[0]) >= (b[3] - b[1])
        order = sorted(
            inside.tolist(),
            key=(lambda i: (round(centres[i, 1] / 0.004), centres[i, 0]))
            if horizontal
            else (lambda i: (round(centres[i, 0] / 0.004), -centres[i, 1])),
        )
        # the reference is raw OCR, so it is compared with the raw text of the tokens (``text_raw``): this
        # measures capture, and post-correction («φ25» → «Ø25», «Cm» → «Ст») must not count as a miss
        raw = "".join(toks[i].get("text_raw") or toks[i]["text"] for i in order)
        found = norm_relaxed_ci(raw)
        want = norm_relaxed_ci(ln.text)
        if M.semi_global(want, found) <= max_err * len(want):
            captured += 1
        else:
            misses.append((ln.text, raw[:40]))
    return {
        "gap_lines": len(gaps),
        "captured": captured,
        "recall": round(captured / max(len(gaps), 1), 4),
        "misses": misses[:30],
    }


def _present(token: str, texts: list[str]) -> bool:
    import re

    rx = re.compile(r"(?<![\w.])" + re.escape(token) + r"(?![\w])")
    return any(rx.search(t) for t in texts)


def title_block_fields(out: dict[str, Any], expected: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Key fields of the stamp found (with word boundaries) in production lines of the bottom-right window."""
    from inspector_docproc.textnorm import HOMO

    w_mm = out["page"]["width_pt"] * 25.4 / 72
    h_mm = out["page"]["height_pt"] * 25.4 / 72
    x0, y0 = 1 - TITLE_BLOCK_MM[0] / w_mm, 1 - TITLE_BLOCK_MM[1] / h_mm
    texts = [
        ln["text"]
        for ln in out.get("lines", [])
        if (ln["bbox"][0] + ln["bbox"][2]) / 2 >= x0 and (ln["bbox"][1] + ln["bbox"][3]) / 2 >= y0
    ]
    res: dict[str, dict[str, bool]] = {}
    for key in TITLE_BLOCK_FIELDS:
        value = expected.get(key)
        if not isinstance(value, str):
            continue
        res[key] = {
            "strict": _present(value, texts),
            "relaxed": _present(value.translate(HOMO), [t.translate(HOMO) for t in texts]),
        }
    return res


def suite_drawings(
    ctx: BenchContext, bench: dict[str, Any], train_checks_path: Path, log=None
) -> dict[str, Any]:
    gold = gold_rooms_by_page(train_checks_path)
    pages, routes = [], []
    tb_n = tb_strict = tb_relaxed = 0
    tb_misses: list[str] = []
    gap_total = gap_captured = 0
    rooms_n = rooms_found = 0
    for entry in bench["pages"]:
        pid = entry["id"]
        wants_route = pid in EXPECTED_ROUTES
        tb_expected = entry.get("key_fields_title_block") or {}
        if not (wants_route or tb_expected):
            continue
        out, wall, _ = ctx.recognize(entry)
        with ctx.open(entry["relative_path"]) as doc:
            row: dict[str, Any] = {"id": pid, "page_class": out["page_class"], "wall_s": round(wall, 2)}
            route = (out.get("ext") or {}).get("route") or {}
            if wants_route:
                want = EXPECTED_ROUTES[pid]
                got = (out["page_class"], route.get("action"))
                routes.append({"id": pid, "expected": list(want), "got": list(got), "ok": got == want,
                               "reason": route.get("reason")})  # fmt: skip
            if pid in DRAWING_PAGES:
                cap = text_gap_capture(ctx, doc[entry["pdf_page_number"] - 1], out)
                row["text_gaps"] = cap
                gap_total += cap["gap_lines"]
                gap_captured += cap["captured"]
                texts = [t["text"] for t in out["tokens"]]
                rooms = {
                    loc: _present(loc, texts)
                    for loc in gold.get((entry["file_id"], entry["pdf_page_number"]), [])
                }
                row["gold_rooms"] = rooms
                rooms_n += len(rooms)
                rooms_found += sum(rooms.values())
        if tb_expected:
            fields = title_block_fields(out, tb_expected)
            row["title_block"] = fields
            for key, r in fields.items():
                tb_n += 1
                tb_strict += r["strict"]
                tb_relaxed += r["relaxed"]
                if not r["strict"]:
                    tb_misses.append(f"{pid}:{key}={tb_expected[key]}")
        pages.append(row)
        if log:
            log(f"drawings {pid}: {out['page_class']} {route.get('action')} {wall:.1f}s")
    return {
        "routes": {"n": len(routes), "ok": sum(r["ok"] for r in routes), "cases": routes},
        "text_gaps": {
            "pages": len(DRAWING_PAGES),
            "gap_lines": gap_total,
            "captured": gap_captured,
            "recall": round(gap_captured / max(gap_total, 1), 4),
        },
        "gold_rooms": {"n": rooms_n, "found": rooms_found},
        "title_block": {
            "n": tb_n,
            "em_strict": round(tb_strict / max(tb_n, 1), 4),
            "em_relaxed": round(tb_relaxed / max(tb_n, 1), 4),
            "misses_strict": tb_misses,
        },
        "pages": pages,
    }
