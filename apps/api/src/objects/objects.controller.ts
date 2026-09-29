import { Controller, Get, Param, Query } from '@nestjs/common';
import type { FileItemDto, ObjectDetailDto, ObjectSummaryDto, Page } from '../api-types';
import { optionalString, parsePage } from '../common/pagination';
import { ApiProblem } from '../common/problem';
import { DashboardService } from '../modules/dashboard/dashboard.service';
import { ObjectsRepository } from './objects.repository';

@Controller('objects')
export class ObjectsController {
  constructor(
    private readonly repository: ObjectsRepository,
    private readonly dashboard: DashboardService,
  ) {}

  /** Colour and scenario come from the latest protocol, by the dashboard's own function. */
  private async withIndicator<T extends ObjectSummaryDto>(item: T): Promise<T> {
    try {
      const ind = await this.dashboard.indicatorOf(item.object_id);
      return ind
        ? {
            ...item,
            name: ind.name ?? item.name,
            indicator_color: ind.color,
            scenario: ind.scenario ?? item.scenario,
            ...('address' in item ? { address: (item as { address: string | null }).address ?? ind.address } : {}),
          }
        : item;
    } catch {
      return item;
    }
  }

  @Get()
  async listObjects(@Query() query: Record<string, unknown>): Promise<Page<ObjectSummaryDto>> {
    const { page, pageSize } = parsePage(query);
    const { items, total } = await this.repository.listObjects({
      page,
      pageSize,
      q: optionalString(query.q),
      includeArchived: query.include_archived === 'true' || query.include_archived === '1',
    });
    return { items: await Promise.all(items.map((i) => this.withIndicator(i))), total, page, page_size: pageSize };
  }

  @Get(':object_id')
  async getObject(@Param('object_id') objectId: string): Promise<ObjectDetailDto> {
    const object = await this.repository.getObject(objectId);
    if (!object) throw new ApiProblem('NOT_FOUND', { object_id: objectId });
    return this.withIndicator(object);
  }

  @Get(':object_id/files')
  async listObjectFiles(
    @Param('object_id') objectId: string,
    @Query() query: Record<string, unknown>,
  ): Promise<Page<FileItemDto>> {
    const { page, pageSize } = parsePage(query);
    const result = await this.repository.listFiles(objectId, {
      page,
      pageSize,
      stage: optionalString(query.stage),
      localStatus: optionalString(query.local_status),
      q: optionalString(query.q),
    });
    if (!result) throw new ApiProblem('NOT_FOUND', { object_id: objectId });
    return { items: result.items, total: result.total, page, page_size: pageSize };
  }
}
