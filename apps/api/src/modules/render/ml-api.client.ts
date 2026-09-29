/**
 * HTTP client of the internal ml-api (services/ml/apps/ml_api, FastAPI on 127.0.0.1:8090 by default).
 * A problem+json answer is re-raised as the same catalogue code; a network failure or timeout becomes
 * PAGE_RENDERER_UNAVAILABLE (503, retryable).
 */
import { Inject, Injectable } from '@nestjs/common';
import { ApiProblem } from '../../common/problem';
import { APP_CONFIG, type AppConfig } from '../../config/config';

export interface MlPageInfo {
  file_id: string;
  object_id: string;
  sha256: string;
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
}

export interface MlPng {
  bytes: Buffer;
  headers: Record<string, string>;
}

/** Codes the ml-api may answer with; anything else is treated as the renderer being unusable. */
const PASS_THROUGH = new Set([
  'FILE_NOT_FOUND',
  'PAGE_NOT_FOUND',
  'FILE_NOT_RENDERABLE',
  'HIDDEN_TEST_ACCESS_DENIED',
  'EXCLUDED_FILE_REFERENCED',
  'VALIDATION_ERROR',
]);

export abstract class MlApiClient {
  abstract pageInfo(fileId: string, pageNo: number, requestId: string): Promise<MlPageInfo>;
  abstract renderPng(route: 'page' | 'crop' | 'tile', body: Record<string, unknown>, requestId: string): Promise<MlPng>;
}

@Injectable()
export class HttpMlApiClient extends MlApiClient {
  constructor(@Inject(APP_CONFIG) private readonly config: AppConfig) {
    super();
  }

  private async post(route: string, body: Record<string, unknown>, requestId: string): Promise<Response> {
    const headers: Record<string, string> = { 'content-type': 'application/json', 'x-request-id': requestId };
    if (this.config.mlApiToken) headers['x-service-token'] = this.config.mlApiToken;
    let res: Response;
    try {
      res = await fetch(`${this.config.mlApiUrl}/v1/render/${route}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(this.config.mlApiTimeoutMs),
      });
    } catch (err) {
      const e = err as { name?: string; cause?: { code?: string } };
      const reason =
        e.name === 'TimeoutError'
          ? `нет ответа за ${Math.round(this.config.mlApiTimeoutMs / 1000)} с`
          : `${this.config.mlApiUrl} не отвечает${e.cause?.code ? ` (${e.cause.code})` : ''}`;
      throw new ApiProblem('PAGE_RENDERER_UNAVAILABLE', { reason });
    }
    if (res.ok) return res;
    let problem: { code?: string; details?: Record<string, unknown>; detail?: string } = {};
    try {
      problem = (await res.json()) as typeof problem;
    } catch {
      // not JSON
    }
    if (problem.code && PASS_THROUGH.has(problem.code)) {
      throw new ApiProblem(problem.code, problem.details ?? {}, { status: problem.code === 'EXCLUDED_FILE_REFERENCED' ? 422 : undefined });
    }
    throw new ApiProblem('PAGE_RENDERER_UNAVAILABLE', {
      reason: `ml-api ответил ${res.status}${problem.code ? ` ${problem.code}` : ''}`,
    });
  }

  async pageInfo(fileId: string, pageNo: number, requestId: string): Promise<MlPageInfo> {
    const res = await this.post('page-info', { file_id: fileId, page_no: pageNo }, requestId);
    return (await res.json()) as MlPageInfo;
  }

  async renderPng(route: 'page' | 'crop' | 'tile', body: Record<string, unknown>, requestId: string): Promise<MlPng> {
    const res = await this.post(route, body, requestId);
    const headers: Record<string, string> = {};
    res.headers.forEach((value, key) => {
      if (key.startsWith('x-render-') || key === 'x-file-sha256') headers[key] = value;
    });
    return { bytes: Buffer.from(await res.arrayBuffer()), headers };
  }
}
