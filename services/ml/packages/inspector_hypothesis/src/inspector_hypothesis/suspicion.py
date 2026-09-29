"""SUSPICION records (ТЗ §9.5 «Структура подозрения») and their protocol rows (Приложение 2 Раздел 6, Приложение А.5).

A suspicion is a hypothesis outside the matrix. It is never a violation: it is not counted in «Выявлено нарушений»,
never a training label and never sent to РиН (ТЗ §9.5). Only evidence-bound FREE element groups are also exported
to the submission (as FREE-* rows, protocol_status WARNING, 97 §2.6); their suspicion carries the FREE code and the
finding group id.

The record keeps the ТЗ §9.5 field names verbatim (``suspicion_id``, ``discovery_method``, ``confidence``,
``description``, ``pd_reference``, ``rd_reference``, ``review_priority``, ``normative_base``, ``finding_status``,
``inspector_status``) and adds the 90 §3.3 #8 extensions. Dedup (§9.5): suspicions merge only within one object and
comparable revisions — ``suspicion_key`` = sha256(object | revision fingerprint of the cited files | rule | subject).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from inspector_common.contracts.enums import (
    DiscoveryMethod,
    EvidenceBindStatus,
    ReviewPriority,
    SuspicionInspectorStatus,
)
from inspector_common.contracts.loader import load_enums
from inspector_common.contracts.models import EvidenceRef, HypothesisRow, SuspicionRow
from inspector_hypothesis.free import DETECTOR as FREE_DETECTOR
from inspector_hypothesis.free import RULE_CODE as FREE_RULE_CODE
from inspector_hypothesis.free import RULE_VERSION as FREE_RULE_VERSION
from inspector_hypothesis.free import (
    FreeCandidate,
    element_noun,
    rationale_of,
    rooms_ru,
    stage_values,
    title_of,
)
from inspector_hypothesis.inputs import HypothesisInputs
from inspector_hypothesis.rules import RuleOutcome, review_priority

STAGES = ("PD", "RD", "ID")
DECISION_RU: dict[str, str] = {
    "PENDING": "⏳ Ожидает",
    "CLARIFICATION_REQUIRED": "❓ Требует уточнения",
    "CONVERTED_TO_CANDIDATE": "✅ Переведено в кандидаты",
    "DISMISSED": "❌ Отклонено",
    "STALE": "Устарело после дозагрузки",
}
NO_VALUE = "—"


class Suspicion(BaseModel):
    """One SUSPICION (ТЗ §9.5 fields first, verbatim; then 90 §3.3 #8 extensions)."""

    model_config = ConfigDict(extra="forbid")

    suspicion_id: int = Field(ge=1)
    discovery_method: DiscoveryMethod
    confidence: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=1)
    pd_reference: str | None
    rd_reference: str | None
    review_priority: ReviewPriority
    normative_base: str
    finding_status: Literal["SUSPICION"] = "SUSPICION"
    inspector_status: SuspicionInspectorStatus = SuspicionInspectorStatus.PENDING

    suspicion_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_id: str
    run_id: str | None = None
    id_reference: str | None = None
    detector: str
    rule_code: str
    rule_version: str
    subject_type: str
    subject_key: str
    expected_value: str | None = None
    actual_value: str | None = None
    stage_cells: dict[str, str]
    evidence: list[EvidenceRef] = Field(default_factory=list)
    evidence_bind_status: EvidenceBindStatus
    parameter_code: str | None = None
    finding_group_id: str | None = None
    exported: bool = False
    not_exported_reasons: list[str] = Field(default_factory=list)
    overlaps_matrix_codes: list[str] = Field(default_factory=list)
    normative_refs: list[str] = Field(default_factory=list)
    normative_verified: bool = False
    revision_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    supporting_methods: list[DiscoveryMethod] = Field(default_factory=list)
    explanation: dict[str, Any] = Field(default_factory=dict)

    def dump(self) -> dict[str, Any]:
        """JSON-ready record (nested evidence without unset optional fields, as the contract models dump)."""
        d = self.model_dump(mode="json")
        d["evidence"] = [e.dump() for e in self.evidence]
        return d

    def tz_view(self) -> dict[str, Any]:
        """Exactly the ТЗ §9.5 example fields, in its order."""
        d = self.model_dump(mode="json")
        return {
            k: d[k]
            for k in (
                "suspicion_id",
                "discovery_method",
                "confidence",
                "description",
                "pd_reference",
                "rd_reference",
                "review_priority",
                "normative_base",
                "finding_status",
                "inspector_status",
            )
        }


