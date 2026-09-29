/**
 * Platform services on the real stack: PostgreSQL (inspector_test, migrations 0002–0003), Redis (db 15, flushed)
 * and the Drizzle repositories. Covers demo seeding and login, the append-only audit log, and the batch-run import
 * v2: idempotency, protocol versioning, preservation of inspector decisions, SUPERSEDED rows, finalized refusal.
 * Run: pnpm --filter @inspector/api test:db
 */
import 'reflect-metadata';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { NestFactory } from '@nestjs/core';
import type { NestFastifyApplication } from '@nestjs/platform-fastify';
import type { FastifyInstance } from 'fastify';
import Redis from 'ioredis';
import { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../../src/app.module';
import { configureApp, createFastifyAdapter } from '../../src/bootstrap';
import { loadConfig } from '../../src/config/config';
import { testDatabaseUrl } from '../../src/db/create-db';
import { Database } from '../../src/db/database';
import { seedDemoUsers } from '../../src/modules/auth/seed';
import { DrizzleUsersRepository } from '../../src/modules/auth/users.repository';
import { tmpDir } from '../helpers';
import { TYUMEN, tyumenDocs, writeTyumenRun } from '../platform/run-fixture';

const REDIS_URL = process.env.INSPECTOR_TEST_REDIS_URL ?? 'redis://127.0.0.1:6379/15';
const PASSWORD = 'Demo-Inspector-2026';
/** audit_log is append-only (never truncated): request ids are unique per test run. */
const RUN = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

describe('platform services on PostgreSQL + Redis', () => {
  const url = testDatabaseUrl();
  const config = loadConfig(
    { INSPECTOR_APP_ENV: 'test', INSPECTOR_DATABASE_URL: url, INSPECTOR_LOG_LEVEL: 'silent', INSPECTOR_REDIS_URL: REDIS_URL, INSPECTOR_AUTH_MODE: 'required' },
    { runsRoot: tmpDir('db-platform-runs'), dataRoot: tmpDir('db-platform-data') },
  );
  let app: NestFastifyApplication;
  let http: FastifyInstance;
  let pool: Pool;
  let admin: { cookie: string; csrf: string };

  beforeAll(async () => {
    const redis = new Redis(REDIS_URL);
    await redis.flushdb();
    redis.disconnect();
    app = await NestFactory.create<NestFastifyApplication>(AppModule.forRoot(config), createFastifyAdapter(), { logger: false });
    await configureApp(app);
    http = app.getHttpAdapter().getInstance();
    pool = new Pool({ connectionString: url, max: 2 });
    await pool.query('TRUNCATE users CASCADE');
    const result = await seedDemoUsers(new DrizzleUsersRepository(app.get(Database)), {
      password: PASSWORD,
      resetPasswords: true,
      trainObjects: [TYUMEN, 'OBJ-SYNTH-B'],
    });
    expect(result.created.sort()).toEqual(['inspector']);
    const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector', password: PASSWORD } });
    expect(res.statusCode, res.body).toBe(200);
    admin = { cookie: String(res.headers['set-cookie']).split(';')[0] ?? '', csrf: res.json().csrf_token };
  });

  afterAll(async () => {
    await pool?.end();
    await app?.close();
  });

  beforeEach(async () => {
    await pool.query('TRUNCATE files, objects, runs CASCADE');
  });

  const importRun = (runDir: string, requestSuffix: string) =>
    http.inject({
      method: 'POST',
      url: '/api/v1/admin/batch-runs/import',
      payload: { run_dir: runDir },
      headers: { cookie: admin.cookie, 'x-csrf-token': admin.csrf, 'x-request-id': `${requestSuffix}-${RUN}` },
    });

  it('seeds demo users idempotently and logs in through Redis with Russian names', async () => {
    const again = await seedDemoUsers(new DrizzleUsersRepository(app.get(Database)), { password: PASSWORD, resetPasswords: false, trainObjects: [TYUMEN] });
    expect(again.created).toEqual([]);
    const login = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector', password: PASSWORD } });
    expect(login.statusCode).toBe(200);
    expect(login.json().user.full_name).toBe('Иванова Мария Сергеевна');
    const cookie = String(login.headers['set-cookie']).split(';')[0] ?? '';
    const me = await http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: { cookie } });
    expect(me.statusCode).toBe(200);
    expect(me.json().assigned_object_ids).toEqual([TYUMEN]);
    const users = await http.inject({ method: 'GET', url: '/api/v1/admin/users', headers: { cookie: admin.cookie } });
    expect(users.json().total).toBe(1);
  });

  it('keeps audit_log append-only', async () => {
    await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector', password: 'wrong' }, headers: { 'x-request-id': `db-audit-${RUN}` } });
    const { rows } = await pool.query("SELECT action, result, actor_type, actor_login, ip_address, retention_class FROM audit_log WHERE request_id = $1", [`db-audit-${RUN}`]);
    expect(rows).toEqual([{ action: 'AUTH_LOGIN_FAILED', result: 'DENIED', actor_type: 'ANONYMOUS', actor_login: 'inspector', ip_address: '127.0.0.1', retention_class: 'SECURITY' }]);
    await expect(pool.query("UPDATE audit_log SET action = 'X' WHERE request_id = $1", [`db-audit-${RUN}`])).rejects.toThrow(/AUDIT_LOG_APPEND_ONLY/);
    await expect(pool.query("DELETE FROM audit_log WHERE request_id = $1", [`db-audit-${RUN}`])).rejects.toThrow(/AUDIT_LOG_APPEND_ONLY/);
    await expect(pool.query('TRUNCATE audit_log')).rejects.toThrow(/AUDIT_LOG_APPEND_ONLY/);
    await pool.query('UPDATE users SET locked_until = NULL, failed_login_count = 0');
  });

  it('imports run artifacts idempotently, versions protocols and preserves inspector decisions', async () => {
    const started = performance.now();
    const first = await importRun(writeTyumenRun(config.runsRoot, { runId: 'db-v2' }), 'db-import-0001');
    const firstMs = performance.now() - started;
    expect(first.statusCode, first.body).toBe(201);
    const o = first.json().artifacts.objects[0];
    expect(o).toMatchObject({ object_id: TYUMEN, process_created: true, process_status: 'READY', finding_groups: 4, suspicions: 1, submissions: ['full', 'strict'] });
    expect(o.protocol).toMatchObject({ version: 1, created: true, status: 'IN_VERIFICATION' });
    expect(o.checks).toEqual({ total: 11, inserted: 11, updated: 0, unchanged: 0, superseded: 0 });

    const q = async (sql: string, params: unknown[] = []) => (await pool.query(sql, params)).rows;
    const [counts] = await q(
      `SELECT (SELECT count(*)::int FROM processes) AS processes, (SELECT count(*)::int FROM protocols) AS protocols,
              (SELECT count(*)::int FROM evidence_groups) AS groups, (SELECT count(*)::int FROM checks) AS checks,
              (SELECT count(*)::int FROM evidence_fragments) AS fragments, (SELECT count(*)::int FROM suspicions) AS suspicions,
              (SELECT count(*)::int FROM submission_exports) AS submissions, (SELECT count(*)::int FROM run_artifacts) AS artifacts,
              (SELECT count(*)::int FROM process_files) AS process_files, (SELECT count(*)::int FROM protocol_exports) AS exports`,
    );
    expect(counts).toMatchObject({ processes: 1, protocols: 1, groups: 4, checks: 11, suspicions: 1, submissions: 2, artifacts: 9, process_files: 3, exports: 2 });
    expect(counts.fragments).toBeGreaterThan(20);
    // ТЗ key fields and the FREE-* chain: suspicion → converted checks.
    const [c012] = await q("SELECT param_code, location, expected_value, actual_value, evidence_group_id, inspector_status, kind FROM checks WHERE location = '012'");
    expect(c012).toMatchObject({ param_code: 'IOS4-079', inspector_status: 'PENDING', kind: 'MATRIX', evidence_group_id: `${TYUMEN}-G-IOS4-079-CFG-01` });
    const [susp] = await q('SELECT inspector_status, promoted_by, discovery_method, array_length(related_check_ids, 1) AS n, converted_check_id FROM suspicions');
    expect(susp).toMatchObject({ inspector_status: 'CONVERTED_TO_CANDIDATE', promoted_by: 'SYSTEM', discovery_method: 'GRAPHIC_DIFF', n: 4 });
    const free = await q("SELECT count(*)::int AS n FROM checks WHERE kind = 'SUSPICION_CONVERTED' AND source_suspicion_id IS NOT NULL");
    expect(free[0].n).toBe(4);
    const pages314 = await q("SELECT DISTINCT page_no FROM evidence_fragments WHERE location = '314' AND stage = 'RD' ORDER BY page_no");
    expect(pages314.map((r) => r.page_no)).toEqual([18, 20]);
    const fragmentIds = (await q('SELECT id FROM evidence_fragments ORDER BY id')).map((r) => r.id);

    // Same run again: nothing changes (no new version, same fragment ids).
    const again = await importRun('db-v2', 'db-import-0002');
    expect(again.statusCode).toBe(200);
    expect(again.json().artifacts.objects[0].protocol).toMatchObject({ version: 1, created: false });
    expect(again.json().artifacts.objects[0].checks).toEqual({ total: 11, inserted: 0, updated: 0, unchanged: 11, superseded: 0 });
    expect((await q('SELECT id FROM evidence_fragments ORDER BY id')).map((r) => r.id)).toEqual(fragmentIds);

    // An inspector decides one check; the engine then changes that finding and drops another one.
    await pool.query("UPDATE checks SET inspector_status = 'CONFIRMED_VIOLATION', decided_by = 'INSPECTOR', decision_comment = 'Подтверждаю' WHERE location = '012'");
    const docs = tyumenDocs();
    const f012 = docs.findings.find((f) => f.location === '012')!;
    f012.rationale = 'Уточнено: в венткамере 012 по РД иной состав приточных установок.';
    docs.findings = docs.findings.filter((f) => f.location !== 'OBJECT');
    docs.protocol = { ...docs.protocol, generated_at: '2026-10-02T09:00:00Z' };
    writeTyumenRun(config.runsRoot, { runId: 'db-v2', docs });
    const third = await importRun('db-v2', 'db-import-0003');
    expect(third.statusCode, third.body).toBe(200);
    const r3 = third.json().artifacts.objects[0];
    expect(r3.protocol).toMatchObject({ version: 2, created: true });
    expect(r3.checks).toEqual({ total: 10, inserted: 0, updated: 1, unchanged: 9, superseded: 1 });
    const versions = await q('SELECT version, status, version_reason, superseded_at IS NOT NULL AS superseded FROM protocols ORDER BY version');
    expect(versions).toEqual([
      { version: 1, status: 'SUPERSEDED', version_reason: 'INITIAL', superseded: true },
      { version: 2, status: 'IN_VERIFICATION', version_reason: 'RECHECK', superseded: false },
    ]);
    const [decided] = await q("SELECT inspector_status, decided_by, decision_comment, row_version, review_required_reason, last_protocol_version FROM checks WHERE location = '012'");
    expect(decided).toEqual({ inspector_status: 'CONFIRMED_VIOLATION', decided_by: 'INSPECTOR', decision_comment: 'Подтверждаю', row_version: 2, review_required_reason: 'VALUE_CHANGED', last_protocol_version: 2 });
    const [dropped] = await q("SELECT lifecycle_state FROM checks WHERE location = 'OBJECT'");
    expect(dropped.lifecycle_state).toBe('SUPERSEDED');
    const [proc] = await q('SELECT p.current_protocol_id = pr.id AS current FROM processes p JOIN protocols pr ON pr.version = 2');
    expect(proc.current).toBe(true);
    // A protocol version is a snapshot.
    await expect(pool.query("UPDATE protocols SET content_json = '{}'::jsonb WHERE version = 2")).rejects.toThrow(/PROTOCOL_VERSION_IMMUTABLE/);
    await expect(pool.query('DELETE FROM protocols WHERE version = 1')).rejects.toThrow(/PROTOCOL_VERSION_IMMUTABLE/);

    // Audit: the import and each new protocol version.
    const audit = await q("SELECT action, object_type, protocol_version FROM audit_log WHERE request_id LIKE 'db-import-%' AND request_id LIKE $1 ORDER BY id", [`%-${RUN}`]);
    expect(audit).toEqual([
      { action: 'PROTOCOL_VERSION_CREATED', object_type: 'PROTOCOL', protocol_version: 1 },
      { action: 'BATCH_RUN_IMPORTED', object_type: 'BATCH_RUN', protocol_version: null },
      { action: 'BATCH_RUN_IMPORTED', object_type: 'BATCH_RUN', protocol_version: null },
      { action: 'PROTOCOL_VERSION_CREATED', object_type: 'PROTOCOL', protocol_version: 2 },
      { action: 'BATCH_RUN_IMPORTED', object_type: 'BATCH_RUN', protocol_version: null },
    ]);
    expect(firstMs).toBeLessThan(5000);
  });

  it('refuses to change a finalized protocol (423) but accepts an unchanged re-import', async () => {
    writeTyumenRun(config.runsRoot, { runId: 'db-final' });
    expect((await importRun('db-final', 'db-final-0001')).statusCode).toBe(201);
    await pool.query("UPDATE protocols SET status = 'PROTOCOL_FINALIZED', finalized_at = now()");
    await pool.query("UPDATE processes SET status = 'FINALIZED'");
    expect((await importRun('db-final', 'db-final-0002')).statusCode).toBe(200);
    const docs = tyumenDocs();
    docs.protocol = { ...docs.protocol, generated_at: '2026-10-03T09:00:00Z' };
    writeTyumenRun(config.runsRoot, { runId: 'db-final', docs });
    const res = await importRun('db-final', 'db-final-0003');
    expect(res.statusCode).toBe(423);
    expect(res.json().code).toBe('PROTOCOL_FINALIZED');
    const rows = (await pool.query('SELECT version, status FROM protocols')).rows;
    expect(rows).toEqual([{ version: 1, status: 'PROTOCOL_FINALIZED' }]);
  });

  it('never stores hidden-object artifacts', async () => {
    const dir = writeTyumenRun(config.runsRoot, { runId: 'db-hidden' });
    expect(readFileSync(path.join(dir, 'layout', 'F9901.json'), 'utf8')).toBe('NEVER READ');
    const res = await importRun('db-hidden', 'db-hidden-0001');
    expect(res.statusCode).toBe(201);
    const paths = (await pool.query('SELECT path FROM run_artifacts ORDER BY path')).rows.map((r) => r.path);
    expect(paths.some((p: string) => p.includes('HIDDEN') || p.includes('F9901'))).toBe(false);
    const objects = (await pool.query('SELECT DISTINCT object_id FROM processes')).rows.map((r) => r.object_id);
    expect(objects).toEqual([TYUMEN]);
    writeFileSync(path.join(dir, 'unused.txt'), 'x');
  });
});
