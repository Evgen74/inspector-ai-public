/**
 * Verification service (ТЗ Module 3, §9.3; 05; 90 §3.2.2–3.2.4). Owner AG-05.
 *
 * Every write runs in one transaction: process row locked (FOR SHARE for decisions, FOR UPDATE for
 * finalize/unfinalize/claim/reopen), finding row locked FOR UPDATE and updated only while its row_version equals
 * If-Match, the append-only decision row, Rejection_Log / Dispute_Log rows, automatic process transitions, and the
 * domain audit rows (AuditService.record with the transaction as executor). Idempotency-Key: the first successful
 * response is stored per (user, key) and replayed; the same key with another body → IDEMPOTENCY_KEY_REUSED.
 *
 * Invariants (05 §3.20): I1 CONFIRMED_VIOLATION only through an inspector decision; I2 no PARTIALLY_CONFIRMED;
 * I3 decisions append-only; I4 nothing changes after finalization; I5 counts over ACTIVE rows only; I6 the РиН
 * payload holds CONFIRMED only; I7 GOLD drafts only from final inspector CONFIRMED/NEGATIVE; I9 seen fingerprint
 * = current fingerprint; I10 un-finalize with a reason; I11 audit in the same transaction;
 * I12 risk level orders the queue and never changes a status. Decisions never reach a submission (97 §1.4).
 */
import { Inject, Injectable } from '@nestjs/common';
import { canonicalJson, sha256Hex } from '../../common/hashing';
import { uuidv7 } from '../../common/ids';
import { ApiProblem, type ProblemItem } from '../../common/problem';
import type { PermissionScope, Principal } from '../../common/request-context';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { ContractSchemas, summarizeAjvErrors } from '../../contracts/contracts';
import type { FileRow } from '../../db/schema';
import { AuditService } from '../audit/audit.service';
import { AuthService } from '../auth/auth.service';
import { UsersRepository } from '../auth/users.repository';
import type { CheckRow, EvidenceGroupRow, ProcessRow, ProtocolRow } from '../import/import.schema';
import { sha256OfJson } from '../import/import-plan';
import { DecisionCodes } from './domain/codes';
import { datasetSplit, goldLabelOf, goldRecord } from './domain/gold';
import {
  checkDecisionBody,
  compareQueue,
  computeGate,
  COMMENT_MAX,
  type DecisionBody,
  type DecisionType,
  defaultConfirmBasis,
  effectOf,
  isReviewable,
  nextPending,
  nextProcessStatus,
  type RuleViolation,
  transitionAllowed,
  UNDO_WINDOW_MS,
  UNFINALIZE_MIN_REASON,
  workingProtocolStatus,
} from './domain/rules';
import { applyDecisions, partialGroupProgress, type GroupProgress, type SnapshotDecision } from './domain/snapshot';
import {
  aiComment,
  clarifyComment,
  confirmComment,
  disputeComment,
  STATUS_LINE,
  suggestedFix,
  SYSTEM_COMMENT_REVERTED,
  systemCommentClarification,
  systemCommentConfirmed,
  systemCommentRejected,
} from './domain/templates';
import { usabilityReport } from './domain/usability';
import { type ValidatorResult, validateRejection } from './domain/validator';
import { type ObjectInfo, VerificationRepository, type VerificationTx } from './verification.repository';
import type { DecisionRow, DisputeRow, IdempotencyRow, NewDecisionRow } from './verification.schema';
import {
  cardFacts,
  cardSources,
  datasetItemDto,
  decisionContract,
  effectiveFindingStatus,
  disputeDto,
  fieldChecklist,
  fingerprintOf,
  historyItem,
  locationText,
  machineFindingStatus,
  prefill,
  protocolIndex,
  protocolRef,
  queueItem,
  type UserNames,
  viewerCard,
  viewerGroup,
} from './verification.views';

type Json = Record<string, unknown>;

/** Who is calling (from the request context). */
export interface Actor {
  principal: Principal | null;
  scope: PermissionScope | null;
  ip: string | null;
  userAgent: string | null;
  requestId: string | null;
}

export interface WriteMeta {
  ifMatch: string | undefined;
  idempotencyKey: string;
}

export interface WriteResult {
  status: number;
  body: Json;
  etag: string | null;
  replayed: boolean;
}

export const QUEUE_TABS = ['ALL', 'PENDING', 'CLARIFICATION', 'CONFIRMED', 'NEGATIVE', 'DISPUTES'] as const;
export type QueueTab = (typeof QUEUE_TABS)[number];

const DISPUTE_RESOLUTIONS = ['INSPECTOR_UPHELD', 'AI_UPHELD', 'KEPT_CLARIFICATION'] as const;

/** The resolution a new decision implies for an OPEN dispute on the same finding (05 §3.7). */
const RESOLUTION_BY_DECISION: Record<DecisionType, string> = {
  CONFIRMED_VIOLATION: 'AI_UPHELD',
  NEGATIVE_VERIFIED: 'INSPECTOR_UPHELD',
  CLARIFICATION_REQUIRED: 'KEPT_CLARIFICATION',
  REVERT_TO_PENDING: 'WITHDRAWN',
};

const AUDIT_BY_DECISION: Record<DecisionType, string> = {
  CONFIRMED_VIOLATION: 'FINDING_CONFIRMED',
  NEGATIVE_VERIFIED: 'FINDING_REJECTED',
  CLARIFICATION_REQUIRED: 'FINDING_CLARIFICATION_REQUESTED',
  REVERT_TO_PENDING: 'FINDING_DECISION_REVERTED',
};

/** Default basis when the inspector keeps a disputed rejection in clarification (05 §3.7 «Оставить на уточнении»). */
const KEEP_CLARIFY_BY_REASON: Record<string, string> = {
  APPROVED_CHANGE: 'AWAITING_APPROVAL_CHECK',
  WRONG_REVISION: 'REVISION_CONFLICT',
  OCR_ERROR: 'SOURCE_UNREADABLE',
};

class ReplayRace extends Error {}

/** `"3"`, `W/"3"` or `3` → 3; anything else → NaN. */
export function parseIfMatch(value: string | undefined): number {
  if (!value) return Number.NaN;
  const m = /^\s*(?:W\/)?"?(\d+)"?\s*$/.exec(value);
  return m ? Number(m[1]) : Number.NaN;
}

export function etagOf(rowVersion: number): string {
  return `"${rowVersion}"`;
}

/** Response of claim / reopen: the process after the transition (the client refetches the summary). */
function transitionDto(p: ProcessRow): Json {
  return {
    process_id: p.id,
    status: p.status,
    verification_status: workingProtocolStatus(p.status),
    row_version: p.rowVersion,
    assigned_inspector_id: p.assignedInspectorId,
    verification_started_at: p.verificationStartedAt?.toISOString() ?? null,
  };
}

function timeRu(d: Date): string {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(d);
}

function isUniqueViolation(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { code?: string }).code === '23505';
}

/** PostgreSQL deadlock_detected / serialization_failure: the transaction is safe to run once more. */
function isRetryable(err: unknown): boolean {
  const code = typeof err === 'object' && err !== null ? (err as { code?: string }).code : undefined;
  return code === '40P01' || code === '40001';
}

/** The protocol's own object name beats the registry label (same rule as the dashboard); uploaded sets keep the typed name. */
function displayObjectName(object: ObjectInfo, protocolContent: unknown): string | null {
  if (object.id.startsWith('OBJ-UPLOAD-') && object.name) return object.name;
  const name = ((protocolContent as Json | undefined)?.object as Json | undefined)?.name;
  return typeof name === 'string' && name.trim() ? name.trim() : object.name;
}

@Injectable()
export class VerificationService {
  readonly codes: DecisionCodes;

  constructor(
    @Inject(APP_CONFIG) config: AppConfig,
    private readonly repo: VerificationRepository,
    private readonly audit: AuditService,
    private readonly users: UsersRepository,
    private readonly auth: AuthService,
    private readonly schemas: ContractSchemas,
  ) {
    this.codes = DecisionCodes.load(config.contractsDir);
  }

  // ───────────────────────────── access ─────────────────────────────

  private async process(processId: string, actor: Actor): Promise<{ process: ProcessRow; object: ObjectInfo }> {
    const process = await this.repo.getProcess(processId);
    if (!process) throw new ApiProblem('PROCESS_NOT_FOUND');
    const object = (await this.repo.getObject(process.objectId)) ?? {
      id: process.objectId,
      name: null,
      address: null,
      split: null,
      objectGroupId: null,
    };
    // Hidden-test integrity (CLAUDE.md rule 4): its findings and decisions are never shown or taken.
    if (object.split === 'TEST_HIDDEN') throw new ApiProblem('HIDDEN_TEST_ACCESS_DENIED', { object_id: object.id });
    if (actor.scope === 'ASSIGNED' && actor.principal && !(await this.users.isAssigned(actor.principal.userId, object.id))) {
      throw new ApiProblem('PROCESS_NOT_FOUND');
    }
    return { process, object };
  }

  private writer(actor: Actor): Principal {
    if (!actor.principal) throw new ApiProblem('UNAUTHENTICATED');
    return actor.principal;
  }

  private can(actor: Actor, permission: string): boolean {
    return Boolean(actor.principal?.permissions.get(permission));
  }

  private async names(ids: Array<string | null | undefined>, actor?: Actor): Promise<Map<string, string>> {
    const out = new Map<string, string>();
    if (actor?.principal) out.set(actor.principal.userId, actor.principal.fullName);
    for (const id of new Set(ids.filter((x): x is string => Boolean(x)))) {
      if (out.has(id)) continue;
      const user = await this.users.findById(id);
      if (user) out.set(id, user.fullName);
    }
    return out;
  }

  // ───────────────────────────── reads ─────────────────────────────

  async objectVerification(objectId: string, actor: Actor): Promise<Json> {
    const object = await this.repo.getObject(objectId);
    if (!object) throw new ApiProblem('NOT_FOUND');
    if (object.split === 'TEST_HIDDEN') throw new ApiProblem('HIDDEN_TEST_ACCESS_DENIED', { object_id: objectId });
    const processes = await this.repo.processesOfObject(objectId);
    const items: Json[] = [];
    for (const p of processes) items.push(await this.buildSummary(p, object, actor));
    const named = items.map((i) => (i.object as Json | undefined)?.name).find((n): n is string => typeof n === 'string' && n.length > 0);
    return { object_id: object.id, object_name: named ?? object.name, processes: items };
  }

