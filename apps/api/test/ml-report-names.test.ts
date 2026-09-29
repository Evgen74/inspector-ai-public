import { describe, expect, it } from 'vitest';
import { buildReport, freeParamName, OUTSIDE_MATRIX, renderHtml, ruDate } from '../src/modules/ml-report/report';

describe('ML report wording', () => {
  it('names hypotheses outside the matrix and labels their section in Russian', () => {
    expect(freeParamName('FREE-HEATING-001')).toBe('вне матрицы: отопление');
    expect(freeParamName('FREE-UNKNOWNFAMILY-001')).toBe('вне матрицы: гипотеза ИИ');
    const now = new Date('2026-09-29T09:00:00Z');
    const report = buildReport({
      rows: [{ at: new Date('2026-09-28T12:00:00Z'), decision: 'CONFIRMED_VIOLATION', reason_code: null, param_code: 'FREE-HEATING-001' }],
      from: new Date('2026-09-22T00:00:00Z'),
      to: now,
      params: new Map(),
      reasons: new Map(),
      disputes: 0,
      now,
    } as never) as { by_param: Array<{ name: string; section: string }>; by_section: Array<{ section: string }> };
    expect(report.by_param[0]).toMatchObject({ name: 'вне матрицы: отопление', section: OUTSIDE_MATRIX });
    expect(report.by_section[0]!.section).toBe('Вне матрицы');
  });

  it('prints dates as dd.mm.yyyy in Moscow time, also in the printable version', () => {
    expect(ruDate('2026-09-28T22:30:00.000Z')).toBe('29.09.2026');
    const html = renderHtml(
      buildReport({ rows: [], from: new Date('2026-09-22T00:00:00Z'), to: new Date('2026-09-29T00:00:00Z'), params: new Map(), reasons: new Map(), disputes: 0, now: new Date('2026-09-29T05:00:00Z') } as never) as never,
    );
    expect(html).toContain('Период: 22.09.2026 — 29.09.2026');
    expect(html).not.toContain('UTC');
  });
});
