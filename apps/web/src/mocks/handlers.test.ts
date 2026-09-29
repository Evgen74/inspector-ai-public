// @vitest-environment node
/**
 * Mocks are generated from the contract, not invented: every JSON body the MSW handlers return validates against
 * the response schema of the OpenAPI document the API serves (contracts file + pending AG-08 overlay).
 */
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import { setupServer } from 'msw/node';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
// @ts-expect-error — plain ESM script without type declarations
import { mergedDocument } from '../../scripts/gen-api-types.mjs';
import { RUN_IDS, TYUMEN } from './data';
import { createHandlers, tileSvg } from './handlers';

const { doc } = mergedDocument() as { doc: { paths: Record<string, Record<string, { responses: Record<string, { content?: Record<string, { schema: unknown }> }> }>> } };
const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
ajv.addFormat('binary', true);
ajv.addSchema({ ...(doc as object), $id: 'openapi' } as never, 'openapi');

function responseSchema(pathTemplate: string, status: number): unknown {
  let r = doc.paths[pathTemplate]!.get!.responses[String(status)]! as { $ref?: string; content?: Record<string, { schema: unknown }> };
  if (r.$ref) {
    const name = r.$ref.split('/').at(-1)!;
    r = (doc as unknown as { components: { responses: Record<string, typeof r> } }).components.responses[name]!;
  }
  const content = r.content ?? {};
  return (content['application/json'] ?? content['application/problem+json'])!.schema;
}

function check(pathTemplate: string, status: number, body: unknown): string[] {
  const schema = responseSchema(pathTemplate, status);
  // $refs in the response schema are relative to the OpenAPI document registered as «openapi».
  const fn = ajv.compile(JSON.parse(JSON.stringify(schema).replaceAll('"#/components', '"openapi#/components')));
  return fn(body) ? [] : (fn.errors ?? []).map((e) => `${e.instancePath} ${e.message}`);
}

const server = setupServer(...createHandlers());
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());

const BASE = 'http://localhost/api/v1';
async function get(url: string): Promise<{ status: number; body: unknown }> {
  const res = await fetch(`${BASE}${url}`);
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null };
}

const CASES: Array<[string, string, number]> = [
  ['/dashboard', '/dashboard', 200],
  ['/dashboard?color=RED,YELLOW&section=ИОС4&status=PENDING&scenario=PD_RD_ONLY&date_from=2026-09-01&date_to=2026-09-30', '/dashboard', 200],
  ['/objects', '/objects', 200],
  [`/objects/${TYUMEN}`, '/objects/{object_id}', 200],
  ['/objects/OBJ-NOPE', '/objects/{object_id}', 404],
  [`/objects/${TYUMEN}/files`, '/objects/{object_id}/files', 200],
  [`/objects/${TYUMEN}/protocols`, '/objects/{object_id}/protocols', 200],
  ['/objects/OBJ-SYNTH-HIDDEN/protocols', '/objects/{object_id}/protocols', 403],
  [`/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}`, '/objects/{object_id}/protocols/{run_id}', 200],
  [`/objects/OBJ-SYNTH-RED/protocols/${RUN_IDS.red}`, '/objects/{object_id}/protocols/{run_id}', 200],
  [`/objects/OBJ-SYNTH-GREEN/protocols/${RUN_IDS.green}`, '/objects/{object_id}/protocols/{run_id}', 200],
  [`/objects/${TYUMEN}/protocols/${RUN_IDS.red}`, '/objects/{object_id}/protocols/{run_id}', 404],
  ['/files/F0202/annotations?page=17', '/files/{file_id}/annotations', 200],
  ['/files/F0171/annotations?page=88', '/files/{file_id}/annotations', 200],
  ['/health', '/health', 200],
  ['/admin/batch-runs', '/admin/batch-runs', 200],
];

describe('MSW handlers ↔ OpenAPI responses', () => {
  it.each(CASES)('GET %s', async (url, template, status) => {
    const res = await get(url);
    expect(res.status).toBe(status);
    expect(check(template, status, res.body)).toEqual([]);
  });

  it('computes every indicator colour with the API rule', async () => {
    const res = (await get('/dashboard')).body as { tiles: Record<string, number>; items: Array<{ object_id: string; indicator: { color: string } }> };
    const colors = Object.fromEntries(res.items.map((i) => [i.object_id, i.indicator.color]));
    expect(colors).toEqual({
      'OBJ-SYNTH-GREEN': 'GREEN',
      'OBJ-SYNTH-HIDDEN': 'NONE',
      'OBJ-SYNTH-NEW': 'NONE',
      'OBJ-SYNTH-RED': 'RED',
      [TYUMEN]: 'YELLOW',
    });
    expect(res.tiles).toMatchObject({ total: 5, RED: 1, YELLOW: 1, GREEN: 1, NONE: 2 });
  });

  it('serves the PageView of the render service and SVG tiles of the exact edge size', async () => {
    const meta = (await get('/files/F0202/pages/17')).body as { width_px: number; height_px: number; max_level: number; tile_url_template: string; layers: unknown[] };
    expect(meta.width_px).toBe(4967);
    expect(meta.height_px).toBe(7021);
    expect(meta.tile_url_template).toBe('/api/v1/files/F0202/pages/17/tiles/{level}/{x}/{y}');
    expect(meta.layers.length).toBeGreaterThan(5);
    const { layers: _l, ...view } = meta;
    expect(check('/files/{file_id}/pages/{page_no}', 200, view)).toEqual([]);
    const svg = tileSvg('F0202', 17, meta.max_level, 9, 0, 0);
    expect(svg).toContain('width="359"'); // 4967 − 9·512
  });

  it('streams exports with a UTF-8 file name', async () => {
    const res = await fetch(`${BASE}/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}/export?format=docx`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-disposition')).toContain("filename*=UTF-8''");
  });
});
