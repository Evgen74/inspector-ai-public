/**
 * Verification REST API (90 §3.4 G; 05 §3.15), contract in ./openapi/verification.openapi.yaml.
 * Writes require `Idempotency-Key` (UUID) and `If-Match` (row_version of the finding, or of the process for
 * claim/reopen/finalize/unfinalize; missing → 428 PRECONDITION_REQUIRED). Responses carry `ETag`.
 */
import { Body, Controller, Get, Headers, HttpCode, Param, Post, Query, Req, Res } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { contextOf, noteAudit } from '../../common/request-context';
import type { DecisionBody } from './domain/rules';
import { type Actor, QUEUE_TABS, type QueueTab, VerificationService, type WriteMeta, type WriteResult } from './verification.service';

type Json = Record<string, unknown>;

const AUDIT_BY_DECISION: Record<string, string> = {
  CONFIRMED_VIOLATION: 'FINDING_CONFIRMED',
  NEGATIVE_VERIFIED: 'FINDING_REJECTED',
  CLARIFICATION_REQUIRED: 'FINDING_CLARIFICATION_REQUESTED',
  REVERT_TO_PENDING: 'FINDING_DECISION_REVERTED',
};

const AUDIT_BY_RESOLUTION: Record<string, string> = {
  INSPECTOR_UPHELD: 'FINDING_REJECTED',
  AI_UPHELD: 'FINDING_CONFIRMED',
  KEPT_CLARIFICATION: 'FINDING_CLARIFICATION_REQUESTED',
};

function actorOf(req: FastifyRequest): Actor {
  const ctx = contextOf(req);
  return { principal: ctx.principal, scope: ctx.scope ?? null, ip: ctx.ip, userAgent: ctx.userAgent, requestId: ctx.requestId };
}

function send(reply: FastifyReply, req: FastifyRequest, result: WriteResult): Json {
  void reply.status(result.status);
  if (result.etag) void reply.header('ETag', result.etag);
  if (result.replayed) {
    void reply.header('Idempotency-Replayed', 'true');
    noteAudit(req, { details: { idempotent_replay: true } });
  }
  return result.body;
}

@Controller()
export class VerificationController {
  constructor(private readonly service: VerificationService) {}

  @Get('objects/:object_id/verification')
  objectVerification(@Param('object_id') objectId: string, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.objectVerification(objectId, actorOf(req));
  }

  @Get('processes/:process_id/verification')
  async summary(@Param('process_id') processId: string, @Req() req: FastifyRequest, @Res({ passthrough: true }) reply: FastifyReply): Promise<Json> {
    const { body, etag } = await this.service.summary(processId, actorOf(req));
    void reply.header('ETag', etag);
    return body;
  }

  @Get('processes/:process_id/findings')
  queue(@Param('process_id') processId: string, @Query('tab') tab: string | undefined, @Req() req: FastifyRequest): Promise<Json> {
    const t = (QUEUE_TABS as readonly string[]).includes(tab ?? '') ? (tab as QueueTab) : 'ALL';
    return this.service.queue(processId, t, actorOf(req));
  }

