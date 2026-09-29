/**
 * Verification tables (owner AG-05; 05 §3.14, 90 §3.3.3–3.3.4, ТЗ §10 #6, #7, #15).
 *
 * | table                    | ТЗ / 90 name            | written when                                             |
 * |--------------------------|-------------------------|----------------------------------------------------------|
 * | verification_decisions   | decisions (05 §3.14)    | every inspector action on one atomic finding (append-only)|
 * | rejection_log            | Rejection_Log (ТЗ #6)   | every «Отклонить» (with the AI verdict)                  |
 * | dispute_log              | Dispute_Log (ТЗ #7)     | the AI disagrees with a rejection (§9.4 sample 2)        |
 * | dataset_items            | Dataset_Items (ТЗ #15)  | finalization: one GOLD draft per final decision          |
 * | verification_idempotency | —                       | every write with an Idempotency-Key (replay store)       |
 * | ui_events                | ui_events (05 §3.14)    | usability telemetry (VER-68)                             |
 *
 * Inspector decisions live only here and in the inspector columns of `checks`; they never reach a submission
 * (97 §1.4) — no code path of this module writes run directories or `submission_exports`.
 * Enum-valued columns hold codes of packages/contracts/enums.yaml (noted per column).
 * Migration: ./sql/0004_verification.sql (tables, CHECK constraints, append-only and finalization triggers).
 */
