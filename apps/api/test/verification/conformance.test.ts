/**
 * The verification overlay (apps/api/src/modules/verification/openapi/verification.openapi.yaml) is ready for
 * AG-00 to merge into packages/contracts/openapi/openapi.yaml: it merges without conflicts, every operation has a
 * route and every verification route has an operation, enums equal enums.yaml, error codes / permissions / audit
 * actions exist, and the SQL migration matches the Drizzle schema (tables and columns).
 */
import { readFileSync } from 'node:fs';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { parse as parseYaml } from 'yaml';
import { ErrorCatalog } from '../../src/common/problem';
import { enumCodes, loadEnums } from '../../src/contracts/contracts';
import { Rbac } from '../../src/modules/auth/rbac';
import { getTableConfig } from 'drizzle-orm/pg-core';
import * as schema from '../../src/modules/verification/verification.schema';
import { VERIFICATION_MIGRATION_SQL, VERIFICATION_OPENAPI_OVERLAY } from '../../src/modules/verification';
import { loadOpenApiDocument, mergeOpenApiOverlay, OPENAPI_PATH, pendingOverlayFiles } from '../../src/openapi/openapi.service';
import { REPO_CONTRACTS } from '../helpers';
import { createVerificationApp, type VerificationTestApp } from './harness';

type Json = Record<string, any>;
const METHODS = ['get', 'post', 'put', 'patch', 'delete'];
const overlay = parseYaml(readFileSync(VERIFICATION_OPENAPI_OVERLAY, 'utf8')) as Json;

function walk(node: unknown, visit: (n: Json) => void): void {
  if (Array.isArray(node)) node.forEach((n) => walk(n, visit));
  else if (node && typeof node === 'object') {
    visit(node as Json);
    Object.values(node).forEach((n) => walk(n, visit));
  }
}

describe('verification OpenAPI overlay', () => {
  let t: VerificationTestApp;
  beforeAll(async () => {
    t = await createVerificationApp();
  });
  afterAll(async () => {
    await t.close();
  });

  it('merges into the contracts document (+ pending overlays) without a single conflict', () => {
    const conflicts: string[] = [];
    const base = loadOpenApiDocument(OPENAPI_PATH, pendingOverlayFiles()) as unknown as Json;
    const merged = mergeOpenApiOverlay(base, overlay, 'verification', conflicts);
    expect(conflicts).toEqual([]);
    expect(Object.keys(overlay.paths).every((p) => p in (merged.paths as Json))).toBe(true);
  });

  it('has a Nest route for every operation and an operation for every verification route', () => {
    const ops: string[] = [];
    for (const [p, item] of Object.entries(overlay.paths as Record<string, Json>)) {
      for (const m of METHODS) {
        if (!item[m]) continue;
        ops.push(`${m.toUpperCase()} ${p}`);
        const url = `/api/v1${p}`.replace(/\{([^}]+)\}/g, ':$1');
        expect(t.http.hasRoute({ method: m.toUpperCase() as 'GET', url }), `${m} ${p}`).toBe(true);
      }
    }
    expect(ops).toHaveLength(20);
  });

  it('declares owner, permission, audit action and error codes that exist in the contracts', () => {
    const catalog = ErrorCatalog.load(REPO_CONTRACTS);
    const rbac = Rbac.load(REPO_CONTRACTS);
    const actions = enumCodes(loadEnums(REPO_CONTRACTS), 'AuditAction');
    for (const [p, item] of Object.entries(overlay.paths as Record<string, Json>)) {
      for (const m of METHODS) {
        const op = item[m];
        if (!op) continue;
        expect(op['x-owner'], `${m} ${p}`).toBe('AG-05');
        expect(rbac.has(op['x-permission']), `${m} ${p}: ${op['x-permission']}`).toBe(true);
        if (m !== 'get') expect(actions, `${m} ${p}`).toContain(op['x-audit-action']);
        for (const code of op['x-error-codes'] as string[]) expect(catalog.has(code), `${m} ${p}: ${code}`).toBe(true);
        expect(op.security, `${m} ${p} must not be public`).toBeUndefined();
      }
    }
  });

  it('keeps every x-contract-enum equal to enums.yaml and never lists PARTIALLY_CONFIRMED (I2)', () => {
    const enums = loadEnums(REPO_CONTRACTS);
    let checked = 0;
    walk(overlay.components, (node) => {
      const name = node['x-contract-enum'];
      if (typeof name === 'string') {
        expect((node.enum as unknown[]).filter((v) => v !== null), name).toEqual(enumCodes(enums, name));
        checked += 1;
      }
    });
    expect(checked).toBeGreaterThanOrEqual(25);
    walk(overlay, (node) => {
      if (Array.isArray(node.enum)) expect(node.enum).not.toContain('PARTIALLY_CONFIRMED');
    });
  });

  it('describes every error response as application/problem+json Problem', () => {
    for (const [name, response] of Object.entries(overlay.components.responses as Record<string, Json>)) {
      expect(Object.keys(response.content), name).toEqual(['application/problem+json']);
      expect(response.content['application/problem+json'].schema.$ref).toBe('#/components/schemas/Problem');
    }
  });
});

describe('verification SQL migration', () => {
  const sql = readFileSync(VERIFICATION_MIGRATION_SQL, 'utf8');
  it('creates every Drizzle table with every column', () => {
    const tables = [schema.verificationDecisions, schema.rejectionLog, schema.disputeLog, schema.datasetItems, schema.verificationIdempotency, schema.uiEvents];
    for (const table of tables) {
      const cfg = getTableConfig(table);
      const block = new RegExp(`CREATE TABLE "${cfg.name}" \\(([\\s\\S]*?)\\n\\);`).exec(sql);
      expect(block, cfg.name).not.toBeNull();
      for (const col of cfg.columns) expect(block![1], `${cfg.name}.${col.name}`).toContain(`"${col.name}"`);
    }
  });
  it('carries the invariants: append-only decisions, finalization lock, inspector-only confirmation, no PARTIALLY_CONFIRMED', () => {
    expect(sql).toContain('CREATE TRIGGER verification_decisions_block_update_delete');
    expect(sql).toContain('CREATE TRIGGER checks_inspector_block_finalized');
    expect(sql).toContain('"checks_confirmed_by_inspector_chk"');
    expect(sql).toContain('"checks_inspector_status_chk"');
    expect(sql).not.toContain("'PARTIALLY_CONFIRMED'");
    expect(sql.split('--> statement-breakpoint').length).toBeGreaterThan(40);
  });
});
