/**
 * Tables filled by the batch-run import v2 (owner AG-00 for the import; semantics owners per 90 §3.3):
 *
 * | table               | 90 / 97 name and owner        | filled from (run_layout.yaml kind)                  |
 * |---------------------|-------------------------------|-----------------------------------------------------|
 * | processes           | processes (B00)               | one per imported run × object                       |
 * | process_files       | process_files (B00)           | the object's files of run_manifest.json             |
 * | protocols           | protocols (B04), versioned    | PROTOCOL_JSON (content_json = the Protocol contract) |
 * | protocol_exports    | protocol_exports (B04)        | PROTOCOL_JSON / _DOCX / _PDF references             |
 * | evidence_groups     | evidence_groups (B04)         | FINDING_GROUPS (evidence_group_id = finding_group_id)|
 * | checks              | checks (ТЗ #2, B04/B05)       | FINDINGS (one atomic check per row)                 |
 * | evidence_fragments  | evidence_fragments (ТЗ #14)   | Finding.evidence, group anchors and location pages  |
 * | suspicions          | suspicions (ТЗ #8, B07)       | FREE_SEARCH finding groups (Приложение 2 §6)        |
 * | submission_exports  | submission_exports (97 §2.8)  | SUBMISSION / SUBMISSION_STRICT / SUBMISSION_SIDECAR |
 * | run_artifacts       | claim-check references        | every entry of artifacts.json (layout, tables, …)   |
 *
 * Enum-valued columns hold codes of packages/contracts/enums.yaml (noted per column). Machine columns are
 * rewritten by a re-import; inspector columns (checks.inspector_status … decision_comment) never are.
 */
import { sql } from 'drizzle-orm';
import {
  bigint,
  bigserial,
  boolean,
  char,
  index,
  integer,
  jsonb,
  numeric,
  pgTable,
  primaryKey,
  text,
  timestamp,
  unique,
  uuid,
  varchar,
} from 'drizzle-orm/pg-core';
import { files, objects, runs } from '../../db/schema';

const tstz = (name: string) => timestamp(name, { withTimezone: true, mode: 'date' });
const confidence = (name: string) => numeric(name, { precision: 4, scale: 3, mode: 'number' });

export const processes = pgTable(
  'processes',
  {
    /** UUID v7 */
    id: uuid('id').primaryKey(),
    objectId: varchar('object_id', { length: 64 })
      .notNull()
      .references(() => objects.id),
    /** ProcessStatus */
    status: varchar('status', { length: 16 }).notNull(),
    /** ProcessStage */
    stage: varchar('stage', { length: 24 }),
    /** ProcessSource (BATCH_IMPORT for imported runs) */
    source: varchar('source', { length: 16 }).notNull(),
    /** ProcessPurpose */
    purpose: varchar('purpose', { length: 16 }).notNull(),
    /** Run that produced the process; with object_id it is the idempotency key of the import. */
    activeRunId: uuid('active_run_id')
      .notNull()
      .references(() => runs.id),
    batchRunId: varchar('batch_run_id', { length: 128 }).notNull(),
    /** LoadScenario */
    scenario: varchar('scenario', { length: 24 }),
    /** ScenarioBase */
    scenarioBase: varchar('scenario_base', { length: 24 }),
    uploadStatus: jsonb('upload_status'),
    inputManifestHash: char('input_manifest_hash', { length: 64 }),
    matrixVersion: text('matrix_version'),
    pipelineVersion: text('pipeline_version'),
    /** protocols.id of the current version (set by the import). */
    currentProtocolId: uuid('current_protocol_id'),
    assignedInspectorId: uuid('assigned_inspector_id'),
    verificationStartedAt: tstz('verification_started_at'),
    completedAt: tstz('completed_at'),
    finalizedAt: tstz('finalized_at'),
    rowVersion: integer('row_version').notNull().default(1),
    createdBy: uuid('created_by'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    unique('processes_run_object_uq').on(t.activeRunId, t.objectId),
    index('processes_object_idx').on(t.objectId, t.createdAt),
  ],
);

export const processFiles = pgTable(
  'process_files',
  {
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id, { onDelete: 'cascade' }),
    fileId: varchar('file_id', { length: 512 })
      .notNull()
      .references(() => files.id),
    included: boolean('included').notNull().default(true),
    addedAt: tstz('added_at').notNull().defaultNow(),
  },
  (t) => [primaryKey({ columns: [t.processId, t.fileId] })],
);

