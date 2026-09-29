/** Read side of objects and files. `ObjectsRepository` is the DI token; tests bind an in-memory store. */
import { Injectable } from '@nestjs/common';
import { and, asc, count, eq, ilike, inArray, isNull, or, type SQL } from 'drizzle-orm';
import type { FileItemDto, ObjectDetailDto, ObjectSummaryDto, PageQuery } from '../api-types';
import { Database } from '../db/database';
import { addFileCount, emptyFileCounts, type FileCounts, toFileItem, toObjectDetail, toObjectSummary } from '../db/mappers';
import { files, objects, runs } from '../db/schema';

export interface ObjectListQuery extends PageQuery {
  q?: string;
  /** Archived objects («Архивировать») are hidden unless true. */
  includeArchived?: boolean;
}

export interface FileListQuery extends PageQuery {
  stage?: string;
  localStatus?: string;
  q?: string;
}

export abstract class ObjectsRepository {
  abstract listObjects(query: ObjectListQuery): Promise<{ items: ObjectSummaryDto[]; total: number }>;
  abstract getObject(objectId: string): Promise<ObjectDetailDto | null>;
  /** null when the object does not exist. */
  abstract listFiles(objectId: string, query: FileListQuery): Promise<{ items: FileItemDto[]; total: number } | null>;
  /** Object card field «Адрес» (entered in the upload form); false when the object does not exist. */
  abstract setAddress(objectId: string, address: string): Promise<boolean>;
}

/** `%`/`_`/`\` are literal in user search text. */
export function likePattern(q: string): string {
  return `%${q.replace(/[\\%_]/g, (c) => `\\${c}`)}%`;
}

@Injectable()
export class DrizzleObjectsRepository extends ObjectsRepository {
  constructor(private readonly database: Database) {
    super();
  }

  private get db() {
    return this.database.db;
  }

  private async fileCounts(objectIds: string[]): Promise<Map<string, FileCounts>> {
    const out = new Map<string, FileCounts>(objectIds.map((id) => [id, emptyFileCounts()]));
    if (objectIds.length === 0) return out;
    const groups = await this.db
      .select({
        objectId: files.objectId,
        manifestStage: files.manifestStage,
        docStage: files.docStage,
        localStatus: files.localStatus,
        n: count(),
      })
      .from(files)
      .where(inArray(files.objectId, objectIds))
      .groupBy(files.objectId, files.manifestStage, files.docStage, files.localStatus);
    for (const g of groups) {
      const counts = out.get(g.objectId);
      if (counts) addFileCount(counts, g.docStage ?? g.manifestStage, g.localStatus, Number(g.n)); // resolved stage wins over the raw manifest one
    }
    return out;
  }

  async listObjects(query: ObjectListQuery): Promise<{ items: ObjectSummaryDto[]; total: number }> {
    const search = query.q ? or(ilike(objects.id, likePattern(query.q)), ilike(objects.name, likePattern(query.q))) : undefined;
    const where = query.includeArchived ? search : and(search, isNull(objects.archivedAt));
    const [totalRow] = await this.db.select({ n: count() }).from(objects).where(where);
    const rows = await this.db
      .select({ object: objects, batchRunId: runs.batchRunId, importedAt: runs.importedAt })
      .from(objects)
      .leftJoin(runs, eq(objects.lastRunId, runs.id))
      .where(where)
      .orderBy(asc(objects.id))
      .limit(query.pageSize)
      .offset((query.page - 1) * query.pageSize);
    const counts = await this.fileCounts(rows.map((r) => r.object.id));
    return {
      total: Number(totalRow?.n ?? 0),
      items: rows.map((r) =>
        toObjectSummary(
          r.object,
          counts.get(r.object.id) ?? emptyFileCounts(),
          r.batchRunId && r.importedAt ? { batchRunId: r.batchRunId, importedAt: r.importedAt } : null,
        ),
      ),
    };
  }

  async getObject(objectId: string): Promise<ObjectDetailDto | null> {
    const [row] = await this.db
      .select({ object: objects, batchRunId: runs.batchRunId, importedAt: runs.importedAt })
      .from(objects)
      .leftJoin(runs, eq(objects.lastRunId, runs.id))
      .where(eq(objects.id, objectId));
    if (!row) return null;
    const counts = await this.fileCounts([objectId]);
    return toObjectDetail(
      row.object,
      counts.get(objectId) ?? emptyFileCounts(),
      row.batchRunId && row.importedAt ? { batchRunId: row.batchRunId, importedAt: row.importedAt } : null,
    );
  }

  async setAddress(objectId: string, address: string): Promise<boolean> {
    const rows = await this.db
      .update(objects)
      .set({ address, updatedAt: new Date() })
      .where(eq(objects.id, objectId))
      .returning({ id: objects.id });
    return rows.length > 0;
  }

  async listFiles(objectId: string, query: FileListQuery): Promise<{ items: FileItemDto[]; total: number } | null> {
    const [exists] = await this.db.select({ id: objects.id }).from(objects).where(eq(objects.id, objectId));
    if (!exists) return null;
    const conditions: SQL[] = [eq(files.objectId, objectId)];
    if (query.stage) conditions.push(eq(files.manifestStage, query.stage));
    if (query.localStatus) conditions.push(eq(files.localStatus, query.localStatus));
    if (query.q) {
      const p = likePattern(query.q);
      conditions.push(or(ilike(files.id, p), ilike(files.fileName, p), ilike(files.filePath, p)) as SQL);
    }
    const where = and(...conditions);
    const [totalRow] = await this.db.select({ n: count() }).from(files).where(where);
    const rows = await this.db
      .select()
      .from(files)
      .where(where)
      .orderBy(asc(files.id))
      .limit(query.pageSize)
      .offset((query.page - 1) * query.pageSize);
    return { total: Number(totalRow?.n ?? 0), items: rows.map(toFileItem) };
  }
}
