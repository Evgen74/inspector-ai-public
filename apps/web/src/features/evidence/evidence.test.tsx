/**
 * Evidence viewer: bbox → OpenSeadragon geometry, zoom-to-region, the ПД/РД panes of a card (room 314 on РД
 * p20 next to the anchor p18), overlays, revision clouds from the layout artifact and the CAD-layer toggle.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it } from 'vitest';
import fixture from '../../../../api/fixtures/d1/OBJ-TYUMENSKAYA-5-GOLD-SEED.protocol.json';
import groupsRaw from '../../../../api/fixtures/d1/OBJ-TYUMENSKAYA-5-GOLD-SEED.groups.jsonl?raw';
import { createQueryClient, Providers } from '../../App';
import type { BBoxNorm, FindingGroup, Protocol } from '../../contracts/protocol';
import { osd } from '../../../test/osd-fake';
import { currentLocation, renderApp, useMockApi } from '../../../test/render';
import { pageViewOf, RUN_IDS, TYUMEN } from '../../mocks/data';
import { EvidencePane } from './EvidencePane';
import { evidencePages } from './EvidenceViewer';
import { bboxToViewport, fitRect, roleColor, unionBox } from './geometry';
import { groupLayers, osdTileSource, revisionOnlyHidden, tileUrl } from './pageSource';

const protocol = fixture as unknown as Protocol;
const groups = groupsRaw
  .split('\n')
  .filter((l) => l.trim())
  .map((l) => JSON.parse(l) as FindingGroup);

describe('geometry (PDF_VISIBLE_ROTATED_TL_V1 → OSD viewport)', () => {
  it('maps a normalized bbox to width-normalized viewport units', () => {
    // F0202 p17 is A0 portrait: aspect 3370/2384
    const a = 3370 / 2384;
    const r = bboxToViewport([0.337, 0.687, 0.423, 0.73], a);
    expect(r.x).toBeCloseTo(0.337);
    expect(r.width).toBeCloseTo(0.086);
    expect(r.y).toBeCloseTo(0.687 * a);
    expect(r.height).toBeCloseTo(0.043 * a);
  });

  it('fits the region ⊕ 25 %, at least 8 % of the page, clamped inside the page', () => {
    const tiny: BBoxNorm = [0.5, 0.5, 0.51, 0.51];
    const r = fitRect([tiny], 1);
    expect(r.width).toBeCloseTo(0.08);
    expect(r.x + r.width / 2).toBeCloseTo(0.505);
    const corner = fitRect([[0.95, 0.0, 1.0, 0.05]], 0.5);
    expect(corner.x + corner.width).toBeLessThanOrEqual(1);
    expect(corner.y).toBeGreaterThanOrEqual(0);
    expect(fitRect([], 0.7)).toEqual({ x: 0, y: 0, width: 1, height: 0.7 });
    expect(unionBox([[0.1, 0.2, 0.3, 0.4], [0.2, 0.1, 0.5, 0.3]])).toEqual([0.1, 0.1, 0.5, 0.4]);
  });

  it('colours by role with the organizers legend: ПД blue, РД/ИД red', () => {
    expect(roleColor('EXPECTED', 'PD')).toBe('#1D4ED8');
    expect(roleColor('SUPPORTING_ACTUAL', 'RD')).toBe('#C62828');
    expect(roleColor(undefined, 'ID')).toBe('#C62828');
  });
});

describe('tile adapter (AG-00 render service)', () => {
  it('maps the PageView of the render service onto an OpenSeadragon tile source', () => {
    const view = pageViewOf('F0202', 17);
    expect(tileUrl(view, 12, 3, 4)).toBe('/api/v1/files/F0202/pages/17/tiles/12/3/4');
    expect(tileUrl(view, 12, 3, 4, [9, 2])).toBe('/api/v1/files/F0202/pages/17/tiles/12/3/4?hidden=2,9');
    const src = osdTileSource(view);
    expect(src).toMatchObject({ width: 4967, height: 7021, tileSize: 512, tileOverlap: 0, maxLevel: 13, minLevel: 7 });
    expect(src.getTileUrl(13, 0, 0)).toBe('/api/v1/files/F0202/pages/17/tiles/13/0/0');
  });

  it('groups CAD layers by prefix and hides everything but the revision layers on «Только изменения»', () => {
    const layers = [
      { number: 1, name: 'ОВ-Отопление', on: true },
      { number: 2, name: 'ОВ-Отопление-Изм. №3', on: true, is_revision: true },
      { number: 3, name: 'АР-Стены', on: true },
      { number: 4, name: 'Рамка', on: true, locked: true },
      { number: 5, name: 'Выкл', on: false },
    ];
    expect(groupLayers(layers).map((g) => [g.group, g.layers.length])).toEqual([
      ['АР', 1],
      ['Выкл', 1],
      ['ОВ', 2],
      ['Рамка', 1],
    ]);
    expect(revisionOnlyHidden(layers)).toEqual([1, 3]);
  });
});

describe('panes of a card', () => {
  it('puts ПД left and РД right; room 314 adds РД p20 next to the anchor p18', () => {
    const card = protocol.evidence_cards.find((c) => c.card_no === 'Б.4')!;
    const group = groups.find((g) => g.finding_group_id === card.finding_group_id)!;
    const pages = evidencePages(card, group);
    expect([...pages.keys()]).toEqual(['PD', 'RD']);
    expect(pages.get('PD')!.map((p) => [p.fileId, p.page, p.regions.length])).toEqual([['F0171', 88, 3]]);
    const rd = pages.get('RD')!;
    expect(rd.map((p) => [p.fileId, p.page, p.primary])).toEqual([
      ['F0201', 18, true],
      ['F0201', 20, false],
    ]);
    expect(rd[1]!.regions[0]!.dashed).toBe(true);
    expect(rd[1]!.regions[0]!.label).toContain('РД л.7');
  });
});

describe('EvidencePane', () => {
  useMockApi();
  beforeEach(() => {
    osd.viewers.length = 0;
  });

  function renderPane(fileId: string, page: number, boxes: BBoxNorm[]) {
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false } });
    return render(
      <Providers client={client}>
        <QueryClientProvider client={client}>
          <EvidencePane
            fileId={fileId}
            page={page}
            title="РД · факт"
            regions={boxes.map((box) => ({ box, color: '#C62828', label: 'РД л.4 · факт' }))}
          />
        </QueryClientProvider>
      </Providers>,
    );
  }

  it('opens zoomed to the regions and draws them with the revision cloud of the layout artifact', async () => {
    renderPane('F0202', 17, [[0.3355, 0.6534, 0.4425, 0.7089]]);
    await waitFor(() => expect(osd.viewers).toHaveLength(1));
    const viewer = osd.viewers[0]!;
    const aspect = 7021 / 4967;
    await waitFor(() => expect(viewer.viewport.fitBounds).toHaveBeenCalled());
    const fitted = viewer.viewport.fitBounds.mock.calls[0]![0];
    const expected = fitRect([[0.3355, 0.6534, 0.4425, 0.7089]], aspect);
    expect(fitted.x).toBeCloseTo(expected.x);
    expect(fitted.height).toBeCloseTo(expected.height);
    const overlay = screen.getByTestId('overlay');
    await waitFor(() => expect(overlay.querySelectorAll('g[data-kind="cloud"]')).toHaveLength(1));
    expect(overlay.querySelectorAll('g[data-kind="region"]')).toHaveLength(1);
    expect(overlay.querySelector('g[data-kind="cloud"] title')!.textContent).toBe('Изм. №3 · ОВ-Отопление-Изм. №3 · пом. 270, 272');
    // region rect in element pixels: viewport ×1000 (fake OSD)
    const rect = overlay.querySelector('g[data-kind="region"] rect')!;
    expect(Number(rect.getAttribute('x'))).toBeCloseTo(335.5, 0);
  });

  it('switches CAD layers: «Только слои изменений» reopens the tiles without the other layers', async () => {
    const user = userEvent.setup();
    renderPane('F0202', 17, [[0.3355, 0.6534, 0.4425, 0.7089]]);
    await waitFor(() => expect(osd.viewers).toHaveLength(1));
    await user.click(await screen.findByRole('button', { name: 'Слои САПР' }));
    await user.click(await screen.findByRole('button', { name: /Только слои изменений \(2\)/ }));
    await waitFor(() => expect(osd.viewers).toHaveLength(2));
    const url = osd.viewers[1]!.options.tileSources.getTileUrl(13, 0, 0);
    expect(url).toBe('/api/v1/files/F0202/pages/17/tiles/13/0/0?hidden=1,2,3,4,5,6,7,8,10,12');
    expect(osd.viewers[0]!.destroyed).toBe(true);
    expect(screen.getByRole('button', { name: 'Слои САПР' }).textContent).toContain('скрыто 10');
  });

  it('cycles regions with ] and fits the page with 0', async () => {
    const user = userEvent.setup();
    renderPane('F0171', 88, [
      [0.3177, 0.575, 0.3856, 0.6808],
      [0.6932, 0.5685, 0.7542, 0.6857],
    ]);
    await waitFor(() => expect(osd.viewers).toHaveLength(1));
    const viewer = osd.viewers[0]!;
    await waitFor(() => expect(viewer.viewport.fitBounds).toHaveBeenCalledTimes(1));
    expect(screen.getByText('1/2')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Следующий фрагмент' }));
    expect(screen.getByText('2/2')).toBeInTheDocument();
    const second = viewer.viewport.fitBounds.mock.calls.at(-1)![0];
    expect(second.x).toBeGreaterThan(0.6);
    const app = screen.getByRole('application');
    act(() => app.focus());
    await user.keyboard('0');
    const page = viewer.viewport.fitBounds.mock.calls.at(-1)![0];
    expect(page).toMatchObject({ x: 0, y: 0, width: 1 });
    await user.keyboard('o');
    expect(within(screen.getByTestId('overlay')).queryAllByText('РД л.4 · факт')).toHaveLength(0);
  });

  it('draws only a compact marker on each box and shows the full label on focus', async () => {
    renderPane('F0171', 88, [
      [0.3177, 0.575, 0.3856, 0.6808],
      [0.6932, 0.5685, 0.7542, 0.6857],
    ]);
    const overlay = await screen.findByTestId('overlay');
    await waitFor(() => expect(overlay.querySelectorAll('g[data-kind="region"]')).toHaveLength(2));
    expect([...overlay.querySelectorAll('text')].some((t) => t.textContent === 'РД л.4 · факт')).toBe(false);
    const markers = overlay.querySelectorAll('g[data-marker]');
    expect(markers[0]!.textContent).toBe('1');
    expect(markers[1]!.textContent).toBe('2');
    act(() => (markers[1] as unknown as SVGElement).dispatchEvent(new FocusEvent('focusin', { bubbles: true })));
    await waitFor(() => expect(overlay.querySelector('[data-testid="overlay-tip"] text')?.textContent).toBe('РД л.4 · факт'));
  });

  it('lists the region coordinates when the page image is unavailable', async () => {
    renderPane('F9999', 1, [[0.1, 0.2, 0.3, 0.4]]);
    // the mock serves meta for any file; simulate a failed tile load
    await waitFor(() => expect(osd.viewers).toHaveLength(1));
    act(() => osd.viewers[0]!.raise('tile-load-failed'));
    expect(await screen.findByText('Изображение страницы недоступно')).toBeInTheDocument();
    expect(screen.getByText(/0,100; 0,200 — 0,300; 0,400/)).toBeInTheDocument();
  });
});

describe('EvidencePage (route)', () => {
  useMockApi();
  beforeEach(() => {
    osd.viewers.length = 0;
  });

  it('opens a card from the protocol row in ≤ 2 clicks and pages through the cards', async () => {
    const user = userEvent.setup();
    renderApp(`/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}`);
    await screen.findByTestId('protocol-sheet');
    const row = document.querySelector('#p2-s4 tr[data-card="Б.1"] td:nth-child(5)') as HTMLElement;
    await user.click(row);
    await waitFor(() => expect(currentLocation.pathname).toBe(`/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}/cards/Б.1`));
    expect(await screen.findByRole('heading', { name: /Карточка Б\.1\. Характеристики вентиляторов \(IOS4-079\), пом\. 012/ })).toBeInTheDocument();
    expect(screen.getByText('ПД · эталон')).toBeInTheDocument();
    expect(screen.getByText('РД · факт')).toBeInTheDocument();
    expect(screen.getByText('F0171, л. 26 / стр. 104')).toBeInTheDocument();
    expect(screen.getByText('F0201, л. 4 / стр. 17')).toBeInTheDocument();
    await waitFor(() => expect(osd.viewers.length).toBeGreaterThanOrEqual(2));
    await user.click(screen.getByRole('button', { name: /Б\.2/ }));
    await waitFor(() => expect(currentLocation.pathname).toMatch(/cards\/Б\.2$/));
    expect(await screen.findByText('F0202, л. 4 / стр. 17')).toBeInTheDocument();
  });

  it('shows РД p20 for room 314 as a second page of the РД pane', async () => {
    const user = userEvent.setup();
    renderApp(`/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}/cards/${encodeURIComponent('Б.4')}`);
    const option = await screen.findByText('стр. 20 · пом. 314');
    await user.click(option);
    expect(await screen.findByText('F0201, л. 7 / стр. 20')).toBeInTheDocument();
  });
});
