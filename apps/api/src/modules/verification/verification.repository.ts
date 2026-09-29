/**
 * Persistence port of the verification service and its PostgreSQL implementation (Drizzle).
 *
 * Writes run inside `transaction()` on a `VerificationTx`: the process row is locked first (FOR NO KEY UPDATE for
 * decisions — serialized per process, see lockProcess — FOR UPDATE for finalize/unfinalize/claim/reopen; 05 §3.13),
 * so no decision can land after a snapshot and none is lost; the finding row is locked FOR UPDATE and updated only when its row_version still
 * equals If-Match. Audit rows go through `auditExecutor` into the same transaction (CLAUDE.md, AG-00 audit).
 */
import { Injectable } from '@nestjs/common';
import { and, asc, desc, eq, inArray, max, sql, type SQL } from 'drizzle-orm';
import { Database, type Db } from '../../db/database';
import { files, objects, type FileRow } from '../../db/schema';
import type { AuditExecutor } from '../audit/audit.repository';
import {
  checks,
  evidenceGroups,
  processes,
  protocols,
  suspicions,
  type CheckRow,
  type EvidenceGroupRow,
  type ProcessRow,
  type ProtocolRow,
  type SuspicionRow,
} from '../import/import.schema';
import {
  datasetItems,
  disputeLog,
  rejectionLog,
  uiEvents,
  verificationDecisions,
  verificationIdempotency,
  type DatasetItemRow,
  type DecisionRow,
  type DisputeRow,
  type IdempotencyRow,
  type NewDatasetItemRow,
  type NewDecisionRow,
  type NewDisputeRow,
  type NewRejectionRow,
  type NewUiEventRow,
  type RejectionRow,
  type UiEventRow,
} from './verification.schema';

export interface ObjectInfo {
  id: string;
  name: string | null;
  address: string | null;
  split: string | null;
  objectGroupId: string | null;
}

/** Inspector columns of `checks` (the import never rewrites them). */
export interface CheckPatch {
  inspectorStatus: string | null;
  findingStatus: string | null;
  decidedBy: string | null;
  decidedUserId: string | null;
  decidedAt: Date | null;
  decisionReasonCode: string | null;
  decisionBasisCode: string | null;
  decisionComment: string | null;
  currentDecisionId: string | null;
  reviewRequiredReason: string | null;
}

export interface ProcessPatch {
  status?: string;
  verificationStartedAt?: Date | null;
  completedAt?: Date | null;
  finalizedAt?: Date | null;
  currentProtocolId?: string | null;
  assignedInspectorId?: string | null;
}

export type NewProtocolRow = typeof protocols.$inferInsert;

export interface NewIdempotency {
  userId: string;
  idempotencyKey: string;
  operation: string;
  requestSha256: string;
  statusCode: number;
  responseBody: unknown;
  etag: string | null;
}

export interface DatasetItemFilter {
  processId?: string;
  objectId?: string;
  status?: string;
}

export interface VerificationTx {
  /** Pass to AuditService.record so the audit row commits with the change. */
  readonly auditExecutor: AuditExecutor | undefined;
  /**
   * `no key update` for decisions: decisions of one process are serialized (a decision may move the process
   * READY → VERIFYING → COMPLETED; two FOR SHARE holders upgrading to an UPDATE of the same row deadlock).
   * `update` for finalize / unfinalize / claim / reopen.
   */
  lockProcess(id: string, mode: 'no key update' | 'update'): Promise<ProcessRow | null>;
  lockCheck(processId: string, findingId: string): Promise<CheckRow | null>;
  checksOf(processId: string): Promise<CheckRow[]>;
  /** Row-version guarded update; null when If-Match no longer matches (VERSION_CONFLICT). */
  updateCheck(id: number, expectedRowVersion: number, patch: CheckPatch): Promise<CheckRow | null>;
  /** Increments row_version. */
  updateProcess(id: string, patch: ProcessPatch): Promise<ProcessRow>;
  getProtocol(id: string): Promise<ProtocolRow | null>;
  maxProtocolVersion(processId: string): Promise<number>;
  insertProtocol(row: NewProtocolRow): Promise<ProtocolRow>;
  updateProtocol(id: string, patch: { status?: string; supersededAt?: Date | null; supersededReason?: string | null }): Promise<void>;
  insertDecision(row: NewDecisionRow): Promise<DecisionRow>;
  decisionsOf(processId: string): Promise<DecisionRow[]>;
  insertRejection(row: NewRejectionRow): Promise<RejectionRow>;
  openDisputesOf(processId: string): Promise<DisputeRow[]>;
  lockDispute(id: number): Promise<DisputeRow | null>;
  insertDispute(row: NewDisputeRow): Promise<DisputeRow>;
  resolveDispute(
    id: number,
    patch: { resolutionStatus: string; resolvedBy: string; resolutionComment: string; resolutionDecisionId: string; resolvedAt: Date },
  ): Promise<DisputeRow>;
  insertDatasetItems(rows: NewDatasetItemRow[]): Promise<void>;
  setDatasetItemsStatus(protocolId: string, status: string): Promise<number>;
  getIdempotency(userId: string, key: string): Promise<IdempotencyRow | null>;
  /** false when (user, key) exists already (a concurrent request with the same key won). */
  putIdempotency(row: NewIdempotency): Promise<boolean>;
}

