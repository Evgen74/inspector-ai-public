import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { mockApi, renderAt } from '../../../test/render';

describe('Самопроверка', () => {
  it('runs the checks with no request body and no JSON content type (the API answers 415 to a JSON body)', async () => {
    const { fetchMock } = mockApi({
      '/api/v1/auth/me': () => ({ body: { user: { id: 'u', login: 'inspector', full_name: 'Иванова Мария Сергеевна' }, roles: ['INSPECTOR'], permissions: [], assigned_object_ids: [], csrf_token: 'tok' } }),
      'POST /api/v1/admin/selftest/run': () => ({
        body: {
          started_at: '2026-09-29T08:00:00.000Z',
          duration_ms: 10,
          summary: { total: 1, pass: 1, fail: 0, not_implemented: 0, skipped: 0 },
          results: [{ id: 'a', group: 'Инфраструктура', title: 'Проверка API', expected: '200', actual: '200', status: 'PASS', detail: null, duration_ms: 1 }],
        },
      }),
    });
    renderAt('/admin/selftest');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Запустить проверки/ }));
    expect(await screen.findByText('Проверка API')).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/admin/selftest/run'))!;
    const init = call[1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(init.body).toBeUndefined();
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  });
});
