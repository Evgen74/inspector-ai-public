import { Body, Controller, Get, Post, Query, Req, Res } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import type { BatchRunDto, Page } from '../api-types';
import { parsePage } from '../common/pagination';
import { noteAudit } from '../common/request-context';
import { type BatchRunImportV2ResultDto, RunImportService } from '../modules/import/run-import.service';
import { BatchRunsRepository } from './batch-runs.repository';

@Controller('admin/batch-runs')
export class BatchRunsController {
  constructor(
    private readonly importer: RunImportService,
    private readonly repository: BatchRunsRepository,
  ) {}

  @Get()
  async listBatchRuns(@Query() query: Record<string, unknown>): Promise<Page<BatchRunDto>> {
    const { page, pageSize } = parsePage(query);
    const { items, total } = await this.repository.listRuns({
      page,
      pageSize,
      includeArchived: query.include_archived === 'true' || query.include_archived === '1',
    });
    return { items, total, page, page_size: pageSize };
  }

  /**
   * 201 on the first import of a run, 200 on a repeated (idempotent) import. Inventory (runs, objects, files) and,
   * when the run has artifacts.json, the run artifacts (import v2, AG-00: processes, protocols, checks, evidence,
   * suspicions, submissions).
   */
  @Post('import')
  async importBatchRun(
    @Body() body: { run_dir: string },
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<BatchRunImportV2ResultDto> {
    noteAudit(req, { objectType: 'BATCH_RUN', objectId: body.run_dir, details: { run_dir: body.run_dir } });
    const result = await this.importer.importRunDir(body.run_dir);
    noteAudit(req, {
      objectId: result.run.batch_run_id,
      details: {
        created: result.created,
        objects: result.objects.length,
        files: result.files_imported,
        processes: result.artifacts?.objects.map((o) => o.process_id) ?? [],
        checks: result.artifacts?.objects.reduce((n, o) => n + o.checks.total, 0) ?? 0,
      },
    });
    void reply.status(result.created ? 201 : 200);
    return result;
  }
}
