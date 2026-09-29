/**
 * Stand-in for `inspector-batch inventory` (owner AG-01) until it lands: writes a contract-valid
 * runs/<run_id>/run_manifest.json from the organizer manifest so the web import can be exercised end to end.
 *
 * Inventory only: reads document_manifest.jsonl + split_policy.json and checks that each file exists on disk
 * (stat, no hashing, no content). Excluded file ids (split_policy.excluded_file_ids) are skipped.
 *
 *   pnpm --filter @inspector/api fixture:inventory                 # every object of the manifest
 *   pnpm --filter @inspector/api fixture:inventory -- --object OBJ-… [--object …] [--run-id …]
 */
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { parse as parseYaml } from 'yaml';
import { canonicalJson, inputManifestHash, sha256Hex } from '../src/common/hashing';
import { documentsRoot, loadConfig, organizerManifestPath, PACKAGE_DIR_NAME, splitPolicyPath } from '../src/config/config';
import { ContractSchemas, summarizeAjvErrors } from '../src/contracts/contracts';
import type { ManifestRow, RunManifest, RunManifestFile, RunManifestObject } from '../src/batch-import/run-manifest';
import { readJsonl } from '../src/batch-import/run-manifest';

const STUB_PIPELINE_VERSION = '0.1.0+m0-inventory-stub';
const DOC_STAGES = new Set(['PD', 'RD', 'ID']);

function utcRunId(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}T${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}Z-inventory-stub`;
}

function sha256OfFile(file: string): string {
  return sha256Hex(readFileSync(file));
}

function main(): void {
  // `pnpm run x -- --flag` forwards the separator itself; drop it.
  const argv = process.argv.slice(2).filter((a, i) => !(i === 0 && a === '--'));
  const { values } = parseArgs({
    args: argv,
    options: {
      object: { type: 'string', multiple: true },
      'run-id': { type: 'string' },
      'runs-root': { type: 'string' },
    },
  });
  const config = loadConfig();
  const runsRoot = path.resolve(values['runs-root'] ?? config.runsRoot);
  const manifestFile = organizerManifestPath(config.dataRoot);
  if (!existsSync(manifestFile)) {
    console.error(`Не найден манифест организаторов: ${manifestFile} (INSPECTOR_DATA_ROOT)`);
    process.exit(2);
  }
  const packageData = path.join(config.dataRoot, PACKAGE_DIR_NAME, 'data');
  const policy = JSON.parse(readFileSync(splitPolicyPath(config.dataRoot), 'utf8')) as {
    excluded_file_ids?: string[];
  };
  const excluded = new Set(policy.excluded_file_ids ?? []);
  const rows = readJsonl<ManifestRow>(manifestFile);
  const wanted = values.object?.length ? new Set(values.object) : null;
  const objectIds = [...new Set(rows.map((r) => r.object_id))].filter((id) => !wanted || wanted.has(id)).sort();
  if (wanted) {
    const unknown = [...wanted].filter((id) => !objectIds.includes(id));
    if (unknown.length) {
      console.error(`Объекты не найдены в манифесте: ${unknown.join(', ')}`);
      process.exit(2);
    }
  }

  const docsRoot = documentsRoot(config.dataRoot);
  const objects: RunManifestObject[] = [];
  const files: RunManifestFile[] = [];
  for (const objectId of objectIds) {
    const objectRows = rows.filter((r) => r.object_id === objectId);
    const included = objectRows.filter((r) => !excluded.has(r.file_id));
    const missing: string[] = [];
    for (const row of included) {
      const onDisk = path.join(docsRoot, row.relative_path.normalize('NFC'));
      let present = false;
      try {
        present = statSync(onDisk).isFile();
      } catch {
        present = false;
      }
      if (!present) missing.push(row.file_id);
      files.push({
        file_id: row.file_id,
        object_id: row.object_id,
        sha256: row.sha256,
        manifest_stage: row.stage,
        stage_resolved: DOC_STAGES.has(row.stage) ? row.stage : null,
        local_status: present ? 'PRESENT' : 'MISSING_ON_DISK',
        sha256_verified: null,
        extension: row.extension,
        pdf_pages: row.pdf_pages,
      });
    }
    const split = objectRows[0]?.split;
    if (split !== 'TRAIN_PUBLIC' && split !== 'TEST_HIDDEN') {
      console.error(`Неизвестная выборка ${String(split)} у объекта ${objectId}`);
      process.exit(2);
    }
    objects.push({
      object_id: objectId,
      split,
      input_manifest_hash: inputManifestHash(objectRows),
      files_total: included.length,
      files_present: included.length - missing.length,
      missing_on_disk: missing,
      scenario: null,
    });
  }

  const runId = values['run-id'] ?? utcRunId();
  const contractVersion = (parseYaml(readFileSync(path.join(config.contractsDir, 'enums.yaml'), 'utf8')) as {
    contract_version?: string;
  }).contract_version;
  const modelsManifest = path.join(config.repoRoot, 'tools', 'models', 'manifest.json');
  const startedAt = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const manifest: RunManifest = {
    schema_version: 1,
    run_id: runId,
    producer: 'inspector-batch',
    command: `inventory-stub ${argv.join(' ')}`.trim(),
    started_at: startedAt,
    finished_at: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
    status: 'SUCCEEDED',
    config_hash: sha256Hex(canonicalJson({ generator: 'make-inventory-run', objects: objectIds })),
    freeze_tag: null,
    versions: {
      pipeline_version: STUB_PIPELINE_VERSION,
      contract_version: contractVersion ?? null,
      code_version: null,
    },
    inputs: {
      manifest_sha256: sha256OfFile(manifestFile),
      catalog_sha256: sha256OfFile(path.join(packageData, 'parameter_catalog_132.jsonl')),
      submission_schema_sha256: sha256OfFile(path.join(packageData, 'submission_schema.json')),
      split_policy_sha256: sha256OfFile(splitPolicyPath(config.dataRoot)),
      ...(existsSync(modelsManifest) ? { models_manifest_sha256: sha256OfFile(modelsManifest) } : {}),
    },
    host: { platform: `${os.platform()}-${os.release()}`, machine: os.arch(), cpu_count: os.cpus().length },
    objects,
    files,
    ext: { stub: true, generator: 'apps/api/scripts/make-inventory-run.ts (AG-08), stand-in for AG-01 inventory' },
  };

  const schemas = new ContractSchemas(config.contractsDir);
  const result = schemas.validate('run_manifest', manifest);
  if (!result.valid) {
    console.error(`run_manifest не соответствует контракту: ${summarizeAjvErrors(result.errors)}`);
    process.exit(3);
  }
  const runDir = path.join(runsRoot, runId);
  mkdirSync(runDir, { recursive: true });
  const out = path.join(runDir, 'run_manifest.json');
  writeFileSync(out, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  console.log(`Записан ${out}`);
  for (const o of objects) {
    console.log(
      `  ${o.object_id}: ${o.split}, файлов ${o.files_total}, на диске ${o.files_present}, отсутствуют ${o.missing_on_disk.length}`,
    );
  }
  console.log(`Импорт: POST /api/v1/admin/batch-runs/import {"run_dir": "${runId}"}`);
}

main();
