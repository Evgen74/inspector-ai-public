/**
 * Every Drizzle table of the API in one module: the Database instance and drizzle-kit (drizzle.config.ts) read
 * this file. Tables are defined next to their owners:
 * - ./schema.ts — runs, objects, files (M0 inventory import; AG-08);
 * - ../modules/auth/auth.schema.ts — users, user_roles, object_assignments (AG-00);
 * - ../modules/audit/audit.schema.ts — audit_log (AG-00);
 * - ../modules/import/import.schema.ts — processes … run_artifacts filled by the batch-run import v2 (AG-00).
 * - ../modules/verification/verification.schema.ts — decisions, disputes, GOLD drafts (AG-05).
 */
export * from './schema';
export * from '../modules/auth/auth.schema';
export * from '../modules/audit/audit.schema';
export * from '../modules/import/import.schema';
export * from '../modules/verification/verification.schema';
