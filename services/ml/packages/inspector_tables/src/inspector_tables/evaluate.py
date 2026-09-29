"""Row-exact accuracy of parsed tables against a hand ground truth (96 §14 R-08: ≥ 0.98 rows exact).

A row is exact when every GT field equals the parsed field: kind, room number, name (whitespace-collapsed),
area (numeric value of the printed number) and category. Parsed and GT rows are aligned in reading order
(difflib on the row tuples), so a missed or spurious row costs one row, not the rest of the table.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from inspector_tables.text import LAT2CYR_LOWER, LAT2CYR_UPPER, parse_number, squash

RowKey = tuple[str, str | None, str | None, float | None, str | None]


def _look(text: str | None) -> str | None:
    """Latin/Cyrillic look-alikes folded: a visual ground truth cannot tell «x» from «х» or «B» from «В»."""
    if not text:
        return None
    return squash(text).translate(LAT2CYR_UPPER).translate(LAT2CYR_LOWER)


def _key(
    kind: str, room: str | None, name: str | None, area_raw: str | float | None, cat: str | None
) -> RowKey:
    area = (
        area_raw if isinstance(area_raw, float) else parse_number(area_raw) if area_raw is not None else None
    )
    return (kind, _look(room), _look(name), round(area, 2) if area is not None else None, _look(cat))


def gt_rows(path: Path) -> list[RowKey]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [_key(*row) for t in doc["tables"] for row in t["rows"]]


@dataclass(slots=True)
class RowAccuracy:
    gt_rows: int
    parsed_rows: int
    exact: int
    data_gt: int
    data_exact: int
    mismatches: list[tuple[RowKey | None, RowKey | None]]

    @property
    def row_exact(self) -> float:
        return self.exact / self.gt_rows if self.gt_rows else 0.0

    @property
    def data_row_exact(self) -> float:
        return self.data_exact / self.data_gt if self.data_gt else 0.0

    def as_dict(self) -> dict:
        return {
            "gt_rows": self.gt_rows,
            "parsed_rows": self.parsed_rows,
            "exact_rows": self.exact,
            "row_exact": round(self.row_exact, 4),
            "data_gt_rows": self.data_gt,
            "data_exact_rows": self.data_exact,
            "data_row_exact": round(self.data_row_exact, 4),
            "mismatches": [[list(a) if a else None, list(b) if b else None] for a, b in self.mismatches[:40]],
        }


def compare(parsed: list[RowKey], gt: list[RowKey]) -> RowAccuracy:
    sm = difflib.SequenceMatcher(a=gt, b=parsed, autojunk=False)
    exact = 0
    data_exact = 0
    mism: list[tuple[RowKey | None, RowKey | None]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            exact += i2 - i1
            data_exact += sum(1 for r in gt[i1:i2] if r[0] in ("DATA", "SUBZONE"))
        else:
            a = gt[i1:i2]
            b = parsed[j1:j2]
            for k in range(max(len(a), len(b))):
                mism.append((a[k] if k < len(a) else None, b[k] if k < len(b) else None))
    return RowAccuracy(
        len(gt), len(parsed), exact, sum(1 for r in gt if r[0] in ("DATA", "SUBZONE")), data_exact, mism
    )


def explication_keys(rows) -> list[RowKey]:  # rows: list[explication.ExplRow]
    return [
        _key(r.kind, r.room_no, r.name if r.kind != "SUBTOTAL" else None, r.area, r.category) for r in rows
    ]


GT_PAGES: tuple[tuple[str, int, str], ...] = (
    ("F0201", 18, "gt_explication_F0201_p18.json"),
    ("F0202", 17, "gt_explication_F0202_p17.json"),
    ("F0104", 22, "gt_explication_F0104_p22.json"),
)


def main() -> None:  # pragma: no cover - reporting entry point (needs the organizer data)
    """``python -m inspector_tables.evaluate``: explication row accuracy on the hand-GT pages, text layer only
    and with cached PageTokens (when recognition has run on the page)."""
    import time

    import pymupdf

    from inspector_tables import explication
    from inspector_tables.pagesource import PageSource
    from inspector_tables.testing import DATA_DIR, cached_token_dir, train_path

    pymupdf.TOOLS.mupdf_display_errors(False)
    report: dict = {"pages": [], "modes": {}}
    for mode in ("text_layer", "page_tokens"):
        exact = total = data_exact = data_total = 0
        for fid, pg, gt_name in GT_PAGES:
            path = train_path(fid)
            if path is None:
                raise SystemExit("organizer data not found")
            tokens = cached_token_dir(fid, [pg]) if mode == "page_tokens" else None
            t0 = time.perf_counter()
            les = explication.parse_page(PageSource(pymupdf.open(path), fid, tokens).page(pg))
            dt = time.perf_counter() - t0
            acc = compare([k for le in les for k in explication_keys(le.rows)], gt_rows(DATA_DIR / gt_name))
            exact += acc.exact
            total += acc.gt_rows
            data_exact += acc.data_exact
            data_total += acc.data_gt
            report["pages"].append({"mode": mode, "file_id": fid, "page": pg, "tokens": bool(tokens), "seconds": round(dt, 2),
                                    **{k: v for k, v in acc.as_dict().items() if k != "mismatches"},
                                    "mismatches": acc.as_dict()["mismatches"]})  # fmt: skip
        report["modes"][mode] = {"rows_exact": exact, "rows": total, "row_exact": round(exact / total, 4),
                                 "data_rows_exact": data_exact, "data_rows": data_total,
                                 "data_row_exact": round(data_exact / data_total, 4)}  # fmt: skip
    print(json.dumps(report, ensure_ascii=False, indent=1))


def binder_accuracy(
    gt_name: str = "gt_binder_kinds_novoslobodskaya.json",
) -> dict:  # pragma: no cover - needs data
    """ИД page-kind accuracy on the hand-labelled pages: every file of the sample goes through the batch code
    path (text layer / cached tokens), then raw page kinds and segment kinds are scored."""
    from inspector_common.settings import Settings
    from inspector_tables import batch
    from inspector_tables.testing import DATA_DIR, train_path, train_row

    gt = json.loads((DATA_DIR / gt_name).read_text(encoding="utf-8"))
    labelled = [p for p in gt["pages"] if p["kind"]]
    s = Settings()
    raw_kind: dict[tuple[str, int], str] = {}
    seg_kind: dict[tuple[str, int], str] = {}
    for fid in sorted({p["file_id"] for p in labelled}):
        row = train_row(fid)
        path = train_path(fid)
        if row is None or path is None:
            raise SystemExit(f"{fid}: organizer data not found")
        plan = batch.token_plan(Path("/nonexistent"), [], s.cache_root, fid, row["sha256"], True)
        task = batch.FileTask(fid, row["object_id"], str(path), row["sha256"], row["stage"], row["relative_path"], "ID", plan,
                              ("BINDER", "ID_REGISTRY"))  # fmt: skip
        res = batch.process_file(task)
        for v in res["values"]:
            if v["fact_key"] == "id.page_kind":
                raw_kind[(fid, v["page_no"])] = v["value_norm"]["value"]
            elif v["fact_key"] == "id.segment":
                q = v["value_norm"]["qualifiers"]
                for pg in range(q["start_page"], q["end_page"] + 1):
                    seg_kind[(fid, pg)] = v["value_norm"]["value"]
    ok_raw = sum(raw_kind.get((p["file_id"], p["page"])) == p["kind"] for p in labelled)
    ok_seg = sum(seg_kind.get((p["file_id"], p["page"])) == p["kind"] for p in labelled)
    misses = [(p["file_id"], p["page"], p["kind"], raw_kind.get((p["file_id"], p["page"])), seg_kind.get((p["file_id"], p["page"])))
              for p in labelled if seg_kind.get((p["file_id"], p["page"])) != p["kind"]]  # fmt: skip
    return {"pages": len(labelled), "raw_exact": ok_raw, "raw_accuracy": round(ok_raw / len(labelled), 4),
            "segment_exact": ok_seg, "segment_accuracy": round(ok_seg / len(labelled), 4), "misses": misses}  # fmt: skip


if __name__ == "__main__":  # pragma: no cover
    import sys

    if sys.argv[1:] == ["binder"]:
        print(json.dumps(binder_accuracy(), ensure_ascii=False, indent=1))
    else:
        main()
