/** GET /audit (audit.read; 90 §3.4 K). OWN scope sees only the user's own actions. */
import { Controller, Get, Query, Req } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import type { Page } from '../../api-types';
import { optionalString, parsePage } from '../../common/pagination';
import { contextOf } from '../../common/request-context';
import { requirePrincipal } from '../auth/auth.controller';
import { AuditRepository } from './audit.repository';
import type { AuditRow } from './audit.schema';
import { AuditService } from './audit.service';

export interface AuditEntryDto {
  id: number;
  timestamp: string;
  user_id: string | null;
  actor_type: string;
  actor_login: string | null;
  actor_role: string | null;
  action: string;
  action_label: string;
  category: string;
  result: string;
  object_type: string | null;
  object_id: string | null;
  construction_object_id: string | null;
  process_id: string | null;
  protocol_version: number | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  user_agent: string | null;
  request_id: string | null;
  session_ref: string | null;
  http_method: string | null;
  route: string | null;
  status_code: number | null;
  duration_ms: number | null;
  retention_class: string;
}

function dateParam(value: unknown): Date | undefined {
  const s = optionalString(value);
  return s ? new Date(s) : undefined;
}

@Controller('audit')
export class AuditController {
  constructor(
    private readonly repository: AuditRepository,
    private readonly audit: AuditService,
  ) {}

  toDto(row: AuditRow): AuditEntryDto {
    return {
      id: row.id,
      timestamp: row.timestamp.toISOString(),
      user_id: row.userId,
      actor_type: row.actorType,
      actor_login: row.actorLogin,
      actor_role: row.actorRole,
      action: row.action,
      action_label: this.audit.label(row.action),
      category: row.category,
      result: row.result,
      object_type: row.objectType,
      object_id: row.objectId,
      construction_object_id: row.constructionObjectId,
      process_id: row.processId,
      protocol_version: row.protocolVersion,
      details: (row.details ?? {}) as Record<string, unknown>,
      ip_address: row.ipAddress,
      user_agent: row.userAgent,
      request_id: row.requestId,
      session_ref: row.sessionRef,
      http_method: row.httpMethod,
      route: row.route,
      status_code: row.statusCode,
      duration_ms: row.durationMs,
      retention_class: row.retentionClass,
    };
  }

  @Get()
  async listAudit(@Query() query: Record<string, unknown>, @Req() req: FastifyRequest): Promise<Page<AuditEntryDto>> {
    const principal = requirePrincipal(req);
    const { page, pageSize } = parsePage(query);
    const own = contextOf(req).scope === 'OWN';
    const { items, total } = await this.repository.list({
      page,
      pageSize,
      userId: own ? principal.userId : optionalString(query.user_id),
      action: optionalString(query.action),
      category: optionalString(query.category),
      objectType: optionalString(query.object_type),
      objectId: optionalString(query.object_id),
      constructionObjectId: optionalString(query.construction_object_id),
      processId: optionalString(query.process_id),
      result: optionalString(query.result),
      requestId: optionalString(query.request_id),
      from: dateParam(query.from),
      to: dateParam(query.to),
    });
    return { items: items.map((r) => this.toDto(r)), total, page, page_size: pageSize };
  }
}
