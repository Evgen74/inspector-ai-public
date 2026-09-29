/**
 * Verification module (AG-05): decisions, disputes, finalization, GOLD drafts, usability telemetry.
 *
 * Wiring (AG-00, one line each; see ./README.md):
 * - app.module.ts: `...VERIFICATION_CONTROLLERS` in controllers, `...VERIFICATION_PROVIDERS` in providers;
 * - db/schema-all.ts: `export * from '../modules/verification/verification.schema';`
 * - OpenAPI: merge ./openapi/verification.openapi.yaml into packages/contracts/openapi/openapi.yaml (or drop it
 *   into apps/api/openapi/pending/ until then);
 * - migration: ./sql/0004_verification.sql into apps/api/drizzle/ (+ journal entry).
 */
import path from 'node:path';
import type { Provider, Type } from '@nestjs/common';
import { VerificationController } from './verification.controller';
import { DrizzleVerificationRepository, VerificationRepository } from './verification.repository';
import { VerificationService } from './verification.service';

export { VerificationRepository } from './verification.repository';
export { VerificationService } from './verification.service';
export { InMemoryVerificationRepository, seedFromArtifacts } from './verification.memory';

export const VERIFICATION_CONTROLLERS: Type<unknown>[] = [VerificationController];

export const VERIFICATION_PROVIDERS: Provider[] = [
  { provide: VerificationRepository, useClass: DrizzleVerificationRepository },
  VerificationService,
];

/** apps/api/src/modules/verification (tsc copies no YAML/SQL into dist/: resolve through src/, same depth). */
const SOURCE_DIR = path.resolve(__dirname, '..', '..', '..', 'src', 'modules', 'verification');

/** The OpenAPI additions of this module. */
export const VERIFICATION_OPENAPI_OVERLAY = path.join(SOURCE_DIR, 'openapi', 'verification.openapi.yaml');

/** The SQL migration of this module's tables, constraints and triggers. */
export const VERIFICATION_MIGRATION_SQL = path.join(SOURCE_DIR, 'sql', '0004_verification.sql');
