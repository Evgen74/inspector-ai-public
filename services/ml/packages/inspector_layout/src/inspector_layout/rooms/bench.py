"""Acceptance measures of the room index on the train gold (96 R-15; room tokens EM ≥ 0.95).

Three measures, all computed from LayoutArtifacts documents:

1. **Gold rooms located** — every ROOM location of ``public_train_checks.jsonl`` must be found with its exact
   token on the cited evidence page, or (group-anchor rule, 93 §2.8) on another page of the same file:
   room 314 is cited on F0201 p18 but drawn on p20.
2. **Room-token EM on the benchmark room set** — the set is (a) the hand-registered room-label anchors of
   ``95_tyumen_dev_fixtures.json`` (``page_facts``: 21 labelled positions on the six gold pages and RD p20),
   matched by exact token within 0.012 of the anchor point, and (b) every room row of the explication tables
   printed on the same plans, matched by an exact plan label on the page (the table and the plan are
   independent printings of the same room numbers). A near miss («12» for «012») counts as a miss. Only fully
   read pages (PageTokens) enter the set; pages read from the text layer alone are reported as coverage
   (their outlined numbers were never recognised).
3. **Plan-label precision against the explications** — plan labels whose token is not in the page's
   explication (extra circles, levels read as rooms).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from inspector_layout.rooms.grammar import parse_tags
from inspector_layout.rooms.inventory import LABEL_SOURCES, page_inventories, tag_elements, tag_subkind

ANCHOR_TOL = 0.012


def gold_rooms(train_checks_path: Path, object_id: str | None = None) -> list[dict[str, Any]]:
    out = []
    for line in train_checks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("location_type") != "ROOM" or (object_id and row.get("object_id") != object_id):
            continue
        out.append(
            {
                "check_id": row["check_id"],
                "group": row.get("finding_group_id"),
                "parameter_code": row.get("parameter_code"),
                "room": row["location"],
                "evidence": [
                    (e["stage"], e["file_id"], int(e["pdf_page_number"])) for e in row.get("evidence", [])
                ],
            }
        )
    return out


def _labels(layout: dict[str, Any], page: int | None = None) -> list[dict[str, Any]]:
    return [
        r for r in layout.get("rooms") or []
        if r.get("source") in LABEL_SOURCES and (page is None or r["pdf_page_number"] == page)
    ]  # fmt: skip


def evaluate_gold(layouts: dict[str, dict[str, Any]], gold: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for g in gold:
        for stage, fid, page in g["evidence"]:
            lay = layouts.get(fid)
            if lay is None:
                rows.append({**_row(g, stage, fid, page), "status": "FILE_NOT_PROCESSED"})
                continue
            on_page = [r for r in _labels(lay, page) if r["room_token"] == g["room"]]
            elsewhere = sorted(
                {r["pdf_page_number"] for r in _labels(lay) if r["room_token"] == g["room"]} - {page}
            )
            status = "ON_CITED_PAGE" if on_page else ("ON_OTHER_PAGE" if elsewhere else "NOT_FOUND")
            rows.append(
                {
                    **_row(g, stage, fid, page),
                    "status": status,
                    "found_pages": sorted({page} if on_page else set()) + elsewhere,
                    "source": on_page[0]["source"] if on_page else None,
                    "has_zone": bool(on_page and on_page[0].get("zone")),
                    "name": on_page[0].get("name") if on_page else None,
                }
            )
    located = sum(1 for r in rows if r["status"] in ("ON_CITED_PAGE", "ON_OTHER_PAGE"))
    return {
        "n": len(rows),
        "located": located,
        "on_cited_page": sum(1 for r in rows if r["status"] == "ON_CITED_PAGE"),
        "rooms": sorted({g["room"] for g in gold}),
        "rows": rows,
    }


def _row(g: dict[str, Any], stage: str, fid: str, page: int) -> dict[str, Any]:
    return {"check_id": g["check_id"], "group": g["group"], "room": g["room"], "stage": stage, "file_id": fid,
            "cited_page": page}  # fmt: skip


_ANCHOR_KEY = re.compile(r"^(?:room_label_|room_|label_)(?P<rooms>[\d._]+)$")


def fixture_anchors(fixtures_path: Path) -> list[dict[str, Any]]:
    """Room-label anchors of 95_tyumen_dev_fixtures.json: (file, page, token, point)."""
    data = json.loads(fixtures_path.read_text(encoding="utf-8"))
    out = []
    for key, facts in (data.get("page_facts") or {}).items():
        fid, page = key.split(":")
        for name, value in (facts.get("anchors") or {}).items():
            m = _ANCHOR_KEY.match(name)
            if not m or not isinstance(value, list) or len(value) != 2:
                continue
            for token in m.group("rooms").split("_"):
                out.append(
                    {
                        "file_id": fid,
                        "pdf_page_number": int(page),
                        "room": token,
                        "point": value,
                        "anchor": name,
                    }
                )
    return out


def token_em(layouts: dict[str, dict[str, Any]], anchors: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact-match rate of room tokens on the benchmark room set (anchors + explication rows)."""
    items = []
    for a in anchors:
        lay = layouts.get(a["file_id"])
        if lay is None:
            continue
        best = None
        for r in _labels(lay, a["pdf_page_number"]):
            b = r.get("bbox")
            if not b:
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            d = math.hypot(cx - a["point"][0], cy - a["point"][1])
            if best is None or d < best[0]:
                best = (d, r["room_token"])
        ok = best is not None and best[0] <= ANCHOR_TOL and best[1] == a["room"]
        # a label listing several rooms («267, 270») carries each token at the same point
        if not ok and best is not None and best[0] <= ANCHOR_TOL:
            ok = any(
                r["room_token"] == a["room"] and r.get("bbox") and
                math.hypot((r["bbox"][0] + r["bbox"][2]) / 2 - a["point"][0], (r["bbox"][1] + r["bbox"][3]) / 2 - a["point"][1]) <= ANCHOR_TOL
                for r in _labels(lay, a["pdf_page_number"])
            )  # fmt: skip
        items.append({"set": "fixture_anchor", "file_id": a["file_id"], "page": a["pdf_page_number"], "room": a["room"],
                      "read": best[1] if best else None, "distance": round(best[0], 4) if best else None, "em": ok})  # fmt: skip
    expl = explication_crosscheck(layouts)
    coverage = {"pages": 0, "rows": 0, "located": 0}
    for p in expl["pages"]:
        if p["tokens"] != "PAGE_TOKENS":
            # text layer only (OCR_PARTIAL): outlined numbers were never read — coverage, not token exactness
            coverage["pages"] += 1
            coverage["rows"] += len(p["explication_rooms"])
            coverage["located"] += len(set(p["explication_rooms"]) & set(p["plan_rooms"]))
            continue
        for room in p["explication_rooms"]:
            items.append({"set": "explication_row", "file_id": p["file_id"], "page": p["page"], "room": room,
                          "em": room in p["plan_rooms"]})  # fmt: skip
    n = len(items)
    hits = sum(1 for i in items if i["em"])
    by_set: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for i in items:
        by_set[i["set"]][0] += 1
        by_set[i["set"]][1] += int(i["em"])
    return {
        "n": n,
        "em": round(hits / n, 4) if n else None,
        "by_set": {k: {"n": v[0], "em": round(v[1] / v[0], 4) if v[0] else None} for k, v in by_set.items()},
        "misses": [i for i in items if not i["em"]],
        "precision": expl["precision"],
        "text_layer_only": coverage,
    }


