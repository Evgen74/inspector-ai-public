import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, setCsrfToken } from './client';

function stubFetch() {
  const seen: Array<{ method: string; csrf: string | null }> = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({ method: init?.method ?? 'GET', csrf: new Headers(init?.headers).get('X-CSRF-Token') });
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
    }),
  );
  return seen;
}

describe('apiFetch CSRF', () => {
  afterEach(() => {
    setCsrfToken(null);
    vi.unstubAllGlobals();
  });

  it('sends the session token on unsafe requests only (an upload is refused without it)', async () => {
    const seen = stubFetch();
    setCsrfToken('tok-1');
    await apiFetch('/processes');
    await apiFetch('/documents/upload', { method: 'POST', body: new FormData() });
    await apiFetch('/objects/x', { method: 'delete' });
    expect(seen).toEqual([
      { method: 'GET', csrf: null },
      { method: 'POST', csrf: 'tok-1' },
      { method: 'delete', csrf: 'tok-1' },
    ]);
  });

  it('keeps an explicit header and sends nothing without a session', async () => {
    const seen = stubFetch();
    setCsrfToken('tok-1');
    await apiFetch('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': 'explicit' } });
    setCsrfToken(null);
    await apiFetch('/documents/upload', { method: 'POST', body: new FormData() });
    expect(seen.map((s) => s.csrf)).toEqual(['explicit', null]);
  });
});
