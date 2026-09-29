/**
 * MSW handlers for every endpoint the web uses. Bodies are typed with the generated OpenAPI types
 * (src/api/schema.gen.ts) and `src/mocks/handlers.test.ts` validates each JSON body against the response schema
 * of the merged OpenAPI document, so the mocks cannot drift from the contract. Page meta/tiles follow the
 * adapter in src/features/evidence/pageSource.ts (AG-00's render service); tiles are drawn as SVG.
 */
import { http, HttpResponse } from 'msw';
import type { components } from '../api/schema.gen';
import type { Page } from '../api/types';
import {
  annotationsOf,
  buildMockObjects,
  dashboardOf,
  filesOf,
  type MockObject,
  pageViewOf,
  versionsOf,
} from './data';

type S = components['schemas'];
/** Any origin: the browser worker (same origin) and Node (tests, absolute URLs) share the handlers. */
const API = '*/api/v1';
const HEADERS = { 'X-Request-Id': 'mock-request' };

function problem(status: number, code: string, title: string, detail: string, instance: string) {
  return HttpResponse.json(
    {
      type: `/problems/${code.toLowerCase().replaceAll('_', '-')}`,
      title,
      status,
      detail,
      instance: `${instance}#mock-request`,
      code,
      request_id: 'mock-request',
      timestamp: new Date().toISOString(),
      retryable: false,
    } satisfies S['Problem'],
    { status, headers: { ...HEADERS, 'Content-Type': 'application/problem+json' } },
  );
}

const notFound = (path: string) => problem(404, 'NOT_FOUND', 'Не найдено', 'Запрошенный ресурс не найден.', path);
const hiddenDenied = (path: string, objectId: string) =>
  problem(
    403,
    'HIDDEN_TEST_ACCESS_DENIED',
    'Доступ к скрытой выборке запрещён',
    `Объект ${objectId} входит в скрытую тестовую выборку; оценка и настройка по нему запрещены.`,
    path,
  );

