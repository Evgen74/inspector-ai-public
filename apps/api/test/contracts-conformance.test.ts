/**
 * The OpenAPI document, the Nest routes and packages/contracts agree:
 * - every OpenAPI operation has a route and every API route has an operation;
 * - enums marked `x-contract-enum` equal enums.yaml;
 * - every `x-error-codes` entry exists in errors.yaml; errors are application/problem+json.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { enumCodes, loadEnums } from '../src/contracts/contracts';
import { ErrorCatalog } from '../src/common/problem';
import { Rbac } from '../src/modules/auth/rbac';
import { loadOpenApiDocument } from '../src/openapi/openapi.service';
import { createTestApp, REPO_CONTRACTS, type TestApp } from './helpers';

type Json = Record<string, unknown>;

function walk(node: unknown, visit: (n: Json) => void): void {
  if (Array.isArray(node)) node.forEach((n) => walk(n, visit));
  else if (node && typeof node === 'object') {
    visit(node as Json);
    Object.values(node).forEach((n) => walk(n, visit));
  }
}

const doc = loadOpenApiDocument() as unknown as Json & { paths: Record<string, Record<string, Json>> };
const METHODS = ['get', 'post', 'put', 'patch', 'delete'];

/** Parse Fastify's printRoutes() tree («├── /seg (GET, HEAD)», children indented by 4) into full paths. */
function parseRouteTree(text: string): Array<{ method: string; url: string }> {
  const out: Array<{ method: string; url: string }> = [];
  const stack: string[] = [];
  for (const line of text.split('\n')) {
    const m = line.match(/^(.*?)(?:├── |└── )(\S+)(?: \(([^)]*)\))?/);
    if (!m) continue;
    const depth = Math.round((m[1] ?? '').length / 4);
    stack.length = depth;
    const url = (depth > 0 ? (stack[depth - 1] ?? '') : '') + (m[2] ?? '');
    stack[depth] = url;
    for (const method of (m[3] ?? '').split(',').map((x) => x.trim()).filter(Boolean)) {
      out.push({ method, url });
    }
  }
  return out;
}


describe('OpenAPI ↔ routes ↔ contracts', () => {
  let t: TestApp;
  beforeAll(async () => {
    t = await createTestApp();
  });
  afterAll(async () => {
    await t.close();
  });

  it('is OpenAPI 3.0.x served under /api/v1', () => {
    expect(String(doc.openapi)).toMatch(/^3\.0\.\d$/);
    expect((doc.servers as Array<{ url: string }>)[0]?.url).toBe('/api/v1');
  });

  it('has a Nest route for every operation, and an operation for every route', () => {
    const operations: string[] = [];
    for (const [p, item] of Object.entries(doc.paths)) {
      for (const m of METHODS) {
        if (item[m]) {
          operations.push(`${m.toUpperCase()} /api/v1${p}`);
          const url = `/api/v1${p}`.replace(/\{([^}]+)\}/g, ':$1');
          expect(t.http.hasRoute({ method: m.toUpperCase() as 'GET', url }), `${m} ${p}`).toBe(true);
        }
      }
    }
    const routes = parseRouteTree(t.http.printRoutes({ commonPrefix: false }))
      .filter((r) => r.method !== 'HEAD' && r.url.startsWith('/api/v1/'))
      .map((r) => `${r.method} ${r.url.replace(/:([A-Za-z_]+)/g, '{$1}')}`);
    expect(routes.length).toBe(operations.length);
    expect([...routes].sort()).toEqual([...operations].sort());
  });

  it('declares operationId, x-owner and x-error-codes that exist in errors.yaml', () => {
    const catalog = ErrorCatalog.load(REPO_CONTRACTS);
    for (const [p, item] of Object.entries(doc.paths)) {
      for (const m of METHODS) {
        const op = item[m];
        if (!op) continue;
        expect(op.operationId, `${m} ${p}`).toBeTypeOf('string');
        // Owners of API operations per CLAUDE.md: AG-08 (web), AG-05 (verification), AG-00 (platform services).
        expect(['AG-00', 'AG-05', 'AG-08'], `${m} ${p}`).toContain(op['x-owner']);
        for (const code of op['x-error-codes'] as string[]) {
          expect(catalog.has(code), `${m} ${p}: ${code}`).toBe(true);
        }
      }
    }
  });

  it('names only rbac.yaml permissions and AuditAction values; public operations are explicit', () => {
    const rbac = Rbac.load(REPO_CONTRACTS);
    const actions = enumCodes(loadEnums(REPO_CONTRACTS), 'AuditAction');
    const publicOps: string[] = [];
    for (const [p, item] of Object.entries(doc.paths)) {
      for (const m of METHODS) {
        const op = item[m];
        if (!op) continue;
        const permission = op['x-permission'];
        if (permission !== undefined) expect(rbac.has(String(permission)), `${m} ${p}: ${String(permission)}`).toBe(true);
        const action = op['x-audit-action'];
        if (action !== undefined) expect(actions, `${m} ${p}`).toContain(action);
        if (Array.isArray(op.security) && op.security.length === 0) publicOps.push(`${m.toUpperCase()} ${p}`);
      }
    }
    expect(publicOps.sort()).toEqual(['GET /health', 'POST /auth/login']);
    expect(doc.security).toEqual([{ sessionCookie: [] }]);
  });

  it('keeps x-contract-enum values identical to packages/contracts/enums.yaml', () => {
    const enums = loadEnums(REPO_CONTRACTS);
    let checked = 0;
    walk(doc.components, (node) => {
      const name = node['x-contract-enum'];
      if (typeof name === 'string') {
        const values = (node.enum as unknown[]).filter((v) => v !== null);
        expect(values, name).toEqual(enumCodes(enums, name));
        checked += 1;
      }
    });
    expect(checked).toBeGreaterThanOrEqual(7);
  });

  it('describes every 4xx/5xx response as application/problem+json Problem (except /health)', () => {
    const responses = (doc.components as Json).responses as Record<string, Json>;
    for (const [name, response] of Object.entries(responses)) {
      const content = response.content as Record<string, { schema: { $ref: string } }>;
      expect(Object.keys(content), name).toEqual(['application/problem+json']);
      expect(content['application/problem+json']?.schema.$ref).toBe('#/components/schemas/Problem');
    }
  });
});
