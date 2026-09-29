import { mkdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import {
  contractSchemas,
  createTestApp,
  organizerRow,
  readContractExample,
  SHA,
  syntheticRunManifest,
  type TestApp,
  tmpDir,
  writeOrganizerManifest,
  writeRunDir,
} from './helpers';

const IMPORT_URL = '/api/v1/admin/batch-runs/import';

describe('POST /api/v1/admin/batch-runs/import', () => {
  let t: TestApp;
  let organizerSha: string;

  beforeAll(async () => {
    t = await createTestApp();
  });
  afterAll(async () => {
    await t.close();
  });
  beforeEach(() => {
    t.store.runs.clear();
    t.store.objects.clear();
    t.store.files.clear();
    organizerSha = writeOrganizerManifest(t.config.dataRoot, [
      organizerRow('F9001', 'OBJ-SYNTH-A', SHA(1), { section: 'AR' }),
      organizerRow('F9002', 'OBJ-SYNTH-A', SHA(2), { stage: 'RD', section: 'KR' }),
      organizerRow('F9003', 'OBJ-SYNTH-A', SHA(3), { stage: 'RD_ID_MIXED', section: 'OV' }),
    ]);
  });

  const post = (payload: unknown, headers: Record<string, string> = {}) =>
    t.http.inject({ method: 'POST', url: IMPORT_URL, payload: payload as string, headers });

  it('imports a run (201), enriches files from the organizer manifest and is idempotent (200)', async () => {
    writeRunDir(t.config.runsRoot, 'run-a', syntheticRunManifest({ manifestSha256: organizerSha }));
    const first = await post({ run_dir: 'run-a' });
    expect(first.statusCode).toBe(201);
    const body = first.json();
    expect(body.created).toBe(true);
    expect(body.files_imported).toBe(3);
    expect(body.warnings).toEqual([]);
    expect(body.objects).toEqual([
      {
        object_id: 'OBJ-SYNTH-A',
        name: 'Корпус OBJ-SYNTH-A',
        split: 'TRAIN_PUBLIC',
        files_total: 3,
        files_present: 3,
        missing_on_disk: [],
      },
    ]);
    expect(body.run).toMatchObject({
      batch_run_id: '20260101T000000Z-inventory',
      producer: 'inspector-batch',
      status: 'SUCCEEDED',
      objects_count: 1,
      files_count: 3,
      warnings_count: 0,
    });
    expect(body.run.manifest_ref).toBe(path.join(realpathSync(t.config.runsRoot), 'run-a', 'run_manifest.json'));

    const files = (await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files' })).json();
    expect(files.items[1]).toMatchObject({
      file_id: 'F9002',
      file_name: 'F9002 том.pdf',
      relative_path: 'Объект/Раздел/F9002 том.pdf',
      manifest_section: 'KR',
      size_bytes: 1234,
      dataset_role: 'UNLABELED_POOL',
      stage_resolved: 'RD',
    });
    expect(files.items[2]).toMatchObject({ file_id: 'F9003', manifest_stage: 'RD_ID_MIXED', stage_resolved: null });

    const again = await post({ run_dir: path.join(t.config.runsRoot, 'run-a') });
    expect(again.statusCode).toBe(200);
    expect(again.json().created).toBe(false);
    expect(again.json().run.id).toBe(body.run.id);

    const runs = (await t.http.inject({ method: 'GET', url: '/api/v1/admin/batch-runs' })).json();
    expect(runs).toMatchObject({ total: 1, items: [{ id: body.run.id }] });
  });

  it('imports the contracts example run manifest', async () => {
    const example = readContractExample<Record<string, unknown>>('run_manifest/valid/tyumen_inventory.json');
    writeRunDir(t.config.runsRoot, 'run-example', example);
    const res = await post({ run_dir: 'run-example' });
    expect(res.statusCode).toBe(201);
    // The example pins another organizer manifest hash: enrichment is skipped with a warning.
    expect(res.json().warnings.map((w: { code: string }) => w.code)).toEqual(['REGISTRY_HASH_MISMATCH']);
    expect(res.json().objects[0]).toMatchObject({ files_total: 58, name: null });
  });

  it('warns and skips enrichment when the organizer manifest hash differs', async () => {
    writeRunDir(t.config.runsRoot, 'run-b', syntheticRunManifest({ manifestSha256: SHA(99) }));
    const res = await post({ run_dir: 'run-b' });
    expect(res.statusCode).toBe(201);
    const [warning] = res.json().warnings;
    expect(warning).toMatchObject({ code: 'REGISTRY_HASH_MISMATCH', details: { file_name: 'document_manifest.jsonl' } });
    expect(warning.detail).toContain(SHA(99).slice(0, 12));
    const file = (await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-A/files' })).json().items[0];
    expect(file).toMatchObject({ file_name: 'F9001', relative_path: null, manifest_section: null });
  });

  it('warns about files missing on disk and files absent from the organizer manifest', async () => {
    const manifest = syntheticRunManifest({
      manifestSha256: organizerSha,
      files: [
        { file_id: 'F9001', object_id: 'OBJ-SYNTH-A', sha256: SHA(1), manifest_stage: 'PD', local_status: 'MISSING_ON_DISK' },
        { file_id: 'F9777', object_id: 'OBJ-SYNTH-A', sha256: SHA(77), manifest_stage: 'PD' },
      ],
    });
    writeRunDir(t.config.runsRoot, 'run-c', manifest);
    const res = await post({ run_dir: 'run-c' });
    expect(res.statusCode).toBe(201);
    const codes = res.json().warnings.map((w: { code: string }) => w.code);
    expect(codes).toEqual(['FILE_MISSING_ON_DISK', 'REGISTRY_FILE_NOT_LISTED']);
    expect(res.json().warnings[0].detail).toContain('F9001');
  });

  it('warns when the organizer data root is absent', async () => {
    rmSync(t.config.dataRoot, { recursive: true, force: true });
    writeRunDir(t.config.runsRoot, 'run-d', syntheticRunManifest({}));
    const res = await post({ run_dir: 'run-d' });
    expect(res.statusCode).toBe(201);
    expect(res.json().warnings.map((w: { code: string }) => w.code)).toEqual(['DATA_ROOT_NOT_FOUND']);
    mkdirSync(t.config.dataRoot, { recursive: true });
  });

  it('imports only the inventory of a hidden-split object and drops its artifact paths', async () => {
    const manifest = syntheticRunManifest({
      manifestSha256: organizerSha,
      objects: [
        { object_id: 'OBJ-SYNTH-A', split: 'TRAIN_PUBLIC' },
        { object_id: 'OBJ-SYNTH-HIDDEN', split: 'TEST_HIDDEN', artifacts: { submission: 'submission/x.json' } },
      ],
      files: [
        { file_id: 'F9001', object_id: 'OBJ-SYNTH-A', sha256: SHA(1), manifest_stage: 'PD' },
        { file_id: 'F9901', object_id: 'OBJ-SYNTH-HIDDEN', sha256: SHA(91), manifest_stage: 'ID' },
      ],
    });
    writeRunDir(t.config.runsRoot, 'run-e', manifest);
    const res = await post({ run_dir: 'run-e' });
    expect(res.statusCode).toBe(201);
    const codes = res.json().warnings.map((w: { code: string }) => w.code);
    expect(codes).toContain('HIDDEN_TEST_ACCESS_DENIED');
    const stored = [...t.store.runs.values()][0]?.manifest as { objects: Array<Record<string, unknown>> };
    expect(stored.objects.find((o) => o.object_id === 'OBJ-SYNTH-HIDDEN')).not.toHaveProperty('artifacts');
    const hidden = (await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-SYNTH-HIDDEN' })).json();
    expect(hidden).toMatchObject({ split: 'TEST_HIDDEN', files_total: 1 });
  });

  it('409 FILE_ID_IMMUTABLE when a file id comes back with another sha256', async () => {
    writeRunDir(t.config.runsRoot, 'run-f1', syntheticRunManifest({ runId: 'run-f1', manifestSha256: organizerSha }));
    expect((await post({ run_dir: 'run-f1' })).statusCode).toBe(201);
    const changed = syntheticRunManifest({
      runId: 'run-f2',
      files: [{ file_id: 'F9001', object_id: 'OBJ-SYNTH-A', sha256: SHA(500), manifest_stage: 'PD' }],
    });
    writeRunDir(t.config.runsRoot, 'run-f2', changed);
    const res = await post({ run_dir: 'run-f2' });
    expect(res.statusCode).toBe(409);
    const body = res.json();
    expect(body).toMatchObject({ code: 'FILE_ID_IMMUTABLE', details: { file_id: 'F9001' } });
    expect(body.errors[0].details).toMatchObject({ stored_sha256: SHA(1), new_sha256: SHA(500) });
    expect(contractSchemas().validate('problem', body)).toEqual({ valid: true });
    expect(t.store.runs.size).toBe(1); // nothing of run-f2 was written
  });

  describe('run directory resolution', () => {
    it('400 when run_dir escapes the runs root (relative, absolute or via symlink)', async () => {
      const outside = tmpDir('outside');
      writeRunDir(outside, 'run', syntheticRunManifest({}));
      for (const runDir of ['..', path.join(outside, 'run')]) {
        const res = await post({ run_dir: runDir });
        expect(res.statusCode).toBe(400);
        expect(res.json().code).toBe('VALIDATION_ERROR');
      }
      symlinkSync(path.join(outside, 'run'), path.join(t.config.runsRoot, 'link-out'));
      expect((await post({ run_dir: 'link-out' })).statusCode).toBe(400);
    });

    it('404 when the directory or its run_manifest.json does not exist', async () => {
      expect((await post({ run_dir: 'no-such-run' })).json()).toMatchObject({ status: 404, code: 'NOT_FOUND' });
      mkdirSync(path.join(t.config.runsRoot, 'empty-run'), { recursive: true });
      const res = await post({ run_dir: 'empty-run' });
      expect(res.statusCode).toBe(404);
      expect(res.json().details).toMatchObject({ file: 'run_manifest.json' });
    });

    it('400 when run_dir points at a file', async () => {
      writeFileSync(path.join(t.config.runsRoot, 'a-file'), 'x');
      expect((await post({ run_dir: 'a-file' })).statusCode).toBe(400);
    });
  });

  describe('contract validation of run_manifest.json (422)', () => {
    it('rejects invalid JSON', async () => {
      writeRunDir(t.config.runsRoot, 'bad-json', '{not json');
      const res = await post({ run_dir: 'bad-json' });
      expect(res.statusCode).toBe(422);
      expect(res.json()).toMatchObject({ code: 'CONTRACT_VALIDATION_FAILED', details: { artifact: 'run_manifest.json' } });
    });

    it.each(['no_objects.json', 'missing_on_disk_is_not_missing_document.json'])(
      'rejects the contracts invalid example %s',
      async (name) => {
        writeRunDir(t.config.runsRoot, `invalid-${name}`, readContractExample(`run_manifest/invalid/${name}`));
        const res = await post({ run_dir: `invalid-${name}` });
        expect(res.statusCode).toBe(422);
        const body = res.json();
        expect(body.code).toBe('CONTRACT_VALIDATION_FAILED');
        expect(body.errors.length).toBeGreaterThan(0);
        expect(contractSchemas().validate('problem', body)).toEqual({ valid: true });
      },
    );

    it('rejects a file that points at an object missing from objects[]', async () => {
      const manifest = syntheticRunManifest({
        files: [{ file_id: 'F9001', object_id: 'OBJ-ELSEWHERE', sha256: SHA(1), manifest_stage: 'PD' }],
      });
      writeRunDir(t.config.runsRoot, 'orphan', manifest);
      const res = await post({ run_dir: 'orphan' });
      expect(res.statusCode).toBe(422);
      expect(res.json().detail).toContain('OBJ-ELSEWHERE');
    });

    it('rejects duplicate file ids', async () => {
      const manifest = syntheticRunManifest({
        files: [
          { file_id: 'F9001', object_id: 'OBJ-SYNTH-A', sha256: SHA(1), manifest_stage: 'PD' },
          { file_id: 'F9001', object_id: 'OBJ-SYNTH-A', sha256: SHA(1), manifest_stage: 'PD' },
        ],
      });
      writeRunDir(t.config.runsRoot, 'dup', manifest);
      expect((await post({ run_dir: 'dup' })).statusCode).toBe(422);
    });
  });

  describe('request validation', () => {
    it('400 VALIDATION_ERROR for a missing or extra property', async () => {
      const missing = await post({});
      expect(missing.statusCode).toBe(400);
      expect(missing.json().errors[0]).toMatchObject({ pointer: '/requestBody/run_dir', field: 'run_dir' });
      const extra = await post({ run_dir: 'x', force: true });
      expect(extra.statusCode).toBe(400);
      expect(extra.json().errors[0]).toMatchObject({ field: 'force' });
    });

    it('400 MALFORMED_JSON for a broken body and 415 for another media type', async () => {
      const broken = await post('{"run_dir":', { 'content-type': 'application/json' });
      expect(broken.statusCode).toBe(400);
      expect(broken.json().code).toBe('MALFORMED_JSON');
      const text = await post('run_dir=x', { 'content-type': 'text/plain' });
      expect(text.statusCode).toBe(415);
      expect(text.json()).toMatchObject({ code: 'UNSUPPORTED_MEDIA_TYPE', details: { content_type: 'text/plain' } });
    });
  });
});
