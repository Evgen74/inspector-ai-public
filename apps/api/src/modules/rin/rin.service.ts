/**
 * Module 6 «ИАИС РиН» stub (ТЗ §9.6): sends confirmed violations of a finalized protocol to a mock endpoint that lives in
 * this API. Retries 1/5/15 min are compressed to seconds outside prod/demo (INSPECTOR_RIN_RETRY_SECONDS overrides the
 * list). No broker is required: a DB-polling tick (`tick()`, once a second) starts auto-sends for finalized processes
 * and re-runs due retries, so pending deliveries survive an API restart. Every attempt is stored in `rin_attempts`.
 */
import { createHash } from 'node:crypto';
import { Inject, Injectable, type OnApplicationBootstrap, type OnModuleDestroy } from '@nestjs/common';
import { ApiProblem } from '../../common/problem';
import { validationProblem } from '../shared/tz-validation';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { type Actor, VerificationService } from '../verification/verification.service';
import { type Attempt, type Delivery, RinRepository } from './rin.repository';

type Json = Record<string, unknown>;

export interface TransportResult {
  ok: boolean;
  httpStatus: number;
  detail: string;
  externalId: string | null;
}

export interface RinTransport {
  deliver(processId: string, payload: Json, ctx: { attemptNo: number; simulateFailures: number }): Promise<TransportResult>;
}

/** The mock ИАИС «РиН»: accepts a well-formed package, or answers 503 while a failure is being simulated. */
export function mockRinReceive(processId: string, payload: Json, attemptNo: number, simulateFailures: number): TransportResult {
  const envFail = Number(process.env.INSPECTOR_MOCK_RIN_FAIL_FIRST ?? 0);
  if (attemptNo <= Math.max(simulateFailures, Number.isFinite(envFail) ? envFail : 0)) {
    return { ok: false, httpStatus: 503, detail: 'Имитация недоступности РиН (503)', externalId: null };
  }
  if (!Array.isArray(payload.violations)) {
    return { ok: false, httpStatus: 422, detail: 'В пакете нет списка нарушений', externalId: null };
  }
  const id = createHash('sha256').update(`${processId}:${JSON.stringify(payload.violations)}`).digest('hex').slice(0, 10).toUpperCase();
  return { ok: true, httpStatus: 200, detail: `Принято нарушений: ${payload.violations.length}`, externalId: `RIN-${id}` };
}

export class MockRinTransport implements RinTransport {
  async deliver(processId: string, payload: Json, ctx: { attemptNo: number; simulateFailures: number }): Promise<TransportResult> {
    return mockRinReceive(processId, payload, ctx.attemptNo, ctx.simulateFailures);
  }
}

export const RIN_TRANSPORT = Symbol('RIN_TRANSPORT');

const SYSTEM_ACTOR: Actor = { principal: null, scope: null, ip: null, userAgent: null, requestId: null };

export const STATUS_LABELS: Record<string, string> = {
  PENDING_SYNC: 'Ожидает синхронизации',
  SYNCED: 'Синхронизировано',
  SYNC_FAILED: 'Ошибка синхронизации',
};

