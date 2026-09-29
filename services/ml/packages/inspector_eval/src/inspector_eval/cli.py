"""`inspector-score`: local replica of the organizers' scoring (60/15/15/10 + gate), 93 §4.1.

    inspector-score run      --pred FILE|DIR [--gold CHECKS.jsonl] [variant switches] [--out DIR] [--json]
    inspector-score validate --pred FILE|DIR            # schemas + integrity rules only
    inspector-score selftest                            # T-GOLD fixture: 93 §2.3 cases
    inspector-score devset   list | show ID | freeze ID # dev-set registry (T-GOLD, N-GOLD)
    inspector-score sweep    --pred-dir DIR             # leave-object-out calibration

Exit codes (inspector_common.exitcodes): 0 OK, 1 error, 2 usage, 3 gate triggered, 4 schema/integrity
invalid, 5 hidden-test refused, 6 data missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from inspector_common.errors import InspectorError
from inspector_common.exitcodes import ExitCode
from inspector_common.hashing import sha256_file
from inspector_common.paths import DataPaths
from inspector_common.settings import Settings
from inspector_eval import calibration, devset
from inspector_eval.args import add_variant_arguments, config_from_args
from inspector_eval.config import CHOICES, DEFAULT_CONFIG, ScoreConfig
from inspector_eval.data import (
    InputError,
    ScoringContext,
    gold_for_object,
    load_context,
    load_predictions,
    peek_object_ids,
    read_json,
    read_jsonl,
    validate_gold,
)
from inspector_eval.fixtures import T_GOLD_OBJECT, run_cases
from inspector_eval.guard import HiddenAccessRefusedError, check_access, objects_in
from inspector_eval.report import build_report, render_text, render_validation, utc_now, write_outputs
from inspector_eval.scoring import ObjectScore, pool, score_object
from inspector_eval.validation import check_integrity, validate_schemas

# ── shared argument helpers ──────────────────────────────────────────────────────────────────


def add_data_arguments(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("данные организаторов (по умолчанию из INSPECTOR_DATA_ROOT)")
    g.add_argument("--data-root", type=Path, default=None)
    g.add_argument("--manifest", type=Path, default=None)
    g.add_argument("--catalog", type=Path, default=None)
    g.add_argument("--split-policy", type=Path, default=None)
    g.add_argument("--weights", type=Path, default=None, help="scoring_summary_without_answers.json")
    g.add_argument(
        "--superseded", type=Path, default=None, help="JSON со списком устаревших file_id (правило R9)"
    )


def add_hidden_arguments(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("скрытая выборка (только после заморозки)")
    g.add_argument(
        "--hidden-final",
        action="store_true",
        help="Явное разрешение: только для замороженного финального прогона",
    )
    g.add_argument(
        "--run-manifest",
        type=Path,
        default=None,
        help="run_manifest.json или sidecar замороженного прогона (freeze_tag)",
    )


def _paths(args: argparse.Namespace) -> DataPaths:
    return Settings(**({"data_root": args.data_root} if getattr(args, "data_root", None) else {})).paths


def _context(args: argparse.Namespace, paths: DataPaths) -> ScoringContext:
    return load_context(
        paths,
        manifest_path=args.manifest,
        catalog_path=args.catalog,
        split_policy_path=args.split_policy,
        weights_path=args.weights,
        superseded_path=args.superseded,
    )


def _emit(text: str, *, stream: Any = None) -> None:
    print(text, file=stream or sys.stdout)


# ── scoring flow shared with inspector-batch ─────────────────────────────────────────────────


def score_predictions(
    *,
    pred_path: Path,
    gold_path: Path,
    ctx: ScoringContext,
    cfg: ScoreConfig,
    objects: Sequence[str] = (),
    hidden_final: bool = False,
    run_manifest: Path | None = None,
) -> tuple[list[ObjectScore], list[str], dict[str, Any]]:
    """Guard first (object ids only), then load, validate and score. Returns (scores, skipped, report extras)."""
    raw_gold = read_jsonl(gold_path) if str(gold_path).endswith(".jsonl") else read_json(gold_path)
    if not isinstance(raw_gold, list):
        raise InputError(f"Эталон {gold_path} должен быть списком строк")
    pred_ids = peek_object_ids(pred_path)
    frozen = check_access(
        [*objects, *objects_in(raw_gold), *pred_ids],
        ctx.split_policy,
        hidden_final=hidden_final,
        run_manifest=run_manifest,
    )
    problems = validate_gold(raw_gold)
    if problems:
        raise InputError(
            f"Эталон {gold_path} не соответствует контракту gold_check: " + "; ".join(problems[:5])
        )
    predictions = {p.object_id: p for p in load_predictions(pred_path) if isinstance(p.object_id, str)}
    if objects:
        wanted = list(dict.fromkeys(objects))
    elif pred_path.is_file():
        wanted = [o for o in pred_ids if isinstance(o, str)]
    else:
        wanted = sorted(objects_in(raw_gold) | set(predictions))
    scores: list[ObjectScore] = []
    skipped: list[str] = []
    for object_id in wanted:
        gold = gold_for_object(raw_gold, object_id)
        if not gold:
            skipped.append(object_id)
            continue
        split = (
            ctx.split_policy.split_of(object_id)
            if object_id in ctx.split_policy.hidden
            else cfg.expected_split
        )
        pred = predictions.get(object_id)
        scores.append(
            score_object(
                gold,
                pred.document if pred else None,
                ctx,
                cfg.replace(expected_split=split or cfg.expected_split),
                object_id=object_id,
                prediction_path=str(pred.path) if pred and pred.path else None,
                prediction_sha256=pred.sha256 if pred else None,
            )
        )
    extras = {
        "gold_path": str(gold_path),
        "gold_sha256": sha256_file(gold_path),
        "skipped_objects_without_gold": skipped,
        "hidden_final": {
            "run_id": frozen.run_id,
            "freeze_tag": frozen.freeze_tag,
            "config_hash": frozen.config_hash,
        }
        if frozen
        else None,
    }
    return scores, skipped, extras


def _gold_not_found(object_id: str) -> str:
    err = InspectorError("GOLD_NOT_FOUND", object_id=object_id)
    return f"{err.title}: {err.detail}"


def exit_code_for(scores: Sequence[ObjectScore]) -> ExitCode:
    if any(not s.schema.organizer_valid for s in scores):
        return ExitCode.SCHEMA_INVALID
    if any(s.gate_triggered for s in scores):
        return ExitCode.GATE_TRIGGERED
    return ExitCode.OK


def _refused(exc: HiddenAccessRefusedError) -> int:
    err = exc.error()
    detail = exc.reason_ru if err.code == "HIDDEN_TEST_ACCESS_DENIED" else err.detail.rstrip(".")
    _emit(f"{err.title}: {detail}. {err.hint or ''}".strip(), stream=sys.stderr)
    return int(ExitCode.HIDDEN_TEST_REFUSED)


# Error-catalogue codes that mean «an input is missing» (exit 6), not a failure of the tool (exit 1).
DATA_MISSING_CODES = frozenset({"PREDICTION_NOT_FOUND", "GOLD_NOT_FOUND"})


# ── subcommands ──────────────────────────────────────────────────────────────────────────────


def cmd_run(args: argparse.Namespace) -> int:
    paths = _paths(args)
    ctx = _context(args, paths)
    cfg = config_from_args(args, args.split)
    scores, skipped, extras = score_predictions(
        pred_path=args.pred,
        gold_path=args.gold or paths.train_checks_path,
        ctx=ctx,
        cfg=cfg,
        objects=args.objects or (),
        hidden_final=args.hidden_final,
        run_manifest=args.run_manifest,
    )
    for object_id in skipped:
        _emit(_gold_not_found(object_id), stream=sys.stderr)
    if not scores:
        _emit("Нечего оценивать: ни для одного объекта нет эталона и ответа.", stream=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    pooled = pool(scores, ctx, cfg)
    report = build_report(
        scores,
        pooled,
        cfg,
        ctx,
        gold_path=extras.pop("gold_path"),
        gold_sha256=extras.pop("gold_sha256"),
        extra=extras,
    )
    if args.out:
        written = write_outputs(report, scores, args.out)
        _emit(f"Отчёт записан: {written['score'].parent}", stream=sys.stderr)
    _emit(
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else render_text(scores, report.get("pooled"))
    )
    return int(exit_code_for(scores))


def cmd_validate(args: argparse.Namespace) -> int:
    paths = _paths(args)
    ctx = _context(args, paths)
    frozen = check_access(
        peek_object_ids(args.pred),
        ctx.split_policy,
        hidden_final=args.hidden_final,
        run_manifest=args.run_manifest,
    )
    cfg = DEFAULT_CONFIG.replace(integrity_rules=args.integrity_rules)
    worst = ExitCode.OK
    outputs: list[dict[str, Any]] = []
    for pred in load_predictions(args.pred):
        object_id = str(pred.object_id)
        split = (
            ctx.split_policy.split_of(object_id)
            if frozen and object_id in ctx.split_policy.hidden
            else args.split
        )
        schema = validate_schemas(pred.document)
        integrity = check_integrity(
            pred.document, ctx, cfg.replace(expected_split=split or args.split), schema=schema
        )
        outputs.append(
            {
                "object_id": object_id,
                "path": str(pred.path),
                "schema": schema.as_dict(),
                "integrity": integrity.as_dict(),
            }
        )
        if not schema.organizer_valid or integrity.failed:
            worst = ExitCode.SCHEMA_INVALID
    if args.json:
        _emit(json.dumps(outputs, ensure_ascii=False, indent=2))
    else:
        _emit("\n\n".join(render_validation(o["object_id"], o["schema"], o["integrity"]) for o in outputs))
    return int(worst)


def cmd_integrity(args: argparse.Namespace) -> int:
    """R1–R15 + P1–P6 on any submission (file, directory or run directory) against any manifest."""
    from inspector_eval import integrity

    paths = _paths(args)
    ctx = load_context(
        paths,
        manifest_path=args.manifest,
        catalog_path=args.catalog,
        split_policy_path=args.split_policy,
        weights_path=args.weights,
        superseded_path=args.superseded,
        require_weights=False,
    )
    answers = integrity.discover(args.pred)
    if not answers:
        raise InspectorError("PREDICTION_NOT_FOUND", path=str(args.pred))
    hidden_sidecar = next(
        (a.sidecar for a in answers if a.object_id in ctx.split_policy.hidden and a.sidecar is not None), None
    )
    # Guard on object ids only, before any answer content is read (93 §4.9).
    check_access(
        [a.object_id for a in answers],
        ctx.split_policy,
        hidden_final=args.hidden_final,
        run_manifest=args.run_manifest or hidden_sidecar,
    )
    cfg = DEFAULT_CONFIG.replace(integrity_rules=args.integrity_rules)
    reports = integrity.check_files(
        answers, ctx, expected_split=args.split, require_packaging=args.require_packaging, cfg=cfg
    )
    rows = [r.as_dict() for r in reports]
    if args.out:
        from inspector_common.paths import ensure_dir

        out = ensure_dir(args.out)
        (out / "integrity.json").write_text(
            json.dumps(
                {
                    "inputs": dict(ctx.input_hashes),
                    "superseded_known": ctx.superseded_file_ids is not None,
                    "objects": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if args.json:
        _emit(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _emit("\n\n".join(integrity.render(r) for r in rows))
    return int(ExitCode.OK if all(r.ok for r in reports) else ExitCode.SCHEMA_INVALID)


def cmd_tgold_gate(args: argparse.Namespace) -> int:
    """The T-GOLD must-pass gate on one run directory (95 §3.8, 97 M1)."""
    from inspector_eval import tgold_gate

    paths = _paths(args)
    ctx = _context(args, paths)
    gold_path = args.gold or paths.train_checks_path
    gold = read_jsonl(gold_path)
    check_access([args.object, *objects_in(gold)], ctx.split_policy)
    run_dir = args.run_dir if args.run_dir.is_dir() else paths.runs_root / str(args.run_dir)
    if not run_dir.is_dir():
        raise InspectorError("PREDICTION_NOT_FOUND", path=str(args.run_dir))
    result = tgold_gate.evaluate(
        run_dir, ctx, gold, object_id=args.object, max_extra=args.max_extra, runtime_s=args.runtime_s
    )
    written = tgold_gate.write(result, run_dir)
    if args.json:
        _emit(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        _emit(tgold_gate.render(result))
        _emit(f"Отчёт: {written}")
    if result.status == "FAIL":
        return int(ExitCode.GATE_TRIGGERED if result.criteria["G4"].status == "FAIL" else ExitCode.ERROR)
    return int(ExitCode.OK)


def cmd_selftest(args: argparse.Namespace) -> int:
    paths = _paths(args)
    ctx = _context(args, paths)
    gold = read_jsonl(args.gold or paths.train_checks_path)
    check_access(objects_in(gold), ctx.split_policy)
    results = run_cases(gold, ctx, object_id=args.object)
    rows = [r.as_dict() for r in results]
    if args.json:
        _emit(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _emit(f"Самопроверка inspector-score на T-GOLD ({args.object}): случаи отчёта 93 §2.3 и §4.10")
        _emit(
            f"{'случай':<10}{'F1':>7}{'лок.':>7}{'знач.':>7}{'цел.':>7}{'гейт':>6}{'без огр.':>10}{'итог':>9}{'ожид.':>9}{'93':>7}  "
        )
        for d in rows:
            _emit(
                f"{d['case']:<10}{d['f1']:>7.3f}{d['localisation']:>7.3f}{d['value_status']:>7.3f}{d['integrity']:>7.3f}"
                f"{('да' if d['gate_triggered'] else 'нет'):>6}{d['total_uncapped']:>10.2f}{d['total']:>9.2f}"
                f"{d['expected_total']:>9.2f}{('—' if d['report_93'] is None else f'{d["report_93"]:.2f}'):>7}  "
                f"{'OK' if d['ok'] else 'РАСХОЖДЕНИЕ'}  {d['title_ru']}"
            )
        failed = [d["case"] for d in rows if not d["ok"]]
        _emit("Все случаи совпали с ожидаемыми." if not failed else f"Расхождения: {', '.join(failed)}")
    return int(ExitCode.OK if all(r.ok for r in results) else ExitCode.ERROR)


def cmd_devset(args: argparse.Namespace) -> int:
    paths = _paths(args)
    ctx = _context(args, paths)
    registry = args.registry
    if args.devset_command == "list":
        rows = []
        for d in devset.load_registry(registry, ctx.split_policy):
            try:
                rows.append(devset.load_devset(d, paths, ctx, verify=False).summary())
            except InputError as exc:  # one broken set must not hide the others
                rows.append({"id": d.id, "object_id": d.object_id, "error": exc.message_ru})
        if args.json:
            _emit(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                if "error" in r:
                    _emit(f"{r['id']:<8} {r['object_id']:<30} ошибка: {r['error']}")
                    continue
                frozen = (
                    f"заморожен, хэш {'совпадает' if r['hash_ok'] else 'НЕ СОВПАДАЕТ'}"
                    if r["frozen"]
                    else "не заморожен"
                )
                _emit(
                    f"{r['id']:<8} {r['object_id']:<30} строк {r['rows']:>4}, нарушений {r['positives']:>3}, "
                    f"исключено {r['excluded_items']:>3}; {frozen}; {r['badge_ru']}"
                )
        return int(ExitCode.OK)
    if args.devset_command == "show":
        rows = devset.load_devset(
            devset.get_devset(args.id, registry, ctx.split_policy), paths, ctx, verify=False
        )
        _emit(
            json.dumps(
                {**rows.summary(), "gold_rows": rows.gold_rows, "excluded": rows.excluded},
                ensure_ascii=False,
                indent=2,
            )
        )
        return int(ExitCode.OK)
    digest = devset.freeze(args.id, paths, ctx, registry, now=utc_now())
    _emit(f"Набор {args.id} заморожен: sha256 меток {digest}")
    return int(ExitCode.OK)


def _ngold_target(args: argparse.Namespace, paths: DataPaths, ctx: ScoringContext) -> tuple[Any, Path]:
    ds = devset.get_devset(args.devset, args.registry, ctx.split_policy)
    if ds.format != "label_seed_json":
        raise InputError(f"Набор {ds.id} не является набором разметки команды ({ds.format})")
    return ds, (args.file or ds.resolve(paths))


def _annotation_from_args(args: argparse.Namespace) -> dict[str, Any]:
    from inspector_eval import ngold

    note: dict[str, Any] = {
        "labeller": args.labeller,
        "labeller_kind": args.labeller_kind,
        "protocol": ngold.PROTOCOL_ID,
        "blind": args.blind,
        "label": args.label,
        "confidence": args.confidence,
        "reasoning": args.reasoning,
        "parameter_code": args.code,
        "location": args.location,
        "labelled_at": utc_now(),
    }
    if args.evidence:
        note["evidence"] = [
            {"stage": s, "file_id": f, "pdf_page_number": int(p)}
            for s, f, p in (e.split(":") for e in args.evidence)
        ]
    if args.pages_viewed:
        note["pages_viewed"] = [
            {"file_id": f, "pdf_page_number": int(p)}
            for f, p in (e.split(":")[:2] for e in args.pages_viewed)
        ]
    for name in ("pd_value", "rd_value", "id_value"):
        value = getattr(args, name)
        if value is not None:
            note[name] = None if value == "null" else value
    if args.not_scorable:
        note["scorable"] = False
    return note


def cmd_ngold(args: argparse.Namespace) -> int:
    from inspector_eval import ngold

    paths = _paths(args)
    ctx = _context(args, paths)
    ds, path = _ngold_target(args, paths, ctx)
    action = args.ngold_command

    if action == "init":
        seed = ngold.upgrade(read_json(args.seed), ds.object_id)
        if seed["meta"]["object_id"] != ds.object_id:
            raise InputError(
                f"Затравка относится к {seed['meta']['object_id']}, набор {ds.id} — к {ds.object_id}"
            )
        document = ngold.load_label_set(path) if path.is_file() else ngold.upgrade({"meta": {}}, ds.object_id)
        known = {i["id"] for i in document["candidates"]}
        added = [i for i in seed["candidates"] if i["id"] not in known]
        document["candidates"].extend(added)
        document["meta"] = {**seed["meta"], **{k: v for k, v in document["meta"].items() if k != "purpose"}}
        document["meta"]["purpose"] = document["meta"].get("purpose") or seed["meta"].get("purpose")
        ngold.save_label_set(path, document, frozen=ds.frozen)
        _emit(
            f"Разметка {ds.id}: добавлено элементов {len(added)}, всего {len(document['candidates'])} → {path}"
        )
        return int(ExitCode.OK)

    document = ngold.load_label_set(path)
    if document["meta"].get("object_id") != ds.object_id:
        raise InputError(
            f"Файл {path} относится к {document['meta'].get('object_id')}, набор {ds.id} — к {ds.object_id}"
        )

    if action == "status":
        summary = ngold.status(document, ds.folds)
        summary["file"] = str(path)
        summary["file_sha256"] = ngold.file_sha256(path)
        summary["frozen"] = ds.frozen
        if args.json:
            _emit(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            agr = summary["agreement"]
            _emit(
                f"{ds.id} ({ds.object_id}): элементов {summary['items']}, оцениваемых {summary['scorable']}; "
                f"{'заморожен' if ds.frozen else 'не заморожен'}"
            )
            _emit(f"  метки: {summary['by_label']}")
            _emit(f"  источники: {summary['by_source']}; фолды: {summary['by_fold']}")
            _emit(
                f"  аннотации: {summary['annotated_by_kind']}; без метки: {len(summary['unlabelled'])}; "
                f"спорные: {len(summary['unresolved'])}"
            )
            if agr["n"]:
                _emit(f"  согласие агент/человек: {agr['agree']}/{agr['n']}, κ = {agr['cohen_kappa']:.3f}")
        return int(ExitCode.OK)

    if action == "packet":
        item = ngold.item_by_id(document, args.id)
        out = args.out or paths.runs_root / "ngold" / "packets" / args.id
        packet = ngold.render_packet(
            item,
            out,
            ngold.PageSource(ds.object_id, ctx),
            ctx,
            dpi=args.dpi,
            tiles=args.tiles,
            tile_dpi=args.tile_dpi,
            extra=args.extra or (),
        )
        if args.json:
            _emit(json.dumps(packet, ensure_ascii=False, indent=2))
        else:
            _emit(f"Слепой пакет {args.id}: {out}")
            for r in packet["rendered"]:
                _emit(f"  {r['file_id']} с.{r['pdf_page_number']}: {', '.join(r['files'])}")
        return int(ExitCode.OK)

    if action == "record":
        if args.json_file:
            raw = read_json(args.json_file)
            entries = raw if isinstance(raw, list) else [raw]
            for entry in entries:
                note = dict(entry["annotation"])
                note.setdefault("labelled_at", utc_now())
                ngold.record(document, str(entry["id"]), note)
        else:
            if not args.id or not args.label or not args.labeller:
                raise ValueError("укажите ID, --label и --labeller (или --json FILE)")
            ngold.record(document, args.id, _annotation_from_args(args))
            entries = [{"id": args.id}]
        ngold.save_label_set(path, document, frozen=ds.frozen)
        for entry in entries:
            item = ngold.item_by_id(document, str(entry["id"]))
            adj = item.get("adjudication") or {}
            _emit(f"{item['id']}: метка {item['label']} ({adj.get('method')}, решил {adj.get('decided_by')})")
        return int(ExitCode.OK)

    if action == "sample":
        n = args.n
        if not ngold.SPOTCHECK_MIN <= n <= ngold.SPOTCHECK_MAX and not args.any_size:
            raise ValueError(
                f"размер выборки для проверки {ngold.SPOTCHECK_MIN}…{ngold.SPOTCHECK_MAX} (или --any-size)"
            )
        ids = ngold.sample_ids(document, n, seed=args.seed, folds=ds.folds)
        out = args.out or paths.runs_root / "ngold" / f"spotcheck-seed{args.seed}"
        source = None if args.no_images else ngold.PageSource(ds.object_id, ctx)
        written = ngold.export_spotcheck(document, ids, out, ctx, source=source, dpi=args.dpi, seed=args.seed)
        _emit(f"Выборка для проверки: {len(ids)} элементов (seed {args.seed}) → {out}")
        if len(ids) < n:
            _emit(f"  В наборе только {len(ids)} оцениваемых элементов: выгружены все.")
        _emit(
            f"  Заполните {written['sheet'].name}, откройте {written['index'].name}; {written['key'].name} — после."
        )
        return int(ExitCode.OK)

    if action == "import-spotcheck":
        added, agr = ngold.import_spotcheck(
            document, args.sheet, labeller=args.labeller, labelled_at=utc_now()
        )
        ngold.save_label_set(path, document, frozen=ds.frozen)
        _emit(f"Импортировано меток проверяющего: {added}")
        if agr.n:
            _emit(
                f"Согласие агент/человек: {agr.agree}/{agr.n} ({agr.raw:.1%}), κ Коэна = {agr.kappa:.3f}"
                if agr.kappa is not None
                else f"{agr.agree}/{agr.n}"
            )
            for d in agr.as_dict()["disagreements"]:
                _emit(f"  расхождение {d['id']}: агент {d['agent']}, человек {d['human']} (решает человек)")
        return int(ExitCode.OK)
    raise ValueError(f"неизвестное действие {action}")


def cmd_sweep(args: argparse.Namespace) -> int:
    paths = _paths(args)
    ctx = _context(args, paths)
    cfg = config_from_args(args)
    registry = devset.load_registry(args.registry, ctx.split_policy)
    wanted = set(args.devsets.split(",")) if args.devsets else {d.id for d in registry}
    rows = [devset.load_devset(d, paths, ctx) for d in registry if d.id in wanted]
    candidates = calibration.load_candidates(args.pred_dir)
    check_access([o for c in candidates for o in c.predictions], ctx.split_policy)
    result = calibration.calibrate(candidates, rows, ctx, cfg, args.objective)
    result["config"] = cfg.describe()
    if args.out:
        from inspector_common.paths import ensure_dir

        out = ensure_dir(args.out)
        (out / "sweep.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.json:
        _emit(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        loo = result["loo"]
        _emit(
            f"Калибровка «оставить объект вне»: {len(result['candidates'])} кандидатов, фолды: {', '.join(loo['folds']) or '—'}"
        )
        if loo["status"] == "INSUFFICIENT_FOLDS":
            _emit("  Фолдов меньше двух: оценка на отложенных данных недоступна (нужны T-GOLD и N-GOLD).")
        for r in loo["held_out"]:
            _emit(f"  отложен {r['held_out_fold']}: выбран {r['chosen_candidate']} → {r['score']:.2f}")
        if loo["mean_held_out"] is not None:
            _emit(f"  среднее на отложенных: {loo['mean_held_out']:.2f}")
        if loo["final_candidate"]:
            _emit(
                f"  итоговый выбор (на всех фолдах): {loo['final_candidate']} (seen {loo['seen_mean']:.2f} — не результат)"
            )
    return int(ExitCode.OK)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inspector-score",
        description="Локальная оценка ответа по правилам организаторов: 60/15/15/10 и гейт критических нарушений (отчёт 93).",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="КОМАНДА")

    run = sub.add_parser("run", help="Оценить ответ по эталону")
    run.add_argument("--pred", type=Path, required=True, help="Файл ответа или каталог с <object_id>.json")
    run.add_argument(
        "--gold", type=Path, default=None, help="Эталон (по умолчанию public_train_checks.jsonl)"
    )
    run.add_argument("--objects", nargs="*", default=None, metavar="OBJECT_ID")
    run.add_argument(
        "--split",
        default="TRAIN_PUBLIC",
        choices=["TRAIN_PUBLIC"],
        help="Ожидаемая выборка (скрытая — только с --hidden-final)",
    )
    run.add_argument(
        "--out", type=Path, default=None, help="Каталог для score.json, per_check.csv, gate.csv, summary.txt"
    )
    run.add_argument("--json", action="store_true", help="Вывести score.json вместо текстового отчёта")
    add_variant_arguments(run)
    add_data_arguments(run)
    add_hidden_arguments(run)
    run.set_defaults(func=cmd_run)

    val = sub.add_parser("validate", help="Проверить ответ: схемы и правила целостности (без эталона)")
    val.add_argument("--pred", type=Path, required=True)
    val.add_argument("--split", default="TRAIN_PUBLIC", choices=["TRAIN_PUBLIC"])
    val.add_argument(
        "--integrity-rules", choices=CHOICES["integrity_rules"], default=DEFAULT_CONFIG.integrity_rules
    )
    val.add_argument("--json", action="store_true")
    add_data_arguments(val)
    add_hidden_arguments(val)
    val.set_defaults(func=cmd_validate)

    ig = sub.add_parser(
        "integrity",
        help="Правила целостности R1–R15 и упаковки P1–P6 для любого ответа и манифеста (без эталона)",
    )
    ig.add_argument(
        "--pred", type=Path, required=True, help="Файл ответа, каталог submission/ или каталог прогона"
    )
    ig.add_argument(
        "--split", default=None, help="Ожидаемая выборка (по умолчанию — выборка объекта в split_policy.json)"
    )
    ig.add_argument(
        "--require-packaging",
        action="store_true",
        help="Режим проверки экспорта: без sidecar и строгого варианта — нарушение (P2, P4)",
    )
    ig.add_argument(
        "--integrity-rules", choices=CHOICES["integrity_rules"], default=DEFAULT_CONFIG.integrity_rules
    )
    ig.add_argument("--out", type=Path, default=None, help="Каталог для integrity.json")
    ig.add_argument("--json", action="store_true")
    add_data_arguments(ig)
    add_hidden_arguments(ig)
    ig.set_defaults(func=cmd_integrity)

    tg = sub.add_parser("tgold-gate", help="Приёмка T-GOLD: прогон на Тюменской против эталона (95 §3.8)")
    tg.add_argument("--run-dir", type=Path, required=True, help="Каталог прогона или его run_id в runs/")
    tg.add_argument("--object", default=T_GOLD_OBJECT)
    tg.add_argument("--gold", type=Path, default=None)
    tg.add_argument("--max-extra", type=int, default=5, help="Допустимо лишних ключей VIOLATION_PRESENT")
    tg.add_argument("--runtime-s", type=float, default=None, help="Измеренное время прогона, с")
    tg.add_argument("--json", action="store_true")
    add_data_arguments(tg)
    tg.set_defaults(func=cmd_tgold_gate)

    st = sub.add_parser("selftest", help="Самопроверка на T-GOLD: случаи отчёта 93 §2.3")
    st.add_argument("--gold", type=Path, default=None)
    st.add_argument("--object", default=T_GOLD_OBJECT)
    st.add_argument("--json", action="store_true")
    add_data_arguments(st)
    st.set_defaults(func=cmd_selftest)

    ds = sub.add_parser("devset", help="Реестр наборов для калибровки (T-GOLD, N-GOLD)")
    ds.add_argument("devset_command", choices=["list", "show", "freeze"])
    ds.add_argument("id", nargs="?", default=None)
    ds.add_argument("--registry", type=Path, default=devset.REGISTRY_PATH)
    ds.add_argument("--json", action="store_true")
    add_data_arguments(ds)
    ds.set_defaults(func=cmd_devset)

    ng = sub.add_parser("ngold", help="Разметка N-GOLD: слепые пакеты, метки, выборка для проверки")
    ng_sub = ng.add_subparsers(dest="ngold_command", required=True, metavar="ДЕЙСТВИЕ")

    def _ng_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--devset", default="N-GOLD", help="Набор разметки команды в реестре")
        p.add_argument("--registry", type=Path, default=devset.REGISTRY_PATH)
        p.add_argument("--file", type=Path, default=None, help="Файл разметки (по умолчанию из реестра)")
        add_data_arguments(p)

    p_init = ng_sub.add_parser("init", help="Создать или дополнить файл разметки из затравки 95")
    p_init.add_argument("--seed", type=Path, required=True, help="docs/analysis/95_novoslob_label_seed.json")
    _ng_common(p_init)
    p_status = ng_sub.add_parser("status", help="Сводка разметки и согласия")
    p_status.add_argument("--json", action="store_true")
    _ng_common(p_status)
    p_packet = ng_sub.add_parser("packet", help="Слепой пакет элемента: вопрос, изображения и текст страниц")
    p_packet.add_argument("id")
    p_packet.add_argument("--out", type=Path, default=None)
    p_packet.add_argument("--dpi", type=int, default=100)
    p_packet.add_argument("--tiles", default=None, metavar="КxР", help="Плитки страницы, например 3x2")
    p_packet.add_argument("--tile-dpi", type=int, default=200)
    p_packet.add_argument(
        "--extra",
        nargs="*",
        default=None,
        metavar="FILE:PAGE[:x0,y0,x1,y1]",
        help="Дополнительные страницы/клипы",
    )
    p_packet.add_argument("--json", action="store_true")
    _ng_common(p_packet)
    p_record = ng_sub.add_parser("record", help="Записать метку элемента (или пакет меток --json)")
    p_record.add_argument("id", nargs="?", default=None)
    p_record.add_argument(
        "--json", dest="json_file", type=Path, default=None, help="[{id, annotation}] или один"
    )
    p_record.add_argument("--label", default=None)
    p_record.add_argument("--labeller", default=None)
    p_record.add_argument("--labeller-kind", default="AGENT", choices=["AGENT", "HUMAN"])
    p_record.add_argument("--blind", action=argparse.BooleanOptionalAction, default=True)
    p_record.add_argument("--confidence", default=None, choices=["HIGH", "MEDIUM", "LOW"])
    p_record.add_argument("--reasoning", default=None)
    p_record.add_argument("--code", default=None)
    p_record.add_argument("--location", default=None)
    p_record.add_argument("--evidence", nargs="*", default=None, metavar="STAGE:FILE:PAGE")
    p_record.add_argument("--pages-viewed", nargs="*", default=None, metavar="FILE:PAGE")
    p_record.add_argument("--pd-value", default=None)
    p_record.add_argument("--rd-value", default=None)
    p_record.add_argument("--id-value", default=None)
    p_record.add_argument("--not-scorable", action="store_true")
    _ng_common(p_record)
    p_sample = ng_sub.add_parser(
        "sample", help="Случайная выборка 25–30 элементов для проверки пользователем"
    )
    p_sample.add_argument("--n", type=int, default=28)
    p_sample.add_argument("--seed", type=int, default=20260928)
    p_sample.add_argument("--out", type=Path, default=None)
    p_sample.add_argument("--dpi", type=int, default=100)
    p_sample.add_argument("--no-images", action="store_true")
    p_sample.add_argument("--any-size", action="store_true", help="Разрешить размер вне 25…30")
    _ng_common(p_sample)
    p_import = ng_sub.add_parser("import-spotcheck", help="Загрузить заполненный sheet.csv проверяющего")
    p_import.add_argument("sheet", type=Path)
    p_import.add_argument("--labeller", default="user")
    _ng_common(p_import)
    ng.set_defaults(func=cmd_ngold)

    sw = sub.add_parser("sweep", help="Калибровка «оставить объект вне» по кандидатам в каталоге")
    sw.add_argument(
        "--pred-dir",
        type=Path,
        required=True,
        help="Каталог кандидатов: <имя>/params.json и <object_id>.json",
    )
    sw.add_argument("--devsets", default=None, help="Наборы через запятую (по умолчанию все из реестра)")
    sw.add_argument("--objective", choices=calibration.OBJECTIVES, default="total")
    sw.add_argument("--registry", type=Path, default=devset.REGISTRY_PATH)
    sw.add_argument("--out", type=Path, default=None)
    sw.add_argument("--json", action="store_true")
    add_variant_arguments(sw)
    add_data_arguments(sw)
    sw.set_defaults(func=cmd_sweep)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "devset" and args.devset_command in ("show", "freeze") and not args.id:
        parser.error("укажите идентификатор набора")
    try:
        return int(args.func(args))
    except HiddenAccessRefusedError as exc:
        return _refused(exc)
    except InspectorError as exc:
        if exc.code in ("HIDDEN_TEST_ACCESS_DENIED", "HIDDEN_FINAL_NOT_FROZEN"):
            _emit(f"{exc.title}: {exc.detail}", stream=sys.stderr)
            return int(ExitCode.HIDDEN_TEST_REFUSED)
        if exc.code in DATA_MISSING_CODES:
            _emit(f"{exc.title}: {exc.detail} {exc.hint or ''}".strip(), stream=sys.stderr)
            return int(ExitCode.DATA_MISSING)
        _emit(f"{exc.title}: {exc.detail} {exc.hint or ''}".strip(), stream=sys.stderr)
        return int(ExitCode.ERROR)
    except InputError as exc:
        _emit(exc.message_ru, stream=sys.stderr)
        return int(ExitCode.DATA_MISSING)
    except ValueError as exc:
        _emit(f"Ошибка аргументов: {exc}", stream=sys.stderr)
        return int(ExitCode.USAGE)


if __name__ == "__main__":
    raise SystemExit(main())
