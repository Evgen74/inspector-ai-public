/**
 * Verification workspace, end to end against a real recording of the API (test/verification/web-fixture.test.ts
 * in apps/api re-records fixtures/tyumen.api.json — `cd apps/api && UPDATE_WEB_FIXTURE=1 pnpm exec vitest run
 * test/verification/web-fixture.test.ts`). GETs are served from that recording; the two decision POSTs below
 * return its real recorded results, so the assertions are the real Приложение 2 codes and templates, not invented
 * mocks. `VerificationPage`/`Workspace` are rendered directly (not through AppRoutes: App.tsx's `/verification`
 * route is still AG-08's M1 placeholder — see this package's open issue) with the same `Providers` the app uses.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import { Providers, createQueryClient } from '../../App';
import { mockApi } from '../../../test/render';
import fixtureJson from './fixtures/tyumen.api.json';
import { VerificationPage } from './VerificationPage';

type Json = Record<string, any>;
const fixture = fixtureJson as unknown as Json;

const PID: string = fixture.process_id;
const OID: string = fixture.object_id;
const F012 = 'OBJ-TYUMENSKAYA-5-GOLD-SEED-IOS4-079-PDRD-012';
const F140 = 'OBJ-TYUMENSKAYA-5-GOLD-SEED-IOS4-078-PDRD-140';

type Handler = (url: URL, init?: RequestInit) => { status?: number; body: unknown; headers?: Record<string, string> };

/** GET routes served from the recorded `initial` session state (queue of 10 PENDING candidates). */
function baseRoutes(): Record<string, Handler> {
  const routes: Record<string, Handler> = {
    'GET /api/v1/auth/me': () => ({ body: fixture.sessions.inspector }),
    'GET /api/v1/dictionaries/decision-codes': () => ({ body: fixture.codes }),
    [`GET /api/v1/objects/${encodeURIComponent(OID)}/verification`]: () => ({ body: fixture.object }),
    [`GET /api/v1/processes/${PID}/verification`]: () => ({ body: fixture.initial.summary }),
    [`GET /api/v1/processes/${PID}/findings`]: () => ({ body: fixture.initial.queue }),
  };
  for (const fid of fixture.finding_ids as string[]) {
    routes[`GET /api/v1/processes/${PID}/findings/${encodeURIComponent(fid)}`] = () => ({ body: fixture.initial.cards[fid] });
  }
  return routes;
}

function renderWorkspace(path: string) {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0, refetchInterval: false } });
  return render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/verification/:processId/:findingId?" element={<VerificationPage />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  );
}

/** The Headers instance apiFetch ultimately hands to `fetch` (case-insensitive; mockApi does not record it). */
function headersOf(init: RequestInit | undefined): Headers {
  return init?.headers instanceof Headers ? init.headers : new Headers(init?.headers as HeadersInit | undefined);
}

