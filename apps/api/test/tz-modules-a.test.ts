/** ТЗ modules 6 (РиН stub), 8 (normative base) and 10 (weekly ML report): service-level tests with in-memory repositories. */
import { describe, expect, it } from 'vitest';
import { ApiProblem } from '../src/common/problem';
import { InMemoryMlReportSource, MlReportService } from '../src/modules/ml-report';
import { buildReport, renderHtml } from '../src/modules/ml-report/report';
import { InMemoryNormativeRepository, NormativeService } from '../src/modules/normative';
import { InMemoryRinRepository, MockRinTransport, RinService } from '../src/modules/rin';
import type { VerificationService } from '../src/modules/verification/verification.service';
import { baseConfig, tmpDir } from './helpers';

const config = baseConfig({ cacheRoot: tmpDir('cache') });
const admin = { id: null, login: 'admin' };

describe('Нормативная база', () => {
  const make = () => new NormativeService(config, new InMemoryNormativeRepository());

  it('lists the 132 parameters and filters by text, section and criticality', async () => {
    const s = make();
    const all = (await s.list({})) as { total: number; items: Array<{ code: string; section: string; criticality_level: string }>; matrix_version: string };
    expect(all.total).toBe(132);
    expect(all.items).toHaveLength(132);
    const one = (await s.list({ q: 'PZ-001' })) as { items: Array<{ code: string }> };
    expect(one.items.map((i) => i.code)).toEqual(['PZ-001']);
    const sec = (await s.list({ section: 'КР' })) as { items: Array<{ section: string }> };
    expect(sec.items.length).toBeGreaterThan(0);
    expect(sec.items.every((i) => i.section === 'КР')).toBe(true);
    const crit = (await s.list({ criticality: 'SUBSTANTIAL_ORDER' })) as { items: unknown[] };
    expect(crit.items).toHaveLength(26);
  });

  it('saves thresholds as an override, bumps the matrix version and reports it in the list', async () => {
    const s = make();
    const before = (await s.list({})) as { matrix_version: string };
    const res = (await s.update('SPZU-030', { min_value: 5, reason: 'проверка' }, admin)) as { unchanged: boolean; version: number; matrix_version: string; audit_details: { fields: Record<string, unknown> } };
    expect(res.unchanged).toBe(false);
    expect(res.version).toBe(1);
    expect(res.matrix_version).toBe(`${before.matrix_version}+ovr.1`);
    expect(res.audit_details.fields).toHaveProperty('min_value', { from: 4.2, to: 5 });
    const list = (await s.list({ q: 'SPZU-030' })) as { matrix_version: string; overrides: number; items: Array<{ min_value: number; base_min_value: number; overridden: boolean }> };
    expect(list.matrix_version).toBe(res.matrix_version);
    expect(list.overrides).toBe(1);
    expect(list.items[0]).toMatchObject({ min_value: 5, base_min_value: 4.2, overridden: true });
    // deactivate → next version; identical save → no new version
    const second = (await s.update('SPZU-030', { is_active: false }, admin)) as { version: number };
    expect(second.version).toBe(2);
    const same = (await s.update('SPZU-030', { is_active: false }, admin)) as { unchanged: boolean };
    expect(same.unchanged).toBe(true);
    expect(((await s.versions()) as { items: unknown[] }).items).toHaveLength(2);
  });

  it('rejects unknown parameters, empty patches and min greater than max', async () => {
    const s = make();
    await expect(s.update('NOPE-1', { min_value: 1 }, admin)).rejects.toMatchObject({ code: 'NOT_FOUND' });
    await expect(s.update('PZ-001', {}, admin)).rejects.toBeInstanceOf(ApiProblem);
    await expect(s.update('PZ-001', { min_value: 10, max_value: 1 }, admin)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
  });

  it('lists the normative documents cited by the matrix, most cited first', () => {
    const docs = make().documents() as { total: number; items: Array<{ designation: string; params_count: number }> };
    expect(docs.total).toBeGreaterThan(10);
    expect(docs.items[0]!.params_count).toBeGreaterThanOrEqual(docs.items.at(-1)!.params_count);
  });
});

describe('РиН (заглушка)', () => {
  const PID = '01a0e91e-c6e7-7bea-8116-66e9d22436a9';

  function make(finalized = true) {
    process.env.INSPECTOR_RIN_RETRY_SECONDS = '0,0,0';
    const repo = new InMemoryRinRepository();
    const verification = {
      rinPreview: async () => ({ process_id: PID, transfer_allowed: finalized, protocol: { version: 3 }, violations: [{ finding_id: 'a' }, { finding_id: 'b' }] }),
    } as unknown as VerificationService;
    const svc = new RinService(config, repo, verification, new MockRinTransport());
    return { repo, svc };
  }
  const actor = { principal: null, scope: null, ip: null, userAgent: null, requestId: null };

  it('refuses to send a protocol that is not finalized', async () => {
    const { svc } = make(false);
    await expect(svc.send(PID, { trigger: 'MANUAL' }, actor)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
  });

  it('delivers on the first attempt and does not resend a synced delivery', async () => {
    const { svc, repo } = make();
    const r = await svc.send(PID, { trigger: 'MANUAL' }, actor);
    expect(r).toMatchObject({ status: 'SYNCED', attempts: 1, violations: 2 });
    expect(String(r.external_id)).toMatch(/^RIN-/);
    const again = await svc.send(PID, { trigger: 'MANUAL' }, actor);
    expect(again.attempts).toBe(1);
    expect(await repo.attempts(PID)).toHaveLength(1);
  });

  it('retries after simulated failures (PENDING_SYNC → SYNCED) and logs every attempt', async () => {
    const { svc, repo } = make();
    const first = await svc.send(PID, { trigger: 'MANUAL', simulateFailures: 2 }, actor);
    expect(first).toMatchObject({ status: 'PENDING_SYNC', attempts: 1 });
    await svc.tick();
    await svc.tick();
    const d = await repo.get(PID);
    expect(d).toMatchObject({ status: 'SYNCED', attempts: 3 });
    const log = await repo.attempts(PID);
    expect(log.map((a) => a.outcome)).toEqual(['RETRYABLE_HTTP', 'RETRYABLE_HTTP', 'SUCCESS']);
  });

  it('gives up with SYNC_FAILED after the retries are exhausted, and can be re-sent manually', async () => {
    const { svc, repo } = make();
    await svc.send(PID, { trigger: 'MANUAL', simulateFailures: 10 }, actor);
    for (let i = 0; i < 5; i += 1) await svc.tick();
    expect(await repo.get(PID)).toMatchObject({ status: 'SYNC_FAILED', attempts: 4 });
    const retry = await svc.send(PID, { trigger: 'MANUAL' }, actor);
    expect(retry).toMatchObject({ status: 'SYNCED', attempts: 1 });
  });

  it('auto-sends finalized processes on a worker tick', async () => {
    const { svc, repo } = make();
    repo.finalized = [PID];
    await svc.tick();
    expect(await repo.get(PID)).toMatchObject({ status: 'SYNCED', trigger: 'AUTO' });
  });
});

describe('Отчёт по дообучению', () => {
  const NOW = new Date('2026-09-29T12:00:00Z');
  const at = (d: string) => new Date(`${d}T10:00:00Z`);
  const rows = [
    ...Array.from({ length: 4 }, () => ({ at: at('2026-09-28'), decision: 'CONFIRMED_VIOLATION', reason_code: null, param_code: 'PZ-001' })),
    ...Array.from({ length: 4 }, () => ({ at: at('2026-09-27'), decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', param_code: 'AR-040' })),
    { at: at('2026-09-26'), decision: 'NEGATIVE_VERIFIED', reason_code: 'OTHER', param_code: 'AR-040' },
    { at: at('2026-09-26'), decision: 'CLARIFICATION_REQUIRED', reason_code: null, param_code: 'AR-040' },
    { at: at('2026-09-14'), decision: 'CONFIRMED_VIOLATION', reason_code: null, param_code: 'PZ-001' },
  ];
  const params = new Map([['PZ-001', { name: 'Площадь застройки', section: 'ПЗ' }], ['AR-040', { name: 'Ширина коридоров', section: 'АР' }]]);
  const reasons = new Map([['OCR_ERROR', { label: 'Ошибка распознавания (OCR)', family: 'MODEL_ERROR' }]]);
  const report = () => buildReport({ rows, from: new Date('2026-09-22T00:00:00Z'), to: NOW, params, reasons, disputes: 1, now: NOW });

  it('counts confirmed and rejected by parameter, section and reason', () => {
    const r = report() as any;
    expect(r.totals).toMatchObject({ decided: 9, confirmed: 4, rejected: 5, clarification: 1, disputes: 1 });
    expect(r.totals.precision).toBeCloseTo(0.444, 2);
    expect(r.by_param.find((p: any) => p.param_code === 'AR-040')).toMatchObject({ confirmed: 0, rejected: 5, section: 'АР' });
    expect(r.by_section.map((s: any) => s.section).sort()).toEqual(['АР', 'ПЗ']);
    expect(r.by_reason[0]).toMatchObject({ reason_code: 'OCR_ERROR', count: 4, label: 'Ошибка распознавания (OCR)' });
  });

  it('builds an 8-week precision trend', () => {
    const r = report() as any;
    expect(r.trend).toHaveLength(8);
    const last = r.trend.at(-1);
    expect(last.week_start).toBe('2026-09-28');
    expect(r.trend.find((w: any) => w.week_start === '2026-09-14')).toMatchObject({ confirmed: 1, rejected: 0, precision: 1 });
  });

  it('writes rule-based Russian recommendations', () => {
    const texts = (report() as any).recommendations.map((x: any) => x.text) as string[];
    expect(texts.some((t) => t.includes('AR-040') && t.includes('отклонено 5 из 5'))).toBe(true);
    expect(texts.some((t) => t.includes('Главная причина отклонений'))).toBe(true);
    expect(texts.some((t) => t.includes('споров с ИИ: 1'))).toBe(true);
  });

  it('says so when there are no decisions and escapes HTML', () => {
    const empty = buildReport({ rows: [], from: at('2026-09-22'), to: NOW, params, reasons, disputes: 0, now: NOW }) as any;
    expect(empty.recommendations[0].text).toContain('нет решений');
    const html = renderHtml({ ...report(), recommendations: [{ severity: 'info', text: '<b>x</b>' }] });
    expect(html).toContain('Отчёт по дообучению');
    expect(html).toContain('&lt;b&gt;x&lt;/b&gt;');
    expect(html).not.toContain('<b>x</b>');
  });

  it('serves the report through the service for a period', async () => {
    const svc = new MlReportService(config, new InMemoryMlReportSource(rows, 0));
    const r = (await svc.weekly('2026-09-22', '2026-09-29T12:00:00Z', NOW)) as any;
    expect(r.totals.decided).toBe(9);
    await expect(svc.weekly('2026-10-01', '2026-09-01')).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
    expect(await svc.weeklyHtml('2026-09-22', '2026-09-29')).toContain('<table>');
  });
});
