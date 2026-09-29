import { Controller, Get, HttpCode, Param, Post, Query } from '@nestjs/common';
import { ApiProblem } from '../../common/problem';
import { JobQueue } from '../upload/job-queue';
import { UploadJob } from '../upload/upload-job';
import type { ProcessRecord } from '../upload/process-store';

function summary(rec: ProcessRecord) {
  const { log: _log, files, steps: _steps, ...rest } = rec;
  const accepted = files.filter((f) => f.status !== 'REJECTED');
  return {
    ...rest,
    files_total: accepted.length,
    files_rejected: files.length - accepted.length,
    pages_total: accepted.reduce((n, f) => n + (f.pages ?? 0), 0),
    protocol: rec.status === 'READY' && rec.run_db_id ? { object_id: rec.object_id, run_id: rec.run_db_id } : null,
  };
}

const detail = (rec: ProcessRecord) => ({ ...summary(rec), steps: rec.steps, files: rec.files, log: rec.log });

@Controller('processes')
export class ProcessesController {
  constructor(
    private readonly job: UploadJob,
    private readonly queue: JobQueue,
  ) {}

  @Get()
  listProcesses(@Query() query: Record<string, unknown> = {}) {
    const includeArchived = query.include_archived === 'true' || query.include_archived === '1';
    const items = this.job.store
      .list()
      .filter((rec) => includeArchived || !rec.archived_at)
      .map(summary);
    return { items, total: items.length };
  }

  @Get(':process_id')
  getProcess(@Param('process_id') id: string) {
    const rec = this.job.store.get(id);
    if (!rec) throw new ApiProblem('PROCESS_NOT_FOUND', {});
    return detail(rec);
  }

  /** «Пауза»: the pipeline stops; recognised pages stay in the cache for «Продолжить». */
  @Post(':process_id/pause')
  @HttpCode(200)
  pauseProcess(@Param('process_id') id: string) {
    return detail(this.job.stop(id, 'PAUSED'));
  }

  @Post(':process_id/resume')
  @HttpCode(200)
  resumeProcess(@Param('process_id') id: string) {
    const rec = this.job.resume(id); // saved as PENDING before the queue may start it
    this.queue.enqueue(id);
    return detail(rec);
  }

  @Post(':process_id/cancel')
  @HttpCode(200)
  cancelProcess(@Param('process_id') id: string) {
    return detail(this.job.stop(id, 'CANCELLED'));
  }
}
