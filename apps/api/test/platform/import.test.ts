/**
 * Batch-run import v2 without a database: artifact reading and validation, the row plan, hidden-object handling
 * and the HTTP endpoint (the repository is the in-memory one that records the plan).
 */
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { canonicalJson, sha256Hex } from '../../src/common/hashing';
import { AuditRepository } from '../../src/modules/audit/audit.repository';
import { UsersRepository } from '../../src/modules/auth/users.repository';
import { expectedActual, planFragments, planSuspicions, sheetPage } from '../../src/modules/import/import-plan';
import { RunImportRepository } from '../../src/modules/import/run-import.repository';
import { RunImportService } from '../../src/modules/import/run-import.service';
import { createTestApp, type TestApp } from '../helpers';
import type { InMemoryAudit, InMemoryRunImport, InMemoryUsers } from '../platform-fakes';
import { findingsOf, HIDDEN, TYUMEN, tyumenDocs, writeTyumenRun } from './run-fixture';

const PASSWORD = 'Demo-Inspector-2026';

describe('import plan (pure)', () => {
  it('maps expected/actual by comparison axis and renders sheet/page', () => {
    const v = { pd_value: 'ПД', rd_value: 'РД', id_value: 'ИД' };
    expect(expectedActual({ ...v, axis: 'PD_RD' })).toEqual(['ПД', 'РД']);
    expect(expectedActual({ ...v, axis: 'RD_ID' })).toEqual(['РД', 'ИД']);
    expect(expectedActual({ ...v, axis: 'PD_ID' })).toEqual(['ПД', 'ИД']);
    expect(expectedActual({ ...v, axis: 'NORM_RD' })).toEqual([null, 'РД']);
    expect(sheetPage({ stage: 'RD', file_id: 'F0201', pdf_page_number: 18, document_sheet_number: 4 })).toBe('л. 4 / стр. 18');
    expect(sheetPage({ stage: 'RD', file_id: 'F0201', pdf_page_number: 18 })).toBe('стр. 18');
  });

  it('gives fragments stable keys (ids survive idempotent re-imports)', () => {
    const docs = tyumenDocs();
    const a = planFragments(docs.groups as never, docs.findings as never).map((f) => f.fragmentKey);
    const b = planFragments(tyumenDocs().groups as never, tyumenDocs().findings as never).map((f) => f.fragmentKey);
    expect(a).toEqual(b);
    expect(new Set(a).size).toBe(a.length);
  });
});

describe('protocol-only suspicions (value conflicts inside one stage)', () => {
  const protocol = {
    object: { object_id: 'OBJ-X' },
    appendix2: {
      section6_ai_suspicions: {
        rows: [
          { no: 1, method: 'LOGICAL_ANALYSIS', description: 'В ПД противоречивые значения параметра PZ-022', card_ref: 'Б.1', confidence: 0.7 },
          { no: 2, method: 'GRAPHIC_DIFF', description: 'FREE group row', card_ref: 'Б.2', finding_group_id: 'G-1' },
        ],
      },
    },
    evidence_cards: [
      {
        card_no: 'Б.1',
        parameter_code: 'PZ-022',
        review_priority: 'HIGH',
        sources: [
          { stage: 'PD', file_id: 'F1', pdf_page_number: 17, sheet_number: null, file_sha256: 'a'.repeat(64) },
          { stage: 'RD', file_id: 'F2', pdf_page_number: 3 },
        ],
      },
    ],
  };

  it('become suspicions with their evidence pages, without touching groups or checks', () => {
    const plan = planSuspicions([], [], protocol as never);
    expect(plan).toHaveLength(1);
    const [s] = plan;
    expect(s!.suspicionKey).toMatch(/^OBJ-X-SUSP-[0-9a-f]{16}$/);
    expect(s!.findingIds).toEqual([]);
    expect(s!.inspectorStatusOnInsert).toBe('PENDING');
    expect(s!.row).toMatchObject({ objectId: 'OBJ-X', discoveryMethod: 'LOGICAL_ANALYSIS', paramCode: 'PZ-022', reviewPriority: 'HIGH' });
    expect(s!.row.pdReference).toBe('F1, стр. 17');
    const frags = planFragments([], [], protocol as never);
    expect(frags.map((f) => f.suspicionKey)).toEqual([s!.suspicionKey, s!.suspicionKey]);
    expect(frags.every((f) => f.findingId === null && f.evidenceGroupId === null)).toBe(true);
    expect(planSuspicions([], [], protocol as never)[0]!.suspicionKey).toBe(s!.suspicionKey); // stable
    expect(planSuspicions([], [], null)).toEqual([]);
  });
});

