/** Module 10 «Отчёт по дообучению» and module 6 «РиН» card. */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { render as rtlRender } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { createQueryClient, Providers } from '../../App';
import { mockApi, renderAt } from '../../../test/render';
import { RinSyncCard } from '../rin/RinSyncCard';

const REPORT = {
  period: { from: '2026-09-22T00:00:00.000Z', to: '2026-09-29T00:00:00.000Z' },
  generated_at: '2026-09-29T00:00:00.000Z',
  totals: { decided: 13, confirmed: 10, rejected: 3, clarification: 0, precision: 0.769, disputes: 1 },
  by_param: [{ param_code: 'IOS4-078', name: 'Воздуховоды', section: 'ИОС4', confirmed: 5, rejected: 3, total: 8, precision: 0.625 }],
  by_section: [{ section: 'ИОС4', confirmed: 5, rejected: 3, total: 8, precision: 0.625 }],
  by_reason: [{ reason_code: 'OCR_ERROR', label: 'Ошибка распознавания (OCR)', family: 'MODEL_ERROR', count: 3, share: 1 }],
  trend: Array.from({ length: 8 }, (_, i) => ({ week_start: `2026-08-${String(10 + i * 7 > 31 ? 3 : 10 + i * 7).padStart(2, '0')}`, confirmed: 1, rejected: 1, precision: 0.5 })),
  recommendations: [{ severity: 'warning', text: 'Параметр IOS4-078: отклонено 3 из 8.' }],
};

const SLOW = { timeout: 10_000 };

describe('Отчёт по дообучению', () => {
  it('shows totals, recommendations, reasons and links to the printable and JSON versions', async () => {
    mockApi({ '/api/v1/ml/reports/weekly': () => ({ body: REPORT }) });
    renderAt('/admin/ml-report');
    expect(await screen.findByText('Параметр IOS4-078: отклонено 3 из 8.', {}, SLOW)).toBeInTheDocument();
    expect(screen.getByText('77%')).toBeInTheDocument();
    expect(screen.getByText('Ошибка распознавания (OCR)')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Печатная версия/ })).toHaveAttribute('href', '/api/v1/ml/reports/weekly.html');
    expect(screen.getByRole('link', { name: /JSON/ })).toHaveAttribute('href', '/api/v1/ml/reports/weekly');
  });
});

describe('Отчёт по дообучению: честная подпись и один пункт динамики', () => {
  it('says the report serves as retraining input, shows dd.mm.yyyy dates and the value instead of an empty chart', async () => {
    const one = REPORT.trend.map((w, i) => (i === 7 ? { ...w, week_start: '2026-09-28', precision: 0.769, confirmed: 10, rejected: 3 } : { ...w, precision: null, confirmed: 0, rejected: 0 }));
    mockApi({
      '/api/v1/ml/reports/weekly': () => ({
        body: { ...REPORT, trend: one, by_param: [{ param_code: 'FREE-HEATING-001', name: 'вне матрицы: отопление', section: 'Вне матрицы', confirmed: 4, rejected: 0, total: 4, precision: 1 }] },
      }),
    });
    renderAt('/admin/ml-report');
    expect(await screen.findByText(/служит исходными данными для дообучения/, {}, SLOW)).toBeInTheDocument();
    expect(await screen.findByText(/Период: 22\.09\.2026 — 29\.09\.2026/)).toBeInTheDocument();
    expect(await screen.findByTestId('trend-single')).toHaveTextContent('77%');
    expect(screen.getByText('вне матрицы: отопление')).toBeInTheDocument();
  });
});

const PID = '01a0ea6f-2b17-7fdb-8446-d58daad90993';
const summary = (status: string) => ({ process_id: PID, run: { run_id: 'run-1', batch_run_id: 'b' }, status });

describe('РиН на странице протокола', () => {
  const renderCard = () => {
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false, staleTime: 0 } });
    return rtlRender(
      <Providers client={client}>
        <MemoryRouter>
          <RinSyncCard objectId="OBJ-1" runId="run-1" />
        </MemoryRouter>
      </Providers>,
    );
  };
  const render = (status: string, rin: unknown, perms = ['rin.send']) =>
    mockApi({
      '/api/v1/objects/OBJ-1/verification': () => ({ body: { object_id: 'OBJ-1', object_name: 'X', processes: [summary(status)] } }),
      [`/api/v1/processes/${PID}/rin`]: () => ({ body: rin }),
      '/api/v1/auth/me': () => ({ body: { user: { id: 'u', login: 'i', full_name: 'И', position: null }, roles: ['INSPECTOR'], permissions: perms.map((code) => ({ code, scope: 'ALL' })), csrf_token: 'c' } }),
      [`POST /api/v1/processes/${PID}/rin/send`]: () => ({ status: 202, body: { process_id: PID, status: 'SYNCED', status_label: 'Синхронизировано', attempts: 1, max_attempts: 4, violations: 10, external_id: 'RIN-ABC' } }),
    });

  it('disables the send button until the protocol is finalized', async () => {
    render('READY', { process_id: PID, status: null, status_label: 'Не отправлялось', attempts: 0 });
    renderCard();
    const card = await screen.findByTestId('rin-card', {}, SLOW);
    expect(within(card).getByRole('button', { name: /Отправить в РиН/ })).toBeDisabled();
    expect(within(card).getByText(/Протокол ещё не утверждён/)).toBeInTheDocument();
  });

  it('sends a finalized protocol and shows the sync status', async () => {
    const user = userEvent.setup();
    const { calls } = render('FINALIZED', { process_id: PID, status: null, status_label: 'Не отправлялось', attempts: 0 });
    renderCard();
    const card = await screen.findByTestId('rin-card', {}, SLOW);
    await user.click(await within(card).findByRole('button', { name: /Отправить в РиН/ }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/rin/send'))).toBe(true));
    await waitFor(() => expect(card.querySelector('[data-code="SYNCED"]')).not.toBeNull());
    expect(within(card).getByText('RIN-ABC')).toBeInTheDocument();
  });
});
