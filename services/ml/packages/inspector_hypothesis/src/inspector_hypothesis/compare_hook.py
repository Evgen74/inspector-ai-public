"""The hook AG-04's ``compare`` calls (``inspector_compare.engine.CompareEngine._external_free``).

    from inspector_hypothesis import compare_hook
    groups = compare_hook.free_finding_groups(ctx=object_context, observations=obs, config=cfg, run_dir=run_dir)

``ctx`` is AG-04's ObjectContext (files with resolved stages and citability, layouts, tables, values); PageTokens
are read from the run directory. The return value is a list of contract FindingGroup dicts (matrix_scope
FREE_SEARCH, evidence_bind_status BOUND); AG-04 validates them, drops locations its own router already covers, caps
and renumbers all FREE groups. The hook never raises: on any problem it logs and returns what it has (possibly []).

:func:`run_for_context` gives the full result (FREE groups, Logical_Rules suspicions, Раздел 6 / А.5 rows, the
Раздел 2 count) for the protocol builder; it is cached per (object, run directory, config), so ``compare`` and
``export`` in one process share one hypothesis run.

For the protocol builder (Приложение 2 Раздел 6 lists *every* suspicion, 93 §5.4; А.5 is its superset):

    extra = compare_hook.protocol_suspicions(ctx=ctx, run_dir=run_dir, rendered_free_groups=free_group_dicts,
                                             start_no=len(section6_rows) + 1, first_card_no=next_card_no)
    section6_rows += extra["section6_rows"]      # contract SuspicionRow dicts (Logical_Rules, unexported FREE)
    a5_rows       += extra["a5_rows"]            # contract HypothesisRow dicts
    ai_suspicions  = len(section6_rows)          # Раздел 2 «Подозрений ИИ (свободный поиск)»

:func:`suspicion_records` gives the §9.5 records themselves (for a SUSPICIONS artifact and the web import).
Both never raise.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from inspector_hypothesis.engine import HypothesisConfig, HypothesisResult, run_hypotheses
from inspector_hypothesis.free import FreeConfig
from inspector_hypothesis.inputs import DocumentInfo, HypothesisInputs, RunPageSource, enrich_with_layouts
from inspector_hypothesis.suspicion import Suspicion, a5_rows, section6_rows
from inspector_hypothesis.valueconflict import RULE_CODE as VALUE_CONFLICT_RULE

log = logging.getLogger(__name__)

_CACHE: dict[tuple[str, str, HypothesisConfig], HypothesisResult] = {}


def _run_dir(ctx: Any, run_dir: Path | str | None) -> Path | None:
    if run_dir is not None:
        return Path(run_dir)
    own = getattr(ctx, "run_dir", None)
    if own is not None:
        return Path(own)
    source = getattr(ctx, "layout_source", None) or ""
    if isinstance(source, str) and source.startswith("run:"):
        from inspector_common.settings import get_settings

        return get_settings().paths.runs_root / source.removeprefix("run:")
    return None


def inputs_from_context(ctx: Any, run_dir: Path) -> HypothesisInputs:
    """HypothesisInputs from AG-04's ObjectContext (duck-typed: files, layouts, tables, values, object_id)."""
    docs: dict[str, DocumentInfo] = {}
    for fid, f in (getattr(ctx, "files", None) or {}).items():
        if not getattr(f, "is_pdf", True):
            continue
        docs[fid] = DocumentInfo(
            file_id=fid,
            stage=getattr(f, "stage", None),
            section=getattr(f, "section", None),
            pages_total=getattr(f, "pdf_pages", None),
            file_sha256=getattr(f, "sha256", None),
            name=getattr(f, "name", None),
            manifest_stage=getattr(f, "manifest_stage", None),
            citable=bool(getattr(f, "citable", True)),
        )
    layouts = dict(getattr(ctx, "layouts", None) or {})
    return HypothesisInputs(
        object_id=ctx.object_id,
        documents=enrich_with_layouts(docs, layouts),
        pages=RunPageSource(run_dir),
        layouts=layouts,
        tables=dict(getattr(ctx, "tables", None) or {}),
        values=list(getattr(ctx, "values", None) or []),
        run_id=run_dir.name,
    )


def run_for_context(
    *, ctx: Any, run_dir: Path | str | None = None, config: HypothesisConfig | None = None
) -> HypothesisResult | None:
    """The full hypothesis run of one object (cached); None when the run directory is unknown."""
    rd = _run_dir(ctx, run_dir)
    if rd is None:
        log.warning("hyp.hook_no_run_dir", extra={"object_id": getattr(ctx, "object_id", None)})
        return None
    config = config or HypothesisConfig()
    key = (str(ctx.object_id), str(rd.resolve()), config)
    if key not in _CACHE:
        _CACHE[key] = run_hypotheses(inputs_from_context(ctx, rd), config)
    return _CACHE[key]


def free_finding_groups(
    *,
    ctx: Any,
    observations: Any = None,
    config: Any = None,
    run_dir: Path | str | None = None,
    **_: Any,
) -> list[dict[str, Any]]:
    """Evidence-bound FREE-* FindingGroup dicts for AG-04's compare (never raises)."""
    try:
        cap = getattr(config, "max_free_groups", None)
        hcfg = HypothesisConfig(free=FreeConfig(max_groups=int(cap) if cap is not None else None))
        result = run_for_context(ctx=ctx, run_dir=run_dir, config=hcfg)
        if result is None:
            return []
        _ = observations  # AG-04's own room observations; the FREE path reads PageTokens itself
        return [g.dump() for g in result.free_groups]
    except Exception as exc:  # the scored path must never break because of AG-07
        log.warning("hyp.hook_failed", extra={"detail": f"{type(exc).__name__}: {exc}"})
        return []


