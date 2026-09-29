/**
 * Per-request context (09 §3.2.1): request id, client address, the authenticated principal and what the audit
 * writer should record for this request.
 *
 * The context lives on the Fastify request (`contextOf(req)`), so Fastify hooks (the audit `onSend` hook) and Nest
 * guards/controllers share it. `RequestContextInterceptor` also binds it to an AsyncLocalStorage around the
 * handler, so services deep in the call chain (e.g. `AuditService.record` inside a verification transaction) can
 * read it with `currentContext()` without threading the request through.
 */
import { AsyncLocalStorage } from 'node:async_hooks';
import { type CallHandler, type ExecutionContext, Injectable, type NestInterceptor } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { Observable } from 'rxjs';

/** PermissionScope codes (packages/contracts/enums.yaml). */
export type PermissionScope = 'ALL' | 'ASSIGNED' | 'OWN';

/** The authenticated user of a request (resolved from the session by the auth guard). */
export interface Principal {
  userId: string;
  login: string;
  fullName: string;
  /** Role codes (enums.yaml Role). */
  roles: string[];
  /** Effective permissions (rbac.yaml) with the widest scope over the user's roles. */
  permissions: ReadonlyMap<string, PermissionScope>;
  /** First 16 hex chars of sha256(session token). */
  sessionRef: string;
  csrfToken: string;
  mustChangePassword: boolean;
}

/** What the audit writer records for this request; handlers refine it before returning or throwing. */
export interface AuditNote {
  /** AuditAction; default: the operation's `x-audit-action`, else HTTP_<METHOD>. */
  action?: string;
  /** AuditObjectType */
  objectType?: string;
  objectId?: string | null;
  constructionObjectId?: string | null;
  processId?: string | null;
  protocolVersion?: number | null;
  details?: Record<string, unknown>;
  /** Actor override for requests without a session (login attempts). */
  actorUserId?: string | null;
  actorLogin?: string | null;
  /** The handler wrote its own domain audit rows (in its transaction): the generic row is skipped. */
  recorded?: boolean;
}

export interface RequestContext {
  requestId: string;
  ip: string | null;
  userAgent: string | null;
  startedAt: number;
  principal: Principal | null;
  /** OpenAPI operation matched by the auth guard. */
  operationId?: string;
  /** OpenAPI path template, e.g. /objects/{object_id} */
  route?: string;
  /** rbac.yaml permission of the operation (`x-permission`) and the scope the principal holds for it. */
  permission?: string | null;
  scope?: PermissionScope | null;
  audit: AuditNote;
}

const CONTEXT = Symbol('inspectorRequestContext');
type WithContext = FastifyRequest & { [CONTEXT]?: RequestContext };

export const requestContextStorage = new AsyncLocalStorage<RequestContext>();

function headerValue(value: string | string[] | undefined): string | null {
  const v = Array.isArray(value) ? value[0] : value;
  return v ? v.slice(0, 512) : null;
}

/** The context of a request, created on first use. */
export function contextOf(req: FastifyRequest): RequestContext {
  const r = req as WithContext;
  if (!r[CONTEXT]) {
    r[CONTEXT] = {
      requestId: String(req.id),
      ip: req.ip ?? null,
      userAgent: headerValue(req.headers['user-agent']),
      startedAt: performance.now(),
      principal: null,
      audit: {},
    };
  }
  return r[CONTEXT];
}

/** The context bound to the current async call chain (inside a Nest handler), if any. */
export function currentContext(): RequestContext | undefined {
  return requestContextStorage.getStore();
}

/** Merge audit facts for this request (later calls win; details are merged). */
export function noteAudit(req: FastifyRequest, note: AuditNote): void {
  const ctx = contextOf(req);
  const details = note.details ? { ...(ctx.audit.details ?? {}), ...note.details } : ctx.audit.details;
  ctx.audit = { ...ctx.audit, ...note, ...(details ? { details } : {}) };
}

/** Binds the request context to AsyncLocalStorage for the duration of the handler. */
@Injectable()
export class RequestContextInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const req = context.switchToHttp().getRequest<FastifyRequest>();
    const ctx = contextOf(req);
    return new Observable((subscriber) =>
      requestContextStorage.run(ctx, () => next.handle().subscribe(subscriber)),
    );
  }
}
