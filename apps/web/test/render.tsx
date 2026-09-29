import { render } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { MemoryRouter, useLocation } from 'react-router';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { createHandlers } from '../src/mocks/handlers';
import { AppRoutes, createQueryClient, Providers } from '../src/App';

type Handler = (url: URL, init?: RequestInit) => { status?: number; body: unknown; headers?: Record<string, string> };

/** Stub fetch with a router of path → response; records the requests. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Array<{ url: string; method: string; body?: string }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    calls.push({ url: url.pathname + url.search, method: init?.method ?? 'GET', body: init?.body as string | undefined });
    const key = Object.keys(routes).find((k) => {
      const [method, path] = k.includes(' ') ? k.split(' ') : ['GET', k];
      return (init?.method ?? 'GET') === method && url.pathname === path;
    });
    if (!key) {
      return new Response(JSON.stringify({ code: 'NOT_FOUND', title: 'Не найдено', detail: 'нет', request_id: 'r' }), {
        status: 404,
        headers: { 'Content-Type': 'application/problem+json' },
      });
    }
    const res = routes[key]!(url, init);
    return new Response(JSON.stringify(res.body), {
      status: res.status ?? 200,
      headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'req-test-1', ...res.headers },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

export function renderAt(path: string) {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0 } });
  return render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
}

/** Current router location, for assertions on URL-synced state (filters, navigation). */
export const currentLocation = { pathname: '', search: '' };

function LocationProbe() {
  const loc = useLocation();
  currentLocation.pathname = decodeURIComponent(loc.pathname);
  currentLocation.search = decodeURIComponent(loc.search);
  return null;
}

/** Render the app at `path` against the MSW handlers (see useMockApi). */
export function renderApp(path: string) {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0, refetchInterval: false } });
  return render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationProbe />
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
}

/** MSW server over the contract-typed mock handlers, with request recording. */
export function useMockApi() {
  const requests: string[] = [];
  const server = setupServer(...createHandlers());
  server.events.on('request:start', ({ request }) => {
    const u = new URL(request.url);
    requests.push(decodeURIComponent(u.pathname + u.search));
  });
  beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => {
    server.resetHandlers();
    requests.length = 0;
  });
  afterAll(() => server.close());
  return { server, requests };
}
