"""Recognition metrics of the real-page benchmark (96 §1.3; ported from the analysis prototypes).

- Character accuracy CA = 1 − (edits + deletions) / N_gt after NFC. ``strict`` removes whitespace only;
  ``relaxed`` also folds dashes, quotes and Latin→Cyrillic look-alikes; ``relaxed_ci`` also folds case.
  OCR lines with score < 0.5 count as not returned.
- Text-layer GT (group A): every GT glyph is assigned to the OCR line polygon containing its centre
  (pad 0.25 line height; nearest by outside distance, then minor-axis offset); per line Levenshtein.
- Line GT (hand transcriptions, groups B/D): per GT line, the minimum semi-global edit distance against
  any overlapping OCR line or the x-ordered concatenation of same-row OCR lines; excluded zones are not
  scored.
- Key-field exact match: the GT token appears with word boundaries in an OCR line over the field box.
- 95 % CI: bootstrap over pages/regions weighted by N_gt.
Coordinates: displayed-page points (origin top-left), i.e. normalized × page size.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from rapidfuzz.distance import Levenshtein

from inspector_docproc.textnorm import HOMO, norm_relaxed, norm_relaxed_ci, norm_strict

MODES: dict[str, Callable[[str], str]] = {
    "strict": norm_strict,
    "relaxed": norm_relaxed,
    "relaxed_ci": norm_relaxed_ci,
}


def bbox_of(poly: np.ndarray) -> tuple[float, float, float, float]:
    return float(poly[:, 0].min()), float(poly[:, 1].min()), float(poly[:, 0].max()), float(poly[:, 1].max())


def _point_in_poly(x: float, y: float, poly: np.ndarray, pad: float) -> bool:
    import cv2

    return cv2.pointPolygonTest(poly.astype(np.float32), (float(x), float(y)), True) >= -pad


def _in_rect(x: float, y: float, r: Sequence[float]) -> bool:
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def _intersects(a: Sequence[float], b: Sequence[float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def align_text_layer(
    gt: list[dict[str, Any]], lines: list[dict[str, Any]], region: Sequence[float] | None = None
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Assign GT glyphs to OCR lines; return (gt string, ocr string) per line and unassigned glyphs."""
    if region is not None:
        gt = [g for g in gt if _in_rect(g["x"], g["y"], region)]
        lines = [ln for ln in lines if _intersects(bbox_of(ln["poly"]), region)]
    assign: dict[int, list[int]] = {}
    boxes = [bbox_of(ln["poly"]) for ln in lines]
    for gi, g in enumerate(gt):
        best, bd = None, 1e18
        for li, ln in enumerate(lines):
            bx = boxes[li]
            h = min(bx[2] - bx[0], bx[3] - bx[1])
            pad = 0.25 * h
            if not (bx[0] - pad <= g["x"] <= bx[2] + pad and bx[1] - pad <= g["y"] <= bx[3] + pad):
                continue
            if not _point_in_poly(g["x"], g["y"], ln["poly"], pad):
                continue
            cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
            out = max(bx[0] - g["x"], 0, g["x"] - bx[2]) + max(bx[1] - g["y"], 0, g["y"] - bx[3])
            d = out * 1000 + (abs(g["y"] - cy) if (bx[2] - bx[0]) >= (bx[3] - bx[1]) else abs(g["x"] - cx))
            if d < bd:
                best, bd = li, d
        if best is not None:
            assign.setdefault(best, []).append(gi)
    pairs: list[tuple[str, str]] = []
    for li, ln in enumerate(lines):
        gis = assign.get(li, [])
        if not gis:
            pairs.append(("", ln["text"]))
            continue
        bx = boxes[li]
        horiz = (bx[2] - bx[0]) >= (bx[3] - bx[1])
        spans: dict[int, list[int]] = {}
        for gi in gis:
            spans.setdefault(gt[gi]["sid"], []).append(gi)

        def skey(item: tuple[int, list[int]], horiz: bool = horiz) -> tuple[float, float]:
            _, gl = item
            ys = float(np.mean([gt[i]["y"] for i in gl]))
            xs = float(np.mean([gt[i]["x"] for i in gl]))
            return (round(ys / 3), xs) if horiz else (round(-xs / 3), -ys)

        s = "".join("".join(gt[i]["c"] for i in sorted(gl)) for _, gl in sorted(spans.items(), key=skey))
        pairs.append((s, ln["text"]))
    assigned = {i for v in assign.values() for i in v}
    unassigned = [gt[i] for i in range(len(gt)) if i not in assigned]
    return pairs, unassigned


