/**
 * Verification state rules (90 §3.2.2–3.2.4, 05 §3.2–3.5, §3.12): decision validation, the finding axis C
 * transitions and their effect on axes A (finding_status) and D, automatic process transitions, the finalize
 * gate and the queue order. Pure functions: no I/O, unit-tested in isolation.
 */
import { canonicalJson, sha256Hex } from '../../../common/hashing';
import type { DecisionCodes } from './codes';
import type { AiVerdict } from './validator';

export type InspectorStatus = 'PENDING' | 'CONFIRMED_VIOLATION' | 'NEGATIVE_VERIFIED' | 'CLARIFICATION_REQUIRED';
export type DecisionType = 'CONFIRMED_VIOLATION' | 'NEGATIVE_VERIFIED' | 'CLARIFICATION_REQUIRED' | 'REVERT_TO_PENDING';
export type GoldEffect = 'POSITIVE_DRAFT' | 'NEGATIVE_DRAFT' | 'WITHDRAW' | 'NONE';

export interface ClientMetrics {
  time_on_card_ms?: number;
  clicks?: number;
  keys?: number;
  input?: string;
}

/** POST …/decisions body (OpenAPI DecisionRequest). */
export interface DecisionBody {
  decision: string;
  reason_code?: string | null;
  basis_code?: string | null;
  clarify_code?: string | null;
  comment?: string | null;
  comment_source?: string | null;
  approved_change_ref?: string | null;
  approved_change_file_id?: string | null;
  approved_change_page?: number | null;
  corrected_value?: string | number | boolean | null;
  correct_file_id?: string | null;
  correct_locus?: string | null;
  duplicate_of?: string | null;
  na_basis?: string | null;
  justification?: string | null;
  planned_action?: string | null;
  override_of_decision_id?: string | null;
  seen_fingerprint: string;
  client_metrics?: ClientMetrics | null;
}

/** A 4xx the service raises: catalogue code + details + per-field items. */
export interface RuleViolation {
  code: string;
  details?: Record<string, unknown>;
  fields?: Array<{ field: string; message: string }>;
}

export const OTHER_MIN_COMMENT = 30;
export const UNFINALIZE_MIN_REASON = 20;
export const COMMENT_MAX = 4000;
/** «Отменить последнее решение» (Ctrl+Z) reopens a COMPLETED verification within this window (90 §3.2.2). */
export const UNDO_WINDOW_MS = 10_000;

function blank(s: string | null | undefined): boolean {
  return s === null || s === undefined || s.trim() === '';
}

/**
 * Normalizes the v1.0 aliases and checks the Decision contract rules (decision.schema.json `allOf`) plus the
 * ТЗ §9.3 п.2 requirements. Returns the canonical decision type or the first violation.
 */