  async summary(processId: string, actor: Actor): Promise<{ body: Json; etag: string }> {
    const { process, object } = await this.process(processId, actor);
    return { body: await this.buildSummary(process, object, actor), etag: etagOf(process.rowVersion) };
  }

  private async buildSummary(process: ProcessRow, object: ObjectInfo, actor: Actor): Promise<Json> {
    const [checks, disputes, suspicions, protocols, items] = await Promise.all([
      this.repo.checksOf(process.id),
      this.repo.disputesOf(process.id),
      this.repo.suspicionsOf(process.id),
      this.repo.protocolsOf(process.id),
      this.repo.datasetItems({ processId: process.id }),
    ]);
    const reviewable = checks.filter(isReviewable);
    const nonReviewable = checks.filter((c) => c.lifecycleState === 'ACTIVE' && !isReviewable(c));
    const open = disputes.filter((d) => d.resolutionStatus === 'OPEN');
    const pending = reviewable.filter((c) => c.inspectorStatus === 'PENDING').length;
    const status = process.status === 'READY' && pending === 0 && open.length === 0 && reviewable.length === 0 ? 'COMPLETED' : process.status;
    const gate = computeGate({
      processStatus: status,
      reviewable: reviewable.map((c) => ({ findingId: c.findingId, inspectorStatus: c.inspectorStatus })),
      openDisputeFindingIds: open.map((d) => d.findingId),
      nonReviewable: nonReviewable.map((c) => ({ findingId: c.findingId, protocolStatus: c.protocolStatus, violationLabel: c.violationLabel })),
      pendingSuspicionKeys: suspicions.filter((s) => s.inspectorStatus === 'PENDING' || s.inspectorStatus === 'CLARIFICATION_REQUIRED').map((s) => s.suspicionKey),
    });
    const current = protocols.find((p) => p.id === process.currentProtocolId) ?? protocols.at(-1) ?? null;
    const names = await this.names([process.assignedInspectorId, ...protocols.map((p) => p.finalizedBy)], actor);
    const ordered = [...reviewable].sort((a, b) => compareQueue(a, b));
    const count = (s: string) => reviewable.filter((c) => c.inspectorStatus === s).length;
    const canDecide = this.can(actor, 'finding.decide');
    return {
      process_id: process.id,
      object: { object_id: object.id, name: displayObjectName(object, current?.contentJson), address: object.address },
      run: { run_id: process.activeRunId, batch_run_id: process.batchRunId },
      status: process.status,
      verification_status: current?.status ?? workingProtocolStatus(process.status),
      status_line: STATUS_LINE[process.status] ?? process.status,
      row_version: process.rowVersion,
      scenario: process.scenario,
      scenario_ru: process.scenario ? this.codes.label('LoadScenario', process.scenario) : null,
      upload_status: (process.uploadStatus as Json | null) ?? null,
      versions: {
        matrix_version: current?.matrixVersion ?? process.matrixVersion,
        pipeline_version: current?.pipelineVersion ?? process.pipelineVersion,
        dataset_version: current?.datasetVersion ?? null,
        model_version: current?.modelVersion ?? null,
        input_manifest_hash: current?.inputManifestHash ?? process.inputManifestHash,
      },
      protocol: current ? protocolRef(current, names) : null,
      protocol_versions: protocols.map((p) => protocolRef(p, names)),
      counts: {
        reviewable: reviewable.length,
        pending,
        confirmed: count('CONFIRMED_VIOLATION'),
        negative: count('NEGATIVE_VERIFIED'),
        clarification: count('CLARIFICATION_REQUIRED'),
        disputes_open: open.length,
        non_reviewable: nonReviewable.length,
        missing_document: nonReviewable.filter((c) => c.violationLabel === 'MISSING_DOCUMENT').length,
        comparison_impossible: nonReviewable.filter((c) => c.violationLabel === 'COMPARISON_IMPOSSIBLE').length,
        suspicions_pending: gate.warnings.find((w) => w.code === 'PENDING_SUSPICIONS')?.count ?? 0,
        dataset_items: items.filter((i) => i.status === 'DRAFT').length,
      },
      gate,
      capabilities: {
        can_decide: canDecide && (process.status === 'READY' || process.status === 'VERIFYING'),
        can_claim: canDecide && process.status === 'READY',
        can_reopen: canDecide && process.status === 'COMPLETED',
        can_finalize: this.can(actor, 'protocol.finalize') && gate.can_finalize,
        can_unfinalize: this.can(actor, 'protocol.unfinalize') && process.status === 'FINALIZED',
      },
      assigned_inspector: process.assignedInspectorId
        ? { user_id: process.assignedInspectorId, full_name: names.get(process.assignedInspectorId) ?? process.assignedInspectorId }
        : null,
      verification_started_at: process.verificationStartedAt?.toISOString() ?? null,
      completed_at: process.completedAt?.toISOString() ?? null,
      finalized_at: process.finalizedAt?.toISOString() ?? null,
      next_finding_id: nextPending(ordered, null),
    };
  }

  async queue(processId: string, tab: QueueTab, actor: Actor): Promise<Json> {
    const { process } = await this.process(processId, actor);
    const [checks, disputes, current] = await Promise.all([
      this.repo.checksOf(process.id),
      this.repo.disputesOf(process.id),
      process.currentProtocolId ? this.repo.getProtocol(process.currentProtocolId) : Promise.resolve(null),
    ]);
    const idx = protocolIndex(current?.contentJson as Json | undefined);
    const open = new Set(disputes.filter((d) => d.resolutionStatus === 'OPEN').map((d) => d.findingId));
    const ordered = checks.filter(isReviewable).sort((a, b) => compareQueue(a, b));
    const names = await this.names(ordered.map((c) => c.decidedUserId), actor);
    const all = ordered.map((c, i) => ({ ...queueItem(c, idx, open, names), position: i + 1 }));
    const filters: Record<QueueTab, (x: (typeof all)[number]) => boolean> = {
      ALL: () => true,
      PENDING: (x) => x.inspector_status === 'PENDING',
      CLARIFICATION: (x) => x.inspector_status === 'CLARIFICATION_REQUIRED',
      CONFIRMED: (x) => x.inspector_status === 'CONFIRMED_VIOLATION',
      NEGATIVE: (x) => x.inspector_status === 'NEGATIVE_VERIFIED',
      DISPUTES: (x) => x.has_open_dispute,
    };
    const counts: Record<string, number> = {};
    for (const t of QUEUE_TABS) counts[t] = all.filter(filters[t]).length;
    return { process_id: process.id, tab, total: all.length, counts, items: all.filter(filters[tab]) };
  }

  private async cardContext(process: ProcessRow, findingId: string) {
    const [checks, groups, current] = await Promise.all([
      this.repo.checksOf(process.id),
      this.repo.groupsOf(process.id),
      process.currentProtocolId ? this.repo.getProtocol(process.currentProtocolId) : Promise.resolve(null),
    ]);
    const check = checks.find((c) => c.findingId === findingId);
    if (!check) throw new ApiProblem('NOT_FOUND');
    const group = groups.find((g) => g.evidenceGroupId === check.evidenceGroupId) ?? null;
    const idx = protocolIndex(current?.contentJson as Json | undefined);
    const card = check.cardNo ? idx.cards.get(check.cardNo) : undefined;
    const refs = [
      ...(((check.findingJson as Json).evidence as Array<{ file_id: string }> | undefined) ?? []),
      ...Object.values(((group?.groupJson as Json | undefined)?.location_pages as Record<string, Array<{ file_id: string }>> | undefined) ?? {}).flat(),
    ];
    const files = new Map((await this.repo.files(refs.map((r) => r.file_id))).map((f) => [f.id, f] as [string, FileRow]));
    const sources = cardSources(check, group, card, files);
    return { checks, check, group, current, idx, card, sources, files };
  }

  async card(processId: string, findingId: string, actor: Actor): Promise<{ body: Json; etag: string }> {
    const { process, object } = await this.process(processId, actor);
    const { checks, check, group, current, idx, card, sources } = await this.cardContext(process, findingId);
    const [decisions, disputes] = await Promise.all([this.repo.decisionsOf(process.id, findingId), this.repo.disputesOf(process.id)]);
    const own = disputes.filter((d) => d.findingId === findingId);
    const names = await this.names([check.decidedUserId, ...decisions.map((d) => d.userId), ...own.map((d) => d.resolvedBy)], actor);
    const facts = cardFacts(check, idx, sources);
    const ordered = checks.filter(isReviewable).sort((a, b) => compareQueue(a, b));
    const pos = ordered.findIndex((c) => c.findingId === findingId);
    const currentDecision = decisions.find((d) => d.id === check.currentDecisionId) ?? null;
    const rationale = check.rationale ?? (typeof card?.rationale === 'string' ? card.rationale : null);
    const openDispute = own.find((d) => d.resolutionStatus === 'OPEN') ?? null;
    const body: Json = {
      process_id: process.id,
      object_id: object.id,
      finding_id: check.findingId,
      finding_group_id: check.evidenceGroupId,
      card_no: check.cardNo,
      row_version: check.rowVersion,
      evidence_fingerprint: fingerprintOf(check, group),
      param: {
        code: check.paramCode,
        id: check.paramId,
        label: facts.parameterLabel,
        rule_code: check.ruleCode,
        rule_version: check.ruleVersion ?? (typeof card?.rule_version === 'string' ? card.rule_version : null),
        matrix_scope: check.matrixScope,
        parameter_mapping_status: check.parameterMappingStatus,
        alt_param_codes: check.altParamCodes,
        element_noun: check.elementNoun,
      },
      kind: check.kind,
      location: check.location,
      location_type: check.locationType,
      location_text: locationText(check),
      values: {
        expected: check.expectedValue,
        actual: check.actualValue,
        pd: check.pdValue,
        rd: check.rdValue,
        id: check.idValue,
        axis: check.axis,
        comparison_result: check.comparisonResult,
        comparison_result_ru: check.comparisonResult ? this.codes.label('ComparisonResult', check.comparisonResult) : null,
        discrepancy_type: check.discrepancyType,
        delta: (check.delta as Json | null) ?? null,
      },
      criticality: check.criticality,
      criticality_level: check.criticalityLevel,
      protocol_status: check.protocolStatus,
      violation_label: check.violationLabel,
      risk_level: check.riskLevel,
      review_priority: check.reviewPriority,
      confidence: check.confidence,
      risk_note: 'Уровень риска определяет только очерёдность проверки и не является основанием для предписания (п. 9.2 ТЗ).',
      rationale,
      recommendation: (check.recommendation as Json | null) ?? null,
      statuses: {
        finding_status: effectiveFindingStatus(check),
        machine_finding_status: machineFindingStatus(check),
        completeness_status: check.completenessStatus,
        inspector_status: check.inspectorStatus,
        lifecycle_state: check.lifecycleState,
        decided_by: check.decidedBy,
        review_required_reason: check.reviewRequiredReason,
      },
      approved_change_ref: typeof card?.approved_change_ref === 'string' ? card.approved_change_ref : 'NONE',
      sources,
      inspector: {
        status: check.inspectorStatus,
        reason_code: check.decisionReasonCode,
        basis_code: check.decisionBasisCode,
        clarify_code: currentDecision?.clarifyCode ?? null,
        comment: check.decisionComment,
        decided_at: check.decidedAt?.toISOString() ?? null,
        user: check.decidedUserId ? { user_id: check.decidedUserId, full_name: names.get(check.decidedUserId) ?? check.decidedUserId } : null,
        decision_id: check.currentDecisionId,
        ai_verdict: currentDecision?.aiVerdict ?? null,
        ai_comment: currentDecision?.aiComment ?? null,
        system_comment: currentDecision?.systemComment ?? null,
      },
      ai_suggestion: {
        action: 'CONFIRM',
        basis_code: defaultConfirmBasis({ axis: check.axis, comparisonResult: check.comparisonResult, matrixScope: check.matrixScope }),
        confidence: check.confidence,
        explanation: rationale,
      },
      prefill: prefill(check, facts, this.codes),
      history: decisions.map((d) => historyItem(d, names)),
      disputes: own.map((d) => disputeDto(d, names)),
      open_dispute: openDispute ? disputeDto(openDispute, names) : null,
      process: {
        status: process.status,
        verification_status: current?.status ?? workingProtocolStatus(process.status),
        status_line: STATUS_LINE[process.status] ?? process.status,
        scenario: process.scenario,
        scenario_ru: process.scenario ? this.codes.label('LoadScenario', process.scenario) : null,
        upload_status: (process.uploadStatus as Json | null) ?? null,
        row_version: process.rowVersion,
      },
      field_checklist: fieldChecklist(check, sources, Boolean(rationale)),
      navigation: {
        position: pos + 1,
        total: ordered.length,
        prev_finding_id: pos > 0 ? ordered[pos - 1]!.findingId : null,
        next_finding_id: pos >= 0 && pos < ordered.length - 1 ? ordered[pos + 1]!.findingId : null,
        next_pending_finding_id: nextPending(ordered, findingId),
      },
      evidence_card: viewerCard(check, card, sources, idx),
      finding_group: viewerGroup(check, group),
    };
    return { body, etag: etagOf(check.rowVersion) };
  }

