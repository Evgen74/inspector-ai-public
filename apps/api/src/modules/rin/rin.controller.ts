/** Module 6 REST: manual send, delivery status, and the mock РиН endpoint (contract: pending/tz-modules-a.openapi.yaml). */
import { Body, Controller, Get, HttpCode, Param, Post, Req } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { ApiProblem } from '../../common/problem';
import { validationProblem } from '../shared/tz-validation';
import { contextOf, noteAudit } from '../../common/request-context';
import type { Actor } from '../verification/verification.service';
import { mockRinReceive, RinService } from './rin.service';

type Json = Record<string, unknown>;

function actorOf(req: FastifyRequest): Actor {
  const ctx = contextOf(req);
  return { principal: ctx.principal, scope: ctx.scope ?? null, ip: ctx.ip, userAgent: ctx.userAgent, requestId: ctx.requestId };
}

@Controller()
export class RinController {
  constructor(private readonly service: RinService) {}

  @Post('processes/:process_id/rin/send')
  @HttpCode(202)
  async send(@Param('process_id') processId: string, @Body() body: { simulate_failures?: number; force?: boolean } | undefined, @Req() req: FastifyRequest): Promise<Json> {
    const actor = actorOf(req);
    const simulate = this.simulationAllowed() ? body?.simulate_failures : 0;
    const result = await this.service.send(processId, { trigger: 'MANUAL', simulateFailures: simulate, force: body?.force === true, userId: actor.principal?.userId ?? null }, actor);
    noteAudit(req, { processId, objectType: 'PROCESS', objectId: processId, details: { sync_status: result.status, attempts: result.attempts, violations: result.violations } });
    return result;
  }

  private simulationAllowed(): boolean {
    return process.env.INSPECTOR_APP_ENV !== 'prod';
  }

  @Get('processes/:process_id/rin')
  status(@Param('process_id') processId: string, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.status(processId, actorOf(req));
  }

  @Get('objects/:object_id/rin-sync')
  byObject(@Param('object_id') objectId: string): Promise<Json> {
    return this.service.byObject(objectId);
  }

  /** Mock ИАИС «РиН»: the same handler the in-process transport calls. `simulate_fail: true` answers 503. */
  @Post('mock-rin/inspection/:process_id')
  @HttpCode(200)
  mock(@Param('process_id') processId: string, @Body() body: Json | undefined): Json {
    const payload = body ?? {};
    const r = mockRinReceive(processId, payload, 1, payload.simulate_fail === true ? 1 : 0);
    if (r.httpStatus === 503) throw new ApiProblem('SERVICE_UNAVAILABLE', { retry_after_s: 1 });
    if (!r.ok) throw validationProblem('RIN_REJECTED', 'РиН отклонил пакет', r.detail);
    return { status: 'ACCEPTED', external_id: r.externalId, received_violations: (payload.violations as unknown[]).length, detail: r.detail };
  }
}
