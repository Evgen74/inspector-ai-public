import type { FileItem, ObjectDetail, ObjectSummary, Page } from '../src/api/types';

const run = { id: '01a0e4c8-7f40-715f-8073-c221218c9abb', batch_run_id: '20260927T000000Z-inventory', imported_at: '2026-09-27T21:32:20.160Z' };

function obj(id: string, name: string, split: ObjectSummary['split'], stages: ObjectSummary['files_by_stage'], missing = 0): ObjectSummary {
  const total = Object.values(stages).reduce((a, b) => a + b, 0);
  return {
    object_id: id,
    name,
    split,
    scenario: null,
    indicator_color: 'NONE',
    files_total: total,
    files_present: total - missing,
    files_missing_on_disk: missing,
    files_by_stage: stages,
    last_run: run,
    updated_at: run.imported_at,
  };
}

// Synthetic objects only (no hidden-object identifiers in code).
export const OBJECTS: Page<ObjectSummary> = {
  items: [
    obj('OBJ-SYNTH-ALPHA', 'Альфа', 'TRAIN_PUBLIC', { PD: 36, RD: 10, ID: 99, RD_ID_MIXED: 0, UNKNOWN: 0 }),
    obj('OBJ-SYNTH-BETA', 'Бета', 'TEST_HIDDEN', { PD: 89, RD: 93, ID: 31, RD_ID_MIXED: 0, UNKNOWN: 0 }, 2),
    obj('OBJ-SYNTH-GAMMA', 'Гамма', 'TRAIN_PUBLIC', { PD: 47, RD: 0, ID: 0, RD_ID_MIXED: 10, UNKNOWN: 1 }),
  ],
  total: 3,
  page: 1,
  page_size: 50,
};

export const GAMMA: ObjectDetail = {
  ...OBJECTS.items[2]!,
  input_manifest_hash: 'ab'.repeat(32),
  address: null,
  customer: null,
  contractor: null,
  permit_number: null,
  created_at: run.imported_at,
};

export function fileItem(id: string, name: string, stage: FileItem['manifest_stage'], extra: Partial<FileItem> = {}): FileItem {
  return {
    file_id: id,
    object_id: 'OBJ-SYNTH-GAMMA',
    file_name: name,
    relative_path: `Гамма/${name}`,
    extension: '.pdf',
    size_bytes: 1_572_864,
    pdf_pages: 24,
    sha256: 'cd'.repeat(32),
    manifest_stage: stage,
    stage_resolved: stage === 'PD' || stage === 'RD' || stage === 'ID' ? stage : null,
    manifest_section: 'OV',
    dataset_role: 'GOLD_SEED',
    split: 'TRAIN_PUBLIC',
    annotation_status: 'UNLABELED',
    duplicate_group: null,
    local_status: 'PRESENT',
    sha256_verified: null,
    last_run_id: run.id,
    updated_at: run.imported_at,
    ...extra,
  };
}
