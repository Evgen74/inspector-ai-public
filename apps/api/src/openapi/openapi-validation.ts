/**
 * Guard: every request is validated against the OpenAPI document before the handler runs.
 * Interceptor: in local/test/demo, every JSON response is validated too (mismatch → 500 RESPONSE_SCHEMA_VIOLATION).
 */
import {
  type CallHandler,
  type CanActivate,
  type ExecutionContext,
  Inject,
  Injectable,
  type NestInterceptor,
} from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { PinoLogger } from 'nestjs-pino';
import { map, type Observable } from 'rxjs';
import type { Operation } from 'openapi-backend';
import { APP_CONFIG, type AppConfig } from '../config/config';
import { ApiProblem, ErrorCatalog } from '../common/problem';
import { OpenApiService } from './openapi.service';

type RequestWithOperation = FastifyRequest & { oasOperation?: Operation };

function pathOf(url: string): string {
  const q = url.indexOf('?');
  return q === -1 ? url : url.slice(0, q);
}

/** Content type of a request body that the operation does not declare, else null. */
function unsupportedMediaType(req: FastifyRequest, operation: Operation): string | null {
  const hasBody =
    Number(req.headers['content-length'] ?? 0) > 0 || req.headers['transfer-encoding'] !== undefined;
  if (!hasBody) return null;
  const raw = String(req.headers['content-type'] ?? '');
  const mediaType = raw.split(';')[0]?.trim().toLowerCase() ?? '';
  const requestBody = operation.requestBody as { content?: Record<string, unknown> } | undefined;
  const declared = Object.keys(requestBody?.content ?? {});
  return declared.includes(mediaType) ? null : raw;
}

@Injectable()
export class OpenApiRequestGuard implements CanActivate {
  constructor(
    private readonly openapi: OpenApiService,
    private readonly catalog: ErrorCatalog,
  ) {}

  canActivate(context: ExecutionContext): boolean {
    const req = context.switchToHttp().getRequest<RequestWithOperation>();
    const oasRequest = {
      // Fastify answers HEAD for every GET route; HEAD is validated as the GET operation.
      method: req.method === 'HEAD' ? 'GET' : req.method,
      path: pathOf(req.url),
      headers: req.headers as Record<string, string | string[]>,
      query: (req.query ?? {}) as Record<string, string | string[]>,
      body: req.body,
    };
    const operation = this.openapi.match(oasRequest);
    if (!operation) {
      // A Nest route without an OpenAPI operation is a conformance bug (see openapi-conformance test).
      throw new Error(`route ${req.method} ${pathOf(req.url)} has no OpenAPI operation`);
    }
    const unsupported = unsupportedMediaType(req, operation);
    if (unsupported !== null) throw new ApiProblem('UNSUPPORTED_MEDIA_TYPE', { content_type: unsupported });
    const errors = this.openapi.validateRequest(oasRequest, operation);
    if (errors.length > 0) {
      const summary = errors
        .slice(0, 3)
        .map((e) => `${e.pointer} — ${e.message}`)
        .join('; ');
      throw new ApiProblem(
        'VALIDATION_ERROR',
        { summary },
        {
          errors: errors.map((e) =>
            this.catalog.item('VALIDATION_ERROR', { summary: `${e.pointer} — ${e.message}` }, {
              pointer: e.pointer,
              ...(e.field ? { field: e.field } : {}),
            }),
          ),
        },
      );
    }
    req.oasOperation = operation;
    return true;
  }
}

@Injectable()
export class OpenApiResponseInterceptor implements NestInterceptor {
  constructor(
    private readonly openapi: OpenApiService,
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly logger: PinoLogger,
  ) {
    this.logger.setContext(OpenApiResponseInterceptor.name);
  }

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    if (!this.config.validateResponses) return next.handle();
    const http = context.switchToHttp();
    const req = http.getRequest<RequestWithOperation>();
    const reply = http.getResponse<FastifyReply>();
    return next.handle().pipe(
      map((body: unknown) => {
        const operation = req.oasOperation;
        if (!operation || req.method === 'HEAD') return body;
        // Binary downloads (protocol DOCX/PDF) are written by the handler through the reply (@Res): nothing to
        // validate here; their media types and headers are declared in the document.
        if (body === undefined && reply.sent) return body;
        // Binary bodies returned by the handler (page images, AG-00), 204 No Content and 304 Not Modified have no
        // JSON body to validate.
        if (Buffer.isBuffer(body) || reply.statusCode === 204 || reply.statusCode === 304) return body;
        const errors = this.openapi.validateResponse(body, operation, reply.statusCode);
        if (errors.length > 0) {
          this.logger.error(
            { event: 'response_schema_violation', operation_id: operation.operationId, errors },
            'response does not match the OpenAPI document',
          );
          throw new ApiProblem('RESPONSE_SCHEMA_VIOLATION', { request_id: req.id });
        }
        return body;
      }),
    );
  }
}
