import { describe, expect, it } from 'vitest';
import { compareSummary } from './compareSummary';
import type { EvidenceCardView } from './types';

function card(over: Record<string, unknown>): EvidenceCardView {
  return {
    location: '140',
    location_type: 'ROOM',
    rationale: null,
    param: { label: 'Местные отсосы (В2)' },
    sources: [{ role: 'EXPECTED', stage: 'PD' }, { role: 'ACTUAL', stage: 'RD' }],
    values: { expected: 'местные отсосы В2.7–В2.9', actual: 'только общеобменная П2/ВЕ' },
    ...over,
  } as unknown as EvidenceCardView;
}

describe('compareSummary', () => {
  it('builds «пом. N: в ПД — …; в РД — …» from expected and actual', () => {
    expect(compareSummary(card({}))).toBe('пом. 140: в ПД — местные отсосы В2.7–В2.9; в РД — только общеобменная П2/ВЕ');
  });
  it('names ИД when the actual side comes from as-built documents', () => {
    const c = card({ sources: [{ role: 'ACTUAL', stage: 'ID' }] });
    expect(compareSummary(c)).toContain('в ИД — только общеобменная');
  });
  it('says «не найдено» for a missing side and falls back to the rationale', () => {
    expect(compareSummary(card({ values: { expected: 'X', actual: null } }))).toBe('пом. 140: в ПД — X; в РД — не найдено');
    expect(compareSummary(card({ values: {}, rationale: 'Нет данных в РД' }))).toBe('пом. 140: Нет данных в РД');
    expect(compareSummary(card({ values: {}, rationale: null }))).toBeNull();
  });
  it('truncates very long values to one line', () => {
    const s = compareSummary(card({ values: { expected: 'а'.repeat(500), actual: 'б' } }))!;
    expect(s.length).toBeLessThan(260);
    expect(s).toContain('…');
  });
});
