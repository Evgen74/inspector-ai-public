/**
 * In-memory VerificationRepository for DB-free tests and demos. Transactions are serialized (one at a time,
 * like the process-row lock) and roll back on any error (a structured clone of the state is restored).
 *
 * `seedFromArtifacts` fills it the way AG-00's batch-run import does (same planners: planGroup, planCheck,
 * planSuspicions), so tests run on exactly the rows the product imports from `inspector-batch` runs.
 */
import { createHash } from 'node:crypto';
import type { FileRow } from '../../db/schema';
import type { CheckRow, EvidenceGroupRow, ProcessRow, ProtocolRow, SuspicionRow } from '../import/import.schema';
import {
  type FindingDoc,
  type FindingGroupDoc,
  planCheck,
  planGroup,
  planSuspicions,
  type ProtocolDoc,
  sha256OfJson,
} from '../import/import-plan';
import { uuidv7 } from '../../common/ids';
import {
  type CheckPatch,
  type DatasetItemFilter,
  type NewIdempotency,
  type NewProtocolRow,
  type ObjectInfo,
  type ProcessPatch,
  VerificationRepository,
  type VerificationTx,
} from './verification.repository';
import type {
  DatasetItemRow,
  DecisionRow,
  DisputeRow,
  IdempotencyRow,
  NewDatasetItemRow,
  NewDecisionRow,
  NewDisputeRow,
  NewRejectionRow,
  NewUiEventRow,
  RejectionRow,
  UiEventRow,
} from './verification.schema';

export interface MemoryState {
  processes: ProcessRow[];
  objects: ObjectInfo[];
  checks: CheckRow[];
  groups: EvidenceGroupRow[];
  suspicions: SuspicionRow[];
  protocols: ProtocolRow[];
  files: FileRow[];
  decisions: DecisionRow[];
  rejections: RejectionRow[];
  disputes: DisputeRow[];
  datasetItems: DatasetItemRow[];
  idempotency: IdempotencyRow[];
  uiEvents: UiEventRow[];
}

function emptyState(): MemoryState {
  return {
    processes: [],
    objects: [],
    checks: [],
    groups: [],
    suspicions: [],
    protocols: [],
    files: [],
    decisions: [],
    rejections: [],
    disputes: [],
    datasetItems: [],
    idempotency: [],
    uiEvents: [],
  };
}

const byTime = <T extends { createdAt: Date }>(a: T, b: T) => a.createdAt.getTime() - b.createdAt.getTime();

class MemoryTx implements VerificationTx {
  readonly auditExecutor = undefined;

  constructor(private readonly repo: InMemoryVerificationRepository) {}

  private get s(): MemoryState {
    return this.repo.state;
  }

  async lockProcess(id: string, _mode: 'no key update' | 'update'): Promise<ProcessRow | null> {
    return structuredClone(this.s.processes.find((p) => p.id === id) ?? null);
  }

  async lockCheck(processId: string, findingId: string): Promise<CheckRow | null> {
    return structuredClone(this.s.checks.find((c) => c.processId === processId && c.findingId === findingId) ?? null);
  }

  async checksOf(processId: string): Promise<CheckRow[]> {
    return structuredClone(this.s.checks.filter((c) => c.processId === processId));
  }

  async updateCheck(id: number, expectedRowVersion: number, patch: CheckPatch): Promise<CheckRow | null> {
    const row = this.s.checks.find((c) => c.id === id);
    if (!row || row.rowVersion !== expectedRowVersion) return null;
    Object.assign(row, patch, { rowVersion: row.rowVersion + 1, updatedAt: new Date() });
    return structuredClone(row);
  }

  async updateProcess(id: string, patch: ProcessPatch): Promise<ProcessRow> {
    const row = this.s.processes.find((p) => p.id === id);
    if (!row) throw new Error(`process ${id} vanished inside its own transaction`);
    Object.assign(row, patch, { rowVersion: row.rowVersion + 1, updatedAt: new Date() });
    return structuredClone(row);
  }

  async getProtocol(id: string): Promise<ProtocolRow | null> {
    return structuredClone(this.s.protocols.find((p) => p.id === id) ?? null);
  }

  async maxProtocolVersion(processId: string): Promise<number> {
    return Math.max(0, ...this.s.protocols.filter((p) => p.processId === processId).map((p) => p.version));
  }

