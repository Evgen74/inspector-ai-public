import { type DynamicModule, Module } from '@nestjs/common';
import { APP_FILTER, APP_GUARD, APP_INTERCEPTOR } from '@nestjs/core';
import { LoggerModule } from 'nestjs-pino';
import type { DestinationStream } from 'pino';
import { BatchImportService } from './batch-import/batch-import.service';
import { BatchRunsController } from './batch-import/batch-runs.controller';
import { BatchRunsRepository, DrizzleBatchRunsRepository } from './batch-import/batch-runs.repository';
import { pinoHttpConfig } from './common/logging';
import { ErrorCatalog } from './common/problem';
import { ProblemFilter } from './common/problem-filter';
import { APP_CONFIG, type AppConfig } from './config/config';
import { ContractSchemas } from './contracts/contracts';
import { Database } from './db/database';
import { HealthController } from './health/health.controller';
import { D1_CONTROLLERS, D1_PROVIDERS } from './modules/d1.providers';
import { ObjectsController } from './objects/objects.controller';
import { DrizzleObjectsRepository, ObjectsRepository } from './objects/objects.repository';
import { OpenApiRequestGuard, OpenApiResponseInterceptor } from './openapi/openapi-validation';
import { OpenApiService } from './openapi/openapi.service';
import { RequestContextInterceptor } from './common/request-context';
import { AUDIT_CONTROLLERS, AUDIT_PROVIDERS } from './modules/audit';
import { AUTH_CONTROLLERS, AUTH_PROVIDERS, AuthGuard } from './modules/auth';
import { IMPORT_PROVIDERS } from './modules/import';
import { MONITORING_CONTROLLERS, MONITORING_PROVIDERS } from './modules/monitoring';
import { RENDER_CONTROLLERS, RENDER_PROVIDERS } from './modules/render';
import { SelftestController, SelftestService } from './modules/selftest';
import { UPLOAD_CONTROLLERS, UPLOAD_PROVIDERS } from './modules/upload';
import { VERIFICATION_CONTROLLERS, VERIFICATION_PROVIDERS } from './modules/verification';
import { ML_REPORT_CONTROLLERS, ML_REPORT_PROVIDERS } from './modules/ml-report';
import { NORMATIVE_CONTROLLERS, NORMATIVE_PROVIDERS } from './modules/normative';
import { RIN_CONTROLLERS, RIN_PROVIDERS } from './modules/rin';

export interface AppModuleOptions {
  /** Test hook: capture JSON log lines instead of writing to stdout. */
  logStream?: DestinationStream;
}

@Module({})
export class AppModule {
  static forRoot(config: AppConfig, options: AppModuleOptions = {}): DynamicModule {
    return {
      module: AppModule,
      imports: [LoggerModule.forRoot({ pinoHttp: pinoHttpConfig(config, options.logStream) })],
      controllers: [
        HealthController,
        ObjectsController,
        BatchRunsController,
        ...D1_CONTROLLERS,
        // Platform services (AG-00).
        ...AUTH_CONTROLLERS,
        ...AUDIT_CONTROLLERS,
        ...RENDER_CONTROLLERS,
        // Monitoring and negative-scenario self-check (modules 11, 12).
        ...MONITORING_CONTROLLERS,
        SelftestController,
        // Verification & learning loop (AG-05).
        ...VERIFICATION_CONTROLLERS,
        // Upload vertical (ТЗ Module 1): documents upload, process status.
        ...UPLOAD_CONTROLLERS,
        // ТЗ modules 6, 8, 10 (AG-08).
        ...NORMATIVE_CONTROLLERS,
        ...RIN_CONTROLLERS,
        ...ML_REPORT_CONTROLLERS,
      ],
      providers: [
        { provide: APP_CONFIG, useValue: config },
        { provide: ErrorCatalog, useFactory: () => ErrorCatalog.load(config.contractsDir) },
        { provide: ContractSchemas, useFactory: () => new ContractSchemas(config.contractsDir) },
        OpenApiService,
        Database,
        { provide: ObjectsRepository, useClass: DrizzleObjectsRepository },
        { provide: BatchRunsRepository, useClass: DrizzleBatchRunsRepository },
        BatchImportService,
        ...D1_PROVIDERS,
        // Platform services (AG-00): auth + RBAC, audit, batch-run import v2, page rendering.
        ...AUTH_PROVIDERS,
        ...AUDIT_PROVIDERS,
        ...IMPORT_PROVIDERS,
        ...RENDER_PROVIDERS,
        ...MONITORING_PROVIDERS,
        SelftestService,
        // Verification & learning loop (AG-05).
        ...VERIFICATION_PROVIDERS,
        ...UPLOAD_PROVIDERS,
        ...NORMATIVE_PROVIDERS,
        ...RIN_PROVIDERS,
        ...ML_REPORT_PROVIDERS,
        // Global guards run in this order: authentication/RBAC (401/403) before request validation (400).
        { provide: APP_GUARD, useClass: AuthGuard },
        { provide: APP_GUARD, useClass: OpenApiRequestGuard },
        // The outermost interceptor binds the request context (AsyncLocalStorage) around the handler.
        { provide: APP_INTERCEPTOR, useClass: RequestContextInterceptor },
        { provide: APP_INTERCEPTOR, useClass: OpenApiResponseInterceptor },
        { provide: APP_FILTER, useClass: ProblemFilter },
      ],
    };
  }
}
