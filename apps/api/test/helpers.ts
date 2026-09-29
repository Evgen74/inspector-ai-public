/** Test harness: the real AppModule with the database and repositories swapped for fakes. */
import 'reflect-metadata';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Test } from '@nestjs/testing';
import type { NestFastifyApplication } from '@nestjs/platform-fastify';
import type { FastifyInstance } from 'fastify';
import { AppModule } from '../src/app.module';
import { BatchRunsRepository } from '../src/batch-import/batch-runs.repository';
import { configureApp, createFastifyAdapter } from '../src/bootstrap';
import { type AppConfig, loadConfig, PACKAGE_DIR_NAME } from '../src/config/config';
import { ContractSchemas } from '../src/contracts/contracts';
import { Database } from '../src/db/database';
import { CatalogLookup } from '../src/modules/shared/lookup.repository';
import { ArchiveRepository } from '../src/modules/archive/archive.repository';
import { ObjectsRepository } from '../src/objects/objects.repository';
import { inMemoryLookup } from './in-memory-lookup';
import { InMemoryStore } from './in-memory-store';
import { AuditRepository } from '../src/modules/audit/audit.repository';
import { InMemorySessionStore, SessionStore } from '../src/modules/auth/session-store';
import { UsersRepository } from '../src/modules/auth/users.repository';
import { RunImportRepository } from '../src/modules/import/run-import.repository';
import { MlApiClient } from '../src/modules/render/ml-api.client';
import { RenderFilesRepository } from '../src/modules/render/render.service';
import { FakeMlApi, InMemoryAudit, InMemoryRenderFiles, InMemoryRunImport, InMemoryUsers } from './platform-fakes';

export class FakeDatabase {
  down = false;
  pool = {};
  db = {};
  async ping(): Promise<number> {
    if (this.down) throw Object.assign(new Error('connect ECONNREFUSED 127.0.0.1:5432'), { code: 'ECONNREFUSED' });
    return 1;
  }
}

export interface TestApp {
  app: NestFastifyApplication;
  http: FastifyInstance;
  store: InMemoryStore;
  database: FakeDatabase;
  logs: string[];
  config: AppConfig;
  close(): Promise<void>;
}

export function tmpDir(prefix: string): string {
  return mkdtempSync(path.join(os.tmpdir(), `inspector-api-${prefix}-`));
}

export function baseConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return loadConfig(
    { INSPECTOR_APP_ENV: 'test', INSPECTOR_LOG_LEVEL: 'info', INSPECTOR_LOG_FORMAT: 'json' },
    { runsRoot: tmpDir('runs'), dataRoot: tmpDir('data'), ...overrides },
  );
}

export async function createTestApp(overrides: Partial<AppConfig> = {}): Promise<TestApp> {
  const config = baseConfig(overrides);
  const logs: string[] = [];
  const store = new InMemoryStore();
  const database = new FakeDatabase();
  const moduleRef = await Test.createTestingModule({
    imports: [AppModule.forRoot(config, { logStream: { write: (line: string) => void logs.push(line) } })],
  })
    .overrideProvider(Database)
    .useValue(database)
    .overrideProvider(ObjectsRepository)
    .useValue(store.objectsRepository)
    .overrideProvider(BatchRunsRepository)
    .useValue(store.batchRunsRepository)
    .overrideProvider(CatalogLookup)
    .useValue(inMemoryLookup(store))
    .overrideProvider(ArchiveRepository)
    .useValue(store.archiveRepository)
    // Platform services (AG-00): no Redis, no PostgreSQL, no ml-api in DB-free tests.
    .overrideProvider(SessionStore)
    .useValue(new InMemorySessionStore())
    .overrideProvider(UsersRepository)
    .useValue(new InMemoryUsers())
    .overrideProvider(AuditRepository)
    .useValue(new InMemoryAudit())
    .overrideProvider(RunImportRepository)
    .useValue(new InMemoryRunImport())
    .overrideProvider(RenderFilesRepository)
    .useValue(new InMemoryRenderFiles())
    .overrideProvider(MlApiClient)
    .useValue(new FakeMlApi())
    .compile();
  const app = moduleRef.createNestApplication<NestFastifyApplication>(createFastifyAdapter(), { logger: false });
  await configureApp(app);
  return {
    app,
    http: app.getHttpAdapter().getInstance(),
    store,
    database,
    logs,
    config,
    close: () => app.close(),
  };
}

export const REPO_CONTRACTS = baseContractsDir();

function baseContractsDir(): string {
  return loadConfig({ INSPECTOR_APP_ENV: 'test' }).contractsDir;
}

let schemas: ContractSchemas | undefined;
export function contractSchemas(): ContractSchemas {
  schemas ??= new ContractSchemas(REPO_CONTRACTS);
  return schemas;
}