def score_text_layer(
    gt: list[dict[str, Any]], lines: list[dict[str, Any]], region: Sequence[float] | None, tau: float = 0.5
) -> dict[str, dict[str, int]]:
    ls = [dict(ln, poly=np.asarray(ln["poly"], float)) for ln in lines if ln["score"] >= tau]
    pairs, unassigned = align_text_layer(gt, ls, region)
    res: dict[str, dict[str, int]] = {}
    for mode, nf in MODES.items():
        ed = ins = n = 0
        for g, o in pairs:
            g2, o2 = nf(g), nf(o)
            if not g2:
                ins += len(o2)
                continue
            ed += Levenshtein.distance(g2, o2)
            n += len(g2)
        dele = sum(len(nf(u["c"])) for u in unassigned)
        res[mode] = {"N": n + dele, "ed": ed, "dele": dele, "ins": ins}
    return res


def semi_global(a: str, b: str) -> int:
    """Minimum edit distance between ``a`` and any substring of ``b``."""
    if not b:
        return len(a)
    if not a:
        return 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ai != b[j - 1]))
        prev = cur
    return min(prev)


def _in_zone(x: float, y: float, zones: list[dict[str, Any]]) -> bool:
    return any(_in_rect(x, y, z["bbox"]) for z in zones)