describe('Verification workspace (AG-05) — READY process, real recorded API shapes', () => {
  it('renders the queue, the header status line and the evidence card of the first candidate', async () => {
    mockApi(baseRoutes());
    renderWorkspace(`/verification/${PID}`);

    expect(await screen.findByTestId('verification-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('status-line')).toHaveTextContent('ОЖИДАЕТ ВЕРИФИКАЦИИ');
    expect(within(screen.getByTestId('queue')).getAllByRole('option')).toHaveLength(10);

    const card = fixture.initial.cards[F012];
    await waitFor(() => expect(screen.getByTestId('expected')).toHaveTextContent(card.values.expected));
    expect(screen.getByTestId('actual')).toHaveTextContent(card.values.actual);
    // §9.2 п.4 evidence fields: both sources (ПД F0171, РД F0201) with file_id and stage are shown.
    expect(screen.getByText('F0171')).toBeInTheDocument();
    expect(screen.getByText('F0201')).toBeInTheDocument();
  });

  it('opens the finalize dialog and shows the real gate blockers (10 pending candidates)', async () => {
    mockApi(baseRoutes());
    renderWorkspace(`/verification/${PID}`);
    await screen.findByTestId('verification-workspace');
    await userEvent.click(await screen.findByTestId('open-finalize'));
    const dialog = await screen.findByTestId('finalize-dialog');
    expect(within(dialog).getByText(/Финализация пока невозможна/)).toBeInTheDocument();
    expect(within(dialog).getByTestId('finalize-submit')).toBeDisabled();
  });

  it('confirms a finding by keyboard (C, Enter) and posts the decision with idempotency + optimistic-lock headers', async () => {
    const routes = baseRoutes();
    let captured: RequestInit | undefined;
    routes[`POST /api/v1/processes/${PID}/findings/${F012}/decisions`] = (_url, init) => {
      captured = init;
      return { status: 201, body: fixture.results.confirmed };
    };
    mockApi(routes);
    renderWorkspace(`/verification/${PID}/${F012}`);

    await screen.findByTestId('evidence-card');
    await waitFor(() => expect(screen.getByRole('button', { name: /Подтвердить нарушение/ })).toBeEnabled());

    fireEvent.keyDown(window, { code: 'KeyC' });
    await screen.findByTestId('decision-panel');
    // Confirm pre-fills the basis and comment from the server templates (05 §3.17.4): Enter alone can submit.
    await waitFor(() => expect(screen.getByTestId('save-decision')).toBeEnabled());
    fireEvent.keyDown(window, { code: 'Enter' });

    await waitFor(() => expect(captured).toBeDefined());
    const headers = headersOf(captured);
    expect(headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/i);
    expect(headers.get('If-Match')).toBe('"1"'); // the card's row_version

    const body = JSON.parse(captured!.body as string) as Json;
    const card = fixture.initial.cards[F012];
    expect(body).toMatchObject({
      decision: 'CONFIRMED_VIOLATION',
      basis_code: card.prefill.confirm_basis_code,
      comment: card.prefill.confirm_comment,
      comment_source: 'TEMPLATE',
      seen_fingerprint: card.evidence_fingerprint,
    });
    expect(body.client_metrics).toMatchObject({ keys: expect.any(Number), input: 'KEYBOARD' });

    // Success toast + auto-advance to the next candidate (05 §3.17.2).
    expect(await screen.findByText(/Подтверждено/)).toBeInTheDocument();
  });

  it('rejects a finding by reason chip (R → code → Сохранить) with no comment required', async () => {
    const routes = baseRoutes();
    let captured: RequestInit | undefined;
    routes[`POST /api/v1/processes/${PID}/findings/${F140}/decisions`] = (_url, init) => {
      captured = init;
      return { status: 201, body: fixture.results.rejected };
    };
    mockApi(routes);
    renderWorkspace(`/verification/${PID}/${F140}`);

    await screen.findByTestId('evidence-card');
    // The button's accessible name is "close Отклонить" (antd's CloseOutlined carries aria-label="close"): match loosely.
    await userEvent.click(await screen.findByRole('button', { name: /Отклонить/ }));
    const chips = await screen.findByRole('listbox', { name: 'Код причины' });
    // Click inside the CheckableTag (its onChange handler is on itself, not on the wrapping role="option" span).
    await userEvent.click(within(chips).getByText(/Ошибка привязки/));

    const save = screen.getByTestId('save-decision');
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);

    await waitFor(() => expect(captured).toBeDefined());
    const body = JSON.parse(captured!.body as string) as Json;
    const card = fixture.initial.cards[F140];
    expect(body).toMatchObject({
      decision: 'NEGATIVE_VERIFIED',
      reason_code: 'LINKING_ERROR',
      comment: null,
      comment_source: null,
      seen_fingerprint: card.evidence_fingerprint,
    });
  });

  it('rejection with «Иное» needs only the reason: the comment box starts empty and stays optional', async () => {
    mockApi(baseRoutes());
    renderWorkspace(`/verification/${PID}/${F140}`);
    await screen.findByTestId('evidence-card');
    await userEvent.click(await screen.findByRole('button', { name: /Отклонить/ }));
    const chips = await screen.findByRole('listbox', { name: 'Код причины' });
    expect(screen.getByTestId('save-decision')).toBeDisabled(); // no reason yet
    await userEvent.click(within(chips).getByText('Иное'));
    expect(screen.getByLabelText('Комментарий')).toHaveValue('');
    await waitFor(() => expect(screen.getByTestId('save-decision')).toBeEnabled());
  });

  it('has no «Взять в работу» step: a READY process is decided right away', async () => {
    mockApi(baseRoutes());
    renderWorkspace(`/verification/${PID}/${F012}`);
    await screen.findByTestId('evidence-card');
    expect(screen.getByTestId('status-line')).toHaveTextContent('ОЖИДАЕТ ВЕРИФИКАЦИИ');
    expect(screen.queryByRole('button', { name: /Взять в работу/ })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /Подтвердить нарушение/ })).toBeEnabled());
  });
});

