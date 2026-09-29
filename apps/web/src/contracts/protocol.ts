/**
 * TypeScript view of packages/contracts/schemas/protocol.schema.json and finding_group.schema.json (owner AG-00;
 * builder AG-04). Rows carry both machine codes and the rendered Russian cell text: the viewer prints the text
 * fields verbatim and never re-derives wording. `src/contracts/protocol.test.ts` validates the fixtures against
 * the JSON Schemas and checks that every field read here exists in the schema.
 */

export type BBoxNorm = [number, number, number, number];
export type PolygonNorm = Array<[number, number]>;

export interface Geometry {
  boxes?: BBoxNorm[];
  polygons?: PolygonNorm[];
}

export type StageValue = string | number | boolean | null;

export interface ProtocolObject {
  object_id: string;
  name?: string | null;
  address?: string | null;
  supervision_case_no?: string | null;
  customer?: string | null;
  contractor?: string | null;
}

export interface ProtocolHeader {
  title: string;
  generated_at_ru: string;
  version_line: string;
  status_line: string;
  scenario_line?: string | null;
  recheck_running?: boolean;
}

export interface LoadStatusRow {
  stage: string;
  stage_ru: string;
  status: string;
  status_ru: string;
  files_loaded: number;
  files_loaded_text: string;
  files_expected?: number | null;
  comment: string;
}

export interface SummaryRow {
  key: string;
  label_ru: string;
  count: number;
  percent: number;
  percent_text: string;
}

export interface NotCheckedRow {
  no: number;
  parameter_code: string;
  parameter_id?: number | null;
  section_ru: string;
  parameter_name: string;
  missing_document: string;
}

export interface Deviation {
  direction?: string | null;
  text: string;
  magnitude?: number | null;
  unit?: string | null;
}

export interface ViolationRow {
  no: number;
  section_ru: string;
  parameter_label: string;
  parameter_code: string;
  parameter_id?: number | null;
  matrix_scope?: string;
  locations?: string[];
  pd: string;
  rd: string;
  id: string;
  deviation: Deviation;
  inspector_status: string;
  inspector_decision_ru: string;
  card_ref: string;
  finding_group_id?: string | null;
  finding_ids?: string[];
  criticality_level?: string | null;
}

export interface SuspicionRow {
  no: number;
  method: string;
  method_ru: string;
  description: string;
  pd: string;
  rd: string;
  id: string;
  parameter_code?: string | null;
  inspector_status: string;
  inspector_decision_ru: string;
  rejection_reason: string;
  ai_comment: string;
  confidence?: number;
  card_ref: string;
  finding_group_id?: string | null;
}

export interface ResolutionCriticalRow {
  no: number;
  work_type: string;
  recommendation: string;
  parameter_code?: string;
  is_draft?: boolean;
  text_origin?: string;
  template_id?: string | null;
  source_row_no?: number | null;
}

export interface ResolutionSubstantialRow {
  no: number;
  violation_kind: string;
  recommendation: string;
  parameter_code?: string;
  is_draft?: boolean;
  text_origin?: string;
  template_id?: string | null;
  source_row_no?: number | null;
}

export interface CompletenessRow {
  parameter_code: string;
  parameter_name: string;
  section_ru?: string | null;
  protocol_status: string;
  completeness_status?: string;
  completeness_basis?: string | null;
  missing_stage?: string | null;
  document?: string | null;
  reason_ru?: string | null;
  action_ru?: string | null;
}

export interface CandidateRow {
  card_ref: string;
  finding_group_id?: string | null;
  finding_ids?: string[];
  parameter_code: string;
  parameter_label: string;
  locations?: string[];
  expected?: StageValue;
  actual?: StageValue;
  deviation_text?: string | null;
  criticality_level?: string | null;
  risk_level?: string;
  confidence?: number;
  inspector_status: string;
  basis_code?: string | null;
  clarify_code?: string | null;
  comment?: string | null;
  decided_at?: string | null;
}

export interface NegativeRow {
  card_ref?: string | null;
  parameter_code: string;
  parameter_label: string;
  locations?: string[];
  decided_by: string;
  reason_code?: string | null;
  reason_ru?: string | null;
  comment?: string | null;
  ai_comment?: string | null;
  decided_at?: string | null;
}

export interface HypothesisRow {
  card_ref: string;
  finding_group_id?: string | null;
  parameter_code?: string | null;
  method: string;
  description: string;
  confidence?: number;
  normative_base?: string | null;
  evidence_bind_status?: string | null;
  inspector_status: string;
}

export interface CardSource {
  role?: string;
  stage: string;
  file_id: string;
  file_name?: string | null;
  file_sha256?: string | null;
  document_code?: string | null;
  revision?: string | null;
  approval_status?: string | null;
  approval_date?: string | null;
  pdf_page_number: number;
  sheet_number?: string | number | null;
  geometry?: Geometry;
  geometry_space?: string;
  thumbnail?: string | null;
  /** Value-conflict suspicions: the value this page supports, as displayed («1,7 %»). */
  value_text?: string | null;
}

export interface CardInspector {
  status: string;
  reason_code?: string | null;
  basis_code?: string | null;
  clarify_code?: string | null;
  comment?: string | null;
  user_id?: string | null;
  decided_at?: string | null;
}

