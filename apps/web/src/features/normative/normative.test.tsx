/** Module 8 «Нормативная база»: the matrix table, filters that reach the API, permission-gated editing. */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { mockApi, renderAt } from '../../../test/render';

const item = (code: string, name: string, extra: Record<string, unknown> = {}) => ({
  code,
  name,
  section: 'СПЗУ',
  criticality_level: 'CRITICAL_SUSPEND',
  criticality: 'Критическое (приостановка работ)',
  unit: 'м',
  min_value: 4.2,
  max_value: null,
  is_active: true,
  base_min_value: 4.2,
  base_max_value: null,
  base_is_active: true,
  overridden: false,
  threshold_source: 'NORMATIVE',
  threshold_note: null,
  refs: [{ kind: 'sp', designation: 'СП 4.13130.2013', clause: 'п. 8.6', edition: null, status: 'CONFIRMED', confidence: 'HIGH' }],
  ...extra,
});

const PARAMS = { matrix_version: '1.1.1', base_version: '1.1.1', total: 132, overrides: 0, sections: ['СПЗУ', 'АР'], items: [item('SPZU-030', 'Ширина пожарных проездов'), item('AR-040', 'Ширина коридоров', { section: 'АР' })] };

const ME = (perms: string[]) => ({ user: { id: 'u', login: 'inspector', full_name: 'Иванова Мария Сергеевна', position: null }, roles: ['INSPECTOR'], permissions: perms.map((code) => ({ code, scope: 'ALL' })), csrf_token: 'csrf-1' });

const SLOW = { timeout: 10_000 };

describe('Нормативная база', () => {
  it('shows the parameters with thresholds and normative references, and sends the search to the API', async () => {
    const user = userEvent.setup();
    const { calls } = mockApi({ '/api/v1/normative/params': () => ({ body: PARAMS }), '/api/v1/auth/me': () => ({ body: ME(['matrix.read']) }) });
    renderAt('/admin/normative');
    const row = (await screen.findByText('SPZU-030', {}, SLOW)).closest('tr')!;
    expect(within(row).getByText('4.2 м')).toBeInTheDocument();
    expect(within(row).getByText(/СП 4.13130.2013 · подтверждена · уверенность: высокая/)).toBeInTheDocument();
    expect(screen.getByText(/Показано 2 из 132 · версия матрицы 1.1.1/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Изменить/ })).not.toBeInTheDocument(); // read-only without params.manage
    await user.type(screen.getByPlaceholderText(/Поиск по коду/), 'коридор{enter}');
    await waitFor(() => expect(calls.some((c) => c.url.includes('q=%D0%BA%D0%BE%D1%80%D0%B8%D0%B4%D0%BE%D1%80'))).toBe(true));
  });

  it('lets an inspector save thresholds (PUT with CSRF) and reports the new matrix version', async () => {
    const user = userEvent.setup();
    const { calls, fetchMock } = mockApi({
      '/api/v1/normative/params': () => ({ body: PARAMS }),
      '/api/v1/auth/me': () => ({ body: ME(['matrix.read', 'params.manage']) }),
      'PUT /api/v1/normative/params/SPZU-030': () => ({ body: { unchanged: false, matrix_version: '1.1.1+ovr.1', version: 1 } }),
    });
    renderAt('/admin/normative');
    await user.click(await screen.findByRole('button', { name: 'Изменить SPZU-030' }, SLOW));
    const min = screen.getByLabelText('Минимум');
    await user.clear(min);
    await user.type(min, '6');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT' && c.url === '/api/v1/normative/params/SPZU-030')).toBe(true));
    const put = calls.find((c) => c.method === 'PUT')!;
    expect(JSON.parse(put.body!)).toMatchObject({ min_value: 6, max_value: null, is_active: true });
    const init = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === 'PUT')![1] as RequestInit;
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-1');
    expect(await screen.findByText(/Версия матрицы 1.1.1\+ovr.1/)).toBeInTheDocument();
  });
});