import { sql } from 'drizzle-orm';
import {
  bigint,
  bigserial,
  boolean,
  char,
  index,
  inet,
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
import { checks, processes, protocols } from '../import/import.schema';

const tstz = (name: string) => timestamp(name, { withTimezone: true, mode: 'date' });
const confidence = (name: string) => numeric(name, { precision: 4, scale: 3, mode: 'number' });

export const verificationDecisions = pgTable(
  'verification_decisions',
  {
    /** decision_id, UUID v7 (Decision contract). */
    id: uuid('id').primaryKey(),
    processId: uuid('process_id')
      .notNull()
      .references(() => processes.id),
    checkId: bigint('check_id', { mode: 'number' })
      .notNull()
      .references(() => checks.id),
    findingId: varchar('finding_id', { length: 96 }).notNull(),
    findingGroupId: varchar('finding_group_id', { length: 96 }),
    objectId: varchar('object_id', { length: 64 }).notNull(),
    runId: uuid('run_id'),
    /** Current protocol version when the decision was taken (decisions never create versions, 90 §3.2.3). */
    protocolId: uuid('protocol_id'),
    protocolVersion: integer('protocol_version'),
    /** DecisionType */
    decision: varchar('decision', { length: 32 }).notNull(),
    /** InspectorStatus of the finding after this decision (differs from `decision` when the AI disagrees). */
    effectiveStatus: varchar('effective_status', { length: 32 }).notNull(),
    /** DecisionRejectReason */
    reasonCode: varchar('reason_code', { length: 48 }),
    /** DecisionConfirmBasis */
    basisCode: varchar('basis_code', { length: 48 }),
    /** DecisionClarifyBasis */
    clarifyCode: varchar('clarify_code', { length: 48 }),
    comment: text('comment').notNull(),
    /** CommentSource */
    commentSource: varchar('comment_source', { length: 16 }).notNull(),
    /** ТЗ §9.4 system comment (samples 1 and 2). */
    systemComment: text('system_comment'),
    approvedChangeRef: text('approved_change_ref'),
    approvedChangeFileId: varchar('approved_change_file_id', { length: 512 }),
    approvedChangePage: integer('approved_change_page'),
    correctedValue: jsonb('corrected_value'),
    correctFileId: varchar('correct_file_id', { length: 512 }),
    correctLocus: text('correct_locus'),
    duplicateOf: varchar('duplicate_of', { length: 96 }),
    naBasis: text('na_basis'),
    justification: text('justification'),
    /** PlannedAction (informational, VER-42) */
    plannedAction: varchar('planned_action', { length: 32 }),
    /** AiVerdict of the rejection validator (05 §3.7). */
    aiVerdict: varchar('ai_verdict', { length: 16 }),
    aiConfidence: confidence('ai_confidence'),
    aiRuleIds: text('ai_rule_ids').array().notNull().default(sql`'{}'::text[]`),
    aiComment: text('ai_comment'),
    /** GoldEffect */
    goldEffect: varchar('gold_effect', { length: 16 }).notNull(),
    /** Fingerprint of the evidence the inspector saw (VER-58, invariant I9). */
    seenFingerprint: char('seen_fingerprint', { length: 64 }).notNull(),
    /** Sources shown on the card: file_id, sha256, stage, шифр, редакция, page, geometry. */
    evidenceSnapshot: jsonb('evidence_snapshot').notNull(),
    /** The decision this one replaces as the finding's current decision. */
    supersedesDecisionId: uuid('supersedes_decision_id'),
    /** «Заменить своим решением» after a VERSION_CONFLICT (audited as DECISION_OVERRIDE). */
    overrideOfDecisionId: uuid('override_of_decision_id'),
    /** dispute_log.id resolved by this decision. */
    resolvesDisputeId: bigint('resolves_dispute_id', { mode: 'number' }),
    userId: uuid('user_id').notNull(),
    /** Role codes of the decider, comma-separated (Role). */
    userRole: varchar('user_role', { length: 128 }).notNull(),
    userLogin: varchar('user_login', { length: 64 }),
    ipAddress: inet('ip_address'),
    userAgent: text('user_agent'),
    requestId: varchar('request_id', { length: 128 }),
    idempotencyKey: uuid('idempotency_key').notNull(),
    /** Usability metrics of the card (time_on_card_ms, clicks, keys, input); never used for the decision. */
    clientMetrics: jsonb('client_metrics'),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [
    unique('verification_decisions_user_key_uq').on(t.userId, t.idempotencyKey),
    index('verification_decisions_check_idx').on(t.checkId, t.createdAt),
    index('verification_decisions_process_idx').on(t.processId, t.createdAt),
  ],
);

export const rejectionLog = pgTable(
  'rejection_log',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    /** ТЗ §10 #6 name; = checks.id of the rejected candidate (05 §6 C11). */
    violationId: bigint('violation_id', { mode: 'number' })
      .notNull()
      .references(() => checks.id),
    decisionId: uuid('decision_id')
      .notNull()
      .references(() => verificationDecisions.id),
    processId: uuid('process_id').notNull(),
    objectId: varchar('object_id', { length: 64 }).notNull(),
    findingId: varchar('finding_id', { length: 96 }).notNull(),
    paramCode: varchar('param_code', { length: 32 }).notNull(),
    /** DecisionRejectReason */
    rejectionReason: varchar('rejection_reason', { length: 48 }).notNull(),
    reasonComment: text('reason_comment').notNull(),
    correctedValue: jsonb('corrected_value'),
    /** AiVerdict */
    aiVerdict: varchar('ai_verdict', { length: 16 }).notNull(),
    aiConfidence: confidence('ai_confidence'),
    aiRuleIds: text('ai_rule_ids').array().notNull().default(sql`'{}'::text[]`),
    aiComment: text('ai_comment'),
    suggestedFix: text('suggested_fix'),
    /** RetrainingStatus: IN_DRAFT (AGREE/UNCERTAIN) or DISPUTED (DISAGREE). */
    retrainingStatus: varchar('retraining_status', { length: 24 }).notNull(),
    /** UNCERTAIN verdicts and upheld disputes go to the curator first. */
    curatorFlag: boolean('curator_flag').notNull().default(false),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [index('rejection_log_process_idx').on(t.processId, t.createdAt), index('rejection_log_reason_idx').on(t.rejectionReason)],
);

export const disputeLog = pgTable(
  'dispute_log',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    /** ТЗ §10 #7 name; = checks.id. */
    violationId: bigint('violation_id', { mode: 'number' })
      .notNull()
      .references(() => checks.id),
    /** The rejection the AI disagreed with. */
    decisionId: uuid('decision_id')
      .notNull()
      .references(() => verificationDecisions.id),
    processId: uuid('process_id').notNull(),
    findingId: varchar('finding_id', { length: 96 }).notNull(),
    rejectionReason: varchar('rejection_reason', { length: 48 }).notNull(),
    inspectorComment: text('inspector_comment').notNull(),
    /** ТЗ §9.4 sample 2 + «Основание: …» (the validator's argument). */
    aiComment: text('ai_comment').notNull(),
    aiRuleIds: text('ai_rule_ids').array().notNull(),
    aiEvidence: jsonb('ai_evidence'),
    /** DisputeResolutionStatus */
    resolutionStatus: varchar('resolution_status', { length: 24 }).notNull().default('OPEN'),
    resolvedBy: uuid('resolved_by'),
    resolutionComment: text('resolution_comment'),
    resolutionDecisionId: uuid('resolution_decision_id'),
    rowVersion: integer('row_version').notNull().default(1),
    createdAt: tstz('created_at').notNull().defaultNow(),
    resolvedAt: tstz('resolved_at'),
  },
  (t) => [index('dispute_log_process_idx').on(t.processId, t.resolutionStatus), index('dispute_log_violation_idx').on(t.violationId)],
);

export const datasetItems = pgTable(
  'dataset_items',
  {
    id: uuid('id').primaryKey(),
    // ТЗ §10 #15 key fields.
    evidenceGroupId: varchar('evidence_group_id', { length: 96 }),
    /** GoldLabel: POSITIVE (CONFIRMED_VIOLATION) or NEGATIVE (inspector NEGATIVE_VERIFIED). */
    goldLabel: varchar('gold_label', { length: 16 }).notNull(),
    /** The inspector who decided (users.id). */
    expertId: uuid('expert_id').notNull(),
    /** DecisionConfirmBasis (POSITIVE) or DecisionRejectReason (NEGATIVE): the GOLD expert_reason_code. */
    reasonCode: varchar('reason_code', { length: 48 }),
    /** Dataset version the item was released in; NULL while it is a draft of the next version. */
    datasetVersion: text('dataset_version'),
    /** Split: by object (ТЗ §9.4 «разбиение по объектам»); TEST_HIDDEN objects are HIDDEN_TEST. */
    split: varchar('split', { length: 16 }).notNull(),
    objectGroupId: varchar('object_group_id', { length: 64 }),
    // Extensions.
    /** DatasetItemStatus: DRAFT at finalization, SUSPENDED after un-finalization. */
    status: varchar('status', { length: 24 }).notNull(),
    objectId: varchar('object_id', { length: 64 }).notNull(),
    processId: uuid('process_id').notNull(),
    /** The FINAL protocol version the draft was captured from. */
    protocolId: uuid('protocol_id')
      .notNull()
      .references(() => protocols.id),
    protocolVersion: integer('protocol_version').notNull(),
    checkId: bigint('check_id', { mode: 'number' }).notNull(),
    findingId: varchar('finding_id', { length: 96 }).notNull(),
    decisionId: uuid('decision_id')
      .notNull()
      .references(() => verificationDecisions.id),
    /** SourceType */
    sourceType: varchar('source_type', { length: 16 }).notNull(),
    /** The label in the organizers' gold format (gold_check.schema.json, v1.0 aliases CONFIRMED/REJECTED). */
    goldRecord: jsonb('gold_record').notNull(),
    /** Full evidence card at finalization (ТЗ §9.4: only items with complete cards enter a release). */
    evidenceCard: jsonb('evidence_card').notNull(),
    /** matrix/model/dataset/pipeline versions and input_manifest_hash of the protocol (ТЗ §14.1 «версии источников»). */
    versions: jsonb('versions').notNull(),
    /** Excluded from training by construction (hidden test split, never trained on). */
    trainingEligible: boolean('training_eligible').notNull(),
    decidedAt: tstz('decided_at').notNull(),
    createdAt: tstz('created_at').notNull().defaultNow(),
    updatedAt: tstz('updated_at').notNull().defaultNow(),
  },
  (t) => [
    unique('dataset_items_protocol_finding_uq').on(t.protocolId, t.findingId),
    index('dataset_items_status_idx').on(t.status, t.split),
    index('dataset_items_object_idx').on(t.objectId, t.createdAt),
  ],
);

export const verificationIdempotency = pgTable(
  'verification_idempotency',
  {
    userId: uuid('user_id').notNull(),
    idempotencyKey: uuid('idempotency_key').notNull(),
    /** OpenAPI operationId of the first request. */
    operation: varchar('operation', { length: 64 }).notNull(),
    /** sha256 of the canonical request (path, If-Match, body): same key + other body → IDEMPOTENCY_KEY_REUSED. */
    requestSha256: char('request_sha256', { length: 64 }).notNull(),
    statusCode: integer('status_code').notNull(),
    responseBody: jsonb('response_body').notNull(),
    etag: varchar('etag', { length: 32 }),
    createdAt: tstz('created_at').notNull().defaultNow(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.idempotencyKey] })],
);

