/** Modules 11–12: monitoring overview, Prometheus endpoint, alerts and the negative-scenario self-check. */
import type { FastifyInstance, LightMyRequestResponse } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { MetricsRegistry } from '../src/modules/monitoring/metrics.registry';
import { computeAlerts, type MonitoringOverview } from '../src/modules/monitoring/monitoring.service';
import { detectQueueMode, probeRabbit } from '../src/modules/monitoring/probes';
import { UsersRepository } from '../src/modules/auth/users.repository';
import { createTestApp, type TestApp } from './helpers';
import type { InMemoryUsers } from './platform-fakes';

const PASSWORD = 'Demo-Inspector-2026';

function cookieOf(res: LightMyRequestResponse): string {
  const raw = res.headers['set-cookie'];
  return String((Array.isArray(raw) ? raw[0] : raw) ?? '').split(';')[0] ?? '';
}

describe('MetricsRegistry', () => {
  it('computes rate, p95 and 5xx over the window and renders the Prometheus text format', () => {
    const m = new MetricsRegistry();
    for (let i = 1; i <= 100; i += 1) m.recordRequest('GET', '/api/v1/x', i === 100 ? 503 : 200, i * 10);
    const w = m.window();
    expect(w.requests).toBe(100);
    expect(w.p95_ms).toBe(950);
    expect(w.errors_5xx).toBe(1);
    const text = m.renderPrometheus([{ name: 'inspector_service_up', help: 'h', type: 'gauge', value: 1, labels: { service: 'api' } }]);
    expect(text).toContain('inspector_http_requests_total{method="GET",route="/api/v1/x",status="503"} 1');
    expect(text).toContain('inspector_http_request_duration_ms_count 100');
    expect(text).toContain('inspector_http_request_duration_ms_bucket{le="+Inf"} 100');
    expect(text).toContain('inspector_service_up{service="api"} 1');
  });

  it('keeps recent JSON log lines newest first and ignores non-JSON', () => {
    const m = new MetricsRegistry();
    const tap = m.logTap();
    tap.write('{"timestamp":"t1","level":"info","message":"one","event":"a"}\n{"timestamp":"t2","level":"error","mess');
    tap.write('age":"two"}\nnot json\n');
    expect(m.recentLogs(10).map((l) => l.message)).toEqual(['two', 'one']);
  });
});

describe('alerts', () => {
  const base: MonitoringOverview = {
    time: '2026-09-29T00:00:00Z',
    services: [
      { code: 'api', name: 'API', status: 'up', latency_ms: 0, detail: null },
      { code: 'rabbitmq', name: 'RabbitMQ', status: 'up', latency_ms: 1, detail: null, optional: true },
    ],
    http: { window_s: 300, requests: 10, rate_per_min: 2, p50_ms: 20, p95_ms: 100, errors_5xx: 0, errors_4xx: 0, total_requests: 10, total_errors_5xx: 0 },
    system: { cpu_percent: 10, load_avg_1m: 1, cpu_count: 8, memory_used_percent: 50, process_rss_mb: 100, uptime_s: 5, api_version: '0' },
    queue: { mode: 'rabbitmq', size: 0, processes_by_status: {} },
    disk: { runs_bytes: 1, runs_dir: '/x', free_bytes: 1, total_bytes: 10, used_percent: 10 },
    logs: [],
    alerts: [],
    thresholds: { cpu_percent: 80, p95_ms: 500, disk_percent: 90, errors_5xx: 1 },
    metrics_url: '/metrics',
  };

  it('is quiet below the thresholds', () => {
    expect(computeAlerts(base)).toEqual([]);
  });

  it('raises CPU > 80 % and p95 > 500 ms, and a warning (not critical) for a missing broker', () => {
    const o: MonitoringOverview = {
      ...base,
      system: { ...base.system, cpu_percent: 85 },
      http: { ...base.http, p95_ms: 640 },
      services: [base.services[0]!, { ...base.services[1]!, status: 'down' }],
    };
    const alerts = computeAlerts(o);
    expect(alerts.map((a) => a.code).sort()).toEqual(['CPU_HIGH', 'P95_HIGH', 'RABBITMQ_DOWN']);
    expect(alerts.find((a) => a.code === 'RABBITMQ_DOWN')?.severity).toBe('warning');
  });
});