export interface EvidenceCard {
  card_no: string;
  finding_group_id?: string | null;
  finding_ids?: string[];
  parameter_code: string;
  parameter_label: string;
  rule_version?: string | null;
  locations: string[];
  expected_value?: StageValue;
  actual_value?: StageValue;
  delta?: Record<string, unknown> | null;
  rationale?: string | null;
  risk_level?: string;
  review_priority?: string;
  criticality?: string | null;
  approved_change_ref?: string | null;
  sources: CardSource[];
  inspector: CardInspector;
  ai_verdict?: string | null;
  ai_comment?: string | null;
  /** Value-conflict suspicions: the conflicting values per stage as displayed; null = the stage has no value. */
  stage_values?: { PD?: string | null; RD?: string | null; ID?: string | null } | null;
}

export interface RegistryRow {
  file_id: string;
  file_name?: string | null;
  stage: string | null;
  manifest_stage?: string | null;
  section?: string | null;
  document_code?: string | null;
  revision?: string | null;
  approval_status?: string | null;
  pages?: number | null;
  sha256: string;
  local_status?: string;
  used: boolean;
  exclusion_reason?: string | null;
}

export interface Signature {
  inspector_name?: string | null;
  inspector_position?: string | null;
  signed_at?: string | null;
  finalized_at?: string | null;
  finalized_by?: string | null;
  content_sha256?: string | null;
}

export interface Protocol {
  schema_version: 1;
  protocol_no: string;
  run_id?: string | null;
  object: ProtocolObject;
  version: number;
  is_final: boolean;
  status: string;
  process_status?: string | null;
  generated_at: string;
  scenario: string;
  scenario_base?: string | null;
  upload_status?: { pd?: string; rd?: string; id?: string };
  versions: {
    pipeline_version: string;
    matrix_version?: string | null;
    dataset_version?: string | null;
    model_version?: string | null;
    code_version?: string | null;
    contract_version?: string | null;
    engine_versions?: Record<string, string>;
  };
  input_manifest_hash: string;
  content_sha256?: string | null;
  header: ProtocolHeader;
  appendix2: {
    section1_load_status: { rows: LoadStatusRow[]; scenario_line?: string | null };
    section2_summary: { rows: SummaryRow[]; footnotes?: string[] };
    section3_not_checked_no_id: { count: number; rows: NotCheckedRow[] };
    section4_critical: { count: number; rows: ViolationRow[] };
    section5_substantial: { count: number; rows: ViolationRow[] };
    section6_ai_suspicions: { count: number; rows: SuspicionRow[] };
    section7_resolution: { critical: ResolutionCriticalRow[]; substantial: ResolutionSubstantialRow[] };
    footnotes?: string[];
  };
  tz92_tables: {
    a1_completeness?: CompletenessRow[];
    a2_candidates?: CandidateRow[];
    a3_confirmed?: CandidateRow[];
    a4_negative_verified?: NegativeRow[];
    a5_hypotheses?: HypothesisRow[];
    banner_ru?: string;
  };
  evidence_cards: EvidenceCard[];
  input_registry: { files: RegistryRow[]; parser_versions?: Record<string, string> };
  signature?: Signature | null;
  submission_checks?: Array<Record<string, unknown>>;
  ext?: Record<string, unknown>;
}

// ── finding_group.schema.json ──

export interface EvidenceRef {
  stage: string;
  file_id: string;
  pdf_page_number: number;
  document_sheet_number?: string | number | null;
  file_sha256?: string;
  page_basis?: string;
  role?: string;
  is_anchor?: boolean;
  geometry?: Geometry;
  geometry_space?: string;
  localization?: string;
  document_code?: string | null;
  revision?: string | null;
  note?: string | null;
}

export interface FindingGroup {
  finding_group_id: string;
  object_id: string;
  run_id?: string | null;
  matrix_scope: string;
  parameter_code: string;
  parameter_id?: number | null;
  title?: string | null;
  element_noun?: string | null;
  comparison_result: string;
  location_type: string;
  locations: string[];
  pd_value?: StageValue;
  rd_value?: StageValue;
  id_value?: StageValue;
  violation_label: string;
  protocol_status: string;
  criticality: string;
  criticality_level?: string | null;
  finding_status?: string | null;
  risk_level?: string;
  confidence?: number;
  anchor_evidence: EvidenceRef[];
  evidence?: EvidenceRef[];
  location_pages?: Record<string, EvidenceRef[]>;
  finding_ids: string[];
  discovery_method?: string | null;
  evidence_bind_status?: string | null;
  rationale?: string | null;
  recommendation?: { text: string; template_id?: string | null; text_origin?: string; work_type?: string | null; normative_refs?: string[] } | null;
  card_no?: string | null;
}

/** «[карточка Б.3]» references inside rendered labels. */
export const CARD_REF_RE = /\s*\[карточка (Б\.\d+)\]\s*$/;

export function splitCardRef(label: string): { text: string; cardRef: string | null } {
  const m = label.match(CARD_REF_RE);
  return m ? { text: label.slice(0, m.index), cardRef: m[1] ?? null } : { text: label, cardRef: null };
}
