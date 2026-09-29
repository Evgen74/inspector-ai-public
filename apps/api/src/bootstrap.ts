/** App wiring shared by main.ts and the tests: Fastify adapter, request ids, prefix, problem errors. */
import type { IncomingMessage } from 'node:http';
import { FastifyAdapter, type NestFastifyApplication } from '@nestjs/platform-fastify';
import { Logger } from 'nestjs-pino';
import { pickRequestId } from './common/ids';
import { contextOf } from './common/request-context';
import { AuditService } from './modules/audit/audit.service';
import { registerMultipartParser } from './modules/upload/multipart-parser';
import { MonitoringService, registerMetrics } from './modules/monitoring';

export const GLOBAL_PREFIX = 'api/v1';
export const BODY_LIMIT_BYTES = 1024 * 1024;

export function createFastifyAdapter(): FastifyAdapter {
  return new FastifyAdapter({
    logger: false, // pino via nestjs-pino
    requestIdHeader: false,
    // One id per request: reuse a well-formed X-Request-Id, else UUID v7. The header is normalized in place so
    // that pino-http (which sees the raw request later) logs the same id.
    genReqId: (raw: IncomingMessage) => {
      const id = pickRequestId(raw.headers['x-request-id']);
      raw.headers['x-request-id'] = id;
      return id;
    },
    bodyLimit: BODY_LIMIT_BYTES,
    trustProxy: false,
  });
}

/** Everything that must happen after the Nest application object exists and before it listens. */
export async function configureApp(app: NestFastifyApplication): Promise<NestFastifyApplication> {
  app.useLogger(app.get(Logger));
  app.setGlobalPrefix(GLOBAL_PREFIX);
  app.enableShutdownHooks();

  const fastify = app.getHttpAdapter().getInstance();
  registerMultipartParser(fastify); // upload vertical: multipart/form-data
  fastify.addHook('onRequest', async (req, reply) => {
    void reply.header('x-request-id', req.id);
    contextOf(req); // starts the request clock for the audit duration_ms
  });
  // Audit of every mutation (and of every 403 on a read), written before the response leaves (AG-00, 09 §3.4.1).
  const audit = app.get(AuditService);
  fastify.addHook('onSend', async (req, reply, payload) => {
    await audit.recordRequest(req, reply, payload);
    return payload;
  });

  // Request metrics for the monitoring page and the Prometheus scrape endpoint GET /metrics.
  registerMetrics(fastify, app.get(MonitoringService, { strict: false }));

  // Errors raised by Fastify before a handler runs (media type, JSON parsing, body size) reach Nest's own
  // Fastify error handler, which forwards them to the global ProblemFilter (see toProblem).
  await app.init();
  await fastify.ready();
  return app;
}