  async insertProtocol(row: NewProtocolRow): Promise<ProtocolRow> {
    if (this.s.protocols.some((p) => p.processId === row.processId && p.version === row.version)) {
      throw Object.assign(new Error('duplicate protocol version'), { code: '23505' });
    }
    const full = protocolRow(row);
    this.s.protocols.push(full);
    return structuredClone(full);
  }

  async updateProtocol(id: string, patch: { status?: string; supersededAt?: Date | null; supersededReason?: string | null }): Promise<void> {
    const row = this.s.protocols.find((p) => p.id === id);
    if (!row) return;
    // Same guard as the DB trigger (migration 0003): a finalized version may only be superseded.
    if (row.status === 'PROTOCOL_FINALIZED' && patch.status && !['PROTOCOL_FINALIZED', 'SUPERSEDED'].includes(patch.status)) {
      throw new Error(`PROTOCOL_FINALIZED: finalized protocol version ${id} can only be superseded`);
    }
    Object.assign(row, patch);
  }

  async insertDecision(row: NewDecisionRow): Promise<DecisionRow> {
    if (this.s.decisions.some((d) => d.userId === row.userId && d.idempotencyKey === row.idempotencyKey)) {
      throw Object.assign(new Error('duplicate idempotency key'), { code: '23505' });
    }
    const full = decisionRow(row);
    this.s.decisions.push(full);
    return structuredClone(full);
  }

  async decisionsOf(processId: string): Promise<DecisionRow[]> {
    return structuredClone(this.s.decisions.filter((d) => d.processId === processId).sort(byTime));
  }

  async insertRejection(row: NewRejectionRow): Promise<RejectionRow> {
    const full: RejectionRow = {
      id: this.s.rejections.length + 1,
      correctedValue: null,
      aiConfidence: null,
      aiRuleIds: [],
      aiComment: null,
      suggestedFix: null,
      curatorFlag: false,
      createdAt: new Date(),
      ...row,
    } as RejectionRow;
    this.s.rejections.push(full);
    return structuredClone(full);
  }

  async openDisputesOf(processId: string): Promise<DisputeRow[]> {
    return structuredClone(this.s.disputes.filter((d) => d.processId === processId && d.resolutionStatus === 'OPEN'));
  }

  async lockDispute(id: number): Promise<DisputeRow | null> {
    return structuredClone(this.s.disputes.find((d) => d.id === id) ?? null);
  }

  async insertDispute(row: NewDisputeRow): Promise<DisputeRow> {
    const full: DisputeRow = {
      id: this.s.disputes.length + 1,
      aiEvidence: null,
      resolutionStatus: 'OPEN',
      resolvedBy: null,
      resolutionComment: null,
      resolutionDecisionId: null,
      rowVersion: 1,
      createdAt: new Date(),
      resolvedAt: null,
      ...row,
    } as DisputeRow;
    this.s.disputes.push(full);
    return structuredClone(full);
  }

  async resolveDispute(
    id: number,
    patch: { resolutionStatus: string; resolvedBy: string; resolutionComment: string; resolutionDecisionId: string; resolvedAt: Date },
  ): Promise<DisputeRow> {
    const row = this.s.disputes.find((d) => d.id === id)!;
    Object.assign(row, patch, { rowVersion: row.rowVersion + 1 });
    return structuredClone(row);
  }

  async insertDatasetItems(rows: NewDatasetItemRow[]): Promise<void> {
    for (const r of rows) {
      if (this.s.datasetItems.some((d) => d.protocolId === r.protocolId && d.findingId === r.findingId)) {
        throw Object.assign(new Error('duplicate dataset item'), { code: '23505' });
      }
      this.s.datasetItems.push({
        evidenceGroupId: null,
        reasonCode: null,
        datasetVersion: null,
        objectGroupId: null,
        createdAt: new Date(),
        updatedAt: new Date(),
        ...r,
      } as DatasetItemRow);
    }
  }

  async setDatasetItemsStatus(protocolId: string, status: string): Promise<number> {
    const rows = this.s.datasetItems.filter((d) => d.protocolId === protocolId);
    for (const r of rows) Object.assign(r, { status, updatedAt: new Date() });
    return rows.length;
  }

  async getIdempotency(userId: string, key: string): Promise<IdempotencyRow | null> {
    return this.repo.getIdempotency(userId, key);
  }

