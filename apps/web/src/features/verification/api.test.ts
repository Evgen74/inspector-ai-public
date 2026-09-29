import { afterEach, describe, expect, it, vi } from 'vitest';
import { postJson } from './api';

describe('postJson', () => {
  afterEach(() => vi.restoreAllMocks());

  const capture = () =>
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }));

  it('sends no body and no JSON Content-Type for an operation without a requestBody (claim → 415 otherwise)', async () => {
    const fetchSpy = capture();
    await postJson('/processes/p1/verification/claim', undefined, { csrf: 't' });
    const init = fetchSpy.mock.calls[0]![1]!;
    expect(init.body).toBeUndefined();
    expect(new Headers(init.headers).get('Content-Type')).toBeNull();
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('t');
  });

  it('sends a JSON body when one is given', async () => {
    const fetchSpy = capture();
    await postJson('/processes/p1/findings/F-1/decisions', { status: 'CONFIRMED_VIOLATION' });
    const init = fetchSpy.mock.calls[0]![1]!;
    expect(init.body).toBe('{"status":"CONFIRMED_VIOLATION"}');
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json');
  });
});
