/**
 * A complete, contract-valid run directory for the import v2 tests, built from packages/contracts/examples (the
 * Тюменская gold: 4 finding groups, 10 atomic findings derived per location, protocol, submission full/strict,
 * sidecar, a protocol DOCX stand-in and a layout reference) plus one TEST_HIDDEN object whose artifacts are not
 * even valid JSON: the importer must never open them.
 */
import { createHash } from 'node:crypto';
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { REPO_CONTRACTS, SHA, syntheticRunManifest } from '../helpers';

export const TYUMEN = 'OBJ-TYUMENSKAYA-5-GOLD-SEED';
export const HIDDEN = 'OBJ-SYNTH-HIDDEN';

type Json = Record<string, unknown>;

const FINDING_KEYS = new Set([
  'finding_id', 'finding_group_id', 'object_id', 'run_id', 'matrix_scope', 'parameter_code', 'parameter_id',
  'parameter_mapping_status', 'alt_parameter_codes', 'hedge_of_finding_id', 'location', 'location_type', 'pd_value',
  'rd_value', 'id_value', 'axis', 'comparison_result', 'discrepancy_type', 'violation_type', 'completeness_status',
  'completeness_basis', 'finding_status', 'inspector_status', 'violation_label', 'protocol_status', 'criticality',
  'criticality_level', 'review_priority', 'risk_level', 'document_status', 'confidence', 'evidence', 'hedge_kind',
  'element_noun', 'discovery_method', 'evidence_bind_status', 'recommendation', 'card_no', 'rule_code', 'rule_version',
  'sub_id', 'delta', 'rationale', 'decision_trace',
]);

function example(dir: string): Json[] {
  const base = path.join(REPO_CONTRACTS, 'examples', dir, 'valid');
  return readdirSync(base)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((f) => JSON.parse(readFileSync(path.join(base, f), 'utf8')) as Json);
}

/** Atomic findings of a group, one per location, reusing the group's anchor pages (97 §2.5). */
export function findingsOf(group: Json): Json[] {
  const locations = group.locations as string[];
  const ids = group.finding_ids as string[];
  return locations.map((location, i) => {
    const f: Json = { completeness_status: 'COMPLETE', finding_status: 'CANDIDATE', review_priority: 'HIGH' };
    for (const [k, v] of Object.entries(group)) if (FINDING_KEYS.has(k)) f[k] = v;
    f.finding_id = ids[i];
    f.finding_group_id = group.finding_group_id;
    f.location = location;
    f.evidence = group.anchor_evidence;
    return f;
  });
}

export interface RunDocs {
  groups: Json[];
  findings: Json[];
  protocol: Json;
  submission: Json;
  strict: Json;
  sidecar: Json;
}

export function tyumenDocs(): RunDocs {
  const groups = example('finding_group');
  const objectLevel = example('finding').find((f) => f.location === 'OBJECT');
  if (!objectLevel) throw new Error('contract example with an OBJECT-level finding is missing');
  return {
    groups,
    findings: [...groups.flatMap(findingsOf), { ...objectLevel, finding_group_id: null }],
    protocol: example('protocol')[0]!,
    submission: example('submission.extended')[0]!,
    strict: example('submission.strict')[0]!,
    sidecar: example('submission_sidecar')[0]!,
  };
}

