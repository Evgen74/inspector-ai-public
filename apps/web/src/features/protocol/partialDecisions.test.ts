import { describe, expect, it } from 'vitest';
import type { Protocol } from '../../contracts/protocol';
import { partialLabel, withPartialDecisions } from './partialDecisions';

const row = (group: string, status: string, text: string) => ({ finding_group_id: group, inspector_status: status, inspector_decision_ru: text });
const protocol = {
  appendix2: {
    section4_critical: { count: 2, rows: [row('G1', 'CONFIRMED_VIOLATION', '✅ Подтверждено'), row('G2', 'CONFIRMED_VIOLATION', '✅ Подтверждено')] },
    section5_substantial: { count: 1, rows: [row('G3', 'PENDING', '⏳ Ожидает')] },
    section6_ai_suspicions: { count: 0, rows: [] },
  },
} as unknown as Protocol;

describe('partial group decisions', () => {
  it('labels a half-confirmed group «Подтверждено частично: 2 из 4» and leaves the others alone', () => {
    const out = withPartialDecisions(protocol, { G1: { confirmed: 2, total: 4 }, G3: { confirmed: 1, total: 2 } });
    const rows = out.appendix2.section4_critical.rows;
    expect(rows[0]!.inspector_decision_ru).toBe('✅ Подтверждено частично: 2 из 4');
    expect(rows[0]!.inspector_status).toBe('CONFIRMED_VIOLATION');
    expect(rows[1]!.inspector_decision_ru).toBe('✅ Подтверждено');
    expect(out.appendix2.section5_substantial.rows[0]!.inspector_decision_ru).toBe('⏳ Ожидает');
  });

  it('returns the same object when nothing is partial and never mutates the input', () => {
    expect(withPartialDecisions(protocol, {})).toBe(protocol);
    expect(withPartialDecisions(protocol, undefined)).toBe(protocol);
    withPartialDecisions(protocol, { G1: { confirmed: 1, total: 3 } });
    expect(protocol.appendix2.section4_critical.rows[0]!.inspector_decision_ru).toBe('✅ Подтверждено');
  });

  it('partialLabel only changes a strictly partial progress', () => {
    expect(partialLabel('✅ Подтверждено', { confirmed: 3, total: 3 })).toBe('✅ Подтверждено');
    expect(partialLabel('✅ Подтверждено', { confirmed: 0, total: 3 })).toBe('✅ Подтверждено');
    expect(partialLabel('✅ Подтверждено', undefined)).toBe('✅ Подтверждено');
  });
});
