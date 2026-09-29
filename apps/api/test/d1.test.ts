/**
 * D1 read side (AG-08): protocol versions, protocol view, export files, dashboard colours and filters, page
 * annotations — all read from imported run directories and validated against the contracts.
 */
import { createHash } from 'node:crypto';
import { copyFileSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { aggregateGroupStatus } from '../src/modules/shared/lookup.repository';
import { createTestApp, SHA, syntheticRunManifest, type TestApp, writeRunDir } from './helpers';
import { inMemoryDecisions } from './in-memory-lookup';

const OBJ = 'OBJ-TYUMENSKAYA-5-GOLD-SEED';
const HIDDEN = 'OBJ-SYNTH-HIDDEN';
const FIXTURES = path.resolve(__dirname, '..', 'fixtures', 'd1');
const REAL_SHA: Record<string, string> = {};
for (const f of (JSON.parse(readFileSync(path.join(FIXTURES, `${OBJ}.protocol.json`), 'utf8')) as {
  input_registry: { files: Array<{ file_id: string; sha256: string }> };
}).input_registry.files) {
  REAL_SHA[f.file_id] = f.sha256;
}

function sha256File(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

/** Write artifacts.json (run_artifacts schema) for the given relative paths. */
function writeIndex(runDir: string, runId: string, entries: Array<{ kind: string; rel: string; object_id?: string; file_id?: string; schema?: string }>) {
  const artifacts = entries.map((e) => {
    const abs = path.join(runDir, e.rel);
    const fmt = e.rel.endsWith('.jsonl') ? 'JSONL' : e.rel.endsWith('.docx') ? 'DOCX' : e.rel.endsWith('.pdf') ? 'PDF' : 'JSON';
    return {
      kind: e.kind,
      path: e.rel,
      format: fmt,
      sha256: sha256File(abs),
      size_bytes: statSync(abs).size,
      ...(e.object_id ? { object_id: e.object_id } : {}),
      ...(e.file_id ? { file_id: e.file_id } : {}),
      ...(e.schema ? { schema_name: e.schema } : {}),
    };
  });
  writeFileSync(
    path.join(runDir, 'artifacts.json'),
    JSON.stringify({ schema_version: 1, layout_version: '1', run_id: runId, generated_at: '2026-09-28T09:10:00Z', objects: [OBJ], artifacts }, null, 2),
  );
}

function protocolFixture(): Record<string, unknown> {
  return JSON.parse(readFileSync(path.join(FIXTURES, `${OBJ}.protocol.json`), 'utf8')) as Record<string, unknown>;
}

async function importRun(t: TestApp, runId: string, opts: { startedAt?: string; withHidden?: boolean } = {}) {
  const manifest = syntheticRunManifest({
    runId,
    objects: [
      { object_id: OBJ, split: 'TRAIN_PUBLIC' },
      ...(opts.withHidden ? [{ object_id: HIDDEN, split: 'TEST_HIDDEN' as const }] : []),
    ],
    files: [
      { file_id: 'F0171', object_id: OBJ, sha256: REAL_SHA.F0171!, manifest_stage: 'PD' },
      { file_id: 'F0201', object_id: OBJ, sha256: REAL_SHA.F0201!, manifest_stage: 'RD_ID_MIXED' },
      { file_id: 'F0202', object_id: OBJ, sha256: REAL_SHA.F0202!, manifest_stage: 'RD_ID_MIXED' },
      ...(opts.withHidden ? [{ file_id: 'F9901', object_id: HIDDEN, sha256: SHA(99), manifest_stage: 'PD' }] : []),
    ],
  });
  if (opts.startedAt) manifest.started_at = opts.startedAt;
  const dir = writeRunDir(t.config.runsRoot, runId, manifest);
  const res = await t.http.inject({ method: 'POST', url: '/api/v1/admin/batch-runs/import', payload: { run_dir: runId } });
  expect(res.statusCode, res.body).toBeLessThan(300);
  return { dir, runUuid: (res.json() as { run: { id: string } }).run.id };
}

function writeProtocolArtifacts(dir: string, runId: string, protocol: Record<string, unknown>, opts: { docx?: boolean; index?: boolean } = {}) {
  mkdirSync(path.join(dir, 'protocol'), { recursive: true });
  mkdirSync(path.join(dir, 'findings'), { recursive: true });
  mkdirSync(path.join(dir, 'layout'), { recursive: true });
  writeFileSync(path.join(dir, 'protocol', `${OBJ}.json`), JSON.stringify(protocol, null, 2));
  copyFileSync(path.join(FIXTURES, `${OBJ}.groups.jsonl`), path.join(dir, 'findings', `${OBJ}.groups.jsonl`));
  copyFileSync(path.join(FIXTURES, 'F0202.layout.json'), path.join(dir, 'layout', 'F0202.json'));
  const entries = [
    { kind: 'PROTOCOL_JSON', rel: `protocol/${OBJ}.json`, object_id: OBJ, schema: 'protocol' },
    { kind: 'FINDING_GROUPS', rel: `findings/${OBJ}.groups.jsonl`, object_id: OBJ, schema: 'finding_group' },
    { kind: 'LAYOUT', rel: 'layout/F0202.json', file_id: 'F0202', schema: 'layout_artifacts' },
  ];
  if (opts.docx) {
    writeFileSync(path.join(dir, 'protocol', `${OBJ}.docx`), Buffer.from('PK\u0003\u0004 docx stand-in'));
    entries.push({ kind: 'PROTOCOL_DOCX', rel: `protocol/${OBJ}.docx`, object_id: OBJ, schema: undefined as unknown as string });
  }
  if (opts.index !== false) writeIndex(dir, runId, entries);
}

describe('protocols API', () => {
  let t: TestApp;
  let runA: { dir: string; runUuid: string };
  let runB: { dir: string; runUuid: string };
  beforeAll(async () => {
    t = await createTestApp();
    runA = await importRun(t, 'd1-run-a', { startedAt: '2026-09-27T08:00:00Z', withHidden: true });
    const first = protocolFixture();
    first.generated_at = '2026-09-27T09:00:00Z';
    writeProtocolArtifacts(runA.dir, 'd1-run-a', first, { docx: true });
    runB = await importRun(t, 'd1-run-b', { startedAt: '2026-09-28T08:00:00Z' });
    writeProtocolArtifacts(runB.dir, 'd1-run-b', protocolFixture(), { index: false }); // template fallback
  });
  afterAll(async () => {
    await t.close();
  });

  it('lists protocol versions newest first with Приложение 2 counts and available formats', async () => {
    const res = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols` });
    expect(res.statusCode, res.body).toBe(200);
    const body = res.json() as { items: Array<Record<string, unknown>> };
    expect(body.items.map((v) => v.batch_run_id)).toEqual(['d1-run-b', 'd1-run-a']);
    expect(body.items.map((v) => v.web_version)).toEqual([2, 1]);
    expect(body.items.map((v) => v.is_latest)).toEqual([true, false]);
    expect(body.items[0]).toMatchObject({
      protocol_no: '2026-09-28-TYUMEN5-1',
      status: 'IN_VERIFICATION',
      scenario: 'PD_RD_ONLY',
      is_final: false,
      status_line: '⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)',
      counts: { critical: 3, substantial: 0, suspicions: 1, not_checked_no_id: 1, cards: 4 },
      formats: ['json'],
    });
    expect(body.items[1]!.formats).toEqual(['json', 'docx']);
  });

  it('returns the contract protocol with the finding groups of the same run', async () => {
    const res = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/${runA.runUuid}` });
    expect(res.statusCode, res.body).toBe(200);
    const body = res.json() as {
      protocol: { header: { title: string }; evidence_cards: unknown[] };
      finding_groups: Array<{ finding_group_id: string; location_pages?: Record<string, unknown> }>;
      warnings: unknown[];
      version: { web_version: number };
    };
    expect(body.protocol.header.title).toBe('ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № 2026-09-28-TYUMEN5-1');
    expect(body.protocol.evidence_cards).toHaveLength(4);
    expect(body.finding_groups).toHaveLength(4);
    expect(body.finding_groups.find((g) => g.finding_group_id.endsWith('IOS4-078-CFG-01'))?.location_pages).toHaveProperty('314');
    expect(body.warnings).toEqual([]);
    expect(body.version.web_version).toBe(1);
  });

  it('streams the DOCX written by export with a UTF-8 file name, 404 when the format was not produced', async () => {
    const res = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/${runA.runUuid}/export?format=docx` });
    expect(res.statusCode, res.body).toBe(200);
    expect(res.headers['content-type']).toContain('wordprocessingml');
    expect(String(res.headers['content-disposition'])).toContain(`filename*=UTF-8''${encodeURIComponent('Протокол_2026-09-28-TYUMEN5-1_v1.docx')}`);
    // The ASCII fallback is a readable transliteration, never a row of underscores.
    expect(String(res.headers['content-disposition'])).toContain('filename="Protokol_2026-09-28-TYUMEN5-1_v1.docx"');
    expect(res.rawPayload.subarray(0, 2).toString()).toBe('PK');
    const json = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/${runA.runUuid}/export?format=json` });
    expect(json.statusCode).toBe(200);
    expect(JSON.parse(json.body).protocol_no).toBe('2026-09-28-TYUMEN5-1');
    const pdf = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/${runA.runUuid}/export?format=pdf` });
    expect(pdf.statusCode).toBe(404);
    expect(pdf.json().code).toBe('NOT_FOUND');
    const bad = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/${runA.runUuid}/export?format=xml` });
    expect(bad.statusCode).toBe(400);
  });

  it('never reads artifacts of the hidden split: 403 on protocols and annotations', async () => {
    // Even a protocol file planted for the hidden object must not be served.
    mkdirSync(path.join(runA.dir, 'protocol'), { recursive: true });
    writeFileSync(path.join(runA.dir, 'protocol', `${HIDDEN}.json`), '{}');
    const list = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${HIDDEN}/protocols` });
    expect(list.statusCode).toBe(403);
    expect(list.json().code).toBe('HIDDEN_TEST_ACCESS_DENIED');
    const one = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${HIDDEN}/protocols/${runA.runUuid}` });
    expect(one.statusCode).toBe(403);
    const ann = await t.http.inject({ method: 'GET', url: '/api/v1/files/F9901/annotations?page=1' });
    expect(ann.statusCode).toBe(403);
  });

  it('404 for unknown objects, runs of other objects and unknown files; 400 for a malformed run id', async () => {
    expect((await t.http.inject({ method: 'GET', url: '/api/v1/objects/OBJ-NOPE/protocols' })).statusCode).toBe(404);
    const other = '01920000-0000-7000-8000-000000000000';
    expect((await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/${other}` })).statusCode).toBe(404);
    expect((await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/not-a-uuid` })).statusCode).toBe(400);
    const ann = await t.http.inject({ method: 'GET', url: '/api/v1/files/F0000/annotations?page=1' });
    expect(ann.statusCode).toBe(404);
    expect(ann.json().code).toBe('FILE_NOT_FOUND');
  });

  it('serves revision clouds and room labels of the page from the layout artifact', async () => {
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/files/F0202/annotations?page=17' });
    expect(res.statusCode, res.body).toBe(200);
    const body = res.json() as { batch_run_id: string; revision_clouds: Array<{ layer: string; rooms_covered: string[] }>; rooms: Array<{ room_token: string }> };
    expect(body.batch_run_id).toBe('d1-run-b');
    expect(body.revision_clouds).toEqual([
      expect.objectContaining({ layer: 'ОВ-Отопление-Изм. №3', rooms_covered: ['270', '272'], revision_label: 'Изм. №3' }),
    ]);
    expect(body.rooms.map((r) => r.room_token).sort()).toEqual(['267', '270', '271', '272', '277']);
    const empty = await t.http.inject({ method: 'GET', url: '/api/v1/files/F0202/annotations?page=18' });
    expect(empty.json()).toMatchObject({ revision_clouds: [], rooms: [] });
    const noLayout = await t.http.inject({ method: 'GET', url: '/api/v1/files/F0171/annotations?page=88' });
    expect(noLayout.json()).toMatchObject({ run_id: null, revision_clouds: [], rooms: [] });
  });

  it('rejects a protocol that violates the contract (422) and leaves it out of the version list', async () => {
    const runC = await importRun(t, 'd1-run-c', { startedAt: '2026-09-29T08:00:00Z' });
    const broken = protocolFixture();
    (broken.header as Record<string, unknown>).title = 'Протокол без номера';
    writeProtocolArtifacts(runC.dir, 'd1-run-c', broken);
    const one = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols/${runC.runUuid}` });
    expect(one.statusCode).toBe(422);
    expect(one.json()).toMatchObject({ code: 'CONTRACT_VALIDATION_FAILED' });
    expect(one.json().detail).toContain('protocol.schema.json');
    const list = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}/protocols` });
    expect((list.json() as { items: Array<{ batch_run_id: string }> }).items.map((v) => v.batch_run_id)).toEqual(['d1-run-b', 'd1-run-a']);
  });
});