export abstract class VerificationRepository {
  abstract transaction<T>(fn: (tx: VerificationTx) => Promise<T>): Promise<T>;
  abstract getProcess(id: string): Promise<ProcessRow | null>;
  abstract processesOfObject(objectId: string): Promise<ProcessRow[]>;
  abstract getObject(id: string): Promise<ObjectInfo | null>;
  abstract checksOf(processId: string): Promise<CheckRow[]>;
  abstract groupsOf(processId: string): Promise<EvidenceGroupRow[]>;
  abstract suspicionsOf(processId: string): Promise<SuspicionRow[]>;
  /** Every protocol version of the process, oldest first. */
  abstract protocolsOf(processId: string): Promise<ProtocolRow[]>;
  abstract getProtocol(id: string): Promise<ProtocolRow | null>;
  abstract files(ids: string[]): Promise<FileRow[]>;
  /** Oldest first. */
  abstract decisionsOf(processId: string, findingId?: string): Promise<DecisionRow[]>;
  abstract disputesOf(processId: string): Promise<DisputeRow[]>;
  abstract getDispute(id: number): Promise<DisputeRow | null>;
  abstract rejectionsOf(processId: string): Promise<RejectionRow[]>;
  abstract datasetItems(filter: DatasetItemFilter): Promise<DatasetItemRow[]>;
  abstract getIdempotency(userId: string, key: string): Promise<IdempotencyRow | null>;
  abstract insertUiEvents(rows: NewUiEventRow[]): Promise<number>;
  abstract uiEventsOf(processId: string): Promise<UiEventRow[]>;
}

type Tx = Parameters<Parameters<Db['transaction']>[0]>[0];
type Reader = Db | Tx;

function isUniqueViolation(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { code?: string }).code === '23505';
}

class DrizzleVerificationTx implements VerificationTx {
  constructor(private readonly tx: Tx) {}

  get auditExecutor(): AuditExecutor {
    return this.tx;
  }

  async lockProcess(id: string, mode: 'no key update' | 'update'): Promise<ProcessRow | null> {
    const [row] = await this.tx.select().from(processes).where(eq(processes.id, id)).for(mode);
    return row ?? null;
  }

  async lockCheck(processId: string, findingId: string): Promise<CheckRow | null> {
    const [row] = await this.tx
      .select()
      .from(checks)
      .where(and(eq(checks.processId, processId), eq(checks.findingId, findingId)))
      .for('update');
    return row ?? null;
  }

  checksOf(processId: string): Promise<CheckRow[]> {
    return this.tx.select().from(checks).where(eq(checks.processId, processId)).orderBy(asc(checks.id));
  }

  async updateCheck(id: number, expectedRowVersion: number, patch: CheckPatch): Promise<CheckRow | null> {
    const [row] = await this.tx
      .update(checks)
      .set({ ...patch, rowVersion: sql`${checks.rowVersion} + 1`, updatedAt: new Date() })
      .where(and(eq(checks.id, id), eq(checks.rowVersion, expectedRowVersion)))
      .returning();
    return row ?? null;
  }

  async updateProcess(id: string, patch: ProcessPatch): Promise<ProcessRow> {
    const [row] = await this.tx
      .update(processes)
      .set({ ...patch, rowVersion: sql`${processes.rowVersion} + 1`, updatedAt: new Date() })
      .where(eq(processes.id, id))
      .returning();
    if (!row) throw new Error(`process ${id} vanished inside its own transaction`);
    return row;
  }