export const protocols = pgTable(
  'protocols',
  {
    /** UUID v7 */
    id: uuid('id').primaryKey(),
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id),
    objectId: varchar('object_id', { length: 64 }).notNull(),
    version: integer('version').notNull(),
    protocolNo: text('protocol_no').notNull(),
    /** ProtocolStatus */
    status: varchar('status', { length: 24 }).notNull(),
    isFinal: boolean('is_final').notNull(),
    /** ProtocolVersionReason: INITIAL, then RECHECK when a re-import brings other content. */
    versionReason: varchar('version_reason', { length: 24 }).notNull(),
    previousVersionId: uuid('previous_version_id'),
    runId: uuid('run_id').references(() => runs.id),
    matrixVersion: text('matrix_version'),
    datasetVersion: text('dataset_version'),
    modelVersion: text('model_version'),
    pipelineVersion: text('pipeline_version').notNull(),
    engineVersions: jsonb('engine_versions'),
    versions: jsonb('versions').notNull(),
    inputManifestHash: char('input_manifest_hash', { length: 64 }).notNull(),
    /** LoadScenario */
    scenario: varchar('scenario', { length: 24 }),
    scenarioBase: varchar('scenario_base', { length: 24 }),
    uploadStatus: jsonb('upload_status'),
    /** appendix2.section2_summary (counts and percentages) for dashboards. */
    summary: jsonb('summary'),
    /** The Protocol contract document (packages/contracts/schemas/protocol.schema.json), immutable. */
    contentJson: jsonb('content_json').notNull(),
    /** sha256 of the canonical JSON of content_json (inspector_common.hashing canonical form). */
    contentSha256: char('content_sha256', { length: 64 }).notNull(),
    /** Run-relative path and sha256 of the imported protocol/<object_id>.json. */
    sourcePath: text('source_path'),
    sourceSha256: char('source_sha256', { length: 64 }),
    generatedAt: tstz('generated_at').notNull(),
    finalizedAt: tstz('finalized_at'),
    finalizedBy: uuid('finalized_by'),
    supersededAt: tstz('superseded_at'),
    supersededReason: text('superseded_reason'),
    createdBy: uuid('created_by'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [unique('protocols_process_version_uq').on(t.processId, t.version)],
);

export const protocolExports = pgTable(
  'protocol_exports',
  {
    id: uuid('id').primaryKey(),
    protocolId: uuid('protocol_id')
      .notNull()
      .references(() => protocols.id, { onDelete: 'cascade' }),
    /** ExportFormat (json, docx, pdf) */
    format: varchar('format', { length: 16 }).notNull(),
    /** Absolute path of the run artifact (claim check); read-only. */
    storageKey: text('storage_key').notNull(),
    sha256: char('sha256', { length: 64 }).notNull(),
    sizeBytes: bigint('size_bytes', { mode: 'number' }).notNull(),
    generatedAt: tstz('generated_at').notNull().defaultNow(),
  },
  (t) => [unique('protocol_exports_protocol_format_uq').on(t.protocolId, t.format)],
);

export const evidenceGroups = pgTable(
  'evidence_groups',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id, { onDelete: 'cascade' }),
    /** = FindingGroup.finding_group_id (ТЗ §10 #2 key field evidence_group_id). */
    evidenceGroupId: varchar('evidence_group_id', { length: 96 }).notNull(),
    objectId: varchar('object_id', { length: 64 }).notNull(),
    /** MatrixScope */
    matrixScope: varchar('matrix_scope', { length: 16 }).notNull(),
    paramId: integer('param_id'),
    paramCode: varchar('param_code', { length: 32 }).notNull(),
    /** ParameterMappingStatus */
    parameterMappingStatus: varchar('parameter_mapping_status', { length: 40 }),
    altParamCodes: text('alt_param_codes').array().notNull().default(sql`'{}'::text[]`),
    /** HedgeKind */
    hedgeKind: varchar('hedge_kind', { length: 32 }),
    hedgeOfGroupId: varchar('hedge_of_group_id', { length: 96 }),
    title: text('title'),
    elementNoun: text('element_noun'),
    /** ComparisonAxis */
    axis: varchar('axis', { length: 8 }),
    /** ComparisonResult */
    comparisonResult: varchar('comparison_result', { length: 32 }).notNull(),
    /** DiscrepancyType */
    discrepancyType: varchar('discrepancy_type', { length: 32 }),
    /** LocationType */
    locationType: varchar('location_type', { length: 16 }).notNull(),
    locations: text('locations').array().notNull(),
    pdValue: jsonb('pd_value'),
    rdValue: jsonb('rd_value'),
    idValue: jsonb('id_value'),
    /** ViolationLabel */
    violationLabel: varchar('violation_label', { length: 24 }).notNull(),
    /** ProtocolParamStatus */
    protocolStatus: varchar('protocol_status', { length: 24 }).notNull(),
    criticality: text('criticality'),
    /** CriticalityLevel */
    criticalityLevel: varchar('criticality_level', { length: 24 }),
    /** FindingStatus */
    findingStatus: varchar('finding_status', { length: 24 }),
    /** RiskLevel */
    riskLevel: varchar('risk_level', { length: 8 }),
    confidence: confidence('confidence'),
    /** EvidenceRef[] — one anchor page per stage (97 §2.5). */
    anchorEvidence: jsonb('anchor_evidence').notNull(),
    /** {location: EvidenceRef[]} */
    locationPages: jsonb('location_pages'),
    findingIds: text('finding_ids').array().notNull(),
    /** DiscoveryMethod */
    discoveryMethod: varchar('discovery_method', { length: 32 }),
    /** EvidenceBindStatus */
    evidenceBindStatus: varchar('evidence_bind_status', { length: 16 }),
    ruleCode: text('rule_code'),
    ruleVersion: text('rule_version'),
    rationale: text('rationale'),
    recommendation: jsonb('recommendation'),
    cardNo: varchar('card_no', { length: 16 }),
    /** The FindingGroup record as imported, and the sha256 of its canonical JSON. */
    groupJson: jsonb('group_json').notNull(),
    groupSha256: char('group_sha256', { length: 64 }).notNull(),
    /** CheckLifecycle: SUPERSEDED when a re-import no longer contains the group. */
    lifecycleState: varchar('lifecycle_state', { length: 16 }).notNull().default('ACTIVE'),
    firstProtocolVersion: integer('first_protocol_version'),
    lastProtocolVersion: integer('last_protocol_version'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [unique('evidence_groups_process_group_uq').on(t.processId, t.evidenceGroupId)],
);

export const checks = pgTable(
  'checks',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id, { onDelete: 'cascade' }),
    // ТЗ §10 #2 key fields.
    paramId: integer('param_id'),
    objectId: varchar('object_id', { length: 64 }).notNull(),
    /** Stage value of the reference side (PD for PD_RD / PD_ID, RD for RD_ID), rendered text. */
    expectedValue: jsonb('expected_value'),
    /** Stage value of the checked side, rendered text. */
    actualValue: jsonb('actual_value'),
    /** CompletenessStatus */
    completenessStatus: varchar('completeness_status', { length: 32 }),
    /** FindingStatus */
    findingStatus: varchar('finding_status', { length: 24 }),
    /** ReviewPriority */
    reviewPriority: varchar('review_priority', { length: 8 }),
    /** = Finding.finding_group_id */
    evidenceGroupId: varchar('evidence_group_id', { length: 96 }),
    // Extensions (90 §3.3.3 #2, 97 §2.8).
    findingId: varchar('finding_id', { length: 96 }).notNull(),
    /** CheckKind: MATRIX, or SUSPICION_CONVERTED for FREE-* rows. */
    kind: varchar('kind', { length: 24 }).notNull(),
    /** MatrixScope */
    matrixScope: varchar('matrix_scope', { length: 16 }).notNull(),
    /** Catalog code (IOS4-078) or FREE-<TOPIC>-<NNN>. */
    paramCode: varchar('param_code', { length: 32 }).notNull(),
    subId: text('sub_id'),
    ruleCode: text('rule_code'),
    ruleVersion: text('rule_version'),
    /** ParameterMappingStatus */
    parameterMappingStatus: varchar('parameter_mapping_status', { length: 40 }),
    altParamCodes: text('alt_param_codes').array().notNull().default(sql`'{}'::text[]`),
    hedgeOfFindingId: varchar('hedge_of_finding_id', { length: 96 }),
    /** HedgeKind */
    hedgeKind: varchar('hedge_kind', { length: 32 }),
    location: text('location').notNull(),
    /** LocationType */
    locationType: varchar('location_type', { length: 16 }).notNull(),
    pdValue: jsonb('pd_value'),
    rdValue: jsonb('rd_value'),
    idValue: jsonb('id_value'),
    /** ComparisonAxis */
    axis: varchar('axis', { length: 8 }),
    /** ComparisonResult */
    comparisonResult: varchar('comparison_result', { length: 32 }),
    /** DiscrepancyType */
    discrepancyType: varchar('discrepancy_type', { length: 32 }),
    /** ViolationType */
    violationType: varchar('violation_type', { length: 32 }),
    /** CompletenessBasis */
    completenessBasis: varchar('completeness_basis', { length: 48 }),
    /** ViolationLabel */
    violationLabel: varchar('violation_label', { length: 24 }).notNull(),
    /** ProtocolParamStatus */
    protocolStatus: varchar('protocol_status', { length: 24 }).notNull(),
    criticality: text('criticality'),
    /** CriticalityLevel */
    criticalityLevel: varchar('criticality_level', { length: 24 }),
    /** RiskLevel */
    riskLevel: varchar('risk_level', { length: 8 }),
    /** DocumentStatus (up to 51 chars, e.g. PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK) */
    documentStatus: varchar('document_status', { length: 64 }),
    confidence: confidence('confidence'),
    elementNoun: text('element_noun'),
    /** DiscoveryMethod (FREE-* rows) */
    discoveryMethod: varchar('discovery_method', { length: 32 }),
    /** EvidenceBindStatus (FREE-* rows) */
    evidenceBindStatus: varchar('evidence_bind_status', { length: 16 }),
    recommendation: jsonb('recommendation'),
    cardNo: varchar('card_no', { length: 16 }),
    delta: jsonb('delta'),
    rationale: text('rationale'),
    decisionTrace: jsonb('decision_trace'),
    /** suspicions.id this check was converted from (FREE-* rows). */
    sourceSuspicionId: bigint('source_suspicion_id', { mode: 'number' }),
    /** The Finding record as imported, and the sha256 of its canonical JSON (change detection). */
    findingJson: jsonb('finding_json').notNull(),
    findingSha256: char('finding_sha256', { length: 64 }).notNull(),
    /** CheckLifecycle */
    lifecycleState: varchar('lifecycle_state', { length: 16 }).notNull().default('ACTIVE'),
    // Inspector columns (AG-05, verification). The import sets inspector_status only on insert.
    /** InspectorStatus (PENDING for new violation candidates; NULL for rows that need no decision). */
    inspectorStatus: varchar('inspector_status', { length: 32 }),
    /** DecidedBy */
    decidedBy: varchar('decided_by', { length: 16 }),
    decidedUserId: uuid('decided_user_id'),
    decidedAt: tstz('decided_at'),
    decisionReasonCode: varchar('decision_reason_code', { length: 48 }),
    decisionBasisCode: varchar('decision_basis_code', { length: 48 }),
    decisionComment: text('decision_comment'),
    currentDecisionId: uuid('current_decision_id'),
    /** ReviewRequiredReason: set by a re-import that changes a decided check. */
    reviewRequiredReason: varchar('review_required_reason', { length: 32 }),
    newEvidenceAvailable: boolean('new_evidence_available').notNull().default(false),
    firstProtocolVersion: integer('first_protocol_version'),
    lastProtocolVersion: integer('last_protocol_version'),
    runId: uuid('run_id').references(() => runs.id),
    rowVersion: integer('row_version').notNull().default(1),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    unique('checks_process_finding_uq').on(t.processId, t.findingId),
    index('checks_process_status_idx').on(t.processId, t.protocolStatus),
    index('checks_process_param_idx').on(t.processId, t.paramCode),
    index('checks_group_idx').on(t.processId, t.evidenceGroupId),
  ],
);

