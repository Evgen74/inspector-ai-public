/**
 * Evidence viewer endpoints over a fake ml-api: page view (OpenSeadragon tile source), tiles and crops, the disk
 * cache and in-flight de-duplication, ETag/304, train-only and assignment checks, renderer outages.
 */
import { existsSync, rmSync } from 'node:fs';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { UsersRepository } from '../../src/modules/auth/users.repository';
import { MlApiClient } from '../../src/modules/render/ml-api.client';
import { RenderFilesRepository, RenderService } from '../../src/modules/render/render.service';
import { createTestApp, SHA, type TestApp, tmpDir } from '../helpers';
import type { FakeMlApi, InMemoryRenderFiles, InMemoryUsers } from '../platform-fakes';

const PASSWORD = 'Demo-Inspector-2026';

describe('page viewer', () => {
  let t: TestApp;
  let http: FastifyInstance;
  let ml: FakeMlApi;
  let filesRepo: InMemoryRenderFiles;
  let cacheRoot: string;
  const headers: Record<string, Record<string, string>> = {};

  let users: InMemoryUsers;

  beforeAll(async () => {
    cacheRoot = tmpDir('cache');
    t = await createTestApp({ authMode: 'required', cacheRoot });
    http = t.http;
    ml = t.app.get(MlApiClient) as FakeMlApi;
    filesRepo = t.app.get(RenderFilesRepository) as InMemoryRenderFiles;
    users = t.app.get(UsersRepository) as InMemoryUsers;
  });

  beforeEach(async () => {
    rmSync(path.join(cacheRoot, 'render'), { recursive: true, force: true });
    ml.calls = [];
    ml.down = false;
    ml.delayMs = 0;
    ml.shaByFile.clear();
    users.users.clear();
    users.assignments.clear();
    const service = t.app.get(RenderService);
    Object.assign(service.stats, { hits: 0, misses: 0, shared: 0 });
    ml.sha256 = SHA(201);
    ml.shaByFile.set('F0202', SHA(202));
    const base = { objectId: 'OBJ-SYNTH-A', split: 'TRAIN_PUBLIC', extension: '.pdf', localStatus: 'PRESENT', pdfPages: 3 };
    filesRepo.files.set('F0201', { fileId: 'F0201', sha256: SHA(201), ...base });
    filesRepo.files.set('F0202', { fileId: 'F0202', sha256: SHA(202), ...base, objectId: 'OBJ-SYNTH-B' });
    filesRepo.files.set('F9300', { fileId: 'F9300', sha256: SHA(300), ...base, extension: '.dwg' });
    filesRepo.files.set('F9301', { fileId: 'F9301', sha256: SHA(301), ...base, localStatus: 'MISSING_ON_DISK' });
    filesRepo.files.set('F0900', { fileId: 'F0900', sha256: SHA(900), ...base, objectId: 'OBJ-SYNTH-HIDDEN', split: 'TEST_HIDDEN' });
    await users.add({ login: 'inspector', password: PASSWORD, roles: ['INSPECTOR'], objects: ['OBJ-SYNTH-A'] });
    await users.add({ login: 'second', password: PASSWORD, roles: ['INSPECTOR'] });
    for (const login of ['inspector', 'second']) {
      const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login, password: PASSWORD } });
      headers[login] = { cookie: String(res.headers['set-cookie']).split(';')[0] ?? '' };
    }
  });

  afterAll(async () => {
    await t.close();
  });

  const get = (url: string, who = 'inspector', extra: Record<string, string> = {}) =>
    http.inject({ method: 'GET', url: `/api/v1${url}`, headers: { ...headers[who], ...extra } });

  it('describes a page as an OpenSeadragon tile source', async () => {
    const res = await get('/files/F0201/pages/2');
    expect(res.statusCode, res.body).toBe(200);
    expect(res.json()).toEqual({
      file_id: 'F0201',
      object_id: 'OBJ-SYNTH-A',
      page_no: 2,
      pdf_pages: 3,
      width_pt: 2384,
      height_pt: 3370,
      rotation: 0,
      max_dpi: 288,
      width_px: 9536,
      height_px: 13480,
      tile_size: 512,
      tile_overlap: 0,
      min_level: 0,
      max_level: 14,
      tile_url_template: '/api/v1/files/F0201/pages/2/tiles/{level}/{x}/{y}',
      image_url: '/api/v1/files/F0201/pages/2/image',
    });
  });

  it('serves tiles from the disk cache after the first render, with ETag and 304', async () => {
    const first = await get('/files/F0201/pages/2/tiles/13/5/3');
    expect(first.statusCode).toBe(200);
    expect(first.headers['content-type']).toBe('image/png');
    expect(first.headers['cache-control']).toBe('private, max-age=86400, immutable');
    expect(first.headers['x-render-cache']).toBe('miss');
    expect(first.rawPayload.subarray(1, 4).toString()).toBe('PNG');
    const second = await get('/files/F0201/pages/2/tiles/13/5/3');
    expect(second.headers['x-render-cache']).toBe('hit');
    expect(second.rawPayload.equals(first.rawPayload)).toBe(true);
    expect(ml.calls.filter((c) => c.route === 'tile')).toEqual([{ route: 'tile', body: { file_id: 'F0201', page_no: 2, level: 13, x: 5, y: 3 } }]);
    expect(existsSync(path.join(cacheRoot, 'render', 'v1', SHA(201), 'p00002', 't_L13_5_3.png'))).toBe(true);
    const etag = String(first.headers.etag);
    const notModified = await get('/files/F0201/pages/2/tiles/13/5/3', 'inspector', { 'if-none-match': etag });
    expect(notModified.statusCode).toBe(304);
    expect(notModified.rawPayload.length).toBe(0);
  });

  it('renders a page or a normalized crop, shares concurrent renders', async () => {
    ml.delayMs = 50;
    const results = await Promise.all([1, 2, 3, 4].map(() => get('/files/F0201/pages/1/image?width=800')));
    expect(results.map((r) => r.statusCode)).toEqual([200, 200, 200, 200]);
    expect(ml.calls.filter((c) => c.route === 'page')).toHaveLength(1);
    expect(t.app.get(RenderService).stats.shared).toBe(3);
    const crop = await get('/files/F0201/pages/1/image?bbox=0.41,0.22,0.58,0.37&dpi=150');
    expect(crop.statusCode).toBe(200);
    expect(ml.calls.at(-1)).toEqual({ route: 'crop', body: { file_id: 'F0201', page_no: 1, dpi: 150, bbox: [0.41, 0.22, 0.58, 0.37] } });
    const bad = await get('/files/F0201/pages/1/image?bbox=0.5,0.5,0.4,0.9');
    expect(bad.statusCode).toBe(400);
    expect(bad.json().code).toBe('VALIDATION_ERROR');
  });

  it.each([
    ['/files/F0900/pages/1', 403, 'HIDDEN_TEST_ACCESS_DENIED'],
    ['/files/F9300/pages/1', 422, 'FILE_NOT_RENDERABLE'],
    ['/files/F9301/pages/1', 422, 'FILE_NOT_RENDERABLE'],
    ['/files/F9404/pages/1', 404, 'FILE_NOT_FOUND'],
    ['/files/F0201/pages/9', 404, 'PAGE_NOT_FOUND'],
    ['/files/F0201/pages/0', 400, 'VALIDATION_ERROR'],
  ])('refuses %s with %i %s and never calls the renderer', async (url, status, code) => {
    const res = await get(url);
    expect(res.statusCode).toBe(status);
    expect(res.json().code).toBe(code);
    expect(ml.calls).toHaveLength(0);
  });

  it('lets every inspector (scope ALL) see every train object, but never the hidden one', async () => {
    expect((await get('/files/F0202/pages/1')).statusCode).toBe(200);
    expect((await get('/files/F0202/pages/1', 'second')).statusCode).toBe(200);
    expect((await get('/files/F0900/pages/1', 'second')).json().code).toBe('HIDDEN_TEST_ACCESS_DENIED');
  });

  it('answers 503 PAGE_RENDERER_UNAVAILABLE when the ml-api is down, and refuses a file with another hash', async () => {
    ml.down = true;
    const down = await get('/files/F0201/pages/1/tiles/0/0/0');
    expect(down.statusCode).toBe(503);
    expect(down.json()).toMatchObject({ code: 'PAGE_RENDERER_UNAVAILABLE', retryable: true });
    ml.down = false;
    ml.sha256 = SHA(999);
    const drift = await get('/files/F0201/pages/1/tiles/0/0/0');
    expect(drift.statusCode).toBe(503);
    expect(drift.json().detail).toContain('другой файл F0201');
    expect(existsSync(path.join(cacheRoot, 'render', 'v1', SHA(201), 'p00001', 't_L0_0_0.png'))).toBe(false);
  });
});
