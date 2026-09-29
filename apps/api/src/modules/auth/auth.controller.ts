/** POST /auth/login, POST /auth/logout, GET /auth/me, POST /auth/password, POST /auth/reauth (90 §3.4 A). */
import { Body, Controller, Get, HttpCode, Inject, Post, Req, Res } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { ApiProblem } from '../../common/problem';
import { contextOf, noteAudit, type Principal } from '../../common/request-context';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { AuthService, tokenHash } from './auth.service';
import { clearSessionCookie, readSessionToken, setSessionCookie } from './cookies';
import { UsersRepository } from './users.repository';

export interface AuthSessionDto {
  user: { id: string; login: string; full_name: string; position: string | null; email: string | null };
  roles: string[];
  permissions: Array<{ code: string; scope: string }>;
  assigned_object_ids: string[];
  csrf_token: string;
  must_change_password: boolean;
  session: { expires_at: string; idle_timeout_s: number };
}

/** The principal of the request, or 401 (also in INSPECTOR_AUTH_MODE=optional: these endpoints need a session). */
export function requirePrincipal(req: FastifyRequest): Principal {
  const principal = contextOf(req).principal;
  if (!principal) throw new ApiProblem('UNAUTHENTICATED');
  return principal;
}

@Controller('auth')
export class AuthController {
  constructor(
    private readonly auth: AuthService,
    private readonly users: UsersRepository,
    @Inject(APP_CONFIG) private readonly config: AppConfig,
  ) {}

  private async sessionDto(principal: Principal, absoluteExpiresAt: number): Promise<AuthSessionDto> {
    const user = await this.users.findById(principal.userId);
    return {
      user: {
        id: principal.userId,
        login: principal.login,
        full_name: principal.fullName,
        position: user?.position ?? null,
        email: user?.email ?? null,
      },
      roles: principal.roles,
      permissions: [...principal.permissions.entries()]
        .map(([code, scope]) => ({ code, scope }))
        .sort((a, b) => (a.code < b.code ? -1 : 1)),
      assigned_object_ids: await this.users.assignedObjectIds(principal.userId),
      csrf_token: principal.csrfToken,
      must_change_password: principal.mustChangePassword,
      session: { expires_at: new Date(absoluteExpiresAt).toISOString(), idle_timeout_s: this.config.sessionIdleSeconds },
    };
  }

  @Post('login')
  @HttpCode(200)
  async login(
    @Body() body: { login: string; password: string },
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<AuthSessionDto> {
    const ctx = contextOf(req);
    noteAudit(req, { objectType: 'USER', actorLogin: body.login.trim().toLowerCase().slice(0, 64), details: { login: body.login } });
    let result;
    try {
      result = await this.auth.login(body.login, body.password, { ip: ctx.ip, userAgent: ctx.userAgent });
    } catch (err) {
      const code = err instanceof ApiProblem ? err.code : 'INTERNAL_ERROR';
      noteAudit(req, {
        action: code === 'ACCOUNT_LOCKED' ? 'AUTH_LOCKED' : 'AUTH_LOGIN_FAILED',
        details: { reason: code },
      });
      throw err;
    }
    // An old session cookie of this browser is replaced (session fixation defence: a fresh token every login).
    const previous = readSessionToken(req, this.config);
    if (previous) await this.auth.logout(previous);
    setSessionCookie(reply, this.config, result.token);
    ctx.principal = result.principal;
    noteAudit(req, {
      action: 'AUTH_LOGIN_SUCCESS',
      objectId: result.user.id,
      actorUserId: result.user.id,
      details: { roles: result.user.roles, evicted_sessions: result.evicted },
    });
    return this.sessionDto(result.principal, result.session.absoluteExpiresAt);
  }

  @Post('logout')
  @HttpCode(204)
  async logout(@Req() req: FastifyRequest, @Res({ passthrough: true }) reply: FastifyReply): Promise<void> {
    const principal = requirePrincipal(req);
    const token = readSessionToken(req, this.config);
    if (token) await this.auth.logout(token);
    clearSessionCookie(reply, this.config);
    noteAudit(req, { action: 'AUTH_LOGOUT', objectType: 'SESSION', objectId: principal.sessionRef });
  }

  @Get('me')
  async me(@Req() req: FastifyRequest): Promise<AuthSessionDto> {
    const principal = requirePrincipal(req);
    const token = readSessionToken(req, this.config);
    const resolved = token ? await this.auth.resolve(token) : null;
    if (!resolved) throw new ApiProblem('SESSION_EXPIRED');
    return this.sessionDto(principal, resolved.session.absoluteExpiresAt);
  }

  @Post('password')
  @HttpCode(204)
  async changePassword(
    @Body() body: { current_password: string; new_password: string },
    @Req() req: FastifyRequest,
  ): Promise<void> {
    const principal = requirePrincipal(req);
    const token = readSessionToken(req, this.config) ?? '';
    noteAudit(req, { action: 'AUTH_PASSWORD_CHANGED', objectType: 'USER', objectId: principal.userId });
    const revoked = await this.auth.changePassword(principal, tokenHash(token), body.current_password, body.new_password);
    noteAudit(req, { details: { other_sessions_revoked: revoked } });
  }

  @Post('reauth')
  @HttpCode(200)
  async reauth(@Body() body: { password: string }, @Req() req: FastifyRequest): Promise<{ reauth_token: string; expires_at: string }> {
    const principal = requirePrincipal(req);
    noteAudit(req, { action: 'AUTH_REAUTH', objectType: 'SESSION', objectId: principal.sessionRef });
    const { token, expiresAt } = await this.auth.reauth(principal, body.password);
    return { reauth_token: token, expires_at: expiresAt.toISOString() };
  }
}
