/**
 * (`.db.spec.ts`: outside the default test glob of `make test`; run with vitest.db.config.mts.)
 *
 * Verification on the real stack: PostgreSQL (inspector_test: migrations 0000–0003 + this module's
 * sql/0004_verification.sql), Redis (db 15) and every Drizzle repository — the Тюменская run is imported through
 * AG-00's batch-run import v2 exactly as in production, then verified, finalized and un-finalized over HTTP.
 * Proves the transactional guarantees the in-memory store only emulates: FOR UPDATE + row_version under real
 * concurrency, audit rows in the decision transaction, the append-only / finalization triggers and the I1 CHECK.
 *
 * Run: cd apps/api && pnpm exec vitest run --config test/verification/vitest.db.config.mts
 * (own database inspector_test_ag05 + Redis db 14, created and migrated by the global setup).
 */
import 'reflect-metadata';
import { readFileSync } from 'node:fs';
import { type DynamicModule, Module, type Provider } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import type { NestFastifyApplication } from '@nestjs/platform-fastify';
import type { FastifyInstance } from 'fastify';
import Redis from 'ioredis';
import { Pool } from 'pg';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { AppModule } from '../../src/app.module';
import { configureApp, createFastifyAdapter } from '../../src/bootstrap';
import { loadConfig } from '../../src/config/config';
import { testDatabaseUrl } from '../../src/db/create-db';
import { Database } from '../../src/db/database';
import { DEMO_USERS, seedDemoUsers } from '../../src/modules/auth/seed';
import { DrizzleUsersRepository } from '../../src/modules/auth/users.repository';
import { VERIFICATION_CONTROLLERS, VERIFICATION_MIGRATION_SQL, VERIFICATION_PROVIDERS } from '../../src/modules/verification';
import { OpenApiService } from '../../src/openapi/openapi.service';
import { contractSchemas, tmpDir } from '../helpers';
import { TYUMEN, writeTyumenRun } from '../platform/run-fixture';
import { call, OverlayOpenApiService, type Session } from './harness';

type Json = Record<string, any>;
const REDIS_URL = process.env.INSPECTOR_TEST_REDIS_URL ?? 'redis://127.0.0.1:6379/15';
const PASSWORD = 'Demo-Inspector-2026';
const RUN = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/** Drops and re-applies this module's migration (idempotent on the shared test database). */
async function applyVerificationMigration(pool: Pool): Promise<void> {
  await pool.query(`
    DROP TABLE IF EXISTS dataset_items, dispute_log, rejection_log, ui_events, verification_idempotency CASCADE;
    ALTER TABLE IF EXISTS checks DROP CONSTRAINT IF EXISTS checks_current_decision_fk;
    DROP TABLE IF EXISTS verification_decisions CASCADE;
    ALTER TABLE checks DROP CONSTRAINT IF EXISTS checks_inspector_status_chk;
    ALTER TABLE checks DROP CONSTRAINT IF EXISTS checks_confirmed_by_inspector_chk;
    DROP TRIGGER IF EXISTS checks_inspector_block_finalized ON checks;
    DROP FUNCTION IF EXISTS verification_decisions_block_mutation() CASCADE;
    DROP FUNCTION IF EXISTS verification_block_when_finalized() CASCADE;
    DROP FUNCTION IF EXISTS verification_logs_block_delete() CASCADE;
  `);
  // Rows left by other DB suites (decisions written directly) must satisfy the new checks: start clean.
  await pool.query('TRUNCATE files, objects, runs CASCADE');
  for (const statement of readFileSync(VERIFICATION_MIGRATION_SQL, 'utf8').split('--> statement-breakpoint')) {
    if (statement.trim()) await pool.query(statement);
  }
}

@Module({})
class VerificationDbRoot {}

