/** «Мониторинг» (module 11): service health, request metrics, queue, disk, recent logs, alerts. */
import { execFile } from 'node:child_process';
import { statfsSync } from 'node:fs';
import os from 'node:os';
import { Inject, Injectable } from '@nestjs/common';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { Database } from '../../db/database';
import { API_VERSION } from '../../version';
import { metricsRegistry } from './metrics.registry';
import { detectQueueMode, parseHostPort, type ProbeResult, probeHttp, probeRabbit, probeRedis, rabbitUrl } from './probes';

export const THRESHOLDS = { cpu_percent: 80, p95_ms: 500, disk_percent: 90, errors_5xx: 1 } as const;

export interface ServiceHealth {
  code: 'api' | 'database' | 'redis' | 'rabbitmq' | 'ml_api';
  name: string;
  status: 'up' | 'down';
  latency_ms: number | null;
  detail: string | null;
  /** RabbitMQ is optional: when it is down jobs run in-process. */
  optional?: boolean;
}

export interface MonitoringAlert {
  code: string;
  severity: 'warning' | 'critical';
  message: string;
}

export interface MonitoringOverview {
  time: string;
  services: ServiceHealth[];
  http: { window_s: number; requests: number; rate_per_min: number; p50_ms: number | null; p95_ms: number | null; errors_5xx: number; errors_4xx: number; total_requests: number; total_errors_5xx: number };
  system: { cpu_percent: number; load_avg_1m: number; cpu_count: number; memory_used_percent: number; process_rss_mb: number; uptime_s: number; api_version: string };
  queue: { mode: 'rabbitmq' | 'in-process'; size: number; processes_by_status: Record<string, number> };
  disk: { runs_bytes: number | null; runs_dir: string; free_bytes: number | null; total_bytes: number | null; used_percent: number | null };
  logs: Array<{ timestamp: string; level: string; message: string; event: string | null; request_id: string | null }>;
  alerts: MonitoringAlert[];
  thresholds: typeof THRESHOLDS;
  metrics_url: string;
}

function cpuTimes(): { idle: number; total: number } {
  let idle = 0;
  let total = 0;
  for (const c of os.cpus()) {
    idle += c.times.idle;
    total += c.times.user + c.times.nice + c.times.sys + c.times.idle + c.times.irq;
  }
  return { idle, total };
}

@Injectable()
export class MonitoringService {
  private lastCpu = cpuTimes();
  private lastCpuPercent = 0;
  private lastCpuAt = 0;
  private diskCache: { at: number; bytes: number | null } | null = null;

  constructor(
    private readonly database: Database,
    @Inject(APP_CONFIG) private readonly config: AppConfig,
  ) {}

  /** System CPU load since the previous sample (samples closer than 1 s reuse the last value). */
  private cpuPercent(): number {
    const now = Date.now();
    if (now - this.lastCpuAt < 1000) return this.lastCpuPercent;
    const cur = cpuTimes();
    const dTotal = cur.total - this.lastCpu.total;
    const dIdle = cur.idle - this.lastCpu.idle;
    this.lastCpu = cur;
    this.lastCpuAt = now;
    this.lastCpuPercent = dTotal > 0 ? Math.round((1 - dIdle / dTotal) * 1000) / 10 : this.lastCpuPercent;
    return this.lastCpuPercent;
  }

  private runsBytes(): Promise<number | null> {
    const cached = this.diskCache;
    if (cached && Date.now() - cached.at < 60_000) return Promise.resolve(cached.bytes);
    return new Promise((resolve) => {
      execFile('du', ['-sk', this.config.runsRoot], { timeout: 10_000 }, (err, stdout) => {
        const kb = err ? NaN : Number(stdout.split(/\s+/)[0]);
        const bytes = Number.isFinite(kb) ? kb * 1024 : (cached?.bytes ?? null);
        this.diskCache = { at: Date.now(), bytes };
        resolve(bytes);
      });
    });
  }

  private async processesByStatus(): Promise<Record<string, number> | null> {
    try {
      const res = await this.database.pool.query<{ status: string; n: string }>(
        'SELECT status, count(*)::text AS n FROM processes GROUP BY status',
      );
      return Object.fromEntries(res.rows.map((r) => [r.status, Number(r.n)]));
    } catch {
      return null;
    }
  }

  async services(): Promise<ServiceHealth[]> {
    const db = await this.database
      .ping()
      .then((ms): ProbeResult => ({ up: true, latency_ms: ms, detail: null }))
      .catch((e: unknown): ProbeResult => ({ up: false, latency_ms: 0, detail: (e as { code?: string }).code ?? 'недоступна' }));
    const [redis, rabbit, ml] = await Promise.all([
      probeRedis(this.config.redisUrl),
      probeRabbit(rabbitUrl()),
      probeHttp(`${this.config.mlApiUrl}/health`),
    ]);
    const row = (code: ServiceHealth['code'], name: string, p: ProbeResult, extra: Partial<ServiceHealth> = {}): ServiceHealth => ({
      code,
      name,
      status: p.up ? 'up' : 'down',
      latency_ms: p.latency_ms,
      detail: p.detail,
      ...extra,
    });
    return [
      { code: 'api', name: 'API', status: 'up', latency_ms: 0, detail: `версия ${API_VERSION}` },
      row('database', 'PostgreSQL', db),
      row('redis', 'Redis', redis),
      row('rabbitmq', 'RabbitMQ', rabbit, {
        optional: true,
        detail: rabbit.up ? null : 'недоступен — задания выполняются внутри процесса (резервный режим)',
      }),
      row('ml_api', 'ml-api (рендер страниц)', ml),
    ];
  }

