/**
 * Types of the verification API (apps/api/src/modules/verification/openapi/verification.openapi.yaml, owner
 * AG-05). Hand-written until AG-00 merges the overlay and AG-08 regenerates api/schema.gen.ts from it.
 */
import type { EvidenceCard, FindingGroup } from '../../contracts/protocol';

export interface UserRef {
  user_id: string;
  full_name: string;
}

export interface GateItem {
  code: string;
  count: number;
  finding_ids: string[];
}

export interface ProtocolVersionRef {
  protocol_id: string;
  version: number;
  protocol_no: string;
  status: string;
  is_final: boolean;
  version_reason: string;
  content_sha256: string;
  generated_at: string;
  finalized_at: string | null;
  finalized_by: UserRef | null;
  superseded_at: string | null;
  superseded_reason: string | null;
}

export interface VerificationSummary {
  process_id: string;
  object: { object_id: string; name: string | null; address: string | null };
  run: { run_id: string; batch_run_id: string };
  status: string;
  verification_status: string;
  status_line: string;
  row_version: number;
  scenario: string | null;
  scenario_ru: string | null;
  upload_status: Record<string, string> | null;
  versions: { matrix_version: string | null; pipeline_version: string | null; dataset_version: string | null; model_version: string | null; input_manifest_hash: string | null };
  protocol: ProtocolVersionRef | null;
  protocol_versions: ProtocolVersionRef[];
  counts: {
    reviewable: number;
    pending: number;
    confirmed: number;
    negative: number;
    clarification: number;
    disputes_open: number;
    non_reviewable: number;
    missing_document: number;
    comparison_impossible: number;
    suspicions_pending: number;
    dataset_items: number;
  };
  gate: { can_finalize: boolean; blockers: GateItem[]; warnings: GateItem[] };
  capabilities: { can_decide: boolean; can_claim: boolean; can_reopen: boolean; can_finalize: boolean; can_unfinalize: boolean };
  assigned_inspector: UserRef | null;
  verification_started_at: string | null;
  completed_at: string | null;
  finalized_at: string | null;
  next_finding_id: string | null;
}

export interface ObjectVerification {
  object_id: string;
  object_name: string | null;
  processes: VerificationSummary[];
}

export type QueueTab = 'ALL' | 'PENDING' | 'CLARIFICATION' | 'CONFIRMED' | 'NEGATIVE' | 'DISPUTES';

export interface QueueItem {
  finding_id: string;
  finding_group_id: string | null;
  card_no: string | null;
  param_code: string;
  parameter_label: string;
  location: string;
  location_type: string;
  matrix_scope: string;
  kind: string;
  criticality_level: string | null;
  protocol_status: string;
  risk_level: string | null;
  review_priority: string | null;
  confidence: number | null;
  inspector_status: string | null;
  finding_status: string | null;
  completeness_status: string | null;
  lifecycle_state: string;
  has_open_dispute: boolean;
  review_required_reason: string | null;
  decided_at: string | null;
  decided_by: UserRef | null;
  row_version: number;
  position?: number;
}

export interface VerificationQueue {
  process_id: string;
  tab: QueueTab;
  total: number;
  counts: Record<QueueTab, number>;
  items: QueueItem[];
}

export interface CardSourceView {
  role: string | null;
  stage: string;
  stage_ru: string;
  file_id: string;
  file_name: string | null;
  file_sha256: string | null;
  document_code: string | null;
  revision: string | null;
  approval_status: string | null;
  pdf_page_number: number;
  sheet_number: string | null;
  geometry: { boxes?: number[][]; polygons?: number[][][] } | null;
  geometry_space: string | null;
  localization: string | null;
  is_anchor: boolean;
  location_page: boolean;
}