function sha256(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

export interface FixtureOptions {
  runId?: string;
  docs?: RunDocs;
  /** Change the artifacts.json entries before writing it (tampering tests). */
  editIndex?: (entries: Json[]) => void;
  withHidden?: boolean;
  withIndex?: boolean;
}

/** Writes `<runsRoot>/<runId>/` and returns its path. */
export function writeTyumenRun(runsRoot: string, opts: FixtureOptions = {}): string {
  const runId = opts.runId ?? 'm1-import-fixture';
  const docs = opts.docs ?? tyumenDocs();
  const dir = path.join(runsRoot, runId);
  mkdirSync(dir, { recursive: true });
  const withHidden = opts.withHidden ?? true;
  const manifest = syntheticRunManifest({
    runId,
    objects: [
      { object_id: TYUMEN, split: 'TRAIN_PUBLIC' },
      ...(withHidden ? [{ object_id: HIDDEN, split: 'TEST_HIDDEN' as const }] : []),
    ],
    files: [
      { file_id: 'F0171', object_id: TYUMEN, sha256: SHA(171), manifest_stage: 'PD' },
      { file_id: 'F0201', object_id: TYUMEN, sha256: SHA(201), manifest_stage: 'RD_ID_MIXED' },
      { file_id: 'F0202', object_id: TYUMEN, sha256: SHA(202), manifest_stage: 'RD_ID_MIXED' },
      ...(withHidden ? [{ file_id: 'F9901', object_id: HIDDEN, sha256: SHA(9901), manifest_stage: 'RD' }] : []),
    ],
  });
  const files: Array<{ kind: string; rel: string; format: string; schema: string | null; object_id?: string; file_id?: string; records?: number; body: string | Buffer }> = [
    { kind: 'RUN_MANIFEST', rel: 'run_manifest.json', format: 'JSON', schema: 'run_manifest', body: JSON.stringify(manifest, null, 2) },
    { kind: 'FINDING_GROUPS', rel: `findings/${TYUMEN}.groups.jsonl`, format: 'JSONL', schema: 'finding_group', object_id: TYUMEN, records: docs.groups.length, body: docs.groups.map((g) => JSON.stringify(g)).join('\n') + '\n' },
    { kind: 'FINDINGS', rel: `findings/${TYUMEN}.jsonl`, format: 'JSONL', schema: 'finding', object_id: TYUMEN, records: docs.findings.length, body: docs.findings.map((f) => JSON.stringify(f)).join('\n') + '\n' },
    { kind: 'PROTOCOL_JSON', rel: `protocol/${TYUMEN}.json`, format: 'JSON', schema: 'protocol', object_id: TYUMEN, body: JSON.stringify(docs.protocol, null, 2) },
    { kind: 'PROTOCOL_DOCX', rel: `protocol/${TYUMEN}.docx`, format: 'DOCX', schema: null, object_id: TYUMEN, body: Buffer.from('PK\u0003\u0004 docx stand-in') },
    { kind: 'SUBMISSION', rel: `submission/${TYUMEN}.json`, format: 'JSON', schema: 'submission.extended', object_id: TYUMEN, body: JSON.stringify(docs.submission, null, 2) },
    { kind: 'SUBMISSION_STRICT', rel: `submission-strict/${TYUMEN}.json`, format: 'JSON', schema: 'submission.strict', object_id: TYUMEN, body: JSON.stringify(docs.strict, null, 2) },
    { kind: 'SUBMISSION_SIDECAR', rel: `submission/${TYUMEN}.sidecar.json`, format: 'JSON', schema: 'submission_sidecar', object_id: TYUMEN, body: JSON.stringify(docs.sidecar, null, 2) },
    { kind: 'LAYOUT', rel: 'layout/F0202.json', format: 'JSON', schema: 'layout_artifacts', file_id: 'F0202', body: JSON.stringify(example('layout_artifacts')[0]) },
  ];
  if (withHidden) {
    // Not JSON at all: reading them would fail the import.
    files.push({ kind: 'FINDINGS', rel: `findings/${HIDDEN}.jsonl`, format: 'JSONL', schema: 'finding', object_id: HIDDEN, body: 'NEVER READ\n' });
    files.push({ kind: 'LAYOUT', rel: 'layout/F9901.json', format: 'JSON', schema: 'layout_artifacts', file_id: 'F9901', body: 'NEVER READ' });
  }
  const entries: Json[] = [];
  for (const f of files) {
    const abs = path.join(dir, ...f.rel.split('/'));
    mkdirSync(path.dirname(abs), { recursive: true });
    writeFileSync(abs, f.body);
    entries.push({
      kind: f.kind,
      path: f.rel,
      format: f.format,
      schema_name: f.schema,
      object_id: f.object_id ?? null,
      file_id: f.file_id ?? null,
      sha256: sha256(abs),
      size_bytes: statSync(abs).size,
      records: f.records ?? null,
      producer: { agent: 'AG-04', command: 'export' },
    });
  }
  opts.editIndex?.(entries);
  if (opts.withIndex ?? true) {
    writeFileSync(
      path.join(dir, 'artifacts.json'),
      JSON.stringify(
        { schema_version: 1, layout_version: '1', run_id: runId, generated_at: '2026-10-01T10:30:00Z', objects: [TYUMEN], commands: ['inventory', 'compare', 'export'], artifacts: entries },
        null,
        2,
      ),
    );
  }
  return dir;
}
