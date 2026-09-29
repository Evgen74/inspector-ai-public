import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createTestApp, parseLogs, type TestApp } from './helpers';

const UUID_V7 = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('GET /api/v1/health', () => {
  let t: TestApp;
  beforeAll(async () => {
    t = await createTestApp();
  });
  afterAll(async () => {
    await t.close();
  });

  it('returns ok when the database answers', async () => {
    t.database.down = false;
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/health' });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body).toMatchObject({ status: 'ok', service: 'inspector-api', checks: { database: { status: 'up' } } });
    expect(typeof body.version).toBe('string');
    expect(Number.isNaN(Date.parse(body.time))).toBe(false);
  });

  it('returns 503 degraded when the database is down', async () => {
    t.database.down = true;
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/health' });
    t.database.down = false;
    expect(res.statusCode).toBe(503);
    expect(res.json()).toMatchObject({ status: 'degraded', checks: { database: { status: 'down' } } });
  });

  it('generates a UUID v7 request id when none is sent', async () => {
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/health' });
    expect(res.headers['x-request-id']).toMatch(UUID_V7);
  });

  it('echoes a well-formed X-Request-Id and replaces a malformed one', async () => {
    const ok = await t.http.inject({ method: 'GET', url: '/api/v1/health', headers: { 'x-request-id': 'nginx-req-0001' } });
    expect(ok.headers['x-request-id']).toBe('nginx-req-0001');
    const bad = await t.http.inject({ method: 'GET', url: '/api/v1/health', headers: { 'x-request-id': 'bad id with spaces' } });
    expect(bad.headers['x-request-id']).toMatch(UUID_V7);
  });

  it('writes structured JSON logs carrying the same request_id', async () => {
    t.logs.length = 0;
    const res = await t.http.inject({ method: 'GET', url: '/api/v1/health', headers: { 'x-request-id': 'trace-me-123456' } });
    expect(res.statusCode).toBe(200);
    const lines = parseLogs(t.logs);
    const line = lines.find((l) => l.request_id === 'trace-me-123456');
    expect(line).toBeDefined();
    expect(line).toMatchObject({ level: 'info', service: 'inspector-api', event: 'http_request' });
    expect(typeof line?.timestamp).toBe('string');
    expect(typeof line?.message).toBe('string');
    expect(typeof line?.duration_ms).toBe('number');
  });
});
