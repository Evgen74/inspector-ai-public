/**
 * «Подтверждено частично: N из M». The protocol row carries the aggregate status (any confirmation → confirmed,
 * a contract enum); the API adds `decision_progress` for groups whose atomic findings disagree, and the view shows
 * that instead of a plain «Подтверждено» so a half-rejected group never reads as fully confirmed.
 */
import type { Protocol } from '../../contracts/protocol';

export interface GroupProgress {
  confirmed: number;
  total: number;
}

export function partialLabel(base: string, p: GroupProgress | undefined): string {
  return p && p.confirmed > 0 && p.confirmed < p.total ? `${base} частично: ${p.confirmed} из ${p.total}` : base;
}

type Row = { finding_group_id?: string | null; inspector_status: string; inspector_decision_ru: string };

export function withPartialDecisions(protocol: Protocol, progress: Record<string, GroupProgress> | undefined): Protocol {
  if (!progress || Object.keys(progress).length === 0) return protocol;
  const fix = <T extends Row>(rows: T[]): T[] =>
    rows.map((r) =>
      r.inspector_status === 'CONFIRMED_VIOLATION' && r.finding_group_id && progress[r.finding_group_id]
        ? { ...r, inspector_decision_ru: partialLabel(r.inspector_decision_ru, progress[r.finding_group_id]) }
        : r,
    );
  const a = protocol.appendix2;
  return {
    ...protocol,
    appendix2: {
      ...a,
      section4_critical: { ...a.section4_critical, rows: fix(a.section4_critical.rows) },
      section5_substantial: { ...a.section5_substantial, rows: fix(a.section5_substantial.rows) },
      section6_ai_suspicions: { ...a.section6_ai_suspicions, rows: fix(a.section6_ai_suspicions.rows) },
    },
  };
}
