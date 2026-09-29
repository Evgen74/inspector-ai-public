/** Module 10 REST: GET /ml/reports/weekly (JSON) and /ml/reports/weekly.html (printable). Permission retraining.read. */
import { Controller, Get, Header, Query } from '@nestjs/common';
import { MlReportService } from './ml-report.service';

@Controller('ml/reports')
export class MlReportController {
  constructor(private readonly service: MlReportService) {}

  @Get('weekly')
  weekly(@Query('from') from?: string, @Query('to') to?: string): Promise<Record<string, unknown>> {
    return this.service.weekly(from, to);
  }

  @Get('weekly.html')
  @Header('Content-Type', 'text/html; charset=utf-8')
  async html(@Query('from') from?: string, @Query('to') to?: string): Promise<Buffer> {
    return Buffer.from(await this.service.weeklyHtml(from, to), 'utf8');
  }
}