export const evidenceFragments = pgTable(
  'evidence_fragments',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id, { onDelete: 'cascade' }),
    /** sha256 of the canonical source reference: stable ids across idempotent re-imports. */
    fragmentKey: char('fragment_key', { length: 64 }).notNull(),
    // ТЗ §10 #14 key fields.
    evidenceGroupId: varchar('evidence_group_id', { length: 96 }),
    fileId: varchar('file_id', { length: 512 }).notNull(),
    /** DocStage */
    stage: varchar('stage', { length: 4 }).notNull(),
    /** Display «л. {sheet_no} / стр. {page_no}». */
    sheetPage: text('sheet_page').notNull(),
    /** Geometry {boxes, polygons} in PDF_VISIBLE_ROTATED_TL_V1 (normalized, top-left origin). */
    bboxPolygonNorm: jsonb('bbox_polygon_norm'),
    extractedValue: text('extracted_value'),
    /** EvidenceRole */
    roleExpectedActual: varchar('role_expected_actual', { length: 24 }),
    // Extensions.
    checkId: bigint('check_id', { mode: 'number' }).references(() => checks.id, { onDelete: 'set null' }),
    findingId: varchar('finding_id', { length: 96 }),
    suspicionId: bigint('suspicion_id', { mode: 'number' }),
    /** Location the fragment depicts (location_pages), or the finding's location. */
    location: text('location'),
    /** One anchor page per stage per group (97 §2.5). */
    isAnchor: boolean('is_anchor').notNull().default(false),
    fileSha256: char('file_sha256', { length: 64 }),
    pageNo: integer('page_no').notNull(),
    sheetNo: text('sheet_no'),
    /** PageBasis */
    pageBasis: varchar('page_basis', { length: 24 }),
    geometrySpace: varchar('geometry_space', { length: 32 }),
    /** EvidenceLocalization */
    localization: varchar('localization', { length: 16 }),
    documentCode: text('document_code'),
    revision: text('revision'),
    extractedValueId: text('extracted_value_id'),
    note: text('note'),
    /** FragmentOrigin: SYSTEM rows are owned by the import; INSPECTOR rows are never touched by it. */
    origin: varchar('origin', { length: 16 }).notNull().default('SYSTEM'),
    createdBy: uuid('created_by'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    unique('evidence_fragments_process_key_uq').on(t.processId, t.fragmentKey),
    index('evidence_fragments_check_idx').on(t.checkId),
    index('evidence_fragments_group_idx').on(t.processId, t.evidenceGroupId),
    index('evidence_fragments_page_idx').on(t.fileId, t.pageNo),
  ],
);

