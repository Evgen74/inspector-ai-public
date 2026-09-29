/**
 * Lean M4 GOLD capture (ТЗ §9.4, §14.1; 97 §2.15): at finalization every final inspector decision with a complete
 * evidence card becomes a Dataset_Items draft. The label is written in the organizers' own gold format
 * (gold_check.schema.json = public_train_checks.jsonl rows, v1.0 inspector vocabulary CONFIRMED / REJECTED), so a
 * curator can diff our drafts against the train gold field by field.
 *
 * Never a draft: CANDIDATE / PENDING, CLARIFICATION_REQUIRED, open disputes, SUSPICION, MISSING_EVIDENCE, split
 * parents (ТЗ §9.4 «CANDIDATE, SUSPICION, MISSING_EVIDENCE и незавершённые решения в обучение не включаются»).
 * Drafts never flow into a submission: they are rows of dataset_items only.
 */

type StageValue = string | number | boolean | null;

export interface GoldCheckInput {
  findingId: string;
  findingGroupId: string | null;
  objectId: string;
  /** ManifestSplit of the object (TRAIN_PUBLIC | TEST_HIDDEN). */
  objectSplit: string;
  matrixScope: string;
  paramId: number | null;
  paramCode: string;
  locationType: string;
  location: string;
  pdValue: StageValue;
  rdValue: StageValue;
  idValue: StageValue;
  comparisonResult: string | null;
  protocolStatus: string;
  criticality: string | null;
  documentStatus: string | null;
  evidence: Array<{ stage: string; file_id: string; pdf_page_number: number; document_sheet_number?: string | number | null }>;
}

export type GoldLabel = 'POSITIVE' | 'NEGATIVE';

/** InspectorStatus → GoldLabel; everything else yields no label (invariant I7). */
export function goldLabelOf(status: string | null, decidedBy: string | null): GoldLabel | null {
  if (decidedBy !== 'INSPECTOR') return null;
  if (status === 'CONFIRMED_VIOLATION') return 'POSITIVE';
  if (status === 'NEGATIVE_VERIFIED') return 'NEGATIVE';
  return null;
}

/** ManifestSplit → Split (97 §2.7: TRAIN_PUBLIC → TRAIN, TEST_HIDDEN → HIDDEN_TEST). */
export function datasetSplit(manifestSplit: string | null): string {
  return manifestSplit === 'TEST_HIDDEN' ? 'HIDDEN_TEST' : 'TRAIN';
}

/** One public_train_checks.jsonl-shaped row for the label (gold_check.schema.json). */
export function goldRecord(input: GoldCheckInput, label: GoldLabel): Record<string, unknown> {
  const positive = label === 'POSITIVE';
  const record: Record<string, unknown> = {
    check_id: input.findingId,
    finding_group_id: input.findingGroupId ?? input.findingId,
    object_id: input.objectId,
    split: input.objectSplit,
    matrix_scope: input.matrixScope,
    parameter_id: input.paramId,
    parameter_code: input.paramCode,
    location_type: input.locationType,
    location: input.location,
    pd_value: input.pdValue,
    rd_value: input.rdValue,
    id_value: input.idValue,
    comparison_result: positive ? input.comparisonResult : null,
    violation_label: positive ? 'VIOLATION_PRESENT' : 'NO_VIOLATION',
    protocol_status: positive ? input.protocolStatus : 'OK',
    criticality: input.criticality,
    // v1.0 vocabulary of the organizers' gold rows (97 §2.6 aliases).
    inspector_status: positive ? 'CONFIRMED' : 'REJECTED',
    evidence: input.evidence.map((e) => ({
      stage: e.stage,
      file_id: e.file_id,
      pdf_page_number: e.pdf_page_number,
      ...(e.document_sheet_number !== undefined && e.document_sheet_number !== null ? { document_sheet_number: e.document_sheet_number } : {}),
    })),
  };
  if (input.documentStatus) record.document_status = input.documentStatus;
  return record;
}
