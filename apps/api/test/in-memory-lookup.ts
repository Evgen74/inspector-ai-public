/** CatalogLookup over the InMemoryStore maps (same semantics as DrizzleCatalogLookup). */
import {
  CatalogLookup,
  type DecisionMap,
  type FileRecord,
  type ObjectRecord,
  type RunRecord,
} from '../src/modules/shared/lookup.repository';
import type { InMemoryStore } from './in-memory-store';

/** Decisions per `${objectId}|${runId}` (what AG-05's verification writes into checks). */
export const inMemoryDecisions = new Map<string, DecisionMap>();

export function inMemoryLookup(store: InMemoryStore): CatalogLookup {
  const toRun = (r: { id: string; batchRunId: string; manifestRef: string; startedAt: Date; finishedAt: Date | null; importedAt: Date }): RunRecord => ({
    id: r.id,
    batchRunId: r.batchRunId,
    manifestRef: r.manifestRef,
    startedAt: r.startedAt,
    finishedAt: r.finishedAt,
    importedAt: r.importedAt,
  });
  const toObject = (id: string): ObjectRecord | null => {
    const o = store.objects.get(id);
    if (!o) return null;
    const filesTotal = [...store.files.values()].filter((f) => f.objectId === id).length;
    return { objectId: o.id, name: o.name, split: o.split, filesTotal, updatedAt: o.updatedAt };
  };
  class Lookup extends CatalogLookup {
    async runsForObject(objectId: string): Promise<RunRecord[]> {
      if (store.failWith) throw store.failWith;
      return [...store.runs.values()]
        .filter((r) => !r.archivedAt)
        .filter((r) => ((r.manifest as { objects?: Array<{ object_id: string }> }).objects ?? []).some((o) => o.object_id === objectId))
        .sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime() || b.importedAt.getTime() - a.importedAt.getTime())
        .map(toRun);
    }
    async getRun(runId: string): Promise<RunRecord | null> {
      const r = store.runs.get(runId) ?? [...store.runs.values()].find((x) => x.id === runId);
      return r ? toRun(r) : null;
    }
    async getObject(objectId: string): Promise<ObjectRecord | null> {
      if (store.failWith) throw store.failWith;
      return toObject(objectId);
    }
    async listObjects(includeArchived = false): Promise<ObjectRecord[]> {
      if (store.failWith) throw store.failWith;
      return [...store.objects.keys()]
        .filter((id) => includeArchived || !store.objects.get(id)?.archivedAt)
        .sort()
        .map((id) => toObject(id)!);
    }
    async decisionsForRun(objectId: string, runId: string): Promise<DecisionMap> {
      return new Map(inMemoryDecisions.get(`${objectId}|${runId}`) ?? []);
    }
    async getFile(fileId: string): Promise<FileRecord | null> {
      const f = store.files.get(fileId);
      if (!f) return null;
      const o = store.objects.get(f.objectId);
      return {
        fileId: f.id,
        objectId: f.objectId,
        fileName: f.fileName,
        filePath: f.filePath,
        fileHash: f.fileHash,
        pdfPages: f.pdfPages,
        localStatus: f.localStatus,
        split: o?.split ?? f.split,
      };
    }
  }
  return new Lookup();
}
