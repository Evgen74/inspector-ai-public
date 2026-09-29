/**
 * AG-05 test harness: the real AppModule with the verification module spread into it — exactly the one-line
 * wiring requested from AG-00 (`...VERIFICATION_CONTROLLERS`, `...VERIFICATION_PROVIDERS`) — plus the platform
 * fakes of test/helpers.ts and the OpenAPI document with the verification overlay merged (as it will be once
 * adopted into packages/contracts/openapi/openapi.yaml). Data: the D1 fixture of Тюменская 5 (AG-08,
 * apps/api/fixtures/d1: contract-valid protocol, 4 finding groups, 10 atomic findings), seeded the way the
 * batch-run import v2 writes it.
 */
import 'reflect-metadata';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { type DynamicModule, Module } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import type { NestFastifyApplication } from '@nestjs/platform-fastify';
import type { FastifyInstance, LightMyRequestResponse } from 'fastify';
import addFormats from 'ajv-formats';
import OpenAPIBackend from 'openapi-backend';
import { AppModule } from '../../src/app.module';
import { BatchRunsRepository } from '../../src/batch-import/batch-runs.repository';
import { configureApp, createFastifyAdapter } from '../../src/bootstrap';
import type { AppConfig } from '../../src/config/config';
import { Database } from '../../src/db/database';
import { AuditRepository } from '../../src/modules/audit/audit.repository';
import { InMemorySessionStore, SessionStore } from '../../src/modules/auth/session-store';
import { UsersRepository } from '../../src/modules/auth/users.repository';
import type { FindingDoc, FindingGroupDoc, ProtocolDoc } from '../../src/modules/import/import-plan';
import { RunImportRepository } from '../../src/modules/import/run-import.repository';
import { MlApiClient } from '../../src/modules/render/ml-api.client';
import { RenderFilesRepository } from '../../src/modules/render/render.service';
import { CatalogLookup } from '../../src/modules/shared/lookup.repository';
import {
  InMemoryVerificationRepository,
  seedFromArtifacts,
  VERIFICATION_CONTROLLERS,
  VERIFICATION_OPENAPI_OVERLAY,
  VERIFICATION_PROVIDERS,
  VerificationRepository,
} from '../../src/modules/verification';
import type { SeedFile } from '../../src/modules/verification/verification.memory';
import { ObjectsRepository } from '../../src/objects/objects.repository';
import { API_PREFIX, loadOpenApiDocument, OPENAPI_PATH, OpenApiService, pendingOverlayFiles } from '../../src/openapi/openapi.service';
import { baseConfig, FakeDatabase } from '../helpers';
import { inMemoryLookup } from '../in-memory-lookup';
import { InMemoryStore } from '../in-memory-store';
import { FakeMlApi, InMemoryAudit, InMemoryRenderFiles, InMemoryRunImport, InMemoryUsers } from '../platform-fakes';

export const TYUMEN = 'OBJ-TYUMENSKAYA-5-GOLD-SEED';
export const PASSWORD = 'Demo-Inspector-2026';
const FIXTURES = path.resolve(__dirname, '..', '..', 'fixtures', 'd1');

function jsonl<T>(file: string): T[] {
  return readFileSync(file, 'utf8')
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as T);
}

export interface D1Fixture {
  protocol: ProtocolDoc;
  groups: FindingGroupDoc[];
  findings: FindingDoc[];
}

export function d1Fixture(): D1Fixture {
  return {
    protocol: JSON.parse(readFileSync(path.join(FIXTURES, `${TYUMEN}.protocol.json`), 'utf8')) as ProtocolDoc,
    groups: jsonl<FindingGroupDoc>(path.join(FIXTURES, `${TYUMEN}.groups.jsonl`)),
    findings: jsonl<FindingDoc>(path.join(FIXTURES, `${TYUMEN}.findings.jsonl`)),
  };
}

/** Registry rows of the files the fixture cites (+ F0203, another RD file of the object, for WRONG_REVISION). */
export const TYUMEN_FILES: SeedFile[] = [
  { file_id: 'F0171', stage: 'PD', manifest_stage: 'PD', file_name: 'V2_01-05-04-02-07_Том 5.4.2 ОВ (1).pdf', approval_status: 'APPROVED' },
  { file_id: 'F0201', stage: 'RD', manifest_stage: 'RD_ID_MIXED', document_code: 'АНО-150321-1-РД-ОВ1', revision: '4', file_name: 'АНО-150321-1-РД-ОВ1 изм. 4_в1 (1).pdf' },
  { file_id: 'F0202', stage: 'RD', manifest_stage: 'RD_ID_MIXED', document_code: 'АНО-150321-1-РД-ОВ2.1', revision: '3', file_name: 'АНО-150321-1-РД-ОВ2.1 изм. 3.pdf' },
  { file_id: 'F0203', stage: 'RD', manifest_stage: 'RD_ID_MIXED', document_code: 'АНО-150321-1-РД-ОВ2.2', revision: '2', file_name: 'АНО-150321-1-РД-ОВ2.2.pdf' },
];

