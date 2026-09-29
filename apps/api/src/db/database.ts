/** PostgreSQL pool + Drizzle instance (node-postgres). One pool per API process. */
import { Inject, Injectable, type OnModuleDestroy } from '@nestjs/common';
import { drizzle, type NodePgDatabase } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import { APP_CONFIG, type AppConfig } from '../config/config';
import * as schema from './schema-all';

export type Db = NodePgDatabase<typeof schema>;

export function createPool(databaseUrl: string): Pool {
  return new Pool({
    connectionString: databaseUrl,
    max: 10,
    connectionTimeoutMillis: 3000,
    idleTimeoutMillis: 30_000,
    application_name: 'inspector-api',
  });
}

@Injectable()
export class Database implements OnModuleDestroy {
  readonly pool: Pool;
  readonly db: Db;

  constructor(@Inject(APP_CONFIG) config: AppConfig) {
    this.pool = createPool(config.databaseUrl);
    // Idle-client errors (e.g. the server restarts) must not crash the process; queries surface them.
    this.pool.on('error', () => undefined);
    this.db = drizzle(this.pool, { schema });
  }

  /** Round-trip latency in ms, or throws when the database is unreachable. */
  async ping(): Promise<number> {
    const started = performance.now();
    await this.pool.query('SELECT 1');
    return Math.round(performance.now() - started);
  }

  async onModuleDestroy(): Promise<void> {
    await this.pool.end();
  }
}
