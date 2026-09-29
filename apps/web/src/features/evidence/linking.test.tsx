/** Location linking of the evidence panes: chips → pages/boxes per stage, lockstep stepping, per-room summary. */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it } from 'vitest';
import { createQueryClient, Providers } from '../../App';
import type { BBoxNorm, EvidenceCard, EvidenceRef, FindingGroup } from '../../contracts/protocol';
import { osd } from '../../../test/osd-fake';
import { useMockApi } from '../../../test/render';
import { EvidenceViewer } from './EvidenceViewer';
import { buildLocationLinks, comparedSummary, locationSegment, stepLocation } from './linking';

const box = (x: number): BBoxNorm => [x, 0.2, x + 0.1, 0.3];
const ref = (stage: string, file: string, page: number, b: BBoxNorm, note?: string): EvidenceRef => ({
  stage,
  file_id: file,
  pdf_page_number: page,
  geometry: { boxes: [b] },
  note: note ?? null,
});

const card = {
  card_no: 'Б.1',
  parameter_code: 'IOS4-078',
  parameter_label: 'Местные отсосы',
  locations: ['129', '140', '142'],
  rationale: 'В помещении 140 иная схема. В помещении 142 в РД только общеобменная вентиляция П2/ВЕ.',
  sources: [
    { role: 'EXPECTED', stage: 'PD', file_id: 'F0171', pdf_page_number: 88, geometry: { boxes: [box(0.1)] } },
    { role: 'ACTUAL', stage: 'RD', file_id: 'F0201', pdf_page_number: 18, geometry: { boxes: [box(0.5)] } },
  ],
} as unknown as EvidenceCard;

const group = {
  finding_group_id: 'G',
  locations: ['129', '140', '142'],
  location_type: 'ROOM',
  pd_value: 'местные отсосы В2.7–В2.9',
  rd_value: 'общеобменная П2/ВЕ',
  location_pages: {
    '129': [ref('PD', 'F0171', 88, box(0.1)), ref('RD', 'F0201', 18, box(0.5))],
    '140': [ref('PD', 'F0171', 88, box(0.3)), ref('RD', 'F0201', 18, box(0.7))],
    '142': [ref('PD', 'F0171', 89, box(0.4), 'местные отсосы В2.4–В2.6'), ref('RD', 'F0201', 20, box(0.2), 'только общеобменная П2/ВЕ')],
  },
} as unknown as FindingGroup;

describe('location links', () => {
  it('builds one chip per location with the page and boxes each stage shows for it', () => {
    const links = buildLocationLinks(card, group);
    expect(links.map((l) => l.label)).toEqual(['пом. 129', 'пом. 140', 'пом. 142']);
    expect(links[2]!.targets.PD).toMatchObject({ pageKey: 'F0171#89', boxes: [box(0.4)] });
    expect(links[2]!.targets.RD).toMatchObject({ pageKey: 'F0201#20', boxes: [box(0.2)] });
    // the PD and RD pages of one room can differ from the neighbouring room
    expect(links[1]!.targets.RD!.pageKey).toBe('F0201#18');
  });

  it('falls back to the anchor pages for a location without its own evidence', () => {
    const links = buildLocationLinks(card, { ...group, location_pages: {} } as FindingGroup);
    expect(links[0]!.targets.PD!.pageKey).toBe('F0171#88');
    expect(links[0]!.targets.RD!.pageKey).toBe('F0201#18');
  });

  it('labels non-room findings by the element noun and returns nothing without locations', () => {
    const el = buildLocationLinks(card, { ...group, location_type: 'ELEMENT', element_noun: 'Вентилятор', locations: ['В2.7'], location_pages: {} } as unknown as FindingGroup);
    expect(el.map((l) => l.label)).toEqual(['Вентилятор В2.7']);
    expect(buildLocationLinks({ ...card, locations: [] } as unknown as EvidenceCard, null)).toEqual([]);
  });

  it('steps through locations circularly', () => {
    expect(stepLocation(0, -1, 4)).toBe(3);
    expect(stepLocation(3, 1, 4)).toBe(0);
    expect(stepLocation(1, 1, 4)).toBe(2);
    expect(stepLocation(0, 1, 0)).toBe(0);
  });

  it('builds the per-room «что сравнивали» line from evidence notes, then rationale, then values', () => {
    const links = buildLocationLinks(card, group);
    expect(links[2]!.summary).toBe('пом. 142: ПД — местные отсосы В2.4–В2.6; РД — только общеобменная П2/ВЕ');
    expect(links[1]!.summary).toBe('пом. 140: В помещении 140 иная схема.');
    expect(links[0]!.summary).toBe('пом. 129: в ПД — местные отсосы В2.7–В2.9; в РД — общеобменная П2/ВЕ');
    expect(comparedSummary(card, group, null)).toContain('в ПД — местные отсосы');
  });
});

