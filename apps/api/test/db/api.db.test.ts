/**
 * End-to-end through the real AppModule, Drizzle repositories and PostgreSQL (database inspector_test).
 * Run: pnpm --filter @inspector/api test:db
 */
import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import type { NestFastifyApplication } from '@nestjs/platform-fastify';
import type { FastifyInstance } from 'fastify';
import { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../../src/app.module';
import { configureApp, createFastifyAdapter } from '../../src/bootstrap';
import { loadConfig } from '../../src/config/config';
import { testDatabaseUrl } from '../../src/db/create-db';
import { organizerRow, SHA, syntheticRunManifest, tmpDir, writeOrganizerManifest, writeRunDir } from '../helpers';

describe('API on PostgreSQL', () => {
  const url = testDatabaseUrl();
  const config = loadConfig(
    { INSPECTOR_APP_ENV: 'test', INSPECTOR_DATABASE_URL: url, INSPECTOR_LOG_LEVEL: 'silent' },
    { runsRoot: tmpDir('db-runs'), dataRoot: tmpDir('db-data') },
  );
  let app: NestFastifyApplication;
  let http: FastifyInstance;
  let pool: Pool;
  let organizerSha: string;

  beforeAll(async () => {
    app = await NestFactory.create<NestFastifyApplication>(AppModule.forRoot(config), createFastifyAdapter(), {
      logger: false,
    });
    await configureApp(app);
    http = app.getHttpAdapter().getInstance();
    pool = new Pool({ connectionString: url, max: 2 });
    organizerSha = writeOrganizerManifest(config.dataRoot, [
      organizerRow('F9001', 'OBJ-DB-A', SHA(1), { corpus: 'Объект А' }),
      organizerRow('F9002', 'OBJ-DB-A', SHA(2), { stage: 'RD' }),
      organizerRow('F9003', 'OBJ-DB-A', SHA(3), { stage: 'RD_ID_MIXED' }),
      organizerRow('F9004', 'OBJ-DB-B', SHA(4), { corpus: 'Объект Б', stage: 'ID' }),
    ]);
  });

  afterAll(async () => {
    await pool?.end();
    await app?.close();
  });

  beforeEach(async () => {
    // CASCADE: processes, protocols, checks … (import v2, AG-00) reference runs, objects and files.
    await pool.query('TRUNCATE files, objects, runs CASCADE');
  });

  const manifest = (runId: string) =>
    syntheticRunManifest({
      runId,
      manifestSha256: organizerSha,
      objects: [
        { object_id: 'OBJ-DB-A', split: 'TRAIN_PUBLIC' },
        { object_id: 'OBJ-DB-B', split: 'TRAIN_PUBLIC' },
      ],
      files: [
        { file_id: 'F9001', object_id: 'OBJ-DB-A', sha256: SHA(1), manifest_stage: 'PD' },
        { file_id: 'F9002', object_id: 'OBJ-DB-A', sha256: SHA(2), manifest_stage: 'RD' },
        { file_id: 'F9003', object_id: 'OBJ-DB-A', sha256: SHA(3), manifest_stage: 'RD_ID_MIXED' },
        { file_id: 'F9004', object_id: 'OBJ-DB-B', sha256: SHA(4), manifest_stage: 'ID', local_status: 'MISSING_ON_DISK' },
      ],
    });

  it('reports the database as up', async () => {
    const res = await http.inject({ method: 'GET', url: '/api/v1/health' });
    expect(res.statusCode).toBe(200);
    expect(res.json().checks.database.status).toBe('up');
  });

  it('imports a run, then lists objects with stage counts and files', async () => {
    writeRunDir(config.runsRoot, 'run-1', manifest('run-1'));
    const imported = await http.inject({ method: 'POST', url: '/api/v1/admin/batch-runs/import', payload: { run_dir: 'run-1' } });
    expect(imported.statusCode).toBe(201);
    expect(imported.json().warnings.map((w: { code: string }) => w.code)).toEqual(['FILE_MISSING_ON_DISK']);

    const objects = (await http.inject({ method: 'GET', url: '/api/v1/objects' })).json();
    expect(objects.total).toBe(2);
    expect(objects.items[0]).toMatchObject({
      object_id: 'OBJ-DB-A',
      name: 'Объект А',
      files_total: 3,
      files_present: 3,
      files_by_stage: { PD: 1, RD: 1, ID: 0, RD_ID_MIXED: 1, UNKNOWN: 0 },
      last_run: { batch_run_id: 'run-1' },
    });
    expect(objects.items[1]).toMatchObject({ object_id: 'OBJ-DB-B', files_missing_on_disk: 1, files_present: 0 });

    const files = (await http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-DB-A/files?stage=RD' })).json();
    expect(files).toMatchObject({ total: 1, items: [{ file_id: 'F9002', file_name: 'F9002 том.pdf', manifest_stage: 'RD' }] });

    // Case-insensitive Cyrillic search: «а» finds «Объект А» only («Объект Б» has no «а»).
    const search = (await http.inject({ method: 'GET', url: '/api/v1/objects?q=%D0%B0' })).json();
    expect(search.items.map((o: { object_id: string }) => o.object_id)).toEqual(['OBJ-DB-A']);

    const card = (await http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-DB-B' })).json();
    expect(card).toMatchObject({ object_id: 'OBJ-DB-B', split: 'TRAIN_PUBLIC', input_manifest_hash: SHA(11) });
  });

  it('re-imports idempotently (200, same run id) and keeps first import time', async () => {
    writeRunDir(config.runsRoot, 'run-2', manifest('run-2'));
    const first = (await http.inject({ method: 'POST', url: '/api/v1/admin/batch-runs/import', payload: { run_dir: 'run-2' } })).json();
    const again = await http.inject({ method: 'POST', url: '/api/v1/admin/batch-runs/import', payload: { run_dir: 'run-2' } });
    expect(again.statusCode).toBe(200);
    expect(again.json().run.id).toBe(first.run.id);
    expect(again.json().run.imported_at).toBe(first.run.imported_at);
    const counts = await pool.query('SELECT (SELECT count(*) FROM runs)::int AS runs, (SELECT count(*) FROM files)::int AS files');
    expect(counts.rows[0]).toEqual({ runs: 1, files: 4 });
    const runs = (await http.inject({ method: 'GET', url: '/api/v1/admin/batch-runs' })).json();
    expect(runs.items[0]).toMatchObject({ batch_run_id: 'run-2', files_count: 4, warnings_count: 1 });
  });

  it('refuses a changed file hash (409) and the DB trigger guards file identity', async () => {
    writeRunDir(config.runsRoot, 'run-3', manifest('run-3'));
    expect((await http.inject({ method: 'POST', url: '/api/v1/admin/batch-runs/import', payload: { run_dir: 'run-3' } })).statusCode).toBe(201);
    const changed = syntheticRunManifest({
      runId: 'run-4',
      objects: [{ object_id: 'OBJ-DB-A', split: 'TRAIN_PUBLIC' }],
      files: [{ file_id: 'F9001', object_id: 'OBJ-DB-A', sha256: SHA(123), manifest_stage: 'PD' }],
    });
    writeRunDir(config.runsRoot, 'run-4', changed);
    const res = await http.inject({ method: 'POST', url: '/api/v1/admin/batch-runs/import', payload: { run_dir: 'run-4' } });
    expect(res.statusCode).toBe(409);
    expect(res.json().code).toBe('FILE_ID_IMMUTABLE');
    const runs = await pool.query('SELECT batch_run_id FROM runs');
    expect(runs.rows).toEqual([{ batch_run_id: 'run-3' }]);
    await expect(pool.query(`UPDATE files SET file_hash = '${SHA(5)}' WHERE id = 'F9001'`)).rejects.toThrow(/FILE_ID_IMMUTABLE/);
  });

  it('carries owner comments on the tables (90 §3.3.1 W5)', async () => {
    const res = await pool.query(
      "SELECT c.relname, obj_description(c.oid) AS comment FROM pg_class c WHERE c.relname IN ('runs','objects','files') ORDER BY 1",
    );
    expect(res.rows.map((r: { comment: string }) => r.comment.split(';')[0])).toEqual(['owner=B01', 'owner=B01', 'owner=B00']);
  });
});
