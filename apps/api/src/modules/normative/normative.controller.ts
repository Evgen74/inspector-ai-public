/** Module 8 REST (contract: apps/api/openapi/pending/tz-modules-a.openapi.yaml). */
import { Body, Controller, Get, Param, Put, Query, Req } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { contextOf, noteAudit } from '../../common/request-context';
import { NormativeService, type ParamUpdate } from './normative.service';

type Json = Record<string, unknown>;

@Controller('normative')
export class NormativeController {
  constructor(private readonly service: NormativeService) {}

  @Get('params')
  list(@Query() query: Record<string, string>): Promise<Json> {
    return this.service.list(query);
  }

  @Put('params/:param_code')
  async update(@Param('param_code') code: string, @Body() body: ParamUpdate, @Req() req: FastifyRequest): Promise<Json> {
    const p = contextOf(req).principal;
    const result = await this.service.update(code, body ?? {}, { id: p?.userId ?? null, login: p?.login ?? null });
    const { audit_details: details, ...rest } = result;
    noteAudit(req, { action: 'PARAM_UPDATED', objectType: 'PARAM', objectId: code, details: { ...(details as Json | undefined), reason: body?.reason ?? null, matrix_version: result.matrix_version } });
    return rest;
  }

  @Get('documents')
  documents(): Json {
    return this.service.documents();
  }

  @Get('versions')
  versions(): Promise<Json> {
    return this.service.versions();
  }
}