describe('per-room rationale from the batch («Сравнение по помещениям: пом. 140: …; пом. 142: …»)', () => {
  const rationale =
    'Сравнение по помещениям: пом. 140: ПД (F0171, с. 88, л. 10) — В2.7, В2.8, В2.9; РД (F0201, с. 18, л. 5) — нет; ' +
    'пом. 142: ПД (F0171, с. 88, л. 10) — В2.4, В2.5, В2.6; РД (F0201, с. 18, л. 5) — нет.';

  it('cuts the text of one room at the next room marker and keeps «с. 88»-style abbreviations whole', () => {
    expect(locationSegment(rationale, '140', ['140', '142'])).toBe(
      'ПД (F0171, с. 88, л. 10) — В2.7, В2.8, В2.9; РД (F0201, с. 18, л. 5) — нет',
    );
    expect(locationSegment(rationale, '142', ['140', '142'])).toBe(
      'ПД (F0171, с. 88, л. 10) — В2.4, В2.5, В2.6; РД (F0201, с. 18, л. 5) — нет',
    );
    expect(locationSegment('Иная схема.', '140', ['140'])).toBeNull();
  });

  it('handles a room name in brackets before the colon («пом. 147 (Лабораторная тип АВ): …»)', () => {
    const named =
      'Сравнение по помещениям: пом. 147 (Лабораторная тип АВ): ПД (F0171, с. 88, л. 10) — В2.10; РД (F0201, с. 18, л. 5) — В2.2; ' +
      'пом. 198 (Лабораторная тип АВ): ПД (F0171, с. 88, л. 10) — В2.2; РД (F0201, с. 18, л. 5) — В2.8.';
    expect(locationSegment(named, '147', ['147', '198'])).toBe('ПД (F0171, с. 88, л. 10) — В2.10; РД (F0201, с. 18, л. 5) — В2.2');
    expect(locationSegment(named, '198', ['147', '198'])).toBe('ПД (F0171, с. 88, л. 10) — В2.2; РД (F0201, с. 18, л. 5) — В2.8');
  });

  it('shows the per-room line without a doubled «пом. 140: 140:» or a cut at «с.»', () => {
    const c = { ...card, locations: ['140', '142'], rationale } as unknown as EvidenceCard;
    const g = { ...group, locations: ['140', '142'], location_pages: {}, rationale } as unknown as FindingGroup;
    const links = buildLocationLinks(c, g);
    expect(links[0]!.summary).toBe('пом. 140: ПД (F0171, с. 88, л. 10) — В2.7, В2.8, В2.9; РД (F0201, с. 18, л. 5) — нет');
    expect(links[1]!.summary.startsWith('пом. 142: ПД (F0171')).toBe(true);
  });
});

describe('EvidenceViewer linked panes', () => {
  useMockApi();
  beforeEach(() => {
    osd.viewers.length = 0;
  });

  function renderViewer() {
    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false } });
    return render(
      <Providers client={client}>
        <QueryClientProvider client={client}>
          <EvidenceViewer card={card} group={group} />
        </QueryClientProvider>
      </Providers>,
    );
  }

  it('a chip switches both panes to the room pages, highlights its boxes and updates the summary', async () => {
    const user = userEvent.setup();
    renderViewer();
    await waitFor(() => expect(osd.viewers.length).toBeGreaterThanOrEqual(2));
    expect(screen.getByText('F0171, л. — / стр. 88')).toBeInTheDocument();
    await user.click(screen.getByText('пом. 142'));
    expect(await screen.findByText('F0171, л. — / стр. 89')).toBeInTheDocument();
    expect(screen.getByText('F0201, л. — / стр. 20')).toBeInTheDocument();
    expect(screen.getByTestId('compare-summary')).toHaveTextContent('пом. 142: ПД — местные отсосы В2.4–В2.6; РД — только общеобменная П2/ВЕ');
    await waitFor(() => expect(document.querySelectorAll('g[data-active="true"][data-kind="region"]').length).toBeGreaterThanOrEqual(2));
  });

  it('does not advertise revision clouds on pages that have none', async () => {
    renderViewer();
    await waitFor(() => expect(osd.viewers.length).toBeGreaterThanOrEqual(2));
    await screen.findAllByText(/Помещения \(/);
    expect(screen.queryByRole('switch', { name: 'Облака изменений' })).not.toBeInTheDocument();
    expect(screen.queryByText(/облако\s+изменения/i)).not.toBeInTheDocument();
  });

  it('‹ › step both panes in lockstep; unlinking makes the panes independent', async () => {
    const user = userEvent.setup();
    renderViewer();
    await waitFor(() => expect(osd.viewers.length).toBeGreaterThanOrEqual(2));
    const next = screen.getAllByRole('button', { name: 'Следующий фрагмент' });
    await user.click(next[0]!);
    await user.click(next[0]!);
    expect(await screen.findByText('F0171, л. — / стр. 89')).toBeInTheDocument();
    expect(screen.getByText('F0201, л. — / стр. 20')).toBeInTheDocument();
    await user.click(screen.getByRole('switch', { name: 'Связать панели' }));
    expect(screen.getByRole('radio', { name: 'По координатам' })).toBeInTheDocument();
  });
});
