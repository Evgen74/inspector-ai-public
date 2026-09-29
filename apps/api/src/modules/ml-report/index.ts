/** Module 10 weekly ML report (AG-08/AG-05): wiring `...ML_REPORT_CONTROLLERS` / `...ML_REPORT_PROVIDERS` in AppModule. */
import type { Provider, Type } from '@nestjs/common';
import { MlReportController } from './ml-report.controller';
import { MlReportService, MlReportSource, PgMlReportSource } from './ml-report.service';

export { MlReportService, MlReportSource, InMemoryMlReportSource } from './ml-report.service';
export { buildReport, renderHtml } from './report';

export const ML_REPORT_CONTROLLERS: Type<unknown>[] = [MlReportController];
export const ML_REPORT_PROVIDERS: Provider[] = [{ provide: MlReportSource, useClass: PgMlReportSource }, MlReportService];
