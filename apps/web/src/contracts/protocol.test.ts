// @vitest-environment node
/**
 * The protocol viewer reads the contract, not a guess of it: every fixture the web uses (the D1 Тюменская
 * fixture and the synthetic mock variants) validates against packages/contracts/schemas/protocol.schema.json and
 * finding_group.schema.json, and every field the renderer reads exists in the schema.
 */
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import { buildMockObjects } from '../mocks/data';

const CONTRACTS = path.resolve(__dirname, '..', '..', '..', '..', 'packages', 'contracts');
const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const BASE = 'https://contracts.inspector-ai.local/schemas/';
// Same registration as the API (apps/api/src/contracts/contracts.ts): $id, else the base + file name.
for (const f of readdirSync(path.join(CONTRACTS, 'schemas')).filter((f) => f.endsWith('.schema.json'))) {
  const schema = JSON.parse(readFileSync(path.join(CONTRACTS, 'schemas', f), 'utf8')) as { $id?: string };
  ajv.addSchema(schema, schema.$id ?? BASE + f);
}
const validate = (name: string, data: unknown) => {
  const fn = ajv.getSchema(`${BASE}${name}.schema.json`)!;
  const ok = fn(data);
  return ok ? [] : (fn.errors ?? []).map((e) => `${e.instancePath} ${e.message}`);
};

describe('fixtures follow the contracts', () => {
  const objects = buildMockObjects();
  for (const [id, o] of objects) {
    for (const entry of o.protocols) {
      it(`${id} / ${entry.batchRunId}: protocol.schema.json`, () => {
        expect(validate('protocol', entry.protocol)).toEqual([]);
      });
      it(`${id} / ${entry.batchRunId}: finding_group.schema.json`, () => {
        for (const g of entry.groups) expect(validate('finding_group', g)).toEqual([]);
      });
    }
  }

  it('the D1 fixture is the gold: four groups, ten atomic findings, 314 drawn on РД p20 with the anchor on p18', () => {
    const tyumen = objects.get('OBJ-TYUMENSKAYA-5-GOLD-SEED')!.protocols[0]!;
    const atoms = tyumen.groups.flatMap((g) => g.finding_ids);
    expect(tyumen.groups).toHaveLength(4);
    expect(atoms).toHaveLength(10);
    const cfg = tyumen.groups.find((g) => g.finding_group_id.endsWith('IOS4-078-CFG-01'))!;
    expect(cfg.anchor_evidence.find((e) => e.stage === 'RD')!.pdf_page_number).toBe(18);
    expect(cfg.location_pages!['314']![0]!.pdf_page_number).toBe(20);
    expect(tyumen.protocol.evidence_cards.map((c) => c.card_no)).toEqual(['Б.1', 'Б.2', 'Б.3', 'Б.4']);
  });
});

describe('renderer fields exist in protocol.schema.json', () => {
  const schema = JSON.parse(readFileSync(path.join(CONTRACTS, 'schemas', 'protocol.schema.json'), 'utf8')) as {
    properties: Record<string, unknown>;
    $defs: Record<string, { properties: Record<string, unknown> }>;
  };
  const READ: Record<string, string[]> = {
    Header: ['title', 'generated_at_ru', 'version_line', 'status_line', 'scenario_line', 'recheck_running'],
    LoadStatusRow: ['stage', 'stage_ru', 'status', 'status_ru', 'files_loaded_text', 'files_expected', 'comment'],
    SummaryRow: ['key', 'label_ru', 'count', 'percent_text'],
    NotCheckedRow: ['no', 'parameter_code', 'section_ru', 'parameter_name', 'missing_document'],
    ViolationRow: ['no', 'section_ru', 'parameter_label', 'pd', 'rd', 'id', 'deviation', 'inspector_status', 'inspector_decision_ru', 'card_ref'],
    SuspicionRow: ['no', 'method', 'method_ru', 'description', 'pd', 'rd', 'id', 'inspector_status', 'inspector_decision_ru', 'rejection_reason', 'ai_comment', 'card_ref'],
    ResolutionCriticalRow: ['no', 'work_type', 'recommendation', 'is_draft'],
    ResolutionSubstantialRow: ['no', 'violation_kind', 'recommendation', 'is_draft'],
    CompletenessRow: ['parameter_code', 'section_ru', 'parameter_name', 'protocol_status', 'completeness_status', 'completeness_basis', 'missing_stage', 'document', 'reason_ru', 'action_ru'],
    CandidateRow: ['card_ref', 'parameter_label', 'locations', 'expected', 'actual', 'deviation_text', 'risk_level', 'inspector_status', 'comment'],
    NegativeRow: ['card_ref', 'parameter_label', 'locations', 'decided_by', 'reason_code', 'reason_ru', 'comment', 'ai_comment', 'decided_at'],
    HypothesisRow: ['card_ref', 'parameter_code', 'method', 'description', 'confidence', 'normative_base', 'evidence_bind_status', 'inspector_status'],
    CardSource: ['role', 'stage', 'file_id', 'file_name', 'file_sha256', 'document_code', 'revision', 'approval_status', 'pdf_page_number', 'sheet_number', 'geometry'],
    CardInspector: ['status', 'reason_code', 'basis_code', 'clarify_code', 'comment', 'decided_at'],
    EvidenceCard: ['card_no', 'finding_group_id', 'finding_ids', 'parameter_code', 'parameter_label', 'rule_version', 'locations', 'expected_value', 'actual_value', 'rationale', 'risk_level', 'criticality', 'approved_change_ref', 'sources', 'inspector', 'ai_comment'],
    RegistryRow: ['file_id', 'file_name', 'stage', 'section', 'document_code', 'revision', 'approval_status', 'pages', 'sha256', 'used', 'exclusion_reason'],
    Signature: ['inspector_name', 'inspector_position', 'signed_at', 'finalized_at', 'content_sha256'],
  };
  it.each(Object.entries(READ))('%s', (def, fields) => {
    const props = Object.keys(schema.$defs[def]!.properties);
    for (const f of fields) expect(props, `${def}.${f}`).toContain(f);
  });
  it('top-level blocks', () => {
    for (const f of ['protocol_no', 'object', 'is_final', 'status', 'scenario', 'versions', 'input_manifest_hash', 'content_sha256', 'header', 'appendix2', 'tz92_tables', 'evidence_cards', 'input_registry', 'signature', 'ext']) {
      expect(Object.keys(schema.properties)).toContain(f);
    }
  });
});
