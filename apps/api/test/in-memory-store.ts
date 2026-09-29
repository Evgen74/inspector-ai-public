/**
 * In-memory implementation of both repositories for DB-free tests. It stores the same row shapes as the
 * Drizzle schema and reuses the same row → DTO mappers, so controllers and services see identical behaviour.
 */
import type { BatchRunDto, FileItemDto, ObjectDetailDto, ObjectSummaryDto, PageQuery } from '../src/api-types';
import {
  BatchRunsRepository,
  type FileIdConflict,
  FileIdConflictError,
  type ImportPlan,
} from '../src/batch-import/batch-runs.repository';
import { uuidv7 } from '../src/common/ids';
import { addFileCount, emptyFileCounts, toBatchRun, toFileItem, toObjectDetail, toObjectSummary } from '../src/db/mappers';
import type { FileRow, ObjectRow, RunRow } from '../src/db/schema';
import { type ArchiveOutcome, ArchiveRepository } from '../src/modules/archive/archive.repository';
import { type FileListQuery, type ObjectListQuery, ObjectsRepository } from '../src/objects/objects.repository';

function page<T>(rows: T[], q: PageQuery): T[] {
  return rows.slice((q.page - 1) * q.pageSize, q.page * q.pageSize);
}

function contains(value: string | null | undefined, q: string): boolean {
  return (value ?? '').toLowerCase().includes(q.toLowerCase());
}

export class InMemoryStore {
  readonly runs = new Map<string, RunRow>();
  readonly objects = new Map<string, ObjectRow>();
  readonly files = new Map<string, FileRow>();
  /** Simulate an unreachable database for every repository call. */
  failWith: Error | null = null;

  private check(): void {
    if (this.failWith) throw this.failWith;
  }

  private counts(objectId: string) {
    const counts = emptyFileCounts();
    for (const f of this.files.values()) {
      if (f.objectId === objectId) addFileCount(counts, f.manifestStage, f.localStatus, 1);
    }
    return counts;
  }

  private lastRun(row: ObjectRow) {
    const run = row.lastRunId ? [...this.runs.values()].find((r) => r.id === row.lastRunId) : undefined;
    return run ? { batchRunId: run.batchRunId, importedAt: run.importedAt } : null;
  }

  readonly objectsRepository: ObjectsRepository = (() => {
    const store = this;
    return new (class extends ObjectsRepository {
      async listObjects(query: ObjectListQuery): Promise<{ items: ObjectSummaryDto[]; total: number }> {
        store.check();
        const rows = [...store.objects.values()]
          .filter((o) => !query.q || contains(o.id, query.q) || contains(o.name, query.q))
          .filter((o) => query.includeArchived || !o.archivedAt)
          .sort((a, b) => (a.id < b.id ? -1 : 1));
        return {
          total: rows.length,
          items: page(rows, query).map((o) => toObjectSummary(o, store.counts(o.id), store.lastRun(o))),
        };
      }

      async setAddress(objectId: string, address: string): Promise<boolean> {
        store.check();
        const o = store.objects.get(objectId);
        if (o) o.address = address;
        return Boolean(o);
      }

      async getObject(objectId: string): Promise<ObjectDetailDto | null> {
        store.check();
        const o = store.objects.get(objectId);
        return o ? toObjectDetail(o, store.counts(o.id), store.lastRun(o)) : null;
      }

      async listFiles(objectId: string, query: FileListQuery): Promise<{ items: FileItemDto[]; total: number } | null> {
        store.check();
        if (!store.objects.has(objectId)) return null;
        const rows = [...store.files.values()]
          .filter((f) => f.objectId === objectId)
          .filter((f) => !query.stage || f.manifestStage === query.stage)
          .filter((f) => !query.localStatus || f.localStatus === query.localStatus)
          .filter((f) => !query.q || contains(f.id, query.q) || contains(f.fileName, query.q) || contains(f.filePath, query.q))
          .sort((a, b) => (a.id < b.id ? -1 : 1));
        return { total: rows.length, items: page(rows, query).map(toFileItem) };
      }
    })();
  })();

  readonly batchRunsRepository: BatchRunsRepository = (() => {
    const store = this;
    return new (class extends BatchRunsRepository {
      async saveImport(plan: ImportPlan): Promise<{ run: BatchRunDto; created: boolean }> {
        store.check();
        const conflicts: FileIdConflict[] = [];
        for (const f of plan.files) {
          const existing = store.files.get(f.id);
          if (existing && (existing.fileHash !== f.fileHash || existing.objectId !== f.objectId)) {
            conflicts.push({
              file_id: f.id,
              stored_sha256: existing.fileHash,
              new_sha256: f.fileHash,
              stored_object_id: existing.objectId,
              new_object_id: f.objectId,
            });
          }
        }
        if (conflicts.length) throw new FileIdConflictError(conflicts);
        const now = new Date();
        const previous = [...store.runs.values()].find((r) => r.batchRunId === plan.run.batchRunId);
        const run = {
          ...(previous ?? { id: uuidv7(), importedAt: now }),
          ...plan.run,
          updatedAt: now,
        } as RunRow;
        store.runs.set(run.id, run);
        for (const o of plan.objects) {
          const prev = store.objects.get(o.id);
          store.objects.set(o.id, {
            address: null,
            customer: null,
            contractor: null,
            permitNumber: null,
            objectGroupId: null,
            indicatorColor: 'NONE',
            indicatorReasons: null,
            indicatorUpdatedAt: null,
            archivedAt: null,
            createdAt: now,
            ...prev,
            id: o.id,
            name: o.name ?? prev?.name ?? null,
            split: o.split,
            inputManifestHash: o.inputManifestHash,
            scenario: o.scenario ?? prev?.scenario ?? null,
            lastRunId: run.id,
            updatedAt: now,
          });
        }
        for (const f of plan.files) {
          const prev = store.files.get(f.id);
          store.files.set(f.id, {
            discipline: null,
            documentCode: null,
            revision: null,
            approvalStatus: null,
            approvalDate: null,
            predecessorId: null,
            createdAt: now,
            uploadedAt: now,
            ...prev,
            ...(f as Partial<FileRow>),
            docStage: f.docStage ?? prev?.docStage ?? null,
            lastRunId: run.id,
            updatedAt: now,
          } as FileRow);
        }
        return { run: toBatchRun(run), created: !previous };
      }

      async listRuns(query: PageQuery & { includeArchived?: boolean }): Promise<{ items: BatchRunDto[]; total: number }> {
        store.check();
        const rows = [...store.runs.values()].filter((r) => query.includeArchived || !r.archivedAt).sort((a, b) => b.importedAt.getTime() - a.importedAt.getTime());
        return { total: rows.length, items: page(rows, query).map(toBatchRun) };
      }
    })();
  })();
  readonly archiveRepository: ArchiveRepository = (() => {
    const store = this;
    return new (class extends ArchiveRepository {
      async setObjectArchived(objectId: string, archived: boolean): Promise<ArchiveOutcome> {
        store.check();
        const o = store.objects.get(objectId);
        if (!o) return { found: false, archivedAt: null };
        o.archivedAt = archived ? new Date() : null;
        return { found: true, archivedAt: o.archivedAt };
      }

      async setRunArchived(batchRunId: string, archived: boolean): Promise<ArchiveOutcome> {
        store.check();
        const r = [...store.runs.values()].find((x) => x.batchRunId === batchRunId);
        if (!r) return { found: false, archivedAt: null };
        r.archivedAt = archived ? new Date() : null;
        return { found: true, archivedAt: r.archivedAt };
      }
    })();
  })();
}
