/**
 * Audit writer (ТЗ §7 row 9, §12.4; 09 §3.4.1). Two paths:
 *
 * 1. **Domain audit** — `record(event, { executor: tx })` inside the transaction of the change (verification
 *    decisions, finalization, …), so the row and the change commit or roll back together. Actor and request
 *    fields are taken from the current request context when omitted.
 * 2. **Mutation audit** — `recordRequest()` runs from the Fastify `onSend` hook for every POST/PUT/PATCH/DELETE
 *    matched to an OpenAPI operation (success or failure) and for every 403 on a read. The action is what the
 *    handler noted (`noteAudit`), else the operation's `x-audit-action`, else HTTP_<METHOD>. It is awaited before
 *    the response leaves, so a client that got a response can already read its row. A successful request whose
 *    handler wrote domain rows itself gets no extra generic row.
 *
 * Category and retention class come from enums.yaml AuditAction (`category`, `retention` attributes).
 */
import { isIP } from 'node:net';
import { Inject, Injectable } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { PinoLogger } from 'nestjs-pino';
import { contextOf, currentContext, type RequestContext } from '../../common/request-context';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { loadEnums } from '../../contracts/contracts';
import { OpenApiService } from '../../openapi/openapi.service';
import { type AuditExecutor, AuditRepository } from './audit.repository';
import type { NewAuditRow } from './audit.schema';

export type AuditResult = 'SUCCESS' | 'FAILURE' | 'DENIED';

export interface AuditEvent {
  /** AuditAction */
  action: string;
  result?: AuditResult;
  /** AuditObjectType */
  objectType?: string | null;
  objectId?: string | null;
  constructionObjectId?: string | null;
  processId?: string | null;
  protocolVersion?: number | null;
  details?: Record<string, unknown>;
  /** Defaults: the principal of the current request, else SYSTEM (outside a request) or ANONYMOUS. */
  actor?: { type?: string; userId?: string | null; login?: string | null; roles?: string[] };
  request?: {
    requestId?: string | null;
    ip?: string | null;
    userAgent?: string | null;
    sessionRef?: string | null;
    method?: string | null;
    route?: string | null;
    statusCode?: number | null;
    durationMs?: number | null;
  };
}

interface ActionMeta {
  category: string;
  retention: string;
  label_ru: string;
}

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
/** Path parameters that identify the affected entity, in priority order (AuditObjectType). */
const PARAM_OBJECT_TYPES: Array<[string, string]> = [
  ['finding_id', 'FINDING'],
  ['suspicion_id', 'SUSPICION'],
  ['protocol_id', 'PROTOCOL'],
  ['process_id', 'PROCESS'],
  ['file_id', 'FILE'],
  ['user_id', 'USER'],
  ['object_id', 'OBJECT'],
];

function resultOf(status: number): AuditResult {
  if (status < 400) return 'SUCCESS';
  if (status === 401 || status === 403 || status === 423 || status === 429) return 'DENIED';
  return 'FAILURE';
}

function pathOf(url: string): string {
  const q = url.indexOf('?');
  return q === -1 ? url : url.slice(0, q);
}

@Injectable()
export class AuditService {
  private readonly actions: Map<string, ActionMeta>;

  constructor(
    @Inject(APP_CONFIG) config: AppConfig,
    private readonly repository: AuditRepository,
    private readonly openapi: OpenApiService,
    private readonly logger: PinoLogger,
  ) {
    this.logger.setContext(AuditService.name);
    const def = loadEnums(config.contractsDir).AuditAction;
    if (!def) throw new Error('enum AuditAction is not in packages/contracts/enums.yaml');
    this.actions = new Map(
      def.values.map((v) => [
        v.code,
        { category: String(v.category ?? 'BUSINESS'), retention: String(v.retention ?? 'STANDARD'), label_ru: v.label_ru ?? v.code },
      ]),
    );
  }

  /** Russian label of an AuditAction (for the audit screen). */
  label(action: string): string {
    return this.actions.get(action)?.label_ru ?? action;
  }

  hasAction(action: string): boolean {
    return this.actions.has(action);
  }

