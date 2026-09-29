/**
 * Read models of the verification API (OpenAPI overlay `verification.openapi.yaml`): queue rows, the evidence
 * card with every ТЗ §9.2 п.4 field, contract-shaped decisions (decision.schema.json), disputes, protocol
 * version references, dataset items. Pure mapping from repository rows; no I/O.
 */
import type { FileRow } from '../../db/schema';
import type { CheckRow, EvidenceGroupRow, ProtocolRow } from '../import/import.schema';
import type { DecisionCodes } from './domain/codes';
import { cardOrdinal, defaultConfirmBasis, evidenceFingerprint } from './domain/rules';
import {
  type CardFacts,
  clarifyComment,
  confirmComment,
  locationPhrase,
  rejectComment,
  stageRu,
  suggestedFix,
} from './domain/templates';
import type { DatasetItemRow, DecisionRow, DisputeRow } from './verification.schema';

type Json = Record<string, unknown>;

export interface UserRef {
  user_id: string;
  full_name: string;
}

export type UserNames = ReadonlyMap<string, string>;

export function userRef(id: string | null | undefined, names: UserNames): UserRef | null {
  if (!id) return null;
  return { user_id: id, full_name: names.get(id) ?? id };
}

/** Axis A as the API shows it: the inspector's outcome when decided by an inspector, else the model's. */
export function effectiveFindingStatus(c: CheckRow): string | null {
  if (c.decidedBy === 'INSPECTOR' && (c.inspectorStatus === 'CONFIRMED_VIOLATION' || c.inspectorStatus === 'NEGATIVE_VERIFIED')) {
    return c.inspectorStatus;
  }
  const machine = (c.findingJson as Json | null)?.finding_status;
  return typeof machine === 'string' ? machine : c.findingStatus;
}

export function machineFindingStatus(c: CheckRow): string | null {
  const machine = (c.findingJson as Json | null)?.finding_status;
  return typeof machine === 'string' ? machine : c.findingStatus;
}

export interface ProtocolIndex {
  /** card_no → Protocol EvidenceCard */
  cards: Map<string, Json>;
  /** card_no → «Воздуховоды общеобменной вентиляции (IOS4-078)» */
  labels: Map<string, string>;
}

export function protocolIndex(content: Json | null | undefined): ProtocolIndex {
  const cards = new Map<string, Json>();
  const labels = new Map<string, string>();
  for (const card of ((content?.evidence_cards as Json[] | undefined) ?? [])) {
    const no = String(card.card_no ?? '');
    if (!no) continue;
    cards.set(no, card);
    if (typeof card.parameter_label === 'string') labels.set(no, card.parameter_label);
  }
  return { cards, labels };
}

export function parameterLabel(c: CheckRow, idx: ProtocolIndex): string {
  return (c.cardNo && idx.labels.get(c.cardNo)) || c.paramCode;
}

export interface QueueItemDto {
  finding_id: string;
  finding_group_id: string | null;
  card_no: string | null;
  param_code: string;
  parameter_label: string;
  location: string;
  location_type: string;
  matrix_scope: string;
  kind: string;
  criticality_level: string | null;
  protocol_status: string;
  risk_level: string | null;
  review_priority: string | null;
  confidence: number | null;
  inspector_status: string | null;
  finding_status: string | null;
  completeness_status: string | null;
  lifecycle_state: string;
  has_open_dispute: boolean;
  review_required_reason: string | null;
  decided_at: string | null;
  decided_by: UserRef | null;
  row_version: number;
}

export function queueItem(c: CheckRow, idx: ProtocolIndex, openDisputes: ReadonlySet<string>, names: UserNames): QueueItemDto {
  return {
    finding_id: c.findingId,
    finding_group_id: c.evidenceGroupId,
    card_no: c.cardNo,
    param_code: c.paramCode,
    parameter_label: parameterLabel(c, idx),
    location: c.location,
    location_type: c.locationType,
    matrix_scope: c.matrixScope,
    kind: c.kind,
    criticality_level: c.criticalityLevel,
    protocol_status: c.protocolStatus,
    risk_level: c.riskLevel,
    review_priority: c.reviewPriority,
    confidence: c.confidence,
    inspector_status: c.inspectorStatus,
    finding_status: effectiveFindingStatus(c),
    completeness_status: c.completenessStatus,
    lifecycle_state: c.lifecycleState,
    has_open_dispute: openDisputes.has(c.findingId),
    review_required_reason: c.reviewRequiredReason,
    decided_at: c.decidedAt ? c.decidedAt.toISOString() : null,
    decided_by: c.decidedBy === 'INSPECTOR' || c.inspectorStatus === 'CLARIFICATION_REQUIRED' ? userRef(c.decidedUserId, names) : null,
    row_version: c.rowVersion,
  };
}

