"""VALUE_CONFLICT: documents of ONE stage print contradicting values of the same matrix parameter (ТЗ §9.5).

The value comparator drops such values as ambiguous (AbstainReason AMBIGUOUS_VALUE) and says nothing. Here they become
one SUSPICION per (parameter, location): «В ПД противоречивые значения параметра PZ-022 «Степень огнестойкости»:
II — <файл> л.17; III — <файл> л.6; в РД — III (<файл> л.3). Требуется уточнение, какое значение действующее.»
A suspicion is never a violation: it changes no label, no submission check and no score.

Rules (against noise):
- only values the extractor trusts (quality OK, first candidate, not a ГПЗУ limit column) with a matrix parameter;
- values are grouped per (parameter, location/element key): «Бетонная подготовка» B7,5 vs «Колонны» B25 never meet;
- enum/ordinal values differ when their normalised value differs; numeric ones when the difference exceeds the
  parameter's tolerance and the shown precision (values of another unit are not comparable: no claim);
- a stage is in conflict only when at least two different FILES of it disagree (two mentions in one file are not);
- a page that itself prints several different values of the parameter (a norm's list «I, II, III, IV степени…») is a
  list, not a statement: its values are ignored;
- a mention whose sentence names another subject (built-in parking, neighbouring/existing building, block) is
  ignored; numbers printed in prose (fact pz.value) are not compared, and the reliability category PZ-015 is skipped (see
  ConflictConfig for why);
- one suspicion per (parameter, location), with every value of every stage and its evidence (file, page).
The caller drops suspicions of a (parameter, location) that already produced a violation (see compare_hook).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from inspector_common.contracts.enums import DiscoveryMethod
from inspector_common.contracts.models import EvidenceRef, ExtractedValue
from inspector_common.params import load_params
from inspector_hypothesis.inputs import HypothesisInputs
from inspector_hypothesis.rules import review_priority
from inspector_hypothesis.suspicion import (
    NO_VALUE,
    STAGES,
    Suspicion,
    _bind_status,
    _ev,
    _stage_refs,
    revision_fingerprint,
    suspicion_key,
)

RULE_CODE = "HR-LOG-101"
RULE_VERSION = "1"
DETECTOR = "VALUE_CONFLICT"
STAGE_RU = {"PD": "ПД", "RD": "РД", "ID": "ИД"}
MAX_REFS_SHOWN = 3
MAX_VALUES_SHOWN = 6
Tolerance = tuple[Decimal | None, Decimal | None]


@dataclass(frozen=True, slots=True)
class ConflictConfig:
    min_files: int = 2  # different files of one stage that must disagree
    base_confidence: float = 0.7
    # A stage printing more distinct values than this is a list of unrelated mentions (loads of many consumers, …),
    # not a contradiction: no suspicion.
    max_distinct_values: int = 4
    # Element-level keys (concrete class of «Колонны», …) are family names, not instances: different floors or
    # structures of one family legitimately differ, so only object-level values are compared by default.
    include_elements: bool = False
    # A number printed in prose next to a label («расчётная мощность 8,86 кВт») often names one consumer, block or
    # mode of the object, so different numbers of different volumes are not a contradiction. Numbers of tables
    # (ТЭП, explications) and enum/ordinal classes of the building are compared.
    prose_numbers: bool = False
    # Parameters whose statements legitimately differ inside one stage: the reliability category of power supply
    # is I for the fire-fighting systems and II for the rest of the building.
    skip_params: frozenset[str] = frozenset({"PZ-015"})
    # Mentions whose sentence is about a built-in parking, a neighbour, an existing block, … (see _OTHER_SUBJECT).
    skip_other_subjects: bool = True


@dataclass(slots=True)
class Cluster:
    """One distinct value of a stage with every mention of it."""

    text: str
    members: list[ExtractedValue] = field(default_factory=list)

    @property
    def files(self) -> set[str]:
        return {m.file_id for m in self.members}


# ── value helpers (the tolerance semantics of valuecmp, without importing AG-04) ───────────────────


def _stage(v: ExtractedValue) -> str:
    return str(v.stage.value if hasattr(v.stage, "value") else v.stage)


def _decimals(raw: str) -> int:
    m = re.search(r"\d+[.,](\d+)", raw or "")
    return len(m.group(1)) if m else 0


def _num(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def _basis(v: ExtractedValue) -> str | None:
    q = v.value_norm.qualifiers or {}
    return q.get("basis") if isinstance(q, Mapping) else None


# The sentence names another subject than the object: a built-in parking or a neighbour, an existing or adjoining
# building, a block («корпус»), a distance «до зданий …». Such a mention states a fact about that part, not about
# the object, and must not be set against the object's value.
_OTHER_SUBJECT = re.compile(
    r"встроенн|автостоянк|паркинг|соседн|существующ|смежн|пристроенн|подземн|до\s+здани|корпус",
    re.IGNORECASE,
)


def _about_other_subject(v: ExtractedValue) -> bool:
    return bool(_OTHER_SUBJECT.search(v.context_text or ""))


def _trusted(v: ExtractedValue) -> bool:
    flag = str(v.quality_flag.value if hasattr(v.quality_flag, "value") else v.quality_flag)
    # is_ambiguous is NOT a reason to skip: the extractor sets it exactly on the values that contradict each other
    return bool(v.param_code) and flag == "OK" and (v.candidate_rank or 1) == 1 and _basis(v) != "ГПЗУ"


def _tolerance(spec: Any) -> Tolerance:
    rule = spec.comparison_rule or {}
    for sub in rule.get("sub_checks") or [rule]:
        tol = sub.get("tolerance") or {}
        if tol.get("abs") is not None or tol.get("rel") is not None:
            return (
                Decimal(str(tol["abs"])) if tol.get("abs") is not None else None,
                Decimal(str(tol["rel"])) if tol.get("rel") is not None else None,
            )
    return None, None


def _differs(a: ExtractedValue, b: ExtractedValue, tol: Tolerance) -> bool:
    """True when two readings contradict each other (never when they cannot be compared)."""
    an, bn = a.value_norm, b.value_norm
    ntype = str(an.type.value if hasattr(an.type, "value") else an.type)
    if ntype == "number":
        x, y = _num(an.value), _num(bn.value)
        if x is None or y is None or (an.unit or None) != (bn.unit or None):
            return False
        shown = min(_decimals(a.value_raw), _decimals(b.value_raw))
        eps = Decimal("0.5") * Decimal(10) ** -shown
        if tol[0] is not None:
            eps = max(eps, tol[0])
        if tol[1] is not None and x != 0:
            eps = max(eps, tol[1] * abs(x))
        return abs(y - x) > eps
    if an.value is None or bn.value is None:
        return False
    return str(an.value) != str(bn.value)


def _display(v: ExtractedValue) -> str:
    n = v.value_norm
    ntype = str(n.type.value if hasattr(n.type, "value") else n.type)
    if ntype == "number" and n.value is not None:
        text = str(n.value)
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        text = text.replace(".", ",")
        return f"{text} {n.unit}" if n.unit else text
    return str(n.value) if n.value is not None else v.value_raw


def _clusters(values: list[ExtractedValue], tol: Tolerance) -> list[Cluster]:
    out: list[Cluster] = []
    for v in sorted(values, key=lambda v: (v.file_id, v.page_no, -v.confidence)):
        for c in out:
            if not _differs(c.members[0], v, tol):
                c.members.append(v)
                break
        else:
            out.append(Cluster(_display(v), [v]))
    return out


def _drop_list_pages(values: list[ExtractedValue], tol: Tolerance) -> list[ExtractedValue]:
    """Values of a page that itself prints several different values of the parameter are a norm's list, not a
    statement about the object."""
    by_page: dict[tuple[str, int], list[ExtractedValue]] = defaultdict(list)
    for v in values:
        by_page[(v.file_id, v.page_no)].append(v)
    bad = {k for k, vs in by_page.items() if len(_clusters(vs, tol)) > 1}
    return [v for v in values if (v.file_id, v.page_no) not in bad]


# ── the detector ────────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ValueConflict:
    code: str
    location: str
    stages: dict[str, list[Cluster]]  # every stage with values, incl. the ones without a conflict
    conflict_stages: list[str]
    also_codes: list[str] = field(
        default_factory=list
    )  # matrix twins reading the very same statements (PZ-021/ZU-124)

    def mentions(self) -> set[tuple[str, str, int]]:
        return {(st, m.file_id, m.page_no) for st, cs in self.stages.items() for c in cs for m in c.members}

    def texts(self) -> set[tuple[str, str]]:
        return {(st, c.text) for st, cs in self.stages.items() for c in cs}


def _merge_twins(conflicts: list[ValueConflict]) -> list[ValueConflict]:
    """One suspicion for a fact that two matrix parameters carry (the energy class is PZ-021 and ZU-124): a conflict
    whose mentions and values are a subset of another one's at the same location is folded into it."""
    kept: list[ValueConflict] = []
    for c in sorted(conflicts, key=lambda c: (-len(c.mentions()), c.code)):
        host = next(
            (
                k
                for k in kept
                if k.location == c.location and c.mentions() <= k.mentions() and c.texts() <= k.texts()
            ),
            None,
        )
        if host is None:
            kept.append(c)
        else:
            host.also_codes.append(c.code)
    return sorted(kept, key=lambda c: (c.code, c.location))


