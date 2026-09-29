/** Upload vertical: multipart parsing, ТЗ §9.1 limits, ad-hoc job flow (fake engine) and process status. */
import os from 'node:os';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ErrorCatalog } from '../src/common/problem';
import { loadConfig } from '../src/config/config';
import { RunImportService } from '../src/modules/import/run-import.service';
import { CommandRunner, type CommandSpec } from '../src/modules/upload/command-runner';
import { JobQueue } from '../src/modules/upload/job-queue';
import { boundaryOf, parseMultipart } from '../src/modules/upload/multipart';
import { parseProgressLine, type StageProgress, weightedPercent } from '../src/modules/upload/process-store';
import { UploadJob } from '../src/modules/upload/upload-job';
import { UploadService } from '../src/modules/upload/upload.service';
import { MAX_FILE_BYTES, safeName, validateFiles } from '../src/modules/upload/upload-validation';
import { createTestApp, type TestApp } from './helpers';

const PDF = Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n');

function multipart(parts: Array<{ name: string; filename?: string; type?: string; data: Buffer | string }>) {
  const boundary = '----testboundary7MA4YWxk';
  const chunks: Buffer[] = [];
  for (const p of parts) {
    const disp = `form-data; name="${p.name}"${p.filename !== undefined ? `; filename="${p.filename}"` : ''}`;
    chunks.push(Buffer.from(`--${boundary}\r\nContent-Disposition: ${disp}\r\n`));
    if (p.filename !== undefined) chunks.push(Buffer.from(`Content-Type: ${p.type ?? 'application/octet-stream'}\r\n`));
    chunks.push(Buffer.from('\r\n'), Buffer.isBuffer(p.data) ? p.data : Buffer.from(p.data), Buffer.from('\r\n'));
  }
  chunks.push(Buffer.from(`--${boundary}--\r\n`));
  return { payload: Buffer.concat(chunks), contentType: `multipart/form-data; boundary=${boundary}` };
}

/** Engine double: writes what the adhoc registry would and emits the pipeline log lines of `inspector-batch run`. */
class FakeEngine extends CommandRunner {
  calls: CommandSpec[] = [];
  failBatch = false;
  async python(spec: CommandSpec, onLine: (l: string) => void): Promise<number> {
    this.calls.push(spec);
    if (spec.args.includes('inspector_registry.adhoc')) {
      const dir = spec.args[spec.args.indexOf('--upload-dir') + 1] as string;
      writeFileSync(
        path.join(dir, 'prepare.json'),
        JSON.stringify({
          files: [
            { file_id: 'U0001', name: 'ПД_том1.pdf', size_bytes: PDF.length, sha256: 'a'.repeat(64), stage: 'PD', stage_source: 'PATH', pdf_pages: 3, from_archive: null, problems: [] },
          ],
          notes: [],
        }),
      );
      return 0;
    }
    const dataroot = spec.args[spec.args.indexOf('--data-root') + 1] as string;
    const runsRoot = spec.args[spec.args.indexOf('--runs-root') + 1] as string;
    const runId = spec.args[spec.args.indexOf('--run-id') + 1] as string;
    mkdirSync(path.join(dataroot, 'ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0', 'data'), { recursive: true });
    writeFileSync(path.join(dataroot, 'ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0', 'data', 'document_manifest.jsonl'), '{}\n');
    mkdirSync(path.join(runsRoot, runId), { recursive: true });
    for (const step of ['inventory', 'recognize', 'layout']) {
      onLine(`2026 INFO inspector_batch: pipeline.step.started | run_id=x command=run step=${step} owner=AG-00`);
      onLine(`2026 INFO inspector_batch: pipeline.step.finished | run_id=x command=run step=${step} exit_code=0`);
    }
    if (this.failBatch) {
      onLine('2026 ERROR inspector_batch: pipeline.step.started | run_id=x command=run step=tables owner=AG-02C');
      onLine('Шаг «tables» завершился с кодом 1; цепочка остановлена.');
      return 1;
    }
    for (const step of ['tables', 'compare', 'export']) {
      onLine(`2026 INFO inspector_batch: pipeline.step.started | run_id=x command=run step=${step} owner=AG-00`);
      onLine(`2026 INFO inspector_batch: pipeline.step.finished | run_id=x command=run step=${step} exit_code=0`);
    }
    return 0;
  }
}