export function protocolRef(p: ProtocolRow, names: UserNames): Json {
  return {
    protocol_id: p.id,
    version: p.version,
    protocol_no: p.protocolNo,
    status: p.status,
    is_final: p.isFinal,
    version_reason: p.versionReason,
    content_sha256: p.contentSha256,
    generated_at: p.generatedAt.toISOString(),
    finalized_at: p.finalizedAt ? p.finalizedAt.toISOString() : null,
    finalized_by: userRef(p.finalizedBy, names),
    superseded_at: p.supersededAt ? p.supersededAt.toISOString() : null,
    superseded_reason: p.supersededReason,
  };
}

/** Decision contract (decision.schema.json) of one stored decision. */
export function decisionContract(d: DecisionRow): Json {
  const out: Json = {
    decision_id: d.id,
    finding_id: d.findingId,
    finding_group_id: d.findingGroupId,
    object_id: d.objectId,
    run_id: d.runId,
    process_id: d.processId,
    protocol_version: d.protocolVersion,
    decision: d.decision,
    effective_status: d.effectiveStatus,
    reason_code: d.reasonCode,
    basis_code: d.basisCode,
    clarify_code: d.clarifyCode,
    comment: d.comment,
    comment_source: d.commentSource,
    approved_change_ref: d.approvedChangeRef,
    approved_change_file_id: d.approvedChangeFileId,
    approved_change_page: d.approvedChangePage,
    corrected_value: (d.correctedValue as string | number | boolean | null) ?? null,
    correct_file_id: d.correctFileId,
    correct_locus: d.correctLocus,
    duplicate_of: d.duplicateOf,
    na_basis: d.naBasis,
    justification: d.justification,
    planned_action: d.plannedAction,
    ai_verdict: d.aiVerdict,
    ai_confidence: d.aiConfidence,
    ai_comment: d.aiComment,
    system_comment: d.systemComment,
    gold_effect: d.goldEffect,
    evidence_fingerprint: d.seenFingerprint,
    override_of_decision_id: d.overrideOfDecisionId,
    decided_by: d.userId,
    decided_at: d.createdAt.toISOString(),
  };
  const role = d.userRole.split(',').find(Boolean);
  if (role) out.decided_role = role;
  return out;
}

export function historyItem(d: DecisionRow, names: UserNames): Json {
  return { decision: decisionContract(d), user: userRef(d.userId, names), ai_rule_ids: d.aiRuleIds, resolves_dispute_id: d.resolvesDisputeId };
}

export function disputeDto(d: DisputeRow, names: UserNames): Json {
  return {
    dispute_id: d.id,
    finding_id: d.findingId,
    violation_id: d.violationId,
    decision_id: d.decisionId,
    resolution_status: d.resolutionStatus,
    rejection_reason: d.rejectionReason,
    inspector_comment: d.inspectorComment,
    ai_comment: d.aiComment,
    ai_rule_ids: d.aiRuleIds,
    created_at: d.createdAt.toISOString(),
    resolved_at: d.resolvedAt ? d.resolvedAt.toISOString() : null,
    resolved_by: userRef(d.resolvedBy, names),
    resolution_comment: d.resolutionComment,
    resolution_decision_id: d.resolutionDecisionId,
    row_version: d.rowVersion,
  };
}

export function datasetItemDto(r: DatasetItemRow, names: UserNames, codes: DecisionCodes): Json {
  const enumName = r.goldLabel === 'POSITIVE' ? 'DecisionConfirmBasis' : 'DecisionRejectReason';
  return {
    item_id: r.id,
    status: r.status,
    gold_label: r.goldLabel,
    split: r.split,
    dataset_version: r.datasetVersion,
    evidence_group_id: r.evidenceGroupId,
    object_id: r.objectId,
    object_group_id: r.objectGroupId,
    process_id: r.processId,
    protocol_id: r.protocolId,
    protocol_version: r.protocolVersion,
    finding_id: r.findingId,
    decision_id: r.decisionId,
    expert: userRef(r.expertId, names),
    reason_code: r.reasonCode,
    reason_ru: r.reasonCode ? codes.label(enumName, r.reasonCode) : null,
    source_type: r.sourceType,
    training_eligible: r.trainingEligible,
    gold_record: r.goldRecord,
    evidence_card: r.evidenceCard,
    versions: r.versions,
    decided_at: r.decidedAt.toISOString(),
    created_at: r.createdAt.toISOString(),
  };
}

interface EvidenceRefJson {
  stage: string;
  file_id: string;
  pdf_page_number: number;
  document_sheet_number?: string | number | null;
  file_sha256?: string | null;
  role?: string | null;
  is_anchor?: boolean;
  geometry?: { boxes?: number[][]; polygons?: number[][][] } | null;
  geometry_space?: string | null;
  localization?: string | null;
  document_code?: string | null;
  revision?: string | null;
  note?: string | null;
}

