/**
 * Response shapes of packages/contracts/openapi/openapi.yaml (snake_case). Responses are validated against the document in
 * local/test/demo, so a drift between these types and the YAML fails the tests.
 */
import type { ProblemItem } from './common/problem';

/** ManifestStage codes (packages/contracts/enums.yaml). */
export const MANIFEST_STAGES = ['PD', 'RD', 'ID', 'RD_ID_MIXED', 'UNKNOWN'] as const;
export type ManifestStage = (typeof MANIFEST_STAGES)[number];

export type StageCounts = Record<ManifestStage, number>;

export function emptyStageCounts(): StageCounts {
  return { PD: 0, RD: 0, ID: 0, RD_ID_MIXED: 0, UNKNOWN: 0 };
}

export interface RunRefDto {
  id: string;
  batch_run_id: string;
  imported_at: string;
}

export interface ObjectSummaryDto {
  object_id: string;
  name: string | null;
  split: string | null;
  scenario: string | null;
  indicator_color: string;
  files_total: number;
  files_present: number;
  files_missing_on_disk: number;
  files_by_stage: StageCounts;
  last_run: RunRefDto | null;
  updated_at: string;
}

export interface ObjectDetailDto extends ObjectSummaryDto {
  input_manifest_hash: string | null;
  address: string | null;
  customer: string | null;
  contractor: string | null;
  permit_number: string | null;
  created_at: string;
}

export interface FileItemDto {
  file_id: string;
  object_id: string;
  file_name: string;
  relative_path: string | null;
  extension: string | null;
  size_bytes: number | null;
  pdf_pages: number | null;
  sha256: string;
  manifest_stage: string;
  stage_resolved: string | null;
  manifest_section: string | null;
  dataset_role: string | null;
  split: string | null;
  annotation_status: string | null;
  duplicate_group: string | null;
  local_status: string;
  sha256_verified: boolean | null;
  last_run_id: string | null;
  updated_at: string;
}

export interface BatchRunDto {
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

export interface ImportedObjectDto {
  object_id: string;
  name: string | null;
  split: string;
  files_total: number;
  files_present: number;
  missing_on_disk: string[];
}

export interface BatchRunImportResultDto {
  run: BatchRunDto;
  created: boolean;
  objects: ImportedObjectDto[];
  files_imported: number;
  warnings: ProblemItem[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PageQuery {
  page: number;
  pageSize: number;
}
