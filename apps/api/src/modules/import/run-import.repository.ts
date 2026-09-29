/**
 * Write side of the batch-run import v2: one transaction for all objects of a run.
 *
 * Idempotency and versioning:
 * - process: one per (run, object) (`processes_run_object_uq`);
 * - protocol: a new version only when the canonical content hash differs from the latest one (reason INITIAL,
 *   then RECHECK); the previous version becomes SUPERSEDED; a finalized protocol is never replaced (423);
 * - checks: upsert by (process, finding_id). Machine columns follow the artifacts; row_version grows only when the
 *   finding's content hash changes, and a decided check then gets review_required_reason = VALUE_CHANGED.
 *   Inspector columns (inspector_status … decision_comment) are written only on first insert. Checks missing from
 *   a re-import become SUPERSEDED; nothing is deleted;
 * - evidence_groups, suspicions: same pattern; evidence_fragments: keyed by the hash of their source reference
 *   (stable ids), SYSTEM rows missing from a re-import are removed, INSPECTOR rows are never touched;
 * - submission_exports: upsert by (process, variant); run_artifacts: replaced by the run's index.
 */
import { Injectable } from '@nestjs/common';
import { and, desc, eq, getTableColumns, notInArray, type SQL, sql } from 'drizzle-orm';
import type { PgTable } from 'drizzle-orm/pg-core';
import { uuidv7 } from '../../common/ids';
import { Database } from '../../db/database';
import type { PlannedCheck, PlannedFragment, PlannedGroup, PlannedSuspicion } from './import-plan';
import {
  checks,
  evidenceFragments,
  evidenceGroups,
  processes,
  processFiles,
  protocolExports,
  protocols,
  runArtifacts,
  submissionExports,
  suspicions,
} from './import.schema';

export interface PlannedProtocol {
  protocolNo: string;
  status: string;
  isFinal: boolean;
  versions: Record<string, unknown>;
  matrixVersion: string | null;
  datasetVersion: string | null;
  modelVersion: string | null;
  pipelineVersion: string;
  engineVersions: Record<string, unknown> | null;
  inputManifestHash: string;
  scenario: string | null;
  scenarioBase: string | null;
  uploadStatus: Record<string, unknown> | null;
  summary: unknown;
  contentJson: Record<string, unknown>;
  contentSha256: string;
  sourcePath: string;
  sourceSha256: string;
  generatedAt: Date;
}

export interface PlannedSubmission {
  variant: 'full' | 'strict';
  path: string;
  sha256: string;
  sizeBytes: number;
  rowsCount: number;
  content: unknown;
  sidecar: unknown;
}

export interface ObjectImportPlan {
  objectId: string;
  /** The object's files in run_manifest.json (already stored by the inventory import). */
  fileIds: string[];
  process: {
    scenario: string | null;
    scenarioBase: string | null;
    uploadStatus: Record<string, unknown> | null;
    inputManifestHash: string | null;
    matrixVersion: string | null;
    pipelineVersion: string | null;
  };
  protocol: PlannedProtocol | null;
  protocolExports: Array<{ format: string; storageKey: string; sha256: string; sizeBytes: number }>;
  groups: PlannedGroup[];
  checks: PlannedCheck[];
  fragments: PlannedFragment[];
  suspicions: PlannedSuspicion[];
  submissions: PlannedSubmission[];
}

export interface ArtifactRefRow {
  path: string;
  kind: string;
  format: string;
  schemaName: string | null;
  objectId: string | null;
  fileId: string | null;
  sha256: string;
  sizeBytes: number;
  records: number | null;
  producer: unknown;
  modifiedAt: Date | null;
}

export interface ArtifactsImportPlan {
  /** runs.id (UUID) of the inventory import of the same run. */
  runId: string;
  batchRunId: string;
  objects: ObjectImportPlan[];
  artifacts: ArtifactRefRow[];
}

export interface CheckCounts {
  total: number;
  inserted: number;
  updated: number;
  unchanged: number;
  superseded: number;
}

export interface ObjectImportResult {
  object_id: string;
  process_id: string;
  process_created: boolean;
  process_status: string;
  protocol: { id: string; version: number; created: boolean; status: string; content_sha256: string } | null;
  finding_groups: number;
  checks: CheckCounts;
  evidence_fragments: number;
  suspicions: number;
  submissions: string[];
}

