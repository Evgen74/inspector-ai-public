/** Persistence of РиН deliveries and attempts (tables of drizzle/0006_tz_modules_a.sql). */
import { Injectable } from '@nestjs/common';
import { Database } from '../../db/database';

/** SyncStatus (enums.yaml) subset used by the stub. */
export type SyncState = 'PENDING_SYNC' | 'SYNCED' | 'SYNC_FAILED';

export interface Delivery {
  process_id: string;
  run_id?: string | null;
  status: SyncState;
  trigger: 'AUTO' | 'MANUAL';
  attempts: number;
  max_attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  payload_sha256: string | null;
  violations: number;
  external_id: string | null;
  simulate_failures: number;
  requested_by: string | null;
  created_at: string;
  updated_at: string;
  synced_at: string | null;
}

export interface Attempt {
  attempt_no: number;
  started_at: string;
  outcome: string;
  http_status: number | null;
  detail: string | null;
  duration_ms: number | null;
}

export abstract class RinRepository {
  abstract get(processId: string): Promise<Delivery | null>;
  abstract upsert(d: Omit<Delivery, 'created_at' | 'updated_at' | 'run_id'>): Promise<Delivery>;
  abstract addAttempt(processId: string, a: Attempt): Promise<void>;
  abstract attempts(processId: string): Promise<Attempt[]>;
  abstract byObject(objectId: string): Promise<Delivery[]>;
  /** PENDING_SYNC deliveries whose next attempt is due. */
  abstract due(now: Date): Promise<string[]>;
  /** FINALIZED processes of non-hidden objects that have no delivery yet. */
  abstract autoCandidates(limit: number): Promise<string[]>;
}

const iso = (v: unknown): string | null => (v instanceof Date ? v.toISOString() : v ? String(v) : null);

function toDelivery(x: Record<string, unknown>): Delivery {
  return {
    process_id: x.process_id as string,
    run_id: (x.run_id as string | null | undefined) ?? null,
    status: x.status as SyncState,
    trigger: x.trigger as 'AUTO' | 'MANUAL',
    attempts: x.attempts as number,
    max_attempts: x.max_attempts as number,
    next_attempt_at: iso(x.next_attempt_at),
    last_error: (x.last_error as string | null) ?? null,
    payload_sha256: ((x.payload_sha256 as string | null) ?? null)?.trim() ?? null,
    violations: x.violations as number,
    external_id: (x.external_id as string | null) ?? null,
    simulate_failures: x.simulate_failures as number,
    requested_by: (x.requested_by as string | null) ?? null,
    created_at: iso(x.created_at) as string,
    updated_at: iso(x.updated_at) as string,
    synced_at: iso(x.synced_at),
  };
}

@Injectable()
export class PgRinRepository extends RinRepository {
  constructor(private readonly database: Database) {
    super();
  }

  async get(processId: string): Promise<Delivery | null> {
    const r = await this.database.pool.query('SELECT * FROM rin_deliveries WHERE process_id = $1', [processId]);
    return r.rows[0] ? toDelivery(r.rows[0]) : null;
  }

  async upsert(d: Omit<Delivery, 'created_at' | 'updated_at' | 'run_id'>): Promise<Delivery> {
    const r = await this.database.pool.query(
      `INSERT INTO rin_deliveries (process_id, status, trigger, attempts, max_attempts, next_attempt_at, last_error,
         payload_sha256, violations, external_id, simulate_failures, requested_by, synced_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
       ON CONFLICT (process_id) DO UPDATE SET status=EXCLUDED.status, trigger=EXCLUDED.trigger, attempts=EXCLUDED.attempts,
         max_attempts=EXCLUDED.max_attempts, next_attempt_at=EXCLUDED.next_attempt_at, last_error=EXCLUDED.last_error,
         payload_sha256=EXCLUDED.payload_sha256, violations=EXCLUDED.violations, external_id=EXCLUDED.external_id,
         simulate_failures=EXCLUDED.simulate_failures, requested_by=EXCLUDED.requested_by, synced_at=EXCLUDED.synced_at,
         updated_at=now()
       RETURNING *`,
      [d.process_id, d.status, d.trigger, d.attempts, d.max_attempts, d.next_attempt_at, d.last_error, d.payload_sha256, d.violations, d.external_id, d.simulate_failures, d.requested_by, d.synced_at],
    );
    return toDelivery(r.rows[0]);
  }

