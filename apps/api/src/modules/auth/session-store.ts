/**
 * Server-side sessions, step-up tokens and login throttling (09 §3.3.1) in Redis.
 *
 * Keys (prefix `ii:`): `sess:<sha256(token)>` → session JSON (TTL = idle timeout, capped by the absolute
 * lifetime); `usess:<user_id>` → ZSET of the user's session hashes by creation time (max N per user, the oldest is
 * evicted); `reauth:<sha256(token)>` → single-use step-up token (5 min); `fail:ip:<ip>` / `block:ip:<ip>` → login
 * failure counter and temporary IP block. Tokens are never stored, only their hashes.
 */
import { Inject, Injectable, type OnModuleDestroy } from '@nestjs/common';
import Redis from 'ioredis';
import { APP_CONFIG, type AppConfig } from '../../config/config';

export interface SessionRecord {
  userId: string;
  login: string;
  roles: string[];
  csrf: string;
  /** epoch ms */
  createdAt: number;
  lastSeenAt: number;
  absoluteExpiresAt: number;
  ip: string | null;
  userAgent: string | null;
}

export interface ReauthRecord {
  userId: string;
  sessionRef: string;
}

/** Redis (or the configured store) cannot be reached: the API answers 503 SESSION_STORE_UNAVAILABLE. */
export class SessionStoreUnavailableError extends Error {
  constructor(cause: unknown) {
    super(`session store unavailable: ${cause instanceof Error ? cause.message : String(cause)}`);
    this.name = 'SessionStoreUnavailableError';
  }
}

export abstract class SessionStore {
  /** Store a new session; returns the hashes of sessions evicted by the per-user limit. */
  abstract create(tokenHash: string, session: SessionRecord, ttlSeconds: number, maxPerUser: number): Promise<string[]>;
  abstract get(tokenHash: string): Promise<SessionRecord | null>;
  /** Refresh last_seen and the idle TTL. */
  abstract touch(tokenHash: string, session: SessionRecord, ttlSeconds: number): Promise<void>;
  abstract delete(tokenHash: string, userId: string): Promise<void>;
  /** Drop every session of a user (password change, deactivation); returns how many. */
  abstract deleteAllForUser(userId: string, exceptHash?: string): Promise<number>;
  abstract putReauth(tokenHash: string, record: ReauthRecord, ttlSeconds: number): Promise<void>;
  /** Read and delete a step-up token (single use). */
  abstract takeReauth(tokenHash: string): Promise<ReauthRecord | null>;
  /** Increment a failure counter with a sliding window; returns the new count. */
  abstract countFailure(key: string, windowSeconds: number): Promise<number>;
  abstract resetFailures(key: string): Promise<void>;
  abstract block(key: string, seconds: number): Promise<void>;
  /** Seconds left on a block, 0 when not blocked. */
  abstract blockedFor(key: string): Promise<number>;
}

const PREFIX = 'ii:';

@Injectable()
export class RedisSessionStore extends SessionStore implements OnModuleDestroy {
  private readonly redis: Redis;

  constructor(@Inject(APP_CONFIG) config: AppConfig) {
    super();
    this.redis = new Redis(config.redisUrl, {
      lazyConnect: true,
      connectTimeout: 2000,
      commandTimeout: 2000,
      maxRetriesPerRequest: 1,
      retryStrategy: (times) => Math.min(times * 200, 2000),
      connectionName: 'inspector-api',
    });
    // Connection errors surface on the commands; an unhandled 'error' event must not crash the process.
    this.redis.on('error', () => undefined);
  }

  private async run<T>(fn: (r: Redis) => Promise<T>): Promise<T> {
    try {
      return await fn(this.redis);
    } catch (err) {
      throw new SessionStoreUnavailableError(err);
    }
  }

