import { Controller, Get, Res } from '@nestjs/common';
import type { FastifyReply } from 'fastify';
import { Database } from '../db/database';
import { SERVICE_NAME } from '../common/logging';
import { API_VERSION } from '../version';

export interface HealthDto {
  status: 'ok' | 'degraded';
  service: typeof SERVICE_NAME;
  version: string;
  time: string;
  checks: { database: { status: 'up' | 'down'; latency_ms: number } };
}

@Controller('health')
export class HealthController {
  constructor(private readonly database: Database) {}

  /** 200 when PostgreSQL answers, 503 (same body, status «degraded») when it does not. */
  @Get()
  async getHealth(@Res({ passthrough: true }) reply: FastifyReply): Promise<HealthDto> {
    const started = performance.now();
    let database: HealthDto['checks']['database'];
    try {
      database = { status: 'up', latency_ms: await this.database.ping() };
    } catch {
      database = { status: 'down', latency_ms: Math.round(performance.now() - started) };
    }
    const ok = database.status === 'up';
    void reply.status(ok ? 200 : 503);
    return {
      status: ok ? 'ok' : 'degraded',
      service: SERVICE_NAME,
      version: API_VERSION,
      time: new Date().toISOString(),
      checks: { database },
    };
  }
}