  async getProtocol(id: string): Promise<ProtocolRow | null> {
    const [row] = await this.tx.select().from(protocols).where(eq(protocols.id, id));
    return row ?? null;
  }

  async maxProtocolVersion(processId: string): Promise<number> {
    const [row] = await this.tx.select({ v: max(protocols.version) }).from(protocols).where(eq(protocols.processId, processId));
    return Number(row?.v ?? 0);
  }

  async insertProtocol(row: NewProtocolRow): Promise<ProtocolRow> {
    const [out] = await this.tx.insert(protocols).values(row).returning();
    return out!;
  }

  async updateProtocol(id: string, patch: { status?: string; supersededAt?: Date | null; supersededReason?: string | null }): Promise<void> {
    await this.tx.update(protocols).set(patch).where(eq(protocols.id, id));
  }

  async insertDecision(row: NewDecisionRow): Promise<DecisionRow> {
    const [out] = await this.tx.insert(verificationDecisions).values(row).returning();
    return out!;
  }

  decisionsOf(processId: string): Promise<DecisionRow[]> {
    return this.tx
      .select()
      .from(verificationDecisions)
      .where(eq(verificationDecisions.processId, processId))
      .orderBy(asc(verificationDecisions.createdAt), asc(verificationDecisions.id));
  }

  async insertRejection(row: NewRejectionRow): Promise<RejectionRow> {
    const [out] = await this.tx.insert(rejectionLog).values(row).returning();
    return out!;
  }

  openDisputesOf(processId: string): Promise<DisputeRow[]> {
    return this.tx
      .select()
      .from(disputeLog)
      .where(and(eq(disputeLog.processId, processId), eq(disputeLog.resolutionStatus, 'OPEN')));
  }

  async lockDispute(id: number): Promise<DisputeRow | null> {
    const [row] = await this.tx.select().from(disputeLog).where(eq(disputeLog.id, id)).for('update');
    return row ?? null;
  }

  async insertDispute(row: NewDisputeRow): Promise<DisputeRow> {
    const [out] = await this.tx.insert(disputeLog).values(row).returning();
    return out!;
  }

  async resolveDispute(
    id: number,
    patch: { resolutionStatus: string; resolvedBy: string; resolutionComment: string; resolutionDecisionId: string; resolvedAt: Date },
  ): Promise<DisputeRow> {
    const [row] = await this.tx
      .update(disputeLog)
      .set({ ...patch, rowVersion: sql`${disputeLog.rowVersion} + 1` })
      .where(eq(disputeLog.id, id))
      .returning();
    return row!;
  }

  async insertDatasetItems(rows: NewDatasetItemRow[]): Promise<void> {
    if (rows.length) await this.tx.insert(datasetItems).values(rows);
  }

  async setDatasetItemsStatus(protocolId: string, status: string): Promise<number> {
    const rows = await this.tx
      .update(datasetItems)
      .set({ status, updatedAt: new Date() })
      .where(eq(datasetItems.protocolId, protocolId))
      .returning({ id: datasetItems.id });
    return rows.length;
  }

  async getIdempotency(userId: string, key: string): Promise<IdempotencyRow | null> {
    return readIdempotency(this.tx, userId, key);
  }

  async putIdempotency(row: NewIdempotency): Promise<boolean> {
    const inserted = await this.tx
      .insert(verificationIdempotency)
      .values(row)
      .onConflictDoNothing()
      .returning({ key: verificationIdempotency.idempotencyKey });
    return inserted.length > 0;
  }
}

async function readIdempotency(db: Reader, userId: string, key: string): Promise<IdempotencyRow | null> {
  const [row] = await db
    .select()
    .from(verificationIdempotency)
    .where(and(eq(verificationIdempotency.userId, userId), eq(verificationIdempotency.idempotencyKey, key)));
  return row ?? null;
}

@Injectable()
export class DrizzleVerificationRepository extends VerificationRepository {
  constructor(private readonly database: Database) {
    super();
  }

  private get db(): Db {
    return this.database.db;
  }

  transaction<T>(fn: (tx: VerificationTx) => Promise<T>): Promise<T> {
    return this.db.transaction((tx) => fn(new DrizzleVerificationTx(tx)));
  }