  async putIdempotency(row: NewIdempotency): Promise<boolean> {
    if (this.s.idempotency.some((r) => r.userId === row.userId && r.idempotencyKey === row.idempotencyKey)) return false;
    this.s.idempotency.push({ ...row, responseBody: structuredClone(row.responseBody), createdAt: new Date() });
    return true;
  }
}

function decisionRow(row: NewDecisionRow): DecisionRow {
  return {
    findingGroupId: null,
    runId: null,
    protocolId: null,
    protocolVersion: null,
    reasonCode: null,
    basisCode: null,
    clarifyCode: null,
    systemComment: null,
    approvedChangeRef: null,
    approvedChangeFileId: null,
    approvedChangePage: null,
    correctedValue: null,
    correctFileId: null,
    correctLocus: null,
    duplicateOf: null,
    naBasis: null,
    justification: null,
    plannedAction: null,
    aiVerdict: null,
    aiConfidence: null,
    aiRuleIds: [],
    aiComment: null,
    supersedesDecisionId: null,
    overrideOfDecisionId: null,
    resolvesDisputeId: null,
    userLogin: null,
    ipAddress: null,
    userAgent: null,
    requestId: null,
    clientMetrics: null,
    createdAt: new Date(),
    ...row,
  } as DecisionRow;
}

function protocolRow(row: NewProtocolRow): ProtocolRow {
  return {
    previousVersionId: null,
    runId: null,
    matrixVersion: null,
    datasetVersion: null,
    modelVersion: null,
    engineVersions: null,
    scenario: null,
    scenarioBase: null,
    uploadStatus: null,
    summary: null,
    sourcePath: null,
    sourceSha256: null,
    finalizedAt: null,
    finalizedBy: null,
    supersededAt: null,
    supersededReason: null,
    createdBy: null,
    createdAt: new Date(),
    ...row,
  } as ProtocolRow;
}

export class InMemoryVerificationRepository extends VerificationRepository {
  state: MemoryState = emptyState();
  private queue: Promise<void> = Promise.resolve();
  /** Test hook: throw inside the next transaction after `fn` ran (rollback check). */
  failNextCommit: Error | null = null;

  reset(): void {
    this.state = emptyState();
    this.failNextCommit = null;
  }

  transaction<T>(fn: (tx: VerificationTx) => Promise<T>): Promise<T> {
    const run = this.queue.then(async () => {
      const snapshot = structuredClone(this.state);
      try {
        const out = await fn(new MemoryTx(this));
        if (this.failNextCommit) {
          const err = this.failNextCommit;
          this.failNextCommit = null;
          throw err;
        }
        return out;
      } catch (err) {
        this.state = snapshot;
        throw err;
      }
    });
    this.queue = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }

  async getProcess(id: string): Promise<ProcessRow | null> {
    return structuredClone(this.state.processes.find((p) => p.id === id) ?? null);
  }

