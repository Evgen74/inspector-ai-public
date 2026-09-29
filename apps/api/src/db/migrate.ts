/**
 * Apply the SQL migrations in apps/api/drizzle/ (idempotent; drizzle keeps its journal in drizzle.__drizzle_migrations).
 * CLI: `pnpm --filter @inspector/api db:migrate` (uses INSPECTOR_DATABASE_URL).
 */
import path from 'node:path';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import { Pool } from 'pg';

/** <pkg>/{src,dist}/db → <pkg>/drizzle */
export const MIGRATIONS_DIR = path.resolve(__dirname, '..', '..', 'drizzle');

export async function runMigrations(databaseUrl: string): Promise<void> {
  const pool = new Pool({ connectionString: databaseUrl, max: 1, application_name: 'inspector-migrate' });
  try {
    await migrate(drizzle(pool), { migrationsFolder: MIGRATIONS_DIR });
  } finally {
    await pool.end();
  }
}

async function main(): Promise<void> {
  const url = process.env.INSPECTOR_DATABASE_URL ?? 'postgresql://localhost:5432/inspector';
  await runMigrations(url);
  console.log(`Миграции применены: ${url.replace(/\/\/[^@]*@/, '//***@')}`);
}

if (require.main === module) {
  main().catch((err: unknown) => {
    console.error(`Не удалось применить миграции: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(1);
  });
}