export const suspicions = pgTable(
  'suspicions',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    // ТЗ §10 #8 key fields.
    objectId: varchar('object_id', { length: 64 }).notNull(),
    /** DiscoveryMethod */
    discoveryMethod: varchar('discovery_method', { length: 32 }),
    confidence: confidence('confidence'),
    description: text('description').notNull(),
    /** SuspicionInspectorStatus */
    inspectorStatus: varchar('inspector_status', { length: 32 }).notNull(),
    // Extensions (90 §3.3.3 #8).
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id, { onDelete: 'cascade' }),
    runId: uuid('run_id').references(() => runs.id),
    /** Dedup key: the FREE-* finding_group_id. */
    suspicionKey: varchar('suspicion_key', { length: 128 }).notNull(),
    paramCode: varchar('param_code', { length: 32 }),
    /** Always SUSPICION (90 §3.2.4 axis A). */
    findingStatus: varchar('finding_status', { length: 16 }).notNull().default('SUSPICION'),
    /** EvidenceBindStatus */
    evidenceStatus: varchar('evidence_status', { length: 16 }),
    expectedValue: jsonb('expected_value'),
    actualValue: jsonb('actual_value'),
    pdReference: text('pd_reference'),
    rdReference: text('rd_reference'),
    idReference: text('id_reference'),
    /** ReviewPriority */
    reviewPriority: varchar('review_priority', { length: 8 }),
    relatedCheckIds: bigint('related_check_ids', { mode: 'number' }).array().notNull().default(sql`'{}'::bigint[]`),
    convertedCheckId: bigint('converted_check_id', { mode: 'number' }),
    /** PromotedBy */
    promotedBy: varchar('promoted_by', { length: 16 }),
    /** The FREE-* FindingGroup as imported. */
    explanation: jsonb('explanation'),
    isStale: boolean('is_stale').notNull().default(false),
    decidedBy: uuid('decided_by'),
    decidedAt: tstz('decided_at'),
    reasonCode: varchar('reason_code', { length: 48 }),
    inspectorComment: text('inspector_comment'),
    rowVersion: integer('row_version').notNull().default(1),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [unique('suspicions_process_key_uq').on(t.processId, t.suspicionKey)],
);

