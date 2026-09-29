"""`inspector-eval`: the ТЗ §14.3 acceptance harness (06 §3.10), skeleton for M1.

    inspector-eval ocr       --run-dir RUN [--gt docs/analysis/gt_staging/ocr_gt_v2.json]   # CA, CER, coverage
    inspector-eval detection --pred DIR|FILE [--devset T-GOLD|N-GOLD]                        # P, R, F1, FPR
    inspector-eval verdict   --run-dir RUN [--devset …]                                      # §14.3 thresholds

It measures what a run actually produced (PageTokens, the exported answer), independently of the code under
test: nothing here imports the recognition or comparison packages. Every threshold of ТЗ §14.3 appears in the
verdict; a metric we cannot compute yet (no gold of that kind) is NOT_EVALUATED, never silently passed.

- **OCR (CA ≥ 0.95).** Ground truth: the adjudicated line transcriptions of ``ocr_gt_v2.json`` (14 pages, two
  independent transcriptions + visual adjudication). Per GT line (``exclude_from_scoring`` skipped), the minimum
  semi-global edit distance against any run text line overlapping it (± 0.4 × its smaller side) or the
  reading-order concatenation of the same-row lines; strict = NFC without whitespace, plus the GT's declared
  undecidable glyph pairs (Ø/⌀/∅, ×/x/х between digits). ``CA = 1 − Σ(edits)/Σ(GT chars)``, a GT line with no
  overlapping text counts as fully deleted. Pages absent from the run are listed and lower ``coverage``.
- **Detection (P ≥ 0.90, R ≥ 0.80, F1 ≥ 0.85) and FPR (≤ 0.10).** On a dev set (T-GOLD, N-GOLD): a TP needs the
  right parameter code, the right location and at least one correct evidence page (ТЗ: «совпадение требует …
  корректного доказательства», the scorer's k4 key). FPR = FP / (FP + TN) over the set's negative labels
  (NO_VIOLATION): a predicted VIOLATION_PRESENT on a negative key is FP. Wilson 95 % intervals and ``n`` are
  reported with every proportion. T-GOLD has positives only, so its FPR is NOT_EVALUATED.
- Key fields, linkage and bbox IoU need gold we do not have yet: NOT_EVALUATED with the reason.

Exit codes: 0 all evaluated thresholds pass, 2 a threshold fails or is NOT_EVALUATED (06 §3.10), 1 error,
5 hidden test refused, 6 data missing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inspector_common.errors import InspectorError
from inspector_common.exitcodes import ExitCode
from inspector_common.paths import repo_root
from inspector_common.runlayout import RunLayout

HARNESS_VERSION = "0.1.0"
DEFAULT_OCR_GT = Path("docs/analysis/gt_staging/ocr_gt_v2.json")
THRESHOLDS: tuple[tuple[str, str, float, str], ...] = (
    ("ocr_character_accuracy", ">=", 0.95, "OCR: Character Accuracy"),
    ("key_fields_exact_match", ">=", 0.90, "Ключевые поля: Exact Match"),
    ("document_linkage", ">=", 0.95, "Связка документов"),
    ("evidence_localization", ">=", 0.95, "Локализация доказательства (IoU ≥ 0,5)"),
    ("detection_precision", ">=", 0.90, "Выявление нарушений: Precision"),
    ("detection_recall", ">=", 0.80, "Выявление нарушений: Recall"),
    ("detection_f1", ">=", 0.85, "Выявление нарушений: F1"),
    ("false_positive_rate", "<=", 0.10, "Ложные срабатывания: FPR"),
)
_DIAMETER = re.compile("[Ø⌀∅]")
_TIMES = re.compile(r"(?<=\d)[xх×](?=\d)")


def strict_text(text: str) -> str:
    """NFC, no whitespace, the GT's undecidable glyph pairs folded (ocr_gt_v2 conventions)."""
    s = re.sub(r"\s+", "", unicodedata.normalize("NFC", str(text)))
    return _TIMES.sub("х", _DIAMETER.sub("ø", s))


def semi_global(a: str, b: str) -> int:
    """Minimum edit distance between ``a`` and any substring of ``b`` (free leading/trailing text in ``b``)."""
    if not a:
        return 0
    if not b:
        return len(a)
    prev = [0] * (len(b) + 1)
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return min(prev)


def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


# ── OCR ──────────────────────────────────────────────────────────────────────────────────────


