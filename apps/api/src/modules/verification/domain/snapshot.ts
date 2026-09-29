/**
 * Protocol versions written by verification (90 §3.2.3; 05 §3.12): the FINAL version at finalization and the
 * working version after un-finalization. The content is the Protocol contract document of the current version
 * with the inspector decisions applied where the contract has inspector fields:
 * - header (version line «N (окончательная)», status line by process status, 93 §5.4);
 * - Разделы 4–5 «Решение инспектора» (⏳ / ✅ / ❌ / ❓, aggregated per row over its atomic findings);
 * - Раздел 6 (FREE-* groups): inspector status, «Причина отклонения», «Комментарий ИИ»;
 * - Приложение А: А.2 candidates with decisions, А.3 = the confirmed ones, А.4 + inspector negatives;
 * - Приложение Б: `inspector` block and AI verdict of every evidence card;
 * - signature block (FINAL only): inspector, finalization time and the content seal.
 * Machine content (values, deviations, section 2 counts) is never re-derived here.
 *
 * Seal: `content_sha256` inside the document = sha256 of its canonical JSON with `content_sha256` and
 * `signature.content_sha256` set to null; the protocols row stores sha256 of the stored document.
 */
import { canonicalJson, sha256Hex } from '../../../common/hashing';
import { DECISION_MARKER, STATUS_LINE, versionLine } from './templates';

type Json = Record<string, unknown>;

export interface SnapshotDecision {
  findingId: string;
  location: string;
  status: string;
  decidedBy: string | null;
  reasonCode: string | null;
  basisCode: string | null;
  clarifyCode: string | null;
  comment: string | null;
  decidedAt: string | null;
  userId: string | null;
  aiVerdict: string | null;
  aiComment: string | null;
}

export interface SnapshotOptions {
  version: number;
  /** ProtocolStatus */
  status: string;
  /** ProcessStatus after the operation */
  processStatus: string;
  isFinal: boolean;
  generatedAt: string;
  /** FINAL only */
  signature?: { inspectorName: string; inspectorPosition: string | null; finalizedAt: string; finalizedBy: string } | null;
  label: (enumName: string, code: string | null | undefined) => string;
}

const MONTHS_GENITIVE = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

/** «28 сентября 2026 г.» in Moscow time (the protocol header, Приложение 2 «Дата формирования»). */
export function dateRu(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(new Date(iso))
    .reduce<Record<string, string>>((acc, p) => ({ ...acc, [p.type]: p.value }), {});
  return `${Number(parts.day)} ${MONTHS_GENITIVE[Number(parts.month) - 1]} ${parts.year} г.`;
}

/**
 * Group status over atomic decisions — the same rule as the dashboard (AG-08 `aggregateGroupStatus`): any
 * confirmation → CONFIRMED_VIOLATION, else any clarification, else all rejected → NEGATIVE_VERIFIED, else PENDING.
 */
export function aggregateStatus(statuses: string[]): string {
  if (statuses.includes('CONFIRMED_VIOLATION')) return 'CONFIRMED_VIOLATION';
  if (statuses.includes('CLARIFICATION_REQUIRED')) return 'CLARIFICATION_REQUIRED';
  if (statuses.length > 0 && statuses.every((s) => s === 'NEGATIVE_VERIFIED')) return 'NEGATIVE_VERIFIED';
  return 'PENDING';
}

export interface GroupProgress {
  confirmed: number;
  total: number;
}

/**
 * Groups whose atomic findings do not all agree on «confirmed» although at least one is confirmed: the protocol row
 * shows the aggregate status (contract enum), the web shows «Подтверждено частично: N из M» from this map.
 */
export function partialGroupProgress(checks: ReadonlyArray<{ evidenceGroupId: string | null; inspectorStatus: string | null }>): Record<string, GroupProgress> {
  const by = new Map<string, string[]>();
  for (const c of checks) {
    if (!c.evidenceGroupId || c.inspectorStatus === null) continue;
    by.set(c.evidenceGroupId, [...(by.get(c.evidenceGroupId) ?? []), c.inspectorStatus]);
  }
  const out: Record<string, GroupProgress> = {};
  for (const [id, statuses] of by) {
    const confirmed = statuses.filter((s) => s === 'CONFIRMED_VIOLATION').length;
    if (confirmed > 0 && confirmed < statuses.length) out[id] = { confirmed, total: statuses.length };
  }
  return out;
}