export interface DecisionRecord {
  decision_id: string;
  finding_id: string;
  decision: string;
  effective_status?: string;
  reason_code?: string | null;
  basis_code?: string | null;
  clarify_code?: string | null;
  comment: string;
  comment_source?: string;
  ai_verdict?: string | null;
  ai_comment?: string | null;
  system_comment?: string | null;
  gold_effect?: string;
  decided_by: string;
  decided_at: string;
  [k: string]: unknown;
}

export interface HistoryItem {
  decision: DecisionRecord;
  user: UserRef | null;
  ai_rule_ids: string[];
  resolves_dispute_id: number | null;
}

export interface Dispute {
  dispute_id: number;
  finding_id: string;
  violation_id: number;
  decision_id: string;
  resolution_status: string;
  rejection_reason: string;
  inspector_comment: string;
  ai_comment: string;
  ai_rule_ids: string[];
  created_at: string;
  resolved_at: string | null;
  resolved_by: UserRef | null;
  resolution_comment: string | null;
  resolution_decision_id: string | null;
  row_version: number;
}

export interface FieldCheck {
  key: string;
  label_ru: string;
  present: boolean;
  partial: boolean;
}

export interface EvidenceCardView {
  process_id: string;
  object_id: string;
  finding_id: string;
  finding_group_id: string | null;
  card_no: string | null;
  row_version: number;
  evidence_fingerprint: string;
  param: { code: string; id: number | null; label: string; rule_code: string | null; rule_version: string | null; matrix_scope: string; parameter_mapping_status: string | null; alt_param_codes: string[]; element_noun: string | null };
  kind: string;
  location: string;
  location_type: string;
  location_text: string;
  values: { expected: unknown; actual: unknown; pd: unknown; rd: unknown; id: unknown; axis: string | null; comparison_result: string | null; comparison_result_ru: string | null; discrepancy_type: string | null; delta: Record<string, unknown> | null };
  criticality: string | null;
  criticality_level: string | null;
  protocol_status: string;
  violation_label: string;
  risk_level: string | null;
  review_priority: string | null;
  confidence: number | null;
  risk_note: string;
  rationale: string | null;
  recommendation: { text?: string } | null;
  statuses: { finding_status: string | null; machine_finding_status: string | null; completeness_status: string | null; inspector_status: string | null; lifecycle_state: string; decided_by: string | null; review_required_reason: string | null };
  approved_change_ref: string;
  sources: CardSourceView[];
  inspector: {
    status: string | null;
    reason_code: string | null;
    basis_code: string | null;
    clarify_code: string | null;
    comment: string | null;
    decided_at: string | null;
    user: UserRef | null;
    decision_id: string | null;
    ai_verdict: string | null;
    ai_comment: string | null;
    system_comment: string | null;
  };
  ai_suggestion: { action: string; basis_code: string; confidence: number | null; explanation: string | null };
  prefill: { confirm_basis_code: string; confirm_comment: string; reject_comments: Record<string, string>; clarify_comments: Record<string, string>; suggested_fixes: Record<string, string> };
  history: HistoryItem[];
  disputes: Dispute[];
  open_dispute: Dispute | null;
  process: { status: string; verification_status: string; status_line: string; scenario: string | null; scenario_ru: string | null; upload_status: Record<string, string> | null; row_version: number };
  field_checklist: FieldCheck[];
  navigation: { position: number; total: number; prev_finding_id: string | null; next_finding_id: string | null; next_pending_finding_id: string | null };
  evidence_card: EvidenceCard;
  finding_group: FindingGroup | null;
}

export interface ClientMetrics {
  time_on_card_ms: number;
  clicks: number;
  keys: number;
  input: 'MOUSE' | 'KEYBOARD' | 'MIXED';
}

export interface DecisionRequest {
  decision: 'CONFIRMED_VIOLATION' | 'NEGATIVE_VERIFIED' | 'CLARIFICATION_REQUIRED' | 'REVERT_TO_PENDING';
  reason_code?: string | null;
  basis_code?: string | null;
  clarify_code?: string | null;
  comment?: string | null;
  comment_source?: 'TEMPLATE' | 'EDITED' | 'MANUAL' | null;
  approved_change_ref?: string | null;
  correct_file_id?: string | null;
  correct_locus?: string | null;
  duplicate_of?: string | null;
  na_basis?: string | null;
  justification?: string | null;
  planned_action?: string | null;
  override_of_decision_id?: string | null;
  seen_fingerprint: string;
  client_metrics?: ClientMetrics;
}