  async history(processId: string, findingId: string, actor: Actor): Promise<Json> {
    const { process } = await this.process(processId, actor);
    const checks = await this.repo.checksOf(process.id);
    if (!checks.some((c) => c.findingId === findingId)) throw new ApiProblem('NOT_FOUND');
    const [decisions, disputes] = await Promise.all([this.repo.decisionsOf(process.id, findingId), this.repo.disputesOf(process.id)]);
    const own = disputes.filter((d) => d.findingId === findingId);
    const names = await this.names([...decisions.map((d) => d.userId), ...own.map((d) => d.resolvedBy)], actor);
    return { finding_id: findingId, decisions: decisions.map((d) => historyItem(d, names)), disputes: own.map((d) => disputeDto(d, names)) };
  }

  async disputes(processId: string, actor: Actor): Promise<Json> {
    const { process } = await this.process(processId, actor);
    const disputes = await this.repo.disputesOf(process.id);
    const names = await this.names(disputes.map((d) => d.resolvedBy), actor);
    return { process_id: process.id, items: disputes.map((d) => disputeDto(d, names)) };
  }

  async completeness(processId: string, actor: Actor): Promise<Json> {
    const { process } = await this.process(processId, actor);
    const [checks, current] = await Promise.all([
      this.repo.checksOf(process.id),
      process.currentProtocolId ? this.repo.getProtocol(process.currentProtocolId) : Promise.resolve(null),
    ]);
    const content = (current?.contentJson as Json | undefined) ?? {};
    const appendix = (content.appendix2 as Json | undefined) ?? {};
    const section1 = (appendix.section1_load_status as Json | undefined) ?? { rows: [] };
    const section3 = (appendix.section3_not_checked_no_id as Json | undefined) ?? { count: 0, rows: [] };
    const a1 = ((content.tz92_tables as Json | undefined)?.a1_completeness as Json[] | undefined) ?? [];
    return {
      process_id: process.id,
      scenario: process.scenario,
      scenario_ru: process.scenario ? this.codes.label('LoadScenario', process.scenario) : null,
      scenario_line: (section1.scenario_line as string | null | undefined) ?? null,
      upload_status: (process.uploadStatus as Json | null) ?? null,
      load_status_rows: (section1.rows as Json[] | undefined) ?? [],
      not_checked_no_id: { count: Number(section3.count ?? 0), rows: (section3.rows as Json[] | undefined) ?? [] },
      completeness_rows: a1,
      non_reviewable: checks
        .filter((c) => c.lifecycleState === 'ACTIVE' && !isReviewable(c))
        .map((c) => ({
          finding_id: c.findingId,
          param_code: c.paramCode,
          location: c.location,
          protocol_status: c.protocolStatus,
          violation_label: c.violationLabel,
          completeness_status: c.completenessStatus,
          completeness_basis: c.completenessBasis,
        })),
      note: 'Статусы комплектности показываются отдельно от кандидатов в нарушения и не требуют решения инспектора (п. 9.3 ТЗ).',
    };
  }

  async protocol(processId: string, version: number | undefined, actor: Actor): Promise<Json> {
    const { process } = await this.process(processId, actor);
    const protocols = await this.repo.protocolsOf(process.id);
    const row = version ? protocols.find((p) => p.version === version) : (protocols.find((p) => p.id === process.currentProtocolId) ?? protocols.at(-1));
    if (!row) throw new ApiProblem('NOT_FOUND');
    const names = await this.names([row.finalizedBy], actor);
    return { protocol: protocolRef(row, names), content: row.contentJson as Json };
  }

  /**
   * The protocol document of an imported run with the inspector's current decisions applied (read model for the
   * protocol view, so it agrees with the verification workspace). Null when the run has no process for the object,
   * or the process is hidden-test. A FINAL protocol is returned as sealed; no decisions → the base unchanged.
   */
  async decisionsOverlay(runId: string, objectId: string, base: Json): Promise<Json | null> {
    const process = (await this.repo.processesOfObject(objectId)).find((p) => p.activeRunId === runId);
    if (!process) return null;
    const object = await this.repo.getObject(objectId);
    if (object?.split === 'TEST_HIDDEN') return null;
    const [checks, decisions, protocols] = await Promise.all([
      this.repo.checksOf(process.id),
      this.repo.decisionsOf(process.id),
      this.repo.protocolsOf(process.id),
    ]);
    const current = protocols.find((p) => p.id === process.currentProtocolId) ?? protocols.at(-1);
    if (!current) return null;
    if (current.isFinal) return current.contentJson as Json;
    return applyDecisions(base, this.snapshotDecisions(checks, decisions), {
      version: Number(base.version ?? current.version),
      status: String(base.status ?? current.status),
      processStatus: process.status,
      isFinal: false,
      generatedAt: String(base.generated_at ?? new Date().toISOString()),
      label: (e, c) => this.codes.label(e, c),
    });
  }

  /** «Подтверждено частично» groups of the process that works this run (see partialGroupProgress); {} when none. */
  async partialProgress(runId: string, objectId: string): Promise<Record<string, GroupProgress>> {
    const process = (await this.repo.processesOfObject(objectId)).find((p) => p.activeRunId === runId);
    if (!process) return {};
    const object = await this.repo.getObject(objectId);
    if (object?.split === 'TEST_HIDDEN') return {};
    const checks = (await this.repo.checksOf(process.id)).filter((c) => isReviewable(c));
    return partialGroupProgress(checks);
  }

  async rinPreview(processId: string, actor: Actor): Promise<Json> {
    const { process, object } = await this.process(processId, actor);
    const [checks, protocols, decisions] = await Promise.all([
      this.repo.checksOf(process.id),
      this.repo.protocolsOf(process.id),
      this.repo.decisionsOf(process.id),
    ]);
    const current = protocols.find((p) => p.id === process.currentProtocolId) ?? protocols.at(-1) ?? null;
    const content = (current?.contentJson as Json | undefined) ?? {};
    const idx = protocolIndex(content);
    const byId = new Map(decisions.map((d) => [d.id, d]));
    const names = await this.names([current?.finalizedBy], actor);
    // Invariant I6: only inspector-confirmed ACTIVE findings.
    const violations = checks
      .filter((c) => c.lifecycleState === 'ACTIVE' && c.inspectorStatus === 'CONFIRMED_VIOLATION' && c.decidedBy === 'INSPECTOR')
      .sort((a, b) => compareQueue(a, b))
      .map((c) => {
        const d = c.currentDecisionId ? byId.get(c.currentDecisionId) : undefined;
        return {
          finding_id: c.findingId,
          param_code: c.paramCode,
          parameter_label: idx.labels.get(c.cardNo ?? '') ?? c.paramCode,
          location: c.location,
          location_type: c.locationType,
          expected_value: c.expectedValue,
          actual_value: c.actualValue,
          criticality: c.criticality,
          sources: (((c.findingJson as Json).evidence as Json[] | undefined) ?? []).map((e) => ({
            stage: e.stage,
            file_id: e.file_id,
            file_sha256: e.file_sha256 ?? null,
            document_code: e.document_code ?? null,
            revision: e.revision ?? null,
            pdf_page_number: e.pdf_page_number,
            geometry: e.geometry ?? null,
          })),
          decision: {
            status: 'CONFIRMED_VIOLATION',
            basis_code: c.decisionBasisCode,
            user_id: c.decidedUserId,
            decided_at: c.decidedAt?.toISOString() ?? null,
            comment: c.decisionComment,
          },
          planned_action: d?.plannedAction ?? null,
        };
      });
    const registry = ((content.input_registry as Json | undefined)?.files as Json[] | undefined) ?? [];
    return {
      process_id: process.id,
      transfer_allowed: process.status === 'FINALIZED' && current?.status === 'PROTOCOL_FINALIZED',
      protocol: current ? protocolRef(current, names) : null,
      versions: {
        matrix_version: current?.matrixVersion ?? null,
        model_version: current?.modelVersion ?? null,
        dataset_version: current?.datasetVersion ?? null,
        pipeline_version: current?.pipelineVersion ?? null,
        input_manifest_hash: current?.inputManifestHash ?? null,
      },
      object: { object_id: object.id, name: displayObjectName(object, content), address: object.address },
      violations,
      input_files_registry: registry,
    };
  }

