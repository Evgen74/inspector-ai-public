import { render, screen, waitFor, within } from '@testing-library/react';
import { SectionPlaceholder } from './pages/SectionPlaceholder';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { enumCodes, enumLabel } from './contracts/enums';
import { fileItem, GAMMA, OBJECTS } from '../test/fixtures';
import { mockApi, renderAt } from '../test/render';

describe('app shell', () => {
  it('renders the Russian sidebar with the seven sections and the product name', async () => {
    mockApi({ '/api/v1/objects': () => ({ body: { items: [], total: 0, page: 1, page_size: 50 } }) });
    renderAt('/objects');
    const nav = screen.getByRole('navigation', { name: 'Основное меню' });
    for (const label of ['Дашборд', 'Объекты', 'Проверки', 'Протоколы', 'Верификация', 'Нормативная база', 'Мониторинг']) {
      expect(within(nav).getByRole('link', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText('Инспектор ИИ')).toBeInTheDocument();
    expect(await screen.findByText(/Объектов пока нет/)).toBeInTheDocument();
  });

  it('renders the placeholder component for sections of later milestones', () => {
    mockApi({});
    render(<SectionPlaceholder title="Проверки" milestone="M9" description="Описание" />);
    expect(screen.getByRole('heading', { name: 'Проверки' })).toBeInTheDocument();
    expect(screen.getByText('Раздел в разработке')).toBeInTheDocument();
  });

  it('shows 404 for an unknown route', () => {
    mockApi({});
    renderAt('/no-such-page');
    expect(screen.getByText('Страница не найдена')).toBeInTheDocument();
  });
});

describe('Объекты', () => {
  it('lists objects with file counts per stage and split labels from the contract', async () => {
    const { calls } = mockApi({ '/api/v1/objects': () => ({ body: OBJECTS }) });
    renderAt('/objects');
    const row = (await screen.findByText('Гамма')).closest('tr')!;
    expect(within(row).getByText('OBJ-SYNTH-GAMMA')).toBeInTheDocument();
    expect(within(row).getByText('47')).toBeInTheDocument(); // ПД
    expect(within(row).getByText('10')).toBeInTheDocument(); // РД/ИД
    expect(within(row).getByText('58')).toBeInTheDocument(); // total
    const beta = screen.getByText('OBJ-SYNTH-BETA').closest('tr')!;
    expect(within(beta).getByText(enumLabel('ManifestSplit', 'TEST_HIDDEN'))).toBeInTheDocument();
    expect(within(beta).getByText('нет на диске: 2')).toBeInTheDocument();
    expect(screen.getByText('Всего: 3')).toBeInTheDocument();
    expect(calls.map((c) => c.url)).toContain('/api/v1/objects?page=1&page_size=50');
  });

  it('shows the server problem with its request id when the API fails', async () => {
    mockApi({
      '/api/v1/objects': () => ({
        status: 503,
        body: {
          type: '/problems/db-unavailable',
          title: 'Сервис временно недоступен',
          status: 503,
          detail: 'Сервис временно недоступен. Повторите попытку через 5 с.',
          instance: '/api/v1/objects#abc',
          code: 'DB_UNAVAILABLE',
          request_id: 'req-problem-42',
          timestamp: '2026-09-27T00:00:00Z',
          retryable: true,
        },
      }),
    });
    renderAt('/objects');
    expect(await screen.findByText('Сервис временно недоступен')).toBeInTheDocument();
    expect(screen.getByText(/Код обращения: req-problem-42/)).toBeInTheDocument();
  });

  it('opens the object card with its files table on row click', async () => {
    const { calls } = mockApi({
      '/api/v1/objects': () => ({ body: OBJECTS }),
      '/api/v1/objects/OBJ-SYNTH-GAMMA': () => ({ body: GAMMA }),
      '/api/v1/objects/OBJ-SYNTH-GAMMA/files': () => ({
        body: {
          items: [
            fileItem('F9101', 'ОВ1 том 5.pdf', 'PD'),
            fileItem('F9102', 'АОСР №1.pdf', 'RD_ID_MIXED', { local_status: 'MISSING_ON_DISK' }),
          ],
          total: 2,
          page: 1,
          page_size: 50,
        },
      }),
    });
    const user = userEvent.setup();
    renderAt('/objects');
    await user.click(await screen.findByText('Гамма'));
    expect(await screen.findByRole('heading', { name: 'Гамма' })).toBeInTheDocument();
    await user.click(await screen.findByRole('tab', { name: /Документы/ }));
    expect(await screen.findByText('ОВ1 том 5.pdf')).toBeInTheDocument();
    const missingRow = screen.getByText('АОСР №1.pdf').closest('tr')!;
    expect(within(missingRow).getByText(enumLabel('LocalFileStatus', 'MISSING_ON_DISK'))).toBeInTheDocument();
    expect(within(missingRow).getByText('РД/ИД')).toBeInTheDocument();
    expect(screen.getAllByText('1,5 МБ')).toHaveLength(2);
    expect(calls.map((c) => c.url)).toContain('/api/v1/objects/OBJ-SYNTH-GAMMA/files?page=1&page_size=50');
  });

  it('filters files by stage through the API', async () => {
    const { calls } = mockApi({
      '/api/v1/objects/OBJ-SYNTH-GAMMA': () => ({ body: GAMMA }),
      '/api/v1/objects/OBJ-SYNTH-GAMMA/files': (url) => ({
        body: {
          items: url.searchParams.get('stage') === 'RD_ID_MIXED' ? [fileItem('F9102', 'АОСР №1.pdf', 'RD_ID_MIXED')] : [],
          total: 1,
          page: 1,
          page_size: 50,
        },
      }),
    });
    const user = userEvent.setup();
    renderAt('/objects/OBJ-SYNTH-GAMMA?tab=documents');
    await user.click(await screen.findByText('РД/ИД (10)'));
    await waitFor(() =>
      expect(calls.map((c) => c.url)).toContain('/api/v1/objects/OBJ-SYNTH-GAMMA/files?page=1&page_size=50&stage=RD_ID_MIXED'),
    );
    expect(await screen.findByText('АОСР №1.pdf')).toBeInTheDocument();
  });

  it('warns on the card of a hidden-split object', async () => {
    mockApi({
      '/api/v1/objects/OBJ-SYNTH-BETA': () => ({ body: { ...GAMMA, ...OBJECTS.items[1] } }),
      '/api/v1/objects/OBJ-SYNTH-BETA/files': () => ({ body: { items: [], total: 0, page: 1, page_size: 50 } }),
    });
    renderAt('/objects/OBJ-SYNTH-BETA');
    expect(await screen.findByText('Объект скрытой тестовой выборки')).toBeInTheDocument();
  });

  it('imports a run directory from the modal', async () => {
    const { calls } = mockApi({
      '/api/v1/objects': () => ({ body: OBJECTS }),
      'POST /api/v1/admin/batch-runs/import': () => ({
        status: 201,
        body: {
          run: { batch_run_id: 'run-x' },
          created: true,
          objects: [{ object_id: 'OBJ-SYNTH-ALPHA' }],
          files_imported: 145,
          warnings: [],
        },
      }),
    });
    const user = userEvent.setup();
    renderAt('/objects');
    await user.click(await screen.findByRole('button', { name: /Импорт запуска/ }));
    await user.type(await screen.findByLabelText('Каталог запуска'), 'run-x');
    await user.click(screen.getByRole('button', { name: 'Импортировать' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(JSON.parse(post.body!)).toEqual({ run_dir: 'run-x' });
    expect(await screen.findByText(/Импортирован запуск run-x: 1 объект, 145 файлов/)).toBeInTheDocument();
  });
});

describe('contract enums', () => {
  it('reads labels from packages/contracts/enums.yaml', () => {
    expect(enumCodes('ManifestStage')).toEqual(['PD', 'RD', 'ID', 'RD_ID_MIXED', 'UNKNOWN']);
    expect(enumLabel('ManifestStage', 'PD')).toBe('ПД');
    expect(enumLabel('ManifestSection', 'AR')).toBe('АР'); // labels added to the contract at M0 integration
    expect(enumLabel('ManifestSection', 'NEW_SECTION')).toBe('NEW_SECTION'); // unknown open-vocabulary value → raw code
    expect(enumLabel('DatasetRole', 'GOLD_SEED')).toBe('GOLD_SEED'); // open vocabulary without labels → raw code
    expect(enumLabel('ManifestStage', null)).toBe('—');
  });
});