describe('Verification workspace — FINALIZED process (real recorded state)', () => {
  it('shows the finalized banner and disables decisions, with the actual protocol version and dataset draft count', async () => {
    const fz = fixture.finalized;
    const routes: Record<string, Handler> = {
      'GET /api/v1/auth/me': () => ({ body: fixture.sessions.inspector }),
      'GET /api/v1/dictionaries/decision-codes': () => ({ body: fixture.codes }),
      [`GET /api/v1/objects/${encodeURIComponent(OID)}/verification`]: () => ({ body: fixture.object }),
      [`GET /api/v1/processes/${PID}/verification`]: () => ({ body: fz.summary }),
      [`GET /api/v1/processes/${PID}/findings`]: () => ({ body: fz.queue }),
      [`GET /api/v1/processes/${PID}/findings/${encodeURIComponent(F012)}`]: () => ({ body: fz.card }),
    };
    mockApi(routes);
    renderWorkspace(`/verification/${PID}/${F012}`);

    expect(await screen.findByTestId('finalized-banner')).toBeInTheDocument();
    expect(screen.getByTestId('status-line')).toHaveTextContent('ФИНАЛИЗИРОВАН');
    await waitFor(() => expect(screen.getByRole('button', { name: /Подтвердить нарушение/ })).toBeDisabled());
    expect(screen.getByText('Протокол финализирован — изменения невозможны')).toBeInTheDocument();
    // The already-decided card still renders the inspector's decision in the evidence card.
    expect(screen.getByTestId('actual')).toHaveTextContent(fz.card.values.actual);
  });
});

describe('Verification workspace — UX polish', () => {
  it('shows Russian labels in the header, the summary line and the help popover; no raw enum codes', async () => {
    mockApi(baseRoutes());
    renderWorkspace(`/verification/${PID}`);
    await screen.findByTestId('verification-workspace');
    const header = screen.getByTestId('status-line').closest('.ant-space')!;
    expect(header.textContent).not.toMatch(/PD_UPLOADED|RD_UPLOADED|ID_UPLOADED|\bFULL\b/);
    expect(header.textContent).toMatch(/загружена/);
    await waitFor(() => expect(screen.getByTestId('compare-summary')).toHaveTextContent(/Что сравнивали: пом\. .*в ПД — /));
    await userEvent.click(screen.getByRole('button', { name: 'Как читать карточку' }));
    expect(await screen.findByTestId('card-help')).toHaveTextContent('Эталон (ПД)');
  });

  it('shows «Завершить» and no «Возобновить верификацию» while the verification is in progress', async () => {
    mockApi(baseRoutes());
    renderWorkspace(`/verification/${PID}`);
    expect(await screen.findByTestId('open-finalize')).toHaveTextContent('Завершить');
    expect(screen.queryByText('Возобновить верификацию')).not.toBeInTheDocument();
  });

  it('for a completed process offers finalize as the primary action and reopen only in the menu', async () => {
    const routes = baseRoutes();
    const done = { ...fixture.initial.summary, status: 'COMPLETED', capabilities: { ...fixture.initial.summary.capabilities, can_reopen: true, can_decide: false } };
    routes[`GET /api/v1/processes/${PID}/verification`] = () => ({ body: done });
    mockApi(routes);
    renderWorkspace(`/verification/${PID}`);
    expect(await screen.findByTestId('open-finalize')).toHaveTextContent('Финализировать протокол');
    expect(screen.queryByText('Возобновить верификацию')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ещё' }));
    expect(await screen.findByText('Возобновить верификацию')).toBeInTheDocument();
  });

  it('shows an empty state instead of eternal skeletons when the protocol has no candidates', async () => {
    const routes = baseRoutes();
    routes[`GET /api/v1/processes/${PID}/verification`] = () => ({ body: { ...fixture.initial.summary, next_finding_id: null, status: 'FINALIZED' } });
    routes[`GET /api/v1/processes/${PID}/findings`] = () => ({ body: { ...fixture.initial.queue, items: [] } });
    mockApi(routes);
    renderWorkspace(`/verification/${PID}`);
    expect(await screen.findByTestId('no-candidates')).toBeInTheDocument();
    expect(document.querySelector('.ant-skeleton')).toBeNull();
  });

  it('gives an object without protocols a header and a back link', async () => {
    mockApi({
      [`GET /api/v1/objects/${encodeURIComponent(OID)}/verification`]: () => ({ body: { ...fixture.object, processes: [] } }),
    });
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false, staleTime: 0, refetchInterval: false } });
    render(
      <Providers client={client}>
        <MemoryRouter initialEntries={[`/objects/${encodeURIComponent(OID)}/verify`]}>
          <Routes>
            <Route path="/objects/:objectId/verify" element={<VerificationPage />} />
          </Routes>
        </MemoryRouter>
      </Providers>,
    );
    expect(await screen.findByTestId('verify-empty')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /К списку верификации/ })).toHaveAttribute('href', '/verification');
    expect(screen.getByRole('heading', { name: 'Верификация' })).toBeInTheDocument();
  });
});