describe('run artifacts import v2', () => {
  let t: TestApp;
  let http: FastifyInstance;
  let repo: InMemoryRunImport;
  let audit: InMemoryAudit;
  let admin: { cookie: string; csrf: string };

  beforeAll(async () => {
    t = await createTestApp({ authMode: 'required' });
    http = t.http;
    repo = t.app.get(RunImportRepository) as InMemoryRunImport;
    audit = t.app.get(AuditRepository) as InMemoryAudit;
    await (t.app.get(UsersRepository) as InMemoryUsers).add({ login: 'admin', password: PASSWORD, roles: ['INSPECTOR'] });
    const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: 'admin', password: PASSWORD } });
    admin = { cookie: String(res.headers['set-cookie']).split(';')[0] ?? '', csrf: res.json().csrf_token };
  });

  beforeEach(() => {
    repo.plans.length = 0;
    audit.rows.length = 0;
    t.store.runs.clear();
    t.store.objects.clear();
    t.store.files.clear();
  });

  afterAll(async () => {
    await t.close();
  });

  const post = (runDir: string, requestId = 'req-import-0000') =>
    http.inject({
      method: 'POST',
      url: '/api/v1/admin/batch-runs/import',
      payload: { run_dir: runDir },
      headers: { cookie: admin.cookie, 'x-csrf-token': admin.csrf, 'x-request-id': requestId },
    });

  it('plans every table from the artifacts and never opens hidden-object artifacts', () => {
    const dir = writeTyumenRun(t.config.runsRoot);
    const service = t.app.get(RunImportService);
    const { manifest } = (service as unknown as { inventory: { readRunManifest(d: string): { manifest: never } } }).inventory.readRunManifest(dir);
    const prepared = service.prepare(dir, manifest)!;
    expect(prepared.dropped).toBe(2);
    expect(prepared.warnings.map((w) => w.code)).toContain('HIDDEN_TEST_ARTIFACTS_DROPPED');
    expect(prepared.plan.artifacts.map((a) => a.path)).not.toContain(`findings/${HIDDEN}.jsonl`);
    expect(prepared.plan.artifacts.map((a) => a.kind)).toContain('LAYOUT');
    expect(prepared.plan.objects.map((o) => o.objectId)).toEqual([TYUMEN]);
    const o = prepared.plan.objects[0]!;
    expect(o.groups).toHaveLength(4);
    // The gold: 10 atomic checks (012; 267/270/271/272; 140/142; 147/198/314) + one object-level row.
    expect(o.checks).toHaveLength(11);
    expect(o.checks.filter((c) => c.row.violationLabel === 'VIOLATION_PRESENT').map((c) => c.row.location).sort()).toEqual(
      ['012', '140', '142', '147', '198', '267', '270', '271', '272', '314'],
    );
    const free = o.checks.filter((c) => c.isFree);
    expect(free).toHaveLength(4);
    expect(free.every((c) => c.row.kind === 'SUSPICION_CONVERTED' && c.inspectorStatusOnInsert === 'PENDING')).toBe(true);
    const objectRow = o.checks.find((c) => c.row.location === 'OBJECT')!;
    expect(objectRow.inspectorStatusOnInsert).toBeNull();
    expect(o.suspicions).toHaveLength(1);
    expect(o.suspicions[0]).toMatchObject({ suspicionKey: `${TYUMEN}-G-FREE-HEATING-001`, inspectorStatusOnInsert: 'CONVERTED_TO_CANDIDATE', promotedBy: 'SYSTEM' });
    expect(o.suspicions[0]!.findingIds).toHaveLength(4);
    expect(o.protocol?.contentSha256).toBe(sha256Hex(canonicalJson(tyumenDocs().protocol)));
    expect(o.protocolExports.map((e) => e.format).sort()).toEqual(['docx', 'json']);
    expect(o.submissions.map((s) => s.variant)).toEqual(['full', 'strict']);
    expect(o.submissions[0]!.sidecar).not.toBeNull();
    // Room 314 is drawn on RD p20 while the anchor is p18: both pages are evidence fragments.
    const p314 = o.fragments.filter((f) => f.row.location === '314' && f.row.stage === 'RD').map((f) => f.row.pageNo);
    expect(new Set(p314)).toEqual(new Set([18, 20]));
    expect(o.fragments.filter((f) => f.row.isAnchor && f.evidenceGroupId === `${TYUMEN}-G-IOS4-078-CFG-01` && !f.findingId)).toHaveLength(2);
    expect(o.fileIds).toEqual(['F0171', 'F0201', 'F0202']);
  });

  it('imports through the endpoint (201, then 200) and audits BATCH_RUN_IMPORTED', async () => {
    writeTyumenRun(t.config.runsRoot, { runId: 'm1-http' });
    const first = await post('m1-http', 'req-import-0001');
    expect(first.statusCode, first.body).toBe(201);
    const body = first.json();
    expect(body.objects.map((o: { object_id: string }) => o.object_id)).toEqual([TYUMEN, HIDDEN]);
    expect(body.artifacts.artifacts_dropped).toBe(2);
    expect(body.artifacts.objects[0]).toMatchObject({ object_id: TYUMEN, finding_groups: 4, suspicions: 1, submissions: ['full', 'strict'] });
    expect(body.artifacts.objects[0].checks.total).toBe(11);
    expect(repo.plans[0]!.runId).toBe(body.run.id);
    const row = audit.rows.find((r) => r.requestId === 'req-import-0001' && r.action === 'BATCH_RUN_IMPORTED');
    expect(row).toMatchObject({ action: 'BATCH_RUN_IMPORTED', result: 'SUCCESS', objectType: 'BATCH_RUN', objectId: 'm1-http', actorLogin: 'admin', retentionClass: 'PERMANENT' });
    expect(row?.details).toMatchObject({ created: true, checks: 11 });
    const version = audit.rows.find((r) => r.action === 'PROTOCOL_VERSION_CREATED');
    expect(version).toMatchObject({ objectType: 'PROTOCOL', constructionObjectId: TYUMEN, protocolVersion: 1, requestId: 'req-import-0001' });
    expect((await post('m1-http')).statusCode).toBe(200);
  });

  it('keeps inventory-only runs working (artifacts: null)', async () => {
    writeTyumenRun(t.config.runsRoot, { runId: 'm1-noindex', withIndex: false });
    const res = await post('m1-noindex');
    expect(res.statusCode).toBe(201);
    expect(res.json().artifacts).toBeNull();
    expect(repo.plans).toHaveLength(0);
  });

  it.each([
    [
      'a tampered file (sha256 differs from artifacts.json)',
      (dir: string) => writeFileSync(path.join(dir, 'protocol', `${TYUMEN}.json`), '{}'),
      /размер|sha256/,
    ],
  ])('refuses %s with 422 and writes nothing', async (_name, tamper, reason) => {
    const dir = writeTyumenRun(t.config.runsRoot, { runId: 'm1-tampered' });
    tamper(dir);
    const res = await post('m1-tampered');
    expect(res.statusCode).toBe(422);
    expect(res.json().code).toBe('CONTRACT_VALIDATION_FAILED');
    expect(res.json().detail).toMatch(reason);
    expect(repo.plans).toHaveLength(0);
    expect(t.store.runs.size).toBe(0);
  });

  it('refuses a record that breaks its schema, pointing at the line', async () => {
    const docs = tyumenDocs();
    (docs.findings[2] as Record<string, unknown>).protocol_status = 'OK'; // VIOLATION_PRESENT needs CRITICAL|WARNING
    writeTyumenRun(t.config.runsRoot, { runId: 'm1-badrow', docs });
    const res = await post('m1-badrow');
    expect(res.statusCode).toBe(422);
    const pointers = (res.json().errors as Array<{ pointer: string; detail: string }>).map((e) => e.pointer);
    expect(pointers.some((p) => p.startsWith('/line/3'))).toBe(true);
  });

  it('refuses index paths outside their run_layout.yaml template and dangling group references', async () => {
    writeTyumenRun(t.config.runsRoot, {
      runId: 'm1-badpath',
      editIndex: (entries) => {
        const layout = entries.find((e) => e.kind === 'LAYOUT' && e.file_id === 'F0202')!;
        layout.kind = 'TABLES'; // layout/F0202.json is not tables/<file_id>.json
      },
    });
    const bad = await post('m1-badpath');
    expect(bad.statusCode).toBe(422);
    expect(bad.json().detail).toContain('не соответствует шаблону');

    const docs = tyumenDocs();
    docs.findings[0]!.finding_group_id = 'G-NOWHERE';
    writeTyumenRun(t.config.runsRoot, { runId: 'm1-dangling', docs });
    const dangling = await post('m1-dangling');
    expect(dangling.statusCode).toBe(422);
    expect(dangling.json().detail).toContain('G-NOWHERE');
  });

  it('warns about evidence citing a file outside the object manifest', async () => {
    const docs = tyumenDocs();
    const [group] = docs.groups;
    const moved = { ...group!, anchor_evidence: [{ stage: 'PD', file_id: 'F0999', pdf_page_number: 1, is_anchor: true }] };
    docs.groups[0] = moved;
    docs.findings = [...docs.groups.flatMap(findingsOf)];
    writeTyumenRun(t.config.runsRoot, { runId: 'm1-unknown-file', docs });
    const res = await post('m1-unknown-file');
    expect(res.statusCode).toBe(201);
    expect(res.json().artifacts.warnings).toContainEqual(expect.objectContaining({ code: 'EVIDENCE_FILE_UNKNOWN', details: { object_id: TYUMEN, file_id: 'F0999' } }));
  });

  it('refuses an index of another run', async () => {
    const dir = writeTyumenRun(t.config.runsRoot, { runId: 'm1-other' });
    const indexFile = path.join(dir, 'artifacts.json');
    const index = JSON.parse((await import('node:fs')).readFileSync(indexFile, 'utf8'));
    index.run_id = 'someone-else';
    writeFileSync(indexFile, JSON.stringify(index));
    const res = await post('m1-other');
    expect(res.statusCode).toBe(422);
    expect(res.json().detail).toContain('someone-else');
  });
});
