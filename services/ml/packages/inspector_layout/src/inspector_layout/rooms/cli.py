"""Developer CLI of the room/CAD stage: LayoutArtifacts for chosen files + the acceptance report.

    python -m inspector_layout.rooms.cli --object OBJ-TYUMENSKAYA-5-GOLD-SEED \\
        --files F0171 F0201 F0202 --pages F0171:88,99,104 --pages F0201:14-40 --pages F0202:14-36 \\
        --tokens-run m1-ag02b2-tokens --run-id m1-ag02b2-layout --workers 3 --report /tmp/rooms_report.json

Writes ``runs/<run_id>/layout/<file_id>.json`` (contract ``layout_artifacts``, validated before writing) and,
with ``--report``, a JSON report: gold rooms located, room-token EM on the benchmark room set, per-room PD vs
RD inventories of the gold rooms, PD↔RD sheet matches, revision clouds and timings. The batch command
``inspector-batch layout`` calls :func:`inspector_layout.rooms.fileproc.process_file` for the same work.
Refuses the hidden test object (97 §2.17: no content processing outside the frozen run).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validate
from inspector_common.paths import repo_root
from inspector_common.runlayout import RunLayout
from inspector_common.settings import get_settings
from inspector_layout.rooms.bench import (
    evaluate_counterparts,
    evaluate_gold,
    evaluate_tag_checks,
    explication_crosscheck,
    fixture_anchors,
    fixture_tag_checks,
    gold_rooms,
    gt_tag_benchmark,
    token_em,
)
from inspector_layout.rooms.fileproc import (
    FileInput,
    build_layout_artifacts,
    default_vocab_cache,
    object_text_vocabulary,
    process_file,
    vocabulary_from_tokens,
)
from inspector_layout.rooms.index import RoomIndex
from inspector_layout.rooms.inventory import room_inventories

FIXTURES = Path("docs/analysis/95_tyumen_dev_fixtures.json")
OCR_GT = Path("docs/analysis/gt_staging/ocr_gt_v2.json")


def _parse_pages(spec: str) -> list[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return sorted(out)


def _stage(manifest_stage: str, relative_path: str) -> str | None:
    if manifest_stage in ("PD", "RD", "ID"):
        return manifest_stage
    name = relative_path.lower()
    if "исполнительн" in Path(name).name:
        return "ID"
    if "-рд-" in name or "рабоч" in name:
        return "RD"
    return None


def _hidden_objects(paths) -> set[str]:
    """TEST_HIDDEN object ids from the organizers' split_policy.json (never hard-coded)."""
    policy = json.loads(paths.split_policy_path.read_text(encoding="utf-8"))
    return set(policy.get("TEST_HIDDEN") or [])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m inspector_layout.rooms.cli", description=__doc__.split("\n\n")[0]
    )
    ap.add_argument("--object", required=True)
    ap.add_argument("--files", nargs="+", default=None, help="по умолчанию все PDF объекта")
    ap.add_argument("--pages", action="append", default=[], metavar="FILE:SPEC", help="например F0201:14-40")
    ap.add_argument("--tokens-run", default=None)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    settings = get_settings()
    paths = settings.paths
    if args.object in _hidden_objects(paths):
        print(
            "Объект скрытой тестовой выборки: обработка вне замороженного прогона запрещена.", file=sys.stderr
        )
        return 5
    from inspector_docproc.inputs import select_files

    jobs, problems = select_files(paths, [args.object], args.files or None)
    for p in problems:
        print(f"Предупреждение: {p}", file=sys.stderr)
    runs_root = paths.runs_root
    run_dir = runs_root / args.run_id
    tokens_root = runs_root / (args.tokens_run or args.run_id) / "tokens"
    page_spec = {}
    for spec in args.pages:
        fid, _, rng = spec.partition(":")
        page_spec[fid] = tuple(_parse_pages(rng))
    vocab = vocabulary_from_tokens(tokens_root / j.file_id for j in jobs)
    vocab.add(object_text_vocabulary(args.object, None, default_vocab_cache()).tags)
    layout = RunLayout(run_dir)
    layouts: dict[str, dict[str, Any]] = {}
    stages: dict[str, str | None] = {}
    t0 = time.perf_counter()
    for job in sorted(jobs, key=lambda j: j.file_id):
        tdir = tokens_root / job.file_id
        fi = FileInput(job.file_id, job.path, tdir if tdir.is_dir() else None, page_spec.get(job.file_id))
        fragment, results = process_file(fi, vocab, workers=args.workers)
        stage = _stage(job.stage, job.relative_path)
        stages[job.file_id] = stage
        doc = build_layout_artifacts(
            file_id=job.file_id,
            object_id=job.object_id,
            file_sha256=job.sha256,
            stage=stage,
            pages_total=int(job.pdf_pages or 0),
            fragment=fragment,
        )
        validate("layout_artifacts", doc)
        out = layout.path("LAYOUT", file_id=job.file_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        layouts[job.file_id] = doc
        n_rooms = sum(1 for r in doc["rooms"] if r["source"] != "EXPLICATION_TABLE")
        print(
            f"{job.file_id}: страниц {len(results)}, помещений {n_rooms}, строк экспликации "
            f"{len(doc['rooms']) - n_rooms}, меток {len(doc['tags'])}, облаков {len(doc['revision_clouds'])}, "
            f"слоёв {len(doc['cad_layers'])}; {doc['timings_ms'].get('wall', 0) / 1000:.1f} с → {out}"
        )
    wall = time.perf_counter() - t0
    if args.report:
        report = build_report(layouts, stages, paths, vocab_size=len(vocab), wall_s=wall)
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        g, em, tc, cp = report["gold"], report["token_em"], report["tag_checks"], report["counterparts"]
        print(f"Золотые помещения: найдено {g['located']}/{g['n']} (на цитируемой странице {g['on_cited_page']}); "
              f"EM номеров помещений {em['em']} на {em['n']} эталонах; проверки меток {tc['passed']}/{tc['n']} "
              f"(полнота элементов {tc['element_recall']}); парные листы {cp['hit'] + cp['hit_drawn']}/{cp['n']}; "
              f"отчёт: {args.report}")  # fmt: skip
        gt = report.get("gt_tags") or {}
        if gt.get("pages"):
            print(f"Метки на страницах эталона OCR: полнота {gt['recall']}, точность {gt['precision']} "
                  f"({gt['expected']} эталонных элементов)")  # fmt: skip
    return 0


def build_report(layouts: dict[str, dict[str, Any]], stages: dict[str, str | None], paths, *, vocab_size: int,
                 wall_s: float) -> dict[str, Any]:  # fmt: skip
    object_id = next(iter(layouts.values()))["object_id"] if layouts else None
    gold = gold_rooms(paths.train_checks_path, object_id) if paths.train_checks_path.is_file() else []
    fixtures = repo_root() / FIXTURES
    anchors = fixture_anchors(fixtures) if fixtures.is_file() else []
    index = RoomIndex.from_layouts(layouts.values(), stages)
    inv_rows = []
    for room in sorted({g["room"] for g in gold}):
        for stage in ("PD", "RD"):
            cited = sorted(
                {
                    (fid, page)
                    for g in gold
                    if g["room"] == room
                    for st, fid, page in g["evidence"]
                    if st == stage
                }
            )
            for inv in room_inventories([layouts[f] for f in {c[0] for c in cited} if f in layouts], room):
                row = inv.summary()
                row["stage"] = stage
                row["cited"] = (inv.file_id, inv.pdf_page_number) in cited
                inv_rows.append(row)
    matches = index.match_sheets("PD", "RD")
    ocr_gt = repo_root() / OCR_GT
    gold_pages = {(fid, page) for g in gold for _, fid, page in g["evidence"]}
    clouds = [
        {"file_id": fid, **{k: c[k] for k in ("pdf_page_number", "bbox", "layer", "source", "rooms_covered", "confidence")}}
        for fid, lay in layouts.items() for c in lay["revision_clouds"] if c["confidence"] >= 0.5
    ]  # fmt: skip
    timings: dict[str, float] = defaultdict(float)
    pages = 0
    for lay in layouts.values():
        for k, v in lay["timings_ms"].items():
            timings[k] += v
        pages += len(lay["ext"]["rooms_stage"]["pages"])
    return {
        "object_id": object_id,
        "files": {
            fid: {
                "stage": stages.get(fid),
                "pages": len(lay["ext"]["rooms_stage"]["pages"]),
                "rooms": sum(1 for r in lay["rooms"] if r["source"] != "EXPLICATION_TABLE"),
                "explication_rows": sum(1 for r in lay["rooms"] if r["source"] == "EXPLICATION_TABLE"),
                "tags": len(lay["tags"]),
                "clouds": len(lay["revision_clouds"]),
                "cad_layers": len(lay["cad_layers"]),
                "warnings": lay["warnings"],
            }
            for fid, lay in layouts.items()
        },
        "vocabulary_size": vocab_size,
        "gold": evaluate_gold(layouts, gold),
        "token_em": token_em(layouts, anchors),
        "tag_checks": evaluate_tag_checks(
            layouts, fixture_tag_checks(fixtures) if fixtures.is_file() else []
        ),
        "gt_tags": gt_tag_benchmark(ocr_gt, layouts) if ocr_gt.is_file() else None,
        "counterparts": evaluate_counterparts(index, gold),
        "explication": {k: v for k, v in explication_crosscheck(layouts).items() if k != "pages"},
        "gold_room_inventories": inv_rows,
        "gold_room_pages": {room: index.pages_of(room) for room in sorted({g["room"] for g in gold})},
        "sheet_matches_gold_pages": [
            m.as_dict() | {"shared_gold_rooms": sorted(set(m.shared) & {g["room"] for g in gold})}
            for m in matches
            if (m.a_file, m.a_page) in gold_pages or (m.b_file, m.b_page) in gold_pages
        ],
        "sheet_matches_total": len(matches),
        "revision_clouds": clouds,
        "pages_processed": pages,
        "wall_s": round(wall_s, 2),
        "timings_ms_total": {k: round(v, 1) for k, v in sorted(timings.items())},
    }


if __name__ == "__main__":
    sys.exit(main())
