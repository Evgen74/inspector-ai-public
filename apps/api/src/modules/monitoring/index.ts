/**
 * Monitoring (module 11, AG-00/AG-08). Wiring: `...MONITORING_CONTROLLERS` / `...MONITORING_PROVIDERS` in AppModule,
 * `registerMetrics(fastify, monitoring)` in bootstrap.ts (request hook + the public GET /metrics scrape endpoint).
 */
import type { Provider, Type } from '@nestjs/common';
import type { FastifyInstance } from 'fastify';
import { MonitoringController } from './monitoring.controller';
import { MonitoringService } from './monitoring.service';
import { metricsRegistry } from './metrics.registry';

export { metricsRegistry } from './metrics.registry';
export { MonitoringService } from './monitoring.service';
export const MONITORING_CONTROLLERS: Type<unknown>[] = [MonitoringController];
export const MONITORING_PROVIDERS: Provider[] = [MonitoringService];

/** Records every response and serves the Prometheus text format at /metrics (outside the /api/v1 prefix). */
export function registerMetrics(fastify: FastifyInstance, monitoring: MonitoringService | null): void {
  fastify.addHook('onResponse', async (req, reply) => {
    const route = req.routeOptions?.url ?? 'unmatched';
    if (route === '/metrics') return;
    const ms = reply.elapsedTime;
    metricsRegistry.recordRequest(req.method, route, reply.statusCode, ms);
    if (!metricsRegistry.logTapActive) {
      metricsRegistry.pushLogLine(
        JSON.stringify({
          timestamp: new Date().toISOString(),
          level: reply.statusCode >= 500 ? 'error' : reply.statusCode >= 400 ? 'warn' : 'info',
          service: 'inspector-api',
          event: 'http_request',
          message: `${req.method} ${req.url} → ${reply.statusCode}`,
          request_id: req.id,
          duration_ms: Math.round(ms),
        }),
      );
    }
  });
  fastify.get('/metrics', async (_req, reply) => {
    const extras = monitoring ? await monitoring.prometheusExtras().catch(() => []) : [];
    void reply.header('content-type', 'text/plain; version=0.0.4; charset=utf-8');
    return metricsRegistry.renderPrometheus(extras);
  });
}
