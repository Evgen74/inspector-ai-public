/** «Архивировать»: objects, imported runs and upload processes disappear from lists and the dashboard by default. */
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { AuditRepository } from '../src/modules/audit/audit.repository';
import { UsersRepository } from '../src/modules/auth/users.repository';
import { UploadJob } from '../src/modules/upload/upload-job';
import { newRecord } from '../src/modules/upload/process-store';
import {
  createTestApp,
  organizerRow,
  SHA,
  syntheticRunManifest,
  type TestApp,
  writeOrganizerManifest,
  writeRunDir,
} from './helpers';
import type { InMemoryAudit, InMemoryUsers } from './platform-fakes';

const PASSWORD = 'Demo-Inspector-2026';

describe('archive admin action', () => {
  let t: TestApp;
  let admin: Record<string, string>;
  let inspector: Record<string, string>;

  async function login(name: string, roles: string[]): Promise<Record<string, string>> {
    await (t.app.get(UsersRepository) as InMemoryUsers).add({ login: name, password: PASSWORD, roles });
    const res = await t.http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: name, password: PASSWORD } });
    return { cookie: String(res.headers['set-cookie']).split(';')[0] ?? '', 'x-csrf-token': res.json().csrf_token };
  }

  const get = (url: string) => t.http.inject({ method: 'GET', url: `/api/v1${url}`, headers: { cookie: admin.cookie as string } });
  const archive = (url: string, body?: unknown, who = admin) =>
    t.http.inject({ method: 'POST', url: `/api/v1${url}`, payload: body as string | undefined, headers: who });

  beforeAll(async () => {
    t = await createTestApp({ authMode: 'required' });
    admin = await login('admin', ['INSPECTOR']);
    inspector = await login('inspector', ['INSPECTOR']);
    const sha = writeOrganizerManifest(t.config.dataRoot, [
      organizerRow('F9001', 'OBJ-KEEP', SHA(1), { corpus: 'Рабочий объект' }),
      organizerRow('F9002', 'OBJ-STALE', SHA(2), { corpus: 'Устаревший объект' }),
    ]);
    const objs = [
      { object_id: 'OBJ-KEEP', split: 'TRAIN_PUBLIC' as const },
      { object_id: 'OBJ-STALE', split: 'TRAIN_PUBLIC' as const },
    ];
    const files = [
      { file_id: 'F9001', object_id: 'OBJ-KEEP', sha256: SHA(1), manifest_stage: 'PD' },
      { file_id: 'F9002', object_id: 'OBJ-STALE', sha256: SHA(2), manifest_stage: 'PD' },
    ];
    for (const [dir, runId] of [['run-a', 'fixture-run'], ['run-b', 'real-run']] as const) {
      writeRunDir(t.config.runsRoot, dir, syntheticRunManifest({ runId, manifestSha256: sha, objects: objs, files }));
      const res = await t.http.inject({
        method: 'POST',
        url: '/api/v1/admin/batch-runs/import',
        payload: { run_dir: dir },
        headers: admin,
      });
      expect(res.statusCode).toBe(201);
    }
  });
  afterAll(async () => t.close());

  it('hides an archived object from /objects and the dashboard, and brings it back', async () => {
    expect(((await get('/objects')).json().items as Array<{ object_id: string }>).map((o) => o.object_id)).toEqual(['OBJ-KEEP', 'OBJ-STALE']);
    const res = await archive('/admin/objects/OBJ-STALE/archive');
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ kind: 'OBJECT', id: 'OBJ-STALE', archived: true });
    expect(res.json().archived_at).toMatch(/^\d{4}-/);

    const ids = async (url: string, key = 'items', field = 'object_id') =>
      ((await get(url)).json()[key] as Array<Record<string, string>>).map((o) => o[field]);
    expect(await ids('/objects')).toEqual(['OBJ-KEEP']);
    expect(await ids('/dashboard')).toEqual(['OBJ-KEEP']);
    expect((await get('/dashboard')).json().tiles.total).toBe(1);
    expect(await ids('/objects?include_archived=true')).toEqual(['OBJ-KEEP', 'OBJ-STALE']);
    expect(await ids('/dashboard?include_archived=true')).toEqual(['OBJ-KEEP', 'OBJ-STALE']);
    expect((await get('/objects/OBJ-STALE')).statusCode).toBe(200); // a direct link still opens

    const back = await archive('/admin/objects/OBJ-STALE/archive', { archived: false });
    expect(back.json()).toMatchObject({ archived: false, archived_at: null });
    expect(await ids('/objects')).toEqual(['OBJ-KEEP', 'OBJ-STALE']);
  });

  it('hides an archived run from /admin/batch-runs', async () => {
    const runs = async (url: string) => ((await get(url)).json().items as Array<{ batch_run_id: string }>).map((r) => r.batch_run_id).sort();
    expect(await runs('/admin/batch-runs')).toEqual(['fixture-run', 'real-run']);
    const res = await archive('/admin/batch-runs/fixture-run/archive');
    expect(res.json()).toMatchObject({ kind: 'BATCH_RUN', id: 'fixture-run', archived: true });
    expect(await runs('/admin/batch-runs')).toEqual(['real-run']);
    expect(await runs('/admin/batch-runs?include_archived=true')).toEqual(['fixture-run', 'real-run']);
  });

  it('hides an archived upload process from /processes', async () => {
    const job = t.app.get(UploadJob);
    const rec = newRecord({ processId: '00000000-0000-7000-8000-0000000000aa', objectId: 'OBJ-UPLOAD-x', objectName: 'Старая загрузка', address: null, registryFile: null, files: [] });
    job.store.create(rec);
    const ids = async (url: string) => ((await get(url)).json().items as Array<{ process_id: string }>).map((p) => p.process_id);
    expect(await ids('/processes')).toContain(rec.process_id);
    const res = await archive(`/processes/${rec.process_id}/archive`);
    expect(res.json()).toMatchObject({ kind: 'PROCESS', archived: true });
    expect(await ids('/processes')).not.toContain(rec.process_id);
    expect(await ids('/processes?include_archived=true')).toContain(rec.process_id);
    await archive(`/processes/${rec.process_id}/archive`, { archived: false });
    expect(await ids('/processes')).toContain(rec.process_id);
  });

  it('answers 404 for unknown targets and 401 without a session', async () => {
    expect((await archive('/admin/objects/NOPE/archive')).statusCode).toBe(404);
    expect((await archive('/admin/batch-runs/nope/archive')).statusCode).toBe(404);
    expect((await archive('/processes/00000000-0000-7000-8000-00000000ffff/archive')).statusCode).toBe(404);
    const anonymous = await t.http.inject({ method: 'POST', url: '/api/v1/admin/objects/OBJ-KEEP/archive' });
    expect(anonymous.statusCode).toBe(401);
    expect((await get('/objects')).json().items).toHaveLength(2);
  });

  it('writes an audit row for every archive call', async () => {
    const rows = (t.app.get(AuditRepository) as InMemoryAudit).rows;
    const mine = rows.filter((r) => r.action === 'HTTP_POST' && ['OBJECT', 'BATCH_RUN', 'PROCESS'].includes(String(r.objectType)));
    expect(mine.length).toBeGreaterThanOrEqual(4);
  });
});
