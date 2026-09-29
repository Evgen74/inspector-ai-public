import { Controller, Get, Query } from '@nestjs/common';
import { type MonitoringOverview, MonitoringService } from './monitoring.service';

@Controller('admin/monitoring')
export class MonitoringController {
  constructor(private readonly monitoring: MonitoringService) {}

  @Get('overview')
  overview(@Query() query: Record<string, unknown>): Promise<MonitoringOverview> {
    const n = Number(query.log_lines);
    return this.monitoring.overview(Number.isFinite(n) && n > 0 ? Math.min(n, 500) : 50);
  }
}
