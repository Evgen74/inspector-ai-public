/**
 * Demo account: the single super-role «Инспектор» (product owner decision 29.09): login `inspector`.
 *
 * CLI: `pnpm --filter @inspector/api db:seed [--reset-passwords]` (make db-seed). Idempotent: existing accounts keep
 * their password unless --reset-passwords. Password: INSPECTOR_DEMO_PASSWORD (default «Demo-Inspector-2026»).
 * The inspector is also assigned to the TRAIN_PUBLIC objects of split_policy.json (read from the data root, never
 * hard-coded); every permission has scope ALL, so assignments do not restrict visibility.
 */
import { readFileSync } from 'node:fs';
import { drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import { loadConfig, splitPolicyPath } from '../../config/config';
import { Database } from '../../db/database';
import * as schema from '../../db/schema-all';
import { hashPassword, passwordViolations } from './passwords';
import { DrizzleUsersRepository } from './users.repository';

export const DEFAULT_DEMO_PASSWORD = 'Demo-Inspector-2026';

export interface DemoUser {
  login: string;
  fullName: string;
  position: string;
  roles: string[];
  /** 'all' = every train object, 'first' = the first train object, 'none'. */
  assignments: 'all' | 'first' | 'none';
}

export const DEMO_USERS: readonly DemoUser[] = [
  { login: 'inspector', fullName: 'Иванова Мария Сергеевна', position: 'Главный специалист отдела надзора', roles: ['INSPECTOR'], assignments: 'all' },
];

/** TRAIN_PUBLIC object ids of the organizer split policy; [] when the data root is absent. */
export function trainObjectIds(dataRoot: string): string[] {
  try {
    const raw = JSON.parse(readFileSync(splitPolicyPath(dataRoot), 'utf8')) as { TRAIN_PUBLIC?: unknown };
    return Array.isArray(raw.TRAIN_PUBLIC) ? raw.TRAIN_PUBLIC.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export interface SeedResult {
  created: string[];
  updated: string[];
  assignments: Record<string, string[]>;
}

export async function seedDemoUsers(
  repository: DrizzleUsersRepository,
  opts: { password: string; resetPasswords: boolean; trainObjects: string[]; users?: readonly DemoUser[] },
): Promise<SeedResult> {
  const violations = await passwordViolations(opts.password, 'demo');
  if (violations.length) throw new Error(`демо-пароль не соответствует политике: ${violations.join('; ')}`);
  const passwordHash = await hashPassword(opts.password);
  const result: SeedResult = { created: [], updated: [], assignments: {} };
  for (const u of opts.users ?? DEMO_USERS) {
    const { id, created } = await repository.upsertSeedUser({
      login: u.login,
      passwordHash,
      fullName: u.fullName,
      position: u.position,
      email: null,
      roles: u.roles,
      isDemo: true,
      mustChangePassword: false,
      resetPassword: opts.resetPasswords,
    });
    (created ? result.created : result.updated).push(u.login);
    const objects = u.assignments === 'all' ? opts.trainObjects : u.assignments === 'first' ? opts.trainObjects.slice(0, 1) : [];
    await repository.setAssignments(id, objects, null);
    result.assignments[u.login] = objects;
  }
  return result;
}

async function main(): Promise<void> {
  const config = loadConfig();
  const pool = new Pool({ connectionString: config.databaseUrl, max: 2, application_name: 'inspector-seed' });
  try {
    const database = { pool, db: drizzle(pool, { schema }) } as unknown as Database;
    const repository = new DrizzleUsersRepository(database);
    const trainObjects = trainObjectIds(config.dataRoot);
    const result = await seedDemoUsers(repository, {
      password: process.env.INSPECTOR_DEMO_PASSWORD ?? DEFAULT_DEMO_PASSWORD,
      resetPasswords: process.argv.includes('--reset-passwords'),
      trainObjects,
    });
    console.log(
      `Демо-пользователи: создано ${result.created.length} (${result.created.join(', ') || '—'}), ` +
        `обновлено ${result.updated.length}; обучающих объектов для назначения: ${trainObjects.length}.`,
    );
  } finally {
    await pool.end();
  }
}

if (require.main === module) {
  main().catch((err: unknown) => {
    console.error(`Не удалось создать демо-пользователей: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(1);
  });
}
