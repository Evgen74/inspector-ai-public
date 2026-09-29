/**
 * Local login/password authentication (09 §3.3.1, 90 §3.4 A): argon2id passwords, opaque 256-bit session tokens
 * kept server-side in Redis (only their sha256), per-account lockout (5 failures → 15 min), per-IP throttling
 * (20 failures in 10 min → 30 min block), CSRF token per session, step-up re-authentication tokens (5 min, single
 * use) for finalize/unfinalize and other `reauth: true` permissions of rbac.yaml.
 */
import { randomBytes } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import { PinoLogger } from 'nestjs-pino';
import { sha256Hex } from '../../common/hashing';
import { ApiProblem } from '../../common/problem';
import type { Principal } from '../../common/request-context';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { hashPassword, PASSWORD_HISTORY, passwordViolations, verifyPassword } from './passwords';
import { Rbac } from './rbac';
import { type SessionRecord, SessionStore } from './session-store';
import { type UserRecord, UsersRepository } from './users.repository';

export const ACCOUNT_LOCK_THRESHOLD = 5;
export const ACCOUNT_LOCK_MINUTES = 15;
export const IP_FAILURE_LIMIT = 20;
export const IP_FAILURE_WINDOW_S = 10 * 60;
export const IP_BLOCK_S = 30 * 60;
export const REAUTH_TTL_S = 5 * 60;
/** Sliding expiry is refreshed at most once per this interval (saves a Redis write per request). */
const TOUCH_INTERVAL_MS = 60_000;

export interface ClientMeta {
  ip: string | null;
  userAgent: string | null;
}

export interface ResolvedSession {
  principal: Principal;
  session: SessionRecord;
  tokenHash: string;
}

export function tokenHash(token: string): string {
  return sha256Hex(token);
}

export function sessionRefOf(hash: string): string {
  return hash.slice(0, 16);
}

function newToken(bytes = 32): string {
  return randomBytes(bytes).toString('base64url');
}

/** Tokens are base64url of 32 random bytes; anything else is rejected before touching the store. */
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{20,128}$/;

