/** «Архивировать»: sets/clears `archived_at` on objects and imported runs. `ArchiveRepository` is the DI token. */
import { Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Database } from '../../db/database';
import { objects, runs } from '../../db/schema';

export interface ArchiveOutcome {
  found: boolean;
  archivedAt: Date | null;
}

export abstract class ArchiveRepository {
  abstract setObjectArchived(objectId: string, archived: boolean): Promise<ArchiveOutcome>;
  /** `batchRunId` is the run's own id from run_manifest.json (the path parameter of the API). */
  abstract setRunArchived(batchRunId: string, archived: boolean): Promise<ArchiveOutcome>;
}

@Injectable()
export class DrizzleArchiveRepository extends ArchiveRepository {
  constructor(private readonly database: Database) {
    super();
  }

  async setObjectArchived(objectId: string, archived: boolean): Promise<ArchiveOutcome> {
    const stamp = archived ? new Date() : null;
    const rows = await this.database.db
      .update(objects)
      .set({ archivedAt: stamp })
      .where(eq(objects.id, objectId))
      .returning({ id: objects.id });
    return { found: rows.length > 0, archivedAt: rows.length > 0 ? stamp : null };
  }

  async setRunArchived(batchRunId: string, archived: boolean): Promise<ArchiveOutcome> {
    const stamp = archived ? new Date() : null;
    const rows = await this.database.db
      .update(runs)
      .set({ archivedAt: stamp })
      .where(eq(runs.batchRunId, batchRunId))
      .returning({ id: runs.id });
    return { found: rows.length > 0, archivedAt: rows.length > 0 ? stamp : null };
  }
}