  @Get('processes/:process_id/findings/:finding_id')
  async card(
    @Param('process_id') processId: string,
    @Param('finding_id') findingId: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Json> {
    const { body, etag } = await this.service.card(processId, findingId, actorOf(req));
    void reply.header('ETag', etag);
    return body;
  }

  @Get('processes/:process_id/findings/:finding_id/history')
  history(@Param('process_id') processId: string, @Param('finding_id') findingId: string, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.history(processId, findingId, actorOf(req));
  }

  @Post('processes/:process_id/findings/:finding_id/decisions')
  async decide(
    @Param('process_id') processId: string,
    @Param('finding_id') findingId: string,
    @Body() body: DecisionBody,
    @Headers('if-match') ifMatch: string | undefined,
    @Headers('idempotency-key') idempotencyKey: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Json> {
    const decision = this.service.codes.normalizeDecision(String(body.decision ?? '').toUpperCase());
    noteAudit(req, {
      action: body.override_of_decision_id ? 'DECISION_OVERRIDE' : AUDIT_BY_DECISION[decision],
      objectType: 'FINDING',
      objectId: findingId,
      processId,
      details: { decision: body.decision, reason_code: body.reason_code ?? null },
    });
    const meta: WriteMeta = { ifMatch, idempotencyKey };
    return send(reply, req, await this.service.decide(processId, findingId, body, meta, actorOf(req)));
  }

  @Post('processes/:process_id/findings/:finding_id/decisions/validate')
  @HttpCode(200)
  validate(
    @Param('process_id') processId: string,
    @Param('finding_id') findingId: string,
    @Body() body: DecisionBody,
    @Req() req: FastifyRequest,
  ): Promise<Json> {
    noteAudit(req, { objectType: 'FINDING', objectId: findingId, processId, details: { dry_run: true } });
    return this.service.validate(processId, findingId, body, actorOf(req));
  }

  @Get('processes/:process_id/disputes')
  disputes(@Param('process_id') processId: string, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.disputes(processId, actorOf(req));
  }

  @Post('disputes/:dispute_id/resolve')
  async resolveDispute(
    @Param('dispute_id') disputeId: string,
    @Body()
    body: { resolution: string; comment?: string | null; comment_source?: string | null; basis_code?: string | null; clarify_code?: string | null; seen_fingerprint: string },
    @Headers('if-match') ifMatch: string | undefined,
    @Headers('idempotency-key') idempotencyKey: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Json> {
    noteAudit(req, { action: AUDIT_BY_RESOLUTION[body.resolution], objectType: 'FINDING', details: { dispute_id: Number(disputeId), resolution: body.resolution } });
    return send(reply, req, await this.service.resolveDispute(Number(disputeId), body, { ifMatch, idempotencyKey }, actorOf(req)));
  }

  @Post('processes/:process_id/verification/claim')
  async claim(
    @Param('process_id') processId: string,
    @Headers('if-match') ifMatch: string | undefined,
    @Headers('idempotency-key') idempotencyKey: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Json> {
    noteAudit(req, { objectType: 'PROCESS', objectId: processId, processId, details: { operation: 'verification.claim' } });
    return send(reply, req, await this.service.claim(processId, { ifMatch, idempotencyKey }, actorOf(req)));
  }

  @Post('processes/:process_id/verification/reopen')
  async reopen(
    @Param('process_id') processId: string,
    @Body() body: { comment?: string | null } | undefined,
    @Headers('if-match') ifMatch: string | undefined,
    @Headers('idempotency-key') idempotencyKey: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Json> {
    noteAudit(req, { objectType: 'PROCESS', objectId: processId, processId, details: { operation: 'verification.reopen' } });
    return send(reply, req, await this.service.reopen(processId, body ?? {}, { ifMatch, idempotencyKey }, actorOf(req)));
  }

  @Post('processes/:process_id/finalize')
  async finalize(
    @Param('process_id') processId: string,
    @Body() body: { reauth_token?: string | null },
    @Headers('if-match') ifMatch: string | undefined,
    @Headers('idempotency-key') idempotencyKey: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Json> {
    noteAudit(req, { action: 'PROTOCOL_FINALIZED', objectType: 'PROCESS', objectId: processId, processId });
    return send(reply, req, await this.service.finalize(processId, body, { ifMatch, idempotencyKey }, actorOf(req)));
  }

  @Post('processes/:process_id/unfinalize')
  async unfinalize(
    @Param('process_id') processId: string,
    @Body() body: { reason_code?: string | null; reason_text?: string | null; reauth_token?: string | null },
    @Headers('if-match') ifMatch: string | undefined,
    @Headers('idempotency-key') idempotencyKey: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Json> {
    noteAudit(req, {
      action: 'PROTOCOL_UNFINALIZED',
      objectType: 'PROCESS',
      objectId: processId,
      processId,
      details: { reason_code: body.reason_code ?? null },
    });
    return send(reply, req, await this.service.unfinalize(processId, body, { ifMatch, idempotencyKey }, actorOf(req)));
  }

  @Get('processes/:process_id/completeness')
  completeness(@Param('process_id') processId: string, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.completeness(processId, actorOf(req));
  }

  @Get('processes/:process_id/protocol')
  protocol(@Param('process_id') processId: string, @Query('version') version: string | undefined, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.protocol(processId, version ? Number(version) : undefined, actorOf(req));
  }

  @Get('processes/:process_id/rin-payload/preview')
  rinPreview(@Param('process_id') processId: string, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.rinPreview(processId, actorOf(req));
  }

  @Get('processes/:process_id/usability')
  usability(@Param('process_id') processId: string, @Req() req: FastifyRequest): Promise<Json> {
    return this.service.usability(processId, actorOf(req));
  }

  @Get('dictionaries/decision-codes')
  decisionCodes(): Json {
    return this.service.decisionCodes();
  }

  @Post('telemetry/ui-events')
  @HttpCode(202)
  telemetry(
    @Body()
    body: { session_id?: string | null; process_id?: string | null; events: Array<{ type: string; finding_id?: string | null; target?: string | null; input?: string | null; ts_client: string; payload?: Json | null }> },
    @Req() req: FastifyRequest,
  ): Promise<Json> {
    noteAudit(req, { objectType: 'PROCESS', objectId: body.process_id ?? null, processId: body.process_id ?? null, details: { ui_events: body.events.length } });
    return this.service.ingestUiEvents(body, actorOf(req));
  }

  @Get('ml/datasets/draft/items')
  datasetItems(
    @Query('process_id') processId: string | undefined,
    @Query('object_id') objectId: string | undefined,
    @Query('status') status: string | undefined,
    @Req() req: FastifyRequest,
  ): Promise<Json> {
    return this.service.datasetItems({ processId, objectId, status }, actorOf(req));
  }
}
