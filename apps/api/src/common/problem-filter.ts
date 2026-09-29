/**
 * Every error leaves the API as application/problem+json (RFC 9457, packages/contracts/schemas/problem.schema.json).
 *
 * `ProblemFilter` handles errors raised inside Nest (guards, controllers, services, the 404 handler);
 * `fastifyErrorToProblem` handles errors raised by Fastify before Nest runs (body parsing, media type, size).
 */
import { type ArgumentsHost, Catch, type ExceptionFilter, HttpException, Injectable } from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { PinoLogger } from 'nestjs-pino';
import { ApiProblem, ErrorCatalog, type ProblemBody } from './problem';

export const PROBLEM_CONTENT_TYPE = 'application/problem+json; charset=utf-8';

/** node-postgres / network failures that mean «database unavailable». */
const DB_UNAVAILABLE_CODES = new Set([
  'ECONNREFUSED',
  'ECONNRESET',
  'ETIMEDOUT',
  'ENOTFOUND',
  'EHOSTUNREACH',
  '57P01', // admin_shutdown
  '57P02', // crash_shutdown
  '57P03', // cannot_connect_now
  '08000', // connection_exception
  '08001', // sqlclient_unable_to_establish_sqlconnection
  '08003', // connection_does_not_exist
  '08006', // connection_failure
  '3D000', // invalid_catalog_name (database does not exist)
  '28000', // invalid_authorization_specification
]);

export function isDbUnavailable(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const err = error as { code?: unknown; cause?: unknown; errors?: unknown[] };
  if (typeof err.code === 'string' && DB_UNAVAILABLE_CODES.has(err.code)) return true;
  if (Array.isArray(err.errors) && err.errors.some(isDbUnavailable)) return true; // AggregateError
  if (err.cause && err.cause !== error) return isDbUnavailable(err.cause);
  const message = (error as Error).message ?? '';
  return /Connection terminated|connection timeout|timeout exceeded when trying to connect/i.test(message);
}

const HTTP_STATUS_CODES: Record<number, string> = {
  400: 'VALIDATION_ERROR',
  404: 'NOT_FOUND',
  405: 'METHOD_NOT_ALLOWED',
  406: 'NOT_ACCEPTABLE',
  408: 'REQUEST_TIMEOUT',
  413: 'PAYLOAD_TOO_LARGE',
  415: 'UNSUPPORTED_MEDIA_TYPE',
  429: 'RATE_LIMITED',
  503: 'SERVICE_UNAVAILABLE',
};

function pathOf(url: string): string {
  const q = url.indexOf('?');
  return q === -1 ? url : url.slice(0, q);
}

export function toProblem(catalog: ErrorCatalog, error: unknown, req: FastifyRequest): ProblemBody {
  const base = { instancePath: pathOf(req.url), requestId: req.id };
  if (error instanceof ApiProblem) {
    return catalog.problem({
      ...base,
      code: error.code,
      details: error.details,
      status: error.options.status,
      errors: error.options.errors,
      warnings: error.options.warnings,
    });
  }
  if (isDbUnavailable(error)) {
    return catalog.problem({ ...base, code: 'DB_UNAVAILABLE', details: { retry_after_s: 5, request_id: req.id } });
  }
  const fst = error as { code?: string; statusCode?: number; message?: string };
  if (typeof fst?.code === 'string' && fst.code.startsWith('FST_ERR_CTP_')) {
    if (fst.code === 'FST_ERR_CTP_INVALID_MEDIA_TYPE') {
      return catalog.problem({
        ...base,
        code: 'UNSUPPORTED_MEDIA_TYPE',
        details: { content_type: String(req.headers['content-type'] ?? '') },
      });
    }
    if (fst.code === 'FST_ERR_CTP_BODY_TOO_LARGE') {
      return catalog.problem({ ...base, code: 'PAYLOAD_TOO_LARGE', details: { limit_bytes: req.routeOptions?.bodyLimit } });
    }
    return catalog.problem({ ...base, code: 'MALFORMED_JSON' });
  }
  if (error instanceof SyntaxError || fst?.code === 'FST_ERR_CTP_INVALID_JSON_BODY') {
    return catalog.problem({ ...base, code: 'MALFORMED_JSON' });
  }
  const status = error instanceof HttpException ? error.getStatus() : (fst?.statusCode ?? 500);
  const mapped = HTTP_STATUS_CODES[status];
  // Nest maps Fastify's own errors (body parsing, media type, size) to HttpException(message, status),
  // dropping the FST_ERR_* code; our code never throws a bare HttpException, so status + message identify them.
  if (status === 400 && /JSON/i.test(fst?.message ?? '')) {
    return catalog.problem({ ...base, code: 'MALFORMED_JSON' });
  }
  if (status === 415) {
    return catalog.problem({
      ...base,
      code: 'UNSUPPORTED_MEDIA_TYPE',
      details: { content_type: String(req.headers['content-type'] ?? '') },
    });
  }
  if (status === 413) {
    return catalog.problem({ ...base, code: 'PAYLOAD_TOO_LARGE', details: { limit_bytes: req.routeOptions?.bodyLimit } });
  }
  if (mapped === 'VALIDATION_ERROR') {
    return catalog.problem({ ...base, code: mapped, details: { summary: fst?.message ?? 'некорректный запрос' } });
  }
  if (mapped === 'METHOD_NOT_ALLOWED') {
    return catalog.problem({ ...base, code: mapped, details: { method: req.method } });
  }
  if (mapped === 'SERVICE_UNAVAILABLE') {
    return catalog.problem({ ...base, code: mapped, details: { retry_after_s: 5 } });
  }
  if (mapped) return catalog.problem({ ...base, code: mapped });
  return catalog.problem({ ...base, code: 'INTERNAL_ERROR', details: { request_id: req.id } });
}

export interface ProblemLogger {
  error(obj: object, msg: string): void;
  info(obj: object, msg: string): void;
}

export function logProblem(logger: ProblemLogger, problem: ProblemBody, error: unknown): void {
  const fields = { event: 'request_failed', error_code: problem.code, status: problem.status };
  if (problem.status >= 500) {
    logger.error({ ...fields, err: error }, problem.detail);
  } else {
    logger.info(fields, problem.detail);
  }
}

@Catch()
@Injectable()
export class ProblemFilter implements ExceptionFilter {
  constructor(
    private readonly catalog: ErrorCatalog,
    private readonly logger: PinoLogger,
  ) {
    this.logger.setContext(ProblemFilter.name);
  }

  catch(exception: unknown, host: ArgumentsHost): void {
    const http = host.switchToHttp();
    const req = http.getRequest<FastifyRequest>();
    const reply = http.getResponse<FastifyReply>();
    const problem = toProblem(this.catalog, exception, req);
    logProblem(this.logger, problem, exception);
    if (problem.code === 'DB_UNAVAILABLE' || problem.code === 'SERVICE_UNAVAILABLE') {
      void reply.header('retry-after', '5');
    }
    void reply.status(problem.status).header('content-type', PROBLEM_CONTENT_TYPE).send(problem);
  }
}
