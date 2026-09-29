/**
 * Types of the artifacts read by the batch import:
 * - RunManifest — packages/contracts/schemas/run_manifest.schema.json (runs/<run_id>/run_manifest.json);
 * - ManifestRow — packages/contracts/schemas/manifest_row.schema.json (organizer document_manifest.jsonl).
 * Both are validated with the contract schemas before use; these types only describe the validated shape.
 */
import { readFileSync } from 'node:fs';

export interface RunManifestObject {
  object_id: string;
  split: 'TRAIN_PUBLIC' | 'TEST_HIDDEN';
  input_manifest_hash: string;
  files_total: number;
  files_present: number;
  missing_on_disk: string[];
  scenario?: string | null;
  checks_total?: number | null;
  artifacts?: Record<string, string>;
}

export interface RunManifestFile {
  file_id: string;
  object_id: string;
  sha256: string;
  manifest_stage: string;
  stage_resolved?: string | null;
  local_status: string;
  sha256_verified?: boolean | null;
  extension?: string;
  pdf_pages?: number | null;
  page_basis?: string | null;
  status?: string | null;
  pages_ocr?: number | null;
  duration_ms?: number | null;
  error_code?: string | null;
  warnings?: string[];
}

export interface RunManifest {
  schema_version: 1;
  run_id: string;
  producer: 'inspector-batch';
  command?: string;
  started_at: string;
  finished_at?: string | null;
  status: string;
  config_hash: string;
  freeze_tag?: string | null;
  versions: {
    pipeline_version: string;
    matrix_version?: string | null;
    dataset_version?: string | null;
    model_version?: string | null;
    code_version?: string | null;
    contract_version?: string | null;
    engine_versions?: Record<string, string>;
  };
  inputs: {
    manifest_sha256: string;
    catalog_sha256: string;
    submission_schema_sha256: string;
    split_policy_sha256?: string;
    models_manifest_sha256?: string;
  };
  host?: Record<string, unknown>;
  objects: RunManifestObject[];
  files: RunManifestFile[];
  timings_s?: Record<string, number>;
  warnings?: string[];
  ext?: Record<string, unknown>;
}

export interface ManifestRow {
  schema_version: string;
  file_id: string;
  object_id: string;
  corpus: string;
  dataset_role: string;
  split: string;
  relative_path: string;
  extension: string;
  size_bytes: number;
  sha256: string;
  stage: string;
  section: string;
  pdf_pages: number | null;
  annotation_status: string;
  exclusion_reason: string | null;
  duplicate_group: string | null;
  distribution_status: string;
  label_visibility: string;
  [extra: string]: unknown;
}

/** Parse a JSONL file; blank lines are skipped. Throws with the 1-based line number on bad JSON. */
export function readJsonl<T>(file: string): T[] {
  const rows: T[] = [];
  const lines = readFileSync(file, 'utf8').split('\n');
  lines.forEach((line, index) => {
    if (!line.trim()) return;
    try {
      rows.push(JSON.parse(line) as T);
    } catch (err) {
      throw new Error(`строка ${index + 1}: ${err instanceof Error ? err.message : String(err)}`);
    }
  });
  return rows;
}

/** Base name of a manifest relative_path (always «/»-separated). */
export function baseName(relativePath: string): string {
  const parts = relativePath.split('/');
  return parts[parts.length - 1] || relativePath;
}