export const submissionExports = pgTable(
  'submission_exports',
  {
    id: uuid('id').primaryKey(),
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id, { onDelete: 'cascade' }),
    runId: uuid('run_id')
      .notNull()
      .references(() => runs.id),
    objectId: varchar('object_id', { length: 64 }).notNull(),
    /** SubmissionVariant (full | strict) */
    variant: varchar('variant', { length: 8 }).notNull(),
    /** Run-relative path of the imported file. */
    path: text('path').notNull(),
    sha256: char('sha256', { length: 64 }).notNull(),
    sizeBytes: bigint('size_bytes', { mode: 'number' }).notNull(),
    rowsCount: integer('rows_count').notNull(),
    content: jsonb('content').notNull(),
    /** submission/<object_id>.sidecar.json (full variant only). */
    sidecar: jsonb('sidecar'),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [unique('submission_exports_process_variant_uq').on(t.processId, t.variant)],
);

export const runArtifacts = pgTable(
  'run_artifacts',
  {
    runId: uuid('run_id')
      .notNull()
      .references(() => runs.id, { onDelete: 'cascade' }),
    /** Run-relative POSIX path (artifacts.json). */
    path: text('path').notNull(),
    /** ArtifactKind */
    kind: varchar('kind', { length: 32 }).notNull(),
    /** ArtifactFormat */
    format: varchar('format', { length: 8 }).notNull(),
    schemaName: text('schema_name'),
    objectId: varchar('object_id', { length: 64 }),
    fileId: varchar('file_id', { length: 512 }),
    sha256: char('sha256', { length: 64 }).notNull(),
    sizeBytes: bigint('size_bytes', { mode: 'number' }).notNull(),
    records: integer('records'),
    producer: jsonb('producer'),
    modifiedAt: tstz('modified_at'),
    importedAt: tstz('imported_at').notNull().defaultNow(),
  },
  (t) => [
    primaryKey({ columns: [t.runId, t.path] }),
    index('run_artifacts_kind_idx').on(t.runId, t.kind),
    index('run_artifacts_file_idx').on(t.fileId, t.kind),
  ],
);

export type ProcessRow = typeof processes.$inferSelect;
export type ProtocolRow = typeof protocols.$inferSelect;
export type CheckRow = typeof checks.$inferSelect;
export type NewCheckRow = typeof checks.$inferInsert;
export type EvidenceGroupRow = typeof evidenceGroups.$inferSelect;
export type EvidenceFragmentRow = typeof evidenceFragments.$inferSelect;
export type SuspicionRow = typeof suspicions.$inferSelect;