def score_line_gt(
    gt: dict[str, Any], lines: list[dict[str, Any]], tau: float = 0.5, pad: float = 0.4
) -> tuple[dict[str, dict[str, int]], list[tuple[str, list[str], int]]]:
    """Hand line GT: per-line semi-global distance (see module docstring). Returns (res, strict misses)."""
    zones = gt.get("excluded_zones", [])
    glines = [
        g
        for g in gt["lines"]
        if not _in_zone((g["bbox"][0] + g["bbox"][2]) / 2, (g["bbox"][1] + g["bbox"][3]) / 2, zones)
    ]
    ocr = []
    for ln in lines:
        b = bbox_of(np.asarray(ln["poly"], float))
        if _in_zone((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, zones):
            continue
        ocr.append((b, ln["text"], ln["score"]))
    res: dict[str, dict[str, int]] = {}
    worst: list[tuple[str, list[str], int]] = []
    for mode, nf in MODES.items():
        n = ed = dele = 0
        for gl in glines:
            gb = gl["bbox"]
            h = min(gb[3] - gb[1], gb[2] - gb[0])
            e = pad * h
            gt_text = nf(gl["text"])
            n += len(gt_text)
            cand = [
                o
                for o in ocr
                if o[2] >= tau
                and o[0][0] < gb[2] + e
                and o[0][2] > gb[0] - e
                and o[0][1] < gb[3] + e
                and o[0][3] > gb[1] - e
            ]
            if not cand:
                dele += len(gt_text)
                ed += len(gt_text)
                continue
            vert = (gb[3] - gb[1]) > (gb[2] - gb[0]) * 1.2 and len(gl["text"]) > 2

            def same_row(o: tuple, gb: Sequence[float] = gb, vert: bool = vert) -> bool:
                ob = o[0]
                if vert:
                    return min(ob[2], gb[2]) - max(ob[0], gb[0]) >= 0.5 * min(ob[2] - ob[0], gb[2] - gb[0])
                return min(ob[3], gb[3]) - max(ob[1], gb[1]) >= 0.5 * min(ob[3] - ob[1], gb[3] - gb[1])

            row = sorted(
                [o for o in cand if same_row(o)],
                key=(lambda o: (o[0][0], -o[0][1])) if not vert else (lambda o: (-o[0][3], o[0][0])),
            )
            opts = [nf(o[1]) for o in cand] + ([nf("".join(o[1] for o in row))] if row else [])
            d = min(semi_global(gt_text, t) for t in opts)
            ed += d
            if mode == "strict" and d > 0:
                worst.append((gl["text"], [o[1] for o in cand], d))
        res[mode] = {"N": n, "ed": ed - dele, "dele": dele, "ins": 0}
    return res, worst


# ── Line GT v2 (ocr_gt_v2.json: two transcriptions + adjudication) ─────────────────────────────

_DIAMETER = re.compile("[Ø⌀∅]")  # Ø ⌀ ∅ → ø (U+00F8): the GT convention, visually one glyph
_TIMES = re.compile(r"(?<=\d)[xх×](?=\d)")  # multiplication sign between digits: Latin x = Cyrillic х = ×


def fold_undecidable(s: str) -> str:
    """Fold the glyph pairs the v2 GT declares visually undecidable (``stats.conventions``): the diameter
    family and the multiplication sign between digits. Applied to GT and OCR text in every mode, after
    whitespace removal, so «ø16x2,2» and «ø16х2,2» are the same string; everything else stays strict."""
    return _TIMES.sub("х", _DIAMETER.sub("ø", s))


MODES_V2: dict[str, Callable[[str], str]] = {
    mode: (lambda s, nf=nf: fold_undecidable(nf(s))) for mode, nf in MODES.items()
}


def _boxes(items: list[Sequence[float]]) -> np.ndarray:
    return np.asarray(items, float).reshape(-1, 4)


def score_line_gt_v2(
    gt: dict[str, Any], lines: list[dict[str, Any]], tau: float = 0.5, pad: float = 0.4
) -> tuple[dict[str, dict[str, int]], list[tuple[str, list[str], int]], dict[str, Any]]:
    """Hand line GT v2 (``docs/analysis/gt_staging/ocr_gt_v2.json`` ``stats.conventions.scoring_rule``).

    Differences from :func:`score_line_gt` (v1):
    - every GT line is scored except ``exclude_from_scoring``; lines are **not** dropped because their centre
      lies in an excluded zone (legible printed lines under seals and signatures are scored);
    - OCR lines are never dropped as candidates; the excluded zones (seal, signature, handwriting, QR) only
      mask OCR **insertions**: accepted OCR text that overlaps no GT line and is not centred in a zone;
    - :func:`fold_undecidable` is applied in every mode (``MODES_V2``).
    Per GT line: the minimum semi-global edit distance against any overlapping OCR line (± ``pad`` × the
    line's smaller side) or the reading-order concatenation of the same-row ones (as v1).
    Returns (counts per mode, strict misses, extras: insertions per mode, per-kind and uncertain counts).
    """
    zones = [z["bbox"] for z in gt.get("excluded_zones", [])]
    all_g = gt["lines"]
    glines = [g for g in all_g if not g.get("exclude_from_scoring")]
    ocr = [
        (bbox_of(np.asarray(ln["poly"], float)), ln["text"], float(ln["score"]))
        for ln in lines
        if float(ln["score"]) >= tau
    ]
    ob = _boxes([o[0] for o in ocr])
    gb_all = _boxes([g["bbox"] for g in all_g])
    # candidates per scored GT line (vectorised once, reused by every mode)
    cands: list[list[int]] = []
    for g in glines:
        gb = g["bbox"]
        e = pad * min(gb[3] - gb[1], gb[2] - gb[0])
        if len(ob):
            hit = (
                (ob[:, 0] < gb[2] + e)
                & (ob[:, 2] > gb[0] - e)
                & (ob[:, 1] < gb[3] + e)
                & (ob[:, 3] > gb[1] - e)
            )
            cands.append(np.nonzero(hit)[0].tolist())
        else:
            cands.append([])
    # insertions: OCR lines overlapping no GT line (scored or not) and not centred in an excluded zone
    inserted: list[int] = []
    if len(ob):
        e_all = (
            pad * np.minimum(gb_all[:, 3] - gb_all[:, 1], gb_all[:, 2] - gb_all[:, 0])
            if len(gb_all)
            else None
        )
        for i, b in enumerate(ob):
            if e_all is not None and bool(
                (
                    (gb_all[:, 0] - e_all < b[2])
                    & (gb_all[:, 2] + e_all > b[0])
                    & (gb_all[:, 1] - e_all < b[3])
                    & (gb_all[:, 3] + e_all > b[1])
                ).any()
            ):
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if any(_in_rect(cx, cy, z) for z in zones):
                continue
            inserted.append(i)
    res: dict[str, dict[str, int]] = {}
    worst: list[tuple[str, list[str], int]] = []
    for mode, nf in MODES_V2.items():
        n = ed = dele = 0
        for gl, cand in zip(glines, cands, strict=True):
            gt_text = nf(gl["text"])
            n += len(gt_text)
            if not cand:
                dele += len(gt_text)
                continue
            gb = gl["bbox"]
            vert = (gb[3] - gb[1]) > (gb[2] - gb[0]) * 1.2 and len(gl["text"]) > 2

            def same_row(i: int, gb: Sequence[float] = gb, vert: bool = vert) -> bool:
                b = ob[i]
                if vert:
                    return min(b[2], gb[2]) - max(b[0], gb[0]) >= 0.5 * min(b[2] - b[0], gb[2] - gb[0])
                return min(b[3], gb[3]) - max(b[1], gb[1]) >= 0.5 * min(b[3] - b[1], gb[3] - gb[1])

            row = sorted(
                (i for i in cand if same_row(i)),
                key=(lambda i: (ob[i][0], -ob[i][1])) if not vert else (lambda i: (-ob[i][3], ob[i][0])),
            )
            opts = [nf(ocr[i][1]) for i in cand] + ([nf("".join(ocr[i][1] for i in row))] if row else [])
            d = min(semi_global(gt_text, t) for t in opts)
            ed += d
            if mode == "strict" and d > 0:
                worst.append((gl["text"], [ocr[i][1] for i in cand], d))
        ins = sum(len(nf(ocr[i][1])) for i in inserted)
        res[mode] = {"N": n, "ed": ed, "dele": dele, "ins": ins}
    kinds: dict[str, int] = {}
    for g in glines:
        k = g.get("kind") or "text"
        kinds[k] = kinds.get(k, 0) + len(MODES_V2["strict"](g["text"]))
    extras = {
        "n_lines": len(glines),
        "n_not_scored": len(all_g) - len(glines),
        "n_uncertain": sum(1 for g in glines if g.get("uncertain")),
        "chars_by_kind": kinds,
        "inserted_lines": len(inserted),
        "inserted_sample": [ocr[i][1] for i in inserted[:8]],
    }
    return res, worst, extras


def ca(counts: dict[str, int]) -> float:
    return 1.0 - (counts["ed"] + counts["dele"]) / max(counts["N"], 1)


# ── Zones (R-10): predicted PageTokens zones against the GT v2 excluded zones ────────────────────

GT_ZONE_FAMILY = {
    "SEAL_ROUND": "SEAL",
    "QR_CODE": "QR",
    "HANDWRITING_SIGNATURE": "HANDWRITING",
    "HANDWRITING": "HANDWRITING",
}
ZONE_FAMILIES = ("SEAL", "QR", "HANDWRITING")


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _share_covered(box: Sequence[float], cover: list[Sequence[float]], grid: int = 24) -> float:
    """Share of ``box`` under the union of ``cover`` boxes (grid sampling, exact enough for reporting)."""
    if not cover:
        return 0.0
    xs = np.linspace(box[0], box[2], grid)
    ys = np.linspace(box[1], box[3], grid)
    gx, gy = np.meshgrid(xs, ys)
    inside = np.zeros_like(gx, dtype=bool)
    for c in cover:
        inside |= (gx >= c[0]) & (gx <= c[2]) & (gy >= c[1]) & (gy <= c[3])
    return float(inside.mean())


def score_zones(
    pred: list[dict[str, Any]], gt_zones: list[dict[str, Any]], iou_hit: float = 0.3
) -> dict[str, dict[str, Any]]:
    """Per zone family: GT zones hit (IoU ≥ ``iou_hit`` with a predicted zone of the family, the R-10
    acceptance) or covered (≥ 50 % of the GT box under same-family predictions), and false alarms
    (predictions of the family overlapping no GT zone of any family). Boxes are normalized page space."""
    out: dict[str, dict[str, Any]] = {}
    gts = [(GT_ZONE_FAMILY.get(z["type"], "OTHER"), z["bbox_norm"]) for z in gt_zones]
    for fam in ZONE_FAMILIES:
        p = [z["bbox"] for z in pred if z.get("kind") == fam]
        g = [b for f, b in gts if f == fam]
        hits = sum(1 for b in g if p and max(box_iou(b, q) for q in p) >= iou_hit)
        covered = sum(1 for b in g if _share_covered(b, p) >= 0.5)
        fp = sum(1 for q in p if all(box_iou(q, b) < 0.05 and _share_covered(b, [q]) < 0.3 for _, b in gts))
        out[fam] = {"n_gt": len(g), "hit": hits, "covered": covered, "n_pred": len(p), "false_alarm": fp}
    return out


def bootstrap_ci(
    values: Sequence[float], weights: Sequence[float] | None = None, n: int = 2000, seed: int = 1
) -> tuple[float, float, float]:
    """Weighted mean with a percentile bootstrap 95 % CI over units (pages or regions)."""
    vals = np.asarray(values, float)
    w = np.ones_like(vals) if weights is None else np.asarray(weights, float)
    if len(vals) == 0:
        return (float("nan"),) * 3
    est = float((vals * w).sum() / w.sum())
    rng = np.random.default_rng(seed)
    k = len(vals)
    bs = []
    for _ in range(n):
        idx = rng.integers(0, k, k)
        bs.append((vals[idx] * w[idx]).sum() / w[idx].sum())
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def pooled(units: list[dict[str, dict[str, int]]], mode: str) -> dict[str, float]:
    """Pooled CA over units (Σ errors / Σ N) plus the bootstrap CI of per-unit CA weighted by N."""
    cas = [ca(u[mode]) for u in units]
    ns = [u[mode]["N"] for u in units]
    est, lo, hi = bootstrap_ci(cas, ns)
    tot = sum(ns)
    err = sum(u[mode]["ed"] + u[mode]["dele"] for u in units)
    return {
        "ca": round(1 - err / max(tot, 1), 4),
        "ci_low": round(lo, 4),
        "ci_high": round(hi, 4),
        "weighted_mean": round(est, 4),
        "n_units": len(units),
        "n_chars": tot,
        "ins_rate": round(sum(u[mode]["ins"] for u in units) / max(tot, 1), 4),
    }


# ── Key fields ───────────────────────────────────────────────────────────────────────────────


def _ws(x: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", x)).strip()


def token_em(
    token: str,
    box: Sequence[float],
    lines: list[dict[str, Any]],
    relaxed: bool,
    *,
    numeric_unit_ok: bool = True,
    pad_frac: float = 0.5,
    tau: float = 0.5,
) -> bool:
    """GT token found with word boundaries in an OCR line overlapping ``box`` (± pad_frac × box height)."""
    h = box[3] - box[1]
    e = pad_frac * h
    nf = (lambda x: _ws(x).translate(HOMO)) if relaxed else _ws
    g = nf(token)
    if not g:
        return False
    numeric = token[-1].isdigit()
    for ln in lines:
        if ln["score"] < tau:
            continue
        q = np.asarray(ln["poly"], float)
        if (
            q[:, 0].max() < box[0] - e
            or q[:, 0].min() > box[2] + e
            or q[:, 1].max() < box[1] - e
            or q[:, 1].min() > box[3] + e
        ):
            continue
        o = nf(ln["text"])
        for m in re.finditer(re.escape(g), o):
            a, z = m.start(), m.end()
            left_ok = a == 0 or not o[a - 1].isalnum()
            if numeric and numeric_unit_ok:
                right_ok = z == len(o) or not o[z].isdigit()
            else:
                right_ok = z == len(o) or not o[z].isalnum()
            if left_ok and right_ok:
                return True
    return False


def find_token_box(gt: dict[str, Any], token: str) -> list[float] | None:
    exact = [ln for ln in gt["lines"] if ln["text"].strip() == token]
    if exact:
        return list(exact[0]["bbox"])
    for ln in gt["lines"]:
        if re.search(r"(?<![\w])" + re.escape(token) + r"(?![\d])", ln["text"]):
            return list(ln["bbox"])
    return None


CODE_RE = re.compile(r"^[0-9A-ZА-ЯЁ][0-9A-Za-zА-Яа-яЁё./_\-]{5,}$")
ROOM_RE = re.compile(r"^(\d{3,4}|\d{1,2}\.\d{2,3}|0\d{2})$")


def is_code_field(t: str) -> bool:
    return (
        bool(CODE_RE.match(t))
        and t.count("-") + t.count("/") >= 2
        and bool(re.search(r"[А-ЯA-Z]{2,}", t))
        and bool(re.search(r"\d", t))
    )


def field_em(
    kind: str, token: str, box: Sequence[float], lines: list[dict[str, Any]], relaxed: bool, tau: float = 0.5
) -> bool:
    """EM of a text-layer field (codes, room numbers) against OCR lines (keyfields prototype)."""
    pad = 0.6 * min(box[2] - box[0], box[3] - box[1])
    zone = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
    nf = (lambda x: _ws(x).translate(HOMO)) if relaxed else _ws
    g = nf(token)
    for ln in lines:
        if ln["score"] < tau or not _intersects(bbox_of(np.asarray(ln["poly"], float)), zone):
            continue
        o = nf(ln["text"])
        for m in re.finditer(re.escape(g), o):
            a, b = m.start(), m.end()
            if (a == 0 or not o[a - 1].isalnum()) and (b == len(o) or not o[b].isalnum()):
                return True
            if kind != "CODE" and (a == 0 or not o[a - 1].isdigit()) and (b == len(o) or not o[b].isdigit()):
                return True
    return False