def _hyp_lines(page: Mapping[str, Any]) -> list[tuple[list[float], str]]:
    """Run text lines in displayed-page points: PageTokens ``lines`` (or tokens), conf ≥ 0.5."""
    size = page.get("page") or {}
    w, h = float(size.get("width_pt") or 0), float(size.get("height_pt") or 0)
    items = page.get("lines") or page.get("tokens") or []
    out = []
    for item in items:
        bbox, text = item.get("bbox"), item.get("text")
        if not bbox or not text or float(item.get("conf", 1.0)) < 0.5:
            continue
        out.append(([bbox[0] * w, bbox[1] * h, bbox[2] * w, bbox[3] * h], str(text)))
    return out


def score_page(gt_page: Mapping[str, Any], page: Mapping[str, Any], pad: float = 0.4) -> dict[str, Any]:
    hyp = _hyp_lines(page)
    n = edits = deleted = 0
    worst: list[dict[str, Any]] = []
    for line in gt_page.get("lines", []):
        if line.get("exclude_from_scoring"):
            continue
        ref = strict_text(line["text"])
        n += len(ref)
        gb = line["bbox"]
        e = pad * min(gb[3] - gb[1], gb[2] - gb[0])
        cand = [
            (b, t)
            for b, t in hyp
            if b[0] < gb[2] + e and b[2] > gb[0] - e and b[1] < gb[3] + e and b[3] > gb[1] - e
        ]
        if not cand:
            deleted += len(ref)
            continue
        vertical = (gb[3] - gb[1]) > (gb[2] - gb[0]) * 1.2 and len(line["text"]) > 2
        if vertical:
            row = [
                c
                for c in cand
                if min(c[0][2], gb[2]) - max(c[0][0], gb[0]) >= 0.5 * min(c[0][2] - c[0][0], gb[2] - gb[0])
            ]
            row.sort(key=lambda c: (-c[0][3], c[0][0]))
        else:
            row = [
                c
                for c in cand
                if min(c[0][3], gb[3]) - max(c[0][1], gb[1]) >= 0.5 * min(c[0][3] - c[0][1], gb[3] - gb[1])
            ]
            row.sort(key=lambda c: (c[0][0], -c[0][1]))
        options = [strict_text(t) for _, t in cand] + (
            [strict_text("".join(t for _, t in row))] if row else []
        )
        d = min(semi_global(ref, o) for o in options)
        edits += d
        if d and len(worst) < 5:
            worst.append({"gt": line["text"], "hyp": [t for _, t in cand][:4], "edits": d})
    ca = 1.0 - (edits + deleted) / max(n, 1)
    return {"chars": n, "edits": edits, "deleted": deleted, "ca": ca, "worst": worst}


def _tokens(run_dir: Path, file_id: str, page: int) -> Mapping[str, Any] | None:
    path = RunLayout(run_dir).path("PAGE_TOKENS", file_id=file_id, page=page)
    if not path.is_file():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def evaluate_ocr(
    run_dir: Path, gt: Mapping[str, Any], hidden_files: frozenset[str] = frozenset()
) -> dict[str, Any]:
    pages, missing = [], []
    for page_id, gt_page in gt.get("pages", {}).items():
        file_id, page_no = str(gt_page["file_id"]), int(gt_page["pdf_page_number"])
        if file_id in hidden_files:
            continue
        tokens = _tokens(run_dir, file_id, page_no)
        if tokens is None:
            missing.append(f"{page_id} {file_id} с.{page_no}")
            continue
        pages.append(
            {"page": page_id, "file_id": file_id, "pdf_page_number": page_no, **score_page(gt_page, tokens)}
        )
    chars = sum(p["chars"] for p in pages)
    errors = sum(p["edits"] + p["deleted"] for p in pages)
    total_pages = len(pages) + len(missing)
    return {
        "gt_version": gt.get("version"),
        "pages_scored": len(pages),
        "pages_missing": missing,
        "coverage": len(pages) / total_pages if total_pages else None,
        "chars": chars,
        "ca": (1.0 - errors / chars) if chars else None,
        "cer": (errors / chars) if chars else None,
        "per_page": pages,
    }


# ── detection and FPR on a dev set ───────────────────────────────────────────────────────────


