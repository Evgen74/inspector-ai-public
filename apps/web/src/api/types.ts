/** Response shapes of packages/contracts/openapi/openapi.yaml (hand-written for M0; Orval generation is planned). */

export type ManifestStage = 'PD' | 'RD' | 'ID' | 'RD_ID_MIXED' | 'UNKNOWN';
export const MANIFEST_STAGES: ManifestStage[] = ['PD', 'RD', 'ID', 'RD_ID_MIXED', 'UNKNOWN'];

export type StageCounts = Record<ManifestStage, number>;

export interface RunRef {
  id: string;
  batch_run_id: string;
  imported_at: string;
}

export interface ObjectSummary {
  object_id: string;
  name: string | null;
  split: 'TRAIN_PUBLIC' | 'TEST_HIDDEN' | null;
  scenario: string | null;
  indicator_color: 'RED' | 'YELLOW' | 'GREEN' | 'NONE';
  files_total: number;
  files_present: number;
  files_missing_on_disk: number;
  files_by_stage: StageCounts;
  last_run: RunRef | null;
  updated_at: string;
}

export interface ObjectDetail extends ObjectSummary {
  input_manifest_hash: string | null;
  address: string | null;
  customer: string | null;
  contractor: string | null;
  permit_number: string | null;
  created_at: string;
}

export interface FileItem {
  file_id: string;
  object_id: string;
  file_name: string;
  relative_path: string | null;
  extension: string | null;
  size_bytes: number | null;
  pdf_pages: number | null;
  sha256: string;
  manifest_stage: ManifestStage;
  stage_resolved: 'PD' | 'RD' | 'ID' | null;
  manifest_section: string | null;
  dataset_role: string | null;
  split: string | null;
  annotation_status: string | null;
  duplicate_group: string | null;
  local_status: 'PRESENT' | 'RECOVERED' | 'MISSING_ON_DISK';
  sha256_verified: boolean | null;
  last_run_id: string | null;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface BatchRun {
  id: string;
  batch_run_id: string;
  producer: string;
  command: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  config_hash: string;
  versions: Record<string, unknown>;
  inputs: Record<string, unknown>;
  manifest_ref: string;
  manifest_sha256: string;
  objects_count: number;
  files_count: number;
  warnings_count: number;
  imported_at: string;
  updated_at: string;
}

export interface ProblemItem {
  code: string;
  title: string;
  detail: string;
  details?: Record<string, unknown>;
  pointer?: string;
  field?: string;
}

export interface ImportResult {
  run: BatchRun;
  created: boolean;
  objects: Array<{
    object_id: string;
    name: string | null;
    split: string;
    files_total: number;
    files_present: number;
    missing_on_disk: string[];
  }>;
  files_imported: number;
  warnings: ProblemItem[];
}

export interface Health {
  status: 'ok' | 'degraded';
  service: string;
  version: string;
  time: string;
  checks: { database: { status: 'up' | 'down'; latency_ms: number } };
}

/** RFC 9457 body (packages/contracts/schemas/problem.schema.json). */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  code: string;
  request_id: string;
  timestamp: string;
  retryable: boolean;
  details?: Record<string, unknown>;
  errors?: ProblemItem[];
  warnings?: ProblemItem[];
}
