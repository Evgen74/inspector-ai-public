/**
 * Evidence card of a value-conflict suspicion (rule HR-LOG-101) on an uploaded object: whole-object place, values per
 * stage, catalog criticality flagged as a suspicion, tabs that name file and value, document name in the header.
 */
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { EvidenceCard, Protocol } from '../../contracts/protocol';
import { CardSummary } from './EvidencePage';
import { evidencePages, tabLabels } from './EvidenceViewer';
import { locationsText, shortFileName, titlePlace } from './cardText';

const src = (file_id: string, file_name: string, page: number, value_text: string): EvidenceCard['sources'][number] => ({
  stage: 'PD',
  file_id,
  file_name,
  pdf_page_number: page,
  sheet_number: page - 2,
  value_text,
});

const card: EvidenceCard = {
  card_no: 'Б.1',
  finding_group_id: null,
  finding_ids: [],
  parameter_code: 'AR-045',
  parameter_label: 'Уклоны кровли и водосток (AR-045): противоречие значений',
  rule_version: '1',
  locations: ['OBJECT'],
  expected_value: null,
  actual_value: null,
  rationale: 'В ПД противоречивые значения',
  risk_level: 'MEDIUM',
  criticality: 'Критическое (приостановка работ)',
  sources: [
    src('Uf9c3a08a-0026', '3. Раздел 3 ЖС-РД-270121-П-АР 2024.pdf', 8, '1,7 %'),
    src('Uf9c3a08a-0027', '3. Раздел 3 ЖС-РД-270121-П-АР.pdf', 8, '1,7 %'),
    src('Uf9c3a08a-0077', '9. Раздел 9 ЖС-РД-270121-П-ПБ.pdf', 16, '1,7 %'),
    src('Uf9c3a08a-0030', '4. П-2025-04-266-КР.Р.pdf', 17, '1 %'),
  ],
  inspector: { status: 'PENDING' },
  stage_values: { PD: '1,7 % (3 файла); 1 % (1 файл)', RD: null, ID: null },
  ai_comment: 'ПД: 1,7 % (3 ф.); 1 % (1 ф.); РД: —; ИД: —',
};

const protocol = {
  appendix2: {
    section4_critical: { rows: [] },
    section5_substantial: { rows: [] },
    section6_ai_suspicions: { rows: [{ card_ref: 'Б.1', method_ru: 'Логический анализ', inspector_decision_ru: 'Ожидает решения' }] },
  },
} as unknown as Protocol;

describe('place of a card', () => {
  it('says «объект в целом» instead of the OBJECT code, and keeps rooms as before', () => {
    expect(locationsText(['OBJECT'])).toBe('объект в целом');
    expect(titlePlace(['OBJECT'])).toBe('');
    expect(locationsText(['140', '142'])).toBe('пом. 140, 142');
    expect(titlePlace(['140', '142'])).toBe(', пом. 140, 142');
  });
});

describe('tabs of a value-conflict card', () => {
  it('names the file and the supported value on each tab and marks no page as the anchor', () => {
    const pages = evidencePages(card).get('PD')!;
    expect(tabLabels(pages).map((t) => t.label)).toEqual([
      'АР 2024 · стр. 8 · 1,7 %',
      'АР · стр. 8 · 1,7 %',
      'ПБ · стр. 16 · 1,7 %',
      'КР.Р · стр. 17 · 1 %',
    ]);
    expect(pages.every((p) => !p.anchor)).toBe(true);
    expect(pages.map((p) => p.fileName)).toContain('3. Раздел 3 ЖС-РД-270121-П-АР 2024.pdf');
  });

  it('keeps «опорная» for role-anchored pages of an ordinary card and needs no file name for one file', () => {
    const plain: EvidenceCard = {
      ...card,
      card_no: 'Б.2',
      stage_values: null,
      sources: [
        { stage: 'PD', file_id: 'F0171', pdf_page_number: 88, role: 'EXPECTED' },
        { stage: 'PD', file_id: 'F0171', pdf_page_number: 90, role: 'SUPPORTING_EXPECTED' },
      ],
    };
    const labels = tabLabels(evidencePages(plain).get('PD')!).map((t) => t.label);
    expect(labels).toEqual(['стр. 88 · опорная', 'стр. 90']);
  });

  it('takes the name of a page without its own file name from the registry', () => {
    const bare: EvidenceCard = { ...card, sources: [{ stage: 'PD', file_id: 'F1', pdf_page_number: 2 }] };
    expect(evidencePages(bare, null, { F1: 'Пояснительная записка.pdf' }).get('PD')![0]!.fileName).toBe('Пояснительная записка.pdf');
  });

  it('shortens document names', () => {
    expect(shortFileName('3. Раздел 3 ЖС-РД-270121-П-АР 2024.pdf')).toBe('АР 2024');
    expect(shortFileName('Пояснительная записка.pdf')).toBe('Пояснительная записка');
    expect(shortFileName(null)).toBeNull();
  });
});

describe('side panel of a value-conflict card', () => {
  it('shows values per stage, the catalog criticality as a suspicion, no English finding_id and no room', () => {
    render(
      <MemoryRouter>
        <CardSummary card={card} protocol={protocol} />
      </MemoryRouter>,
    );
    expect(screen.getByText('Место')).toBeInTheDocument();
    expect(screen.getByText('объект в целом')).toBeInTheDocument();
    expect(screen.queryByText(/OBJECT/)).toBeNull();
    expect(screen.getByTestId('stage-pd')).toHaveTextContent('1,7 % (3 файла); 1 % (1 файл)');
    expect(screen.getByTestId('stage-rd')).toHaveTextContent('—');
    const crit = screen.getByText('Критичность').closest('tr')!;
    expect(within(crit).getByText(/Критическое \(приостановка работ\)/)).toBeInTheDocument();
    expect(within(crit).getByText(/подозрение ИИ, а не нарушение/)).toBeInTheDocument();
    expect(screen.queryByText('finding_id')).toBeNull();
    expect(screen.queryByText('ID находки')).toBeNull();
  });
});