def evaluate_detection(
    pred_path: Path, devset_id: str, *, registry: Path | None = None, paths: Any = None
) -> dict[str, Any]:
    from inspector_common.settings import Settings
    from inspector_eval import devset
    from inspector_eval.config import DEFAULT_CONFIG
    from inspector_eval.data import load_context, load_predictions
    from inspector_eval.guard import check_access
    from inspector_eval.scoring import POSITIVE, key_of, score_object

    paths = paths or Settings().paths
    ctx = load_context(paths)
    ds = devset.get_devset(devset_id, registry or devset.REGISTRY_PATH, ctx.split_policy)
    rows = devset.load_devset(ds, paths, ctx)
    check_access([ds.object_id], ctx.split_policy)
    predictions = {p.object_id: p for p in load_predictions(pred_path)}
    pred = predictions.get(ds.object_id)
    cfg = DEFAULT_CONFIG.replace(key="k4")
    result = score_object(
        rows.gold_rows, pred.document if pred else None, ctx, cfg, object_id=ds.object_id, extras=False
    )
    det = result.detection
    negatives = {key_of(g, cfg) for g in rows.gold_rows if g.get("violation_label") == "NO_VIOLATION"}
    predicted_pos = set()
    if pred is not None and isinstance(pred.document, Mapping):
        predicted_pos = {
            key_of(c, cfg)
            for c in pred.document.get("checks", [])
            if isinstance(c, Mapping) and c.get("violation_label") == POSITIVE
        }
    fp_neg = len(negatives & predicted_pos)
    tn = len(negatives) - fp_neg
    return {
        "devset": ds.id,
        "object_id": ds.object_id,
        "prediction_found": pred is not None,
        "key_rule": "k4: code + location + ≥ 1 correct evidence page",
        "tp": det.tp,
        "fp": det.fp,
        "fn": det.fn,
        "precision": det.precision if det.tp + det.fp else None,
        "recall": det.recall if det.tp + det.fn else None,
        "f1": det.f1 if det.tp + det.fp + det.fn else None,
        "precision_ci": wilson(det.tp, det.tp + det.fp),
        "recall_ci": wilson(det.tp, det.tp + det.fn),
        "negatives": len(negatives),
        "fpr": (fp_neg / len(negatives)) if negatives else None,
        "fpr_ci": wilson(fp_neg, len(negatives)),
        "fp_on_negatives": fp_neg,
        "tn": tn,
        "positives_only_set": ds.positives_only,
    }


# ── verdict ──────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Threshold:
    metric: str
    op: str
    threshold: float
    title_ru: str
    value: float | None
    n: int | None
    status: str
    note_ru: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "title_ru": self.title_ru,
            "op": self.op,
            "threshold": self.threshold,
            "value": self.value,
            "n": self.n,
            "status": self.status,
            "note_ru": self.note_ru,
        }


