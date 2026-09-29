/** Persistence of matrix overrides and matrix versions (tables of drizzle/0006_tz_modules_a.sql). */
import { Injectable } from '@nestjs/common';
import { Database } from '../../db/database';

export interface OverrideRow {
  param_code: string;
  min_value: number | null;
  max_value: number | null;
  is_active: boolean | null;
  matrix_version: number;
  updated_at: string;
}

export interface MatrixVersionRow {
  version: number;
  base_version: string;
  reason: string | null;
  changes: unknown[];
  created_by_login: string | null;
  created_at: string;
}

export interface OverridePatch {
  min_value: number | null;
  max_value: number | null;
  is_active: boolean | null;
}

export interface SaveInput {
  code: string;
  patch: OverridePatch;
  baseVersion: string;
  reason: string | null;
  change: Record<string, unknown>;
  user: { id: string | null; login: string | null };
}

export abstract class NormativeRepository {
  abstract overrides(): Promise<OverrideRow[]>;
  /** Upserts the override and inserts a matrix_versions row in one transaction; returns the new version. */
  abstract save(input: SaveInput): Promise<MatrixVersionRow>;
  abstract versions(limit: number): Promise<MatrixVersionRow[]>;
}

const numOrNull = (v: unknown): number | null => (v === null || v === undefined ? null : Number(v));

@Injectable()
export class PgNormativeRepository extends NormativeRepository {
  constructor(private readonly database: Database) {
    super();
  }

  async overrides(): Promise<OverrideRow[]> {
    const r = await this.database.pool.query(
      'SELECT param_code, min_value, max_value, is_active, matrix_version, updated_at FROM params_overrides ORDER BY param_code',
    );
    return r.rows.map((x) => ({
      param_code: x.param_code as string,
      min_value: numOrNull(x.min_value),
      max_value: numOrNull(x.max_value),
      is_active: x.is_active as boolean | null,
      matrix_version: x.matrix_version as number,
      updated_at: (x.updated_at as Date).toISOString(),
    }));
  }

  async save(input: SaveInput): Promise<MatrixVersionRow> {
    const client = await this.database.pool.connect();
    try {
      await client.query('BEGIN');
      const v = await client.query(
        `INSERT INTO matrix_versions (base_version, reason, changes, created_by, created_by_login)
         VALUES ($1, $2, $3::jsonb, $4, $5) RETURNING version, base_version, reason, changes, created_by_login, created_at`,
        [input.baseVersion, input.reason, JSON.stringify([input.change]), input.user.id, input.user.login],
      );
      const ver = v.rows[0] as { version: number };
      await client.query(
        `INSERT INTO params_overrides (param_code, min_value, max_value, is_active, matrix_version, updated_by, updated_at)
         VALUES ($1, $2, $3, $4, $5, $6, now())
         ON CONFLICT (param_code) DO UPDATE SET min_value = EXCLUDED.min_value, max_value = EXCLUDED.max_value,
           is_active = EXCLUDED.is_active, matrix_version = EXCLUDED.matrix_version,
           updated_by = EXCLUDED.updated_by, updated_at = now()`,
        [input.code, input.patch.min_value, input.patch.max_value, input.patch.is_active, ver.version, input.user.id],
      );
      await client.query('COMMIT');
      return toVersion(v.rows[0]);
    } catch (err) {
      await client.query('ROLLBACK').catch(() => undefined);
      throw err;
    } finally {
      client.release();
    }
  }

  async versions(limit: number): Promise<MatrixVersionRow[]> {
    const r = await this.database.pool.query(
      'SELECT version, base_version, reason, changes, created_by_login, created_at FROM matrix_versions ORDER BY version DESC LIMIT $1',
      [limit],
    );
    return r.rows.map(toVersion);
  }
}

function toVersion(x: Record<string, unknown>): MatrixVersionRow {
  return {
    version: x.version as number,
    base_version: x.base_version as string,
    reason: (x.reason as string | null) ?? null,
    changes: (x.changes as unknown[]) ?? [],
    created_by_login: (x.created_by_login as string | null) ?? null,
    created_at: (x.created_at as Date).toISOString(),
  };
}

/** Test double. */
export class InMemoryNormativeRepository extends NormativeRepository {
  rows = new Map<string, OverrideRow>();
  vers: MatrixVersionRow[] = [];

  async overrides(): Promise<OverrideRow[]> {
    return [...this.rows.values()];
  }

  async save(input: SaveInput): Promise<MatrixVersionRow> {
    const version: MatrixVersionRow = {
      version: this.vers.length + 1,
      base_version: input.baseVersion,
      reason: input.reason,
      changes: [input.change],
      created_by_login: input.user.login,
      created_at: new Date().toISOString(),
    };
    this.vers.push(version);
    this.rows.set(input.code, { param_code: input.code, ...input.patch, matrix_version: version.version, updated_at: version.created_at });
    return version;
  }

  async versions(limit: number): Promise<MatrixVersionRow[]> {
    return [...this.vers].reverse().slice(0, limit);
  }
}