  async datasetItems(filter: { processId?: string; objectId?: string; status?: string }, actor: Actor): Promise<Json> {
    if (filter.processId) await this.process(filter.processId, actor);
    if (filter.objectId) {
      const object = await this.repo.getObject(filter.objectId);
      if (object?.split === 'TEST_HIDDEN') throw new ApiProblem('HIDDEN_TEST_ACCESS_DENIED', { object_id: filter.objectId });
    }
    const rows = await this.repo.datasetItems(filter);
    const names = await this.names(rows.map((r) => r.expertId), actor);
    return { total: rows.length, items: rows.map((r) => datasetItemDto(r, names, this.codes)) };
  }

  decisionCodes(): Json {
    const withHotkeys = (list: Array<{ code: string; label_ru: string }>) => list.map((e, i) => ({ ...e, hotkey: i < 9 ? String(i + 1) : null }));
    return {
      reject: withHotkeys(
        this.codes.reject.map((r) => ({
          code: r.code,
          label_ru: r.label_ru,
          family: r.family ?? null,
          requires: r.requires,
          suggested_fix_ru: suggestedFix(r.code, '{param}'),
        })),
      ),
      confirm: withHotkeys(this.codes.confirm.map((r) => ({ code: r.code, label_ru: r.label_ru }))),
      clarify: withHotkeys(this.codes.clarify.map((r) => ({ code: r.code, label_ru: r.label_ru }))),
      unfinalize: this.codes.unfinalize.map((r) => ({ code: r.code, label_ru: r.label_ru })),
      revision_basis: this.codes.revisionBasis.map((r) => ({ code: r.code, label_ru: r.label_ru })),
      planned_action: this.codes.plannedAction.map((code) => ({ code, label_ru: this.codes.label('PlannedAction', code) })),
      limits: { other_comment_min: 30, unfinalize_reason_min: UNFINALIZE_MIN_REASON, comment_max: COMMENT_MAX, undo_window_ms: UNDO_WINDOW_MS },
    };
  }

  async usability(processId: string, actor: Actor): Promise<Json> {
    const { process } = await this.process(processId, actor);
    const [decisions, events] = await Promise.all([this.repo.decisionsOf(process.id), this.repo.uiEventsOf(process.id)]);
    const report = usabilityReport(
      decisions.map((d) => ({ decidedAt: d.createdAt, userId: d.userId, decision: d.decision, metrics: (d.clientMetrics as Json | null) ?? null })),
      events.map((e) => ({ type: e.type, tsClient: e.tsClient, userId: e.userId })),
      process.finalizedAt,
    );
    return { process_id: process.id, ...report };
  }

  async ingestUiEvents(
    body: { session_id?: string | null; process_id?: string | null; events: Array<{ type: string; finding_id?: string | null; target?: string | null; input?: string | null; ts_client: string; payload?: Json | null }> },
    actor: Actor,
  ): Promise<Json> {
    if (!actor.principal) return { accepted: 0 };
    if (body.process_id) await this.process(body.process_id, actor);
    const accepted = await this.repo.insertUiEvents(
      body.events.map((e) => ({
        sessionId: body.session_id ?? null,
        userId: actor.principal!.userId,
        processId: body.process_id ?? null,
        findingId: e.finding_id ?? null,
        type: e.type,
        target: e.target ?? null,
        input: e.input ?? null,
        tsClient: new Date(e.ts_client),
        payload: e.payload ?? null,
      })),
    );
    return { accepted };
  }

  // ───────────────────────────── writes ─────────────────────────────

  private async idempotent(
    operation: string,
    actor: Actor,
    meta: WriteMeta,
    request: unknown,
    work: (tx: VerificationTx) => Promise<{ status: number; body: Json; etag: string | null }>,
  ): Promise<WriteResult> {
    const principal = this.writer(actor);
    const requestSha256 = sha256Hex(canonicalJson({ operation, request, if_match: meta.ifMatch ?? null }));
    const replay = (row: IdempotencyRow): WriteResult => {
      if (row.operation !== operation || row.requestSha256 !== requestSha256) throw new ApiProblem('IDEMPOTENCY_KEY_REUSED');
      return { status: row.statusCode, body: row.responseBody as Json, etag: row.etag, replayed: true };
    };
    const prior = await this.repo.getIdempotency(principal.userId, meta.idempotencyKey);
    if (prior) return replay(prior);
    const attempt = () =>
      this.repo.transaction(async (tx) => {
        const result = await work(tx);
        const stored = await tx.putIdempotency({
          userId: principal.userId,
          idempotencyKey: meta.idempotencyKey,
          operation,
          requestSha256,
          statusCode: result.status,
          responseBody: result.body,
          etag: result.etag,
        });
        if (!stored) throw new ReplayRace();
        return { ...result, replayed: false };
      });
    try {
      try {
        return await attempt();
      } catch (err) {
        if (!isRetryable(err)) throw err;
        return await attempt();
      }
    } catch (err) {
      if (err instanceof ReplayRace || isUniqueViolation(err)) {
        const again = await this.repo.getIdempotency(principal.userId, meta.idempotencyKey);
        if (again) return replay(again);
      }
      throw err;
    }
  }

  private requireIfMatch(meta: WriteMeta): number {
    const v = parseIfMatch(meta.ifMatch);
    if (!Number.isFinite(v)) throw new ApiProblem('PRECONDITION_REQUIRED');
    return v;
  }

  /** A rule violation as a problem: catalogue code + one `errors[]` item per offending field. */
  private violation(v: RuleViolation): ApiProblem {
    const errors: ProblemItem[] = (v.fields ?? []).map((f) => ({
      code: v.code,
      title: v.code === 'COMMENT_REQUIRED' ? 'Нужен комментарий' : 'Некорректный запрос',
      detail: f.message,
      field: f.field,
      pointer: `/requestBody/${f.field}`,
    }));
    return new ApiProblem(v.code, v.details ?? {}, errors.length ? { errors } : {});
  }

  /** POST …/findings/{finding_id}/decisions */
  async decide(processId: string, findingId: string, body: DecisionBody, meta: WriteMeta, actor: Actor): Promise<WriteResult> {
    const principal = this.writer(actor);
    const { object } = await this.process(processId, actor);
    const checked = checkDecisionBody(body, this.codes);
    if ('violation' in checked) throw this.violation(checked.violation);
    const ifMatch = this.requireIfMatch(meta);
    return this.idempotent('decideFinding', actor, meta, { processId, findingId, body }, async (tx) => {
      const out = await this.applyDecision(tx, { processId, findingId, object, body, decision: checked.decision, ifMatch, actor, principal, meta });
      return { status: 201, body: out.body, etag: etagOf(out.rowVersion) };
    });
  }

  /** POST …/decisions/validate — the same checks and the AI verdict, without side effects. */
  async validate(processId: string, findingId: string, body: DecisionBody, actor: Actor): Promise<Json> {
    const { process, object } = await this.process(processId, actor);
    const checked = checkDecisionBody(body, this.codes);
    if ('violation' in checked) throw this.violation(checked.violation);
    const { checks, check, group } = await this.cardContext(process, findingId);
    const warnings: string[] = [];
    const fingerprint = fingerprintOf(check, group);
    if (body.seen_fingerprint && body.seen_fingerprint !== fingerprint) warnings.push('EVIDENCE_CHANGED');
    let ai: ValidatorResult | null = null;
    if (checked.decision === 'NEGATIVE_VERIFIED') ai = await this.runValidator(check, group, body, checks, object);
    const effect = effectOf(checked.decision, ai?.verdict ?? null, machineFindingStatus(check), false);
    return {
      decision: checked.decision,
      effective_status: effect.effectiveStatus,
      ai: ai ? this.aiDto(ai, body.reason_code ?? null, check.paramCode) : null,
      opens_dispute: effect.opensDispute,
      evidence_fingerprint: fingerprint,
      warnings,
    };
  }

  private aiDto(ai: ValidatorResult, reasonCode: string | null, paramCode: string): Json {
    return {
      verdict: ai.verdict,
      confidence: ai.confidence,
      rule_ids: ai.ruleIds,
      argument: ai.argument,
      comment: aiComment(ai.verdict, ai.confidence, ai.argument, reasonCode ? suggestedFix(reasonCode, paramCode) : null),
    };
  }

  private async runValidator(check: CheckRow, group: EvidenceGroupRow | null, body: DecisionBody, checks: CheckRow[], object: ObjectInfo): Promise<ValidatorResult> {
    const evidence = (((check.findingJson as Json).evidence as Array<Json>) ?? []).map((e) => ({
      stage: String(e.stage),
      file_id: String(e.file_id),
      pdf_page_number: Number(e.pdf_page_number),
      role: (e.role as string | undefined) ?? null,
      localization: (e.localization as string | undefined) ?? null,
      geometry: (e.geometry as { boxes?: unknown[] } | undefined) ?? null,
    }));
    const fileIds = [body.correct_file_id, body.approved_change_file_id].filter((x): x is string => Boolean(x));
    const files = new Map(
      (await this.repo.files(fileIds)).map((f) => [f.id, { fileId: f.id, objectId: f.objectId, docStage: f.docStage, manifestStage: f.manifestStage }]),
    );
    const fields: Array<{ field: string; message: string }> = [];
    for (const [field, id] of [
      ['correct_file_id', body.correct_file_id],
      ['approved_change_file_id', body.approved_change_file_id],
    ] as const) {
      if (!id) continue;
      const f = files.get(id);
      if (!f || f.objectId !== object.id) fields.push({ field, message: `файл ${id} не относится к объекту ${object.id}` });
    }
    let duplicate = null;
    if (body.reason_code === 'DUPLICATE' && body.duplicate_of) {
      const d = checks.find((c) => c.findingId === body.duplicate_of && c.lifecycleState === 'ACTIVE');
      if (!d || d.findingId === check.findingId) fields.push({ field: 'duplicate_of', message: 'укажите другую действующую находку этой проверки' });
      else duplicate = { findingId: d.findingId, paramCode: d.paramCode, location: d.location };
    }
    if (fields.length) {
      throw this.violation({ code: 'VALIDATION_ERROR', details: { summary: fields.map((f) => `/${f.field} — ${f.message}`).join('; ') }, fields });
    }
    return validateRejection({
      reasonCode: body.reason_code!,
      finding: {
        findingId: check.findingId,
        paramCode: check.paramCode,
        location: check.location,
        locationType: check.locationType,
        axis: check.axis,
        comparisonResult: check.comparisonResult,
        criticalityLevel: check.criticalityLevel,
        riskLevel: check.riskLevel,
        confidence: check.confidence,
        evidence,
        groupLocations: (group?.locations as string[] | undefined) ?? [check.location],
      },
      approvedChangeRef: body.approved_change_ref ?? null,
      approvedChangeFileId: body.approved_change_file_id ?? null,
      correctFileId: body.correct_file_id ?? null,
      duplicate,
      files,
      label: (e, c) => this.codes.label(e, c),
    });
  }