describe('multipart parser and name safety', () => {
  it('parses fields and files, incl. UTF-8 names and binary payloads', () => {
    const { payload, contentType } = multipart([
      { name: 'object_name', data: 'Тюменская, 5' },
      { name: 'files', filename: 'ПД том 1.pdf', data: Buffer.from([0, 255, 13, 10, 1, 2]) },
    ]);
    expect(boundaryOf(contentType)).toBe('----testboundary7MA4YWxk');
    const out = parseMultipart(payload, contentType);
    expect(out.fields.object_name).toBe('Тюменская, 5');
    expect(out.files).toHaveLength(1);
    expect(out.files[0]?.filename).toBe('ПД том 1.pdf');
    expect([...(out.files[0]?.data ?? [])]).toEqual([0, 255, 13, 10, 1, 2]);
  });

  it('rejects path traversal names', () => {
    expect(safeName('../../etc/passwd')).toBeNull();
    expect(safeName('a/../b.pdf')).toBeNull();
    expect(safeName('ПД/том 1.pdf')).toBe('ПД/том 1.pdf');
  });
});

describe('POST /documents/upload → GET /processes', () => {
  let t: TestApp;
  const engine = new FakeEngine();

  beforeAll(async () => {
    t = await createTestApp();
    const job = t.app.get(UploadJob) as unknown as { commands: CommandRunner; importer: unknown };
    job.commands = engine;
    job.importer = {
      importRunDir: async () => ({
        run: { id: '00000000-0000-7000-8000-000000000001' },
        artifacts: { objects: [{ object_id: 'X', process_id: '00000000-0000-7000-8000-000000000002', protocol: { id: 'p1' } }] },
      }),
    } as unknown as RunImportService;
  });
  afterAll(async () => t.close());

  async function post(parts: Parameters<typeof multipart>[0]) {
    const { payload, contentType } = multipart(parts);
    return t.http.inject({ method: 'POST', url: '/api/v1/documents/upload', payload, headers: { 'content-type': contentType } });
  }
  const waitReady = async (id: string) => {
    await t.app.get(JobQueue).idle();
    return (await t.http.inject({ method: 'GET', url: `/api/v1/processes/${id}` })).json();
  };

  it('publishes the upload limits (500 МБ per document, 5 ГБ per package)', async () => {
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/documents/upload/limits' });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ max_file_bytes: 500 * 1024 * 1024, max_package_bytes: 5 * 1024 * 1024 * 1024 });
  });

  it('accepts a package (202), runs it to READY and links the protocol', async () => {
    const res = await post([
      { name: 'object_name', data: 'Тестовый объект' },
      { name: 'files', filename: 'ПД_том1.pdf', type: 'application/pdf', data: PDF },
      { name: 'files', filename: 'notes.txt', data: 'text' },
    ]);
    expect(res.statusCode).toBe(202);
    const body = res.json();
    expect(body.status).toBe('PENDING');
    expect(body.object_id).toMatch(/^OBJ-UPLOAD-[0-9a-f]{8}$/);
    expect(body.accepted).toHaveLength(1);
    expect(body.accepted[0].sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(body.rejected[0]).toMatchObject({ name: 'notes.txt', code: 'UNSUPPORTED_FORMAT' });
    expect(body.rejected[0].detail).toContain('не поддерживается');

    const detail = await waitReady(body.process_id);
    expect(detail.status).toBe('READY');
    expect(detail.progress.percent).toBe(100);
    expect(detail.steps.map((s: { status: string }) => s.status)).toEqual(Array(8).fill('DONE'));
    expect(detail.files.find((f: { name: string }) => f.name === 'ПД_том1.pdf')).toMatchObject({ file_id: 'U0001', stage: 'PD', pages: 3, status: 'DONE' });
    expect(detail.files.find((f: { name: string }) => f.name === 'notes.txt').status).toBe('REJECTED');
    expect(detail.protocol).toEqual({ object_id: body.object_id, run_id: '00000000-0000-7000-8000-000000000001' });
    expect(detail.verification_process_id).toBe('00000000-0000-7000-8000-000000000002');
    expect(detail.log.length).toBeGreaterThan(3);
    const batch = engine.calls.find((c) => c.args.includes('inspector_batch.cli'));
    expect(batch?.args).toContain('--workers');
    // auto: 75 % of the CPUs (INSPECTOR_RESOURCE_CAP)
    expect(batch?.args[batch.args.indexOf('--workers') + 1]).toBe(String(Math.max(1, Math.floor(os.availableParallelism() * 0.75))));
    expect(batch?.args).not.toContain('score');
    expect(batch?.args).not.toContain('--hidden-run');

    const list = (await t.http.inject({ method: 'GET', url: '/api/v1/processes' })).json();
    expect(list.items.some((p: { process_id: string }) => p.process_id === body.process_id)).toBe(true);
    expect(list.items[0].files).toBeUndefined();
  });

  it('writes the address of the upload form into the object card after the import', async () => {
    const job = t.app.get(UploadJob) as unknown as { objects: { setAddress: (id: string, a: string) => Promise<boolean> } };
    const original = job.objects;
    const calls: Array<[string, string]> = [];
    job.objects = {
      setAddress: async (id, a) => {
        calls.push([id, a]);
        return true;
      },
    };
    try {
      const res = await post([
        { name: 'address', data: '  г. Москва, ул. Тестовая, 1  ' },
        { name: 'files', filename: 'ПД_том1.pdf', type: 'application/pdf', data: PDF },
      ]);
      const body = res.json();
      const detail = await waitReady(body.process_id);
      expect(detail.status).toBe('READY');
      expect(detail.address).toBe('г. Москва, ул. Тестовая, 1');
      expect(calls).toEqual([[body.object_id, 'г. Москва, ул. Тестовая, 1']]);
      // no address typed: the card is left alone
      calls.length = 0;
      const second = await post([{ name: 'files', filename: 'ПД_том1.pdf', type: 'application/pdf', data: PDF }]);
      await waitReady(second.json().process_id);
      expect(calls).toEqual([]);
    } finally {
      job.objects = original;
    }
  });

  it('pauses a running upload (the pipeline is stopped), resumes it to READY; cancel is final', async () => {
    const job = t.app.get(UploadJob) as unknown as { commands: CommandRunner };
    let batchStarted!: () => void;
    const started = new Promise<void>((r) => (batchStarted = r));
    const aborted: boolean[] = [];
    job.commands = {
      python: async (spec: CommandSpec, onLine: (l: string) => void) => {
        if (!spec.args.includes('inspector_batch.cli') || aborted.length > 0) return engine.python(spec, onLine);
        // the first batch run hangs like a long recognition until the pause stops it
        onLine('2026 INFO inspector_batch: pipeline.step.started | run_id=x command=run step=recognize owner=AG-02A');
        batchStarted();
        await new Promise<void>((resolve) => spec.signal?.addEventListener('abort', () => resolve(), { once: true }));
        aborted.push(true);
        return 143;
      },
    } as unknown as CommandRunner;
    try {
      const id = (await post([{ name: 'files', filename: 'a.pdf', data: PDF }])).json().process_id;
      await started;
      const pause = await t.http.inject({ method: 'POST', url: `/api/v1/processes/${id}/pause` });
      expect(pause.statusCode).toBe(200);
      let detail = await waitReady(id);
      expect(aborted).toEqual([true]); // the running pipeline was stopped
      expect(detail.status).toBe('PAUSED');
      expect(detail.steps.some((s: { status: string }) => s.status === 'RUNNING' || s.status === 'FAILED')).toBe(false);
      expect(detail.log.at(-1).message).toContain('приостановлена');
      const again = await t.http.inject({ method: 'POST', url: `/api/v1/processes/${id}/pause` });
      expect(again.statusCode).toBe(409);
      expect(again.json().code).toBe('PROCESS_STATE_CONFLICT');

      const resume = await t.http.inject({ method: 'POST', url: `/api/v1/processes/${id}/resume` });
      expect(resume.statusCode).toBe(200);
      detail = await waitReady(id);
      expect(detail.status).toBe('READY');

      const done = await t.http.inject({ method: 'POST', url: `/api/v1/processes/${id}/cancel` });
      expect(done.statusCode).toBe(409); // a finished process cannot be cancelled
      const missing = await t.http.inject({ method: 'POST', url: '/api/v1/processes/nope/cancel' });
      expect(missing.statusCode).toBe(404);
    } finally {
      job.commands = engine;
    }
  });

  it('cancels a paused upload for good (resume is refused)', async () => {
    const store = t.app.get(UploadJob).store;
    const id = (await post([{ name: 'files', filename: 'a.pdf', data: PDF }])).json().process_id;
    await waitReady(id);
    const rec = store.get(id)!;
    rec.status = 'PAUSED'; // as left by a pause
    store.save(rec);
    const cancel = await t.http.inject({ method: 'POST', url: `/api/v1/processes/${id}/cancel` });
    expect(cancel.statusCode).toBe(200);
    expect(cancel.json().status).toBe('CANCELLED');
    const resume = await t.http.inject({ method: 'POST', url: `/api/v1/processes/${id}/resume` });
    expect(resume.statusCode).toBe(409);
  });

  it('marks the process FAILED with a Russian message when the engine fails', async () => {
    engine.failBatch = true;
    const res = await post([{ name: 'files', filename: 'a.pdf', data: PDF }]);
    engine.failBatch = false;
    const detail = await waitReady(res.json().process_id);
    expect(detail.status).toBe('FAILED');
    expect(detail.error).toContain('Обработка комплекта завершилась с ошибкой');
    expect(detail.steps.find((s: { step: string }) => s.step === 'tables').status).toBe('FAILED');
    expect(detail.protocol).toBeNull();
  });

  it('rejects a package without accepted files with per-file reasons (422)', async () => {
    const res = await post([
      { name: 'files', filename: 'fake.pdf', data: 'not a pdf at all' },
      { name: 'files', filename: 'empty.pdf', data: Buffer.alloc(0) },
      { name: 'files', filename: 'macro.docm', data: 'x' },
    ]);
    expect(res.statusCode).toBe(422);
    const body = res.json();
    expect(body.code).toBe('NO_ACCEPTED_FILES');
    expect(body.errors.map((e: { code: string }) => e.code).sort()).toEqual(['CONTENT_TYPE_MISMATCH', 'EMPTY_FILE', 'UNSUPPORTED_FORMAT']);
    expect(body.errors[0].detail).toMatch(/Файл|Содержимое|Формат/);
  });

  it('answers 400 NO_FILES for an empty selection and 404 for an unknown process', async () => {
    const res = await post([{ name: 'object_name', data: 'x' }]);
    expect(res.statusCode).toBe(400);
    expect(res.json().code).toBe('NO_FILES');
    const nf = await t.http.inject({ method: 'GET', url: '/api/v1/processes/00000000-0000-7000-8000-00000000ffff' });
    expect(nf.statusCode).toBe(404);
    expect(nf.json().code).toBe('PROCESS_NOT_FOUND');
    const bad = await t.http.inject({ method: 'GET', url: '/api/v1/processes/..%2F..%2Fetc' });
    expect(bad.statusCode).toBe(404);
  });

  it('enforces 500 MB per document and 5 GB per package; an archive is bounded by the package limit only', async () => {
    const service = t.app.get(UploadService);
    const file = (name: string, size: number) => ({
      field: 'files',
      filename: name,
      contentType: 'application/pdf',
      data: Buffer.concat([PDF, Buffer.alloc(size)]),
    });
    // Oversized parts are refused by their length alone, before any byte is read: no gigabyte buffers in the test.
    const sized = (name: string, size: number) => ({ field: 'files', filename: name, contentType: 'application/octet-stream', data: { length: size } as Buffer });
    const result = service.create({ fields: {}, files: [sized('big.pdf', MAX_FILE_BYTES + 1), file('ok.pdf', 10)] });
    expect(result.accepted.map((a) => a.name)).toEqual(['ok.pdf']);
    expect(result.rejected).toEqual([expect.objectContaining({ name: 'big.pdf', code: 'FILE_TOO_LARGE' })]);
    expect(result.rejected[0]?.detail).toContain('500 МБ');
    await t.app.get(JobQueue).idle();

    // The per-document limit (scaled down to 32 bytes here) does not apply to an archive container.
    const zip = Buffer.concat([Buffer.from('PK\u0003\u0004', 'latin1'), Buffer.alloc(60)]);
    const pdf = Buffer.concat([PDF, Buffer.alloc(60)]);
    const big = validateFiles(
      [
        { field: 'files', filename: 'all.zip', contentType: 'application/zip', data: zip },
        { field: 'files', filename: 'doc.pdf', contentType: 'application/pdf', data: pdf },
      ],
      t.app.get(ErrorCatalog),
      32,
    );
    expect(big.accepted.map((a) => a.name)).toEqual(['all.zip']);
    expect(big.rejected.map((r) => r.name)).toEqual(['doc.pdf']);
    expect(JSON.stringify(big.rejected[0]?.problem)).toContain('FILE_TOO_LARGE');

    const parts = Array.from({ length: 11 }, (_, i) => sized(`p${i}.pdf`, 490 * 1024 * 1024));
    try {
      service.create({ fields: {}, files: parts });
      expect.unreachable();
    } catch (err) {
      expect(err).toMatchObject({ code: 'PACKAGE_TOO_LARGE' });
    }
  });
});

describe('INSPECTOR_UPLOAD_WORKERS', () => {
  it('defaults to 2 and is passed to the batch run when raised', async () => {
    const auto = Math.max(1, Math.floor(os.availableParallelism() * 0.75));
    expect(loadConfig({ INSPECTOR_APP_ENV: 'test' }).uploadWorkers).toBe(auto); // 75 % of the CPUs
    expect(loadConfig({ INSPECTOR_APP_ENV: 'test', INSPECTOR_UPLOAD_WORKERS: '' }).uploadWorkers).toBe(auto);
    expect(loadConfig({ INSPECTOR_APP_ENV: 'test', INSPECTOR_RESOURCE_CAP: '0.5' }).uploadWorkers).toBe(
      Math.max(1, Math.floor(os.availableParallelism() * 0.5)),
    );
    expect(loadConfig({ INSPECTOR_APP_ENV: 'test', INSPECTOR_UPLOAD_WORKERS: '6' }).uploadWorkers).toBe(6);
    expect(() => loadConfig({ INSPECTOR_APP_ENV: 'test', INSPECTOR_UPLOAD_WORKERS: '0' })).toThrow(/INSPECTOR_UPLOAD_WORKERS/);
    const t = await createTestApp({ uploadWorkers: 6 });
    try {
      const engine = new FakeEngine();
      const job = t.app.get(UploadJob) as unknown as { commands: CommandRunner; importer: unknown };
      job.commands = engine;
      job.importer = {
        importRunDir: async () => ({ run: { id: '00000000-0000-7000-8000-000000000001' }, artifacts: { objects: [] } }),
      } as unknown as RunImportService;
      const { payload, contentType } = multipart([{ name: 'files', filename: 'a.pdf', type: 'application/pdf', data: PDF }]);
      const res = await t.http.inject({ method: 'POST', url: '/api/v1/documents/upload', payload, headers: { 'content-type': contentType } });
      expect(res.statusCode).toBe(202);
      await t.app.get(JobQueue).idle();
      const batch = engine.calls.find((c) => c.args.includes('inspector_batch.cli'));
      expect(batch?.args[batch.args.indexOf('--workers') + 1]).toBe('6');
      expect(batch?.env?.INSPECTOR_WORKERS).toBe('6');
    } finally {
      await t.close();
    }
  });
});

describe('upload progress', () => {
  const step = (name: string, status: 'DONE' | 'RUNNING' | 'PENDING') => ({ step: name, status, started_at: null, finished_at: null });
  const line =
    '2026-09-29T10:40:00.000Z INFO    inspector_docproc.runner: recognize.progress | run_id=upload-01a0ecb2 command=recognize done=1287 total=3169 pages_per_min=80.4';

  it('parses the recognizer progress line', () => {
    expect(parseProgressLine(line)).toEqual({ step: 'recognize', done: 1287, total: 3169, pages_per_min: 80.4 });
    expect(parseProgressLine('x recognize.progress | done=1 total=0')).toBeNull();
    expect(parseProgressLine('pipeline.step.started | step=recognize')).toBeNull();
  });

  it('weights the percent by step duration and the running step by done/total', () => {
    const steps = ['prepare', 'inventory', 'recognize', 'layout', 'tables', 'compare', 'export', 'import'];
    const mk = (statuses: Array<'DONE' | 'RUNNING' | 'PENDING'>, stage: StageProgress | null) => ({
      status: 'PARSING' as const,
      steps: steps.map((n, i) => step(n, statuses[i] ?? 'PENDING')),
      progress: { stage },
    });
    expect(weightedPercent(mk(['DONE', 'DONE', 'RUNNING'], null))).toBe(5);
    expect(weightedPercent(mk(['DONE', 'DONE', 'RUNNING'], { step: 'recognize', done: 50, total: 100, pages_per_min: 10 }))).toBe(43);
    expect(weightedPercent({ ...mk(['DONE'], null), status: 'READY' })).toBe(100);
  });

  it('saves stage progress at most once per 5 s', async () => {
    const t = await createTestApp();
    try {
      const job = t.app.get(UploadJob) as unknown as { commands: CommandRunner; store: { save: (r: unknown) => void } };
      const saves: number[] = [];
      const orig = job.store.save.bind(job.store);
      job.store.save = (r) => {
        saves.push((r as { progress: { stage: StageProgress | null } }).progress.stage?.done ?? -1);
        orig(r);
      };
      job.commands = {
        python: async (spec: CommandSpec, onLine: (l: string) => void) => {
          if (spec.args.includes('inspector_registry.adhoc')) return new FakeEngine().python(spec, onLine);
          for (let i = 1; i <= 50; i++) onLine(line.replace('done=1287', `done=${i}`));
          return 1;
        },
      } as unknown as CommandRunner;
      const { payload, contentType } = multipart([
        { name: 'object_name', data: 'Прогресс' },
        { name: 'files', filename: 'a.pdf', type: 'application/pdf', data: PDF },
      ]);
      await t.http.inject({ method: 'POST', url: '/api/v1/documents/upload', payload, headers: { 'content-type': contentType } });
      await t.app.get(JobQueue).idle();
      expect(saves.filter((d) => d > 0)).toEqual([1]);
    } finally {
      await t.close();
    }
  });
});