export interface AiResult {
  verdict: 'AGREE' | 'UNCERTAIN' | 'DISAGREE';
  confidence: number;
  rule_ids: string[];
  argument: string | null;
  comment: string;
}

export interface DecisionResult {
  finding: QueueItem;
  decision: DecisionRecord;
  ai: AiResult | null;
  system_comment: string;
  dispute: Dispute | null;
  process: { status: string; verification_status: string; row_version: number; pending: number; disputes_open: number; can_finalize: boolean };
  next_finding_id: string | null;
}

export interface CodeItem {
  code: string;
  label_ru: string;
  hotkey?: string | null;
}

export interface RejectCodeItem extends CodeItem {
  family: string | null;
  requires: string[];
  suggested_fix_ru: string;
}

export interface DecisionCodes {
  reject: RejectCodeItem[];
  confirm: CodeItem[];
  clarify: CodeItem[];
  unfinalize: CodeItem[];
  revision_basis: CodeItem[];
  planned_action: CodeItem[];
  limits: { other_comment_min: number; unfinalize_reason_min: number; comment_max: number; undo_window_ms: number };
}

export interface CompletenessView {
  process_id: string;
  scenario: string | null;
  scenario_ru: string | null;
  scenario_line: string | null;
  upload_status: Record<string, string> | null;
  load_status_rows: Array<{ stage: string; stage_ru: string; status: string; status_ru: string; files_loaded_text: string; files_expected?: number | null; comment: string }>;
  not_checked_no_id: { count: number; rows: Array<{ no: number; parameter_code: string; section_ru: string; parameter_name: string; missing_document: string }> };
  completeness_rows: Array<{ parameter_code: string; parameter_name: string; protocol_status: string; completeness_status?: string | null; reason_ru?: string | null; action_ru?: string | null; document?: string | null }>;
  non_reviewable: Array<{ finding_id: string; param_code: string; location: string; protocol_status: string; violation_label: string; completeness_status: string | null; completeness_basis: string | null }>;
  note: string;
}

export interface FinalizeResult {
  process_id: string;
  status: string;
  verification_status: string;
  row_version: number;
  protocol: ProtocolVersionRef;
  counts: { confirmed: number; negative: number; clarification: number };
  dataset_items: number;
  rin: { violations: number; transfer_allowed: boolean };
}

export interface UnfinalizeResult {
  process_id: string;
  status: string;
  verification_status: string;
  row_version: number;
  protocol: ProtocolVersionRef;
  suspended_dataset_items: number;
}

export interface ProcessTransition {
  process_id: string;
  status: string;
  verification_status: string;
  row_version: number;
  assigned_inspector_id: string | null;
  verification_started_at: string | null;
}

export interface AuthSession {
  user: { id: string; login: string; full_name: string; position: string | null };
  roles: string[];
  permissions: Array<{ code: string; scope: string }>;
  csrf_token: string;
}

export interface UsabilityReport {
  process_id: string;
  decisions: number;
  measured_decisions: number;
  clicks: { n: number; mean: number | null; median: number | null; p90: number | null; max: number | null; share_within_target: number | null };
  keys: { n: number; mean: number | null; median: number | null; p90: number | null; max: number | null };
  keyboard_only_share: number | null;
  time_on_card_ms: { n: number; mean: number | null; median: number | null; p90: number | null; max: number | null };
  protocol_time_ms: number | null;
  active_time_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
  inspectors: number;
  targets: { protocol_minutes: number; clicks_per_decision: number };
  met: { protocol_time: boolean | null; clicks: boolean | null };
}
