/**
 * Demo D1 stand-in for `inspector-batch export` (owner AG-04) until it lands: stages the AG-08 fixture protocol of
 * Тюменская 5 (apps/api/fixtures/d1: contract example + gold + registered markup zones, labelled as a demo in
 * `ext.note`) as a run directory that the web product imports like any other run.
 *
 * It copies the RunManifest of an existing inventory run (objects/files of the one object only, new run_id),
 * writes protocol/<object>.json, findings/<object>.groups.jsonl (4 gold groups), findings/<object>.jsonl (10 atomic
 * findings, what the verification decides), layout/F0202.json and artifacts.json, and
 * validates everything against the contracts. Train object only; the hidden split is refused.
 *
 *   pnpm --filter @inspector/api fixture:d1 [-- --from m0-int-inventory-all] [--run-id d1-fixture-tyumen]
 *   then: POST /api/v1/admin/batch-runs/import {"run_dir": "d1-fixture-tyumen"}
 */
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { loadConfig } from '../src/config/config';
import { ContractSchemas, summarizeAjvErrors } from '../src/contracts/contracts';

const OBJECT_ID = 'OBJ-TYUMENSKAYA-5-GOLD-SEED';
const FIXTURES = path.resolve(__dirname, '..', 'fixtures', 'd1');