@Injectable()
export class AuthService {
  private dummyHash: Promise<string> | null = null;

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    readonly rbac: Rbac,
    private readonly users: UsersRepository,
    private readonly sessions: SessionStore,
    private readonly logger: PinoLogger,
  ) {
    this.logger.setContext(AuthService.name);
  }

  /** Same work for unknown logins as for known ones (no user enumeration through timing). */
  private async burnVerify(password: string): Promise<void> {
    this.dummyHash ??= hashPassword(newToken(16));
    await verifyPassword(await this.dummyHash, password);
  }

  principalOf(user: Pick<UserRecord, 'id' | 'login' | 'fullName' | 'mustChangePassword'>, session: SessionRecord, hash: string): Principal {
    return {
      userId: user.id,
      login: user.login,
      fullName: user.fullName,
      roles: session.roles,
      permissions: this.rbac.effective(session.roles),
      sessionRef: sessionRefOf(hash),
      csrfToken: session.csrf,
      mustChangePassword: user.mustChangePassword,
    };
  }

  async login(
    loginInput: string,
    password: string,
    meta: ClientMeta,
  ): Promise<{ token: string; principal: Principal; user: UserRecord; session: SessionRecord; evicted: number }> {
    const login = loginInput.trim().toLowerCase();
    const ipKey = `ip:${meta.ip ?? 'unknown'}`;
    const blocked = await this.sessions.blockedFor(ipKey);
    if (blocked > 0) {
      throw new ApiProblem('IP_TEMPORARILY_BLOCKED', { retry_after_min: Math.ceil(blocked / 60) });
    }
    const user = await this.users.findByLogin(login);
    const now = Date.now();
    if (user?.lockedUntil && user.lockedUntil.getTime() > now) {
      throw new ApiProblem('ACCOUNT_LOCKED', {
        attempts: ACCOUNT_LOCK_THRESHOLD,
        retry_after_min: Math.ceil((user.lockedUntil.getTime() - now) / 60_000),
      });
    }
    const ok = user ? await verifyPassword(user.passwordHash, password) : (await this.burnVerify(password), false);
    if (!ok || !user || !user.isActive) {
      const ipFailures = await this.sessions.countFailure(ipKey, IP_FAILURE_WINDOW_S);
      if (ipFailures >= IP_FAILURE_LIMIT) await this.sessions.block(ipKey, IP_BLOCK_S);
      if (user && user.isActive) {
        const { lockedUntil } = await this.users.recordFailure(user.id, ACCOUNT_LOCK_THRESHOLD, ACCOUNT_LOCK_MINUTES);
        if (lockedUntil) {
          throw new ApiProblem('ACCOUNT_LOCKED', {
            attempts: ACCOUNT_LOCK_THRESHOLD,
            retry_after_min: Math.ceil((lockedUntil.getTime() - Date.now()) / 60_000),
          });
        }
      }
      throw new ApiProblem('INVALID_CREDENTIALS');
    }
    await this.users.recordSuccess(user.id);
    const token = newToken();
    const hash = tokenHash(token);
    const session: SessionRecord = {
      userId: user.id,
      login: user.login,
      roles: user.roles,
      csrf: newToken(24),
      createdAt: now,
      lastSeenAt: now,
      absoluteExpiresAt: now + this.config.sessionAbsoluteSeconds * 1000,
      ip: meta.ip,
      userAgent: meta.userAgent,
    };
    const evicted = await this.sessions.create(hash, session, this.config.sessionIdleSeconds, this.config.maxSessionsPerUser);
    return { token, principal: this.principalOf(user, session, hash), user, session, evicted: evicted.length };
  }

  /** Principal of a session token, or null when the token is unknown or expired (idle or absolute). */
  async resolve(token: string): Promise<ResolvedSession | null> {
    if (!TOKEN_SHAPE.test(token)) return null;
    const hash = tokenHash(token);
    const session = await this.sessions.get(hash);
    if (!session) return null;
    const now = Date.now();
    if (now >= session.absoluteExpiresAt) {
      await this.sessions.delete(hash, session.userId);
      return null;
    }
    if (now - session.lastSeenAt >= TOUCH_INTERVAL_MS) {
      const refreshed = { ...session, lastSeenAt: now };
      const ttl = Math.min(this.config.sessionIdleSeconds, Math.ceil((session.absoluteExpiresAt - now) / 1000));
      await this.sessions.touch(hash, refreshed, Math.max(1, ttl));
    }
    const user = await this.users.findById(session.userId);
    if (!user || !user.isActive) {
      await this.sessions.delete(hash, session.userId);
      return null;
    }
    // Roles come from the database on every request, so a role change applies without a new login.
    const current = { ...session, roles: user.roles };
    return { principal: this.principalOf(user, current, hash), session: current, tokenHash: hash };
  }

  async logout(token: string): Promise<void> {
    if (!TOKEN_SHAPE.test(token)) return;
    const hash = tokenHash(token);
    const session = await this.sessions.get(hash);
    if (session) await this.sessions.delete(hash, session.userId);
  }

  async changePassword(principal: Principal, tokenHashValue: string, current: string, next: string): Promise<number> {
    const user = await this.users.findById(principal.userId);
    if (!user || !(await verifyPassword(user.passwordHash, current))) {
      throw new ApiProblem('INVALID_CREDENTIALS');
    }
    const history = [user.passwordHash, ...user.passwordHistory].slice(0, PASSWORD_HISTORY);
    const violations = await passwordViolations(next, user.login, history);
    if (violations.length) {
      throw new ApiProblem('PASSWORD_POLICY_VIOLATION', { violations: violations.join('; ') });
    }
    await this.users.setPassword(user.id, await hashPassword(next), history, false);
    // Other sessions of the user end; the current one continues.
    return this.sessions.deleteAllForUser(user.id, tokenHashValue);
  }

  /** Step-up re-authentication (POST /auth/reauth): a single-use token valid for 5 minutes. */
  async reauth(principal: Principal, password: string): Promise<{ token: string; expiresAt: Date }> {
    const user = await this.users.findById(principal.userId);
    if (!user || !(await verifyPassword(user.passwordHash, password))) {
      throw new ApiProblem('INVALID_CREDENTIALS');
    }
    const token = newToken();
    await this.sessions.putReauth(tokenHash(token), { userId: user.id, sessionRef: principal.sessionRef }, REAUTH_TTL_S);
    return { token, expiresAt: new Date(Date.now() + REAUTH_TTL_S * 1000) };
  }

  /**
   * For actions that need a fresh confirmation (rbac.yaml `reauth: true`, e.g. protocol.finalize): consumes the
   * token and throws REAUTH_REQUIRED unless it was issued to this user in this session.
   */
  async consumeReauthToken(token: string | null | undefined, principal: Principal): Promise<void> {
    if (!token || !TOKEN_SHAPE.test(token)) throw new ApiProblem('REAUTH_REQUIRED');
    const record = await this.sessions.takeReauth(tokenHash(token));
    if (!record || record.userId !== principal.userId || record.sessionRef !== principal.sessionRef) {
      throw new ApiProblem('REAUTH_REQUIRED');
    }
  }
}
