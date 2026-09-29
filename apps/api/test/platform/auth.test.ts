/**
 * Auth, RBAC, CSRF, sessions and the audit trail through the real AppModule (INSPECTOR_AUTH_MODE=required),
 * with in-memory users, sessions and audit rows (no Redis, no PostgreSQL).
 */
import type { FastifyInstance, LightMyRequestResponse } from 'fastify';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadConfig } from '../../src/config/config';
import { AuditRepository } from '../../src/modules/audit/audit.repository';
import { AuditService } from '../../src/modules/audit/audit.service';
import { AuthService } from '../../src/modules/auth/auth.service';
import { InMemorySessionStore, SessionStore } from '../../src/modules/auth/session-store';
import { UsersRepository } from '../../src/modules/auth/users.repository';
import { createTestApp, type TestApp } from '../helpers';
import type { InMemoryAudit, InMemoryUsers } from '../platform-fakes';

const PASSWORD = 'Demo-Inspector-2026';

interface Session {
  cookie: string;
  csrf: string;
  body: Record<string, unknown>;
}

function cookieOf(res: LightMyRequestResponse): string {
  const raw = res.headers['set-cookie'];
  const first = Array.isArray(raw) ? raw[0] : raw;
  return String(first ?? '').split(';')[0] ?? '';
}

