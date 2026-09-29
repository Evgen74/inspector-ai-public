import { Controller, Get, Query } from '@nestjs/common';
import { optionalString } from '../../common/pagination';
import type { IndicatorColor } from './indicator';
import { type DashboardDto, DashboardService } from './dashboard.service';

/** `a,b` or repeated `?x=a&x=b` → ['a', 'b'] (the OpenAPI document declares form/explode=false arrays). */
export function csvList(value: unknown): string[] | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  const parts = (Array.isArray(value) ? value : [value]).flatMap((v) => String(v).split(','));
  const out = parts.map((p) => p.trim()).filter(Boolean);
  return out.length ? out : undefined;
}

@Controller('dashboard')
export class DashboardController {
  constructor(private readonly dashboard: DashboardService) {}

  @Get()
  async getDashboard(@Query() query: Record<string, unknown>): Promise<DashboardDto> {
    return this.dashboard.dashboard({
      q: optionalString(query.q),
      color: csvList(query.color) as IndicatorColor[] | undefined,
      section: csvList(query.section),
      status: csvList(query.status),
      scenario: optionalString(query.scenario),
      dateFrom: optionalString(query.date_from),
      dateTo: optionalString(query.date_to),
      includeArchived: query.include_archived === 'true' || query.include_archived === '1',
    });
  }
}