export function checkDecisionBody(body: DecisionBody, codes: DecisionCodes): { decision: DecisionType } | { violation: RuleViolation } {
  const raw = String(body.decision ?? '').trim().toUpperCase();
  if (raw === 'PARTIALLY_CONFIRMED') return { violation: { code: 'STATUS_NOT_ALLOWED', details: { status: raw } } };
  const decision = codes.normalizeDecision(raw);
  if (!codes.decisionTypes.includes(decision)) {
    return {
      violation: {
        code: 'VALIDATION_ERROR',
        details: { summary: `/decision — допустимые значения: ${codes.decisionTypes.join(', ')} (или CONFIRMED, REJECTED)` },
        fields: [{ field: 'decision', message: 'неизвестный тип решения' }],
      },
    };
  }
  const fields: Array<{ field: string; message: string }> = [];
  const comment = body.comment ?? '';
  if (comment.length > COMMENT_MAX) fields.push({ field: 'comment', message: `комментарий длиннее ${COMMENT_MAX} символов` });
  if (body.comment_source && !codes.commentSource.includes(body.comment_source)) {
    fields.push({ field: 'comment_source', message: 'неизвестный источник комментария' });
  }
  if (body.planned_action && (decision !== 'CONFIRMED_VIOLATION' || !codes.plannedAction.includes(body.planned_action))) {
    fields.push({ field: 'planned_action', message: 'дальнейшее действие указывается только при подтверждении нарушения' });
  }
  if (decision === 'NEGATIVE_VERIFIED') {
    if (blank(body.reason_code)) return { violation: { code: 'REASON_CODE_REQUIRED' } };
    const entry = codes.rejectEntry(body.reason_code!);
    if (!entry) {
      return {
        violation: {
          code: 'VALIDATION_ERROR',
          details: { summary: `/reason_code — неизвестный код причины ${body.reason_code}` },
          fields: [{ field: 'reason_code', message: 'неизвестный код причины' }],
        },
      };
    }
    // A rejection needs only the reason code: the comment (also for OTHER) and the extra fields are optional.
    if (!blank(body.basis_code)) fields.push({ field: 'basis_code', message: 'основание подтверждения не указывается при отклонении' });
    if (!blank(body.clarify_code)) fields.push({ field: 'clarify_code', message: 'основание уточнения не указывается при отклонении' });
  } else if (decision === 'CONFIRMED_VIOLATION') {
    if (blank(comment)) return { violation: { code: 'COMMENT_REQUIRED' } };
    if (!blank(body.basis_code) && !codes.has('DecisionConfirmBasis', body.basis_code)) {
      fields.push({ field: 'basis_code', message: 'неизвестное основание подтверждения' });
    }
    if (!blank(body.reason_code)) fields.push({ field: 'reason_code', message: 'код причины отклонения не указывается при подтверждении' });
    if (!blank(body.clarify_code)) fields.push({ field: 'clarify_code', message: 'основание уточнения не указывается при подтверждении' });
  } else if (decision === 'CLARIFICATION_REQUIRED') {
    if (blank(body.clarify_code)) {
      fields.push({ field: 'clarify_code', message: 'выберите основание запроса уточнения' });
    } else if (!codes.has('DecisionClarifyBasis', body.clarify_code)) {
      fields.push({ field: 'clarify_code', message: 'неизвестное основание уточнения' });
    }
    if (blank(comment)) return { violation: { code: 'COMMENT_REQUIRED' } };
    if (!blank(body.reason_code)) fields.push({ field: 'reason_code', message: 'код причины отклонения не указывается при запросе уточнения' });
    if (!blank(body.basis_code)) fields.push({ field: 'basis_code', message: 'основание подтверждения не указывается при запросе уточнения' });
  }
  if (fields.length) {
    return {
      violation: {
        code: 'VALIDATION_ERROR',
        details: { summary: fields.map((f) => `/${f.field} — ${f.message}`).join('; ') },
        fields,
      },
    };
  }
  return { decision: decision as DecisionType };
}

/** GOLD expert_reason_code auto-default (05 §3.6.2, 0 extra clicks). */
export function defaultConfirmBasis(f: { axis: string | null; comparisonResult: string | null; discrepancyType?: string | null; matrixScope?: string | null }): string {
  const axis = f.axis ?? 'PD_RD';
  if (axis.startsWith('NORM_')) return 'CV_NORM_VIOLATION';
  if (axis === 'RD_ID' || axis === 'PD_ID') {
    return f.comparisonResult === 'TOLERANCE_EXCEEDED' ? 'CV_TOLERANCE_EXCEEDED' : 'CV_NOT_PER_RD';
  }
  if (f.comparisonResult === 'MISSING_DESIGN_ELEMENT') return 'CV_MISSING_IN_RD';
  return 'CV_DEVIATION_PD_RD';
}

export interface DecisionEffect {
  effectiveStatus: InspectorStatus;
  /** Axis A: CONFIRMED_VIOLATION / NEGATIVE_VERIFIED only through an inspector decision (invariant I1). */
  findingStatus: string | null;
  decidedBy: 'INSPECTOR' | 'SYSTEM';
  goldEffect: GoldEffect;
  opensDispute: boolean;
}

/**
 * 90 §3.2.4 canonical action mapping. `machineStatus` is the model outcome of the imported finding (CANDIDATE, or
 * SUSPICION for FREE-* checks); `hadDraft` = the previous current decision produced a GOLD draft.
 */