def verdict(ocr: Mapping[str, Any] | None, detection: Mapping[str, Any] | None) -> dict[str, Any]:
    values: dict[str, tuple[float | None, int | None, str | None]] = {
        "key_fields_exact_match": (None, None, "нет эталона ключевых полей (шифр, стадия, редакция, лист)"),
        "document_linkage": (None, None, "нет эталона связки (объект, стадия, шифр, актуальная редакция)"),
        "evidence_localization": (None, None, "эталон только постраничный: IoU не вычисляется"),
    }
    if ocr is not None:
        values["ocr_character_accuracy"] = (
            ocr.get("ca"),
            ocr.get("chars"),
            None if ocr.get("ca") is not None else "нет страниц эталона в прогоне",
        )
    if detection is not None:
        n_pos = detection["tp"] + detection["fn"]
        values["detection_precision"] = (detection["precision"], detection["tp"] + detection["fp"], None)
        values["detection_recall"] = (detection["recall"], n_pos, None)
        values["detection_f1"] = (detection["f1"], n_pos, None)
        values["false_positive_rate"] = (
            detection["fpr"],
            detection["negatives"],
            "в наборе нет отрицательных меток" if detection["fpr"] is None else None,
        )
    rows = []
    for metric, op, threshold, title in THRESHOLDS:
        value, n, note = values.get(metric, (None, None, "метрика не запрашивалась"))
        if value is None:
            status = "NOT_EVALUATED"
        else:
            ok = value >= threshold if op == ">=" else value <= threshold
            status = "PASS" if ok else "FAIL"
        rows.append(Threshold(metric, op, threshold, title, value, n, status, note))
    return {
        "harness_version": HARNESS_VERSION,
        "accepted": all(r.status == "PASS" for r in rows),
        "failed": [r.metric for r in rows if r.status == "FAIL"],
        "not_evaluated": [r.metric for r in rows if r.status == "NOT_EVALUATED"],
        "thresholds": [r.as_dict() for r in rows],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────


def _load_gt(path: Path | None) -> dict[str, Any]:
    gt_path = path or repo_root() / DEFAULT_OCR_GT
    try:
        return json.loads(gt_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InspectorError("GOLD_NOT_FOUND", object_id=str(gt_path)) from None


def _hidden_files() -> frozenset[str]:
    """File ids of TEST_HIDDEN objects (manifest metadata only): never scored by this harness."""
    from inspector_common.settings import Settings
    from inspector_eval.data import load_context

    ctx = load_context(Settings().paths, require_weights=False)
    return frozenset(
        fid for fid, row in ctx.manifest.items() if row.get("object_id") in ctx.split_policy.hidden
    )


def _print_verdict(v: Mapping[str, Any]) -> None:
    mark = {"PASS": "✓", "FAIL": "✗", "NOT_EVALUATED": "—"}
    print(f"Приёмка по ТЗ §14.3: {'ПРИНЯТО' if v['accepted'] else 'НЕ ПРИНЯТО'}")
    for t in v["thresholds"]:
        value = "—" if t["value"] is None else f"{t['value']:.4f}"
        print(
            f"  {mark[t['status']]} {t['title_ru']}: {value} (порог {t['op']} {t['threshold']}, n={t['n']})"
            + (f" — {t['note_ru']}" if t["note_ru"] else "")
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inspector-eval", description="Приёмочные метрики ТЗ §14.3 (каркас М1)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_ocr = sub.add_parser("ocr", help="Точность OCR прогона на эталоне строк (ocr_gt_v2)")
    p_ocr.add_argument("--run-dir", type=Path, required=True)
    p_ocr.add_argument("--gt", type=Path, default=None)
    p_ocr.add_argument("--json", action="store_true")
    p_det = sub.add_parser("detection", help="P/R/F1 и FPR ответа на наборе T-GOLD или N-GOLD")
    p_det.add_argument("--pred", type=Path, required=True)
    p_det.add_argument("--devset", default="T-GOLD")
    p_det.add_argument("--json", action="store_true")
    p_ver = sub.add_parser("verdict", help="Сводка порогов ТЗ §14.3 по прогону")
    p_ver.add_argument("--run-dir", type=Path, required=True)
    p_ver.add_argument("--gt", type=Path, default=None)
    p_ver.add_argument("--devset", default="T-GOLD")
    p_ver.add_argument("--out", type=Path, default=None, help="Каталог для metrics.json")
    p_ver.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from inspector_eval.data import InputError
    from inspector_eval.guard import HiddenAccessRefusedError

    try:
        if args.command == "ocr":
            result = evaluate_ocr(args.run_dir, _load_gt(args.gt), _hidden_files())
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                ca = "—" if result["ca"] is None else f"{result['ca']:.4f}"
                print(
                    f"OCR (эталон v{result['gt_version']}): CA {ca} на {result['chars']} символах, "
                    f"страниц {result['pages_scored']}, покрытие {result['coverage']}"
                )
                for p in result["per_page"]:
                    print(
                        f"  {p['page']} {p['file_id']} с.{p['pdf_page_number']}: CA {p['ca']:.4f} ({p['chars']} симв.)"
                    )
                if result["pages_missing"]:
                    print("  нет в прогоне: " + ", ".join(result["pages_missing"]))
            return int(ExitCode.OK if result["ca"] is not None and result["ca"] >= 0.95 else 2)
        if args.command == "detection":
            det = evaluate_detection(args.pred, args.devset)
            v = verdict(None, det)
            print(json.dumps(det, ensure_ascii=False, indent=2) if args.json else "")
            if not args.json:
                _print_verdict(v)
            return int(ExitCode.OK if not v["failed"] else 2)
        run_dir = args.run_dir
        ocr = evaluate_ocr(run_dir, _load_gt(args.gt), _hidden_files())
        det = evaluate_detection(run_dir, args.devset)
        v = verdict(ocr, det)
        metrics = {
            "verdict": v,
            "ocr": {k: val for k, val in ocr.items() if k != "per_page"},
            "detection": det,
        }
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "metrics.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        if args.json:
            print(json.dumps(metrics, ensure_ascii=False, indent=2))
        else:
            _print_verdict(v)
        return int(ExitCode.OK if v["accepted"] else 2)
    except HiddenAccessRefusedError as exc:
        err = exc.error()
        print(f"{err.title}: {exc.reason_ru}.", file=sys.stderr)
        return int(ExitCode.HIDDEN_TEST_REFUSED)
    except InspectorError as exc:
        print(f"{exc.title}: {exc.detail}", file=sys.stderr)
        return int(
            ExitCode.DATA_MISSING
            if exc.code in ("GOLD_NOT_FOUND", "PREDICTION_NOT_FOUND")
            else ExitCode.ERROR
        )
    except InputError as exc:
        print(exc.message_ru, file=sys.stderr)
        return int(ExitCode.DATA_MISSING)


if __name__ == "__main__":
    raise SystemExit(main())