/** Раздел 6 inspector status of a FREE-* group from its atomic checks (SuspicionInspectorStatus). */
function suspicionStatus(agg: string, current: string): string {
  if (agg === 'NEGATIVE_VERIFIED') return 'DISMISSED';
  if (agg === 'CLARIFICATION_REQUIRED') return 'CLARIFICATION_REQUIRED';
  if (agg === 'CONFIRMED_VIOLATION') return 'CONVERTED_TO_CANDIDATE';
  return current;
}

function latest(ds: SnapshotDecision[]): string | null {
  const times = ds.map((d) => d.decidedAt).filter((t): t is string => Boolean(t)).sort();
  return times.at(-1) ?? null;
}

/** The decision that represents a group row: the first one whose status equals the aggregate. */
function representative(ds: SnapshotDecision[], agg: string): SnapshotDecision | undefined {
  return ds.find((d) => d.status === agg);
}

export function sealProtocol(content: Json): string {
  const copy = structuredClone(content);
  copy.content_sha256 = null;
  if (copy.signature && typeof copy.signature === 'object') (copy.signature as Json).content_sha256 = null;
  return sha256Hex(canonicalJson(copy));
}

/** Applies the decisions to a copy of `base` (a Protocol document). `decisions` has one entry per atomic finding. */
export function applyDecisions(base: Json, decisions: ReadonlyMap<string, SnapshotDecision>, opts: SnapshotOptions): Json {
  const p = structuredClone(base) as Json & {
    header: Json;
    appendix2: Json & {
      section4_critical: { rows: Json[] };
      section5_substantial: { rows: Json[] };
      section6_ai_suspicions: { rows: Json[] };
    };
    tz92_tables: Json;
    evidence_cards: Json[];
  };
  const of = (ids: unknown): SnapshotDecision[] =>
    ((ids as string[] | undefined) ?? []).map((id) => decisions.get(id)).filter((d): d is SnapshotDecision => Boolean(d));
  const statusOf = (ids: unknown) => aggregateStatus(of(ids).map((d) => d.status));

  p.version = opts.version;
  p.status = opts.status;
  p.process_status = opts.processStatus;
  p.is_final = opts.isFinal;
  p.generated_at = opts.generatedAt;
  p.header = {
    ...p.header,
    generated_at_ru: dateRu(opts.generatedAt),
    version_line: versionLine(opts.version, opts.isFinal),
    status_line: STATUS_LINE[opts.processStatus] ?? String(p.header.status_line ?? ''),
    recheck_running: false,
  };

  for (const section of [p.appendix2.section4_critical, p.appendix2.section5_substantial]) {
    for (const row of section.rows) {
      const agg = statusOf(row.finding_ids);
      row.inspector_status = agg;
      row.inspector_decision_ru = DECISION_MARKER[agg];
    }
  }

  const byGroup = new Map<string, SnapshotDecision[]>();
  for (const card of p.evidence_cards) {
    if (typeof card.finding_group_id === 'string') byGroup.set(card.finding_group_id, of(card.finding_ids));
  }
  for (const row of p.appendix2.section6_ai_suspicions.rows) {
    const ds = typeof row.finding_group_id === 'string' ? (byGroup.get(row.finding_group_id) ?? []) : [];
    if (!ds.length) continue;
    const agg = aggregateStatus(ds.map((d) => d.status));
    row.inspector_status = suspicionStatus(agg, String(row.inspector_status));
    row.inspector_decision_ru = DECISION_MARKER[agg];
    if (agg === 'NEGATIVE_VERIFIED') {
      row.rejection_reason = [...new Set(ds.map((d) => opts.label('DecisionRejectReason', d.reasonCode)).filter(Boolean))].join('; ') || '—';
      row.ai_comment = ds.find((d) => d.aiComment)?.aiComment ?? '—';
    }
  }

  const tables = p.tz92_tables as Json & { a2_candidates?: Json[]; a3_confirmed?: Json[]; a4_negative_verified?: Json[]; a5_hypotheses?: Json[] };
  for (const row of tables.a5_hypotheses ?? []) {
    const ds = typeof row.finding_group_id === 'string' ? (byGroup.get(row.finding_group_id) ?? []) : [];
    if (ds.length) row.inspector_status = suspicionStatus(aggregateStatus(ds.map((d) => d.status)), String(row.inspector_status));
  }
  const candidates = tables.a2_candidates ?? [];
  for (const row of candidates) {
    const ds = of(row.finding_ids);
    if (!ds.length) continue;
    const agg = aggregateStatus(ds.map((d) => d.status));
    const rep = representative(ds, agg);
    row.inspector_status = agg;
    row.basis_code = agg === 'CONFIRMED_VIOLATION' ? (rep?.basisCode ?? null) : null;
    row.clarify_code = agg === 'CLARIFICATION_REQUIRED' ? (rep?.clarifyCode ?? null) : null;
    row.comment = rep?.comment ?? null;
    row.decided_at = latest(ds);
  }
  if (tables.a2_candidates) tables.a3_confirmed = candidates.filter((r) => r.inspector_status === 'CONFIRMED_VIOLATION').map((r) => structuredClone(r));
  // А.4: system negatives stay; one row per inspector NEGATIVE_VERIFIED atomic finding of every card (matrix and FREE-*).
  const negatives = (tables.a4_negative_verified ?? []).filter((r) => r.decided_by !== 'INSPECTOR');
  for (const card of p.evidence_cards) {
    for (const d of of(card.finding_ids)) {
      if (d.status !== 'NEGATIVE_VERIFIED') continue;
      negatives.push({
        card_ref: card.card_no ?? null,
        parameter_code: card.parameter_code,
        parameter_label: card.parameter_label,
        locations: [d.location],
        decided_by: 'INSPECTOR',
        reason_code: d.reasonCode,
        reason_ru: opts.label('DecisionRejectReason', d.reasonCode) || null,
        comment: d.comment,
        ai_comment: d.aiComment,
        decided_at: d.decidedAt,
      });
    }
  }
  if (tables.a4_negative_verified || negatives.length) tables.a4_negative_verified = negatives;

  for (const card of p.evidence_cards) {
    const ds = of(card.finding_ids);
    if (!ds.length) continue;
    const agg = aggregateStatus(ds.map((d) => d.status));
    const rep = representative(ds, agg);
    card.inspector = {
      status: agg,
      reason_code: agg === 'NEGATIVE_VERIFIED' ? (rep?.reasonCode ?? null) : null,
      basis_code: agg === 'CONFIRMED_VIOLATION' ? (rep?.basisCode ?? null) : null,
      clarify_code: agg === 'CLARIFICATION_REQUIRED' ? (rep?.clarifyCode ?? null) : null,
      comment: rep?.comment ?? null,
      user_id: rep?.userId ?? null,
      decided_at: latest(ds),
    };
    const rejection = ds.find((d) => d.aiVerdict);
    if (rejection) {
      card.ai_verdict = rejection.aiVerdict;
      card.ai_comment = rejection.aiComment;
    }
  }

  if (opts.isFinal && opts.signature) {
    p.signature = {
      inspector_name: opts.signature.inspectorName,
      inspector_position: opts.signature.inspectorPosition,
      signed_at: opts.signature.finalizedAt,
      finalized_at: opts.signature.finalizedAt,
      finalized_by: opts.signature.finalizedBy,
      content_sha256: null,
    };
  } else if (!opts.isFinal) {
    p.signature = null;
  }
  p.content_sha256 = null;
  const seal = sealProtocol(p);
  p.content_sha256 = seal;
  if (p.signature && typeof p.signature === 'object') (p.signature as Json).content_sha256 = seal;
  return p;
}