describe('RabbitMQ fallback', () => {
  it('runs in-process when the broker does not answer', async () => {
    const r = await detectQueueMode('amqp://127.0.0.1:1');
    expect(r.mode).toBe('in-process');
    expect((await probeRabbit('amqp://127.0.0.1:1')).up).toBe(false);
  });
});

describe('monitoring and selftest endpoints', () => {
  let t: TestApp;
  let http: FastifyInstance;

  beforeAll(async () => {
    t = await createTestApp({ authMode: 'required' });
    http = t.http;
    const users = t.app.get(UsersRepository) as InMemoryUsers;
    await users.add({ login: 'inspector', password: PASSWORD, roles: ['INSPECTOR'] });
  });
  afterAll(async () => {
    await t.close();
  });

  async function login(name: string) {
    const res = await http.inject({ method: 'POST', url: '/api/v1/auth/login', payload: { login: name, password: PASSWORD } });
    expect(res.statusCode, res.body).toBe(200);
    return { cookie: cookieOf(res), csrf: String((res.json() as { csrf_token: string }).csrf_token) };
  }

  it('serves the Prometheus text format at /metrics', async () => {
    await http.inject({ method: 'GET', url: '/api/v1/health' });
    const res = await http.inject({ method: 'GET', url: '/metrics' });
    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toContain('text/plain');
    expect(res.body).toContain('inspector_http_requests_total{method="GET",route="/api/v1/health",status="200"}');
    expect(res.body).toContain('inspector_service_up{service="database"}');
  });

  it('overview needs a session and reports and reports services, http, queue, disk, logs and alerts', async () => {
    expect((await http.inject({ method: 'GET', url: '/api/v1/admin/monitoring/overview' })).statusCode).toBe(401);
    const admin = await login('inspector');
    const res = await http.inject({ method: 'GET', url: '/api/v1/admin/monitoring/overview?log_lines=5', headers: { cookie: admin.cookie } });
    expect(res.statusCode, res.body).toBe(200);
    const o = res.json() as MonitoringOverview;
    expect(o.services.map((s) => s.code)).toEqual(['api', 'database', 'redis', 'rabbitmq', 'ml_api']);
    expect(o.services.find((s) => s.code === 'database')?.status).toBe('up');
    expect(['rabbitmq', 'in-process']).toContain(o.queue.mode);
    expect(o.http.total_requests).toBeGreaterThan(0);
    expect(o.logs.length).toBeLessThanOrEqual(5);
    expect(o.thresholds).toMatchObject({ cpu_percent: 80, p95_ms: 500 });
  });

  it('selftest runs the negative scenarios, fails nothing on a healthy API', async () => {
    const admin = await login('inspector');
    const res = await http.inject({ method: 'POST', url: '/api/v1/admin/selftest/run', headers: { cookie: admin.cookie, 'x-csrf-token': admin.csrf } });
    expect(res.statusCode, res.body).toBe(200);
    const r = res.json() as { summary: Record<string, number>; results: Array<{ id: string; status: string; actual: string; detail: string | null }> };
    expect(r.summary.total).toBeGreaterThanOrEqual(15);
    // Scenarios that need PostgreSQL answer 500 here (the DB-free harness has no tables); the rest must not fail.
    const dbBound = new Set(['decision-missing-process', 'decision-invalid-body', 'decision-after-finalization', 'finalize-with-pending', 'unfinalize-no-reason', 'upload-unsupported-format', 'upload-corrupted-pdf']);
    const failed = r.results.filter((x) => x.status === 'FAIL' && !dbBound.has(x.id));
    expect(failed, JSON.stringify(failed)).toEqual([]);
    const byId = new Map(r.results.map((x) => [x.id, x]));
    expect(byId.get('decision-no-auth')?.status).toBe('PASS');
    expect(byId.get('rabbitmq-down-fallback')?.status).toBe('PASS');
    expect(byId.get('export-missing-protocol')?.status).toBe('PASS');
  });
});
