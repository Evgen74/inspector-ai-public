/** Write side of the batch import: one transaction per run directory. */
import { Injectable } from '@nestjs/common';
import { count, desc, getTableColumns, inArray, isNull, sql } from 'drizzle-orm';
import type { BatchRunDto, PageQuery } from '../api-types';
import { uuidv7 } from '../common/ids';
import { Database } from '../db/database';
import { toBatchRun } from '../db/mappers';
import { files, type NewFileRow, type NewRunRow, objects, runs } from '../db/schema';

export interface ImportPlanObject {
  id: string;
  name: string | null;
  split: string;
  inputManifestHash: string;
  scenario: string | null;
}

export type ImportPlanFile = Omit<NewFileRow, 'lastRunId' | 'createdAt' | 'updatedAt' | 'uploadedAt'> & {
  id: string;
  objectId: string;
  fileHash: string;
};

export interface ImportPlan {
  run: Omit<NewRunRow, 'id' | 'importedAt' | 'updatedAt'>;
  objects: ImportPlanObject[];
  files: ImportPlanFile[];
}

export interface FileIdConflict {
  file_id: string;
  stored_sha256: string;
  new_sha256: string;
  stored_object_id: string;
  new_object_id: string;
}

/** Same file_id with another sha256 or object (90 §3.3.2): the import is refused as a whole. */
export class FileIdConflictError extends Error {
  constructor(readonly conflicts: FileIdConflict[]) {
    super(`file id conflicts: ${conflicts.map((c) => c.file_id).join(', ')}`);
    this.name = 'FileIdConflictError';
  }
}

export abstract class BatchRunsRepository {
  abstract saveImport(plan: ImportPlan): Promise<{ run: BatchRunDto; created: boolean }>;
  abstract listRuns(query: PageQuery & { includeArchived?: boolean }): Promise<{ items: BatchRunDto[]; total: number }>;
}

const FILES_CHUNK = 500;

@Injectable()
export class DrizzleBatchRunsRepository extends BatchRunsRepository {
  constructor(private readonly database: Database) {
    super();
  }

  async saveImport(plan: ImportPlan): Promise<{ run: BatchRunDto; created: boolean }> {
    return this.database.db.transaction(async (tx) => {
      const byId = new Map(plan.files.map((f) => [f.id, f]));
      const ids = [...byId.keys()];
      const conflicts: FileIdConflict[] = [];
      for (let i = 0; i < ids.length; i += FILES_CHUNK) {
        const existing = await tx
          .select({ id: files.id, fileHash: files.fileHash, objectId: files.objectId })
          .from(files)
          .where(inArray(files.id, ids.slice(i, i + FILES_CHUNK)))
          .for('update');
        for (const row of existing) {
          const incoming = byId.get(row.id);
          if (incoming && (incoming.fileHash !== row.fileHash || incoming.objectId !== row.objectId)) {
            conflicts.push({
              file_id: row.id,
              stored_sha256: row.fileHash,
              new_sha256: incoming.fileHash,
              stored_object_id: row.objectId,
              new_object_id: incoming.objectId,
            });
          }
        }
      }
      if (conflicts.length > 0) throw new FileIdConflictError(conflicts);

      const now = new Date();
      const { batchRunId: _ignored, ...mutableRun } = plan.run;
      const [runRow] = await tx
        .insert(runs)
        .values({ id: uuidv7(), ...plan.run, importedAt: now, updatedAt: now })
        .onConflictDoUpdate({ target: runs.batchRunId, set: { ...mutableRun, updatedAt: now } })
        .returning({ ...getTableColumns(runs), inserted: sql<boolean>`(xmax = 0)` });
      if (!runRow) throw new Error('run upsert returned no row');
      const { inserted, ...run } = runRow;

      if (plan.objects.length > 0) {
        await tx
          .insert(objects)
          .values(plan.objects.map((o) => ({ ...o, lastRunId: run.id, createdAt: now, updatedAt: now })))
          .onConflictDoUpdate({
            target: objects.id,
            set: {
              name: sql`COALESCE(excluded.name, ${objects.name})`,
              split: sql`excluded.split`,
              inputManifestHash: sql`excluded.input_manifest_hash`,
              scenario: sql`COALESCE(excluded.scenario, ${objects.scenario})`,
              lastRunId: sql`excluded.last_run_id`,
              updatedAt: now,
            },
          });
      }

      for (let i = 0; i < plan.files.length; i += FILES_CHUNK) {
        const chunk = plan.files.slice(i, i + FILES_CHUNK);
        await tx
          .insert(files)
          .values(chunk.map((f) => ({ ...f, lastRunId: run.id, uploadedAt: now, createdAt: now, updatedAt: now })))
          .onConflictDoUpdate({
            target: files.id,
            // Identity (id, object_id, file_hash) is never updated; a DB trigger enforces it too.
            set: {
              docStage: sql`COALESCE(excluded.doc_stage, ${files.docStage})`,
              filePath: sql`excluded.file_path`,
              fileName: sql`excluded.file_name`,
              ext: sql`excluded.ext`,
              sizeBytes: sql`excluded.size_bytes`,
              manifestStage: sql`excluded.manifest_stage`,
              manifestSection: sql`excluded.manifest_section`,
              datasetRole: sql`excluded.dataset_role`,
              split: sql`excluded.split`,
              duplicateGroup: sql`excluded.duplicate_group`,
              annotationStatus: sql`excluded.annotation_status`,
              pdfPages: sql`excluded.pdf_pages`,
              localStatus: sql`excluded.local_status`,
              sha256Verified: sql`excluded.sha256_verified`,
              lastRunId: sql`excluded.last_run_id`,
              updatedAt: now,
            },
          });
      }
      return { run: toBatchRun(run), created: Boolean(inserted) };
    });
  }

  async listRuns(query: PageQuery & { includeArchived?: boolean }): Promise<{ items: BatchRunDto[]; total: number }> {
    const db = this.database.db;
    const where = query.includeArchived ? undefined : isNull(runs.archivedAt);
    const [totalRow] = await db.select({ n: count() }).from(runs).where(where);
    const rows = await db
      .select()
      .from(runs)
      .where(where)
      .orderBy(desc(runs.importedAt), desc(runs.id))
      .limit(query.pageSize)
      .offset((query.page - 1) * query.pageSize);
    return { total: Number(totalRow?.n ?? 0), items: rows.map(toBatchRun) };
  }
}
