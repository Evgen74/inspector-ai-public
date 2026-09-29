/**
 * Page annotations for the evidence viewer: revision clouds and room labels of one page, from the
 * `layout/<file_id>.json` artifact (layout_artifacts.schema.json, AG-02B) of the newest imported run that has
 * it. The page images themselves come from AG-00's render service; this only overlays run facts on them.
 */
import { Controller, Get, Injectable, Param, Query } from '@nestjs/common';
import { ApiProblem } from '../../common/problem';
import { isHiddenSplit } from '../protocols/protocols.service';
import { CatalogLookup } from '../shared/lookup.repository';
import { RunArtifacts } from '../shared/run-artifacts';

type BBox = [number, number, number, number];

export interface PageAnnotationsDto {
  file_id: string;
  page: number;
  run_id: string | null;
  batch_run_id: string | null;
  revision_clouds: Array<{
    bbox: BBox;
    source: string;
    layer: string | null;
    revision_label: string | null;
    rooms_covered: string[];
  }>;
  rooms: Array<{ room_token: string; bbox: BBox; name: string | null }>;
}

interface LayoutLike {
  file_id: string;
  revision_clouds?: Array<{
    pdf_page_number: number;
    bbox: BBox;
    source: string;
    layer?: string | null;
    revision_label?: string | null;
    rooms_covered?: string[];
  }>;
  rooms?: Array<{ room_token: string; pdf_page_number: number; bbox?: BBox; name?: string | null }>;
}

@Injectable()
export class AnnotationsService {
  constructor(
    private readonly lookup: CatalogLookup,
    private readonly artifacts: RunArtifacts,
  ) {}

  async forPage(fileId: string, page: number): Promise<PageAnnotationsDto> {
    const file = await this.lookup.getFile(fileId);
    if (!file) throw new ApiProblem('FILE_NOT_FOUND', { file_id: fileId });
    if (isHiddenSplit(file.split)) throw new ApiProblem('HIDDEN_TEST_ACCESS_DENIED', { object_id: file.objectId });
    const empty: PageAnnotationsDto = { file_id: fileId, page, run_id: null, batch_run_id: null, revision_clouds: [], rooms: [] };
    // A newer run may carry a layout of this file without the page's markup (or a stale fixture run may shadow
    // a real one): take the first run whose layout has clouds or rooms on this page, else the first with a layout.
    let fallback: PageAnnotationsDto | null = null;
    for (const run of await this.lookup.runsForObject(file.objectId)) {
      const ref = this.artifacts.locate(run, 'LAYOUT', { fileId });
      if (!ref) continue;
      const layout = this.artifacts.readJson(ref.absPath, 'layout_artifacts', `${run.batchRunId}/${ref.relPath}`) as LayoutLike;
      const dto: PageAnnotationsDto = {
        file_id: fileId,
        page,
        run_id: run.id,
        batch_run_id: run.batchRunId,
        revision_clouds: (layout.revision_clouds ?? [])
          .filter((c) => c.pdf_page_number === page)
          .map((c) => ({
            bbox: c.bbox,
            source: c.source,
            layer: c.layer ?? null,
            revision_label: c.revision_label ?? null,
            rooms_covered: c.rooms_covered ?? [],
          })),
        rooms: (layout.rooms ?? [])
          .filter((r): r is typeof r & { bbox: BBox } => r.pdf_page_number === page && Array.isArray(r.bbox))
          .map((r) => ({ room_token: r.room_token, bbox: r.bbox, name: r.name ?? null })),
      };
      if (dto.revision_clouds.length > 0 || dto.rooms.length > 0) return dto;
      fallback ??= dto;
    }
    if (fallback) return fallback;
    return empty;
  }
}

@Controller('files/:file_id/annotations')
export class AnnotationsController {
  constructor(private readonly annotations: AnnotationsService) {}

  @Get()
  async getFileAnnotations(
    @Param('file_id') fileId: string,
    @Query() query: Record<string, unknown>,
  ): Promise<PageAnnotationsDto> {
    return this.annotations.forPage(fileId, Number(query.page));
  }
}
