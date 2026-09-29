import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import { Providers, createQueryClient } from '../App';
import { mockApi } from '../../test/render';
import { AppShell, sessionLabel } from './AppShell';

const session = {
  user: { id: 'u1', login: 'inspector', full_name: 'Иванов И. И.', position: null },
  roles: ['INSPECTOR'],
  permissions: [],
  csrf_token: 'tok',
};

function renderShell() {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0, refetchInterval: false } });
  return render(
    <Providers client={client}>
      <MemoryRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </Providers>,
  );
}

describe('AppShell user menu', () => {
  it('labels the role from enums.yaml', () => {
    expect(sessionLabel(session)).toEqual({ name: 'Иванов И. И.', role: 'Инспектор' });
  });

  it('shows the name, the Russian role and «Выйти» when logged in', async () => {
    mockApi({ 'GET /api/v1/auth/me': () => ({ body: session }) });
    renderShell();
    const menu = await screen.findByTestId('user-menu');
    expect(menu).toHaveTextContent('Иванов И. И.');
    expect(menu).toHaveTextContent('Инспектор');
    expect(screen.getByRole('button', { name: 'Выйти' })).toBeInTheDocument();
  });

  it('shows «Войти» when there is no session and opens the login form', async () => {
    mockApi({ 'GET /api/v1/auth/me': () => ({ status: 401, body: { code: 'UNAUTHENTICATED', title: 'x', detail: 'x', status: 401 } }) });
    renderShell();
    const btn = await screen.findByTestId('login-button');
    await userEvent.click(btn);
    await waitFor(() => expect(screen.getByPlaceholderText('Логин')).toBeInTheDocument());
  });
});

describe('AppShell menu by role', () => {
  const perms = (...codes: string[]) => codes.map((code) => ({ code, scope: 'ALL' }));

  it('hides pages the inspector cannot open (the API would answer 403)', async () => {
    mockApi({ 'GET /api/v1/auth/me': () => ({ body: { ...session, permissions: perms('object.read', 'matrix.read') } }) });
    renderShell();
    await screen.findByTestId('user-menu');
    expect(screen.getByRole('link', { name: 'Нормативная база' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Отчёт по дообучению' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Мониторинг' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Самопроверка' })).toBeNull();
  });

  it('shows the operations pages to a user that has their permissions', async () => {
    const full = { ...session, roles: ['INSPECTOR'], permissions: perms('object.read', 'matrix.read', 'retraining.read', 'monitoring.read', 'ops.run') };
    mockApi({ 'GET /api/v1/auth/me': () => ({ body: full }) });
    renderShell();
    await screen.findByTestId('user-menu');
    for (const name of ['Отчёт по дообучению', 'Мониторинг', 'Самопроверка']) {
      expect(await screen.findByRole('link', { name })).toBeInTheDocument();
    }
  });
});
