/**
 * Page images for the evidence viewer (whole page, crop, Deep Zoom tiles), rendered by the ml-api and cached on
 * disk under `<INSPECTOR_CACHE_ROOT>/render/v1/<file sha256>/p<page>/…` (renders are immutable per file hash).
 * Concurrent requests for the same image share one render (in-flight de-duplication).
 *
 * Access: train objects only (files.split = TRAIN_PUBLIC; the ml-api re-checks split_policy.json), PDF files present
 * on disk, and — for ASSIGNED-scoped principals — objects assigned to the user.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { PinoLogger } from 'nestjs-pino';
import { ApiProblem } from '../../common/problem';
import type { RequestContext } from '../../common/request-context';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { Database } from '../../db/database';
import { files } from '../../db/schema';
import { UsersRepository } from '../auth/users.repository';
import { MlApiClient, type MlPageInfo } from './ml-api.client';

export interface RenderFile {
  fileId: string;
  objectId: string;
  sha256: string;
  split: string | null;
  extension: string | null;
  localStatus: string;
  pdfPages: number | null;
}

export abstract class RenderFilesRepository {
  abstract find(fileId: string): Promise<RenderFile | null>;
}

@Injectable()
export class DrizzleRenderFilesRepository extends RenderFilesRepository {
  constructor(private readonly database: Database) {
    super();
  }

  async find(fileId: string): Promise<RenderFile | null> {
    const [row] = await this.database.db
      .select({
        fileId: files.id,
        objectId: files.objectId,
        sha256: files.fileHash,
        split: files.split,
        extension: files.ext,
        localStatus: files.localStatus,
        pdfPages: files.pdfPages,
      })
      .from(files)
      .where(eq(files.id, fileId))
      .limit(1);
    return row ?? null;
  }
}

export interface PageImage {
  bytes: Buffer;
  etag: string;
  cached: boolean;
  headers: Record<string, string>;
}

const CACHE_VERSION = 'v1';

@Injectable()
export class RenderService {
  private readonly inflight = new Map<string, Promise<unknown>>();
  readonly stats = { hits: 0, misses: 0, shared: 0 };

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly filesRepo: RenderFilesRepository,
    private readonly users: UsersRepository,
    private readonly ml: MlApiClient,
    private readonly logger: PinoLogger,
  ) {
    this.logger.setContext(RenderService.name);
  }

  /** The file, after the access checks (existence, train split, PDF on disk, page range, assignment). */
  async checkAccess(fileId: string, pageNo: number, ctx: RequestContext): Promise<RenderFile> {
    const file = await this.filesRepo.find(fileId);
    if (!file) throw new ApiProblem('FILE_NOT_FOUND', { file_id: fileId });
    if (file.split === 'TEST_HIDDEN') throw new ApiProblem('HIDDEN_TEST_ACCESS_DENIED', { object_id: file.objectId });
    if (file.split !== 'TRAIN_PUBLIC') {
      throw new ApiProblem('FILE_NOT_RENDERABLE', { file_id: fileId, reason: 'объект не относится к обучающей выборке' });
    }
    if ((file.extension ?? '').toLowerCase() !== '.pdf') {
      throw new ApiProblem('FILE_NOT_RENDERABLE', { file_id: fileId, reason: `это не PDF (${file.extension ?? 'без расширения'})` });
    }
    if (file.localStatus === 'MISSING_ON_DISK') {
      throw new ApiProblem('FILE_NOT_RENDERABLE', { file_id: fileId, reason: 'файл отсутствует на диске' });
    }
    if (file.pdfPages !== null && (pageNo < 1 || pageNo > file.pdfPages)) {
      throw new ApiProblem('PAGE_NOT_FOUND', { file_id: fileId, page_no: pageNo, pdf_pages: file.pdfPages });
    }
    if (ctx.scope === 'ASSIGNED' && ctx.principal && !(await this.users.isAssigned(ctx.principal.userId, file.objectId))) {
      throw new ApiProblem('FORBIDDEN');
    }
    return file;
  }

  private dir(file: RenderFile, pageNo: number): string {
    return path.join(this.config.cacheRoot, 'render', CACHE_VERSION, file.sha256, `p${String(pageNo).padStart(5, '0')}`);
  }

  /** Read-through disk cache with in-flight de-duplication; writes are atomic (tmp + rename). */
  private async cached<T>(
    file: string,
    load: () => Promise<T>,
    encode: (v: T) => Buffer,
    decode: (b: Buffer) => T,
  ): Promise<{ value: T; cached: boolean }> {
    try {
      const value = decode(await readFile(file));
      this.stats.hits += 1;
      return { value, cached: true };
    } catch {
      // miss
    }
    const running = this.inflight.get(file) as Promise<T> | undefined;
    if (running) {
      this.stats.shared += 1;
      return { value: await running, cached: false };
    }
    this.stats.misses += 1;
    const job = (async () => {
      const value = await load();
      try {
        await mkdir(path.dirname(file), { recursive: true });
        const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
        await writeFile(tmp, encode(value));
        await rename(tmp, file);
      } catch (err) {
        this.logger.warn({ event: 'render_cache_write_failed', err, file_name: path.basename(file) }, 'render cache write failed');
      }
      return value;
    })();
    this.inflight.set(file, job);
    try {
      return { value: await job, cached: false };
    } finally {
      this.inflight.delete(file);
    }
  }

  private checkSha(file: RenderFile, sha: string | undefined): void {
    if (sha && sha !== file.sha256) {
      throw new ApiProblem('PAGE_RENDERER_UNAVAILABLE', {
        reason: `ml-api отдаёт другой файл ${file.fileId} (sha256 ${sha.slice(0, 12)}… ≠ ${file.sha256.slice(0, 12)}…)`,
      });
    }
  }

  async pageInfo(file: RenderFile, pageNo: number, requestId: string): Promise<MlPageInfo> {
    const { value } = await this.cached(
      path.join(this.dir(file, pageNo), 'info.json'),
      () => this.ml.pageInfo(file.fileId, pageNo, requestId),
      (v) => Buffer.from(JSON.stringify(v)),
      (b) => JSON.parse(b.toString('utf8')) as MlPageInfo,
    );
    this.checkSha(file, value.sha256);
    return value;
  }

  async tile(file: RenderFile, pageNo: number, level: number, x: number, y: number, requestId: string): Promise<PageImage> {
    const key = `t_L${level}_${x}_${y}`;
    let headers: Record<string, string> = {};
    const { value, cached } = await this.cached(
      path.join(this.dir(file, pageNo), `${key}.png`),
      async () => {
        const png = await this.ml.renderPng('tile', { file_id: file.fileId, page_no: pageNo, level, x, y }, requestId);
        this.checkSha(file, png.headers['x-file-sha256']);
        headers = png.headers;
        return png.bytes;
      },
      (v) => v,
      (b) => b,
    );
    return { bytes: value, cached, headers, etag: `"${file.sha256.slice(0, 16)}-${pageNo}-${key}"` };
  }

  async image(
    file: RenderFile,
    pageNo: number,
    opts: { width?: number; dpi?: number; bbox?: [number, number, number, number] },
    requestId: string,
  ): Promise<PageImage> {
    const spec = { width: opts.width ?? null, dpi: opts.dpi ?? null, bbox: opts.bbox ?? null };
    const key = `i_${createHash('sha256').update(JSON.stringify(spec)).digest('hex').slice(0, 16)}`;
    let headers: Record<string, string> = {};
    const { value, cached } = await this.cached(
      path.join(this.dir(file, pageNo), `${key}.png`),
      async () => {
        const body: Record<string, unknown> = { file_id: file.fileId, page_no: pageNo };
        if (opts.width !== undefined) body.width = opts.width;
        if (opts.dpi !== undefined) body.dpi = opts.dpi;
        if (opts.bbox) body.bbox = opts.bbox;
        const png = await this.ml.renderPng(opts.bbox ? 'crop' : 'page', body, requestId);
        this.checkSha(file, png.headers['x-file-sha256']);
        headers = png.headers;
        return png.bytes;
      },
      (v) => v,
      (b) => b,
    );
    return { bytes: value, cached, headers, etag: `"${file.sha256.slice(0, 16)}-${pageNo}-${key}"` };
  }
}