@Injectable()
export class RinService implements OnApplicationBootstrap, OnModuleDestroy {
  private timer: NodeJS.Timeout | null = null;
  private readonly inFlight = new Set<string>();
  private readonly retryDelaysMs: number[];

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly repo: RinRepository,
    private readonly verification: VerificationService,
    @Inject(RIN_TRANSPORT) private readonly transport: RinTransport,
  ) {
    const custom = (process.env.INSPECTOR_RIN_RETRY_SECONDS ?? '')
      .split(',')
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n >= 0);
    const seconds = custom.length ? custom : config.appEnv === 'prod' || config.appEnv === 'demo' ? [60, 300, 900] : [1, 5, 15];
    this.retryDelaysMs = seconds.map((s) => s * 1000);
  }

  onApplicationBootstrap(): void {
    if (this.config.appEnv === 'test' || process.env.INSPECTOR_RIN_WORKER === '0') return;
    this.timer = setInterval(() => void this.tick().catch(() => undefined), 1000);
    this.timer.unref();
  }

  onModuleDestroy(): void {
    if (this.timer) clearInterval(this.timer);
  }

  private dto(d: Delivery, attempts?: Attempt[]): Json {
    return {
      process_id: d.process_id,
      run_id: d.run_id ?? null,
      status: d.status,
      status_label: STATUS_LABELS[d.status] ?? d.status,
      trigger: d.trigger,
      attempts: d.attempts,
      max_attempts: d.max_attempts,
      next_attempt_at: d.next_attempt_at,
      last_error: d.last_error,
      violations: d.violations,
      external_id: d.external_id,
      synced_at: d.synced_at,
      updated_at: d.updated_at,
      ...(attempts ? { attempts_log: attempts } : {}),
    };
  }

  /** Manual «Отправить в РиН» or the automatic start (`trigger`). Only for a finalized protocol. */
  async send(processId: string, opts: { trigger: 'AUTO' | 'MANUAL'; simulateFailures?: number; force?: boolean; userId?: string | null }, actor: Actor): Promise<Json> {
    const preview = await this.verification.rinPreview(processId, actor); // 404/403/hidden-test guards
    if (!preview.transfer_allowed) {
      throw validationProblem('PROTOCOL_NOT_FINALIZED', 'Протокол не утверждён', 'Отправка в РиН доступна только для утверждённого протокола (PROTOCOL_FINALIZED).');
    }
    const existing = await this.repo.get(processId);
    if (existing && !opts.force && (existing.status === 'SYNCED' || existing.status === 'PENDING_SYNC')) {
      return this.dto(existing, await this.repo.attempts(processId));
    }
    const violations = Array.isArray(preview.violations) ? preview.violations.length : 0;
    await this.repo.upsert({
      process_id: processId,
      status: 'PENDING_SYNC',
      trigger: opts.trigger,
      attempts: 0,
      max_attempts: 1 + this.retryDelaysMs.length,
      next_attempt_at: new Date().toISOString(),
      last_error: null,
      payload_sha256: null,
      violations,
      external_id: null,
      simulate_failures: Math.max(0, Math.min(10, Math.trunc(opts.simulateFailures ?? 0))),
      requested_by: opts.userId ?? null,
      synced_at: null,
    });
    return this.attempt(processId);
  }

  /** One delivery attempt; schedules the next one (DB-polled) or ends in SYNC_FAILED. */
  async attempt(processId: string): Promise<Json> {
    const d = await this.repo.get(processId);
    if (!d) throw new ApiProblem('NOT_FOUND');
    if (this.inFlight.has(processId) || d.status !== 'PENDING_SYNC') return this.dto(d, await this.repo.attempts(processId));
    this.inFlight.add(processId);
    try {
      const started = Date.now();
      const attemptNo = d.attempts + 1;
      let result: TransportResult;
      let sha: string | null = d.payload_sha256;
      let violations = d.violations;
      try {
        const preview = await this.verification.rinPreview(processId, SYSTEM_ACTOR);
        const payload: Json = { schema: 'rin-inspection/1', idempotency_key: `${processId}:${(preview.protocol as Json | null)?.version ?? 0}`, ...preview };
        sha = createHash('sha256').update(JSON.stringify(payload)).digest('hex');
        violations = Array.isArray(preview.violations) ? preview.violations.length : 0;
        result = await this.transport.deliver(processId, payload, { attemptNo, simulateFailures: d.simulate_failures });
      } catch (err) {
        result = { ok: false, httpStatus: 0, detail: err instanceof Error ? err.message : String(err), externalId: null };
      }
      await this.repo.addAttempt(processId, {
        attempt_no: attemptNo,
        started_at: new Date(started).toISOString(),
        outcome: result.ok ? 'SUCCESS' : result.httpStatus >= 500 || result.httpStatus === 0 ? 'RETRYABLE_HTTP' : 'NON_RETRYABLE',
        http_status: result.httpStatus || null,
        detail: result.detail,
        duration_ms: Date.now() - started,
      });
      const nonRetryable = !result.ok && result.httpStatus > 0 && result.httpStatus < 500;
      const exhausted = attemptNo >= d.max_attempts || nonRetryable;
      const next = await this.repo.upsert({
        ...d,
        status: result.ok ? 'SYNCED' : exhausted ? 'SYNC_FAILED' : 'PENDING_SYNC',
        attempts: attemptNo,
        next_attempt_at: result.ok || exhausted ? null : new Date(Date.now() + (this.retryDelaysMs[attemptNo - 1] ?? 0)).toISOString(),
        last_error: result.ok ? null : result.detail,
        payload_sha256: sha,
        violations,
        external_id: result.externalId,
        synced_at: result.ok ? new Date().toISOString() : null,
      });
      return this.dto(next, await this.repo.attempts(processId));
    } finally {
      this.inFlight.delete(processId);
    }
  }

  /** Worker step: due retries first, then automatic sends for newly finalized processes. */
  async tick(): Promise<void> {
    for (const id of await this.repo.due(new Date())) await this.attempt(id);
    if (process.env.INSPECTOR_RIN_AUTOSEND === '0') return;
    for (const id of await this.repo.autoCandidates(5)) {
      try {
        await this.send(id, { trigger: 'AUTO' }, SYSTEM_ACTOR);
      } catch {
        // e.g. hidden-test object or a race: mark nothing, the next tick retries the candidate query.
        await this.repo.upsert({ process_id: id, status: 'SYNC_FAILED', trigger: 'AUTO', attempts: 0, max_attempts: 1, next_attempt_at: null, last_error: 'Автоотправка не выполнена', payload_sha256: null, violations: 0, external_id: null, simulate_failures: 0, requested_by: null, synced_at: null }).catch(() => undefined);
      }
    }
  }

  async status(processId: string, actor: Actor): Promise<Json> {
    await this.verification.rinPreview(processId, actor); // 404 / hidden-test / scope guards
    const d = await this.repo.get(processId);
    if (!d) return { process_id: processId, status: null, status_label: 'Не отправлялось', attempts: 0, attempts_log: [] };
    return this.dto(d, await this.repo.attempts(processId));
  }

  async byObject(objectId: string): Promise<Json> {
    const items = await this.repo.byObject(objectId);
    return { object_id: objectId, items: items.map((d) => this.dto(d)) };
  }
}