export interface CardSourceDto {
  role: string | null;
  stage: string;
  stage_ru: string;
  file_id: string;
  file_name: string | null;
  file_sha256: string | null;
  document_code: string | null;
  revision: string | null;
  approval_status: string | null;
  pdf_page_number: number;
  sheet_number: string | null;
  geometry: Json | null;
  geometry_space: string | null;
  localization: string | null;
  is_anchor: boolean;
  location_page: boolean;
}

function findingEvidence(c: CheckRow): EvidenceRefJson[] {
  return (((c.findingJson as Json | null)?.evidence as EvidenceRefJson[] | undefined) ?? []).filter((e) => e && e.file_id);
}

/** Pages of this location drawn apart from the anchor page (group `location_pages`, e.g. room 314 on p20). */
function locationPages(c: CheckRow, group: EvidenceGroupRow | null): EvidenceRefJson[] {
  const pages = ((group?.groupJson as Json | undefined)?.location_pages as Record<string, EvidenceRefJson[]> | undefined) ?? {};
  return pages[c.location] ?? [];
}

function sourceDto(e: EvidenceRefJson, card: Json | undefined, files: ReadonlyMap<string, FileRow>, locationPage: boolean): CardSourceDto {
  const cardSource = ((card?.sources as Json[] | undefined) ?? []).find((s) => s.file_id === e.file_id) as Json | undefined;
  const file = files.get(e.file_id);
  const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
  const role = e.role ?? (locationPage ? (e.stage === 'PD' ? 'SUPPORTING_EXPECTED' : 'SUPPORTING_ACTUAL') : e.stage === 'PD' ? 'EXPECTED' : 'ACTUAL');
  return {
    role,
    stage: e.stage,
    stage_ru: stageRu(e.stage),
    file_id: e.file_id,
    file_name: str(cardSource?.file_name) ?? file?.fileName ?? null,
    file_sha256: e.file_sha256 ?? str(cardSource?.file_sha256) ?? file?.fileHash ?? null,
    document_code: e.document_code ?? str(cardSource?.document_code) ?? file?.documentCode ?? null,
    revision: e.revision ?? str(cardSource?.revision) ?? file?.revision ?? null,
    approval_status: str(cardSource?.approval_status) ?? file?.approvalStatus ?? null,
    pdf_page_number: e.pdf_page_number,
    sheet_number: e.document_sheet_number === undefined || e.document_sheet_number === null ? null : String(e.document_sheet_number),
    geometry: (e.geometry as Json | null | undefined) ?? null,
    geometry_space: e.geometry_space ?? null,
    localization: e.localization ?? null,
    is_anchor: Boolean(e.is_anchor),
    location_page: locationPage,
  };
}

export function cardSources(c: CheckRow, group: EvidenceGroupRow | null, card: Json | undefined, files: ReadonlyMap<string, FileRow>): CardSourceDto[] {
  const own = findingEvidence(c).map((e) => sourceDto(e, card, files, false));
  const seen = new Set(own.map((s) => `${s.file_id}#${s.pdf_page_number}`));
  const extra = locationPages(c, group)
    .map((e) => sourceDto(e, card, files, true))
    .filter((s) => !seen.has(`${s.file_id}#${s.pdf_page_number}`));
  return [...own, ...extra];
}

export function cardFacts(c: CheckRow, idx: ProtocolIndex, sources: CardSourceDto[]): CardFacts {
  const primary = sources.filter((s) => !s.location_page);
  const expected = primary.find((s) => s.role === 'EXPECTED') ?? primary.find((s) => s.stage === 'PD') ?? null;
  const actual = primary.find((s) => s.role === 'ACTUAL') ?? primary.find((s) => s.stage !== 'PD') ?? null;
  return {
    paramCode: c.paramCode,
    parameterLabel: parameterLabel(c, idx),
    location: c.location,
    locationType: c.locationType,
    expected: c.expectedValue,
    actual: c.actualValue,
    expectedSource: expected,
    actualSource: actual,
  };
}

export interface FieldCheck {
  key: string;
  label_ru: string;
  present: boolean;
  partial: boolean;
}

