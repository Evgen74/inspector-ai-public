/** Upload vertical (ТЗ Module 1): multipart upload, ad-hoc registry, job queue, process status. */
import type { Provider, Type } from '@nestjs/common';
import { ArchiveController } from '../archive/archive.controller';
import { ArchiveRepository, DrizzleArchiveRepository } from '../archive/archive.repository';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { ProcessesController } from '../processes/processes.controller';
import { CommandRunner, SpawnCommandRunner } from './command-runner';
import { JobQueue } from './job-queue';
import { UploadController } from './upload.controller';
import { UploadJob } from './upload-job';
import { UploadService } from './upload.service';

export const UPLOAD_CONTROLLERS: Type<unknown>[] = [UploadController, ProcessesController, ArchiveController];

export const UPLOAD_PROVIDERS: Provider[] = [
  { provide: CommandRunner, useFactory: (config: AppConfig) => new SpawnCommandRunner(config.repoRoot), inject: [APP_CONFIG] },
  JobQueue,
  UploadJob,
  UploadService,
  // «Архивировать» (objects, imported runs, upload processes).
  { provide: ArchiveRepository, useClass: DrizzleArchiveRepository },
];
