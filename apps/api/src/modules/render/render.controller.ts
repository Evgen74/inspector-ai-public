/**
 * Evidence viewer pages (evidence.read; train objects only):
 *   GET /files/{file_id}/pages/{page_no}                      → PageView (size, rotation, Deep Zoom pyramid, URLs)
 *   GET /files/{file_id}/pages/{page_no}/image?width|dpi&bbox  → image/png (whole page or normalized crop)
 *   GET /files/{file_id}/pages/{page_no}/tiles/{level}/{x}/{y} → image/png tile
 * The PageView maps 1:1 onto an OpenSeadragon tile source: {width: width_px, height: height_px, tileSize,
 * tileOverlap, minLevel, maxLevel, getTileUrl: (l, x, y) => tile_url_template with {level}/{x}/{y} filled}.
 * Evidence geometry (bbox_polygon_norm) is in the same displayed page space: multiply by width_px/height_px.
 */
import { Controller, Get, Param, Query, Req, Res } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { optionalString } from '../../common/pagination';
import { ApiProblem } from '../../common/problem';
import { contextOf } from '../../common/request-context';
import { GLOBAL_PREFIX } from '../../bootstrap';
import { type PageImage, RenderService } from './render.service';

export interface PageViewDto {
  file_id: string;
  object_id: string;
  page_no: number;
  pdf_pages: number;
  width_pt: number;
  height_pt: number;
  rotation: number;
  max_dpi: number;
  width_px: number;
  height_px: number;
  tile_size: number;
  tile_overlap: number;
  min_level: number;
  max_level: number;
  tile_url_template: string;
  image_url: string;
}

const IMMUTABLE = 'private, max-age=86400, immutable';

function intParam(value: string, name: string, min: number, max: number): number {
  const n = Number(value);
  if (!Number.isInteger(n) || n < min || n > max) {
    throw new ApiProblem('VALIDATION_ERROR', { summary: `/path/${name} — ожидается целое число от ${min} до ${max}` });
  }
  return n;
}

function bboxParam(value: string | undefined): [number, number, number, number] | undefined {
  if (value === undefined) return undefined;
  const parts = value.split(',').map(Number);
  const [x0, y0, x1, y1] = parts as [number, number, number, number];
  if (parts.length !== 4 || parts.some((p) => !Number.isFinite(p)) || !(0 <= x0 && x0 < x1 && x1 <= 1 && 0 <= y0 && y0 < y1 && y1 <= 1)) {
    throw new ApiProblem('VALIDATION_ERROR', { summary: '/query/bbox — ожидается x0,y0,x1,y1: доли страницы, 0 ≤ x0 < x1 ≤ 1, 0 ≤ y0 < y1 ≤ 1' });
  }
  return [x0, y0, x1, y1];
}

@Controller('files')
export class RenderController {
  constructor(private readonly render: RenderService) {}

  private send(req: FastifyRequest, reply: FastifyReply, image: PageImage): Buffer {
    void reply.header('etag', image.etag).header('cache-control', IMMUTABLE).header('x-render-cache', image.cached ? 'hit' : 'miss');
    for (const [key, value] of Object.entries(image.headers)) if (key.startsWith('x-render-')) void reply.header(key, value);
    if (req.headers['if-none-match'] === image.etag) {
      void reply.status(304);
      return Buffer.alloc(0);
    }
    void reply.header('content-type', 'image/png');
    return image.bytes;
  }

  @Get(':file_id/pages/:page_no')
  async getPageView(@Param('file_id') fileId: string, @Param('page_no') pageParam: string, @Req() req: FastifyRequest): Promise<PageViewDto> {
    const pageNo = intParam(pageParam, 'page_no', 1, 100_000);
    const ctx = contextOf(req);
    const file = await this.render.checkAccess(fileId, pageNo, ctx);
    const info = await this.render.pageInfo(file, pageNo, ctx.requestId);
    const base = `/${GLOBAL_PREFIX}/files/${encodeURIComponent(fileId)}/pages/${pageNo}`;
    return {
      file_id: fileId,
      object_id: file.objectId,
      page_no: pageNo,
      pdf_pages: info.pdf_pages,
      width_pt: info.width_pt,
      height_pt: info.height_pt,
      rotation: info.rotation,
      max_dpi: info.max_dpi,
      width_px: info.width_px,
      height_px: info.height_px,
      tile_size: info.tile_size,
      tile_overlap: info.tile_overlap,
      min_level: info.min_level,
      max_level: info.max_level,
      tile_url_template: `${base}/tiles/{level}/{x}/{y}`,
      image_url: `${base}/image`,
    };
  }

  @Get(':file_id/pages/:page_no/image')
  async getPageImage(
    @Param('file_id') fileId: string,
    @Param('page_no') pageParam: string,
    @Query() query: Record<string, unknown>,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Buffer> {
    const pageNo = intParam(pageParam, 'page_no', 1, 100_000);
    const width = optionalString(query.width);
    const dpi = optionalString(query.dpi);
    const bbox = bboxParam(optionalString(query.bbox));
    const ctx = contextOf(req);
    const file = await this.render.checkAccess(fileId, pageNo, ctx);
    const image = await this.render.image(
      file,
      pageNo,
      { width: width === undefined ? (dpi === undefined ? 1600 : undefined) : Number(width), dpi: dpi === undefined ? undefined : Number(dpi), bbox },
      ctx.requestId,
    );
    return this.send(req, reply, image);
  }

  @Get(':file_id/pages/:page_no/tiles/:level/:x/:y')
  async getPageTile(
    @Param('file_id') fileId: string,
    @Param('page_no') pageParam: string,
    @Param('level') levelParam: string,
    @Param('x') xParam: string,
    @Param('y') yParam: string,
    @Req() req: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ): Promise<Buffer> {
    const pageNo = intParam(pageParam, 'page_no', 1, 100_000);
    const level = intParam(levelParam, 'level', 0, 40);
    const x = intParam(xParam, 'x', 0, 100_000);
    const y = intParam(yParam, 'y', 0, 100_000);
    const ctx = contextOf(req);
    const file = await this.render.checkAccess(fileId, pageNo, ctx);
    return this.send(req, reply, await this.render.tile(file, pageNo, level, x, y, ctx.requestId));
  }
}