/** ТЗ §9.2 п.4 mandatory card fields (VER-06): what this card actually carries. */
export function fieldChecklist(c: CheckRow, sources: CardSourceDto[], hasRationale: boolean): FieldCheck[] {
  const all = (pred: (s: CardSourceDto) => boolean) => sources.length > 0 && sources.every(pred);
  const some = (pred: (s: CardSourceDto) => boolean) => sources.some(pred);
  const f = (key: string, label: string, full: boolean, partial = false): FieldCheck => ({ key, label_ru: label, present: full, partial: !full && partial });
  const decided = c.inspectorStatus !== null && c.inspectorStatus !== 'PENDING';
  return [
    f('finding_id', 'Идентификатор находки (finding_id)', Boolean(c.findingId)),
    f('parameter', 'Код параметра / правила', Boolean(c.paramCode)),
    f('expected_actual', 'Ожидаемое и фактическое значения', c.expectedValue !== null && c.actualValue !== null, c.expectedValue !== null || c.actualValue !== null),
    f('file_sha256', 'file_id и SHA-256 каждого источника', all((s) => Boolean(s.file_sha256)), some((s) => Boolean(s.file_sha256))),
    f('stage', 'Стадия', all((s) => Boolean(s.stage))),
    f('document_code', 'Шифр', all((s) => Boolean(s.document_code)), some((s) => Boolean(s.document_code))),
    f('revision', 'Редакция', all((s) => Boolean(s.revision)), some((s) => Boolean(s.revision))),
    f('approval_status', 'Статус утверждения', all((s) => Boolean(s.approval_status)), some((s) => Boolean(s.approval_status))),
    f('sheet_page', 'Лист / страница', all((s) => s.sheet_number !== null && s.pdf_page_number > 0), some((s) => s.pdf_page_number > 0)),
    f('geometry', 'bbox / polygon', all((s) => ((s.geometry?.boxes as unknown[] | undefined)?.length ?? 0) + ((s.geometry?.polygons as unknown[] | undefined)?.length ?? 0) > 0), some((s) => Boolean(s.geometry))),
    f('rationale', 'Обоснование', hasRationale),
    f('risk_level', 'Уровень риска', Boolean(c.riskLevel)),
    f('decision', 'Решение инспектора и причина решения', decided && Boolean(c.decisionComment)),
  ];
}

/** The EvidenceCard (protocol contract) of one atomic finding, for AG-08's EvidenceViewer ({card, group}). */
export function viewerCard(c: CheckRow, card: Json | undefined, sources: CardSourceDto[], idx: ProtocolIndex): Json {
  const base: Json = card ? structuredClone(card) : { card_no: c.cardNo ?? 'Б.1' };
  return {
    ...base,
    card_no: base.card_no ?? c.cardNo,
    finding_group_id: c.evidenceGroupId,
    finding_ids: [c.findingId],
    parameter_code: c.paramCode,
    parameter_label: parameterLabel(c, idx),
    locations: [c.location],
    expected_value: c.expectedValue,
    actual_value: c.actualValue,
    sources: sources
      .filter((s) => !s.location_page)
      .map((s) => ({
        role: s.role,
        stage: s.stage,
        file_id: s.file_id,
        file_name: s.file_name,
        file_sha256: s.file_sha256,
        document_code: s.document_code,
        revision: s.revision,
        approval_status: s.approval_status,
        pdf_page_number: s.pdf_page_number,
        sheet_number: s.sheet_number,
        geometry: s.geometry,
        geometry_space: s.geometry_space,
      })),
    inspector: { status: c.inspectorStatus ?? 'PENDING' },
  };
}

/** The FindingGroup narrowed to this location (so the viewer offers only this room and its extra pages). */
export function viewerGroup(c: CheckRow, group: EvidenceGroupRow | null): Json | null {
  if (!group) return null;
  const g = structuredClone(group.groupJson) as Json;
  const pages = (g.location_pages as Record<string, unknown> | undefined) ?? {};
  g.location_pages = c.location in pages ? { [c.location]: pages[c.location] } : {};
  // One candidate = one location: the viewer must not offer the group's other rooms (their boxes belong to other candidates).
  g.locations = [c.location];
  return g;
}

export function prefill(c: CheckRow, facts: CardFacts, codes: DecisionCodes): Json {
  const reject: Record<string, string> = {};
  for (const r of codes.reject) reject[r.code] = rejectComment(r.code, facts);
  const clarify: Record<string, string> = {};
  for (const r of codes.clarify) clarify[r.code] = clarifyComment(r.label_ru, facts);
  const fix: Record<string, string> = {};
  for (const r of codes.reject) fix[r.code] = suggestedFix(r.code, c.paramCode);
  return {
    confirm_basis_code: defaultConfirmBasis({ axis: c.axis, comparisonResult: c.comparisonResult, matrixScope: c.matrixScope }),
    confirm_comment: confirmComment(facts),
    reject_comments: reject,
    clarify_comments: clarify,
    suggested_fixes: fix,
  };
}

export function locationText(c: CheckRow): string {
  return locationPhrase(c.locationType, c.location);
}

export function fingerprintOf(c: CheckRow, group: EvidenceGroupRow | null): string {
  return evidenceFingerprint(c.findingSha256, group?.groupSha256 ?? null);
}

export function sortByCard<T extends { card_no: string | null }>(items: T[]): T[] {
  return [...items].sort((a, b) => cardOrdinal(a.card_no) - cardOrdinal(b.card_no));
}