  async processesOfObject(objectId: string): Promise<ProcessRow[]> {
    return structuredClone(this.state.processes.filter((p) => p.objectId === objectId).sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime()));
  }

  async getObject(id: string): Promise<ObjectInfo | null> {
    return structuredClone(this.state.objects.find((o) => o.id === id) ?? null);
  }

  async checksOf(processId: string): Promise<CheckRow[]> {
    return structuredClone(this.state.checks.filter((c) => c.processId === processId));
  }

  async groupsOf(processId: string): Promise<EvidenceGroupRow[]> {
    return structuredClone(this.state.groups.filter((g) => g.processId === processId));
  }

  async suspicionsOf(processId: string): Promise<SuspicionRow[]> {
    return structuredClone(this.state.suspicions.filter((s) => s.processId === processId));
  }

  async protocolsOf(processId: string): Promise<ProtocolRow[]> {
    return structuredClone(this.state.protocols.filter((p) => p.processId === processId).sort((a, b) => a.version - b.version));
  }

  async getProtocol(id: string): Promise<ProtocolRow | null> {
    return structuredClone(this.state.protocols.find((p) => p.id === id) ?? null);
  }

  async files(ids: string[]): Promise<FileRow[]> {
    const want = new Set(ids);
    return structuredClone(this.state.files.filter((f) => want.has(f.id)));
  }

  async decisionsOf(processId: string, findingId?: string): Promise<DecisionRow[]> {
    return structuredClone(
      this.state.decisions.filter((d) => d.processId === processId && (!findingId || d.findingId === findingId)).sort(byTime),
    );
  }

  async disputesOf(processId: string): Promise<DisputeRow[]> {
    return structuredClone(this.state.disputes.filter((d) => d.processId === processId));
  }

  async getDispute(id: number): Promise<DisputeRow | null> {
    return structuredClone(this.state.disputes.find((d) => d.id === id) ?? null);
  }

  async rejectionsOf(processId: string): Promise<RejectionRow[]> {
    return structuredClone(this.state.rejections.filter((r) => r.processId === processId));
  }

  async datasetItems(filter: DatasetItemFilter): Promise<DatasetItemRow[]> {
    return structuredClone(
      this.state.datasetItems.filter(
        (d) =>
          (!filter.processId || d.processId === filter.processId) &&
          (!filter.objectId || d.objectId === filter.objectId) &&
          (!filter.status || d.status === filter.status),
      ),
    );
  }

  async getIdempotency(userId: string, key: string): Promise<IdempotencyRow | null> {
    return structuredClone(this.state.idempotency.find((r) => r.userId === userId && r.idempotencyKey === key) ?? null);
  }

  async insertUiEvents(rows: NewUiEventRow[]): Promise<number> {
    for (const r of rows) {
      this.state.uiEvents.push({
        id: this.state.uiEvents.length + 1,
        sessionId: null,
        processId: null,
        findingId: null,
        target: null,
        input: null,
        payload: null,
        tsServer: new Date(),
        ...r,
      } as UiEventRow);
    }
    return rows.length;
  }

  async uiEventsOf(processId: string): Promise<UiEventRow[]> {
    return structuredClone(this.state.uiEvents.filter((e) => e.processId === processId));
  }
}

export interface SeedFile {
  file_id: string;
  file_name?: string;
  sha256?: string;
  stage?: string | null;
  manifest_stage?: string;
  document_code?: string | null;
  revision?: string | null;
  approval_status?: string | null;
  pdf_pages?: number | null;
}

export interface SeedInput {
  objectId: string;
  objectName?: string;
  /** ManifestSplit of the object. */
  split?: string;
  runId?: string;
  batchRunId?: string;
  protocol: ProtocolDoc;
  groups: FindingGroupDoc[];
  findings: FindingDoc[];
  files?: SeedFile[];
  createdAt?: Date;
}

/**
 * Seeds one imported process the way `DrizzleRunImportRepository.saveObject` writes it: process READY, protocol
 * version 1 (status of the document), evidence groups, one check per atomic finding (inspector_status from the
 * finding, else PENDING for VIOLATION_PRESENT) and FREE_SEARCH suspicions. Returns the process id.
 */