  async overview(logLines = 50): Promise<MonitoringOverview> {
    const [services, byStatus, runsBytes, queueMode] = await Promise.all([
      this.services(),
      this.processesByStatus(),
      this.runsBytes(),
      detectQueueMode(),
    ]);
    const win = metricsRegistry.window();
    const totals = metricsRegistry.totals();
    const cpu = this.cpuPercent();
    let free: number | null = null;
    let total: number | null = null;
    try {
      const fs = statfsSync(this.config.runsRoot);
      free = fs.bavail * fs.bsize;
      total = fs.blocks * fs.bsize;
    } catch {
      // runs/ may not exist yet
    }
    const usedPercent = free !== null && total ? Math.round((1 - free / total) * 1000) / 10 : null;
    const memUsed = Math.round((1 - os.freemem() / os.totalmem()) * 1000) / 10;
    const statuses = byStatus ?? {};
    const overview: MonitoringOverview = {
      time: new Date().toISOString(),
      services,
      http: {
        window_s: 300,
        requests: win.requests,
        rate_per_min: win.rate_per_min,
        p50_ms: win.p50_ms,
        p95_ms: win.p95_ms,
        errors_5xx: win.errors_5xx,
        errors_4xx: win.errors_4xx,
        total_requests: totals.requests,
        total_errors_5xx: totals.errors_5xx,
      },
      system: {
        cpu_percent: cpu,
        load_avg_1m: Math.round((os.loadavg()[0] ?? 0) * 100) / 100,
        cpu_count: os.cpus().length,
        memory_used_percent: memUsed,
        process_rss_mb: Math.round(process.memoryUsage().rss / 1048576),
        uptime_s: totals.uptime_s,
        api_version: API_VERSION,
      },
      queue: {
        mode: queueMode.mode,
        size: (statuses.PENDING ?? 0) + (statuses.PARSING ?? 0),
        processes_by_status: statuses,
      },
      disk: {
        runs_bytes: runsBytes,
        runs_dir: this.config.runsRoot,
        free_bytes: free,
        total_bytes: total,
        used_percent: usedPercent,
      },
      logs: metricsRegistry.recentLogs(logLines).map(({ raw: _raw, ...rest }) => rest),
      alerts: [],
      thresholds: THRESHOLDS,
      metrics_url: '/metrics',
    };
    overview.alerts = computeAlerts(overview);
    return overview;
  }

  /** Extra gauges for /metrics (service state, CPU, disk, process counts). */
  async prometheusExtras(): Promise<Parameters<typeof metricsRegistry.renderPrometheus>[0]> {
    const [services, byStatus, runsBytes] = await Promise.all([this.services(), this.processesByStatus(), this.runsBytes()]);
    const extra: Parameters<typeof metricsRegistry.renderPrometheus>[0] = [];
    for (const s of services) {
      extra.push({ name: 'inspector_service_up', help: 'Доступность сервиса (1 — работает).', type: 'gauge', value: s.status === 'up' ? 1 : 0, labels: { service: s.code } });
    }
    extra.push({ name: 'inspector_cpu_percent', help: 'Загрузка процессора, %.', type: 'gauge', value: this.cpuPercent() });
    extra.push({ name: 'inspector_process_rss_bytes', help: 'Память процесса API.', type: 'gauge', value: process.memoryUsage().rss });
    if (runsBytes !== null) extra.push({ name: 'inspector_runs_dir_bytes', help: 'Размер каталога runs/.', type: 'gauge', value: runsBytes });
    for (const [status, n] of Object.entries(byStatus ?? {})) {
      extra.push({ name: 'inspector_processes', help: 'Проверки по статусам.', type: 'gauge', value: n, labels: { status } });
    }
    return extra;
  }
}

export function computeAlerts(o: MonitoringOverview): MonitoringAlert[] {
  const alerts: MonitoringAlert[] = [];
  if (o.system.cpu_percent > THRESHOLDS.cpu_percent) {
    alerts.push({ code: 'CPU_HIGH', severity: 'warning', message: `Загрузка процессора ${o.system.cpu_percent}% превышает порог ${THRESHOLDS.cpu_percent}%` });
  }
  if (o.http.p95_ms !== null && o.http.p95_ms > THRESHOLDS.p95_ms) {
    alerts.push({ code: 'P95_HIGH', severity: 'warning', message: `Задержка p95 ${o.http.p95_ms} мс превышает порог ${THRESHOLDS.p95_ms} мс` });
  }
  if (o.http.errors_5xx >= THRESHOLDS.errors_5xx) {
    alerts.push({ code: 'ERRORS_5XX', severity: 'warning', message: `Ответов 5xx за последние 5 минут: ${o.http.errors_5xx}` });
  }
  if (o.disk.used_percent !== null && o.disk.used_percent > THRESHOLDS.disk_percent) {
    alerts.push({ code: 'DISK_HIGH', severity: 'critical', message: `Диск заполнен на ${o.disk.used_percent}% (порог ${THRESHOLDS.disk_percent}%)` });
  }
  for (const s of o.services) {
    if (s.status === 'down' && !s.optional) {
      alerts.push({ code: `SERVICE_DOWN_${s.code.toUpperCase()}`, severity: 'critical', message: `Сервис «${s.name}» недоступен` });
    }
  }
  const rabbit = o.services.find((s) => s.code === 'rabbitmq');
  if (rabbit?.status === 'down') {
    alerts.push({ code: 'RABBITMQ_DOWN', severity: 'warning', message: 'RabbitMQ недоступен: задания выполняются внутри процесса (резервный режим)' });
  }
  return alerts;
}

export { parseHostPort };
