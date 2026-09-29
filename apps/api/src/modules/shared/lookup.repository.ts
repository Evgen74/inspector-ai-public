/**
 * Read-only lookups the D1 modules (protocols, dashboard, pages) need from the imported inventory:
 * which imported runs include an object, where their run directories are, and where a file lives on disk.
 * `CatalogLookup` is the DI token; DB-free tests bind an in-memory implementation.
 */
import { Injectable } from '@nestjs/common';
import { and, asc, desc, eq, isNull, sql } from 'drizzle-orm';
import type { SQL } from 'drizzle-orm';
import { Database } from '../../db/database';
import { files, objects, runs } from '../../db/schema';

export interface RunRecord {
  /** runs.id (UUID v7) */
  id: string;
  batchRunId: string;
  /** Absolute path of the imported run_manifest.json; its directory is the run directory. */
  manifestRef: string;
  startedAt: Date;
  finishedAt: Date | null;
  importedAt: Date;
}

export interface ObjectRecord {
  objectId: string;
  name: string | null;
  /** ManifestSplit */
  split: string | null;
  filesTotal: number;
  updatedAt: Date;
}

export interface FileRecord {
  fileId: string;
  objectId: string;
  fileName: string;
  /** manifest relative_path (base 01_ДОКУМЕНТАЦИЯ) */
  filePath: string | null;
  fileHash: string;
  pdfPages: number | null;
  /** LocalFileStatus */
  localStatus: string;
  /** Split of the owning object (the file's own split when the object has none). */
  split: string | null;
}

/** Inspector status per finding group (checks aggregated) and per FREE-* suspicion, for one run × object. */
export type DecisionMap = Map<string, string>;

/**
 * Group status from its atomic checks (AG-05 decides per check): any confirmation → CONFIRMED_VIOLATION, else
 * any clarification → CLARIFICATION_REQUIRED, else all rejected → NEGATIVE_VERIFIED, else PENDING.
 */
export function aggregateGroupStatus(statuses: string[]): string {
  if (statuses.includes('CONFIRMED_VIOLATION')) return 'CONFIRMED_VIOLATION';
  if (statuses.includes('CLARIFICATION_REQUIRED')) return 'CLARIFICATION_REQUIRED';
  if (statuses.length > 0 && statuses.every((s) => s === 'NEGATIVE_VERIFIED')) return 'NEGATIVE_VERIFIED';
  return 'PENDING';
}

export abstract class CatalogLookup {
  /** Imported runs whose run_manifest.json lists the object, newest (started_at) first. */
  abstract runsForObject(objectId: string): Promise<RunRecord[]>;
  abstract getRun(runId: string): Promise<RunRecord | null>;
  abstract getObject(objectId: string): Promise<ObjectRecord | null>;
  /** Archived objects («Архивировать») are left out unless `includeArchived`. */
  abstract listObjects(includeArchived?: boolean): Promise<ObjectRecord[]>;
  abstract getFile(fileId: string): Promise<FileRecord | null>;
  /**
   * Live inspector decisions for the process of (object, run) from the verification tables (checks and
   * suspicions, filled by AG-00's import and updated by AG-05). Empty when those tables do not exist yet.
   */
  abstract decisionsForRun(objectId: string, runId: string): Promise<DecisionMap>;
}

@Injectable()
export class DrizzleCatalogLookup extends CatalogLookup {
  constructor(private readonly database: Database) {
    super();
  }

  private get db() {
    return this.database.db;
  }

  private static run(r: typeof runs.$inferSelect): RunRecord {
    return {
      id: r.id,
      batchRunId: r.batchRunId,
      manifestRef: r.manifestRef,
      startedAt: r.startedAt,
      finishedAt: r.finishedAt,
      importedAt: r.importedAt,
    };
  }