export function seedFromArtifacts(repo: InMemoryVerificationRepository, input: SeedInput): string {
  const now = input.createdAt ?? new Date();
  const processId = uuidv7(now.getTime());
  const protocolId = uuidv7(now.getTime());
  const runId = input.runId ?? uuidv7(now.getTime());
  const s = repo.state;
  if (!s.objects.some((o) => o.id === input.objectId)) {
    s.objects.push({ id: input.objectId, name: input.objectName ?? input.objectId, address: null, split: input.split ?? 'TRAIN_PUBLIC', objectGroupId: null });
  }
  const p = input.protocol;
  s.processes.push({
    id: processId,
    objectId: input.objectId,
    status: 'READY',
    stage: 'DONE',
    source: 'BATCH_IMPORT',
    purpose: 'INSPECTION',
    activeRunId: runId,
    batchRunId: input.batchRunId ?? 'run-seed',
    scenario: p.scenario ?? null,
    scenarioBase: p.scenario_base ?? null,
    uploadStatus: p.upload_status ?? null,
    inputManifestHash: p.input_manifest_hash,
    matrixVersion: p.versions.matrix_version ?? null,
    pipelineVersion: p.versions.pipeline_version,
    currentProtocolId: protocolId,
    assignedInspectorId: null,
    verificationStartedAt: null,
    completedAt: null,
    finalizedAt: null,
    rowVersion: 1,
    createdBy: null,
    createdAt: now,
    updatedAt: now,
  });
  const content = structuredClone(p) as unknown as Record<string, unknown>;
  s.protocols.push(
    protocolRow({
      id: protocolId,
      processId,
      objectId: input.objectId,
      version: p.version,
      protocolNo: p.protocol_no,
      status: p.status,
      isFinal: p.is_final,
      versionReason: 'INITIAL',
      runId,
      matrixVersion: p.versions.matrix_version ?? null,
      datasetVersion: p.versions.dataset_version ?? null,
      modelVersion: p.versions.model_version ?? null,
      pipelineVersion: p.versions.pipeline_version,
      engineVersions: p.versions.engine_versions ?? null,
      versions: p.versions,
      inputManifestHash: p.input_manifest_hash,
      scenario: p.scenario,
      scenarioBase: p.scenario_base ?? null,
      uploadStatus: p.upload_status ?? null,
      contentJson: content,
      contentSha256: sha256OfJson(content),
      generatedAt: new Date(p.generated_at),
      createdAt: now,
    }),
  );
  for (const g of input.groups) {
    const plan = planGroup(g);
    s.groups.push({
      id: s.groups.length + 1,
      processId,
      evidenceGroupId: plan.evidenceGroupId,
      ...(plan.row as object),
      groupSha256: plan.groupSha256,
      lifecycleState: 'ACTIVE',
      firstProtocolVersion: p.version,
      lastProtocolVersion: p.version,
      createdAt: now,
      updatedAt: now,
    } as EvidenceGroupRow);
  }
  const suspicionIds = new Map<string, number>();
  for (const sp of planSuspicions(input.groups, input.findings, p)) {
    const id = s.suspicions.length + 1;
    suspicionIds.set(sp.suspicionKey, id);
    s.suspicions.push({
      id,
      processId,
      runId,
      suspicionKey: sp.suspicionKey,
      ...(sp.row as object),
      inspectorStatus: sp.inspectorStatusOnInsert,
      promotedBy: sp.promotedBy,
      findingStatus: 'SUSPICION',
      relatedCheckIds: [],
      convertedCheckId: null,
      isStale: false,
      decidedBy: null,
      decidedAt: null,
      reasonCode: null,
      inspectorComment: null,
      rowVersion: 1,
      createdAt: now,
      updatedAt: now,
    } as unknown as SuspicionRow);
  }
  for (const f of input.findings) {
    const plan = planCheck(f);
    s.checks.push({
      id: s.checks.length + 1,
      processId,
      findingId: plan.findingId,
      ...(plan.row as object),
      findingSha256: plan.findingSha256,
      sourceSuspicionId: plan.isFree && plan.groupId ? (suspicionIds.get(plan.groupId) ?? null) : null,
      lifecycleState: 'ACTIVE',
      inspectorStatus: plan.inspectorStatusOnInsert,
      decidedBy: null,
      decidedUserId: null,
      decidedAt: null,
      decisionReasonCode: null,
      decisionBasisCode: null,
      decisionComment: null,
      currentDecisionId: null,
      reviewRequiredReason: null,
      newEvidenceAvailable: false,
      firstProtocolVersion: p.version,
      lastProtocolVersion: p.version,
      runId,
      rowVersion: 1,
      createdAt: now,
      updatedAt: now,
    } as CheckRow);
  }
  for (const f of input.files ?? []) {
    if (s.files.some((x) => x.id === f.file_id)) continue;
    s.files.push({
      id: f.file_id,
      objectId: input.objectId,
      docStage: f.stage ?? null,
      discipline: null,
      documentCode: f.document_code ?? null,
      revision: f.revision ?? null,
      approvalStatus: f.approval_status ?? null,
      approvalDate: null,
      predecessorId: null,
      fileHash: f.sha256 ?? createHash('sha256').update(f.file_id).digest('hex'),
      filePath: null,
      uploadedAt: now,
      fileName: f.file_name ?? `${f.file_id}.pdf`,
      ext: '.pdf',
      sizeBytes: null,
      manifestStage: f.manifest_stage ?? f.stage ?? 'UNKNOWN',
      manifestSection: null,
      datasetRole: null,
      split: input.split ?? 'TRAIN_PUBLIC',
      duplicateGroup: null,
      annotationStatus: null,
      pdfPages: f.pdf_pages ?? null,
      localStatus: 'PRESENT',
      lastRunId: null,
      createdAt: now,
      updatedAt: now,
    } as unknown as FileRow);
  }
  return processId;
}