/** OpenApiService over the contracts document + pending overlays + the verification overlay. */
export class OverlayOpenApiService extends OpenApiService {
  constructor(extra: string[] = [VERIFICATION_OPENAPI_OVERLAY]) {
    super();
    const document = loadOpenApiDocument(OPENAPI_PATH, [...pendingOverlayFiles(), ...extra]);
    const backend = new OpenAPIBackend({
      definition: structuredClone(document),
      apiRoot: API_PREFIX,
      strict: true,
      validate: true,
      coerceTypes: true,
      ajvOpts: { allErrors: true, strict: false },
      customizeAjv: (ajv) => {
        addFormats(ajv);
        return ajv;
      },
    });
    Object.assign(this, { document, backend });
  }
}

@Module({})
class VerificationTestRoot {}

export interface VerificationTestApp {
  app: NestFastifyApplication;
  http: FastifyInstance;
  repo: InMemoryVerificationRepository;
  users: InMemoryUsers;
  audit: InMemoryAudit;
  sessions: InMemorySessionStore;
  config: AppConfig;
  logs: string[];
  close(): Promise<void>;
}

export async function createVerificationApp(overrides: Partial<AppConfig> = {}): Promise<VerificationTestApp> {
  const config = baseConfig({ authMode: 'required', ...overrides });
  const logs: string[] = [];
  const root = AppModule.forRoot(config, { logStream: { write: (line: string) => void logs.push(line) } });
  const composed: DynamicModule = {
    module: VerificationTestRoot,
    imports: root.imports,
    controllers: [...(root.controllers ?? []), ...VERIFICATION_CONTROLLERS],
    providers: [...(root.providers ?? []), ...VERIFICATION_PROVIDERS],
  };
  const store = new InMemoryStore();
  const repo = new InMemoryVerificationRepository();
  const users = new InMemoryUsers();
  const audit = new InMemoryAudit();
  const sessions = new InMemorySessionStore();
  const openapi = new OverlayOpenApiService();
  await openapi.init();
  const moduleRef = await Test.createTestingModule({ imports: [composed] })
    .overrideProvider(Database)
    .useValue(new FakeDatabase())
    .overrideProvider(ObjectsRepository)
    .useValue(store.objectsRepository)
    .overrideProvider(BatchRunsRepository)
    .useValue(store.batchRunsRepository)
    .overrideProvider(CatalogLookup)
    .useValue(inMemoryLookup(store))
    .overrideProvider(SessionStore)
    .useValue(sessions)
    .overrideProvider(UsersRepository)
    .useValue(users)
    .overrideProvider(AuditRepository)
    .useValue(audit)
    .overrideProvider(RunImportRepository)
    .useValue(new InMemoryRunImport())
    .overrideProvider(RenderFilesRepository)
    .useValue(new InMemoryRenderFiles())
    .overrideProvider(MlApiClient)
    .useValue(new FakeMlApi())
    .overrideProvider(OpenApiService)
    .useValue(openapi)
    .overrideProvider(VerificationRepository)
    .useValue(repo)
    .compile();
  const app = moduleRef.createNestApplication<NestFastifyApplication>(createFastifyAdapter(), { logger: false });
  await configureApp(app);
  return { app, http: app.getHttpAdapter().getInstance(), repo, users, audit, sessions, config, logs, close: () => app.close() };
}

export interface Session {
  cookie: string;
  csrf: string;
  userId: string;
  fullName: string;
}

export async function login(http: FastifyInstance, loginName: string): Promise<Session> {
  const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: loginName, password: PASSWORD } });
  if (res.statusCode !== 200) throw new Error(`login ${loginName}: ${res.statusCode} ${res.body}`);
  const raw = res.headers['set-cookie'];
  const cookie = String(Array.isArray(raw) ? raw[0] : raw).split(';')[0]!;
  const body = res.json() as { csrf_token: string; user: { id: string; full_name: string } };
  return { cookie, csrf: body.csrf_token, userId: body.user.id, fullName: body.user.full_name };
}