# ───────────────────────────────────────────── references and keys ─────────────────────────────────────────────


def reference(inputs: HypothesisInputs, ev: Mapping[str, Any] | EvidenceRef) -> str:
    """«<шифр>, л.<лист>, стр.<страница>» as in the ТЗ §9.5 example («25-01-АР-ПЭ, л.11, стр.3»);
    the file id stands in for an unknown шифр."""
    if isinstance(ev, EvidenceRef):
        fid, page, sheet = ev.file_id, ev.pdf_page_number, ev.document_sheet_number
    else:
        fid, page, sheet = str(ev.get("file_id")), ev.get("pdf_page_number"), ev.get("document_sheet_number")
    if sheet is None and page is not None:
        sheet = inputs.sheet_number(fid, int(page))
    code = (inputs.page_code(fid, int(page)) if page is not None else None) or fid
    parts = [code]
    if sheet is not None:
        parts.append(f"л.{sheet}")
    if page is not None:
        parts.append(f"стр.{page}")
    return ", ".join(parts)


def _stage_refs(
    inputs: HypothesisInputs, evidence: Sequence[Mapping[str, Any] | EvidenceRef]
) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for ev in evidence:
        stage = str(ev.stage) if isinstance(ev, EvidenceRef) else str(ev.get("stage"))
        if stage in STAGES:
            ref = reference(inputs, ev)
            if ref not in out.setdefault(stage, []):
                out[stage].append(ref)
    return {k: "; ".join(v[:2]) for k, v in out.items()}