def explication_crosscheck(layouts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pages = []
    tp = fp = 0
    for fid, lay in sorted(layouts.items()):
        origin = {
            x["page"]: x.get("tokens")
            for x in ((lay.get("ext") or {}).get("rooms_stage") or {}).get("pages", [])
        }
        by_page: dict[int, dict[str, set[str]]] = defaultdict(lambda: {"expl": set(), "plan": set()})
        for r in lay.get("rooms") or []:
            key = (
                "expl"
                if r["source"] == "EXPLICATION_TABLE"
                else "plan"
                if r["source"] in LABEL_SOURCES
                else None
            )
            if key:
                by_page[r["pdf_page_number"]][key].add(r["room_token"])
        for page, d in sorted(by_page.items()):
            if len(d["expl"]) < 3 or not d["plan"]:
                continue
            pages.append({"file_id": fid, "page": page, "tokens": origin.get(page, "PAGE_TOKENS"),
                          "explication_rooms": sorted(d["expl"]),
                          "plan_rooms": sorted(d["plan"]), "plan_not_in_explication": sorted(d["plan"] - d["expl"]),
                          "explication_not_on_plan": sorted(d["expl"] - d["plan"])})  # fmt: skip
            tp += len(d["plan"] & d["expl"])
            fp += len(d["plan"] - d["expl"])
    return {"pages": pages, "precision": round(tp / (tp + fp), 4) if tp + fp else None, "plan_in_explication": tp,
            "plan_not_in_explication": fp}  # fmt: skip


# ── tags: per-room expectations of the dev fixtures, adjudicated OCR GT, counterparts ────────────────────────

TAG_BENCH_SUBKINDS = ("branch", "system", "natural", "terminal", "local_exhaust", "riser", "radiator", "pipeline",
                      "warm_floor")  # fmt: skip
VENT_ELEMENT_SUBKINDS = ("branch", "system", "natural")


def _elements(
    text: str, *, vent: bool = True, heating: bool = True, subkinds=VENT_ELEMENT_SUBKINDS
) -> list[str]:
    """Elements the grammar reads in a fixture string («П17.1, 17.2» → П17.1, П17.2; «В2.1 (OCR: B2.1)» → В2.1)."""
    text = re.sub(r"\((?:OCR|ocr)[^)]*\)", " ", text)
    return [m.tag_norm for m in parse_tags(text, vent=vent, heating=heating) if m.subkind in subkinds]


def fixture_tag_checks(fixtures_path: Path) -> list[dict[str, Any]]:
    """Room-level tag expectations registered by hand in ``95_tyumen_dev_fixtures.json`` (page_facts + RT-04).

    - ``ROOM_BRANCHES_EXACT``: the local-exhaust branches of a PD schematic room (F0171 p88 ``pd_local_exhaust_tags``);
    - ``ROOM_UNITS``: the supply units of room 012 on PD p104 (``supply_units_in_012_text_layer``, RT-09) are all
      in 012, and the unit drawn outside it (``unit_outside_012``) is not;
    - ``ROOM_ELEMENTS_RECALL``: vent marks read by hand on the RD plans (``rd_tags_ocr``: F0201 p18, p20);
    - ``ZONE_RECALL``: marks in a registered zone of a page, any room (F0201 p17 ``zone_012_bbox``, RT-02: an OCR
      crop, so a mark whose box intersects the zone counts);
    - ``CLOUD``: the revision cloud of F0202 p17 (``revision_cloud_bbox``) over rooms 270, 272 (RT-04).
    """
    data = json.loads(fixtures_path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for key, facts in (data.get("page_facts") or {}).items():
        fid, page_s = key.split(":")
        page = int(page_s)
        anchors = facts.get("anchors") or {}
        for room, tags in (anchors.get("pd_local_exhaust_tags") or {}).items():
            out.append({"check": "ROOM_BRANCHES_EXACT", "file_id": fid, "page": page, "room": room,
                        "expected": sorted({e for t in tags for e in _elements(t)})})  # fmt: skip
        units = anchors.get("supply_units_in_012_text_layer")
        if units:
            out.append({"check": "ROOM_UNITS", "file_id": fid, "page": page, "room": "012",
                        "expected": sorted({e for t in units for e in _elements(t)}),
                        "absent": sorted({e for t in anchors.get("unit_outside_012") or {} for e in _elements(t)})})  # fmt: skip
        for room, tags in (anchors.get("rd_tags_ocr") or {}).items():
            expected = sorted({e for t in tags for e in _elements(t)})
            local = any(re.search(r"М\.?\s?О\.", t) for t in tags)
            out.append({"check": "ROOM_ELEMENTS_RECALL", "file_id": fid, "page": page, "room": room,
                        "expected": expected, "local_exhaust": local})  # fmt: skip
        zone = anchors.get("zone_012_bbox")
        tokens = anchors.get("ocr_tokens_text_layers_only_300dpi")
        if zone and tokens:
            out.append({"check": "ZONE_RECALL", "file_id": fid, "page": page, "bbox": zone,
                        "expected": sorted({e for t in tokens for e in _elements(t)})})  # fmt: skip
        cloud = anchors.get("revision_cloud_bbox")
        if cloud:
            rooms = []
            for rt in data.get("recognition_tests") or []:
                if (
                    rt.get("file") == fid
                    and rt.get("page") == page
                    and "cloud" in str(rt.get("assert", "")).lower()
                ):
                    m = re.search(r"room labels ([\d, ]+)", str(rt["assert"]))
                    rooms = [r.strip() for r in m.group(1).split(",") if r.strip()] if m else []
            out.append({"check": "CLOUD", "file_id": fid, "page": page, "bbox": cloud,
                        "layer": anchors.get("revision_cloud_layer"), "rooms": rooms})  # fmt: skip
    return out


def _box_iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def evaluate_tag_checks(layouts: dict[str, dict[str, Any]], checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Pass/fail and element recall of every fixture tag check (see :func:`fixture_tag_checks`)."""
    rows = []
    exp_total = found_total = 0
    for c in checks:
        lay = layouts.get(c["file_id"])
        if lay is None:
            continue
        row: dict[str, Any] = {k: v for k, v in c.items()}
        if c["check"] in ("ROOM_BRANCHES_EXACT", "ROOM_UNITS", "ROOM_ELEMENTS_RECALL"):
            inv = page_inventories(lay, c["page"]).get(c["room"])
            got = set(inv.tags_of(*VENT_ELEMENT_SUBKINDS)) if inv else set()
            if c["check"] == "ROOM_BRANCHES_EXACT":
                got = set(inv.branches) if inv else set()
            exp = set(c["expected"])
            row["got"] = sorted(got, key=_natural_key)
            row["missing"] = sorted(exp - got, key=_natural_key)
            if c["check"] == "ROOM_ELEMENTS_RECALL":
                ok = not row["missing"] and (not c.get("local_exhaust") or bool(inv and inv.local_exhausts))
                row["local_exhausts"] = inv.local_exhausts if inv else 0
            else:
                ok = got == exp
                row["extra"] = sorted(got - exp, key=_natural_key)
                if c["check"] == "ROOM_UNITS":
                    ok = exp <= got and not (set(c.get("absent") or ()) & got)
            exp_total += len(exp)
            found_total += len(exp & got)
            row["pass"] = ok
        elif c["check"] == "ZONE_RECALL":
            x0, y0, x1, y1 = c["bbox"]
            got = set()
            for t in lay.get("tags") or []:
                b = t.get("bbox")
                if t["pdf_page_number"] != c["page"] or not b:
                    continue
                if b[0] < x1 and x0 < b[2] and b[1] < y1 and y0 < b[3]:  # a mark cut by the crop is read too
                    got.update(e for e in tag_elements(t) if tag_subkind(t, e) in VENT_ELEMENT_SUBKINDS)
            exp = set(c["expected"])
            row["missing"] = sorted(exp - got, key=_natural_key)
            exp_total += len(exp)
            found_total += len(exp & got)
            row["pass"] = not row["missing"]
        elif c["check"] == "CLOUD":
            best = None
            for cl in lay.get("revision_clouds") or []:
                if cl["pdf_page_number"] != c["page"]:
                    continue
                iou = _box_iou(cl["bbox"], c["bbox"])
                if best is None or iou > best[0]:
                    best = (iou, cl)
            row["iou"] = round(best[0], 3) if best else 0.0
            row["rooms_covered"] = best[1]["rooms_covered"] if best else []
            row["layer_found"] = best[1].get("layer") if best else None
            row["pass"] = bool(best and best[0] >= 0.5 and set(c["rooms"]) <= set(best[1]["rooms_covered"]))
        rows.append(row)
    return {
        "n": len(rows),
        "passed": sum(1 for r in rows if r.get("pass")),
        "element_recall": round(found_total / exp_total, 4) if exp_total else None,
        "elements": exp_total,
        "rows": rows,
    }


def _natural_key(tag: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", tag)]


def gt_tag_benchmark(ocr_gt_path: Path, layouts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Tag spotting against the adjudicated OCR ground truth of drawing pages (``ocr_gt_v2.json``).

    Expected = the same grammar applied to the GT text lines (so the measure is OCR + line assembly + page
    context, not the grammar itself); found = the TagInstances of the page (one per printed mark, room copies
    counted once). Multiset precision/recall over the elements of the subkinds :data:`TAG_BENCH_SUBKINDS`.
    """
    data = json.loads(ocr_gt_path.read_text(encoding="utf-8"))
    pages = []
    tp_all = exp_all = got_all = 0
    for key, p in sorted((data.get("pages") or {}).items()):
        lay = layouts.get(p["file_id"])
        page = int(p["pdf_page_number"])
        processed = {
            x["page"] for x in ((lay or {}).get("ext") or {}).get("rooms_stage", {}).get("pages", [])
        }
        if lay is None or page not in processed:
            continue
        expected: Counter = Counter()
        for ln in p.get("lines") or []:
            if ln.get("exclude_from_scoring"):
                continue
            for m in parse_tags(str(ln.get("text", ""))):
                if m.subkind in TAG_BENCH_SUBKINDS:
                    expected[m.tag_norm] += 1
        seen: set[tuple] = set()
        got: Counter = Counter()
        for t in lay.get("tags") or []:
            if t["pdf_page_number"] != page:
                continue
            k = (t["tag"], t.get("tag_norm"), tuple(t.get("bbox") or ()))
            if k in seen:
                continue
            seen.add(k)
            for e in tag_elements(t):
                if tag_subkind(t, e) in TAG_BENCH_SUBKINDS:
                    got[e] += 1
        if not expected:
            continue
        tp = sum((expected & got).values())
        n_exp, n_got = sum(expected.values()), sum(got.values())
        tp_all, exp_all, got_all = tp_all + tp, exp_all + n_exp, got_all + n_got
        pages.append({"gt_page": key, "file_id": p["file_id"], "page": page, "expected": n_exp, "found": n_got,
                      "tp": tp, "recall": round(tp / n_exp, 4) if n_exp else None,
                      "precision": round(tp / n_got, 4) if n_got else None,
                      "missed": sorted((expected - got).elements())[:40],
                      "spurious": sorted((got - expected).elements())[:40]})  # fmt: skip
    return {
        "pages": pages,
        "recall": round(tp_all / exp_all, 4) if exp_all else None,
        "precision": round(tp_all / got_all, 4) if got_all else None,
        "expected": exp_all,
        "found": got_all,
    }


def evaluate_counterparts(
    index: Any, gold: list[dict[str, Any]], a_stage: str = "PD", b_stage: str = "RD"
) -> dict[str, Any]:
    """Top-1 counterpart page of every gold room (from its PD evidence page) against the gold RD page.

    ``HIT``: top-1 is the cited RD page. ``HIT_DRAWN``: the cited page does not label the room (group-anchor rule,
    93 §2.8: 314 is cited on F0201 p18, drawn on p20) and top-1 is a page of the same file that does.
    """
    rows = []
    for g in gold:
        a = [(fid, page) for st, fid, page in g["evidence"] if st == a_stage]
        b = [(fid, page) for st, fid, page in g["evidence"] if st == b_stage]
        if not a or not b:
            continue
        ranked = index.counterparts(g["room"], a[0][0], a[0][1], b_stage)
        top = (ranked[0].file_id, ranked[0].pdf_page_number) if ranked else None
        labelled_on_cited = (b[0][0], b[0][1]) in set(index.pages_of(g["room"], b_stage))
        if top == b[0]:
            status = "HIT"
        elif top and not labelled_on_cited and top[0] == b[0][0]:
            status = "HIT_DRAWN"
        else:
            status = "MISS"
        rows.append({"check_id": g["check_id"], "room": g["room"], "from": list(a[0]), "gold": list(b[0]),
                     "top": list(top) if top else None, "status": status,
                     "ranked": [c.as_dict() for c in ranked[:4]]})  # fmt: skip
    return {
        "n": len(rows),
        "hit": sum(1 for r in rows if r["status"] == "HIT"),
        "hit_drawn": sum(1 for r in rows if r["status"] == "HIT_DRAWN"),
        "rows": rows,
    }