export function effectOf(decision: DecisionType, verdict: AiVerdict | null, machineStatus: string | null, hadDraft: boolean): DecisionEffect {
  switch (decision) {
    case 'CONFIRMED_VIOLATION':
      return { effectiveStatus: 'CONFIRMED_VIOLATION', findingStatus: 'CONFIRMED_VIOLATION', decidedBy: 'INSPECTOR', goldEffect: 'POSITIVE_DRAFT', opensDispute: false };
    case 'NEGATIVE_VERIFIED':
      if (verdict === 'DISAGREE') {
        return { effectiveStatus: 'CLARIFICATION_REQUIRED', findingStatus: machineStatus, decidedBy: 'SYSTEM', goldEffect: hadDraft ? 'WITHDRAW' : 'NONE', opensDispute: true };
      }
      return { effectiveStatus: 'NEGATIVE_VERIFIED', findingStatus: 'NEGATIVE_VERIFIED', decidedBy: 'INSPECTOR', goldEffect: 'NEGATIVE_DRAFT', opensDispute: false };
    case 'CLARIFICATION_REQUIRED':
      return { effectiveStatus: 'CLARIFICATION_REQUIRED', findingStatus: machineStatus, decidedBy: 'SYSTEM', goldEffect: hadDraft ? 'WITHDRAW' : 'NONE', opensDispute: false };
    case 'REVERT_TO_PENDING':
      return { effectiveStatus: 'PENDING', findingStatus: machineStatus, decidedBy: 'SYSTEM', goldEffect: hadDraft ? 'WITHDRAW' : 'NONE', opensDispute: false };
  }
}

/** Finding transitions (90 §3.2.4): every decided state can change before finalization; PENDING cannot be reverted. */
export function transitionAllowed(from: string | null, decision: DecisionType): boolean {
  if (from === null) return false;
  if (from === 'PENDING') return decision !== 'REVERT_TO_PENDING';
  return ['CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED', 'CLARIFICATION_REQUIRED'].includes(from);
}

export interface ReviewableCheck {
  lifecycleState: string;
  inspectorStatus: string | null;
  completenessStatus: string | null;
}

/** Axis C applies: an ACTIVE check with an inspector status (NULL = no decision needed) and complete data. */
export function isReviewable(c: ReviewableCheck): boolean {
  return (
    c.lifecycleState === 'ACTIVE' &&
    c.inspectorStatus !== null &&
    (c.completenessStatus === null || c.completenessStatus === 'COMPLETE')
  );
}

/** The process statuses in which decisions are accepted (90 §3.2.2 gating matrix). */
export const DECIDING_STATUSES = new Set(['READY', 'VERIFYING']);

/**
 * Automatic process transitions after a decision or a dispute resolution (90 §3.2.2): READY → VERIFYING on the
 * first decision; VERIFYING → COMPLETED when nothing is pending and no dispute is open; COMPLETED → VERIFYING
 * when an undo brought a finding back.
 */
export function nextProcessStatus(current: string, pending: number, openDisputes: number): string {
  const open = pending > 0 || openDisputes > 0;
  if (current === 'READY' || current === 'VERIFYING') return open ? 'VERIFYING' : 'COMPLETED';
  if (current === 'COMPLETED' && open) return 'VERIFYING';
  return current;
}

/** ProtocolStatus of the working version mirroring the process status (90 §3.2.3 rule 2). */
export function workingProtocolStatus(processStatus: string): string {
  if (processStatus === 'FINALIZED') return 'PROTOCOL_FINALIZED';
  return processStatus === 'COMPLETED' ? 'VERIFICATION_COMPLETED' : 'IN_VERIFICATION';
}

/** Evidence fingerprint (05 §3.10, VER-58): changes only when the imported finding or its group change. */
export function evidenceFingerprint(findingSha256: string, groupSha256: string | null): string {
  return sha256Hex(canonicalJson({ finding_sha256: findingSha256, group_sha256: groupSha256 }));
}

/** «Б.12» → 12 (cards sort numerically). */
export function cardOrdinal(cardNo: string | null | undefined): number {
  const m = /(\d+)\s*$/.exec(cardNo ?? '');
  return m ? Number(m[1]) : Number.MAX_SAFE_INTEGER;
}

const CRIT_RANK: Record<string, number> = { CRITICAL_SUSPEND: 0, SUBSTANTIAL_ORDER: 1 };
const PRIORITY_RANK: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };
const COLLATOR = new Intl.Collator('ru', { numeric: true, sensitivity: 'base' });

export interface QueueKey {
  findingId: string;
  criticalityLevel: string | null;
  protocolStatus: string;
  riskLevel: string | null;
  reviewPriority: string | null;
  cardNo: string | null;
  location: string;
}