describe('auth, RBAC and audit (required mode)', () => {
  let t: TestApp;
  let http: FastifyInstance;
  let users: InMemoryUsers;
  let audit: InMemoryAudit;
  let sessions: InMemorySessionStore;

  beforeAll(async () => {
    t = await createTestApp({ authMode: 'required' });
    http = t.http;
    users = t.app.get(UsersRepository) as InMemoryUsers;
    audit = t.app.get(AuditRepository) as InMemoryAudit;
    sessions = t.app.get(SessionStore) as InMemorySessionStore;
  });

  beforeEach(async () => {
    // One app per file (building it dominates the test time); every test starts from clean fakes.
    users.users.clear();
    users.assignments.clear();
    audit.rows.length = 0;
    audit.failWith = null;
    sessions.sessions.clear();
    sessions.reauth.clear();
    sessions.failures.clear();
    sessions.blocks.clear();
    sessions.down = false;
    sessions.skewMs = 0;
    t.store.objects.clear();
    await users.add({ login: 'inspector', password: PASSWORD, roles: ['INSPECTOR'], fullName: 'Иванова Мария Сергеевна', objects: ['OBJ-SYNTH-A'] });
    await users.add({ login: 'inspector2', password: PASSWORD, roles: ['INSPECTOR'], objects: [] });
    await users.add({ login: 'inspector3', password: PASSWORD, roles: ['INSPECTOR'] });
    await users.add({ login: 'newbie', password: PASSWORD, roles: ['INSPECTOR'], mustChangePassword: true });
    t.store.objects.set('OBJ-SYNTH-A', {
      id: 'OBJ-SYNTH-A',
      name: 'Объект А',
      address: null,
      customer: null,
      contractor: null,
      permitNumber: null,
      split: 'TRAIN_PUBLIC',
      objectGroupId: null,
      inputManifestHash: null,
      scenario: null,
      indicatorColor: 'NONE',
      indicatorReasons: null,
      indicatorUpdatedAt: null,
      archivedAt: null,
      lastRunId: null,
      createdAt: new Date(),
      updatedAt: new Date(),
    });
  });

  afterAll(async () => {
    await t.close();
  });

  async function login(loginName: string, password = PASSWORD): Promise<Session> {
    const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: loginName, password } });
    expect(res.statusCode, res.body).toBe(200);
    const body = res.json() as Record<string, unknown>;
    return { cookie: cookieOf(res), csrf: String(body.csrf_token), body };
  }

  function as(s: Session, extra: Record<string, string> = {}) {
    return { cookie: s.cookie, 'x-csrf-token': s.csrf, ...extra };
  }

  it('keeps /health and /auth/login public and everything else behind a session', async () => {
    expect((await http.inject({ method: 'GET', url: '/api/v1/health' })).statusCode).toBe(200);
    const res = await http.inject({ method: 'GET', url: '/api/v1/objects' });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toMatchObject({ code: 'UNAUTHENTICATED', status: 401 });
    expect(res.headers['content-type']).toContain('application/problem+json');
  });

  it('logs in with argon2id, sets an HttpOnly SameSite=Strict cookie and audits the login', async () => {
    const res = await http.inject({
      method: 'POST',
      url: '/api/v1/auth/login',
      payload: { login: 'Inspector', password: PASSWORD },
      headers: { 'user-agent': 'vitest', 'x-request-id': 'req-login-0001' },
    });
    expect(res.statusCode).toBe(200);
    const setCookie = String(res.headers['set-cookie']);
    expect(setCookie).toMatch(/^ii_sid=[A-Za-z0-9_-]{40,};/);
    expect(setCookie).toContain('HttpOnly');
    expect(setCookie).toContain('SameSite=Strict');
    const body = res.json() as { user: { full_name: string }; roles: string[]; permissions: Array<{ code: string; scope: string }>; assigned_object_ids: string[] };
    expect(body.user.full_name).toBe('Иванова Мария Сергеевна');
    expect(body.roles).toEqual(['INSPECTOR']);
    expect(body.permissions).toContainEqual({ code: 'finding.decide', scope: 'ALL' });
    expect(body.permissions.map((p) => p.code)).toContain('users.manage');
    expect(body.assigned_object_ids).toEqual(['OBJ-SYNTH-A']);
    // Only the token hash is stored server-side.
    const token = cookieOf(res).split('=')[1] ?? '';
    expect([...sessions.sessions.keys()]).not.toContain(token);
    const row = audit.rows.find((r) => r.requestId === 'req-login-0001');
    expect(row).toMatchObject({ action: 'AUTH_LOGIN_SUCCESS', result: 'SUCCESS', category: 'SECURITY', actorType: 'USER', actorLogin: 'inspector', retentionClass: 'SECURITY', userAgent: 'vitest', route: '/auth/login', statusCode: 200 });
    expect(row?.userId).toBe((body as unknown as { user: { id: string } }).user.id);
  });

  it('refuses wrong passwords, locks the account after 5 failures and audits each attempt', async () => {
    for (let i = 0; i < 4; i += 1) {
      const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector', password: 'wrong-password-1' } });
      expect(res.statusCode).toBe(401);
      expect(res.json().code).toBe('INVALID_CREDENTIALS');
    }
    const fifth = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector', password: 'wrong-password-1' } });
    expect(fifth.statusCode).toBe(423);
    expect(fifth.json()).toMatchObject({ code: 'ACCOUNT_LOCKED', details: { attempts: 5, retry_after_min: 15 } });
    // Even the right password is refused while locked.
    const locked = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector', password: PASSWORD } });
    expect(locked.statusCode).toBe(423);
    const actions = audit.rows.map((r) => r.action);
    expect(actions.filter((a) => a === 'AUTH_LOGIN_FAILED')).toHaveLength(4);
    expect(actions.filter((a) => a === 'AUTH_LOCKED')).toHaveLength(2);
    const failed = audit.rows.find((r) => r.action === 'AUTH_LOGIN_FAILED');
    expect(failed).toMatchObject({ result: 'DENIED', actorType: 'ANONYMOUS', actorLogin: 'inspector', category: 'SECURITY' });
    expect(failed?.details).toMatchObject({ reason: 'INVALID_CREDENTIALS', error_code: 'INVALID_CREDENTIALS' });
  });

  it('does not reveal whether a login exists', async () => {
    const unknown = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'nobody', password: 'x' } });
    const wrong = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector3', password: 'x' } });
    expect(unknown.statusCode).toBe(401);
    expect(wrong.statusCode).toBe(401);
    expect(unknown.json().detail).toBe(wrong.json().detail);
  });

  it('blocks an address after 20 failed logins in 10 minutes', async () => {
    for (let i = 0; i < 20; i += 1) {
      await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: `ghost${i}`, password: 'x' } });
    }
    const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector3', password: PASSWORD } });
    expect(res.statusCode).toBe(429);
    expect(res.json()).toMatchObject({ code: 'IP_TEMPORARILY_BLOCKED', details: { retry_after_min: 30 } });
  });

  it('serves /auth/me and enforces rbac.yaml permissions with scopes', async () => {
    const inspector = await login('inspector');
    const me = await http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: as(inspector) });
    expect(me.statusCode).toBe(200);
    expect(me.json().csrf_token).toBe(inspector.csrf);
    // The single INSPECTOR super-role has every permission with scope ALL: another inspector sees the same objects.
    expect((await http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A', headers: as(inspector) })).statusCode).toBe(200);
    const inspector2 = await login('inspector2');
    expect((await http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A', headers: as(inspector2) })).statusCode).toBe(200);
    const list = await http.inject({ method: 'GET', url: '/api/v1/admin/users?role=INSPECTOR', headers: as(inspector) });
    expect(list.statusCode).toBe(200);
    expect(list.json().items.map((u: { login: string }) => u.login)).toEqual(['inspector', 'inspector2', 'inspector3', 'newbie']);
    const roles = await http.inject({ method: 'GET', url: '/api/v1/admin/roles', headers: as(inspector) });
    expect(roles.json().roles).toEqual(['INSPECTOR']);
    const decide = roles.json().permissions.find((p: { code: string }) => p.code === 'finding.decide');
    expect(decide.grants).toEqual({ INSPECTOR: 'ALL' });
  });

  it('requires the CSRF token on mutations and audits denied mutations', async () => {
    const admin = await login('inspector3');
    const noCsrf = await http.inject({
      method: 'POST',
      url: '/api/v1/admin/batch-runs/import',
      payload: { run_dir: 'nope' },
      headers: { cookie: admin.cookie, 'x-request-id': 'req-csrf-00001' },
    });
    expect(noCsrf.statusCode).toBe(403);
    expect(noCsrf.json().code).toBe('CSRF_TOKEN_INVALID');
    expect(audit.rows.find((r) => r.requestId === 'req-csrf-00001')).toMatchObject({ action: 'BATCH_RUN_IMPORTED', result: 'DENIED', actorLogin: 'inspector3', httpMethod: 'POST' });
    // With the token the admin reaches the handler (404: the run directory does not exist) — still audited.
    const ok = await http.inject({ method: 'POST', url: '/api/v1/admin/batch-runs/import', payload: { run_dir: 'nope' }, headers: as(admin, { 'x-request-id': 'req-import-0001' }) });
    expect(ok.statusCode).toBe(404);
    expect(audit.rows.find((r) => r.requestId === 'req-import-0001')).toMatchObject({ action: 'BATCH_RUN_IMPORTED', result: 'FAILURE', objectType: 'BATCH_RUN', objectId: 'nope', statusCode: 404 });
  });

  it('forces a pending password change before anything else', async () => {
    const newbie = await login('newbie');
    expect(newbie.body.must_change_password).toBe(true);
    const blocked = await http.inject({ method: 'GET', url: '/api/v1/objects', headers: as(newbie) });
    expect(blocked.statusCode).toBe(403);
    expect(blocked.json().code).toBe('PASSWORD_CHANGE_REQUIRED');
    expect((await http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: as(newbie) })).statusCode).toBe(200);
    const weak = await http.inject({
      method: 'POST',
      url: '/api/v1/auth/password',
      payload: { current_password: PASSWORD, new_password: 'newbie' },
      headers: as(newbie),
    });
    expect(weak.statusCode).toBe(422);
    expect(weak.json()).toMatchObject({ code: 'PASSWORD_POLICY_VIOLATION' });
    expect(weak.json().detail).toContain('короче 12 символов');
    expect(weak.json().detail).toContain('совпадает с логином');
    const reuse = await http.inject({ method: 'POST', url: '/api/v1/auth/password', payload: { current_password: PASSWORD, new_password: PASSWORD }, headers: as(newbie) });
    expect(reuse.json().detail).toContain('совпадает с одним из последних 5 паролей');
    const other = await login('newbie'); // a second session, revoked by the change
    const good = await http.inject({ method: 'POST', url: '/api/v1/auth/password', payload: { current_password: PASSWORD, new_password: 'Новый-пароль-2026!' }, headers: as(newbie) });
    expect(good.statusCode).toBe(204);
    expect((await http.inject({ method: 'GET', url: '/api/v1/objects', headers: as(newbie) })).statusCode).toBe(200);
    expect((await http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: as(other) })).statusCode).toBe(401);
    await login('newbie', 'Новый-пароль-2026!');
    expect(audit.rows.some((r) => r.action === 'AUTH_PASSWORD_CHANGED' && r.result === 'SUCCESS')).toBe(true);
  });

  it('issues single-use step-up tokens bound to the session', async () => {
    const supervisor = await login('inspector3');
    const bad = await http.inject({ method: 'POST', url: '/api/v1/auth/reauth', payload: { password: 'wrong' }, headers: as(supervisor) });
    expect(bad.statusCode).toBe(401);
    const res = await http.inject({ method: 'POST', url: '/api/v1/auth/reauth', payload: { password: PASSWORD }, headers: as(supervisor) });
    expect(res.statusCode).toBe(200);
    const token = res.json().reauth_token as string;
    const auth = t.app.get(AuthService);
    const resolved = await auth.resolve(supervisor.cookie.split('=')[1] ?? '');
    const principal = resolved!.principal;
    await expect(auth.consumeReauthToken(token, principal)).resolves.toBeUndefined();
    await expect(auth.consumeReauthToken(token, principal)).rejects.toMatchObject({ code: 'REAUTH_REQUIRED' });
    await expect(auth.consumeReauthToken(undefined, principal)).rejects.toMatchObject({ code: 'REAUTH_REQUIRED' });
  });

  it('ends sessions on logout, on idle/absolute expiry, and evicts beyond 3 per user', async () => {
    const s1 = await login('inspector3');
    const logout = await http.inject({ method: 'POST', url: '/api/v1/auth/logout', headers: as(s1) });
    expect(logout.statusCode).toBe(204);
    expect(String(logout.headers['set-cookie'])).toContain('Max-Age=0');
    const after = await http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: as(s1) });
    expect(after.statusCode).toBe(401);
    expect(after.json().code).toBe('SESSION_EXPIRED');

    const s2 = await login('inspector3');
    sessions.skewMs = 31 * 60_000; // idle timeout 30 min
    expect((await http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: as(s2) })).json().code).toBe('SESSION_EXPIRED');
    sessions.skewMs = 0;

    const four = [await login('inspector3'), await login('inspector3'), await login('inspector3'), await login('inspector3')];
    const alive = await Promise.all(four.map((s) => http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: as(s) })));
    expect(alive.map((r) => r.statusCode)).toEqual([401, 200, 200, 200]);
  });

  it('answers 503 when the session store is down', async () => {
    const s = await login('inspector3');
    sessions.down = true;
    const res = await http.inject({ method: 'GET', url: '/api/v1/auth/me', headers: as(s) });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toMatchObject({ code: 'SESSION_STORE_UNAVAILABLE', retryable: true });
  });

  it('shows the whole audit log to every inspector', async () => {
    await login('inspector');
    const inspector = await login('inspector');
    const supervisor = await login('inspector3');
    const own = await http.inject({ method: 'GET', url: '/api/v1/audit?page_size=200', headers: as(inspector) });
    expect(own.statusCode).toBe(200);
    expect(own.json().items.length).toBeGreaterThan(0);
    const all = await http.inject({ method: 'GET', url: '/api/v1/audit?action=AUTH_LOGIN_SUCCESS', headers: as(supervisor) });
    expect(all.statusCode).toBe(200);
    const items = all.json().items as Array<{ actor_login: string; action_label: string }>;
    expect(items.map((i) => i.actor_login).sort()).toEqual(['inspector', 'inspector', 'inspector3']);
    expect(items[0]?.action_label).toBe('Вход в систему');
    const badFilter = await http.inject({ method: 'GET', url: '/api/v1/audit?action=NOPE', headers: as(supervisor) });
    expect(badFilter.statusCode).toBe(400);
  });

  it('never breaks a response when the audit write fails', async () => {
    audit.failWith = new Error('connection refused');
    const service = t.app.get(AuditService) as unknown as { logger: { error: (...args: unknown[]) => void } };
    const spy = vi.spyOn(service.logger, 'error');
    const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'inspector3', password: PASSWORD } });
    expect(res.statusCode).toBe(200);
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ event: 'audit_write_failed' }), expect.any(String));
    expect(audit.rows).toHaveLength(0);
    spy.mockRestore();
  });
});

describe('optional mode (local development)', () => {
  it('lets requests without a session through as anonymous and still enforces a present session', async () => {
    const t = await createTestApp({ authMode: 'optional' });
    try {
      expect((await t.http.inject({ method: 'GET', url: '/api/v1/objects' })).statusCode).toBe(200);
      expect((await t.http.inject({ method: 'GET', url: '/api/v1/auth/me' })).statusCode).toBe(401);
      const stale = await t.http.inject({ method: 'GET', url: '/api/v1/objects', headers: { cookie: 'ii_sid=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' } });
      expect(stale.statusCode).toBe(401);
      expect(stale.json().code).toBe('SESSION_EXPIRED');
    } finally {
      await t.close();
    }
  });

  it('is refused in demo and prod', () => {
    expect(() => loadConfig({ INSPECTOR_APP_ENV: 'demo', INSPECTOR_AUTH_MODE: 'optional' })).toThrow(/INSPECTOR_AUTH_MODE/);
    expect(loadConfig({ INSPECTOR_APP_ENV: 'demo' }).authMode).toBe('required');
    expect(loadConfig({ INSPECTOR_APP_ENV: 'local' }).authMode).toBe('optional');
  });
});