describe('dashboard API', () => {
  let t: TestApp;
  let runUuid: string;
  beforeAll(async () => {
    t = await createTestApp();
    const run = await importRun(t, 'd1-dash', { withHidden: true });
    runUuid = run.runUuid;
    writeProtocolArtifacts(run.dir, 'd1-dash', protocolFixture());
  });
  afterAll(async () => {
    await t.close();
  });

  const get = async (query = '') => {
    const res = await t.http.inject({ method: 'GET', url: `/api/v1/dashboard${query}` });
    expect(res.statusCode, res.body).toBe(200);
    return res.json() as {
      tiles: Record<string, number>;
      items: Array<{ object_id: string; indicator: { color: string; reasons: Array<{ code: string; text: string }> }; counters: Record<string, number>; sections: string[] }>;
      sections: Array<{ section_ru: string; pending: number; suspicions: number }>;
    };
  };

  it('colours the gold object yellow (candidates await the inspector) and the hidden one grey', async () => {
    const body = await get();
    expect(body.tiles).toEqual({ total: 2, RED: 0, YELLOW: 1, GREEN: 0, NONE: 1, awaiting_decision: 3 });
    const gold = body.items.find((i) => i.object_id === OBJ)!;
    expect(gold.indicator.color).toBe('YELLOW');
    expect(gold.indicator.reasons.map((r) => r.code)).toEqual(['CANDIDATES_PENDING', 'MISSING_EVIDENCE']);
    expect(gold.indicator.reasons[0]!.text).toBe('Ожидают решения инспектора: 3 кандидата (критических: 3)');
    expect(gold.counters).toMatchObject({ confirmed: 0, pending: 3, pending_high: 3, suspicions: 1, suspicions_pending: 1 });
    expect(gold.sections).toEqual(['ИОС4']);
    const hidden = body.items.find((i) => i.object_id === HIDDEN)!;
    expect(hidden.indicator).toEqual({
      color: 'NONE',
      reasons: [{ code: 'HIDDEN_TEST_INVENTORY_ONLY', count: 0, text: 'Скрытая тестовая выборка: только инвентаризация' }],
    });
    expect(body.sections).toEqual([
      { section_ru: 'ИОС4', confirmed: 0, pending: 3, clarification: 0, rejected: 0, suspicions: 0 },
      { section_ru: 'Вне матрицы', confirmed: 0, pending: 0, clarification: 0, rejected: 0, suspicions: 1 },
    ]);
  });

  it('gives the objects list and the object card the very colour and scenario of the dashboard', async () => {
    const dash = await get();
    const list = await t.http.inject({ method: 'GET', url: '/api/v1/objects' });
    const items = (list.json() as { items: Array<{ object_id: string; indicator_color: string; scenario: string | null }> }).items;
    for (const d of dash.items) {
      expect(items.find((i) => i.object_id === d.object_id)?.indicator_color, d.object_id).toBe(d.indicator.color);
    }
    const card = await t.http.inject({ method: 'GET', url: `/api/v1/objects/${OBJ}` });
    const detail = card.json() as { indicator_color: string; scenario: string | null };
    expect(detail.indicator_color).toBe('YELLOW');
    expect(detail.scenario).toBe(dash.items.find((i) => i.object_id === OBJ) ? 'PD_RD_ONLY' : null);
  });

  it('filters by colour after the tiles, by section and decision, scenario and protocol date', async () => {
    const red = await get('?color=RED');
    expect(red.items).toEqual([]);
    expect(red.tiles.YELLOW).toBe(1);
    expect((await get('?color=YELLOW,NONE')).items).toHaveLength(2);
    expect((await get('?section=ИОС4')).items.map((i) => i.object_id)).toEqual([OBJ]);
    expect((await get('?section=КР')).items).toEqual([]);
    expect((await get('?status=PENDING&section=ИОС4')).items).toHaveLength(1);
    expect((await get('?status=CONFIRMED_VIOLATION')).items).toEqual([]);
    expect((await get('?scenario=PD_RD_ONLY')).items.map((i) => i.object_id)).toEqual([OBJ]);
    expect((await get('?scenario=FULL')).items).toEqual([]);
    expect((await get('?date_from=2026-09-28&date_to=2026-09-28')).items.map((i) => i.object_id)).toEqual([OBJ]);
    expect((await get('?date_from=2026-09-29')).items).toEqual([]);
    expect((await get('?q=тюмен')).items).toEqual([]);
    expect((await get('?q=tyumen')).items).toHaveLength(1);
  });

  it('turns red only after an inspector confirmation (live decisions of the verification)', async () => {
    const key = `${OBJ}|${runUuid}`;
    inMemoryDecisions.set(key, new Map([['OBJ-TYUMENSKAYA-5-GOLD-SEED-G-IOS4-078-MISS-01', 'NEGATIVE_VERIFIED']]));
    let gold = (await get()).items.find((i) => i.object_id === OBJ)!;
    expect(gold.indicator.color).toBe('YELLOW');
    expect(gold.counters).toMatchObject({ pending: 2, rejected: 1 });
    inMemoryDecisions.set(
      key,
      new Map([
        ['OBJ-TYUMENSKAYA-5-GOLD-SEED-G-IOS4-079-CFG-01', 'CONFIRMED_VIOLATION'],
        ['OBJ-TYUMENSKAYA-5-GOLD-SEED-G-FREE-HEATING-001', 'DISMISSED'],
      ]),
    );
    const body = await get();
    gold = body.items.find((i) => i.object_id === OBJ)!;
    expect(gold.indicator).toMatchObject({ color: 'RED', reasons: [{ code: 'CONFIRMED_VIOLATIONS', count: 1 }] });
    expect(gold.counters).toMatchObject({ confirmed: 1, pending: 2, suspicions_pending: 0 });
    expect(body.tiles).toMatchObject({ RED: 1, YELLOW: 0 });
    expect((await get('?status=CONFIRMED_VIOLATION')).items.map((i) => i.object_id)).toEqual([OBJ]);
    inMemoryDecisions.delete(key);
  });

  it('aggregates per-check decisions into the group status', () => {
    expect(aggregateGroupStatus(['PENDING', 'CONFIRMED_VIOLATION', 'NEGATIVE_VERIFIED'])).toBe('CONFIRMED_VIOLATION');
    expect(aggregateGroupStatus(['PENDING', 'CLARIFICATION_REQUIRED'])).toBe('CLARIFICATION_REQUIRED');
    expect(aggregateGroupStatus(['NEGATIVE_VERIFIED', 'NEGATIVE_VERIFIED'])).toBe('NEGATIVE_VERIFIED');
    expect(aggregateGroupStatus(['NEGATIVE_VERIFIED', 'PENDING'])).toBe('PENDING');
    expect(aggregateGroupStatus([])).toBe('PENDING');
  });

  it('rejects unknown colours and malformed dates with a Russian validation problem', async () => {
    const bad = await t.http.inject({ method: 'GET', url: '/api/v1/dashboard?color=PURPLE' });
    expect(bad.statusCode).toBe(400);
    expect(bad.json().code).toBe('VALIDATION_ERROR');
    const date = await t.http.inject({ method: 'GET', url: '/api/v1/dashboard?date_from=28.09.2026' });
    expect(date.statusCode).toBe(400);
  });
});


describe('Content-Disposition file names', () => {
  it('transliterates the ASCII fallback and percent-encodes the UTF-8 name per RFC 5987', async () => {
    const { contentDisposition, transliterate } = await import('../src/modules/protocols/protocols.controller.js');
    expect(transliterate('Протокол_Щёлково_№5.pdf')).toBe('Protokol_Shchelkovo__5.pdf');
    const header = contentDisposition("Протокол (1)'.docx");
    expect(header).toBe(`attachment; filename="Protokol (1)'.docx"; filename*=UTF-8''%D0%9F%D1%80%D0%BE%D1%82%D0%BE%D0%BA%D0%BE%D0%BB%20%281%29%27.docx`);
  });
});