/** Standard users: the single role is INSPECTOR; extra inspectors exist for scenarios that need two people. */
export async function seedUsers(users: InMemoryUsers): Promise<void> {
  users.users.clear();
  users.assignments.clear();
  await users.add({ login: 'inspector', password: PASSWORD, roles: ['INSPECTOR'], fullName: 'Иванова Мария Сергеевна', objects: [TYUMEN] });
  await users.add({ login: 'inspector2', password: PASSWORD, roles: ['INSPECTOR'], fullName: 'Петров Алексей Игоревич', objects: [] });
  await users.add({ login: 'inspector3', password: PASSWORD, roles: ['INSPECTOR'], fullName: 'Смирнова Ольга Павловна', objects: [TYUMEN] });
}

export function seedTyumen(repo: InMemoryVerificationRepository, split = 'TRAIN_PUBLIC'): string {
  repo.reset();
  const f = d1Fixture();
  return seedFromArtifacts(repo, {
    objectId: TYUMEN,
    objectName: 'Тюменская ул., 5',
    split,
    batchRunId: 'd1-fixture-tyumen',
    protocol: f.protocol,
    groups: f.groups,
    findings: f.findings,
    files: TYUMEN_FILES,
  });
}

let keySeq = 0;
/** Deterministic, well-formed UUIDs for Idempotency-Key. */
export function idemKey(): string {
  keySeq += 1;
  return `00000000-0000-4000-8000-${keySeq.toString(16).padStart(12, '0')}`;
}

export interface Call {
  method?: 'GET' | 'POST';
  url: string;
  session?: Session | null;
  body?: unknown;
  ifMatch?: string | number | null;
  key?: string | null;
  headers?: Record<string, string>;
}

export async function call(http: FastifyInstance, c: Call): Promise<LightMyRequestResponse> {
  const headers: Record<string, string> = { ...(c.headers ?? {}) };
  if (c.session) {
    headers.cookie = c.session.cookie;
    headers['x-csrf-token'] = c.session.csrf;
  }
  if (c.ifMatch !== undefined && c.ifMatch !== null) headers['if-match'] = typeof c.ifMatch === 'number' ? `"${c.ifMatch}"` : c.ifMatch;
  if ((c.method ?? 'GET') === 'POST' && c.key !== null) headers['idempotency-key'] = c.key ?? idemKey();
  return http.inject({
    method: c.method ?? 'GET',
    url: `/api/v1${c.url}`,
    headers,
    ...(c.body !== undefined ? { payload: c.body as Record<string, unknown> } : {}),
  });
}

export interface CardBody {
  finding_id: string;
  row_version: number;
  evidence_fingerprint: string;
  prefill: { confirm_comment: string; confirm_basis_code: string; reject_comments: Record<string, string>; clarify_comments: Record<string, string> };
  [k: string]: unknown;
}

export async function getCard(http: FastifyInstance, session: Session, processId: string, findingId: string): Promise<CardBody> {
  const res = await call(http, { url: `/processes/${processId}/findings/${encodeURIComponent(findingId)}`, session });
  if (res.statusCode !== 200) throw new Error(`card ${findingId}: ${res.statusCode} ${res.body}`);
  return res.json() as CardBody;
}

/** Posts a decision with the card's fingerprint and ETag (the UI's 2–3 action path). */
export async function decide(
  http: FastifyInstance,
  session: Session,
  processId: string,
  findingId: string,
  body: Record<string, unknown>,
  opts: { key?: string; ifMatch?: number | string } = {},
): Promise<LightMyRequestResponse> {
  const card = await getCard(http, session, processId, findingId);
  return call(http, {
    method: 'POST',
    url: `/processes/${processId}/findings/${encodeURIComponent(findingId)}/decisions`,
    session,
    key: opts.key,
    ifMatch: opts.ifMatch ?? card.row_version,
    body: { seen_fingerprint: card.evidence_fingerprint, ...body },
  });
}

export async function confirm(http: FastifyInstance, session: Session, processId: string, findingId: string): Promise<LightMyRequestResponse> {
  const card = await getCard(http, session, processId, findingId);
  return call(http, {
    method: 'POST',
    url: `/processes/${processId}/findings/${encodeURIComponent(findingId)}/decisions`,
    session,
    ifMatch: card.row_version,
    body: { decision: 'CONFIRMED_VIOLATION', comment: card.prefill.confirm_comment, comment_source: 'TEMPLATE', seen_fingerprint: card.evidence_fingerprint },
  });
}

export async function reauth(http: FastifyInstance, session: Session): Promise<string> {
  const res = await call(http, { method: 'POST', url: '/auth/reauth', session, key: null, body: { password: PASSWORD } });
  if (res.statusCode !== 200) throw new Error(`reauth: ${res.statusCode} ${res.body}`);
  return (res.json() as { reauth_token: string }).reauth_token;
}

export const FID = (suffix: string) => `${TYUMEN}-${suffix}`;