  async addAttempt(processId: string, a: Attempt): Promise<void> {
    await this.database.pool.query(
      'INSERT INTO rin_attempts (process_id, attempt_no, started_at, outcome, http_status, detail, duration_ms) VALUES ($1,$2,$3,$4,$5,$6,$7)',
      [processId, a.attempt_no, a.started_at, a.outcome, a.http_status, a.detail, a.duration_ms],
    );
  }

  async attempts(processId: string): Promise<Attempt[]> {
    const r = await this.database.pool.query(
      'SELECT attempt_no, started_at, outcome, http_status, detail, duration_ms FROM rin_attempts WHERE process_id = $1 ORDER BY id',
      [processId],
    );
    return r.rows.map((x) => ({ ...x, started_at: iso(x.started_at) as string }) as Attempt);
  }

  async byObject(objectId: string): Promise<Delivery[]> {
    const r = await this.database.pool.query(
      `SELECT d.*, p.active_run_id AS run_id FROM rin_deliveries d JOIN processes p ON p.id = d.process_id
       WHERE p.object_id = $1 ORDER BY d.updated_at DESC`,
      [objectId],
    );
    return r.rows.map(toDelivery);
  }

  async due(now: Date): Promise<string[]> {
    const r = await this.database.pool.query(
      "SELECT process_id FROM rin_deliveries WHERE status = 'PENDING_SYNC' AND next_attempt_at IS NOT NULL AND next_attempt_at <= $1 LIMIT 20",
      [now],
    );
    return r.rows.map((x) => x.process_id as string);
  }

  async autoCandidates(limit: number): Promise<string[]> {
    const r = await this.database.pool.query(
      `SELECT p.id FROM processes p JOIN objects o ON o.id = p.object_id
       LEFT JOIN rin_deliveries d ON d.process_id = p.id
       WHERE p.status = 'FINALIZED' AND d.process_id IS NULL AND COALESCE(o.split, '') <> 'TEST_HIDDEN' LIMIT $1`,
      [limit],
    );
    return r.rows.map((x) => x.id as string);
  }
}

/** Test double. */
export class InMemoryRinRepository extends RinRepository {
  deliveries = new Map<string, Delivery>();
  log = new Map<string, Attempt[]>();
  finalized: string[] = [];

  async get(processId: string): Promise<Delivery | null> {
    return this.deliveries.get(processId) ?? null;
  }

  async upsert(d: Omit<Delivery, 'created_at' | 'updated_at' | 'run_id'>): Promise<Delivery> {
    const prev = this.deliveries.get(d.process_id);
    const now = new Date().toISOString();
    const row: Delivery = { ...d, run_id: null, created_at: prev?.created_at ?? now, updated_at: now };
    this.deliveries.set(d.process_id, row);
    return row;
  }

  async addAttempt(processId: string, a: Attempt): Promise<void> {
    this.log.set(processId, [...(this.log.get(processId) ?? []), a]);
  }

  async attempts(processId: string): Promise<Attempt[]> {
    return this.log.get(processId) ?? [];
  }

  async byObject(): Promise<Delivery[]> {
    return [...this.deliveries.values()];
  }

  async due(now: Date): Promise<string[]> {
    return [...this.deliveries.values()].filter((d) => d.status === 'PENDING_SYNC' && d.next_attempt_at && new Date(d.next_attempt_at) <= now).map((d) => d.process_id);
  }

  async autoCandidates(): Promise<string[]> {
    return this.finalized.filter((id) => !this.deliveries.has(id));
  }
}