describe('verification on PostgreSQL + Redis (AG-05)', () => {
  const url = testDatabaseUrl();
  const config = loadConfig(
    { INSPECTOR_APP_ENV: 'test', INSPECTOR_DATABASE_URL: url, INSPECTOR_LOG_LEVEL: 'silent', INSPECTOR_REDIS_URL: REDIS_URL, INSPECTOR_AUTH_MODE: 'required' },
    { runsRoot: tmpDir('db-verification-runs'), dataRoot: tmpDir('db-verification-data') },
  );
  let app: NestFastifyApplication;
  let http: FastifyInstance;
  let pool: Pool;
  const sessions: Record<string, Session> = {};
  let pid = '';
  const q = async (sql: string, params: unknown[] = []) => (await pool.query(sql, params)).rows as Json[];

  beforeAll(async () => {
    pool = new Pool({ connectionString: url, max: 3 });
    await applyVerificationMigration(pool);
    const redis = new Redis(REDIS_URL);
    await redis.flushdb();
    redis.disconnect();
    const root = AppModule.forRoot(config);
    const providers = [...((root.providers ?? []) as Provider[]).filter((p) => p !== OpenApiService), ...VERIFICATION_PROVIDERS];
    const overlay = new OverlayOpenApiService();
    await overlay.init();
    providers.push({ provide: OpenApiService, useValue: overlay });
    const composed: DynamicModule = {
      module: VerificationDbRoot,
      imports: root.imports,
      controllers: [...(root.controllers ?? []), ...VERIFICATION_CONTROLLERS],
      providers,
    };
    app = await NestFactory.create<NestFastifyApplication>(composed, createFastifyAdapter(), { logger: false });
    await configureApp(app);
    http = app.getHttpAdapter().getInstance();
    await pool.query('TRUNCATE users CASCADE');
    await seedDemoUsers(new DrizzleUsersRepository(app.get(Database)), { password: PASSWORD, resetPasswords: true, trainObjects: [TYUMEN], users: [...DEMO_USERS, { login: 'inspector2', fullName: 'Петров Алексей Николаевич', position: 'Специалист', roles: ['INSPECTOR'], assignments: 'none' }] });
    for (const login of ['inspector', 'inspector2']) {
      const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login, password: PASSWORD } });
      expect(res.statusCode, res.body).toBe(200);
      const body = res.json() as Json;
      sessions[login] = { cookie: String(res.headers['set-cookie']).split(';')[0]!, csrf: body.csrf_token, userId: body.user.id, fullName: body.user.full_name };
    }
    const imported = await call(http, {
      method: 'POST',
      url: '/admin/batch-runs/import',
      session: sessions.inspector,
      key: null,
      headers: { 'x-request-id': `ver-import-${RUN}` },
      body: { run_dir: writeTyumenRun(config.runsRoot, { runId: 'db-verification' }) },
    });
    expect(imported.statusCode, imported.body).toBe(201);
    const obj = (await call(http, { url: `/objects/${TYUMEN}/verification`, session: sessions.inspector })).json() as Json;
    pid = obj.processes[0].process_id;
  });

  afterAll(async () => {
    await pool?.end();
    await app?.close();
  });

  const card = async (s: Session, id: string) => (await call(http, { url: `/processes/${pid}/findings/${encodeURIComponent(id)}`, session: s })).json() as Json;
  const post = (s: Session, id: string, c: Json, body: Json) =>
    call(http, { method: 'POST', url: `/processes/${pid}/findings/${encodeURIComponent(id)}/decisions`, session: s, ifMatch: c.row_version, body: { seen_fingerprint: c.evidence_fingerprint, ...body } });

  it('runs the whole flow on PostgreSQL with audit in the decision transaction and real row locks', async () => {
    const inspector = sessions.inspector!;
    const queue = (await call(http, { url: `/processes/${pid}/findings`, session: inspector })).json() as Json;
    expect(queue.total).toBe(10);
    const ids: string[] = queue.items.map((i: Json) => i.finding_id);
    const completeness = (await call(http, { url: `/processes/${pid}/completeness`, session: inspector })).json() as Json;
    expect(completeness.non_reviewable).toHaveLength(1);

    // Real concurrency: same If-Match from two sessions → one 201, one 409 (FOR UPDATE + row_version).
    const first = await card(inspector, ids[0]!);
    const second = sessions.inspector2!;
    const results = await Promise.all([
      post(inspector, ids[0]!, first, { decision: 'CONFIRMED_VIOLATION', comment: first.prefill.confirm_comment, comment_source: 'TEMPLATE' }),
      post(second, ids[0]!, first, { decision: 'CONFIRMED_VIOLATION', comment: first.prefill.confirm_comment, comment_source: 'TEMPLATE' }),
    ]);
    expect(results.map((r) => r.statusCode).sort(), results.map((r) => r.body.slice(0, 300)).join(' | ')).toEqual([201, 409]);
    const [decisionRow] = await q('SELECT decision, effective_status, user_id, seen_fingerprint, evidence_snapshot FROM verification_decisions');
    expect(decisionRow).toMatchObject({ decision: 'CONFIRMED_VIOLATION', effective_status: 'CONFIRMED_VIOLATION' });
    expect(decisionRow!.evidence_snapshot.length).toBeGreaterThanOrEqual(2);
    const [check] = await q('SELECT inspector_status, finding_status, decided_by, row_version, current_decision_id FROM checks WHERE finding_id = $1', [ids[0]]);
    expect(check).toMatchObject({ inspector_status: 'CONFIRMED_VIOLATION', finding_status: 'CONFIRMED_VIOLATION', decided_by: 'INSPECTOR', row_version: 2 });
    // audit_log is append-only (never truncated between runs): scope by this run's process.
    const audit = await q("SELECT action, user_id, process_id, result FROM audit_log WHERE object_id = $1 AND process_id = $2 AND action = 'FINDING_CONFIRMED'", [ids[0], pid]);
    expect(audit.filter((a) => a.result === 'SUCCESS')).toHaveLength(1);

    // AI disagreement → Dispute_Log + Rejection_Log rows; then decide the rest.
    const c2 = await card(inspector, ids[1]!);
    const disputed = await post(inspector, ids[1]!, c2, { decision: 'NEGATIVE_VERIFIED', reason_code: 'WITHIN_TOLERANCE', comment: 'В пределах допуска' });
    expect(disputed.statusCode).toBe(201);
    const [dispute] = await q('SELECT resolution_status, rejection_reason FROM dispute_log');
    expect(dispute).toEqual({ resolution_status: 'OPEN', rejection_reason: 'WITHIN_TOLERANCE' });
    const disputeId = (disputed.json() as Json).dispute.dispute_id;
    const c2b = await card(inspector, ids[1]!);
    const kept = await call(http, {
      method: 'POST',
      url: `/disputes/${disputeId}/resolve`,
      session: inspector,
      ifMatch: c2b.row_version,
      body: { resolution: 'KEPT_CLARIFICATION', seen_fingerprint: c2b.evidence_fingerprint },
    });
    expect(kept.statusCode, kept.body).toBe(200);
    const latencies: number[] = [];
    for (const id of ids.slice(2)) {
      const c = await card(inspector, id);
      const t0 = performance.now();
      const res = id === ids[2]
        ? await post(inspector, id, c, { decision: 'NEGATIVE_VERIFIED', reason_code: 'OCR_ERROR', comment: c.prefill.reject_comments.OCR_ERROR, comment_source: 'TEMPLATE' })
        : await post(inspector, id, c, { decision: 'CONFIRMED_VIOLATION', comment: c.prefill.confirm_comment, comment_source: 'TEMPLATE' });
      latencies.push(performance.now() - t0);
      expect(res.statusCode, res.body).toBe(201);
    }
    latencies.sort((a, b) => a - b);
    console.info(`decision latency on PostgreSQL: median ${latencies[Math.floor(latencies.length / 2)]!.toFixed(1)} ms, max ${latencies.at(-1)!.toFixed(1)} ms (n=${latencies.length})`);
    expect(latencies.at(-1)!).toBeLessThan(1000);
    const [proc] = await q('SELECT status FROM processes WHERE id = $1', [pid]);
    expect(proc!.status).toBe('COMPLETED');
    const [rejections] = await q("SELECT count(*)::int AS n, count(*) FILTER (WHERE ai_verdict = 'DISAGREE')::int AS disputed FROM rejection_log");
    expect(rejections).toEqual({ n: 2, disputed: 1 });

    // Finalize: FINAL protocol version, dataset drafts, then the database itself refuses changes (I4).
    const s = (await call(http, { url: `/processes/${pid}/verification`, session: inspector })).json() as Json;
    expect(s.gate.can_finalize).toBe(true);
    const token = (await call(http, { method: 'POST', url: '/auth/reauth', session: inspector, key: null, body: { password: PASSWORD } })).json() as Json;
    const fin = await call(http, { method: 'POST', url: `/processes/${pid}/finalize`, session: inspector, ifMatch: s.row_version, body: { reauth_token: token.reauth_token } });
    expect(fin.statusCode, fin.body).toBe(200);
    const protocols = await q('SELECT version, status, content_json FROM protocols WHERE process_id = $1 ORDER BY version', [pid]);
    expect(protocols.map((p) => [p.version, p.status])).toEqual([
      [1, 'SUPERSEDED'],
      [2, 'PROTOCOL_FINALIZED'],
    ]);
    const valid = contractSchemas().validate('protocol', protocols[1]!.content_json);
    expect(valid.valid ? [] : valid.errors).toEqual([]);
    const [items] = await q("SELECT count(*)::int AS n, count(*) FILTER (WHERE gold_label = 'NEGATIVE')::int AS neg FROM dataset_items WHERE status = 'DRAFT'");
    expect(items).toEqual({ n: 9, neg: 1 });
    await expect(pool.query("UPDATE checks SET inspector_status = 'NEGATIVE_VERIFIED' WHERE finding_id = $1", [ids[0]])).rejects.toThrow(/PROTOCOL_FINALIZED/);
    await expect(pool.query('UPDATE verification_decisions SET comment = $1', ['подмена'])).rejects.toThrow(/APPEND_ONLY/);
    await expect(pool.query('DELETE FROM dispute_log')).rejects.toThrow(/APPEND_ONLY/);
    await expect(pool.query("UPDATE protocols SET content_json = '{}'::jsonb WHERE version = 2 AND process_id = $1", [pid])).rejects.toThrow(/PROTOCOL_VERSION_IMMUTABLE/);
    const locked = await post(inspector, ids[3]!, await card(inspector, ids[3]!), { decision: 'REVERT_TO_PENDING' });
    expect(locked.statusCode).toBe(423);

    // Un-finalize by the second inspector: v3 working version; drafts suspended.
    const s2 = (await call(http, { url: `/processes/${pid}/verification`, session: sessions.inspector2 })).json() as Json;
    const token2 = (await call(http, { method: 'POST', url: '/auth/reauth', session: sessions.inspector2, key: null, body: { password: PASSWORD } })).json() as Json;
    const un = await call(http, {
      method: 'POST',
      url: `/processes/${pid}/unfinalize`,
      session: sessions.inspector2,
      ifMatch: s2.row_version,
      body: { reason_code: 'SUPERVISOR_REVIEW', reason_text: 'Повторная проверка решений по вентиляции', reauth_token: token2.reauth_token },
    });
    expect(un.statusCode, un.body).toBe(200);
    const after = await q('SELECT version, status, superseded_reason FROM protocols WHERE process_id = $1 ORDER BY version', [pid]);
    expect(after.map((p) => [p.version, p.status, p.superseded_reason])).toEqual([
      [1, 'SUPERSEDED', 'FINALIZATION'],
      [2, 'SUPERSEDED', 'UNFINALIZED'],
      [3, 'VERIFICATION_COMPLETED', null],
    ]);
    const [suspended] = await q("SELECT count(*)::int AS n FROM dataset_items WHERE status = 'SUSPENDED'");
    expect(suspended!.n).toBe(9);
  });

  it('I1 in the database: CONFIRMED_VIOLATION without an inspector decision is rejected', async () => {
    await expect(
      pool.query("UPDATE checks SET finding_status = 'CONFIRMED_VIOLATION', decided_by = 'SYSTEM' WHERE process_id = $1 AND inspector_status IS NULL", [pid]),
    ).rejects.toThrow(/checks_confirmed_by_inspector_chk/);
    await expect(pool.query("UPDATE checks SET inspector_status = 'PARTIALLY_CONFIRMED' WHERE process_id = $1", [pid])).rejects.toThrow(/checks_inspector_status_chk/);
  });
});