  async create(tokenHash: string, session: SessionRecord, ttlSeconds: number, maxPerUser: number): Promise<string[]> {
    return this.run(async (r) => {
      const userKey = `${PREFIX}usess:${session.userId}`;
      await r
        .multi()
        .set(`${PREFIX}sess:${tokenHash}`, JSON.stringify(session), 'EX', ttlSeconds)
        .zadd(userKey, session.createdAt, tokenHash)
        .expire(userKey, Math.max(ttlSeconds, Math.ceil((session.absoluteExpiresAt - Date.now()) / 1000)))
        .exec();
      // Forget hashes whose session already expired, then evict the oldest beyond the limit.
      const members = await r.zrange(userKey, 0, -1);
      const alive = await Promise.all(members.map((m) => r.exists(`${PREFIX}sess:${m}`)));
      const dead = members.filter((_, i) => !alive[i]);
      if (dead.length) await r.zrem(userKey, ...dead);
      const live = members.filter((_, i) => alive[i]);
      const evicted = live.length > maxPerUser ? live.slice(0, live.length - maxPerUser) : [];
      if (evicted.length) {
        await r
          .multi()
          .del(...evicted.map((h) => `${PREFIX}sess:${h}`))
          .zrem(userKey, ...evicted)
          .exec();
      }
      return evicted;
    });
  }

  async get(tokenHash: string): Promise<SessionRecord | null> {
    const raw = await this.run((r) => r.get(`${PREFIX}sess:${tokenHash}`));
    if (!raw) return null;
    try {
      return JSON.parse(raw) as SessionRecord;
    } catch {
      return null;
    }
  }

  async touch(tokenHash: string, session: SessionRecord, ttlSeconds: number): Promise<void> {
    await this.run((r) => r.set(`${PREFIX}sess:${tokenHash}`, JSON.stringify(session), 'EX', ttlSeconds));
  }

  async delete(tokenHash: string, userId: string): Promise<void> {
    await this.run((r) => r.multi().del(`${PREFIX}sess:${tokenHash}`).zrem(`${PREFIX}usess:${userId}`, tokenHash).exec());
  }

  async deleteAllForUser(userId: string, exceptHash?: string): Promise<number> {
    return this.run(async (r) => {
      const userKey = `${PREFIX}usess:${userId}`;
      const members = (await r.zrange(userKey, 0, -1)).filter((m) => m !== exceptHash);
      if (!members.length) return 0;
      await r
        .multi()
        .del(...members.map((m) => `${PREFIX}sess:${m}`))
        .zrem(userKey, ...members)
        .exec();
      return members.length;
    });
  }

  async putReauth(tokenHash: string, record: ReauthRecord, ttlSeconds: number): Promise<void> {
    await this.run((r) => r.set(`${PREFIX}reauth:${tokenHash}`, JSON.stringify(record), 'EX', ttlSeconds));
  }

  async takeReauth(tokenHash: string): Promise<ReauthRecord | null> {
    const raw = await this.run((r) => r.getdel(`${PREFIX}reauth:${tokenHash}`));
    return raw ? (JSON.parse(raw) as ReauthRecord) : null;
  }

  async countFailure(key: string, windowSeconds: number): Promise<number> {
    return this.run(async (r) => {
      const full = `${PREFIX}fail:${key}`;
      const results = await r.multi().incr(full).expire(full, windowSeconds, 'NX').exec();
      return Number(results?.[0]?.[1] ?? 0);
    });
  }

  async resetFailures(key: string): Promise<void> {
    await this.run((r) => r.del(`${PREFIX}fail:${key}`));
  }

  async block(key: string, seconds: number): Promise<void> {
    await this.run((r) => r.set(`${PREFIX}block:${key}`, '1', 'EX', seconds));
  }

  async blockedFor(key: string): Promise<number> {
    const ttl = await this.run((r) => r.ttl(`${PREFIX}block:${key}`));
    return ttl > 0 ? ttl : 0;
  }

  async onModuleDestroy(): Promise<void> {
    if (this.redis.status === 'ready') await this.redis.quit().catch(() => undefined);
    else this.redis.disconnect();
  }
}

