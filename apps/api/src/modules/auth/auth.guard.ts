/**
 * Global authentication + RBAC guard (runs before the OpenAPI request guard).
 *
 * The OpenAPI document is the source of the rules (contracts are law):
 * - `security: []` → public operation (login, health);
 * - otherwise a session is required (INSPECTOR_AUTH_MODE=optional lets requests without a cookie through as
 *   anonymous, for local development only);
 * - `x-permission: <rbac.yaml code>` → the principal must hold it; ASSIGNED scope also checks the `object_id` path
 *   parameter against object_assignments;
 * - unsafe methods need `X-CSRF-Token` equal to the session's token;
 * - a pending forced password change blocks everything except operations with `x-allow-password-change: true`.
 */
import { timingSafeEqual } from 'node:crypto';
import { type CanActivate, type ExecutionContext, Inject, Injectable } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { ApiProblem } from '../../common/problem';
import { contextOf, noteAudit } from '../../common/request-context';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { OpenApiService } from '../../openapi/openapi.service';
import { AuthService } from './auth.service';
import { clearSessionCookie, CSRF_HEADER, readSessionToken } from './cookies';
import { SessionStoreUnavailableError } from './session-store';
import { UsersRepository } from './users.repository';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function pathOf(url: string): string {
  const q = url.indexOf('?');
  return q === -1 ? url : url.slice(0, q);
}

function sameToken(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

interface OperationExtensions {
  operationId?: string;
  path?: string;
  security?: unknown[];
  'x-permission'?: string;
  'x-allow-password-change'?: boolean;
}

@Injectable()
export class AuthGuard implements CanActivate {
  constructor(
    private readonly openapi: OpenApiService,
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly auth: AuthService,
    private readonly users: UsersRepository,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const http = context.switchToHttp();
    const req = http.getRequest<FastifyRequest>();
    const reply = http.getResponse<FastifyReply>();
    const ctx = contextOf(req);
    const operation = this.openapi.match({
      method: req.method === 'HEAD' ? 'GET' : req.method,
      path: pathOf(req.url),
      headers: req.headers as Record<string, string | string[]>,
      query: (req.query ?? {}) as Record<string, string | string[]>,
      body: req.body,
    }) as (OperationExtensions & object) | undefined;
    // No operation: the OpenAPI guard raises the conformance error next.
    if (!operation) return true;
    ctx.operationId = operation.operationId;
    ctx.route = operation.path;
    const isPublic = Array.isArray(operation.security) && operation.security.length === 0;
    const permission = operation['x-permission'] ?? null;
    ctx.permission = permission;

    const token = readSessionToken(req, this.config);
    if (token) {
      let resolved;
      try {
        resolved = await this.auth.resolve(token);
      } catch (err) {
        if (err instanceof SessionStoreUnavailableError) throw new ApiProblem('SESSION_STORE_UNAVAILABLE');
        throw err;
      }
      if (resolved) {
        ctx.principal = resolved.principal;
      } else if (!isPublic) {
        clearSessionCookie(reply, this.config);
        throw new ApiProblem('SESSION_EXPIRED');
      }
    }
    if (isPublic) return true;

    const principal = ctx.principal;
    if (!principal) {
      if (this.config.authMode === 'optional') return true;
      throw new ApiProblem('UNAUTHENTICATED');
    }
    if (UNSAFE_METHODS.has(req.method)) {
      const header = req.headers[CSRF_HEADER];
      const value = Array.isArray(header) ? header[0] : header;
      if (!value || !sameToken(value, principal.csrfToken)) throw new ApiProblem('CSRF_TOKEN_INVALID');
    }
    if (principal.mustChangePassword && !operation['x-allow-password-change']) {
      throw new ApiProblem('PASSWORD_CHANGE_REQUIRED');
    }
    if (permission) {
      const scope = principal.permissions.get(permission) ?? null;
      if (!scope) {
        noteAudit(req, { details: { permission, roles: principal.roles } });
        throw new ApiProblem('FORBIDDEN');
      }
      ctx.scope = scope;
      const objectId = (req.params as Record<string, string> | undefined)?.object_id;
      if (scope === 'ASSIGNED' && objectId && !(await this.users.isAssigned(principal.userId, objectId))) {
        noteAudit(req, { details: { permission, scope, object_id: objectId } });
        throw new ApiProblem('FORBIDDEN');
      }
    }
    return true;
  }
}
