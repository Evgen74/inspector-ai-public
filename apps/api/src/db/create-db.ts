/**
 * Create the local PostgreSQL database if it does not exist (same effect as `make db-create`).
 * CLI: `pnpm --filter @inspector/api db:create` → INSPECTOR_DATABASE_URL (default …/inspector);
 *      `… db:create --test` → INSPECTOR_TEST_DATABASE_URL (default …/inspector_test).
 */
import { Client } from 'pg';

export const DEFAULT_DATABASE_URL = 'postgresql://localhost:5432/inspector';
export const DEFAULT_TEST_DATABASE_URL = 'postgresql://localhost:5432/inspector_test';

export function testDatabaseUrl(env: NodeJS.ProcessEnv = process.env): string {
  return env.INSPECTOR_TEST_DATABASE_URL ?? DEFAULT_TEST_DATABASE_URL;
}

/** Returns true when the database was created, false when it already existed. */
export async function ensureDatabase(databaseUrl: string): Promise<boolean> {
  const url = new URL(databaseUrl);
  const name = decodeURIComponent(url.pathname.replace(/^\//, ''));
  if (!/^[A-Za-z0-9_]{1,63}$/.test(name)) throw new Error(`недопустимое имя базы данных: ${name}`);
  url.pathname = '/postgres';
  const client = new Client({ connectionString: url.toString(), application_name: 'inspector-db-create' });
  await client.connect();
  try {
    const found = await client.query('SELECT 1 FROM pg_database WHERE datname = $1', [name]);
    if (found.rowCount) return false;
    await client.query(`CREATE DATABASE "${name}"`);
    return true;
  } finally {
    await client.end();
  }
}

async function main(): Promise<void> {
  const url = process.argv.includes('--test')
    ? testDatabaseUrl()
    : (process.env.INSPECTOR_DATABASE_URL ?? DEFAULT_DATABASE_URL);
  const name = new URL(url).pathname.slice(1);
  const created = await ensureDatabase(url);
  console.log(created ? `База ${name} создана.` : `База ${name} уже существует.`);
}

if (require.main === module) {
  main().catch((err: unknown) => {
    console.error(`Не удалось создать базу данных: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(1);
  });
}
