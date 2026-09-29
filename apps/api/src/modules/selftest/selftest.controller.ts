import { Controller, HttpCode, Post, Req } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { Inject } from '@nestjs/common';
import { CSRF_HEADER } from '../auth/cookies';
import { type SelftestReport, SelftestService } from './selftest.service';

@Controller('admin/selftest')
export class SelftestController {
  constructor(
    private readonly selftest: SelftestService,
    @Inject(APP_CONFIG) private readonly config: AppConfig,
  ) {}

  /** Runs every negative check against this API; nothing is changed. */
  @Post('run')
  @HttpCode(200)
  run(@Req() req: FastifyRequest): Promise<SelftestReport> {
    const csrf = req.headers[CSRF_HEADER];
    return this.selftest.run({
      cookie: typeof req.headers.cookie === 'string' ? req.headers.cookie : null,
      csrf: Array.isArray(csrf) ? (csrf[0] ?? null) : (csrf ?? null),
    });
  }
}
