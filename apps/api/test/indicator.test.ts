/** Strict colour rule (08 §3.5): the truth table is the unit-test table. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  computeIndicator,
  emptyCounters,
  type FindingCounters,
  type IndicatorColor,
  type IndicatorInput,
  tallyProtocol,
} from '../src/modules/dashboard/indicator';

const c = (over: Partial<FindingCounters> = {}): FindingCounters => ({ ...emptyCounters(), ...over });
const withProtocol = (counters: FindingCounters, extra: Partial<IndicatorInput> = {}): IndicatorInput => ({
  hasProtocol: true,
  scenario: 'FULL',
  counters,
  ...extra,
});

const TABLE: Array<[string, IndicatorInput, IndicatorColor, string[]]> = [
  ['no protocol', { hasProtocol: false, counters: c() }, 'NONE', ['NO_PROTOCOL']],
  ['no protocol, hidden split', { hasProtocol: false, hiddenInventoryOnly: true, counters: c() }, 'NONE', ['HIDDEN_TEST_INVENTORY_ONLY']],
  ['hidden split wins even with counters', { hasProtocol: true, hiddenInventoryOnly: true, counters: c({ confirmed: 3 }) }, 'NONE', ['HIDDEN_TEST_INVENTORY_ONLY']],
  ['one confirmed violation', withProtocol(c({ confirmed: 1 })), 'RED', ['CONFIRMED_VIOLATIONS']],
  ['confirmed with pending candidates', withProtocol(c({ confirmed: 2, pending: 7, pending_high: 5 })), 'RED', ['CONFIRMED_VIOLATIONS']],
  ['confirmed with missing evidence', withProtocol(c({ confirmed: 1, missing_evidence: 4 })), 'RED', ['CONFIRMED_VIOLATIONS']],
  ['confirmed on a partial upload', withProtocol(c({ confirmed: 1 }), { scenario: 'PARTIALLY_LOADED' }), 'RED', ['CONFIRMED_VIOLATIONS']],
  ['pending HIGH candidates only (risk ≠ violation)', withProtocol(c({ pending: 3, pending_high: 3 })), 'YELLOW', ['CANDIDATES_PENDING']],
  ['pending LOW candidates only', withProtocol(c({ pending: 1 })), 'YELLOW', ['CANDIDATES_PENDING']],
  ['clarification required only', withProtocol(c({ clarification: 1 })), 'YELLOW', ['CLARIFICATION_REQUIRED']],
  ['missing evidence only', withProtocol(c({ missing_evidence: 4 })), 'YELLOW', ['MISSING_EVIDENCE']],
  ['not comparable only', withProtocol(c({ not_comparable: 2 })), 'YELLOW', ['NOT_COMPARABLE']],
  ['partial upload only', withProtocol(c(), { scenario: 'PARTIALLY_LOADED' }), 'YELLOW', ['PARTIAL_UPLOAD']],
  ['registry missing only', withProtocol(c(), { registryMissing: true }), 'YELLOW', ['REGISTRY_MISSING']],
  [
    'every yellow reason at once, in a fixed order',
    withProtocol(c({ pending: 1, clarification: 1, missing_evidence: 1, not_comparable: 1 }), { scenario: 'PARTIALLY_LOADED', registryMissing: true }),
    'YELLOW',
    ['CANDIDATES_PENDING', 'CLARIFICATION_REQUIRED', 'MISSING_EVIDENCE', 'NOT_COMPARABLE', 'PARTIAL_UPLOAD', 'REGISTRY_MISSING'],
  ],
  ['all rejected by the inspector', withProtocol(c({ rejected: 5 })), 'GREEN', ['NO_VIOLATIONS_COMPLETE']],
  ['nothing found, complete set', withProtocol(c()), 'GREEN', ['NO_VIOLATIONS_COMPLETE']],
  ['pending suspicions never colour (ТЗ §9.5)', withProtocol(c({ suspicions: 3, suspicions_pending: 3 })), 'GREEN', ['NO_VIOLATIONS_COMPLETE']],
  ['suspicions do not turn red either', withProtocol(c({ suspicions: 1, rejected: 2 })), 'GREEN', ['NO_VIOLATIONS_COMPLETE']],
  ['PD_RD_ONLY scenario itself is not a reason', withProtocol(c(), { scenario: 'PD_RD_ONLY' }), 'GREEN', ['NO_VIOLATIONS_COMPLETE']],
  ['rejected plus clarification', withProtocol(c({ rejected: 2, clarification: 1 })), 'YELLOW', ['CLARIFICATION_REQUIRED']],
  ['pending plus rejected', withProtocol(c({ pending: 1, rejected: 9 })), 'YELLOW', ['CANDIDATES_PENDING']],
];

describe('computeIndicator — strict rule truth table', () => {
  it.each(TABLE)('%s', (_name, input, color, reasons) => {
    const result = computeIndicator(input);
    expect(result.color).toBe(color);
    expect(result.reasons.map((r) => r.code)).toEqual(reasons);
  });

  it('has at least 20 cases (08 §3.5)', () => {
    expect(TABLE.length).toBeGreaterThanOrEqual(20);
  });

  it('writes Russian reasons with correct plurals', () => {
    const text = (n: number) => computeIndicator(withProtocol(c({ confirmed: n }))).reasons[0]!.text;
    expect(text(1)).toBe('Подтверждено инспектором: 1 нарушение');
    expect(text(3)).toBe('Подтверждено инспектором: 3 нарушения');
    expect(text(11)).toBe('Подтверждено инспектором: 11 нарушений');
    expect(text(21)).toBe('Подтверждено инспектором: 21 нарушение');
    expect(computeIndicator(withProtocol(c({ pending: 2, pending_high: 1 }))).reasons[0]!.text).toBe(
      'Ожидают решения инспектора: 2 кандидата (критических: 1)',
    );
    expect(computeIndicator(withProtocol(c({ missing_evidence: 5 }))).reasons[0]!.text).toBe(
      'Нет обязательных документов: 5 параметров',
    );
  });
});

describe('tallyProtocol — counters from the protocol contract', () => {
  const protocol = JSON.parse(
    readFileSync(path.resolve(__dirname, '..', 'fixtures', 'd1', 'OBJ-TYUMENSKAYA-5-GOLD-SEED.protocol.json'), 'utf8'),
  );

  it('counts the gold fixture: 3 pending critical groups, 1 missing ИД parameter, 1 pending suspicion', () => {
    const { counters, bySection } = tallyProtocol(protocol);
    expect(counters).toEqual({
      confirmed: 0,
      pending: 3,
      pending_high: 3,
      clarification: 0,
      rejected: 0,
      missing_evidence: 1,
      not_comparable: 0,
      suspicions: 1,
      suspicions_pending: 1,
    });
    expect([...bySection.entries()]).toEqual([['ИОС4', { confirmed: 0, pending: 3, clarification: 0, rejected: 0 }]]);
  });

  it('applies inspector decisions (AG-05) by finding group or card, and red follows a confirmation', () => {
    const decisions = new Map([
      ['OBJ-TYUMENSKAYA-5-GOLD-SEED-G-IOS4-079-CFG-01', 'CONFIRMED_VIOLATION'],
      ['Б.3', 'NEGATIVE_VERIFIED'],
      ['OBJ-TYUMENSKAYA-5-GOLD-SEED-G-FREE-HEATING-001', 'DISMISSED'],
    ]);
    const { counters } = tallyProtocol(protocol, decisions);
    expect(counters).toMatchObject({ confirmed: 1, rejected: 1, pending: 1, suspicions: 1, suspicions_pending: 0 });
    expect(computeIndicator({ hasProtocol: true, scenario: protocol.scenario, counters }).color).toBe('RED');
  });
});
