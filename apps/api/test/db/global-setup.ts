/** Create the test database if needed and apply the migrations once per `test:db` run. */
import { ensureDatabase, testDatabaseUrl } from '../../src/db/create-db';
import { runMigrations } from '../../src/db/migrate';

export default async function setup(): Promise<void> {
  const url = testDatabaseUrl();
  await ensureDatabase(url);
  await runMigrations(url);
}
