/**
 * «Архивировать» (M2 backlog item 6): hides fixture and stale objects, imported runs and upload processes from
 * lists and the dashboard (they stay in the database and can be restored with `archived: false`).
 * Admin action: permission `batch.import`; every call is written to the audit log by the global interceptor.
 */
import { Body, Controller, HttpCode, Param, Post, Req } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { ApiProblem } from '../../common/problem';
import { noteAudit } from '../../common/request-context';
import { UploadJob } from '../upload/upload-job';
import { ArchiveRepository } from './archive.repository';

export interface ArchiveResultDto {
  kind: 'OBJECT' | 'BATCH_RUN' | 'PROCESS';
  id: string;
  archived: boolean;
  archived_at: string | null;
}

function wanted(body: { archived?: unknown } | undefined): boolean {
  return body?.archived !== false; // the body is optional; the request guard already checked the type
}

@Controller()
export class ArchiveController {
  constructor(
    private readonly repository: ArchiveRepository,
    private readonly job: UploadJob,
  ) {}

  @HttpCode(200)
  @Post('admin/objects/:object_id/archive')
  async archiveObject(
    @Param('object_id') objectId: string,
    @Body() body: { archived?: boolean } | undefined,
    @Req() req: FastifyRequest,
  ): Promise<ArchiveResultDto> {
    const archived = wanted(body);
    noteAudit(req, { objectType: 'OBJECT', objectId, details: { archived } });
    const out = await this.repository.setObjectArchived(objectId, archived);
    if (!out.found) throw new ApiProblem('NOT_FOUND', { object_id: objectId });
    return { kind: 'OBJECT', id: objectId, archived, archived_at: out.archivedAt?.toISOString() ?? null };
  }

  @HttpCode(200)
  @Post('admin/batch-runs/:batch_run_id/archive')
  async archiveRun(
    @Param('batch_run_id') batchRunId: string,
    @Body() body: { archived?: boolean } | undefined,
    @Req() req: FastifyRequest,
  ): Promise<ArchiveResultDto> {
    const archived = wanted(body);
    noteAudit(req, { objectType: 'BATCH_RUN', objectId: batchRunId, details: { archived } });
    const out = await this.repository.setRunArchived(batchRunId, archived);
    if (!out.found) throw new ApiProblem('NOT_FOUND', { batch_run_id: batchRunId });
    return { kind: 'BATCH_RUN', id: batchRunId, archived, archived_at: out.archivedAt?.toISOString() ?? null };
  }

  @HttpCode(200)
  @Post('processes/:process_id/archive')
  archiveProcess(
    @Param('process_id') processId: string,
    @Body() body: { archived?: boolean } | undefined,
    @Req() req: FastifyRequest,
  ): ArchiveResultDto {
    const archived = wanted(body);
    const rec = this.job.store.get(processId);
    if (!rec) throw new ApiProblem('PROCESS_NOT_FOUND', {});
    noteAudit(req, { objectType: 'PROCESS', objectId: processId, details: { archived } });
    const at = archived ? new Date().toISOString() : null;
    rec.archived_at = at;
    this.job.store.save(rec);
    return { kind: 'PROCESS', id: processId, archived, archived_at: at };
  }
}