def clear_cache() -> None:
    _CACHE.clear()


def _result_for(ctx: Any, run_dir: Path | str | None) -> HypothesisResult | None:
    """The result ``compare`` already computed for this object and run directory (whatever its config), else a
    fresh run with the default config."""
    rd = _run_dir(ctx, run_dir)
    if rd is None:
        return None
    obj, where = str(ctx.object_id), str(rd.resolve())
    for (o, r, _cfg), result in _CACHE.items():
        if (o, r) == (obj, where):
            return result
    return run_for_context(ctx=ctx, run_dir=rd)


def _covered(s: Suspicion, rendered: list[tuple[str, frozenset[str]]]) -> bool:
    """A FREE suspicion whose rooms a rendered FREE group of the same topic already shows (AG-04 renders those)."""
    if not s.exported or not s.parameter_code:
        return False
    topic = s.parameter_code.split("-")[1]
    rooms = set(s.subject_key.split(":", 1)[1].split(",")) if ":" in s.subject_key else set()
    return any(t == topic and rooms <= locs for t, locs in rendered)


def _drop_reported(s: Suspicion, matrix_keys: frozenset[tuple[str, str]]) -> bool:
    """A value-conflict suspicion of a (parameter, location) that already produced a violation adds nothing: the
    violation is the stronger statement (§9.5)."""
    if s.rule_code != VALUE_CONFLICT_RULE:
        return False
    codes = [s.explanation.get("matrix_parameter_code"), *(s.explanation.get("twin_parameter_codes") or [])]
    loc = str(s.explanation.get("location") or "OBJECT")
    return any((str(c), loc) in matrix_keys for c in codes if c)


def protocol_suspicions(
    *,
    ctx: Any,
    run_dir: Path | str | None = None,
    rendered_free_groups: Iterable[Mapping[str, Any]] = (),
    start_no: int = 1,
    first_card_no: int = 1,
    matrix_keys: Iterable[tuple[str, str]] = (),
    rule_codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Раздел 6 and А.5 rows for the suspicions the protocol builder does not render from FREE finding groups:
    Logical_Rules suspicions and FREE candidates that were not exported (or whose group was not kept). Rows are
    numbered from ``start_no``, cards from ``first_card_no`` (Б.n), in the order of :func:`suspicion.finalize`.
    ``matrix_keys``: (matrix parameter code, location) of the violations already found: value-conflict suspicions
    of those get no duplicate; ``rule_codes`` limits the rows to those rule codes (default: all).
    Never raises: on a problem the lists are empty and ``error`` says why."""
    out: dict[str, Any] = {"section6_rows": [], "a5_rows": [], "suspicions": [], "error": None}
    try:
        result = _result_for(ctx, run_dir)
        if result is None:
            out["error"] = "run directory unknown"
            return out
        rendered = [
            (str(g.get("parameter_code", "")).split("-")[1], frozenset(g.get("locations") or []))
            for g in rendered_free_groups
            if str(g.get("parameter_code", "")).startswith("FREE-")
        ]
        extra = []
        keys = frozenset((str(c), str(loc)) for c, loc in matrix_keys)
        only = None if rule_codes is None else set(rule_codes)
        for s in result.suspicions:
            if only is not None and s.rule_code not in only:
                continue
            if _covered(s, rendered) or _drop_reported(s, keys):
                continue
            if s.exported:  # its FREE group was not kept by the protocol builder: a plain suspicion now
                s = s.model_copy(update={"parameter_code": None, "finding_group_id": None, "exported": False})
            extra.append(s)
        rows6 = section6_rows(extra, first_card_no)
        rowsa5 = a5_rows(extra, first_card_no)
        for i, row in enumerate(rows6):
            row.no = start_no + i
        out["section6_rows"] = [r.model_dump(mode="json", exclude_none=True) for r in rows6]
        out["a5_rows"] = [r.model_dump(mode="json", exclude_none=True) for r in rowsa5]
        out["suspicions"] = [
            {**s.dump(), "card_ref": r.card_ref, "section6_no": r.no}
            for s, r in zip(extra, rows6, strict=True)
        ]
    except Exception as exc:  # the protocol must never break because of AG-07
        log.warning("hyp.protocol_suspicions_failed", extra={"detail": f"{type(exc).__name__}: {exc}"})
        out.update(section6_rows=[], a5_rows=[], suspicions=[], error=f"{type(exc).__name__}: {exc}")
    return out


def suspicion_records(*, ctx: Any, run_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Every SUSPICION of the object (ТЗ §9.5 fields + 90 §3.3 #8 extensions), JSON-ready; never raises."""
    try:
        result = _result_for(ctx, run_dir)
        return [] if result is None else [s.dump() for s in result.suspicions]
    except Exception as exc:
        log.warning("hyp.suspicion_records_failed", extra={"detail": f"{type(exc).__name__}: {exc}"})
        return []
