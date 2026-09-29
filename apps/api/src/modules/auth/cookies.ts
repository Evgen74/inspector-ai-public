/**
 * Session cookie (09 §3.3.1, 90 §3.4): HttpOnly, SameSite=Strict, Path=/. With INSPECTOR_COOKIE_SECURE (default in
 * prod) it is `__Host-ii_sid` + Secure; on plain-http localhost it is `ii_sid`. The CSRF token travels in the
 * response body and comes back in the `X-CSRF-Token` header (never in a cookie).
 */
import { parse, serialize } from 'cookie';
import type { FastifyReply, FastifyRequest } from 'fastify';
import type { AppConfig } from '../../config/config';

export const CSRF_HEADER = 'x-csrf-token';

export function sessionCookieName(config: Pick<AppConfig, 'cookieSecure'>): string {
  return config.cookieSecure ? '__Host-ii_sid' : 'ii_sid';
}

export function readSessionToken(req: FastifyRequest, config: Pick<AppConfig, 'cookieSecure'>): string | null {
  const header = req.headers.cookie;
  if (!header) return null;
  try {
    const value = parse(header)[sessionCookieName(config)];
    return value && value.length > 0 ? value : null;
  } catch {
    return null;
  }
}

export function setSessionCookie(reply: FastifyReply, config: AppConfig, token: string): void {
  void reply.header(
    'set-cookie',
    serialize(sessionCookieName(config), token, {
      httpOnly: true,
      sameSite: 'strict',
      path: '/',
      secure: config.cookieSecure,
      maxAge: config.sessionAbsoluteSeconds,
    }),
  );
}

export function clearSessionCookie(reply: FastifyReply, config: AppConfig): void {
  void reply.header(
    'set-cookie',
    serialize(sessionCookieName(config), '', {
      httpOnly: true,
      sameSite: 'strict',
      path: '/',
      secure: config.cookieSecure,
      maxAge: 0,
    }),
  );
}