function sha256(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

function main(): void {
  const argv = process.argv.slice(2).filter((a, i) => !(i === 0 && a === '--'));
  const { values } = parseArgs({
    args: argv,
    options: { from: { type: 'string' }, 'run-id': { type: 'string' } },
  });
  const config = loadConfig();
  const schemas = new ContractSchemas(config.contractsDir);
  const from = path.resolve(config.runsRoot, values.from ?? 'm0-int-inventory-all');
  const runId = values['run-id'] ?? 'd1-fixture-tyumen';
  const source = path.join(from, 'run_manifest.json');
  if (!existsSync(source)) {
    console.error(`Не найден run_manifest.json инвентаризации: ${source} (make inventory-all или --from)`);
    process.exit(2);
  }
  const manifest = JSON.parse(readFileSync(source, 'utf8')) as {
    run_id: string;
    command?: string | null;
    started_at: string;
    finished_at?: string | null;
    objects: Array<{ object_id: string; split: string; artifacts?: Record<string, string> }>;
    files: Array<{ object_id: string }>;
    warnings?: unknown[];
  };
  const object = manifest.objects.find((o) => o.object_id === OBJECT_ID);
  if (!object) {
    console.error(`В запуске ${manifest.run_id} нет объекта ${OBJECT_ID}`);
    process.exit(2);
  }
  if (object.split !== 'TRAIN_PUBLIC') {
    console.error('Демонстрационный протокол формируется только для обучающего объекта.');
    process.exit(5);
  }
  const now = new Date().toISOString();
  const dir = path.join(config.runsRoot, runId);
  for (const sub of ['protocol', 'findings', 'layout']) mkdirSync(path.join(dir, sub), { recursive: true });

  const artifacts = {
    protocol_json: `protocol/${OBJECT_ID}.json`,
    finding_groups: `findings/${OBJECT_ID}.groups.jsonl`,
    findings: `findings/${OBJECT_ID}.jsonl`,
  };
  const out = {
    ...manifest,
    run_id: runId,
    command: 'fixture:d1 (AG-08 demo stand-in for inspector-batch export)',
    started_at: now,
    finished_at: now,
    objects: [{ ...object, artifacts: { ...(object.artifacts ?? {}), ...artifacts } }],
    files: manifest.files.filter((f) => f.object_id === OBJECT_ID),
    warnings: [],
  };
  const check = schemas.validate('run_manifest', out);
  if (!check.valid) {
    console.error(`run_manifest.json не соответствует контракту: ${summarizeAjvErrors(check.errors)}`);
    process.exit(3);
  }
  writeFileSync(path.join(dir, 'run_manifest.json'), `${JSON.stringify(out, null, 2)}\n`);

  const protocol = JSON.parse(readFileSync(path.join(FIXTURES, `${OBJECT_ID}.protocol.json`), 'utf8')) as Record<string, unknown>;
  protocol.run_id = runId;
  protocol.generated_at = now;
  // The object's real input manifest hash from the inventory run (the fixture carries a placeholder).
  const manifestHash = (object as { input_manifest_hash?: string }).input_manifest_hash;
  if (manifestHash) protocol.input_manifest_hash = manifestHash;
  writeFileSync(path.join(dir, artifacts.protocol_json), `${JSON.stringify(protocol, null, 2)}\n`);
  copyFileSync(path.join(FIXTURES, `${OBJECT_ID}.groups.jsonl`), path.join(dir, artifacts.finding_groups));
  copyFileSync(path.join(FIXTURES, `${OBJECT_ID}.findings.jsonl`), path.join(dir, artifacts.findings));
  copyFileSync(path.join(FIXTURES, 'F0202.layout.json'), path.join(dir, 'layout', 'F0202.json'));

  const entries: Array<{ kind: string; rel: string; format: string; schema: string | null; object_id?: string; file_id?: string; agent: string; command: string }> = [
    { kind: 'RUN_MANIFEST', rel: 'run_manifest.json', format: 'JSON', schema: 'run_manifest', agent: 'AG-01', command: 'inventory' },
    { kind: 'PROTOCOL_JSON', rel: artifacts.protocol_json, format: 'JSON', schema: 'protocol', object_id: OBJECT_ID, agent: 'AG-04', command: 'export' },
    { kind: 'FINDING_GROUPS', rel: artifacts.finding_groups, format: 'JSONL', schema: 'finding_group', object_id: OBJECT_ID, agent: 'AG-04', command: 'compare' },
    { kind: 'FINDINGS', rel: artifacts.findings, format: 'JSONL', schema: 'finding', object_id: OBJECT_ID, agent: 'AG-04', command: 'compare' },
    { kind: 'LAYOUT', rel: 'layout/F0202.json', format: 'JSON', schema: 'layout_artifacts', file_id: 'F0202', agent: 'AG-02B', command: 'layout' },
  ];
  for (const e of entries) {
    const file = path.join(dir, e.rel);
    const docs = e.format === 'JSONL'
      ? readFileSync(file, 'utf8').split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l) as unknown)
      : [JSON.parse(readFileSync(file, 'utf8')) as unknown];
    for (const doc of docs) {
      const r = e.schema ? schemas.validate(e.schema, doc) : { valid: true as const };
      if (!r.valid) {
        console.error(`${e.rel}: не соответствует ${e.schema}.schema.json: ${summarizeAjvErrors(r.errors)}`);
        process.exit(3);
      }
    }
  }
  const index = {
    schema_version: 1,
    layout_version: '1',
    run_id: runId,
    generated_at: now,
    objects: [OBJECT_ID],
    commands: ['inventory', 'layout', 'compare', 'export'],
    artifacts: entries.map((e) => ({
      kind: e.kind,
      path: e.rel,
      format: e.format,
      schema_name: e.schema,
      ...(e.object_id ? { object_id: e.object_id } : {}),
      ...(e.file_id ? { file_id: e.file_id } : {}),
      sha256: sha256(path.join(dir, e.rel)),
      size_bytes: statSync(path.join(dir, e.rel)).size,
      producer: { agent: e.agent, command: e.command },
    })),
    ext: { note: 'Демонстрационный запуск D1 (AG-08), не результат inspector-batch.' },
  };
  const idx = schemas.validate('run_artifacts', index);
  if (!idx.valid) {
    console.error(`artifacts.json не соответствует контракту: ${summarizeAjvErrors(idx.errors)}`);
    process.exit(3);
  }
  writeFileSync(path.join(dir, 'artifacts.json'), `${JSON.stringify(index, null, 2)}\n`);
  console.log(`Демонстрационный запуск записан: ${dir}`);
  console.log(`Импорт: curl -X POST http://127.0.0.1:${config.port}/api/v1/admin/batch-runs/import -H 'content-type: application/json' -d '{"run_dir":"${runId}"}'`);
}

main();
