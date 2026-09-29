/**
 * Page images for the evidence viewer come from AG-00's render service (PyMuPDF renders of the visible page
 * area, contract PDF_VISIBLE_ROTATED_TL_V1 — the same space as the evidence boxes):
 *   GET /api/v1/files/{file_id}/pages/{page_no}                       → PageView (operation getPageView)
 *   GET /api/v1/files/{file_id}/pages/{page_no}/tiles/{level}/{x}/{y} → PNG tile (getPageTile)
 * PageView maps one-to-one onto an OpenSeadragon tile source. This adapter is the only place that knows it.
 *
 * CAD layers: the viewer shows a layer toggle when the PageView carries `layers` (PyMuPDF layer UI configs) and
 * then appends `?hidden=n1,n2` to the tile URLs. AG-00's render service does not offer that yet (open issue),
 * so the toggle stays hidden against the real API and is exercised by the mocks and tests.
 */
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import type { components } from '../../api/schema.gen';

export interface PageLayer {
  number: number;
  name: string;
  on: boolean;
  locked?: boolean;
  is_revision?: boolean;
}

export type PageView = components['schemas']['PageView'] & {
  /** Proposed extension (AG-00): CAD layers of the page, see the header. */
  layers?: PageLayer[];
};

const enc = encodeURIComponent;

export function pageViewPath(fileId: string, page: number): string {
  return `/files/${enc(fileId)}/pages/${page}`;
}

export function tileUrl(view: Pick<PageView, 'tile_url_template'>, level: number, x: number, y: number, hidden: number[] = []): string {
  const url = view.tile_url_template
    .replace('{level}', String(level))
    .replace('{x}', String(x))
    .replace('{y}', String(y));
  return hidden.length ? `${url}?hidden=${[...hidden].sort((a, b) => a - b).join(',')}` : url;
}

/** OpenSeadragon custom tile source: level `max_level` is the full resolution `max_dpi`. */
export function osdTileSource(view: PageView, hidden: number[] = []) {
  return {
    width: view.width_px,
    height: view.height_px,
    tileSize: view.tile_size,
    tileOverlap: view.tile_overlap,
    minLevel: view.min_level,
    maxLevel: view.max_level,
    getTileUrl: (level: number, x: number, y: number) => tileUrl(view, level, x, y, hidden),
  };
}

export function usePageView(fileId: string, page: number) {
  return useQuery({
    queryKey: ['pageView', fileId, page],
    queryFn: () => apiFetch<PageView>(pageViewPath(fileId, page)),
    staleTime: 10 * 60_000,
    retry: false,
  });
}

/** Layers grouped by the prefix before the first «-» / «_» (CAD naming: «ОВ-Отопление-Изм. №3»). */
export function groupLayers(layers: PageLayer[]): Array<{ group: string; layers: PageLayer[] }> {
  const groups = new Map<string, PageLayer[]>();
  for (const l of layers) {
    const g = l.name.split(/[-_|]/)[0]?.trim() || 'Прочие';
    groups.set(g, [...(groups.get(g) ?? []), l]);
  }
  return [...groups.entries()]
    .map(([group, ls]) => ({ group, layers: ls.sort((a, b) => a.name.localeCompare(b.name, 'ru')) }))
    .sort((a, b) => a.group.localeCompare(b.group, 'ru'));
}

/** «Только изменения»: hide every visible, unlocked layer that does not mark a revision. */
export function revisionOnlyHidden(layers: PageLayer[]): number[] {
  return layers.filter((l) => l.on && !l.locked && !l.is_revision).map((l) => l.number);
}