def revision_fingerprint(inputs: HypothesisInputs, file_ids: Iterable[str]) -> str:
    """sha256 over the cited files' identities (file_id:sha256), i.e. the compared revisions (§9.5 dedup)."""
    parts = sorted(
        f"{fid}:{(inputs.documents[fid].file_sha256 if fid in inputs.documents else '') or ''}"
        for fid in set(file_ids)
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def suspicion_key(object_id: str, fingerprint: str, rule_code: str, subject_key: str) -> str:
    return hashlib.sha256(f"{object_id}|{fingerprint}|{rule_code}|{subject_key}".encode()).hexdigest()


def _ev(**fields: Any) -> EvidenceRef:
    """An EvidenceRef with only the known fields set (unset ones stay out of the dump)."""
    return EvidenceRef.model_validate({k: v for k, v in fields.items() if v is not None})


def _evidence_refs(evidence: Iterable[Mapping[str, Any]], inputs: HypothesisInputs) -> list[EvidenceRef]:
    out: list[EvidenceRef] = []
    for ev in evidence:
        if not ev.get("file_id") or not ev.get("pdf_page_number") or ev.get("stage") not in STAGES:
            continue
        doc = inputs.documents.get(str(ev["file_id"]))
        geometry = ev.get("geometry")
        out.append(
            _ev(
                stage=ev["stage"],
                file_id=ev["file_id"],
                pdf_page_number=int(ev["pdf_page_number"]),
                document_sheet_number=ev.get("document_sheet_number"),
                file_sha256=doc.file_sha256 if doc is not None else None,
                page_basis="PDF_NATIVE",
                geometry=geometry,
                geometry_space="PDF_VISIBLE_ROTATED_TL_V1" if geometry else None,
                document_code=inputs.page_code(str(ev["file_id"]), int(ev["pdf_page_number"])),
            )
        )
    return out


def _bind_status(evidence: Sequence[EvidenceRef]) -> EvidenceBindStatus:
    if not evidence:
        return EvidenceBindStatus.UNBOUND
    if all(e.geometry is not None and (e.geometry.boxes or e.geometry.polygons) for e in evidence):
        return EvidenceBindStatus.BOUND
    return EvidenceBindStatus.PARTIAL


# ───────────────────────────────────────────── builders ─────────────────────────────────────────────


def from_rule_outcome(outcome: RuleOutcome, inputs: HypothesisInputs, run_id: str | None) -> Suspicion:
    """A SUSPICION from an EMITTED Logical_Rule outcome (never exported to the submission)."""
    rule = outcome.rule
    evidence = _evidence_refs(outcome.evidence, inputs)
    confidence = rule.base_confidence
    if outcome.item and isinstance(outcome.item.get("confidence"), int | float):
        confidence *= float(outcome.item["confidence"])
    confidence = round(max(0.0, min(1.0, confidence)), 3)
    stage = outcome.stage
    cells: dict[str, str] = {}
    for st in STAGES:
        tpl = rule.cells.get(st)
        if tpl is None and stage == st:
            tpl = rule.cells.get("*")
        cells[st] = (outcome.render(tpl) if tpl else None) or NO_VALUE
    refs = _stage_refs(inputs, evidence)
    fingerprint = revision_fingerprint(inputs, (e.file_id for e in evidence))
    # §9.5 dedup: by content when the rule names it (copies in several documents are one statement), else by the
    # subject within the cited revisions
    content = outcome.render(rule.scope.dedup) if rule.scope.dedup else None
    key = (
        suspicion_key(inputs.object_id, "content", rule.rule_code, content)
        if content
        else suspicion_key(inputs.object_id, fingerprint, rule.rule_code, outcome.subject_key)
    )
    return Suspicion(
        suspicion_id=1,
        discovery_method=rule.discovery_method,
        confidence=confidence,
        description=outcome.render(rule.message_template) or rule.rule_name,
        pd_reference=refs.get("PD"),
        rd_reference=refs.get("RD"),
        review_priority=review_priority(rule.severity, confidence),
        normative_base=rule.normative_base or NO_VALUE,
        suspicion_key=key,
        object_id=inputs.object_id,
        run_id=run_id,
        id_reference=refs.get("ID"),
        detector="LOGICAL_RULE",
        rule_code=rule.rule_code,
        rule_version=str(rule.version),
        subject_type=rule.scope.subject_type,
        subject_key=outcome.subject_key,
        expected_value=outcome.render(rule.expected_template),
        actual_value=outcome.render(rule.actual_template),
        stage_cells=cells,
        evidence=evidence,
        evidence_bind_status=_bind_status(evidence),
        overlaps_matrix_codes=list(rule.overlaps_matrix_codes),
        normative_refs=list(rule.normative_refs),
        normative_verified=rule.verified,
        not_exported_reasons=["логические правила формируют подозрения только для Раздела 6"],
        revision_fingerprint=fingerprint,
        explanation={
            "rule_name": rule.rule_name,
            **outcome.trace(),
            **({"norm_check": rule.norm_check.model_dump(exclude_none=True)} if rule.norm_check else {}),
        },
    )


def from_free_candidate(cand: FreeCandidate, inputs: HypothesisInputs, run_id: str | None) -> Suspicion:
    """The SUSPICION of a FREE element candidate (exported or not)."""
    noun = element_noun(cand.route) or cand.family.label_ru
    evidence: list[EvidenceRef] = []
    for score, role in ((cand.pd_anchor, "EXPECTED"), (cand.rd_anchor, "ACTUAL")):
        if score is None:
            continue
        boxes = score.hit_boxes + [b for r in cand.rooms for b in score.room_boxes.get(r, [])]
        evidence.append(
            _ev(
                stage=score.stage,
                file_id=score.file_id,
                pdf_page_number=score.page_no,
                document_sheet_number=inputs.sheet_number(score.file_id, score.page_no),
                file_sha256=inputs.documents[score.file_id].file_sha256,
                page_basis="PDF_NATIVE",
                role=role,
                is_anchor=True,
                geometry={"boxes": [list(b) for b in boxes[:8]]} if boxes else None,
                geometry_space="PDF_VISIBLE_ROTATED_TL_V1" if boxes else None,
                document_code=inputs.page_code(score.file_id, score.page_no),
            )
        )
    refs = _stage_refs(inputs, evidence)
    fingerprint = revision_fingerprint(inputs, (e.file_id for e in evidence))
    subject = f"{cand.family.family}:{','.join(cand.rooms)}"
    pd_cell, rd_cell, _ = stage_values(cand.route, cand, inputs)  # the same texts as the FREE finding
    cells = {"PD": pd_cell or NO_VALUE, "RD": rd_cell or NO_VALUE, "ID": NO_VALUE}
    bind = cand.bind_status
    if bind == EvidenceBindStatus.BOUND and not all(e.geometry for e in evidence):
        bind = EvidenceBindStatus.PARTIAL
    return Suspicion(
        suspicion_id=1,
        discovery_method=DiscoveryMethod.SEMANTIC_DISSONANCE,
        confidence=cand.confidence,
        description=title_of(cand),
        pd_reference=refs.get("PD"),
        rd_reference=refs.get("RD"),
        review_priority=review_priority("MEDIUM", cand.confidence),
        normative_base="; ".join(r for r in _norm_refs(cand)) or NO_VALUE,
        suspicion_key=suspicion_key(inputs.object_id, fingerprint, FREE_RULE_CODE, subject),
        object_id=inputs.object_id,
        run_id=run_id,
        id_reference=refs.get("ID"),
        detector=FREE_DETECTOR,
        rule_code=FREE_RULE_CODE,
        rule_version=FREE_RULE_VERSION,
        subject_type="ROOM",
        subject_key=subject,
        expected_value=f"{noun} предусмотрен ПД ({rooms_ru(cand.rooms)})",
        actual_value=f"{noun} в РД отсутствует",
        stage_cells=cells,
        evidence=evidence,
        evidence_bind_status=bind,
        parameter_code=cand.parameter_code if cand.exported else None,
        finding_group_id=f"{inputs.object_id}-G-{cand.parameter_code}" if cand.exported else None,
        exported=cand.exported,
        not_exported_reasons=[] if cand.exported else list(cand.reasons),
        normative_refs=_norm_refs(cand),
        revision_fingerprint=fingerprint,
        supporting_methods=[DiscoveryMethod.GRAPHIC_DIFF]
        if cand.rd_anchor is not None and cand.rd_anchor.cloud_rooms
        else [],
        explanation={
            "family": cand.family.family,
            "absence": cand.absence,
            "rd_pages_read": cand.rd_read,
            "rd_pages_total": cand.rd_total,
            "confidence_terms": cand.confidence_terms,
            "present_rooms": cand.present_rooms,
            "assertion_sources": dict(cand.sources),
            "removal_statements": [
                {"file_id": r.file_id, "page": r.page_no, "quote": r.quote} for r in cand.removals[:3]
            ],
            "rationale": rationale_of(cand, inputs),
        },
    )


def _norm_refs(cand: FreeCandidate) -> list[str]:
    from inspector_hypothesis.free import recommendation

    rec = recommendation(cand)
    return list(rec.normative_refs or []) if rec is not None else []


def _join_refs(*refs: str | None, limit: int = 3) -> str | None:
    parts: list[str] = []
    for r in refs:
        for part in (r or "").split("; "):
            if part and part not in parts:
                parts.append(part)
    return "; ".join(parts[:limit]) + (f" и ещё {len(parts) - limit}" if len(parts) > limit else "") or None


def _merge(a: Suspicion, b: Suspicion) -> Suspicion:
    """One suspicion from two with the same key: the more confident one, with the evidence, references and
    revisions of both, and the merged subjects listed as copies."""
    best, other = (b, a) if b.confidence > a.confidence else (a, b)
    seen = {(e.stage, e.file_id, e.pdf_page_number) for e in best.evidence}
    extra = [e for e in other.evidence if (e.stage, e.file_id, e.pdf_page_number) not in seen]
    copies = list(dict.fromkeys([*best.explanation.get("copies", [best.subject_key]),
                                 *other.explanation.get("copies", [other.subject_key])]))  # fmt: skip
    fingerprint = hashlib.sha256(
        "|".join(sorted({best.revision_fingerprint, other.revision_fingerprint})).encode("utf-8")
    ).hexdigest()
    return best.model_copy(
        update={
            "evidence": best.evidence + extra,
            "pd_reference": _join_refs(best.pd_reference, other.pd_reference),
            "rd_reference": _join_refs(best.rd_reference, other.rd_reference),
            "id_reference": _join_refs(best.id_reference, other.id_reference),
            "revision_fingerprint": fingerprint,
            "explanation": {**best.explanation, "copies": copies},
        }
    )


def finalize(suspicions: Iterable[Suspicion]) -> list[Suspicion]:
    """Merge duplicates (same key: max confidence, union of evidence) and number them 1…n in protocol order:
    exported FREE groups first, then by priority, method and rule."""
    merged: dict[str, Suspicion] = {}
    for s in suspicions:
        cur = merged.get(s.suspicion_key)
        if cur is None:
            merged[s.suspicion_key] = s
            continue
        merged[s.suspicion_key] = _merge(cur, s)
    priority = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    ordered = sorted(
        merged.values(),
        key=lambda s: (
            not s.exported,
            s.parameter_code or "",
            priority[str(s.review_priority)],
            s.rule_code,
            s.subject_key,
        ),
    )
    return [s.model_copy(update={"suspicion_id": i}) for i, s in enumerate(ordered, 1)]


# ───────────────────────────────────────────── protocol rows ─────────────────────────────────────────────


def _method_ru(method: DiscoveryMethod | str) -> str:
    return load_enums()["DiscoveryMethod"].value(str(method)).label_ru or str(method)


def section6_rows(
    suspicions: Sequence[Suspicion], card_refs: Mapping[str, str] | int = 1
) -> list[SuspicionRow]:
    """Приложение 2 Раздел 6 «ПОДОЗРЕНИЯ ИИ»: | № | Метод | Описание | ПД | РД | ИД | Решение | Причина | Комментарий ИИ |.

    ``card_refs``: evidence-card number per suspicion_key («Б.4»), or the first card number to count from."""
    rows: list[SuspicionRow] = []
    for i, s in enumerate(suspicions, 1):
        card = f"Б.{card_refs + i - 1}" if isinstance(card_refs, int) else card_refs[s.suspicion_key]
        rows.append(
            SuspicionRow(
                no=i,
                method=s.discovery_method,
                method_ru=_method_ru(s.discovery_method),
                description=s.description,
                pd=s.stage_cells.get("PD", NO_VALUE),
                rd=s.stage_cells.get("RD", NO_VALUE),
                id=s.stage_cells.get("ID", NO_VALUE),
                parameter_code=s.parameter_code,
                inspector_status=s.inspector_status,
                inspector_decision_ru=DECISION_RU[str(s.inspector_status)],
                rejection_reason=NO_VALUE,
                ai_comment=NO_VALUE,
                confidence=s.confidence,
                card_ref=card,
                finding_group_id=s.finding_group_id,
            )
        )
    return rows


def a5_rows(suspicions: Sequence[Suspicion], card_refs: Mapping[str, str] | int = 1) -> list[HypothesisRow]:
    """Приложение А.5 «Гипотезы свободного поиска» (superset of Раздел 6: confidence, norm, binding status)."""
    rows: list[HypothesisRow] = []
    for i, s in enumerate(suspicions, 1):
        card = f"Б.{card_refs + i - 1}" if isinstance(card_refs, int) else card_refs[s.suspicion_key]
        rows.append(
            HypothesisRow(
                card_ref=card,
                finding_group_id=s.finding_group_id,
                parameter_code=s.parameter_code,
                method=s.discovery_method,
                description=s.description,
                confidence=s.confidence,
                normative_base=None if s.normative_base == NO_VALUE else s.normative_base,
                evidence_bind_status=s.evidence_bind_status,
                inspector_status=s.inspector_status,
            )
        )
    return rows


def stage_label(stage: str) -> str:
    return load_enums()["DocStage"].value(stage).label_ru or stage


@cache
def suspicion_schema() -> dict[str, Any]:
    """The proposed contract schema of a suspicion (``schemas/suspicion.proposed.schema.json``)."""
    text = (
        resources.files("inspector_hypothesis")
        .joinpath("schemas/suspicion.proposed.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


@cache
def _validator() -> Any:
    from jsonschema import Draft202012Validator

    from inspector_common.contracts.loader import registry

    return Draft202012Validator(suspicion_schema(), registry=registry())


def suspicion_schema_errors(suspicion: Suspicion | Mapping[str, Any]) -> list[str]:
    """JSON-Schema errors of one suspicion record against the proposed contract (empty = valid)."""
    doc = suspicion.dump() if isinstance(suspicion, Suspicion) else suspicion
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in _validator().iter_errors(doc)
    ]


__all__ = [
    "DECISION_RU",
    "Suspicion",
    "a5_rows",
    "finalize",
    "from_free_candidate",
    "from_rule_outcome",
    "reference",
    "section6_rows",
    "stage_label",
    "suspicion_schema",
    "suspicion_schema_errors",
]