/**
 * Stable queue order (05 §3.15.1): criticality (critical first), review priority / risk (ordering only, never a
 * status, ТЗ §9.2), protocol card, location, finding id. The order does not change as decisions are taken, so
 * the inspector's position never jumps; «pending first» is a filter.
 */
export function compareQueue(a: QueueKey, b: QueueKey): number {
  const crit = (k: QueueKey) => CRIT_RANK[k.criticalityLevel ?? ''] ?? (k.protocolStatus === 'CRITICAL' ? 0 : k.protocolStatus === 'WARNING' ? 1 : 2);
  const prio = (k: QueueKey) => PRIORITY_RANK[k.reviewPriority ?? k.riskLevel ?? ''] ?? 3;
  return (
    crit(a) - crit(b) ||
    prio(a) - prio(b) ||
    cardOrdinal(a.cardNo) - cardOrdinal(b.cardNo) ||
    COLLATOR.compare(a.location, b.location) ||
    (a.findingId < b.findingId ? -1 : a.findingId > b.findingId ? 1 : 0)
  );
}

/** The next PENDING finding after `current` in queue order (wrapping); null when nothing is pending. */
export function nextPending<T extends QueueKey & { inspectorStatus: string | null }>(ordered: T[], current: string | null): string | null {
  if (!ordered.length) return null;
  const start = current ? ordered.findIndex((c) => c.findingId === current) : -1;
  for (let i = 1; i <= ordered.length; i += 1) {
    const c = ordered[(start + i + ordered.length) % ordered.length]!;
    if (c.inspectorStatus === 'PENDING' && c.findingId !== current) return c.findingId;
  }
  return null;
}

export interface GateItem {
  code: string;
  count: number;
  finding_ids: string[];
}

export interface Gate {
  can_finalize: boolean;
  blockers: GateItem[];
  warnings: GateItem[];
}

export interface GateInput {
  processStatus: string;
  reviewable: Array<{ findingId: string; inspectorStatus: string | null }>;
  openDisputeFindingIds: string[];
  /** Imported checks that need no decision, by protocol status (MISSING_DOCUMENT rows etc.). */
  nonReviewable: Array<{ findingId: string; protocolStatus: string; violationLabel: string }>;
  pendingSuspicionKeys: string[];
}

/**
 * Finalization gate (ТЗ §9.3 п.4, 90 §3.2.4, single implementation): every CANDIDATE processed or explicitly
 * moved to CLARIFICATION_REQUIRED, no open dispute, the process COMPLETED. Warnings never block.
 */
export function computeGate(input: GateInput): Gate {
  const blockers: GateItem[] = [];
  const warnings: GateItem[] = [];
  const add = (list: GateItem[], code: string, ids: string[]) => {
    if (ids.length) list.push({ code, count: ids.length, finding_ids: ids });
  };
  add(blockers, 'PENDING_CANDIDATE', input.reviewable.filter((c) => c.inspectorStatus === 'PENDING').map((c) => c.findingId));
  add(blockers, 'OPEN_DISPUTE', [...new Set(input.openDisputeFindingIds)]);
  if (input.processStatus !== 'COMPLETED' && input.processStatus !== 'FINALIZED') {
    blockers.push({ code: 'PROCESS_NOT_COMPLETED', count: 1, finding_ids: [] });
  }
  const disputed = new Set(input.openDisputeFindingIds);
  add(
    warnings,
    'CLARIFICATION_KEPT',
    input.reviewable.filter((c) => c.inspectorStatus === 'CLARIFICATION_REQUIRED' && !disputed.has(c.findingId)).map((c) => c.findingId),
  );
  add(warnings, 'MISSING_EVIDENCE', input.nonReviewable.filter((c) => c.violationLabel === 'MISSING_DOCUMENT').map((c) => c.findingId));
  add(warnings, 'NOT_COMPARABLE', input.nonReviewable.filter((c) => c.violationLabel === 'COMPARISON_IMPOSSIBLE').map((c) => c.findingId));
  add(warnings, 'PENDING_SUSPICIONS', input.pendingSuspicionKeys);
  return { can_finalize: blockers.length === 0 && input.processStatus === 'COMPLETED', blockers, warnings };
}
