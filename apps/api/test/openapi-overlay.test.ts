/**
 * The pending AG-08 overlay (apps/api/openapi/pending) only adds to the contracts document: no path, component
 * or tag of the base is redefined, and adopting it verbatim into the base is a no-op for the merge.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parse as parseYaml } from 'yaml';
import { loadEnums } from '../src/contracts/contracts';
import {
  loadOpenApiDocument,
  mergeOpenApiOverlay,
  OPENAPI_OVERLAY_CONFLICTS,
  OPENAPI_PATH,
  pendingOverlayFiles,
} from '../src/openapi/openapi.service';
import { REPO_CONTRACTS } from './helpers';

type Json = Record<string, unknown>;
const base = parseYaml(readFileSync(OPENAPI_PATH, 'utf8')) as Json;
const overlays = pendingOverlayFiles().map((f) => parseYaml(readFileSync(f, 'utf8')) as Json);
/** The D1 overlay (dashboard, protocols, IndicatorReason); other overlays are looked up by content, not by position. */
const d1Overlay = overlays.find((o) => '/dashboard' in ((o.paths ?? {}) as Json))!;

describe('pending OpenAPI overlay (AG-08 → AG-00)', () => {
  it('exists and merges into the contracts document without conflicts', () => {
    expect(overlays.length).toBeGreaterThan(0);
    loadOpenApiDocument();
    expect(OPENAPI_OVERLAY_CONFLICTS).toEqual([]);
  });

  it('adds the D1 operations', () => {
    const doc = loadOpenApiDocument() as unknown as { paths: Record<string, Record<string, { operationId?: string }>> };
    const ids = Object.values(doc.paths).flatMap((item) => Object.values(item).map((op) => op.operationId));
    expect(ids).toEqual(
      expect.arrayContaining([
        'getDashboard',
        'listObjectProtocols',
        'getObjectProtocol',
        'exportObjectProtocol',
        'getFileAnnotations',
      ]),
    );
  });

  it('is idempotent once adopted: an identical entry is skipped, a different one is reported', () => {
    const overlay = d1Overlay;
    const adopted = mergeOpenApiOverlay(base, overlay);
    const conflicts: string[] = [];
    const again = mergeOpenApiOverlay(adopted, overlay, 'again', conflicts);
    expect(conflicts).toEqual([]);
    expect(again).toEqual(adopted);
    const changed = structuredClone(overlay) as { paths: Record<string, Json> };
    changed.paths['/dashboard'] = { get: { operationId: 'somethingElse' } };
    const reported: string[] = [];
    const kept = mergeOpenApiOverlay(adopted, changed, 'changed', reported) as { paths: Record<string, { get: { operationId: string } }> };
    expect(reported).toEqual(['changed: paths./dashboard']);
    expect(kept.paths['/dashboard']!.get.operationId).toBe('getDashboard');
  });

  it('proposes IndicatorReason for enums.yaml and uses only existing enum values elsewhere', () => {
    const enums = loadEnums(REPO_CONTRACTS);
    const schemas = (d1Overlay.components as { schemas: Record<string, Json> }).schemas;
    const proposed = schemas.IndicatorReason as { 'x-contract-enum-proposed': string; enum: string[] };
    expect(proposed['x-contract-enum-proposed']).toBe('IndicatorReason');
    // Not yet in the contract; once AG-00 adds it, this test must switch to x-contract-enum.
    if (enums.IndicatorReason) {
      expect(enums.IndicatorReason.values.map((v) => v.code)).toEqual(proposed.enum);
    }
    for (const [name, schema] of Object.entries(schemas)) {
      const enumName = schema['x-contract-enum'] as string | undefined;
      if (!enumName) continue;
      const codes = enums[enumName]!.values.map((v) => v.code);
      const values = (schema.enum as Array<string | null>).filter((v): v is string => v !== null);
      expect(values, name).toEqual(codes);
    }
  });
});