def detect(values: Iterable[ExtractedValue], cfg: ConflictConfig | None = None) -> list[ValueConflict]:
    cfg = cfg or ConflictConfig()
    params = load_params()
    groups: dict[tuple[str, str], list[ExtractedValue]] = defaultdict(list)
    for v in values:
        if not _trusted(v) or _stage(v) not in STAGES or str(v.param_code) in cfg.skip_params:
            continue
        if cfg.skip_other_subjects and _about_other_subject(v):
            continue
        if not cfg.include_elements and (v.location or "OBJECT") != "OBJECT":
            continue
        ntype = v.value_norm.type
        if (
            not cfg.prose_numbers
            and v.fact_key == "pz.value"
            and str(getattr(ntype, "value", ntype)) == "number"
        ):
            continue
        groups[(str(v.param_code), v.location or "OBJECT")].append(v)
    out: list[ValueConflict] = []
    for (code, loc), vs in sorted(groups.items()):
        try:
            spec = params.get(code)
        except Exception:
            continue
        tol = _tolerance(spec)
        vs = _drop_list_pages(vs, tol)
        per_stage: dict[str, list[Cluster]] = {}
        conflicts: list[str] = []
        for stage in STAGES:
            sv = [v for v in vs if _stage(v) == stage]
            if not sv:
                continue
            clusters = _clusters(sv, tol)
            if len(clusters) > cfg.max_distinct_values:
                continue
            per_stage[stage] = clusters
            # two different FILES must disagree: two distinct values, each with a file the other lacks
            if len({v.file_id for v in sv}) >= cfg.min_files and any(
                a.files - b.files and b.files - a.files for a in clusters for b in clusters if a is not b
            ):
                conflicts.append(stage)
        if conflicts:
            out.append(ValueConflict(code, loc, per_stage, conflicts))
    return _merge_twins(out)


