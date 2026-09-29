/** Row → API DTO mapping shared by the Drizzle repositories and the in-memory test store. */
import {
  type BatchRunDto,
  emptyStageCounts,
  type FileItemDto,
  MANIFEST_STAGES,
  type ManifestStage,
  type ObjectDetailDto,
  type ObjectSummaryDto,
  type StageCounts,
} from '../api-types';
import type { FileRow, ObjectRow, RunRow } from './schema';

export interface FileCounts {
  total: number;
  present: number;
  missing: number;
  byStage: StageCounts;
}

export function emptyFileCounts(): FileCounts {
  return { total: 0, present: 0, missing: 0, byStage: emptyStageCounts() };
}

/** Accumulate one (manifest_stage, local_status, n) group into the counters. */
export function addFileCount(counts: FileCounts, manifestStage: string, localStatus: string, n: number): void {
  counts.total += n;
  if (localStatus === 'MISSING_ON_DISK') counts.missing += n;
  else counts.present += n; // PRESENT or RECOVERED
  const stage = (MANIFEST_STAGES as readonly string[]).includes(manifestStage)
    ? (manifestStage as ManifestStage)
    : 'UNKNOWN';
  counts.byStage[stage] += n;
}

const iso = (d: Date) => d.toISOString();

export function toObjectSummary(
  row: ObjectRow,
  counts: FileCounts,
  lastRun: { batchRunId: string; importedAt: Date } | null,
): ObjectSummaryDto {
  return {
    object_id: row.id,
    name: row.name,
    split: row.split,
    scenario: row.scenario,
    indicator_color: row.indicatorColor,
    files_total: counts.total,
    files_present: counts.present,
    files_missing_on_disk: counts.missing,
    files_by_stage: counts.byStage,
    last_run:
      row.lastRunId && lastRun
        ? { id: row.lastRunId, batch_run_id: lastRun.batchRunId, imported_at: iso(lastRun.importedAt) }
        : null,
    updated_at: iso(row.updatedAt),
  };
}

export function toObjectDetail(
  row: ObjectRow,
  counts: FileCounts,
  lastRun: { batchRunId: string; importedAt: Date } | null,
): ObjectDetailDto {
  return {
    ...toObjectSummary(row, counts, lastRun),
    input_manifest_hash: row.inputManifestHash,
    address: row.address,
    customer: row.customer,
    contractor: row.contractor,
    permit_number: row.permitNumber,
    created_at: iso(row.createdAt),
  };
}

export function toFileItem(row: FileRow): FileItemDto {
  return {
    file_id: row.id,
    object_id: row.objectId,
    file_name: row.fileName,
    relative_path: row.filePath,
    extension: row.ext,
    size_bytes: row.sizeBytes,
    pdf_pages: row.pdfPages,
    sha256: row.fileHash,
    manifest_stage: row.manifestStage,
    stage_resolved: row.docStage,
    manifest_section: row.manifestSection,
    dataset_role: row.datasetRole,
    split: row.split,
    annotation_status: row.annotationStatus,
    duplicate_group: row.duplicateGroup,
    local_status: row.localStatus,
    sha256_verified: row.sha256Verified,
    last_run_id: row.lastRunId,
    updated_at: iso(row.updatedAt),
  };
}

export function toBatchRun(row: RunRow): BatchRunDto {
  return {
    id: row.id,
    batch_run_id: row.batchRunId,
    producer: row.producer,
    command: row.command,
    status: row.status,
    started_at: iso(row.startedAt),
    finished_at: row.finishedAt ? iso(row.finishedAt) : null,
    config_hash: row.configHash,
    versions: row.versions as Record<string, unknown>,
    inputs: row.inputs as Record<string, unknown>,
    manifest_ref: row.manifestRef,
    manifest_sha256: row.manifestSha256,
    objects_count: row.objectsCount,
    files_count: row.filesCount,
    warnings_count: Array.isArray(row.importWarnings) ? row.importWarnings.length : 0,
    imported_at: iso(row.importedAt),
    updated_at: iso(row.updatedAt),
  };
}