/** The object's process is finalized and the run would change it (ТЗ §9.3 п.5 → 423 PROTOCOL_FINALIZED). */
export class ProtocolFinalizedConflict extends Error {
  constructor(
    readonly objectId: string,
    readonly processId: string,
  ) {
    super(`process ${processId} of ${objectId} is finalized`);
    this.name = 'ProtocolFinalizedConflict';
  }
}

export abstract class RunImportRepository {
  abstract saveArtifacts(plan: ArtifactsImportPlan): Promise<ObjectImportResult[]>;
}

const CHUNK = 200;

function chunks<T>(items: T[], size = CHUNK): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/** `{key: excluded.<column>}` for an ON CONFLICT DO UPDATE of the given TS keys. */
function excluded<T extends PgTable>(table: T, keys: string[]): Record<string, SQL> {
  const columns = getTableColumns(table) as Record<string, { name: string }>;
  const out: Record<string, SQL> = {};
  for (const key of keys) {
    const column = columns[key];
    if (!column) throw new Error(`unknown column ${key}`);
    out[key] = sql.raw(`excluded."${column.name}"`);
  }
  return out;
}

type Tx = Parameters<Parameters<Database['db']['transaction']>[0]>[0];

const OPEN_STATUSES = ['PENDING', 'PARSING', 'READY'];

@Injectable()
export class DrizzleRunImportRepository extends RunImportRepository {
  constructor(private readonly database: Database) {
    super();
  }

  async saveArtifacts(plan: ArtifactsImportPlan): Promise<ObjectImportResult[]> {
    return this.database.db.transaction(async (tx) => {
      const results: ObjectImportResult[] = [];
      for (const object of plan.objects) results.push(await this.saveObject(tx, plan, object));
      await tx.delete(runArtifacts).where(eq(runArtifacts.runId, plan.runId));
      for (const part of chunks(plan.artifacts)) {
        await tx.insert(runArtifacts).values(part.map((a) => ({ ...a, runId: plan.runId })));
      }
      return results;
    });
  }

