"""Developer entry point: run the hypothesis engine on one object of a run directory and print a summary.

    cd services/ml
    uv run --locked python -m inspector_hypothesis runs/<run_id> --object OBJ-TYUMENSKAYA-5-GOLD-SEED
    uv run --locked python -m inspector_hypothesis runs/<run_id> --object … --out ../../runs/<run_id>/hyp_debug.json

It reads contract artifacts only and writes nothing unless ``--out`` is given. FREE-* findings reach the submission
through ``compare``/``export`` (AG-04), not through this tool. The hidden test object is refused: nobody reads its
outputs before the frozen submission is sent (CLAUDE.md, rule 4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 5


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m inspector_hypothesis", description="Гипотезы свободного поиска (AG-07)"
    )
    ap.add_argument("run_dir", type=Path, help="каталог запуска runs/<run_id> с артефактами распознавания")
    ap.add_argument("--object", required=True, dest="object_id", help="идентификатор объекта")
    ap.add_argument("--out", type=Path, default=None, help="записать полный результат (JSON) в этот файл")
    ap.add_argument("--no-rules", action="store_true", help="без логических правил")
    ap.add_argument("--no-free", action="store_true", help="без FREE-находок")
    args = ap.parse_args(argv)

    from inspector_registry.api import open_registry

    registry, _ = open_registry()
    if registry.split_of(args.object_id) == "TEST_HIDDEN":
        print(
            "отказано: объект скрытой тестовой выборки — результаты не просматриваются до отправки",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if not args.run_dir.is_dir():
        print(f"нет каталога запуска: {args.run_dir}", file=sys.stderr)
        return EXIT_USAGE

    from inspector_hypothesis import HypothesisConfig, HypothesisInputs, run_hypotheses

    inputs = HypothesisInputs.from_run(args.run_dir, args.object_id, registry=registry)
    result = run_hypotheses(
        inputs, HypothesisConfig(enable_rules=not args.no_rules, enable_free=not args.no_free)
    )
    summary = {
        "object_id": result.object_id,
        "run_id": result.run_id,
        "versions": result.versions,
        "stats": result.stats,
        "free_groups": [
            {
                "parameter_code": g.parameter_code,
                "locations": g.locations,
                "pd_value": g.pd_value,
                "rd_value": g.rd_value,
                "confidence": g.confidence,
                "anchors": [f"{a.stage}:{a.file_id}:p{a.pdf_page_number}" for a in g.anchor_evidence],
            }
            for g in result.free_groups
        ],
        "suspicions": [
            {
                **s.tz_view(),
                "rule_code": s.rule_code,
                "exported": s.exported,
                "bind": str(s.evidence_bind_status),
            }
            for s in result.suspicions
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