  async runsForObject(objectId: string): Promise<RunRecord[]> {
    const probe = JSON.stringify([{ object_id: objectId }]);
    const rows = await this.db
      .select()
      .from(runs)
      .where(and(sql`${runs.manifest} -> 'objects' @> ${probe}::jsonb`, isNull(runs.archivedAt)))
      .orderBy(desc(runs.startedAt), desc(runs.importedAt));
    return rows.map(DrizzleCatalogLookup.run);
  }

  async getRun(runId: string): Promise<RunRecord | null> {
    const [row] = await this.db.select().from(runs).where(eq(runs.id, runId)).limit(1);
    return row ? DrizzleCatalogLookup.run(row) : null;
  }

  private async objectRows(where?: SQL): Promise<ObjectRecord[]> {
    const base = this.db
      .select({
        objectId: objects.id,
        name: objects.name,
        split: objects.split,
        updatedAt: objects.updatedAt,
        filesTotal: sql<number>`(select count(*) from ${files} where ${files.objectId} = ${objects.id})`.mapWith(Number),
      })
      .from(objects);
    const rows = await (where ? base.where(where) : base).orderBy(asc(objects.id));
    return rows;
  }

  async getObject(objectId: string): Promise<ObjectRecord | null> {
    const [row] = await this.objectRows(eq(objects.id, objectId));
    return row ?? null;
  }

  async listObjects(includeArchived = false): Promise<ObjectRecord[]> {
    return this.objectRows(includeArchived ? undefined : isNull(objects.archivedAt));
  }

  private tablesCheckedAt = 0;
  private tables = { checks: false, suspicions: false };

  private async verificationTables(): Promise<{ checks: boolean; suspicions: boolean }> {
    if (Date.now() - this.tablesCheckedAt < 60_000) return this.tables;
    const result = await this.db.execute(
      sql`select to_regclass('public.checks') is not null as checks, to_regclass('public.suspicions') is not null as suspicions`,
    );
    const row = (result as unknown as { rows: Array<{ checks: boolean; suspicions: boolean }> }).rows[0];
    this.tables = { checks: Boolean(row?.checks), suspicions: Boolean(row?.suspicions) };
    this.tablesCheckedAt = Date.now();
    return this.tables;
  }

  async decisionsForRun(objectId: string, runId: string): Promise<DecisionMap> {
    const out: DecisionMap = new Map();
    const tables = await this.verificationTables();
    if (tables.checks) {
      const result = await this.db.execute(sql`
        select c.evidence_group_id as group_id, array_agg(c.inspector_status) as statuses
        from checks c join processes p on p.id = c.process_id
        where p.object_id = ${objectId} and p.active_run_id = ${runId}::uuid
          and c.evidence_group_id is not null and c.inspector_status is not null and c.lifecycle_state = 'ACTIVE'
        group by c.evidence_group_id`);
      for (const r of (result as unknown as { rows: Array<{ group_id: string; statuses: string[] }> }).rows) {
        out.set(r.group_id, aggregateGroupStatus(r.statuses));
      }
    }
    if (tables.suspicions) {
      const result = await this.db.execute(sql`
        select s.suspicion_key as key, s.inspector_status as status
        from suspicions s join processes p on p.id = s.process_id
        where p.object_id = ${objectId} and p.active_run_id = ${runId}::uuid`);
      for (const r of (result as unknown as { rows: Array<{ key: string; status: string }> }).rows) {
        if (!out.has(r.key)) out.set(r.key, r.status);
      }
    }
    return out;
  }

  async getFile(fileId: string): Promise<FileRecord | null> {
    const [row] = await this.db
      .select({
        fileId: files.id,
        objectId: files.objectId,
        fileName: files.fileName,
        filePath: files.filePath,
        fileHash: files.fileHash,
        pdfPages: files.pdfPages,
        localStatus: files.localStatus,
        fileSplit: files.split,
        objectSplit: objects.split,
      })
      .from(files)
      .innerJoin(objects, eq(objects.id, files.objectId))
      .where(eq(files.id, fileId))
      .limit(1);
    if (!row) return null;
    const { fileSplit, objectSplit, ...rest } = row;
    return { ...rest, split: objectSplit ?? fileSplit };
  }
}
