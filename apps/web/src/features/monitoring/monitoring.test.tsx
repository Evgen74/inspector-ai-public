/** Modules 11–12 pages and the M2 backlog text helpers. */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { mockApi, renderAt } from '../../../test/render';
import { deltaText } from '../verification/CardPanel';
import type { MonitoringOverview } from './api';

const overview: MonitoringOverview = {
  time: '2026-09-29T08:00:00Z',
  services: [
    { code: 'api', name: 'API', status: 'up', latency_ms: 0, detail: 'версия 0.1.0' },
    { code: 'database', name: 'PostgreSQL', status: 'up', latency_ms: 3, detail: null },
    { code: 'redis', name: 'Redis', status: 'up', latency_ms: 1, detail: null },
    { code: 'rabbitmq', name: 'RabbitMQ', status: 'down', latency_ms: 2, detail: 'ECONNREFUSED', optional: true },
    { code: 'ml_api', name: 'ml-api (рендер страниц)', status: 'up', latency_ms: 8, detail: 'HTTP 200' },
  ],
  http: { window_s: 300, requests: 40, rate_per_min: 8, p50_ms: 30, p95_ms: 640, errors_5xx: 2, errors_4xx: 1, total_requests: 400, total_errors_5xx: 2 },
  system: { cpu_percent: 91.5, load_avg_1m: 6.2, cpu_count: 10, memory_used_percent: 70, process_rss_mb: 300, uptime_s: 4000, api_version: '0.1.0' },
  queue: { mode: 'in-process', size: 1, processes_by_status: { PENDING: 1, READY: 3 } },
  disk: { runs_bytes: 5_000_000_000, runs_dir: '/x/runs', free_bytes: 100_000_000_000, total_bytes: 500_000_000_000, used_percent: 80 },
  logs: [{ timestamp: '2026-09-29T08:00:00.000Z', level: 'warn', message: 'GET /api/v1/x → 404', event: 'http_request', request_id: 'abcdef123456' }],
  alerts: [
    { code: 'CPU_HIGH', severity: 'warning', message: 'Загрузка процессора 91.5% превышает порог 80%' },
    { code: 'P95_HIGH', severity: 'warning', message: 'Задержка p95 640 мс превышает порог 500 мс' },
  ],
  thresholds: { cpu_percent: 80, p95_ms: 500, disk_percent: 90, errors_5xx: 1 },
  metrics_url: '/metrics',
};

describe('«Мониторинг»', () => {
  it('shows service health, request metrics, queue, disk, log lines, alerts and the Prometheus link', async () => {
    mockApi({
      'GET /api/v1/admin/monitoring/overview': () => ({ body: overview }),
      'GET /api/v1/admin/batch-runs': () => ({ body: { items: [], total: 0, page: 1, page_size: 20 } }),
    });
    renderAt('/admin/monitoring');
    const alerts = await screen.findByTestId('alerts', {}, { timeout: 10_000 });
    expect(within(alerts).getByText(/превышает порог 80%/)).toBeInTheDocument();
    expect(within(alerts).getByText(/p95 640 мс/)).toBeInTheDocument();
    expect(screen.getByTestId('service-rabbitmq')).toHaveTextContent('недоступен: ECONNREFUSED');
    expect(screen.getByTestId('service-database')).toHaveTextContent('работает, 3 мс');
    expect(screen.getByText('внутри процесса (резервный)')).toBeInTheDocument();
    expect(screen.getByText('GET /api/v1/x → 404')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Экспорт метрик Prometheus' })).toHaveAttribute('href', '/metrics');
  });
});

describe('«Самопроверка»', () => {
  it('runs the checks and reports pass / fail / не реализовано in Russian', async () => {
    const { calls } = mockApi({
      'GET /api/v1/auth/me': () => ({ body: { user: { id: 'u', login: 'inspector', full_name: 'Иванова Мария Сергеевна', position: null }, roles: ['INSPECTOR'], permissions: [], csrf_token: 'csrf-1' } }),
      'POST /api/v1/admin/selftest/run': () => ({
        body: {
          started_at: '2026-09-29T08:00:00Z',
          duration_ms: 320,
          summary: { total: 3, pass: 1, fail: 1, not_implemented: 1, skipped: 0 },
          results: [
            { id: 'a', group: 'Доступ', title: 'Решение без авторизации', expected: '401', actual: '401 UNAUTHENTICATED', status: 'PASS', detail: null, duration_ms: 3 },
            { id: 'b', group: 'Протокол', title: 'Выгрузка несуществующего протокола', expected: '404', actual: '200', status: 'FAIL', detail: 'запрос не отклонён', duration_ms: 3 },
            { id: 'c', group: 'Настройки', title: 'Пороги: минимум больше максимума', expected: '422', actual: '—', status: 'NOT_IMPLEMENTED', detail: 'ещё не опубликовано', duration_ms: 1 },
          ],
        },
      }),
    });
    const user = userEvent.setup();
    renderAt('/admin/selftest');
    await screen.findByText('Проверки ещё не запускались', {}, { timeout: 10_000 });
    await waitFor(() => expect(calls.some((c) => c.url === '/api/v1/auth/me')).toBe(true));
    await user.click(screen.getByRole('button', { name: /Запустить проверки/ }));
    expect(await screen.findByText('Не пройдено сценариев: 1')).toBeInTheDocument();
    expect(screen.getByText('Пройдена')).toHaveAttribute('data-code', 'PASS');
    expect(screen.getByText('Не пройдена')).toHaveAttribute('data-code', 'FAIL');
    expect(screen.getByText('не реализовано')).toHaveAttribute('data-code', 'NOT_IMPLEMENTED');
  });
});

describe('deltaText (M2 backlog #2)', () => {
  it('renders the machine delta as Russian text, never as JSON', () => {
    expect(deltaText({ actual: '', expected: 'В10.3', direction: 'ABSENT' })).toBe('В РД отсутствует В10.3');
    expect(deltaText({ actual: '12', expected: '10', direction: 'HIGHER' })).toBe('ожидалось 10, фактически 12, больше эталона');
    expect(deltaText(null)).toBeNull();
  });
});