# ── suspicion ───────────────────────────────────────────────────────────────────────────────────────


def _where(inputs: HypothesisInputs, file_id: str, page: int) -> str:
    """«<файл> л.<страница PDF>»: inspectors cite the PDF page of the uploaded file as its sheet."""
    doc = inputs.documents.get(file_id)
    return f"{(doc.name if doc is not None else None) or file_id} л.{page}"


def _cluster_refs(inputs: HypothesisInputs, c: Cluster) -> list[str]:
    seen: list[tuple[str, int]] = []
    for m in sorted(c.members, key=lambda m: (m.file_id, m.page_no)):
        if (m.file_id, m.page_no) not in seen:
            seen.append((m.file_id, m.page_no))
    shown = [_where(inputs, f, p) for f, p in seen[:MAX_REFS_SHOWN]]
    if len(seen) > MAX_REFS_SHOWN:
        shown.append(f"и ещё {len(seen) - MAX_REFS_SHOWN}")
    return shown


def _stage_text(inputs: HypothesisInputs, clusters: list[Cluster], conflict: bool) -> str:
    ordered = sorted(clusters, key=lambda c: (-len(c.files), c.text))
    parts = []
    for c in ordered[:MAX_VALUES_SHOWN]:
        refs = "; ".join(_cluster_refs(inputs, c))
        parts.append(f"{c.text} — {refs}" if conflict else f"{c.text} ({refs})")
    if len(ordered) > MAX_VALUES_SHOWN:
        parts.append(f"и ещё значений: {len(ordered) - MAX_VALUES_SHOWN}")
    return "; ".join(parts)


def _cell(stage_clusters: list[Cluster] | None) -> str:
    if not stage_clusters:
        return NO_VALUE
    ordered = sorted(stage_clusters, key=lambda c: (-len(c.files), c.text))[:MAX_VALUES_SHOWN]
    return "; ".join(c.text if len(stage_clusters) == 1 else f"{c.text} ({len(c.files)} ф.)" for c in ordered)


def _description(conflict: ValueConflict, inputs: HypothesisInputs) -> str:
    params = load_params()
    label = " / ".join(
        f"{code} «{params.get(code).parameter_name or params.get(code).short_name}»"
        for code in (conflict.code, *conflict.also_codes)
    )
    where = "" if conflict.location == "OBJECT" else f" ({conflict.location})"
    lead, rest = [], []
    for stage in STAGES:
        clusters = conflict.stages.get(stage)
        if not clusters:
            continue
        if stage in conflict.conflict_stages:
            lead.append(
                f"В {STAGE_RU[stage]} противоречивые значения параметра {label}{where}: "
                + _stage_text(inputs, clusters, True)
            )
        else:
            rest.append(f"в {STAGE_RU[stage]} — " + _stage_text(inputs, clusters, False))
    return "; ".join(lead + rest) + ". Требуется уточнение, какое значение действующее."