export function readContractExample<T>(relative: string): T {
  return JSON.parse(readFileSync(path.join(REPO_CONTRACTS, 'examples', relative), 'utf8')) as T;
}

export const SHA = (n: number) => n.toString(16).padStart(64, '0');

/** A synthetic, contract-valid RunManifest for objects of our own (never real hidden-object ids). */
export function syntheticRunManifest(opts: {
  runId?: string;
  manifestSha256?: string;
  objects?: Array<{ object_id: string; split: 'TRAIN_PUBLIC' | 'TEST_HIDDEN'; artifacts?: Record<string, string> }>;
  files?: Array<{ file_id: string; object_id: string; sha256: string; manifest_stage: string; local_status?: string }>;
}): Record<string, unknown> {
  const objects = opts.objects ?? [{ object_id: 'OBJ-SYNTH-A', split: 'TRAIN_PUBLIC' }];
  const files = opts.files ?? [
    { file_id: 'F9001', object_id: 'OBJ-SYNTH-A', sha256: SHA(1), manifest_stage: 'PD' },
    { file_id: 'F9002', object_id: 'OBJ-SYNTH-A', sha256: SHA(2), manifest_stage: 'RD' },
    { file_id: 'F9003', object_id: 'OBJ-SYNTH-A', sha256: SHA(3), manifest_stage: 'RD_ID_MIXED' },
  ];
  return {
    schema_version: 1,
    run_id: opts.runId ?? '20260101T000000Z-inventory',
    producer: 'inspector-batch',
    command: 'inspector-batch inventory',
    started_at: '2026-01-01T00:00:00Z',
    finished_at: '2026-01-01T00:00:02Z',
    status: 'SUCCEEDED',
    config_hash: SHA(7),
    versions: { pipeline_version: '0.1.0+test', contract_version: '0.1.0' },
    inputs: { manifest_sha256: opts.manifestSha256 ?? SHA(8), catalog_sha256: SHA(9), submission_schema_sha256: SHA(10) },
    objects: objects.map((o) => {
      const own = files.filter((f) => f.object_id === o.object_id);
      const missing = own.filter((f) => f.local_status === 'MISSING_ON_DISK').map((f) => f.file_id);
      return {
        object_id: o.object_id,
        split: o.split,
        input_manifest_hash: SHA(11),
        files_total: own.length,
        files_present: own.length - missing.length,
        missing_on_disk: missing,
        scenario: null,
        ...(o.artifacts ? { artifacts: o.artifacts } : {}),
      };
    }),
    files: files.map((f) => ({
      file_id: f.file_id,
      object_id: f.object_id,
      sha256: f.sha256,
      manifest_stage: f.manifest_stage,
      stage_resolved: ['PD', 'RD', 'ID'].includes(f.manifest_stage) ? f.manifest_stage : null,
      local_status: f.local_status ?? 'PRESENT',
      sha256_verified: null,
      extension: '.pdf',
      pdf_pages: 3,
    })),
  };
}

export function writeRunDir(runsRoot: string, name: string, manifest: unknown | string): string {
  const dir = path.join(runsRoot, name);
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    path.join(dir, 'run_manifest.json'),
    typeof manifest === 'string' ? manifest : JSON.stringify(manifest, null, 2),
  );
  return dir;
}

/** Organizer manifest rows for the synthetic objects; returns the file's sha256. */
export function writeOrganizerManifest(dataRoot: string, rows: Array<Record<string, unknown>>): string {
  const dir = path.join(dataRoot, PACKAGE_DIR_NAME, 'data');
  mkdirSync(dir, { recursive: true });
  const body = rows.map((r) => JSON.stringify(r)).join('\n') + '\n';
  writeFileSync(path.join(dir, 'document_manifest.jsonl'), body);
  return createHash('sha256').update(body).digest('hex');
}

export function organizerRow(fileId: string, objectId: string, sha256: string, extra: Record<string, unknown> = {}) {
  return {
    schema_version: '0.1.0',
    file_id: fileId,
    object_id: objectId,
    corpus: `Корпус ${objectId}`,
    dataset_role: 'UNLABELED_POOL',
    split: 'TRAIN_PUBLIC',
    relative_path: `Объект/Раздел/${fileId} том.pdf`,
    extension: '.pdf',
    size_bytes: 1234,
    sha256,
    stage: 'PD',
    section: 'AR',
    pdf_pages: 3,
    annotation_status: 'UNLABELED',
    exclusion_reason: null,
    duplicate_group: null,
    distribution_status: 'INCLUDE',
    label_visibility: 'PUBLIC_TRAIN',
    ...extra,
  };
}

export function parseLogs(logs: string[]): Array<Record<string, unknown>> {
  return logs.flatMap((chunk) =>
    chunk
      .split('\n')
      .filter((l) => l.trim())
      .map((l) => JSON.parse(l) as Record<string, unknown>),
  );
}
