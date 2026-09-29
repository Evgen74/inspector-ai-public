import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { contractSchemas, createTestApp, SHA, syntheticRunManifest, type TestApp, writeRunDir } from './helpers';

function expectProblem(res: { statusCode: number; headers: Record<string, unknown>; json(): unknown }, status: number, code: string) {
  expect(res.statusCode).toBe(status);
  expect(String(res.headers['content-type'])).toContain('application/problem+json');
  const body = res.json() as Record<string, unknown>;
  expect(body.code).toBe(code);
  expect(body.request_id).toBe(res.headers['x-request-id']);
  // Every problem body satisfies the contract schema (packages/contracts/schemas/problem.schema.json).
  expect(contractSchemas().validate('problem', body)).toEqual({ valid: true });
  return body;
}

describe('objects API', () => {
  let t: TestApp;
  beforeAll(async () => {
    t = await createTestApp();
  });
  afterAll(async () => {
    await t.close();
  });
  beforeEach(() => {
    t.store.failWith = null;
  });

  it('lists no objects before any import', async () => {
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/objects' });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ items: [], total: 0, page: 1, page_size: 50 });
  });

  describe('after importing a run with two objects', () => {
    beforeAll(async () => {
      const manifest = syntheticRunManifest({
        objects: [
          { object_id: 'OBJ-SYNTH-A', split: 'TRAIN_PUBLIC' },
          { object_id: 'OBJ-SYNTH-B', split: 'TRAIN_PUBLIC' },
        ],
        files: [
          { file_id: 'F9001', object_id: 'OBJ-SYNTH-A', sha256: SHA(1), manifest_stage: 'PD' },
          { file_id: 'F9002', object_id: 'OBJ-SYNTH-A', sha256: SHA(2), manifest_stage: 'PD' },
          { file_id: 'F9003', object_id: 'OBJ-SYNTH-A', sha256: SHA(3), manifest_stage: 'RD' },
          { file_id: 'F9004', object_id: 'OBJ-SYNTH-A', sha256: SHA(4), manifest_stage: 'ID', local_status: 'MISSING_ON_DISK' },
          { file_id: 'F9005', object_id: 'OBJ-SYNTH-A', sha256: SHA(5), manifest_stage: 'RD_ID_MIXED' },
          { file_id: 'F9006', object_id: 'OBJ-SYNTH-B', sha256: SHA(6), manifest_stage: 'UNKNOWN' },
        ],
      });
      writeRunDir(t.config.runsRoot, 'run-two-objects', manifest);
      const res = await t.http.inject({
        method: 'POST',
        url: '/api/v1/admin/batch-runs/import',
        payload: { run_dir: 'run-two-objects' },
      });
      expect(res.statusCode).toBe(201);
    });

    it('lists objects with file counts per manifest stage', async () => {
      const res = await t.http.inject({ method: 'GET', url: '/api/v1/objects' });
      expect(res.statusCode).toBe(200);
      const body = res.json();
      expect(body.total).toBe(2);
      expect(body.items.map((o: { object_id: string }) => o.object_id)).toEqual(['OBJ-SYNTH-A', 'OBJ-SYNTH-B']);
      expect(body.items[0]).toMatchObject({
        split: 'TRAIN_PUBLIC',
        indicator_color: 'NONE',
        files_total: 5,
        files_present: 4,
        files_missing_on_disk: 1,
        files_by_stage: { PD: 2, RD: 1, ID: 1, RD_ID_MIXED: 1, UNKNOWN: 0 },
      });
      expect(body.items[0].last_run.batch_run_id).toBe('20260101T000000Z-inventory');
      expect(body.items[1].files_by_stage).toEqual({ PD: 0, RD: 0, ID: 0, RD_ID_MIXED: 0, UNKNOWN: 1 });
    });

    it('paginates and filters the object list', async () => {
      const p2 = await t.http.inject({ method: 'GET', url: '/api/v1/objects?page=2&page_size=1' });
      expect(p2.json()).toMatchObject({ total: 2, page: 2, page_size: 1, items: [{ object_id: 'OBJ-SYNTH-B' }] });
      const q = await t.http.inject({ method: 'GET', url: '/api/v1/objects?q=synth-b' });
      expect(q.json().items.map((o: { object_id: string }) => o.object_id)).toEqual(['OBJ-SYNTH-B']);
    });

    it('returns one object card', async () => {
      const res = await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A' });
      expect(res.statusCode).toBe(200);
      expect(res.json()).toMatchObject({ object_id: 'OBJ-SYNTH-A', input_manifest_hash: SHA(11), address: null });
    });

    it('lists an object files with stage, status and text filters', async () => {
      const all = await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files' });
      expect(all.statusCode).toBe(200);
      expect(all.json().total).toBe(5);
      expect(all.json().items[0]).toMatchObject({ file_id: 'F9001', manifest_stage: 'PD', stage_resolved: 'PD', sha256: SHA(1) });
      const pd = await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files?stage=PD' });
      expect(pd.json().items.map((f: { file_id: string }) => f.file_id)).toEqual(['F9001', 'F9002']);
      const missing = await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files?local_status=MISSING_ON_DISK' });
      expect(missing.json().items.map((f: { file_id: string }) => f.file_id)).toEqual(['F9004']);
      const q = await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files?q=f9003' });
      expect(q.json().total).toBe(1);
      const paged = await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files?page=3&page_size=2' });
      expect(paged.json()).toMatchObject({ total: 5, page: 3, page_size: 2, items: [{ file_id: 'F9005' }] });
    });
  });

  it('404 NOT_FOUND for an unknown object and its files', async () => {
    expectProblem(await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-NOPE' }), 404, 'NOT_FOUND');
    expectProblem(await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-NOPE/files' }), 404, 'NOT_FOUND');
  });

  it('400 VALIDATION_ERROR with pointers for invalid query parameters', async () => {
    const big = expectProblem(await t.http.inject({ method: 'GET', url: '/api/v1/objects?page_size=500' }), 400, 'VALIDATION_ERROR');
    expect(big.errors).toEqual([expect.objectContaining({ pointer: '/query/page_size', field: 'page_size' })]);
    expect(String(big.detail)).toContain('должно быть <= 200');
    const zero = expectProblem(await t.http.inject({ method: 'GET', url: '/api/v1/objects?page=0' }), 400, 'VALIDATION_ERROR');
    expect((zero.errors as Array<{ pointer: string }>)[0]?.pointer).toBe('/query/page');
    const stage = expectProblem(
      await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files?stage=XX' }),
      400,
      'VALIDATION_ERROR',
    );
    expect(String((stage.errors as Array<{ detail: string }>)[0]?.detail)).toContain('RD_ID_MIXED');
    expectProblem(await t.http.inject({ method: 'GET', url: '/api/v1/objects?page=abc' }), 400, 'VALIDATION_ERROR');
  });

  it('503 DB_UNAVAILABLE with Retry-After when the database is unreachable', async () => {
    t.store.failWith = Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/objects' });
    const body = expectProblem(res, 503, 'DB_UNAVAILABLE');
    expect(res.headers['retry-after']).toBe('5');
    expect(body.retryable).toBe(true);
  });

  it('500 INTERNAL_ERROR for unexpected failures, without leaking the message', async () => {
    t.store.failWith = new Error('secret internal detail');
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/objects' });
    const body = expectProblem(res, 500, 'INTERNAL_ERROR');
    expect(JSON.stringify(body)).not.toContain('secret internal detail');
  });

  it('answers HEAD like GET (Fastify auto-route), without a body', async () => {
    const res = await t.http.inject({ method: 'HEAD', url: '/api/v1/objects' });
    expect(res.statusCode).toBe(200);
    expect(res.body).toBe('');
    const bad = await t.http.inject({ method: 'HEAD', url: '/api/v1/objects?page_size=999' });
    expect(bad.statusCode).toBe(400);
  });

  it('404 NOT_FOUND problem for an unknown route', async () => {
    expectProblem(await t.http.inject({ method: 'GET', url: '/api/v1/unknown' }), 404, 'NOT_FOUND');
  });
});
