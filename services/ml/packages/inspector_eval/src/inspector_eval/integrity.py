"""Integrity checker for any submission plus a manifest (93 §2.6, §4.6; 97 §2.5): R1–R15 and run packaging.

``validation.check_integrity`` holds the per-document rules R1–R15, which feed the 10-point
``document_integrity_and_split_handling`` component. This module runs them on any submission — a file, a
directory, or a run directory (``runs/<run_id>/``, paths from ``run_layout.yaml``) — against any organizer-style
manifest, without gold and without the scoring weights, and adds the packaging rules the organizers cannot see
but our exporter must satisfy before an answer leaves the machine (P-rules, never counted in the score):

- P1 the file is named ``<object_id>.json`` (one object per answer file);
- P2 the sidecar exists, validates (``submission_sidecar``) and describes exactly this object;
- P3 the sidecar's ``input_manifest_hash`` and ``inputs.manifest_sha256`` match the manifest used now (a stale
  run or another package version fails);
- P4 the strict variant exists, validates (``submission.strict``) and equals the organizer-field projection of the
  full answer, check by check;
- P5 every cited file was readable in the run (sidecar ``files[].local_status`` is not MISSING_ON_DISK);
- P6 ``RD_ID_MIXED`` files are cited with their resolved stage (sidecar ``files[].stage_resolved``; the organizer
  rule R7 accepts both RD and ID, but the gold cites the resolved one, 93 §2.6 (e)).

A P-rule without its input (no sidecar, no strict file) is NOT_EVALUATED, except in ``require_packaging`` mode
(the exporter's gate), where a missing sidecar or strict file fails P2/P4.

Hidden-test integrity (93 §4.9, CLAUDE.md rule 4): these are format checks. A TEST_HIDDEN object is checked only
through the frozen-run guard (``guard.check_access``: ``--hidden-final`` plus a RunManifest/sidecar with a
``freeze_tag`` that exists as a git tag), and its report is always redacted: rule ids, statuses and violation
counts only — no codes, locations, values, file ids or pages.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import SubmissionCheck
from inspector_common.hashing import input_manifest_hash
from inspector_eval.config import DEFAULT_CONFIG, ScoreConfig
from inspector_eval.data import InputError, ScoringContext, read_json
from inspector_eval.validation import (
    IntegrityReport,
    RuleResult,
    SchemaReport,
    Violation,
    check_integrity,
    validate_schemas,
)

PACKAGING_TITLES: dict[str, str] = {
    "P1": "Файл ответа назван по объекту (<object_id>.json), один объект в файле",
    "P2": "Есть sidecar, он соответствует контракту и описывает этот объект",
    "P3": "Sidecar построен по текущему манифесту (хэши совпадают)",
    "P4": "Строгий вариант совпадает с полями организаторов полного ответа",
    "P5": "Цитируемые файлы были доступны при прогоне",
    "P6": "Файлы RD_ID_MIXED цитируются с определённой стадией",
}
PACKAGING_IDS: tuple[str, ...] = tuple(PACKAGING_TITLES)


@dataclass(slots=True)
class PackagingResult:
    rule: str
    status: str = "PASS"  # PASS | FAIL | WARN | NOT_EVALUATED
    violations: list[Violation] = field(default_factory=list)
    note_ru: str | None = None

    def fail(self, detail_ru: str, **where: Any) -> None:
        self.status = "FAIL"
        self.violations.append(Violation(detail_ru=detail_ru, **where))

    def as_dict(self, redact: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "title_ru": PACKAGING_TITLES[self.rule],
            "status": self.status,
            "violations_count": len(self.violations),
        }
        if not redact:
            out["violations"] = [v.as_dict() for v in self.violations]
            if self.note_ru:
                out["note_ru"] = self.note_ru
        return out


@dataclass(slots=True)
class SubmissionIntegrity:
    object_id: str | None
    path: str | None
    expected_split: str
    schema: SchemaReport
    integrity: IntegrityReport
    packaging: dict[str, PackagingResult]
    hidden: bool = False

    @property
    def failed_rules(self) -> list[str]:
        counted = [r for r, res in self.integrity.rules.items() if res.counted and res.status == "FAIL"]
        return counted + [p for p, res in self.packaging.items() if res.status == "FAIL"]

    @property
    def ok(self) -> bool:
        """Organizer schema valid and no counted R-rule or P-rule failed (WARN and NOT_EVALUATED pass)."""
        return self.schema.organizer_valid and not self.failed_rules

    def as_dict(self, redact: bool | None = None) -> dict[str, Any]:
        redact = self.hidden if redact is None else redact
        rules = []
        for res in self.integrity.rules.values():
            row: dict[str, Any] = {
                "rule": res.rule,
                "title_ru": res.title_ru,
                "status": res.status,
                "counted": res.counted,
                "violations_count": len(res.violations),
            }
            if not redact:
                row["violations"] = [v.as_dict() for v in res.violations]
                if res.note_ru:
                    row["note_ru"] = res.note_ru
            rules.append(row)
        counted = [r for r in self.integrity.rules.values() if r.counted and r.status in ("PASS", "FAIL")]
        schema: dict[str, Any] = {
            name: {"valid": not errs, "errors_count": len(errs), **({} if redact else {"errors": errs[:50]})}
            for name, errs in self.schema.errors.items()
        }
        return {
            "object_id": self.object_id,
            "path": None if redact else self.path,
            "expected_split": self.expected_split,
            "redacted": redact,
            "ok": self.ok,
            "failed_rules": self.failed_rules,
            "schema": schema,
            "integrity": {
                "rule_set": self.integrity.rule_set,
                "share": self.integrity.share,
                "hard": self.integrity.hard,
                "passed": sum(1 for r in counted if r.status == "PASS"),
                "counted": len(counted),
                "rules": rules,
            },
            "packaging": [p.as_dict(redact) for p in self.packaging.values()],
        }


# ── helpers ──────────────────────────────────────────────────────────────────────────────────


def strict_projection(document: Mapping[str, Any]) -> dict[str, Any]:
    """The organizer-field projection of a full answer (``SubmissionCheck.STRICT_FIELDS``, evidence trimmed)."""
    checks = []
    for check in document.get("checks", []) if isinstance(document.get("checks"), list) else []:
        if not isinstance(check, Mapping):
            continue
        row = {name: check.get(name) for name in SubmissionCheck.STRICT_FIELDS}
        row["evidence"] = [
            {k: e.get(k) for k in ("stage", "file_id", "pdf_page_number")}
            for e in check.get("evidence", [])
            if isinstance(e, Mapping)
        ]
        checks.append(row)
    return {"object_id": document.get("object_id"), "checks": checks}


def _cited(document: Any) -> list[tuple[int, Mapping[str, Any], Mapping[str, Any]]]:
    out = []
    checks = document.get("checks") if isinstance(document, Mapping) else None
    for index, check in enumerate(checks if isinstance(checks, list) else []):
        if not isinstance(check, Mapping):
            continue
        for ev in check.get("evidence", []) if isinstance(check.get("evidence"), list) else []:
            if isinstance(ev, Mapping):
                out.append((index, check, ev))
    return out


def _name_stage(row: Mapping[str, Any]) -> str | None:
    """Last-resort stage of an RD_ID_MIXED file from its manifest path (registry signals, no text)."""
    from inspector_registry.stages import resolve_stage

    relative = row.get("relative_path")
    if not isinstance(relative, str):
        return None
    resolved = resolve_stage(str(row.get("stage")), relative, None).stage_resolved
    return resolved if resolved in ("RD", "ID") else None


def _where(index: int, check: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "check_index": index,
        "parameter_code": str(check.get("parameter_code")),
        "location": str(check.get("location")),
    }


# ── the checker ──────────────────────────────────────────────────────────────────────────────


def check_document(
    document: Any,
    ctx: ScoringContext,
    *,
    path: Path | None = None,
    expected_split: str | None = None,
    sidecar: Mapping[str, Any] | None = None,
    strict_document: Any = None,
    resolved_stages: Mapping[str, str] | None = None,
    require_packaging: bool = False,
    cfg: ScoreConfig = DEFAULT_CONFIG,
) -> SubmissionIntegrity:
    """R1–R15 (``validation.check_integrity``) plus P1–P6 on one answer document.

    ``expected_split`` defaults to the object's own split in split_policy.json (TRAIN_PUBLIC for an unknown
    object, which then fails R2). ``sidecar`` enables P2, P3 and P5; ``strict_document`` P4; P6 uses the
    sidecar's ``files[].stage_resolved`` and then ``resolved_stages`` (file_id → RD/ID, e.g. from the
    registry's inventory report).
    """
    object_id = document.get("object_id") if isinstance(document, Mapping) else None
    own_split = ctx.split_policy.split_of(object_id) if isinstance(object_id, str) else None
    split = expected_split or own_split or "TRAIN_PUBLIC"
    schema = validate_schemas(document)
    integrity = check_integrity(document, ctx, cfg.replace(expected_split=split), schema=schema)
    packaging = {rule: PackagingResult(rule) for rule in PACKAGING_IDS}

    # P1 name and one object per file
    p1 = packaging["P1"]
    if path is None:
        p1.status, p1.note_ru = "NOT_EVALUATED", "ответ передан без файла"
    elif not isinstance(object_id, str) or path.name != f"{object_id}.json":
        p1.fail(f"файл {path.name} не соответствует объекту {object_id!r} (ожидается <object_id>.json)")

    # P2/P3/P5/P6 need the sidecar
    sidecar_files: dict[str, Mapping[str, Any]] = {}
    if sidecar is None:
        for rule in ("P2", "P3", "P5"):
            packaging[rule].status = "NOT_EVALUATED"
            packaging[rule].note_ru = "sidecar не найден"
        if require_packaging:
            packaging["P2"].note_ru = None
            packaging["P2"].fail(
                "sidecar отсутствует: экспорт обязан записать submission/<object_id>.sidecar.json"
            )
    else:
        p2 = packaging["P2"]
        errors = validation_errors("submission_sidecar", sidecar)
        for message in errors[:10]:
            p2.fail(f"sidecar не соответствует контракту: {message}")
        entries = sidecar.get("objects") if isinstance(sidecar.get("objects"), list) else []
        listed = [e.get("object_id") for e in entries if isinstance(e, Mapping)]
        if listed != [object_id]:
            p2.fail(f"sidecar описывает объекты {listed}, а ответ — {object_id!r}")
        sidecar_files = {
            str(f.get("file_id")): f
            for f in (sidecar.get("files") if isinstance(sidecar.get("files"), list) else [])
            if isinstance(f, Mapping)
        }
        foreign = sorted(fid for fid, f in sidecar_files.items() if f.get("object_id") != object_id)
        if foreign:
            p2.fail(f"в sidecar есть файлы другого объекта: {', '.join(foreign[:10])}")

        p3 = packaging["P3"]
        rows = [r for r in ctx.manifest.values() if r.get("object_id") == object_id]
        entry = next((e for e in entries if isinstance(e, Mapping) and e.get("object_id") == object_id), None)
        if rows and entry is not None:
            expected = input_manifest_hash(rows)
            if entry.get("input_manifest_hash") != expected:
                p3.fail(
                    f"input_manifest_hash sidecar {str(entry.get('input_manifest_hash'))[:12]}… ≠ "
                    f"текущий {expected[:12]}…"
                )
        else:
            p3.status, p3.note_ru = "NOT_EVALUATED", "нет строк манифеста или записи объекта в sidecar"
        manifest_sha = ctx.input_hashes.get("manifest_sha256")
        used_sha = (
            (sidecar.get("inputs") or {}).get("manifest_sha256")
            if isinstance(sidecar.get("inputs"), Mapping)
            else None
        )
        if manifest_sha and used_sha and used_sha != manifest_sha:
            p3.fail(f"manifest_sha256 sidecar {used_sha[:12]}… ≠ проверяемый манифест {manifest_sha[:12]}…")

        p5 = packaging["P5"]
        if not sidecar_files:
            p5.status, p5.note_ru = "NOT_EVALUATED", "в sidecar нет списка файлов"
        for index, check, ev in _cited(document):
            fid = str(ev.get("file_id"))
            info = sidecar_files.get(fid)
            if info is None:
                if sidecar_files:
                    p5.fail(
                        f"файл {fid} не обрабатывался в прогоне (нет в sidecar)",
                        file_id=fid,
                        **_where(index, check),
                    )
                continue
            if info.get("local_status") == "MISSING_ON_DISK":
                p5.fail(f"файл {fid} отсутствовал на диске при прогоне", file_id=fid, **_where(index, check))

    # P6 resolved stage of RD_ID_MIXED files: the sidecar's files first, then the registry's inventory report
    resolved_by_file = {
        fid: str(f["stage_resolved"])
        for fid, f in sidecar_files.items()
        if f.get("stage_resolved") in ("RD", "ID")
    }
    for fid, stage in (resolved_stages or {}).items():
        resolved_by_file.setdefault(fid, stage)
    p6 = packaging["P6"]
    mixed_cited = False
    for index, check, ev in _cited(document):
        fid = str(ev.get("file_id"))
        if (ctx.manifest.get(fid) or {}).get("stage") != "RD_ID_MIXED":
            continue
        mixed_cited = True
        resolved = resolved_by_file.get(fid)
        if resolved is None:
            resolved = _name_stage(ctx.manifest.get(fid) or {})
            if resolved is not None:
                resolved_by_file[fid] = resolved
        if resolved is None:
            p6.status = "WARN" if p6.status == "PASS" else p6.status
            p6.violations.append(
                Violation(
                    detail_ru=f"стадия файла {fid} (RD_ID_MIXED) не определена",
                    file_id=fid,
                    **_where(index, check),
                )
            )
        elif ev.get("stage") != resolved:
            p6.fail(
                f"файл {fid} (RD_ID_MIXED) определён как {resolved}, процитирован как {ev.get('stage')}",
                file_id=fid,
                **_where(index, check),
            )
    if not mixed_cited:
        p6.note_ru = "файлы RD_ID_MIXED не цитируются"

    # P4 strict variant
    p4 = packaging["P4"]
    if strict_document is None:
        p4.status, p4.note_ru = "NOT_EVALUATED", "строгий вариант не найден"
        if require_packaging:
            p4.note_ru = None
            p4.fail("строгий вариант отсутствует: экспорт обязан записать submission-strict/<object_id>.json")
    else:
        for message in validation_errors("submission.strict", strict_document)[:10]:
            p4.fail(f"строгий вариант не соответствует схеме: {message}")
        if isinstance(document, Mapping):
            expected_strict = strict_projection(document)
            got = strict_document if isinstance(strict_document, Mapping) else {}
            if got.get("object_id") != expected_strict["object_id"]:
                p4.fail(
                    f"объект строгого варианта {got.get('object_id')!r} ≠ {expected_strict['object_id']!r}"
                )
            got_checks = got.get("checks") if isinstance(got.get("checks"), list) else []
            if len(got_checks) != len(expected_strict["checks"]):
                p4.fail(
                    f"проверок в строгом варианте {len(got_checks)}, в полном {len(expected_strict['checks'])}"
                )
            else:
                for index, (a, b) in enumerate(zip(expected_strict["checks"], got_checks, strict=True)):
                    if {k: a.get(k) for k in a} != {k: (b or {}).get(k) for k in a}:
                        p4.fail(
                            "проверка отличается от полного ответа",
                            check_index=index,
                            parameter_code=str(a.get("parameter_code")),
                            location=str(a.get("location")),
                        )

    hidden = isinstance(object_id, str) and object_id in ctx.split_policy.hidden
    return SubmissionIntegrity(
        object_id=object_id if isinstance(object_id, str) else None,
        path=str(path) if path else None,
        expected_split=split,
        schema=schema,
        integrity=integrity,
        packaging=packaging,
        hidden=hidden,
    )


@dataclass(frozen=True, slots=True)
class AnswerFiles:
    """One answer and its companions, as found on disk."""

    object_id: str | None
    submission: Path
    strict: Path | None
    sidecar: Path | None
    inventory: Path | None = None  # the registry's inventory report of the object in the same run


def discover(pred: Path) -> list[AnswerFiles]:
    """Answer files under ``pred``: a file, a ``submission/`` directory, or a run directory.

    In a run directory the strict variant and the sidecar come from their ``run_layout.yaml`` paths
    (SUBMISSION_STRICT, SUBMISSION_SIDECAR); next to a lone file they are looked up the same way relative to
    the file's directory (``../submission-strict/<object_id>.json``, ``<object_id>.sidecar.json``).
    """
    from inspector_common.runlayout import artifact_path

    if pred.is_file():
        files = [pred]
    elif pred.is_dir():
        base = pred / "submission" if (pred / "submission").is_dir() else pred
        files = sorted(p for p in base.glob("*.json") if not p.name.endswith(".sidecar.json"))
    else:
        raise InputError(f"Ответ не найден: {pred}")
    out = []
    for file in files:
        doc = read_json(file)
        object_id = doc.get("object_id") if isinstance(doc, dict) else None
        stem = object_id if isinstance(object_id, str) and "/" not in object_id and object_id else file.stem
        run_dir = file.parent.parent
        strict = run_dir / artifact_path("SUBMISSION_STRICT", object_id=stem)
        sidecar = run_dir / artifact_path("SUBMISSION_SIDECAR", object_id=stem)
        if not sidecar.is_file():
            sidecar = file.parent / f"{stem}.sidecar.json"
        inventory = run_dir / artifact_path("INVENTORY", object_id=stem)
        out.append(
            AnswerFiles(
                object_id=object_id if isinstance(object_id, str) else None,
                submission=file,
                strict=strict if strict.is_file() else None,
                sidecar=sidecar if sidecar.is_file() else None,
                inventory=inventory if inventory.is_file() else None,
            )
        )
    return out


def inventory_stages(path: Path) -> dict[str, str]:
    """file_id → resolved stage (RD/ID) from an inventory report (``inventory/<object_id>.json``, AG-01)."""
    raw = read_json(path)
    files = raw.get("files") if isinstance(raw, dict) else None
    rows = files if isinstance(files, list) else []
    return {
        str(f["file_id"]): str(f["stage_resolved"])
        for f in rows
        if isinstance(f, Mapping) and f.get("stage_resolved") in ("RD", "ID") and f.get("file_id")
    }


def check_files(
    answers: Sequence[AnswerFiles],
    ctx: ScoringContext,
    *,
    expected_split: str | None = None,
    require_packaging: bool = False,
    cfg: ScoreConfig = DEFAULT_CONFIG,
) -> list[SubmissionIntegrity]:
    """Check every discovered answer. The caller runs the hidden-test guard first (object ids only)."""
    reports = []
    for answer in answers:
        document = read_json(answer.submission)
        reports.append(
            check_document(
                document,
                ctx,
                path=answer.submission,
                expected_split=expected_split,
                sidecar=read_json(answer.sidecar) if answer.sidecar else None,
                strict_document=read_json(answer.strict) if answer.strict else None,
                resolved_stages=inventory_stages(answer.inventory) if answer.inventory else None,
                require_packaging=require_packaging,
                cfg=cfg,
            )
        )
    return reports


def render(report: Mapping[str, Any]) -> str:
    """Russian text report of one ``SubmissionIntegrity.as_dict()``."""
    mark = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "NOT_EVALUATED": "—"}
    lines = [
        f"Объект {report['object_id']}: {'целостность в порядке' if report['ok'] else 'ЕСТЬ НАРУШЕНИЯ'}"
        + (" (отчёт обезличен: скрытая выборка)" if report["redacted"] else ""),
        f"  схема организаторов: {'соответствует' if report['schema']['organizer']['valid'] else 'НЕ соответствует'}; "
        f"правила R: {report['integrity']['passed']} из {report['integrity']['counted']} "
        f"(доля {report['integrity']['share']:.3f}, набор {report['integrity']['rule_set']})",
    ]
    for rule in report["integrity"]["rules"]:
        extra = "" if rule["counted"] else " (не учитывается)"
        lines.append(
            f"  {mark[rule['status']]} {rule['rule']:<4}{rule['title_ru']}{extra}: {rule['status']}"
            + (f", нарушений {rule['violations_count']}" if rule["violations_count"] else "")
        )
        for v in rule.get("violations", [])[:5]:
            lines.append(
                f"        {v.get('detail_ru')} [{v.get('parameter_code', '')} · {v.get('location', '')}]"
            )
        if rule.get("note_ru"):
            lines.append(f"        {rule['note_ru']}")
    for rule in report["packaging"]:
        lines.append(
            f"  {mark[rule['status']]} {rule['rule']:<4}{rule['title_ru']}: {rule['status']}"
            + (f", нарушений {rule['violations_count']}" if rule["violations_count"] else "")
        )
        for v in rule.get("violations", [])[:5]:
            lines.append(f"        {v.get('detail_ru')}")
        if rule.get("note_ru"):
            lines.append(f"        {rule['note_ru']}")
    return "\n".join(lines)


def result_rule(report: SubmissionIntegrity, rule: str) -> RuleResult | PackagingResult:
    return report.integrity.rules.get(rule) or report.packaging[rule]
