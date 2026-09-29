import { Body, Controller, Get, Post, Req, Res } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { contextOf, noteAudit } from '../../common/request-context';
import { Database } from '../../db/database';
import { objectAssignments } from '../auth/auth.schema';
import type { MultipartBody } from './multipart';
import { type UploadResultDto, UploadService } from './upload.service';

@Controller('documents')
export class UploadController {
  constructor(
    private readonly uploads: UploadService,
    private readonly database: Database,
  ) {}

  @Get('upload/limits')
  getUploadLimits() {
    return this.uploads.limits();
  }

  /** Multipart: `files` (repeatable), optional `registry`, `object_name`, `address`. 202 + process_id. */
  @Post('upload')
  async upload(
    @Body() body: MultipartBody,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<UploadResultDto> {
    const result = this.uploads.create(body);
    // The uploader is recorded as assigned to the new object (informational: every permission has scope ALL).
    const principal = contextOf(req).principal;
    if (principal) {
      await this.database.db
        .insert(objectAssignments)
        .values({ objectId: result.object_id, userId: principal.userId, assignedBy: principal.userId })
        .onConflictDoNothing();
    }
    noteAudit(req, {
      objectType: 'PROCESS',
      objectId: result.process_id,
      details: { object_id: result.object_id, accepted: result.accepted.length, rejected: result.rejected.length },
    });
    void reply.status(202);
    return result;
  }
}