  private async saveObject(tx: Tx, plan: ArtifactsImportPlan, o: ObjectImportPlan): Promise<ObjectImportResult> {
    const now = new Date();
    const [proc] = await tx
      .insert(processes)
      .values({
        id: uuidv7(),
        objectId: o.objectId,
        status: o.protocol ? 'READY' : 'PARSING',
        stage: o.protocol ? 'DONE' : 'PROTOCOL_BUILDING',
        source: 'BATCH_IMPORT',
        purpose: 'INSPECTION',
        activeRunId: plan.runId,
        batchRunId: plan.batchRunId,
        ...o.process,
        createdAt: now,
        updatedAt: now,
      })
      .onConflictDoUpdate({
        target: [processes.activeRunId, processes.objectId],
        set: {
          ...excluded(processes, ['scenario', 'scenarioBase', 'uploadStatus', 'inputManifestHash', 'matrixVersion', 'pipelineVersion']),
          updatedAt: now,
        },
      })
      .returning({ id: processes.id, status: processes.status, inserted: sql<boolean>`(xmax = 0)` });
    if (!proc) throw new Error('process upsert returned no row');
    const processId = proc.id;

    const existingChecks = await tx
      .select({ id: checks.id, findingId: checks.findingId, sha: checks.findingSha256, lifecycle: checks.lifecycleState })
      .from(checks)
      .where(eq(checks.processId, processId));
    const byFinding = new Map(existingChecks.map((c) => [c.findingId, c]));
    const [latest] = await tx
      .select()
      .from(protocols)
      .where(eq(protocols.processId, processId))
      .orderBy(desc(protocols.version))
      .limit(1)
      .for('update');

    const protocolChanged = o.protocol !== null && latest?.contentSha256 !== o.protocol.contentSha256;
    const checksChanged =
      o.checks.some((c) => byFinding.get(c.findingId)?.sha !== c.findingSha256) ||
      existingChecks.some((c) => c.lifecycle === 'ACTIVE' && !o.checks.some((p) => p.findingId === c.findingId));
    if (proc.status === 'FINALIZED' || latest?.status === 'PROTOCOL_FINALIZED') {
      if (protocolChanged || checksChanged) throw new ProtocolFinalizedConflict(o.objectId, processId);
      return this.unchangedResult(o, processId, proc, latest ?? null);
    }

    if (o.fileIds.length) {
      for (const part of chunks(o.fileIds, 1000)) {
        await tx
          .insert(processFiles)
          .values(part.map((fileId) => ({ processId, fileId, addedAt: now })))
          .onConflictDoNothing();
      }
    }

    // Protocol version.
    let protocolRow = latest ?? null;
    let protocolCreated = false;
    if (o.protocol && protocolChanged) {
      if (latest) {
        await tx
          .update(protocols)
          .set({ status: 'SUPERSEDED', supersededAt: now, supersededReason: 'Заменён новой версией при повторном импорте прогона' })
          .where(eq(protocols.id, latest.id));
      }
      const [row] = await tx
        .insert(protocols)
        .values({
          id: uuidv7(),
          processId,
          objectId: o.objectId,
          version: (latest?.version ?? 0) + 1,
          versionReason: latest ? 'RECHECK' : 'INITIAL',
          previousVersionId: latest?.id ?? null,
          runId: plan.runId,
          ...o.protocol,
          createdAt: now,
        })
        .returning();
      protocolRow = row ?? null;
      protocolCreated = true;
    }
    const version = protocolRow?.version ?? null;
    if (protocolRow) {
      for (const e of o.protocolExports) {
        await tx
          .insert(protocolExports)
          .values({ id: uuidv7(), protocolId: protocolRow.id, ...e, generatedAt: now })
          .onConflictDoUpdate({
            target: [protocolExports.protocolId, protocolExports.format],
            set: { ...excluded(protocolExports, ['storageKey', 'sha256', 'sizeBytes']), generatedAt: now },
          });
      }
    }

    // Evidence groups.
    const groupKeys = o.groups.length ? Object.keys(o.groups[0]!.row) : [];
    for (const part of chunks(o.groups)) {
      await tx
        .insert(evidenceGroups)
        .values(
          part.map((g) => ({
            processId,
            evidenceGroupId: g.evidenceGroupId,
            ...(g.row as object),
            groupSha256: g.groupSha256,
            lifecycleState: 'ACTIVE',
            firstProtocolVersion: version,
            lastProtocolVersion: version,
            createdAt: now,
            updatedAt: now,
          })) as Array<typeof evidenceGroups.$inferInsert>,
        )
        .onConflictDoUpdate({
          target: [evidenceGroups.processId, evidenceGroups.evidenceGroupId],
          set: {
            ...excluded(evidenceGroups, [...groupKeys, 'groupSha256', 'lastProtocolVersion']),
            lifecycleState: 'ACTIVE',
            updatedAt: sql`CASE WHEN ${evidenceGroups.groupSha256} IS DISTINCT FROM excluded."group_sha256" THEN now() ELSE ${evidenceGroups.updatedAt} END`,
          },
        });
    }
    const groupIds = o.groups.map((g) => g.evidenceGroupId);
    await tx
      .update(evidenceGroups)
      .set({ lifecycleState: 'SUPERSEDED', updatedAt: now })
      .where(
        and(
          eq(evidenceGroups.processId, processId),
          eq(evidenceGroups.lifecycleState, 'ACTIVE'),
          ...(groupIds.length ? [notInArray(evidenceGroups.evidenceGroupId, groupIds)] : []),
        ),
      );

    // Suspicions (FREE_SEARCH groups).
    const suspicionIdByKey = new Map<string, number>();
    const suspicionKeys = o.suspicions.length ? Object.keys(o.suspicions[0]!.row) : [];
    for (const s of o.suspicions) {
      const [row] = await tx
        .insert(suspicions)
        .values({
          processId,
          runId: plan.runId,
          suspicionKey: s.suspicionKey,
          ...(s.row as object),
          inspectorStatus: s.inspectorStatusOnInsert,
          promotedBy: s.promotedBy,
          findingStatus: 'SUSPICION',
          createdAt: now,
          updatedAt: now,
        } as typeof suspicions.$inferInsert)
        .onConflictDoUpdate({
          target: [suspicions.processId, suspicions.suspicionKey],
          set: { ...excluded(suspicions, [...suspicionKeys, 'runId']), isStale: false, updatedAt: now },
        })
        .returning({ id: suspicions.id });
      if (row) suspicionIdByKey.set(s.suspicionKey, row.id);
    }
    const suspicionKeysPlanned = o.suspicions.map((s) => s.suspicionKey);
    await tx
      .update(suspicions)
      .set({ isStale: true, updatedAt: now })
      .where(
        and(
          eq(suspicions.processId, processId),
          eq(suspicions.isStale, false),
          ...(suspicionKeysPlanned.length ? [notInArray(suspicions.suspicionKey, suspicionKeysPlanned)] : []),
        ),
      );

    // Checks.
    const counts: CheckCounts = { total: o.checks.length, inserted: 0, updated: 0, unchanged: 0, superseded: 0 };
    const checkIdByFinding = new Map<string, number>();
    const checkKeys = o.checks.length ? Object.keys(o.checks[0]!.row) : [];
    const changed = sql`${checks.findingSha256} IS DISTINCT FROM excluded."finding_sha256"`;
    for (const part of chunks(o.checks)) {
      const rows = await tx
        .insert(checks)
        .values(
          part.map((c) => ({
            processId,
            findingId: c.findingId,
            ...(c.row as object),
            findingSha256: c.findingSha256,
            sourceSuspicionId: c.isFree && c.groupId ? (suspicionIdByKey.get(c.groupId) ?? null) : null,
            inspectorStatus: c.inspectorStatusOnInsert,
            runId: plan.runId,
            lifecycleState: 'ACTIVE',
            firstProtocolVersion: version,
            lastProtocolVersion: version,
            createdAt: now,
            updatedAt: now,
          })) as Array<typeof checks.$inferInsert>,
        )
        .onConflictDoUpdate({
          target: [checks.processId, checks.findingId],
          set: {
            ...excluded(checks, [...checkKeys, 'findingSha256', 'sourceSuspicionId', 'runId', 'lastProtocolVersion']),
            lifecycleState: 'ACTIVE',
            rowVersion: sql`CASE WHEN ${changed} THEN ${checks.rowVersion} + 1 ELSE ${checks.rowVersion} END`,
            reviewRequiredReason: sql`CASE WHEN ${changed} AND ${checks.decidedBy} = 'INSPECTOR' THEN 'VALUE_CHANGED' ELSE ${checks.reviewRequiredReason} END`,
            updatedAt: sql`CASE WHEN ${changed} OR ${checks.lifecycleState} <> 'ACTIVE' THEN now() ELSE ${checks.updatedAt} END`,
          },
        })
        .returning({ id: checks.id, findingId: checks.findingId });
      for (const r of rows) checkIdByFinding.set(r.findingId, r.id);
    }
    for (const c of o.checks) {
      const before = byFinding.get(c.findingId);
      if (!before) counts.inserted += 1;
      else if (before.sha !== c.findingSha256 || before.lifecycle !== 'ACTIVE') counts.updated += 1;
      else counts.unchanged += 1;
    }
    const plannedFindings = o.checks.map((c) => c.findingId);
    const superseded = await tx
      .update(checks)
      .set({ lifecycleState: 'SUPERSEDED', updatedAt: now })
      .where(
        and(
          eq(checks.processId, processId),
          eq(checks.lifecycleState, 'ACTIVE'),
          ...(plannedFindings.length ? [notInArray(checks.findingId, plannedFindings)] : []),
        ),
      )
      .returning({ id: checks.id });
    counts.superseded = superseded.length;

    // Evidence fragments.
    const fragmentKeys = o.fragments.map((f) => f.fragmentKey);
    for (const part of chunks(o.fragments)) {
      await tx
        .insert(evidenceFragments)
        .values(
          part.map((f) => ({
            processId,
            fragmentKey: f.fragmentKey,
            ...(f.row as object),
            checkId: f.findingId ? (checkIdByFinding.get(f.findingId) ?? null) : null,
            suspicionId: f.suspicionKey ? (suspicionIdByKey.get(f.suspicionKey) ?? null) : null,
            createdAt: now,
            updatedAt: now,
          })) as Array<typeof evidenceFragments.$inferInsert>,
        )
        .onConflictDoUpdate({
          target: [evidenceFragments.processId, evidenceFragments.fragmentKey],
          set: excluded(evidenceFragments, ['checkId', 'suspicionId']),
        });
    }
    await tx
      .delete(evidenceFragments)
      .where(
        and(
          eq(evidenceFragments.processId, processId),
          eq(evidenceFragments.origin, 'SYSTEM'),
          ...(fragmentKeys.length ? [notInArray(evidenceFragments.fragmentKey, fragmentKeys)] : []),
        ),
      );

    // Suspicion ↔ check links.
    for (const s of o.suspicions) {
      const id = suspicionIdByKey.get(s.suspicionKey);
      if (id === undefined) continue;
      const related = s.findingIds.map((f) => checkIdByFinding.get(f)).filter((x): x is number => x !== undefined);
      await tx
        .update(suspicions)
        .set({ relatedCheckIds: related, convertedCheckId: s.promotedBy ? (related[0] ?? null) : null })
        .where(eq(suspicions.id, id));
    }

    // Submissions.
    const submissionVariants: string[] = [];
    for (const s of o.submissions) {
      await tx
        .insert(submissionExports)
        .values({ id: uuidv7(), processId, runId: plan.runId, objectId: o.objectId, ...s, createdAt: now, updatedAt: now })
        .onConflictDoUpdate({
          target: [submissionExports.processId, submissionExports.variant],
          set: {
            ...excluded(submissionExports, ['path', 'sha256', 'sizeBytes', 'rowsCount', 'content', 'sidecar', 'runId']),
            updatedAt: now,
          },
        });
      submissionVariants.push(s.variant);
    }

    const newStatus = o.protocol ? 'READY' : 'PARSING';
    const [updated] = await tx
      .update(processes)
      .set({
        currentProtocolId: protocolRow?.id ?? null,
        status: sql`CASE WHEN ${processes.status} IN (${sql.join(
          OPEN_STATUSES.map((s) => sql`${s}`),
          sql`, `,
        )}) THEN ${newStatus} ELSE ${processes.status} END`,
        stage: sql`CASE WHEN ${processes.status} IN (${sql.join(
          OPEN_STATUSES.map((s) => sql`${s}`),
          sql`, `,
        )}) THEN ${o.protocol ? 'DONE' : 'PROTOCOL_BUILDING'} ELSE ${processes.stage} END`,
        rowVersion: sql`${processes.rowVersion} + ${protocolCreated || counts.inserted + counts.updated + counts.superseded > 0 ? 1 : 0}`,
        updatedAt: now,
      })
      .where(eq(processes.id, processId))
      .returning({ status: processes.status });

    return {
      object_id: o.objectId,
      process_id: processId,
      process_created: Boolean(proc.inserted),
      process_status: updated?.status ?? proc.status,
      protocol: protocolRow
        ? {
            id: protocolRow.id,
            version: protocolRow.version,
            created: protocolCreated,
            status: protocolCreated ? protocolRow.status : (await this.currentStatus(tx, protocolRow.id)),
            content_sha256: protocolRow.contentSha256,
          }
        : null,
      finding_groups: o.groups.length,
      checks: counts,
      evidence_fragments: o.fragments.length,
      suspicions: o.suspicions.length,
      submissions: submissionVariants,
    };
  }

  private async currentStatus(tx: Tx, protocolId: string): Promise<string> {
    const [row] = await tx.select({ status: protocols.status }).from(protocols).where(eq(protocols.id, protocolId));
    return row?.status ?? 'SUPERSEDED';
  }

  private unchangedResult(
    o: ObjectImportPlan,
    processId: string,
    proc: { status: string },
    latest: typeof protocols.$inferSelect | null,
  ): ObjectImportResult {
    return {
      object_id: o.objectId,
      process_id: processId,
      process_created: false,
      process_status: proc.status,
      protocol: latest
        ? { id: latest.id, version: latest.version, created: false, status: latest.status, content_sha256: latest.contentSha256 }
        : null,
      finding_groups: o.groups.length,
      checks: { total: o.checks.length, inserted: 0, updated: 0, unchanged: o.checks.length, superseded: 0 },
      evidence_fragments: o.fragments.length,
      suspicions: o.suspicions.length,
      submissions: o.submissions.map((s) => s.variant),
    };
  }
}