/** One SVG tile of `level` (x, y) with the exact pixel size OSD expects at the page edge. */
export function tileSvg(fileId: string, page: number, level: number, x: number, y: number, hidden: number): string {
  const meta = pageViewOf(fileId, page);
  const scale = 2 ** (level - meta.max_level);
  const lw = Math.ceil(meta.width_px * scale);
  const lh = Math.ceil(meta.height_px * scale);
  const w = Math.max(1, Math.min(meta.tile_size, lw - x * meta.tile_size));
  const h = Math.max(1, Math.min(meta.tile_size, lh - y * meta.tile_size));
  const step = Math.max(8, 64 * 2 ** Math.min(0, level - meta.max_level + 2));
  const lines: string[] = [];
  for (let i = 0; i <= w; i += step) lines.push(`<line x1="${i}" y1="0" x2="${i}" y2="${h}"/>`);
  for (let j = 0; j <= h; j += step) lines.push(`<line x1="0" y1="${j}" x2="${w}" y2="${j}"/>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<rect width="${w}" height="${h}" fill="#ffffff"/>
<g stroke="#e3e7ee" stroke-width="1">${lines.join('')}</g>
<text x="8" y="18" font-family="sans-serif" font-size="11" fill="#b0b6c0">${fileId} · стр. ${page} · ур. ${level} (${x},${y})${hidden ? ` · скрыто слоёв: ${hidden}` : ''}</text>
</svg>`;
}

export function createHandlers(objects: Map<string, MockObject> = buildMockObjects()) {
  const summary = (o: MockObject): S['ObjectSummary'] => {
    const { input_manifest_hash: _h, address: _a, customer: _c, contractor: _k, permit_number: _p, created_at: _t, ...rest } = o.detail;
    return rest as S['ObjectSummary'];
  };
  const obj = (id: string) => objects.get(decodeURIComponent(id));

  return [
    http.get(`${API}/health`, () =>
      HttpResponse.json(
        {
          status: 'ok',
          service: 'inspector-api',
          version: '0.1.0-mock',
          time: new Date().toISOString(),
          checks: { database: { status: 'up', latency_ms: 1 } },
        } satisfies S['Health'],
        { headers: HEADERS },
      ),
    ),
    http.get(`${API}/dashboard`, ({ request }) =>
      HttpResponse.json(dashboardOf(objects, new URL(request.url).searchParams), { headers: HEADERS }),
    ),
    http.get(`${API}/objects`, ({ request }) => {
      const q = new URL(request.url).searchParams.get('q')?.toLowerCase();
      const items = [...objects.values()]
        .filter((o) => !q || o.detail.object_id.toLowerCase().includes(q) || (o.detail.name ?? '').toLowerCase().includes(q))
        .map(summary);
      return HttpResponse.json({ items, total: items.length, page: 1, page_size: 50 } satisfies S['ObjectList'], { headers: HEADERS });
    }),
    http.get(`${API}/objects/:objectId`, ({ params, request }) => {
      const o = obj(String(params.objectId));
      return o ? HttpResponse.json(o.detail as S['ObjectDetail'], { headers: HEADERS }) : notFound(new URL(request.url).pathname);
    }),
    http.get(`${API}/objects/:objectId/files`, ({ params, request }) => {
      const o = obj(String(params.objectId));
      if (!o) return notFound(new URL(request.url).pathname);
      const stage = new URL(request.url).searchParams.get('stage');
      const items = filesOf(o.detail.object_id).filter((f) => !stage || f.manifest_stage === stage);
      return HttpResponse.json({ items, total: items.length, page: 1, page_size: 50 } satisfies Page<unknown> as S['FileList'], { headers: HEADERS });
    }),
    http.get(`${API}/objects/:objectId/protocols`, ({ params, request }) => {
      const o = obj(String(params.objectId));
      const path = new URL(request.url).pathname;
      if (!o) return notFound(path);
      if (o.detail.split === 'TEST_HIDDEN') return hiddenDenied(path, o.detail.object_id);
      return HttpResponse.json({ object_id: o.detail.object_id, items: versionsOf(o) } satisfies S['ProtocolVersionList'], { headers: HEADERS });
    }),
    http.get(`${API}/objects/:objectId/protocols/:runId`, ({ params, request }) => {
      const o = obj(String(params.objectId));
      const path = new URL(request.url).pathname;
      if (!o) return notFound(path);
      if (o.detail.split === 'TEST_HIDDEN') return hiddenDenied(path, o.detail.object_id);
      const entry = o.protocols.find((p) => p.runId === params.runId);
      const version = versionsOf(o).find((v) => v.run_id === params.runId);
      if (!entry || !version) return notFound(path);
      return HttpResponse.json(
        { version, protocol: entry.protocol as unknown as S['ContractProtocol'], finding_groups: entry.groups as unknown as S['ContractFindingGroup'][], warnings: [] } satisfies S['ProtocolView'],
        { headers: HEADERS },
      );
    }),
    http.get(`${API}/objects/:objectId/protocols/:runId/export`, ({ params, request }) => {
      const o = obj(String(params.objectId));
      const url = new URL(request.url);
      const format = url.searchParams.get('format') ?? '';
      const entry = o?.protocols.find((p) => p.runId === params.runId);
      if (!o || !entry || !entry.formats.includes(format as 'json')) return notFound(url.pathname);
      const name = `Протокол_${entry.protocol.protocol_no}.${format}`;
      const disposition = `attachment; filename*=UTF-8''${encodeURIComponent(name)}`;
      if (format === 'json') {
        return new HttpResponse(JSON.stringify(entry.protocol, null, 2), {
          headers: { 'Content-Type': 'application/json', 'Content-Disposition': disposition },
        });
      }
      return new HttpResponse(`Демонстрационный файл ${name}`, {
        headers: { 'Content-Type': 'application/octet-stream', 'Content-Disposition': disposition },
      });
    }),
    http.get(`${API}/files/:fileId/annotations`, ({ params, request }) => {
      const page = Number(new URL(request.url).searchParams.get('page') ?? '1');
      return HttpResponse.json(annotationsOf(String(params.fileId), page), { headers: HEADERS });
    }),
    http.get(`${API}/files/:fileId/pages/:page`, ({ params }) => {
      const { layers, ...view } = pageViewOf(String(params.fileId), Number(params.page));
      // `layers` is the proposed extension (AG-00): the mock carries it so the CAD-layer toggle can be shown.
      return HttpResponse.json({ ...(view satisfies S['PageView']), ...(layers ? { layers } : {}) }, { headers: HEADERS });
    }),
    http.get(`${API}/files/:fileId/pages/:page/tiles/:level/:x/:y`, ({ params, request }) => {
      const hidden = (new URL(request.url).searchParams.get('hidden') ?? '').split(',').filter(Boolean).length;
      return new HttpResponse(
        tileSvg(String(params.fileId), Number(params.page), Number(params.level), Number(params.x), Number(params.y), hidden),
        { headers: { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'max-age=3600' } },
      );
    }),
    http.get(`${API}/admin/batch-runs`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 } satisfies S['BatchRunList'], { headers: HEADERS }),
    ),
  ];
}
