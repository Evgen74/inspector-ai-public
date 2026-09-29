/**
 * Structured JSON logs (pino via nestjs-pino). Field schema per 00 §3.12:
 * timestamp, level, service, message, request_id (+ event, error_code, duration_ms where relevant).
 */
import type { IncomingMessage, ServerResponse } from 'node:http';
import pino, { type DestinationStream } from 'pino';
import { metricsRegistry } from '../modules/monitoring/metrics.registry';
import type { Options } from 'pino-http';
import type { AppConfig } from '../config/config';
import { pickRequestId } from './ids';

export const SERVICE_NAME = 'inspector-api';

export function pinoHttpOptions(config: AppConfig): Options {
  const options: Options = {
    level: config.logLevel,
    base: { service: SERVICE_NAME },
    messageKey: 'message',
    timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
    formatters: { level: (label: string) => ({ level: label }) },
    // Fastify's genReqId has already normalized the header, so this returns the same id.
    genReqId: (req: IncomingMessage) => pickRequestId(req.headers['x-request-id']),
    quietReqLogger: true,
    customAttributeKeys: { reqId: 'request_id', responseTime: 'duration_ms' },
    serializers: {
      req: (req: { method?: string; url?: string }) => ({ method: req.method, url: req.url }),
      res: (res: { statusCode?: number }) => ({ status_code: res.statusCode }),
    },
    customLogLevel: (_req: IncomingMessage, res: ServerResponse, err?: Error) => {
      if (err || res.statusCode >= 500) return 'error';
      if (res.statusCode >= 400) return 'warn';
      return 'info';
    },
    customSuccessMessage: (req: IncomingMessage, res: ServerResponse) =>
      `${req.method ?? ''} ${req.url ?? ''} → ${res.statusCode}`,
    customErrorMessage: (req: IncomingMessage, res: ServerResponse) =>
      `${req.method ?? ''} ${req.url ?? ''} → ${res.statusCode}`,
    customProps: () => ({ event: 'http_request' }),
    redact: { paths: ['req.headers.cookie', 'req.headers.authorization'], remove: true },
  };
  if (config.logFormat === 'console') {
    options.transport = {
      target: 'pino-pretty',
      options: {
        singleLine: true,
        messageKey: 'message',
        timestampKey: 'timestamp',
        translateTime: 'SYS:HH:MM:ss.l',
        ignore: 'pid,hostname,service,event',
      },
    };
  }
  return options;
}

/** nestjs-pino accepts `[options, stream]`; tests pass a stream to capture log lines. */
export function pinoHttpConfig(config: AppConfig, stream?: DestinationStream): Options | [Options, DestinationStream] {
  const options = pinoHttpOptions(config);
  if (stream) {
    delete options.transport;
    return [options, stream];
  }
  // JSON logs go to stdout as before and are teed into the ring buffer shown on the monitoring page.
  if (options.transport === undefined) {
    return [options, pino.multistream([{ level: 'trace', stream: process.stdout }, { level: 'trace', stream: metricsRegistry.logTap() }])];
  }
  return options;
}
