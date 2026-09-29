"""Layout benchmarks (96 R-06/R-07 acceptance): document codes on the 17 benchmark stamps, sheet = stamp.

``codes`` — the gate «document codes EM ≥ 0.95» on the stamps of ``recognition_benchmark.json``:
- **11 vector codes**: every code-shaped text-layer token inside the group-A regions (the AG-02A metric of
  ``inspector_docproc.bench.suites.suite_vector``: region rendered at 300 dpi, OCR v2, exact match of the token
  inside the corrected text of the lines around it, word boundaries enforced). Correction here = AG-02A's
  post-correction followed by the layout code gate (:func:`codes.gate_text`) with the object's registry prior.
- **6 outlined title blocks** (A04, A05, A06, D01, D02, D04): the full title-block reader (text layer → OCR of
  the stamp window) must return the benchmark шифр exactly; стадия/лист/листов and Изм. rows are reported.

``sheets`` — «sheet = stamp ≥ 0.95» on every drawing page of the ground-truth file
(``tests/data/sheet_stamp_gt.json``, stamp sheet numbers verified visually on rendered stamps): the sheet
number of the sheet ↔ page map must equal the printed one. Duplicates must be flagged where the GT says so.

    cd services/ml && uv run --frozen python -m inspector_layout.bench --suite codes --out /tmp/codes.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SHEET_GT = PACKAGE_ROOT / "tests" / "data" / "sheet_stamp_gt.json"
OUTLINED_IDS = ("A04", "A05", "A06", "D01", "D02", "D04")


def _stage_of(manifest_stage: str) -> str | None:
    return manifest_stage if manifest_stage in ("PD", "RD", "ID") else None


def suite_codes(paths, *, providers: str = "cpu", threads: int = 2, log=print) -> dict[str, Any]:
    import numpy as np
    import pymupdf

    from inspector_docproc.bench import metrics as M
    from inspector_docproc.bench.suites import load_benchmark, text_layer_fields
    from inspector_docproc.codefix import post_correct
    from inspector_docproc.config import ExecutionConfig, RecognitionConfig
    from inspector_docproc.inputs import load_manifest
    from inspector_docproc.recognize import ocr_with_fallback
    from inspector_docproc.render import render_page
    from inspector_layout.codes import CodeRegistry, gate_text
    from inspector_layout.pagescan import PageScanner, ScanOptions

    bench = load_benchmark()
    rows = load_manifest(paths)
    regs: dict[str, CodeRegistry] = {}

    def reg(obj: str) -> CodeRegistry:
        if obj not in regs:
            regs[obj] = CodeRegistry.from_manifest_rows(rows, obj)
        return regs[obj]

    cfg = RecognitionConfig()  # the AG-02A benchmark configuration (v6-small + medium union)
    exec_cfg = ExecutionConfig(providers=providers, threads=threads, warmup=False)
    scanner_cache: dict[str, PageScanner] = {}
    vector: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    engine = None
    for entry in bench["pages"]:
        if entry["group"] != "A":
            continue
        with pymupdf.open(paths.documents_root / entry["relative_path"]) as doc:
            page = doc[entry["pdf_page_number"] - 1]
            W, H = page.rect.width, page.rect.height
            for rname, rn in entry["regions_norm"].items():
                reg_pt = (rn[0] * W, rn[1] * H, rn[2] * W, rn[3] * H)
                fields = [f for f in text_layer_fields(page, reg_pt) if f[0] == "CODE"]
                if not fields:
                    continue
                if engine is None:
                    from inspector_docproc.ocr.engine import OcrEngine

                    engine = OcrEngine(cfg=cfg.ocr, providers=exec_cfg.providers, threads=exec_cfg.threads)
                img = render_page(page, 300, clip=pymupdf.Rect(*reg_pt))
                lines, _ = ocr_with_fallback(engine, img, cfg.ocr)
                zoom = img.shape[1] / (reg_pt[2] - reg_pt[0])
                r = reg(entry["object_id"])
                stage = _stage_of(entry["stage"])
                raw_l, fix_l, gate_l = [], [], []
                for ln in lines:
                    poly = ln.quad / zoom + np.array((reg_pt[0], reg_pt[1]))
                    fixed = post_correct(ln.text, r.extras())[0]
                    raw_l.append({"poly": poly, "text": ln.text, "score": ln.score})
                    fix_l.append({"poly": poly, "text": fixed, "score": ln.score})
                    gate_l.append({"poly": poly, "text": gate_text(fixed, r, stage=stage), "score": ln.score})
                for _, tok, box in fields:
                    row = {
                        "id": entry["id"],
                        "file_id": entry["file_id"],
                        "page": entry["pdf_page_number"],
                        "region": rname,
                        "gt": tok,
                        "raw": bool(M.field_em("CODE", tok, box, raw_l, False)),
                        "corrector": bool(M.field_em("CODE", tok, box, fix_l, False)),
                        "gate": bool(M.field_em("CODE", tok, box, gate_l, False)),
                    }
                    if not row["gate"]:
                        near = [
                            x["text"] for x in gate_l if M._intersects(M.bbox_of(np.asarray(x["poly"])), box)
                        ]
                        row["ocr_near"] = near[:3]
                    vector.append(row)
                    log(f"код {entry['id']}/{rname}: {tok} → {'ok' if row['gate'] else 'MISS'}")
    outlined: list[dict[str, Any]] = []
    by_id = {e["id"]: e for e in bench["pages"]}
    for pid in OUTLINED_IDS:
        entry = by_id[pid]
        gt = entry.get("key_fields_title_block") or {}
        obj = entry["object_id"]
        if obj not in scanner_cache:
            scanner_cache[obj] = PageScanner(
                reg(obj), ScanOptions(providers=providers, threads=threads, qr=False)
            )
        sc = scanner_cache[obj]
        with pymupdf.open(paths.documents_root / entry["relative_path"]) as doc:
            res = sc.scan(
                doc, entry["pdf_page_number"], file_id=entry["file_id"], stage_hint=_stage_of(entry["stage"])
            )
        tb = res.title_block or {}
        row = {
            "id": pid,
            "file_id": entry["file_id"],
            "page": entry["pdf_page_number"],
            "source": res.words_source,
            "code_gt": gt.get("шифр"),
            "code_raw": tb.get("document_code_raw"),
            "code": tb.get("document_code"),
            "code_ok": tb.get("document_code") == gt.get("шифр"),
            "stage_ok": (tb.get("stage_raw") == gt["стадия"]) if "стадия" in gt else None,
            "sheet_ok": (str(tb.get("sheet_number")) == gt["лист"]) if "лист" in gt else None,
            "sheets_ok": (str(tb.get("sheets_total")) == gt["листов"]) if "листов" in gt else None,
        }
        if "изм_rows" in gt:
            got = [
                " ".join(x for x in (r.get("change_no"), r.get("sheet"), r.get("doc_no"), r.get("date")) if x)
                for r in tb.get("change_rows", [])
            ]
            row["change_rows_gt"] = gt["изм_rows"]
            row["change_rows"] = got
            row["change_rows_ok"] = got == gt["изм_rows"]
        outlined.append(row)
        log(f"штамп {pid}: {row['code']} ({'ok' if row['code_ok'] else 'MISS'}), ист. {row['source']}")
    n = len(vector) + len(outlined)
    ok_gate = sum(r["gate"] for r in vector) + sum(r["code_ok"] for r in outlined)
    key_fields = [
        v
        for r in outlined
        for v in (r["code_ok"], r["stage_ok"], r["sheet_ok"], r["sheets_ok"])
        if v is not None
    ]
    return {
        "suite": "codes",
        "n_stamps": n,
        "em": round(ok_gate / n, 4) if n else None,
        "gate_met": bool(n) and ok_gate / n >= 0.95,
        "vector": {
            "n": len(vector),
            "em_raw": round(sum(r["raw"] for r in vector) / len(vector), 4) if vector else None,
            "em_corrector": round(sum(r["corrector"] for r in vector) / len(vector), 4) if vector else None,
            "em_gate": round(sum(r["gate"] for r in vector) / len(vector), 4) if vector else None,
            "rows": vector,
        },
        "outlined": {
            "n": len(outlined),
            "code_em": round(sum(r["code_ok"] for r in outlined) / len(outlined), 4) if outlined else None,
            "key_fields_em": round(sum(key_fields) / len(key_fields), 4) if key_fields else None,
            "key_fields_n": len(key_fields),
            "rows": outlined,
        },
        "wall_s": round(time.perf_counter() - t0, 1),
    }


def suite_sheets(
    paths, *, gt_path: Path = SHEET_GT, workers: int = 3, providers: str = "cpu", threads: int = 2, log=print
) -> dict[str, Any]:
    from inspector_docproc.inputs import load_manifest, select_files
    from inspector_layout.codes import CodeRegistry
    from inspector_layout.pagescan import ScanOptions
    from inspector_layout.pipeline import FileTask, assemble_object, scan_files

    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    obj = gt["object_id"]
    rows = load_manifest(paths)
    registries = {obj: CodeRegistry.from_manifest_rows(rows, obj)}
    jobs, _ = select_files(paths, (obj,), list(gt["files"]))
    tasks = []
    for j in jobs:
        pages = tuple(sorted(int(p) for p in gt["files"][j.file_id]["sheets"]))
        tasks.append(FileTask(j.file_id, j.object_id, str(j.path), j.sha256, j.stage, pages))
    t0 = time.perf_counter()
    opts = ScanOptions(providers=providers, threads=threads)
    results = scan_files(tasks, registries, opts, workers=workers, chunk_pages=20)
    docs = assemble_object(obj, results, pipeline_version="layout-bench")
    per_file: dict[str, Any] = {}
    n = ok = n_read = ok_read = 0
    dup_expected = dup_ok = 0
    misses: list[str] = []
    for fid, spec in gt["files"].items():
        doc = docs[fid]
        smap = {e["pdf_page_number"]: e for e in doc["sheet_page_map"]}
        tbs = {t["pdf_page_number"]: t for t in doc["title_blocks"]}
        f_n = f_ok = 0
        for p_str, want in spec["sheets"].items():
            p = int(p_str)
            got = smap.get(p, {}).get("sheet_number")
            read = tbs.get(p, {}).get("sheet_number")
            n += 1
            f_n += 1
            n_read += 1
            if str(got) == str(want):
                ok += 1
                f_ok += 1
            else:
                misses.append(f"{fid} p{p}: {got!r} ≠ {want!r}")
            if str(read) == str(want):
                ok_read += 1
        for p_str, first in (spec.get("duplicates") or {}).items():
            dup_expected += 1
            if smap.get(int(p_str), {}).get("duplicate_of_page") == first:
                dup_ok += 1
        per_file[fid] = {"n": f_n, "sheet_eq_stamp": round(f_ok / f_n, 4) if f_n else None}
    res = {
        "suite": "sheets",
        "object_id": obj,
        "n_pages": n,
        "sheet_eq_stamp": round(ok / n, 4) if n else None,
        "gate_met": bool(n) and ok / n >= 0.95,
        "read_eq_stamp": round(ok_read / n_read, 4) if n_read else None,
        "duplicates": {"expected": dup_expected, "flagged": dup_ok},
        "files": per_file,
        "misses": misses,
        "ocr_pages": sum(d["ext"]["title_block"]["ocr_pages"] for d in docs.values()),
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    log(f"лист = штамп: {res['sheet_eq_stamp']} на {n} страницах; дубликаты {dup_ok}/{dup_expected}")
    return res


def main(argv: list[str] | None = None) -> int:
    from inspector_common.settings import get_settings

    ap = argparse.ArgumentParser(prog="python -m inspector_layout.bench")
    ap.add_argument("--suite", choices=("codes", "sheets", "all"), default="all")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--providers", default="cpu")
    args = ap.parse_args(argv)
    paths = get_settings().paths
    out: dict[str, Any] = {}
    if args.suite in ("codes", "all"):
        out["codes"] = suite_codes(paths, providers=args.providers)
    if args.suite in ("sheets", "all"):
        out["sheets"] = suite_sheets(paths, workers=args.workers, providers=args.providers)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    summary = {
        k: {
            kk: v.get(kk)
            for kk in ("em", "gate_met", "sheet_eq_stamp", "n_stamps", "n_pages", "wall_s")
            if kk in v
        }
        for k, v in out.items()
    }
    print(json.dumps(summary, ensure_ascii=False))
    ok = all(v.get("gate_met") for v in out.values())
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