def to_suspicion(
    conflict: ValueConflict, inputs: HypothesisInputs, run_id: str | None, cfg: ConflictConfig
) -> Suspicion:
    spec = load_params().get(conflict.code)
    evidence: list[EvidenceRef] = []
    seen: set[tuple[str, str, int]] = set()
    for stage in STAGES:
        for c in conflict.stages.get(stage, []):
            for m in sorted(c.members, key=lambda m: (m.file_id, m.page_no)):
                if (stage, m.file_id, m.page_no) in seen:
                    continue
                seen.add((stage, m.file_id, m.page_no))
                doc = inputs.documents.get(m.file_id)
                boxes = list(m.geometry.boxes) if m.geometry is not None and m.geometry.boxes else None
                evidence.append(
                    _ev(
                        stage=stage,
                        file_id=m.file_id,
                        pdf_page_number=m.page_no,
                        document_sheet_number=inputs.sheet_number(m.file_id, m.page_no),
                        file_sha256=doc.file_sha256 if doc is not None else None,
                        page_basis="PDF_NATIVE",
                        geometry={"boxes": [list(b) for b in boxes[:8]]} if boxes else None,
                        geometry_space="PDF_VISIBLE_ROTATED_TL_V1" if boxes else None,
                        document_code=inputs.page_code(m.file_id, m.page_no),
                    )
                )
    refs = _stage_refs(inputs, evidence)
    fingerprint = revision_fingerprint(inputs, (e.file_id for e in evidence))
    subject = f"{conflict.code}:{conflict.location}"
    conf = [m.confidence for cs in conflict.stages.values() for c in cs for m in c.members]
    confidence = round(min(0.85, cfg.base_confidence * (sum(conf) / len(conf)) / 0.9), 3)
    critical = "КРИТ" in str(spec.criticality).upper() or str(spec.criticality).upper().startswith("CRIT")
    return Suspicion(
        suspicion_id=1,
        discovery_method=DiscoveryMethod.LOGICAL_ANALYSIS,
        confidence=confidence,
        description=_description(conflict, inputs),
        pd_reference=refs.get("PD"),
        rd_reference=refs.get("RD"),
        review_priority=review_priority("HIGH" if critical else "MEDIUM", confidence),
        normative_base=NO_VALUE,
        suspicion_key=suspicion_key(inputs.object_id, fingerprint, RULE_CODE, subject),
        object_id=inputs.object_id,
        run_id=run_id,
        id_reference=refs.get("ID"),
        detector=DETECTOR,
        rule_code=RULE_CODE,
        rule_version=RULE_VERSION,
        subject_type="OBJECT" if conflict.location == "OBJECT" else "ELEMENT",
        subject_key=subject,
        stage_cells={st: _cell(conflict.stages.get(st)) for st in STAGES},
        evidence=evidence,
        evidence_bind_status=_bind_status(evidence),
        parameter_code=None,  # the row's code slot is for FREE-* codes; the matrix code is in subject_key/explanation
        not_exported_reasons=["противоречие значений внутри стадии: подозрение, не нарушение (ТЗ §9.5)"],
        revision_fingerprint=fingerprint,
        explanation={
            "kind": "VALUE_CONFLICT",
            "matrix_parameter_code": conflict.code,
            "twin_parameter_codes": conflict.also_codes,
            "location": conflict.location,
            "conflict_stages": conflict.conflict_stages,
            "values": {
                st: [
                    {
                        "value": c.text,
                        "files": len(c.files),
                        "mentions": [
                            {"file_id": m.file_id, "page": m.page_no, "raw": m.value_raw}
                            for m in c.members[:8]
                        ],
                    }
                    for c in cs
                ]
                for st, cs in conflict.stages.items()
            },
        },
    )


def value_conflict_suspicions(
    inputs: HypothesisInputs, run_id: str | None, cfg: ConflictConfig | None = None
) -> list[Suspicion]:
    cfg = cfg or ConflictConfig()
    return [to_suspicion(c, inputs, run_id, cfg) for c in detect(inputs.values, cfg)]


__all__ = ["ConflictConfig", "ValueConflict", "detect", "to_suspicion", "value_conflict_suspicions"]
