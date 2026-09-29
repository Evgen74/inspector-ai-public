import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { Inject, Injectable, type OnApplicationBootstrap } from '@nestjs/common';
import { ApiProblem } from '../../common/problem';
import { ErrorCatalog } from '../../common/problem';
import { uuidv7 } from '../../common/ids';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { JobQueue } from './job-queue';
import { writeFileLarge } from './large-buffer';
import type { MultipartBody } from './multipart';
import { newRecord, type ProcessFile, type ProcessRecord } from './process-store';
import {
  extOf,
  MAX_FILE_BYTES,
  MAX_FILES,
  MAX_PACKAGE_BYTES,
  REGISTRY_EXTENSIONS,
  safeName,
  validateFiles,
} from './upload-validation';
import { UploadJob } from './upload-job';

export interface UploadResultDto {
  process_id: string;
  status: 'PENDING';
  object_id: string;
  accepted: Array<{ name: string; size_bytes: number; sha256: string }>;
  rejected: Array<{ name: string; code: string; detail: string }>;
  queue: 'rabbitmq' | 'in-process';
}

@Injectable()
export class UploadService implements OnApplicationBootstrap {
  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly catalog: ErrorCatalog,
    private readonly job: UploadJob,
    private readonly queue: JobQueue,
  ) {}

  /** Start the worker and re-enqueue processes that a restart interrupted. */
  async onApplicationBootstrap(): Promise<void> {
    const url = this.config.appEnv === 'test' ? null : (process.env.INSPECTOR_RABBITMQ_URL ?? 'amqp://127.0.0.1:5672');
    await this.queue.start((id) => this.job.run(id), url === 'off' ? null : url);
    for (const rec of this.job.store.list()) {
      if (rec.status === 'PENDING' || rec.status === 'PARSING') {
        rec.status = 'PENDING';
        rec.log.push({ ts: new Date().toISOString(), level: 'warn', message: 'Обработка возобновлена после перезапуска сервера.' });
        this.job.store.save(rec);
        this.queue.enqueue(rec.process_id);
      }
    }
  }

  limits(): { max_file_bytes: number; max_package_bytes: number; max_files: number; extensions: string[] } {
    return {
      max_file_bytes: MAX_FILE_BYTES,
      max_package_bytes: MAX_PACKAGE_BYTES,
      max_files: MAX_FILES,
      extensions: ['.pdf', '.docx', '.xml', '.zip', '.7z', '.rar'],
    };
  }

  create(body: MultipartBody): UploadResultDto {
    const docs = body.files.filter((f) => f.field !== 'registry');
    const registry = body.files.find((f) => f.field === 'registry');
    if (docs.length === 0) throw new ApiProblem('NO_FILES', {}, { status: 400 });
    if (docs.length > MAX_FILES) throw new ApiProblem('TOO_MANY_FILES', { count: docs.length, limit: MAX_FILES });
    const total = docs.reduce((n, f) => n + f.data.length, 0);
    if (total > MAX_PACKAGE_BYTES) {
      throw new ApiProblem('PACKAGE_TOO_LARGE', {
        total_mb: (total / (1024 * 1024)).toFixed(1),
        limit_bytes: MAX_PACKAGE_BYTES,
        actual_bytes: total,
      });
    }
    const { accepted, rejected } = validateFiles(docs, this.catalog);
    let registryName: string | null = null;
    if (registry) {
      const ext = extOf(registry.filename);
      if (!(REGISTRY_EXTENSIONS as readonly string[]).includes(ext) || registry.data.length === 0) {
        rejected.push({
          name: registry.filename,
          problem: this.catalog.item(
            registry.data.length === 0 ? 'EMPTY_FILE' : 'UNSUPPORTED_FORMAT',
            { file_name: registry.filename, detected: ext || '—', allowed: [...REGISTRY_EXTENSIONS] },
            { file_name: registry.filename },
          ),
        });
      } else {
        registryName = `registry${ext}`;
      }
    }
    if (accepted.length === 0) {
      throw new ApiProblem('NO_ACCEPTED_FILES', {}, { status: 422, errors: rejected.map((r) => r.problem) });
    }

    const processId = uuidv7();
    const objectId = `OBJ-UPLOAD-${processId.replace(/-/g, '').slice(-8).toLowerCase()}`;
    const objectName = (body.fields.object_name ?? '').trim().slice(0, 200) || `Загрузка ${new Date().toISOString().slice(0, 10)}`;
    const address = (body.fields.address ?? '').trim().slice(0, 300) || null;
    const store = this.job.store;
    const dir = store.dir(processId);
    const incoming = path.join(dir, 'incoming');
    for (const f of accepted) {
      const safe = safeName(f.name);
      if (!safe) continue;
      const target = path.join(incoming, safe);
      mkdirSync(path.dirname(target), { recursive: true });
      writeFileLarge(target, f.data);
    }
    if (registry && registryName) {
      mkdirSync(path.join(dir, 'registry'), { recursive: true });
      writeFileSync(path.join(dir, 'registry', registryName), registry.data);
    }
    const files: ProcessFile[] = [
      ...accepted.map(
        (f): ProcessFile => ({
          file_id: null,
          name: f.name,
          size_bytes: f.data.length,
          sha256: f.sha256,
          status: 'RECEIVED',
          stage: null,
          stage_source: null,
          pages: null,
          problems: [],
          from_archive: null,
        }),
      ),
      ...rejected
        .filter((r) => r.name !== registry?.filename)
        .map(
          (r): ProcessFile => ({
            file_id: null,
            name: r.name,
            size_bytes: 0,
            sha256: '',
            status: 'REJECTED',
            stage: null,
            stage_source: null,
            pages: null,
            problems: [r.problem.detail],
            from_archive: null,
          }),
        ),
    ];
    const rec: ProcessRecord = newRecord({ processId, objectId, objectName, address, registryFile: registryName, files });
    store.create(rec);
    const mode = this.queue.enqueue(processId);
    rec.queue = mode;
    store.save(rec);
    return {
      process_id: processId,
      status: 'PENDING',
      object_id: objectId,
      accepted: accepted.map((f) => ({ name: f.name, size_bytes: f.data.length, sha256: f.sha256 })),
      rejected: rejected.map((r) => ({ name: r.name, code: r.problem.code, detail: r.problem.detail })),
      queue: mode,
    };
  }
}