  async getProcess(id: string): Promise<ProcessRow | null> {
    const [row] = await this.db.select().from(processes).where(eq(processes.id, id));
    return row ?? null;
  }

  processesOfObject(objectId: string): Promise<ProcessRow[]> {
    return this.db.select().from(processes).where(eq(processes.objectId, objectId)).orderBy(desc(processes.createdAt));
  }

  async getObject(id: string): Promise<ObjectInfo | null> {
    const [row] = await this.db
      .select({ id: objects.id, name: objects.name, address: objects.address, split: objects.split, objectGroupId: objects.objectGroupId })
      .from(objects)
      .where(eq(objects.id, id));
    return row ?? null;
  }

  checksOf(processId: string): Promise<CheckRow[]> {
    return this.db.select().from(checks).where(eq(checks.processId, processId)).orderBy(asc(checks.id));
  }

  groupsOf(processId: string): Promise<EvidenceGroupRow[]> {
    return this.db.select().from(evidenceGroups).where(eq(evidenceGroups.processId, processId)).orderBy(asc(evidenceGroups.id));
  }

  suspicionsOf(processId: string): Promise<SuspicionRow[]> {
    return this.db.select().from(suspicions).where(eq(suspicions.processId, processId)).orderBy(asc(suspicions.id));
  }

  protocolsOf(processId: string): Promise<ProtocolRow[]> {
    return this.db.select().from(protocols).where(eq(protocols.processId, processId)).orderBy(asc(protocols.version));
  }

  async getProtocol(id: string): Promise<ProtocolRow | null> {
    const [row] = await this.db.select().from(protocols).where(eq(protocols.id, id));
    return row ?? null;
  }

  async files(ids: string[]): Promise<FileRow[]> {
    const unique = [...new Set(ids)];
    if (!unique.length) return [];
    return this.db.select().from(files).where(inArray(files.id, unique));
  }

  decisionsOf(processId: string, findingId?: string): Promise<DecisionRow[]> {
    const where: SQL[] = [eq(verificationDecisions.processId, processId)];
    if (findingId) where.push(eq(verificationDecisions.findingId, findingId));
    return this.db
      .select()
      .from(verificationDecisions)
      .where(and(...where))
      .orderBy(asc(verificationDecisions.createdAt), asc(verificationDecisions.id));
  }

  disputesOf(processId: string): Promise<DisputeRow[]> {
    return this.db.select().from(disputeLog).where(eq(disputeLog.processId, processId)).orderBy(asc(disputeLog.id));
  }

  async getDispute(id: number): Promise<DisputeRow | null> {
    const [row] = await this.db.select().from(disputeLog).where(eq(disputeLog.id, id));
    return row ?? null;
  }

  rejectionsOf(processId: string): Promise<RejectionRow[]> {
    return this.db.select().from(rejectionLog).where(eq(rejectionLog.processId, processId)).orderBy(asc(rejectionLog.id));
  }

  datasetItems(filter: DatasetItemFilter): Promise<DatasetItemRow[]> {
    const where: SQL[] = [];
    if (filter.processId) where.push(eq(datasetItems.processId, filter.processId));
    if (filter.objectId) where.push(eq(datasetItems.objectId, filter.objectId));
    if (filter.status) where.push(eq(datasetItems.status, filter.status));
    return this.db
      .select()
      .from(datasetItems)
      .where(where.length ? and(...where) : undefined)
      .orderBy(desc(datasetItems.createdAt), asc(datasetItems.findingId))
      .limit(1000);
  }

  getIdempotency(userId: string, key: string): Promise<IdempotencyRow | null> {
    return readIdempotency(this.db, userId, key);
  }

  async insertUiEvents(rows: NewUiEventRow[]): Promise<number> {
    if (!rows.length) return 0;
    try {
      const out = await this.db.insert(uiEvents).values(rows).returning({ id: uiEvents.id });
      return out.length;
    } catch (err) {
      if (isUniqueViolation(err)) return 0;
      throw err;
    }
  }

  uiEventsOf(processId: string): Promise<UiEventRow[]> {
    return this.db.select().from(uiEvents).where(eq(uiEvents.processId, processId)).orderBy(asc(uiEvents.tsClient)).limit(20_000);
  }
}