export const uiEvents = pgTable(
  'ui_events',
  {
    id: bigserial('id', { mode: 'number' }).primaryKey(),
    /** Browser session of the workspace (pseudonymous, VER-73). */
    sessionId: uuid('session_id'),
    userId: uuid('user_id').notNull(),
    processId: uuid('process_id'),
    findingId: varchar('finding_id', { length: 96 }),
    /** UiEventType (proposed) */
    type: varchar('type', { length: 32 }).notNull(),
    target: varchar('target', { length: 64 }),
    /** UiInputMode (proposed): MOUSE, KEYBOARD. */
    input: varchar('input', { length: 16 }),
    tsClient: tstz('ts_client').notNull(),
    tsServer: tstz('ts_server').notNull().defaultNow(),
    payload: jsonb('payload'),
  },
  (t) => [index('ui_events_process_idx').on(t.processId, t.tsClient), index('ui_events_session_idx').on(t.sessionId, t.tsClient)],
);

export type DecisionRow = typeof verificationDecisions.$inferSelect;
export type NewDecisionRow = typeof verificationDecisions.$inferInsert;
export type RejectionRow = typeof rejectionLog.$inferSelect;
export type NewRejectionRow = typeof rejectionLog.$inferInsert;
export type DisputeRow = typeof disputeLog.$inferSelect;
export type NewDisputeRow = typeof disputeLog.$inferInsert;
export type DatasetItemRow = typeof datasetItems.$inferSelect;
export type NewDatasetItemRow = typeof datasetItems.$inferInsert;
export type IdempotencyRow = typeof verificationIdempotency.$inferSelect;
export type UiEventRow = typeof uiEvents.$inferSelect;
export type NewUiEventRow = typeof uiEvents.$inferInsert;