/** Process-local store with the same semantics (tests; never used by main.ts). */
export class InMemorySessionStore extends SessionStore {
  readonly sessions = new Map<string, { value: SessionRecord; expiresAt: number }>();
  readonly reauth = new Map<string, { value: ReauthRecord; expiresAt: number }>();
  readonly failures = new Map<string, { count: number; expiresAt: number }>();
  readonly blocks = new Map<string, number>();
  /** Simulate an unreachable store. */
  down = false;
  /** Test clock offset (ms), to expire keys without waiting. */
  skewMs = 0;

  private now(): number {
    return Date.now() + this.skewMs;
  }

  private check(): void {
    if (this.down) throw new SessionStoreUnavailableError(new Error('connect ECONNREFUSED 127.0.0.1:6379'));
  }

  private live<T>(map: Map<string, { value: T; expiresAt: number }>, key: string): T | null {
    const entry = map.get(key);
    if (!entry) return null;
    if (entry.expiresAt <= this.now()) {
      map.delete(key);
      return null;
    }
    return entry.value;
  }

  async create(tokenHash: string, session: SessionRecord, ttlSeconds: number, maxPerUser: number): Promise<string[]> {
    this.check();
    this.sessions.set(tokenHash, { value: session, expiresAt: this.now() + ttlSeconds * 1000 });
    const own = [...this.sessions.entries()]
      .filter(([h, e]) => e.value.userId === session.userId && this.live(this.sessions, h))
      .sort((a, b) => a[1].value.createdAt - b[1].value.createdAt)
      .map(([h]) => h);
    const evicted = own.length > maxPerUser ? own.slice(0, own.length - maxPerUser) : [];
    for (const h of evicted) this.sessions.delete(h);
    return evicted;
  }

  async get(tokenHash: string): Promise<SessionRecord | null> {
    this.check();
    return this.live(this.sessions, tokenHash);
  }

  async touch(tokenHash: string, session: SessionRecord, ttlSeconds: number): Promise<void> {
    this.check();
    this.sessions.set(tokenHash, { value: session, expiresAt: this.now() + ttlSeconds * 1000 });
  }

  async delete(tokenHash: string): Promise<void> {
    this.check();
    this.sessions.delete(tokenHash);
  }

  async deleteAllForUser(userId: string, exceptHash?: string): Promise<number> {
    this.check();
    let n = 0;
    for (const [h, e] of this.sessions) {
      if (e.value.userId === userId && h !== exceptHash) {
        this.sessions.delete(h);
        n += 1;
      }
    }
    return n;
  }

  async putReauth(tokenHash: string, record: ReauthRecord, ttlSeconds: number): Promise<void> {
    this.check();
    this.reauth.set(tokenHash, { value: record, expiresAt: this.now() + ttlSeconds * 1000 });
  }

  async takeReauth(tokenHash: string): Promise<ReauthRecord | null> {
    this.check();
    const value = this.live(this.reauth, tokenHash);
    this.reauth.delete(tokenHash);
    return value;
  }

  async countFailure(key: string, windowSeconds: number): Promise<number> {
    this.check();
    const entry = this.failures.get(key);
    if (!entry || entry.expiresAt <= this.now()) {
      this.failures.set(key, { count: 1, expiresAt: this.now() + windowSeconds * 1000 });
      return 1;
    }
    entry.count += 1;
    return entry.count;
  }

  async resetFailures(key: string): Promise<void> {
    this.check();
    this.failures.delete(key);
  }

  async block(key: string, seconds: number): Promise<void> {
    this.check();
    this.blocks.set(key, this.now() + seconds * 1000);
  }

  async blockedFor(key: string): Promise<number> {
    this.check();
    const until = this.blocks.get(key);
    return until && until > this.now() ? Math.ceil((until - this.now()) / 1000) : 0;
  }
}