  private async applyDecision(
    tx: VerificationTx,
    a: {
      processId: string;
      findingId: string;
      object: ObjectInfo;
      body: DecisionBody;
      decision: DecisionType;
      ifMatch: number;
      actor: Actor;
      principal: Principal;
      meta: WriteMeta;
      /** Explicit resolution from POST /disputes/{id}/resolve. */
      resolution?: { disputeId: number; status: string };
    },
  ): Promise<{ body: Json; rowVersion: number }> {
    const process = await tx.lockProcess(a.processId, 'no key update');
    if (!process) throw new ApiProblem('PROCESS_NOT_FOUND');
    if (process.status === 'FINALIZED') throw new ApiProblem('PROTOCOL_FINALIZED');
    const check = await tx.lockCheck(a.processId, a.findingId);
    if (!check) throw new ApiProblem('NOT_FOUND');
    if (!isReviewable(check)) {
      throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: check.inspectorStatus === null ? check.protocolStatus : check.lifecycleState });
    }
    const decisions = await tx.decisionsOf(a.processId);
    const previous = check.currentDecisionId ? (decisions.find((d) => d.id === check.currentDecisionId) ?? null) : null;
    const now = new Date();
    const undo =
      process.status === 'COMPLETED' &&
      a.decision === 'REVERT_TO_PENDING' &&
      previous !== null &&
      previous.userId === a.principal.userId &&
      now.getTime() - previous.createdAt.getTime() <= UNDO_WINDOW_MS;
    if (!(process.status === 'READY' || process.status === 'VERIFYING' || undo)) {
      throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: process.status });
    }
    if (check.rowVersion !== a.ifMatch) throw await this.versionConflict(check, previous);
    const current = process.currentProtocolId ? await tx.getProtocol(process.currentProtocolId) : null;
    const groups = await this.repo.groupsOf(a.processId);
    const group = groups.find((g) => g.evidenceGroupId === check.evidenceGroupId) ?? null;
    const fingerprint = fingerprintOf(check, group);
    if (a.body.seen_fingerprint !== fingerprint) throw new ApiProblem('EVIDENCE_CHANGED', { evidence_fingerprint: fingerprint });
    if (!transitionAllowed(check.inspectorStatus, a.decision)) {
      throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: check.inspectorStatus ?? 'NOT_REVIEWABLE' });
    }
    if (a.body.override_of_decision_id && a.body.override_of_decision_id !== check.currentDecisionId) {
      throw this.violation({
        code: 'VALIDATION_ERROR',
        details: { summary: '/override_of_decision_id — решение уже изменено; откройте карточку заново' },
        fields: [{ field: 'override_of_decision_id', message: 'не совпадает с текущим решением по карточке' }],
      });
    }
    const idx = protocolIndex(current?.contentJson as Json | undefined);
    const card = check.cardNo ? idx.cards.get(check.cardNo) : undefined;
    const openDisputes = await tx.openDisputesOf(a.processId);
    const openDispute = openDisputes.find((d) => d.findingId === check.findingId) ?? null;
    if (a.resolution && (!openDispute || openDispute.id !== a.resolution.disputeId)) {
      throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: 'DISPUTE_NOT_OPEN' });
    }
    const resolution = openDispute ? (a.resolution?.status ?? RESOLUTION_BY_DECISION[a.decision]) : null;
    const body = { ...a.body };
    if (resolution === 'INSPECTOR_UPHELD' && (body.comment_source ?? 'MANUAL') === 'TEMPLATE') {
      throw this.violation({
        code: 'COMMENT_REQUIRED',
        fields: [{ field: 'comment', message: 'ИИ не согласен с отклонением: чтобы настоять на нём, добавьте собственный комментарий' }],
      });
    }
    // Approved change on the card: a confirmation needs an explicit justification (ТЗ §9.2 п.3, VER-17).
    const approvedChangeRef = typeof card?.approved_change_ref === 'string' ? card.approved_change_ref : 'NONE';
    if (a.decision === 'CONFIRMED_VIOLATION' && approvedChangeRef.toUpperCase() !== 'NONE' && !body.justification?.trim()) {
      throw this.violation({
        code: 'VALIDATION_ERROR',
        details: { summary: '/justification — в карточке указано согласованное изменение; обоснуйте подтверждение' },
        fields: [{ field: 'justification', message: `согласованное изменение «${approvedChangeRef}»: обоснуйте подтверждение нарушения` }],
      });
    }
    let ai: ValidatorResult | null = null;
    if (a.decision === 'NEGATIVE_VERIFIED' && !openDispute) {
      ai = await this.runValidator(check, group, body, await tx.checksOf(a.processId), a.object);
    }
    const hadDraft = previous?.effectiveStatus === 'CONFIRMED_VIOLATION' || previous?.effectiveStatus === 'NEGATIVE_VERIFIED';
    const effect = effectOf(a.decision, ai?.verdict ?? null, machineFindingStatus(check), hadDraft);
    const basisCode = a.decision === 'CONFIRMED_VIOLATION' ? (body.basis_code ?? defaultConfirmBasis({ axis: check.axis, comparisonResult: check.comparisonResult, matrixScope: check.matrixScope })) : null;
    const reasonCode = a.decision === 'NEGATIVE_VERIFIED' ? body.reason_code! : null;
    const clarifyCode = a.decision === 'CLARIFICATION_REQUIRED' ? body.clarify_code! : null;
    const files = new Map((await this.repo.files(((check.findingJson as Json).evidence as Array<{ file_id: string }>).map((e) => e.file_id))).map((f) => [f.id, f] as [string, FileRow]));
    const sources = cardSources(check, group, card, files);
    const facts = cardFacts(check, idx, sources);
    let comment = (body.comment ?? '').trim();
    if (!comment) {
      comment =
        a.decision === 'REVERT_TO_PENDING'
          ? SYSTEM_COMMENT_REVERTED
          : a.decision === 'CONFIRMED_VIOLATION'
            ? confirmComment(facts)
            : a.decision === 'NEGATIVE_VERIFIED'
              ? `Отклонено: ${this.codes.label('DecisionRejectReason', reasonCode)}`
              : clarifyComment(this.codes.label('DecisionClarifyBasis', clarifyCode), facts);
    }
    const upheldDisagree = resolution === 'INSPECTOR_UPHELD' && openDispute !== null;
    const aiVerdict = ai?.verdict ?? (upheldDisagree ? 'DISAGREE' : null);
    const aiConfidence = ai?.confidence ?? null;
    const aiText = ai ? aiComment(ai.verdict, ai.confidence, ai.argument, reasonCode ? suggestedFix(reasonCode, check.paramCode) : null) : upheldDisagree ? openDispute.aiComment : null;
    let systemComment: string;
    if (a.decision === 'CONFIRMED_VIOLATION') systemComment = systemCommentConfirmed(basisCode!);
    else if (a.decision === 'NEGATIVE_VERIFIED') systemComment = effect.opensDispute ? disputeComment(ai!.argument ?? '') : systemCommentRejected(reasonCode!);
    else if (a.decision === 'CLARIFICATION_REQUIRED') systemComment = systemCommentClarification(clarifyCode!);
    else systemComment = SYSTEM_COMMENT_REVERTED;

    const decisionId = uuidv7(now.getTime());
    const row: NewDecisionRow = {
      id: decisionId,
      processId: a.processId,
      checkId: check.id,
      findingId: check.findingId,
      findingGroupId: check.evidenceGroupId,
      objectId: check.objectId,
      runId: check.runId,
      protocolId: current?.id ?? null,
      protocolVersion: current?.version ?? null,
      decision: a.decision,
      effectiveStatus: effect.effectiveStatus,
      reasonCode,
      basisCode,
      clarifyCode,
      comment: comment.slice(0, COMMENT_MAX),
      commentSource: body.comment_source ?? (body.comment?.trim() ? 'MANUAL' : 'TEMPLATE'),
      systemComment,
      approvedChangeRef: body.approved_change_ref ?? null,
      approvedChangeFileId: body.approved_change_file_id ?? null,
      approvedChangePage: body.approved_change_page ?? null,
      correctedValue: body.corrected_value ?? null,
      correctFileId: body.correct_file_id ?? null,
      correctLocus: body.correct_locus ?? null,
      duplicateOf: body.duplicate_of ?? null,
      naBasis: body.na_basis ?? null,
      justification: body.justification ?? null,
      plannedAction: body.planned_action ?? null,
      aiVerdict,
      aiConfidence,
      aiRuleIds: ai?.ruleIds ?? (upheldDisagree ? openDispute.aiRuleIds : []),
      aiComment: aiText,
      goldEffect: effect.goldEffect,
      seenFingerprint: fingerprint,
      evidenceSnapshot: sources.map((s) => ({
        role: s.role,
        stage: s.stage,
        file_id: s.file_id,
        file_sha256: s.file_sha256,
        document_code: s.document_code,
        revision: s.revision,
        approval_status: s.approval_status,
        pdf_page_number: s.pdf_page_number,
        sheet_number: s.sheet_number,
        geometry: s.geometry,
      })),
      supersedesDecisionId: previous?.id ?? null,
      overrideOfDecisionId: body.override_of_decision_id ?? null,
      resolvesDisputeId: openDispute?.id ?? null,
      userId: a.principal.userId,
      userRole: a.principal.roles.join(','),
      userLogin: a.principal.login,
      ipAddress: a.actor.ip && /^[0-9a-fA-F:.]+$/.test(a.actor.ip) ? a.actor.ip : null,
      userAgent: a.actor.userAgent,
      requestId: a.actor.requestId,
      idempotencyKey: a.meta.idempotencyKey,
      clientMetrics: body.client_metrics ?? null,
      createdAt: now,
    };
    const decision = await tx.insertDecision(row);
    const updated = await tx.updateCheck(check.id, a.ifMatch, {
      inspectorStatus: effect.effectiveStatus,
      findingStatus: effect.findingStatus,
      decidedBy: effect.decidedBy,
      decidedUserId: a.principal.userId,
      decidedAt: now,
      decisionReasonCode: effect.effectiveStatus === 'NEGATIVE_VERIFIED' || effect.opensDispute ? reasonCode : null,
      decisionBasisCode: basisCode,
      decisionComment: decision.comment,
      currentDecisionId: decisionId,
      reviewRequiredReason: null,
    });
    if (!updated) throw await this.versionConflict(check, previous);

    let dispute: DisputeRow | null = null;
    if (a.decision === 'NEGATIVE_VERIFIED') {
      await tx.insertRejection({
        violationId: check.id,
        decisionId,
        processId: a.processId,
        objectId: check.objectId,
        findingId: check.findingId,
        paramCode: check.paramCode,
        rejectionReason: reasonCode!,
        reasonComment: decision.comment,
        correctedValue: body.corrected_value ?? null,
        aiVerdict: aiVerdict ?? 'AGREE',
        aiConfidence,
        aiRuleIds: decision.aiRuleIds,
        aiComment: aiText,
        suggestedFix: suggestedFix(reasonCode!, check.paramCode),
        retrainingStatus: effect.opensDispute ? 'DISPUTED' : 'IN_DRAFT',
        curatorFlag: ai?.verdict === 'UNCERTAIN' || upheldDisagree,
      });
    }
    if (effect.opensDispute && ai) {
      dispute = await tx.insertDispute({
        violationId: check.id,
        decisionId,
        processId: a.processId,
        findingId: check.findingId,
        rejectionReason: reasonCode!,
        inspectorComment: decision.comment,
        aiComment: disputeComment(ai.argument ?? ''),
        aiRuleIds: ai.ruleIds,
        aiEvidence: ai.evidence,
      });
    }
    if (openDispute && resolution) {
      dispute = await tx.resolveDispute(openDispute.id, {
        resolutionStatus: resolution,
        resolvedBy: a.principal.userId,
        resolutionComment: decision.comment,
        resolutionDecisionId: decisionId,
        resolvedAt: now,
      });
    }

    const after = await tx.checksOf(a.processId);
    const reviewable = after.filter(isReviewable);
    const pending = reviewable.filter((c) => c.inspectorStatus === 'PENDING').length;
    const disputesOpen = (await tx.openDisputesOf(a.processId)).length;
    const nextStatus = nextProcessStatus(process.status, pending, disputesOpen);
    const processAfter = await this.moveProcess(tx, process, nextStatus, a.principal.userId, now);

    await this.audit.record(
      {
        action: body.override_of_decision_id ? 'DECISION_OVERRIDE' : AUDIT_BY_DECISION[a.decision],
        objectType: 'FINDING',
        objectId: check.findingId,
        constructionObjectId: check.objectId,
        processId: a.processId,
        protocolVersion: current?.version ?? null,
        details: {
          decision_id: decisionId,
          decision: a.decision,
          effective_status: effect.effectiveStatus,
          reason_code: reasonCode,
          basis_code: basisCode,
          clarify_code: clarifyCode,
          ai_verdict: aiVerdict,
          ai_rule_ids: decision.aiRuleIds,
          gold_effect: effect.goldEffect,
          dispute_id: dispute?.id ?? null,
          dispute_resolution: resolution,
          row_version: updated.rowVersion,
          seen_fingerprint: fingerprint,
          supersedes_decision_id: previous?.id ?? null,
          ...(undo ? { undo: true } : {}),
        },
      },
      { executor: tx.auditExecutor },
    );
    if (processAfter.status !== process.status) {
      await this.auditTransition(tx, processAfter, process.status, current?.version ?? null);
    }

    const ordered = reviewable.sort((x, y) => compareQueue(x, y));
    const names: UserNames = new Map([[a.principal.userId, a.principal.fullName]]);
    const open = new Set((await tx.openDisputesOf(a.processId)).map((d) => d.findingId));
    const gate = computeGate({
      processStatus: processAfter.status,
      reviewable: reviewable.map((c) => ({ findingId: c.findingId, inspectorStatus: c.inspectorStatus })),
      openDisputeFindingIds: [...open],
      nonReviewable: [],
      pendingSuspicionKeys: [],
    });
    return {
      rowVersion: updated.rowVersion,
      body: {
        finding: queueItem(updated, idx, open, names),
        decision: decisionContract(decision),
        ai: ai ? this.aiDto(ai, reasonCode, check.paramCode) : null,
        system_comment: systemComment,
        dispute: dispute ? disputeDto(dispute, names) : null,
        process: {
          status: processAfter.status,
          verification_status: workingProtocolStatus(processAfter.status),
          row_version: processAfter.rowVersion,
          pending,
          disputes_open: disputesOpen,
          can_finalize: gate.can_finalize,
        },
        next_finding_id: nextPending(ordered, check.findingId),
      },
    };
  }

  private async versionConflict(check: CheckRow, previous: DecisionRow | null): Promise<ApiProblem> {
    const names = await this.names([previous?.userId ?? check.decidedUserId]);
    const userId = previous?.userId ?? check.decidedUserId;
    return new ApiProblem('VERSION_CONFLICT', {
      user: userId ? (names.get(userId) ?? userId) : 'другой пользователь',
      decision: this.codes.label('InspectorStatus', check.inspectorStatus) || 'изменено',
      time: check.decidedAt ? timeRu(check.decidedAt) : timeRu(check.updatedAt),
      row_version: check.rowVersion,
      inspector_status: check.inspectorStatus,
      decision_id: check.currentDecisionId,
    });
  }

  /** Applies an automatic process transition and mirrors it on the working protocol version (90 §3.2.3 rule 2). */
  private async moveProcess(tx: VerificationTx, process: ProcessRow, next: string, userId: string, now: Date): Promise<ProcessRow> {
    if (next === process.status && process.status !== 'READY') return process;
    const patch: Parameters<VerificationTx['updateProcess']>[1] = { status: next };
    if (!process.verificationStartedAt) patch.verificationStartedAt = now;
    if (!process.assignedInspectorId) patch.assignedInspectorId = userId;
    if (next === 'COMPLETED') patch.completedAt = now;
    if (next === 'VERIFYING' && process.status === 'COMPLETED') patch.completedAt = null;
    const updated = await tx.updateProcess(process.id, patch);
    if (process.currentProtocolId) {
      const current = await tx.getProtocol(process.currentProtocolId);
      if (current && (current.status === 'IN_VERIFICATION' || current.status === 'VERIFICATION_COMPLETED')) {
        const status = workingProtocolStatus(next);
        if (status !== current.status) await tx.updateProtocol(current.id, { status });
      }
    }
    return updated;
  }

  private async auditTransition(tx: VerificationTx, process: ProcessRow, from: string, protocolVersion: number | null): Promise<void> {
    await this.audit.record(
      {
        action: process.status === 'COMPLETED' ? 'VERIFICATION_COMPLETED' : 'HTTP_POST',
        objectType: 'PROCESS',
        objectId: process.id,
        constructionObjectId: process.objectId,
        processId: process.id,
        protocolVersion,
        details: { transition: `${from}→${process.status}`, automatic: true },
      },
      { executor: tx.auditExecutor, additional: true },
    );
  }

  /** POST /disputes/{dispute_id}/resolve — «Настоять на отклонении» / «Подтвердить нарушение» / «Оставить на уточнении». */
  async resolveDispute(
    disputeId: number,
    input: { resolution: string; comment?: string | null; comment_source?: string | null; basis_code?: string | null; clarify_code?: string | null; seen_fingerprint: string },
    meta: WriteMeta,
    actor: Actor,
  ): Promise<WriteResult> {
    const principal = this.writer(actor);
    const dispute = await this.repo.getDispute(disputeId);
    if (!dispute) throw new ApiProblem('NOT_FOUND');
    const { object } = await this.process(dispute.processId, actor);
    if (!(DISPUTE_RESOLUTIONS as readonly string[]).includes(input.resolution)) {
      throw this.violation({ code: 'VALIDATION_ERROR', details: { summary: '/resolution — неизвестный исход спора' }, fields: [{ field: 'resolution', message: 'неизвестный исход спора' }] });
    }
    const ifMatch = this.requireIfMatch(meta);
    const rejection = await this.repo.decisionsOf(dispute.processId, dispute.findingId).then((ds) => ds.find((d) => d.id === dispute.decisionId) ?? null);
    const body: DecisionBody = { seen_fingerprint: input.seen_fingerprint, decision: 'CONFIRMED_VIOLATION', comment: input.comment ?? '', comment_source: input.comment_source ?? null };
    if (input.resolution === 'INSPECTOR_UPHELD') {
      if (!input.comment?.trim()) {
        throw this.violation({ code: 'COMMENT_REQUIRED', fields: [{ field: 'comment', message: 'чтобы настоять на отклонении, добавьте собственный комментарий' }] });
      }
      Object.assign(body, {
        decision: 'NEGATIVE_VERIFIED',
        reason_code: dispute.rejectionReason,
        comment_source: input.comment_source && input.comment_source !== 'TEMPLATE' ? input.comment_source : 'MANUAL',
        approved_change_ref: rejection?.approvedChangeRef ?? null,
        approved_change_file_id: rejection?.approvedChangeFileId ?? null,
        correct_file_id: rejection?.correctFileId ?? null,
        duplicate_of: rejection?.duplicateOf ?? null,
        na_basis: rejection?.naBasis ?? null,
      });
    } else if (input.resolution === 'AI_UPHELD') {
      Object.assign(body, { decision: 'CONFIRMED_VIOLATION', basis_code: input.basis_code ?? null });
    } else {
      Object.assign(body, {
        decision: 'CLARIFICATION_REQUIRED',
        clarify_code: input.clarify_code ?? KEEP_CLARIFY_BY_REASON[dispute.rejectionReason] ?? 'EXPERT_CONSULTATION',
      });
    }
    const checked = checkDecisionBody({ ...body, comment: body.comment || 'autofill' }, this.codes);
    if ('violation' in checked) throw this.violation(checked.violation);
    return this.idempotent('resolveDispute', actor, meta, { disputeId, input }, async (tx) => {
      const out = await this.applyDecision(tx, {
        processId: dispute.processId,
        findingId: dispute.findingId,
        object,
        body,
        decision: checked.decision,
        ifMatch,
        actor,
        principal,
        meta,
        resolution: { disputeId, status: input.resolution },
      });
      return { status: 200, body: out.body, etag: etagOf(out.rowVersion) };
    });
  }

  /** POST …/verification/claim — READY → VERIFYING (and the assignment). */
  async claim(processId: string, meta: WriteMeta, actor: Actor): Promise<WriteResult> {
    const principal = this.writer(actor);
    const { object } = await this.process(processId, actor);
    const ifMatch = this.requireIfMatch(meta);
    return this.idempotent('claimVerification', actor, meta, { processId }, async (tx) => {
      const process = await this.lockForUpdate(tx, processId, ifMatch);
      if (process.status !== 'READY' && process.status !== 'VERIFYING') {
        throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: process.status });
      }
      const reviewable = (await tx.checksOf(processId)).filter(isReviewable);
      const pending = reviewable.filter((c) => c.inspectorStatus === 'PENDING').length;
      const disputes = (await tx.openDisputesOf(processId)).length;
      const now = new Date();
      let after = process;
      if (process.status === 'READY') {
        after = await this.moveProcess(tx, process, nextProcessStatus('READY', pending, disputes), principal.userId, now);
      } else if (!process.assignedInspectorId) {
        after = await tx.updateProcess(processId, { assignedInspectorId: principal.userId });
      }
      await this.audit.record(
        {
          action: 'HTTP_POST',
          objectType: 'PROCESS',
          objectId: processId,
          constructionObjectId: object.id,
          processId,
          details: { operation: 'verification.claim', transition: `${process.status}→${after.status}`, assigned_inspector_id: after.assignedInspectorId },
        },
        { executor: tx.auditExecutor },
      );
      if (after.status === 'COMPLETED') await this.auditTransition(tx, after, process.status, null);
      return { status: 200, body: transitionDto(after), etag: etagOf(after.rowVersion) };
    });
  }

  /** POST …/verification/reopen — «Возобновить верификацию»: COMPLETED → VERIFYING. */
  async reopen(processId: string, input: { comment?: string | null }, meta: WriteMeta, actor: Actor): Promise<WriteResult> {
    const principal = this.writer(actor);
    const { object } = await this.process(processId, actor);
    const ifMatch = this.requireIfMatch(meta);
    return this.idempotent('reopenVerification', actor, meta, { processId, input }, async (tx) => {
      const process = await this.lockForUpdate(tx, processId, ifMatch);
      if (process.status === 'FINALIZED') throw new ApiProblem('PROTOCOL_FINALIZED');
      if (process.status !== 'COMPLETED') throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: process.status });
      const now = new Date();
      const after = await tx.updateProcess(processId, { status: 'VERIFYING', completedAt: null, assignedInspectorId: process.assignedInspectorId ?? principal.userId });
      if (process.currentProtocolId) {
        const current = await tx.getProtocol(process.currentProtocolId);
        if (current?.status === 'VERIFICATION_COMPLETED') await tx.updateProtocol(current.id, { status: 'IN_VERIFICATION' });
      }
      await this.audit.record(
        {
          action: 'HTTP_POST',
          objectType: 'PROCESS',
          objectId: processId,
          constructionObjectId: object.id,
          processId,
          details: { operation: 'verification.reopen', transition: 'COMPLETED→VERIFYING', comment: input.comment ?? null, at: now.toISOString() },
        },
        { executor: tx.auditExecutor },
      );
      return { status: 200, body: transitionDto(after), etag: etagOf(after.rowVersion) };
    });
  }

  private async lockForUpdate(tx: VerificationTx, processId: string, ifMatch: number): Promise<ProcessRow> {
    const process = await tx.lockProcess(processId, 'update');
    if (!process) throw new ApiProblem('PROCESS_NOT_FOUND');
    if (process.rowVersion !== ifMatch) {
      throw new ApiProblem('VERSION_CONFLICT', {
        user: 'другой пользователь',
        decision: this.codes.label('ProcessStatus', process.status),
        time: timeRu(process.updatedAt),
        row_version: process.rowVersion,
      });
    }
    return process;
  }

  private snapshotDecisions(checks: CheckRow[], decisions: DecisionRow[]): Map<string, SnapshotDecision> {
    const byId = new Map(decisions.map((d) => [d.id, d]));
    const out = new Map<string, SnapshotDecision>();
    for (const c of checks) {
      if (!isReviewable(c)) continue;
      const d = c.currentDecisionId ? byId.get(c.currentDecisionId) : undefined;
      out.set(c.findingId, {
        findingId: c.findingId,
        location: c.location,
        status: c.inspectorStatus ?? 'PENDING',
        decidedBy: c.decidedBy,
        reasonCode: c.inspectorStatus === 'NEGATIVE_VERIFIED' ? c.decisionReasonCode : null,
        basisCode: c.inspectorStatus === 'CONFIRMED_VIOLATION' ? c.decisionBasisCode : null,
        clarifyCode: c.inspectorStatus === 'CLARIFICATION_REQUIRED' ? (d?.clarifyCode ?? null) : null,
        comment: c.decisionComment,
        decidedAt: c.decidedAt?.toISOString() ?? null,
        userId: c.decidedUserId,
        aiVerdict: c.inspectorStatus === 'NEGATIVE_VERIFIED' ? (d?.aiVerdict ?? null) : null,
        aiComment: c.inspectorStatus === 'NEGATIVE_VERIFIED' ? (d?.aiComment ?? null) : null,
      });
    }
    return out;
  }

  private validateProtocol(content: Json): void {
    const result = this.schemas.validate('protocol', content);
    if (!result.valid) {
      throw new ApiProblem('CONTRACT_VALIDATION_FAILED', { schema: 'protocol', summary: summarizeAjvErrors(result.errors) }, { status: 422 });
    }
  }

  private newVersionRow(base: ProtocolRow, content: Json, fields: Partial<ProtocolRow> & { id: string; version: number; status: string; isFinal: boolean; versionReason: string; generatedAt: Date }) {
    return {
      processId: base.processId,
      objectId: base.objectId,
      protocolNo: base.protocolNo,
      previousVersionId: base.id,
      runId: base.runId,
      matrixVersion: base.matrixVersion,
      datasetVersion: base.datasetVersion,
      modelVersion: base.modelVersion,
      pipelineVersion: base.pipelineVersion,
      engineVersions: base.engineVersions,
      versions: base.versions,
      inputManifestHash: base.inputManifestHash,
      scenario: base.scenario,
      scenarioBase: base.scenarioBase,
      uploadStatus: base.uploadStatus,
      summary: base.summary,
      contentJson: content,
      contentSha256: sha256OfJson(content),
      sourcePath: null,
      sourceSha256: null,
      ...fields,
    };
  }

  /** POST …/finalize — gate, step-up re-auth, FINAL protocol version, GOLD drafts (05 §3.12, 97 ruling 20). */
  async finalize(processId: string, input: { reauth_token?: string | null }, meta: WriteMeta, actor: Actor): Promise<WriteResult> {
    const principal = this.writer(actor);
    const { process: before, object } = await this.process(processId, actor);
    const ifMatch = this.requireIfMatch(meta);
    const prior = await this.repo.getIdempotency(principal.userId, meta.idempotencyKey);
    if (!prior) {
      if (before.status === 'FINALIZED') throw new ApiProblem('PROTOCOL_FINALIZED');
      await this.assertGate(before, await this.repo.checksOf(processId), await this.repo.disputesOf(processId));
      // The seal of the inspector's decision (ТЗ §9.6 «подписанное решение»): a fresh password confirmation.
      await this.auth.consumeReauthToken(input.reauth_token ?? null, principal);
    }
    return this.idempotent('finalizeProtocol', actor, meta, { processId }, async (tx) => {
      let process = await this.lockForUpdate(tx, processId, ifMatch);
      if (process.status === 'FINALIZED') throw new ApiProblem('PROTOCOL_FINALIZED');
      const checks = await tx.checksOf(processId);
      const openDisputes = await tx.openDisputesOf(processId);
      const reviewable = checks.filter(isReviewable);
      const pending = reviewable.filter((c) => c.inspectorStatus === 'PENDING').length;
      if (process.status === 'READY' && pending === 0 && openDisputes.length === 0) {
        process = await this.moveProcess(tx, process, 'COMPLETED', principal.userId, new Date());
      }
      await this.assertGate(process, checks, openDisputes);
      const now = new Date();
      const current = process.currentProtocolId ? await tx.getProtocol(process.currentProtocolId) : null;
      if (!current) throw new ApiProblem('NOT_FOUND');
      const decisions = await tx.decisionsOf(processId);
      const version = (await tx.maxProtocolVersion(processId)) + 1;
      const content = applyDecisions(current.contentJson as Json, this.snapshotDecisions(checks, decisions), {
        version,
        status: 'PROTOCOL_FINALIZED',
        processStatus: 'FINALIZED',
        isFinal: true,
        generatedAt: now.toISOString(),
        signature: {
          inspectorName: principal.fullName,
          inspectorPosition: (await this.users.findById(principal.userId))?.position ?? null,
          finalizedAt: now.toISOString(),
          finalizedBy: principal.fullName,
        },
        label: (e, c) => this.codes.label(e, c),
      });
      this.validateProtocol(content);
      const finalId = uuidv7(now.getTime());
      await tx.updateProtocol(current.id, { status: 'SUPERSEDED', supersededAt: now, supersededReason: 'FINALIZATION' });
      const final = await tx.insertProtocol(
        this.newVersionRow(current, content, {
          id: finalId,
          version,
          status: 'PROTOCOL_FINALIZED',
          isFinal: true,
          versionReason: 'FINALIZATION',
          generatedAt: now,
          finalizedAt: now,
          finalizedBy: principal.userId,
          createdBy: principal.userId,
        }),
      );
      const after = await tx.updateProcess(processId, { status: 'FINALIZED', finalizedAt: now, currentProtocolId: finalId });
      const items = await this.captureGold(tx, after, object, final, checks, decisions, now);
      const counts = {
        confirmed: reviewable.filter((c) => c.inspectorStatus === 'CONFIRMED_VIOLATION').length,
        negative: reviewable.filter((c) => c.inspectorStatus === 'NEGATIVE_VERIFIED').length,
        clarification: reviewable.filter((c) => c.inspectorStatus === 'CLARIFICATION_REQUIRED').length,
      };
      await this.audit.record(
        {
          action: 'PROTOCOL_FINALIZED',
          objectType: 'PROTOCOL',
          objectId: finalId,
          constructionObjectId: object.id,
          processId,
          protocolVersion: version,
          details: { content_sha256: content.content_sha256, stored_sha256: final.contentSha256, previous_version: current.version, counts, dataset_items: items, sign_method: 'SIMPLE_EP_REAUTH' },
        },
        { executor: tx.auditExecutor },
      );
      await this.audit.record(
        {
          action: 'PROTOCOL_VERSION_CREATED',
          objectType: 'PROTOCOL',
          objectId: finalId,
          constructionObjectId: object.id,
          processId,
          protocolVersion: version,
          details: { version_reason: 'FINALIZATION', supersedes: current.id },
        },
        { executor: tx.auditExecutor, additional: true },
      );
      const names = new Map([[principal.userId, principal.fullName]]);
      return {
        status: 200,
        etag: etagOf(after.rowVersion),
        body: {
          process_id: processId,
          status: 'FINALIZED',
          verification_status: 'PROTOCOL_FINALIZED',
          row_version: after.rowVersion,
          protocol: protocolRef(final, names),
          counts,
          dataset_items: items,
          rin: { violations: counts.confirmed, transfer_allowed: true },
        },
      };
    });
  }

  private async assertGate(process: ProcessRow, checks: CheckRow[], disputes: DisputeRow[]): Promise<void> {
    const reviewable = checks.filter(isReviewable);
    const open = disputes.filter((d) => d.resolutionStatus === 'OPEN');
    const pending = reviewable.filter((c) => c.inspectorStatus === 'PENDING').length;
    const status = process.status === 'READY' && pending === 0 && open.length === 0 ? 'COMPLETED' : process.status;
    const gate = computeGate({
      processStatus: status,
      reviewable: reviewable.map((c) => ({ findingId: c.findingId, inspectorStatus: c.inspectorStatus })),
      openDisputeFindingIds: open.map((d) => d.findingId),
      nonReviewable: [],
      pendingSuspicionKeys: [],
    });
    if (!gate.can_finalize) {
      const blockers = gate.blockers.map((b) => ({
        code: 'FINALIZE_GATE_BLOCKED',
        title: 'Финализация невозможна',
        detail:
          b.code === 'PENDING_CANDIDATE'
            ? `Не обработано кандидатов: ${b.count}`
            : b.code === 'OPEN_DISPUTE'
              ? `Открытых споров с ИИ: ${b.count}`
              : `Верификация не завершена (статус ${process.status})`,
        details: { blocker: b.code, count: b.count, finding_ids: b.finding_ids },
      }));
      throw new ApiProblem('FINALIZE_GATE_BLOCKED', { n: pending, blockers: gate.blockers }, { errors: blockers });
    }
  }

  /** Lean M4: Dataset_Items drafts from the final inspector decisions (ТЗ §9.4, §14.1). */
  private async captureGold(tx: VerificationTx, process: ProcessRow, object: ObjectInfo, final: ProtocolRow, checks: CheckRow[], decisions: DecisionRow[], now: Date): Promise<number> {
    const byId = new Map(decisions.map((d) => [d.id, d]));
    const content = final.contentJson as Json;
    const idx = protocolIndex(content);
    const groups = await this.repo.groupsOf(process.id);
    const fileIds = checks.flatMap((c) => (((c.findingJson as Json).evidence as Array<{ file_id: string }> | undefined) ?? []).map((e) => e.file_id));
    const files = new Map((await this.repo.files(fileIds)).map((f) => [f.id, f] as [string, FileRow]));
    const rows = [];
    for (const c of checks) {
      if (!isReviewable(c)) continue;
      const label = goldLabelOf(c.inspectorStatus, c.decidedBy);
      const d = c.currentDecisionId ? byId.get(c.currentDecisionId) : undefined;
      if (!label || !d) continue;
      const group = groups.find((g) => g.evidenceGroupId === c.evidenceGroupId) ?? null;
      const card = c.cardNo ? idx.cards.get(c.cardNo) : undefined;
      const sources = cardSources(c, group, card, files);
      const evidence = viewerCard(c, card, sources, idx);
      evidence.inspector = {
        status: c.inspectorStatus,
        reason_code: label === 'NEGATIVE' ? c.decisionReasonCode : null,
        basis_code: label === 'POSITIVE' ? c.decisionBasisCode : null,
        clarify_code: null,
        comment: c.decisionComment,
        user_id: c.decidedUserId,
        decided_at: c.decidedAt?.toISOString() ?? null,
      };
      evidence.rationale = c.rationale ?? (card?.rationale as string | undefined) ?? null;
      evidence.risk_level = c.riskLevel;
      evidence.ai_verdict = d.aiVerdict;
      evidence.ai_comment = d.aiComment;
      rows.push({
        id: uuidv7(now.getTime()),
        evidenceGroupId: c.evidenceGroupId,
        goldLabel: label,
        expertId: d.userId,
        reasonCode: label === 'POSITIVE' ? d.basisCode : d.reasonCode,
        datasetVersion: null,
        split: datasetSplit(object.split),
        objectGroupId: object.objectGroupId,
        status: 'DRAFT',
        objectId: object.id,
        processId: process.id,
        protocolId: final.id,
        protocolVersion: final.version,
        checkId: c.id,
        findingId: c.findingId,
        decisionId: d.id,
        sourceType: 'PRODUCTION',
        goldRecord: goldRecord(
          {
            findingId: c.findingId,
            findingGroupId: c.evidenceGroupId,
            objectId: c.objectId,
            objectSplit: object.split ?? 'TRAIN_PUBLIC',
            matrixScope: c.matrixScope,
            paramId: c.paramId,
            paramCode: c.paramCode,
            locationType: c.locationType,
            location: c.location,
            pdValue: (c.pdValue as string | number | boolean | null) ?? null,
            rdValue: (c.rdValue as string | number | boolean | null) ?? null,
            idValue: (c.idValue as string | number | boolean | null) ?? null,
            comparisonResult: c.comparisonResult,
            protocolStatus: c.protocolStatus,
            criticality: c.criticality,
            documentStatus: c.documentStatus,
            evidence: ((c.findingJson as Json).evidence as Array<{ stage: string; file_id: string; pdf_page_number: number; document_sheet_number?: string | number | null }>) ?? [],
          },
          label,
        ),
        evidenceCard: evidence,
        versions: {
          matrix_version: final.matrixVersion,
          model_version: final.modelVersion,
          dataset_version: final.datasetVersion,
          pipeline_version: final.pipelineVersion,
          input_manifest_hash: final.inputManifestHash,
          protocol_version: final.version,
          content_sha256: content.content_sha256 ?? null,
        },
        trainingEligible: object.split !== 'TEST_HIDDEN',
        decidedAt: d.createdAt,
      });
    }
    await tx.insertDatasetItems(rows);
    return rows.length;
  }

  /** POST …/unfinalize — reason code + text ≥ 20, step-up re-auth (ТЗ §9.3 «Отмена финализации»). */
  async unfinalize(processId: string, input: { reason_code?: string | null; reason_text?: string | null; reauth_token?: string | null }, meta: WriteMeta, actor: Actor): Promise<WriteResult> {
    const principal = this.writer(actor);
    const { process: before, object } = await this.process(processId, actor);
    const reasonText = (input.reason_text ?? '').trim();
    if (!input.reason_code || !this.codes.has('UnfinalizeReason', input.reason_code) || reasonText.length < UNFINALIZE_MIN_REASON) {
      throw new ApiProblem('UNFINALIZE_REASON_REQUIRED');
    }
    const ifMatch = this.requireIfMatch(meta);
    const prior = await this.repo.getIdempotency(principal.userId, meta.idempotencyKey);
    if (!prior) {
      if (before.status !== 'FINALIZED') throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: before.status });
      await this.auth.consumeReauthToken(input.reauth_token ?? null, principal);
    }
    return this.idempotent('unfinalizeProtocol', actor, meta, { processId, reason_code: input.reason_code, reason_text: reasonText }, async (tx) => {
      const process = await this.lockForUpdate(tx, processId, ifMatch);
      if (process.status !== 'FINALIZED') throw new ApiProblem('VERIFICATION_NOT_ALLOWED_IN_STATUS', { status: process.status });
      const final = process.currentProtocolId ? await tx.getProtocol(process.currentProtocolId) : null;
      if (!final) throw new ApiProblem('NOT_FOUND');
      const now = new Date();
      const checks = await tx.checksOf(processId);
      const decisions = await tx.decisionsOf(processId);
      const version = (await tx.maxProtocolVersion(processId)) + 1;
      const content = applyDecisions(final.contentJson as Json, this.snapshotDecisions(checks, decisions), {
        version,
        status: 'VERIFICATION_COMPLETED',
        processStatus: 'COMPLETED',
        isFinal: false,
        generatedAt: now.toISOString(),
        label: (e, c) => this.codes.label(e, c),
      });
      this.validateProtocol(content);
      const workingId = uuidv7(now.getTime());
      await tx.updateProtocol(final.id, { status: 'SUPERSEDED', supersededAt: now, supersededReason: 'UNFINALIZED' });
      const working = await tx.insertProtocol(
        this.newVersionRow(final, content, {
          id: workingId,
          version,
          status: 'VERIFICATION_COMPLETED',
          isFinal: false,
          versionReason: 'UNFINALIZATION',
          generatedAt: now,
          createdBy: principal.userId,
        }),
      );
      const after = await tx.updateProcess(processId, { status: 'COMPLETED', finalizedAt: null, currentProtocolId: workingId });
      const suspended = await tx.setDatasetItemsStatus(final.id, 'SUSPENDED');
      await this.audit.record(
        {
          action: 'PROTOCOL_UNFINALIZED',
          objectType: 'PROTOCOL',
          objectId: final.id,
          constructionObjectId: object.id,
          processId,
          protocolVersion: final.version,
          details: { reason_code: input.reason_code, reason_text: reasonText, new_version: version, suspended_dataset_items: suspended },
        },
        { executor: tx.auditExecutor },
      );
      await this.audit.record(
        {
          action: 'PROTOCOL_VERSION_CREATED',
          objectType: 'PROTOCOL',
          objectId: workingId,
          constructionObjectId: object.id,
          processId,
          protocolVersion: version,
          details: { version_reason: 'UNFINALIZATION', supersedes: final.id },
        },
        { executor: tx.auditExecutor, additional: true },
      );
      const names = new Map([[principal.userId, principal.fullName]]);
      return {
        status: 200,
        etag: etagOf(after.rowVersion),
        body: {
          process_id: processId,
          status: 'COMPLETED',
          verification_status: 'VERIFICATION_COMPLETED',
          row_version: after.rowVersion,
          protocol: protocolRef(working, names),
          suspended_dataset_items: suspended,
        },
      };
    });
  }
}