  toRow(event: AuditEvent, ctx: RequestContext | undefined = currentContext()): NewAuditRow {
    const meta = this.actions.get(event.action);
    if (!meta) throw new Error(`audit action ${event.action} is not in enums.yaml AuditAction`);
    const principal = ctx?.principal ?? null;
    const actorType = event.actor?.type ?? (principal ? 'USER' : ctx ? 'ANONYMOUS' : 'SYSTEM');
    const result = event.result ?? 'SUCCESS';
    const denied = result === 'DENIED' && meta.retention !== 'PERMANENT';
    const ip = event.request?.ip ?? ctx?.ip ?? null;
    return {
      userId: event.actor?.userId ?? principal?.userId ?? null,
      action: event.action,
      objectId: event.objectId ?? null,
      details: event.details ?? {},
      ipAddress: ip && isIP(ip) ? ip : null,
      userAgent: event.request?.userAgent ?? ctx?.userAgent ?? null,
      actorType,
      actorRole: (event.actor?.roles ?? principal?.roles ?? []).join(',') || null,
      actorLogin: event.actor?.login ?? principal?.login ?? null,
      category: denied ? 'SECURITY' : meta.category,
      result,
      objectType: event.objectType ?? null,
      constructionObjectId: event.constructionObjectId ?? null,
      processId: event.processId ?? null,
      protocolVersion: event.protocolVersion ?? null,
      requestId: event.request?.requestId ?? ctx?.requestId ?? null,
      sessionRef: event.request?.sessionRef ?? principal?.sessionRef ?? null,
      httpMethod: event.request?.method ?? null,
      route: event.request?.route ?? ctx?.route ?? null,
      statusCode: event.request?.statusCode ?? null,
      durationMs: event.request?.durationMs ?? null,
      retentionClass: denied ? 'SECURITY' : meta.retention,
    };
  }

  /**
   * Domain audit. Pass the transaction as `executor` so the row commits with the change. Inside a request the
   * generic mutation row is then skipped (the request is already audited by this domain row), unless
   * `additional` is set: a side effect worth its own row (e.g. PROTOCOL_VERSION_CREATED during an import).
   */
  async record(event: AuditEvent, opts: { executor?: AuditExecutor; additional?: boolean } = {}): Promise<void> {
    const ctx = currentContext();
    await this.repository.insert([this.toRow(event, ctx)], opts.executor);
    if (ctx && !opts.additional) ctx.audit.recorded = true;
  }

  /** Mutation audit for one request (Fastify onSend hook). Never throws: a failure is logged as an error. */
  async recordRequest(req: FastifyRequest, reply: FastifyReply, payload: unknown): Promise<void> {
    try {
      const status = reply.statusCode;
      const mutating = MUTATING.has(req.method);
      if (!mutating && status !== 403) return;
      const ctx = contextOf(req);
      if (ctx.audit.recorded && status < 400) return;
      let route = ctx.route;
      const operation = this.openapi.match({
        method: req.method === 'HEAD' ? 'GET' : req.method,
        path: pathOf(req.url),
        headers: req.headers as Record<string, string | string[]>,
        query: {},
        body: undefined,
      }) as ({ path?: string; 'x-audit-action'?: string } & object) | undefined;
      if (!operation) return; // not an API operation (unknown route): nothing was changed
      route ??= operation.path;
      const operationAction = operation['x-audit-action'];
      const note = ctx.audit;
      const action = note.action ?? (mutating ? (operationAction ?? `HTTP_${req.method}`) : 'ACCESS_DENIED');
      const params = (req.params ?? {}) as Record<string, string>;
      let objectType = note.objectType ?? null;
      let objectId = note.objectId ?? null;
      if (!objectType) {
        const hit = PARAM_OBJECT_TYPES.find(([name]) => params[name]);
        if (hit) {
          objectType = hit[1];
          objectId ??= params[hit[0]] ?? null;
        }
      }
      const details: Record<string, unknown> = { ...(note.details ?? {}) };
      const problemCode = this.problemCode(reply, payload);
      if (problemCode) details.error_code = problemCode;
      if (ctx.permission) details.permission = ctx.permission;
      const principal = ctx.principal;
      await this.repository.insert([
        this.toRow(
          {
            action,
            result: resultOf(status),
            objectType,
            objectId,
            constructionObjectId: note.constructionObjectId ?? params.object_id ?? null,
            processId: note.processId ?? params.process_id ?? null,
            protocolVersion: note.protocolVersion ?? null,
            details,
            actor: principal
              ? undefined
              : { type: 'ANONYMOUS', userId: note.actorUserId ?? null, login: note.actorLogin ?? null, roles: [] },
            request: {
              method: req.method,
              route: route ?? null,
              statusCode: status,
              durationMs: Math.round(performance.now() - ctx.startedAt),
            },
          },
          ctx,
        ),
      ]);
    } catch (err) {
      this.logger.error(
        { event: 'audit_write_failed', err, method: req.method, url: pathOf(req.url), request_id: req.id },
        'audit row could not be written',
      );
    }
  }

  private problemCode(reply: FastifyReply, payload: unknown): string | null {
    const type = String(reply.getHeader('content-type') ?? '');
    if (!type.startsWith('application/problem+json')) return null;
    try {
      const text = typeof payload === 'string' ? payload : Buffer.isBuffer(payload) ? payload.toString('utf8') : '';
      const code = (JSON.parse(text) as { code?: unknown }).code;
      return typeof code === 'string' ? code : null;
    } catch {
      return null;
    }
  }
}
