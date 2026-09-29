/** Batch-run import v2 (AG-00): run artifacts → processes, protocols, checks, evidence, suspicions, submissions. */
import type { Provider } from '@nestjs/common';
import { DrizzleRunImportRepository, RunImportRepository } from './run-import.repository';
import { RunImportService } from './run-import.service';

export { RunImportRepository } from './run-import.repository';
export { RunImportService } from './run-import.service';

export const IMPORT_PROVIDERS: Provider[] = [{ provide: RunImportRepository, useClass: DrizzleRunImportRepository }, RunImportService];
