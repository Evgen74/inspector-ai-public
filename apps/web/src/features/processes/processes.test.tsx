import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { mockApi, renderAt } from '../../../test/render';
import { validateClientFiles, type ProcessDetail, type ProcessSummary } from './api';

const summary = (over: Partial<ProcessSummary>): ProcessSummary => ({
  process_id: '01a0ebb5-b715-7ef5-a425-28907de7f69f',
  status: 'READY',
  stage: null,
  object_id: 'OBJ-UPLOAD-7de7f69f',
  object_name: 'Жилой дом, ул. Тестовая 7',
  address: null,
  created_at: '2026-09-29T05:49:52.000Z',
  updated_at: '2026-09-29T05:50:45.000Z',
  started_at: '2026-09-29T05:49:52.000Z',
  finished_at: '2026-09-29T05:50:45.000Z',
  queue: 'rabbitmq',
  progress: { steps_done: 8, steps_total: 8, percent: 100 },
  error: null,
  files_total: 4,
  files_rejected: 1,
  pages_total: 25,
  verification_process_id: 'ver-1',
  protocol: { object_id: 'OBJ-UPLOAD-7de7f69f', run_id: 'run-1' },
  ...over,
});

const detail: ProcessDetail = {
  ...summary({ status: 'FAILED', error: 'Обработка комплекта завершилась с ошибкой (код 1).', protocol: null, verification_process_id: null, progress: { steps_done: 3, steps_total: 8, percent: 38 } }),
  steps: [
    { step: 'prepare', status: 'DONE', started_at: '2026-09-29T05:49:52.000Z', finished_at: '2026-09-29T05:49:54.000Z' },
    { step: 'recognize', status: 'FAILED', started_at: '2026-09-29T05:49:54.000Z', finished_at: '2026-09-29T05:50:00.000Z' },
  ],
  files: [
    { file_id: 'U7de7f69f-0001', name: 'ПД_том1.pdf', size_bytes: 1286506, sha256: 'a', status: 'PROCESSING', stage: 'PD', stage_source: 'PATH', pages: 8, problems: [], from_archive: null },
    { file_id: null, name: 'notes.txt', size_bytes: 0, sha256: '', status: 'REJECTED', stage: null, stage_source: null, pages: null, problems: ['Формат файла «notes.txt» не поддерживается.'], from_archive: null },
  ],
  log: [{ ts: '2026-09-29T05:50:00.000Z', level: 'error', message: 'Этап «recognize» завершён с ошибкой (код 1).' }],
};

describe('validateClientFiles (500 МБ per document, 5 ГБ per package)', () => {
  it('reports per-file Russian errors and the package limit', () => {
    const mb = 1024 * 1024;
    const r = validateClientFiles([
      { name: 'ok.pdf', size: 3 * mb },
      { name: 'big.pdf', size: 501 * mb },
      { name: 'all.zip', size: 2900 * mb },
      { name: 'x.exe', size: 10 },
      { name: 'empty.docx', size: 0 },
    ]);
    expect(r.errors.has('ok.pdf')).toBe(false);
    expect(r.errors.get('big.pdf')).toContain('больше 500 МБ');
    expect(r.errors.has('all.zip')).toBe(false);
    expect(r.errors.get('x.exe')).toContain('не поддерживается');
    expect(r.errors.get('empty.docx')).toContain('пустой');
    const pkg = validateClientFiles(Array.from({ length: 11 }, (_, i) => ({ name: `p${i}.pdf`, size: 490 * mb })));
    expect(pkg.packageError).toContain('лимит 5 ГБ');
  });
});

describe('Проверки', () => {
  it('lists processes with status, progress and a protocol link when READY', async () => {
    mockApi({
      '/api/v1/processes': () => ({
        body: {
          total: 2,
          items: [
            summary({}),
            summary({ process_id: '01a0ebb5-b715-7ef5-a425-000000000002', status: 'PARSING', stage: 'recognize', object_name: 'Второй', object_id: 'OBJ-UPLOAD-00000002', progress: { steps_done: 2, steps_total: 8, percent: 25 }, protocol: null, verification_process_id: null, files_rejected: 0 }),
          ],
        },
      }),
    });
    renderAt('/processes');
    const ready = (await screen.findByText('Жилой дом, ул. Тестовая 7')).closest('tr')!;
    expect(within(ready).getByText('Готово')).toBeInTheDocument();
    expect(within(ready).getByRole('link', { name: 'Протокол' })).toHaveAttribute('href', '/objects/OBJ-UPLOAD-7de7f69f/protocols/run-1');
    expect(within(ready).getByText('4 / 25', { exact: false })).toBeInTheDocument();
    const busy = screen.getByText('Второй').closest('tr')!;
    expect(within(busy).getByText('Обработка')).toBeInTheDocument();
    expect(within(busy).getByText('Распознавание документов')).toBeInTheDocument();
    expect(within(busy).queryByRole('link', { name: 'Протокол' })).toBeNull();
  });

  it('archives a process through «Архивировать» and can show archived ones', async () => {
    let archived = false;
    const { calls } = mockApi({
      '/api/v1/processes': (url) => ({
        body: {
          total: 1,
          items: archived && url.searchParams.get('include_archived') !== 'true' ? [] : [summary({ archived_at: archived ? '2026-09-29T07:00:00.000Z' : null })],
        },
      }),
      [`POST /api/v1/processes/${summary({}).process_id}/archive`]: () => {
        archived = true;
        return { body: { kind: 'PROCESS', id: summary({}).process_id, archived: true, archived_at: '2026-09-29T07:00:00.000Z' } };
      },
    });
    const user = userEvent.setup();
    renderAt('/processes');
    const row = (await screen.findByText('Жилой дом, ул. Тестовая 7')).closest('tr')!;
    await user.click(within(row).getByRole('button', { name: 'Архивировать' }));
    const confirm = (await screen.findAllByRole('button', { name: 'Архивировать' })).at(-1)!;
    await user.click(confirm);
    await waitFor(() => expect(screen.queryByText('Жилой дом, ул. Тестовая 7')).toBeNull());
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe(`/api/v1/processes/${summary({}).process_id}/archive`);
    expect(JSON.parse(post.body!)).toEqual({ archived: true });
    await user.click(screen.getByRole('switch', { name: 'Показать архивные' }));
    const back = (await screen.findByText('Жилой дом, ул. Тестовая 7')).closest('tr')!;
    expect(within(back).getByText('В архиве')).toBeInTheDocument();
    expect(within(back).getByRole('button', { name: 'Вернуть из архива' })).toBeInTheDocument();
    expect(calls.some((c) => c.url === '/api/v1/processes?include_archived=true')).toBe(true);
  }, 20_000);

  it('shows the empty state', async () => {
    mockApi({ '/api/v1/processes': () => ({ body: { items: [], total: 0 } }) });
    renderAt('/processes');
    expect(await screen.findByText(/Проверок пока нет/)).toBeInTheDocument();
  });

  it('shows recognition progress text under the bar while recognizing', async () => {
    const busy: ProcessDetail = {
      ...detail,
      status: 'PARSING',
      error: null,
      stage: 'recognize',
      progress: { steps_done: 2, steps_total: 8, percent: 45, stage: { step: 'recognize', done: 1287, total: 3169, pages_per_min: 80.4 } },
    };
    mockApi({ [`/api/v1/processes/${busy.process_id}`]: () => ({ body: busy }) });
    renderAt(`/processes/${busy.process_id}`);
    const el = await screen.findByTestId('recognition-progress');
    expect(el.textContent).toMatch(/^Распознавание: 1\s287 из 3\s169 страниц · 80 стр\/мин · осталось ≈ 24 мин$/);
  });

  it('pauses a running check and offers «Продолжить» once it is paused', async () => {
    const busy: ProcessDetail = { ...detail, status: 'PARSING', error: null, stage: 'recognize' };
    const paused: ProcessDetail = { ...busy, status: 'PAUSED', stage: null };
    let current = busy;
    const { calls } = mockApi({
      [`/api/v1/processes/${busy.process_id}`]: () => ({ body: current }),
      [`POST /api/v1/processes/${busy.process_id}/pause`]: () => {
        current = paused;
        return { body: paused };
      },
    });
    const user = userEvent.setup();
    renderAt(`/processes/${busy.process_id}`);
    await user.click(await screen.findByRole('button', { name: /Пауза/ }));
    expect(await screen.findByRole('button', { name: /Продолжить/ })).toBeInTheDocument();
    expect(screen.getByText('На паузе')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Отменить/ })).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST' && c.url === `/api/v1/processes/${busy.process_id}/pause`)).toBe(true);
  });

  it('shows the process page: failure reason, stages and per-file state', async () => {
    mockApi({ [`/api/v1/processes/${detail.process_id}`]: () => ({ body: detail }) });
    renderAt(`/processes/${detail.process_id}`);
    expect(await screen.findByText('Обработка не завершена')).toBeInTheDocument();
    expect(screen.getByText('Обработка комплекта завершилась с ошибкой (код 1).')).toBeInTheDocument();
    expect(screen.getByText(/Распознавание документов/)).toBeInTheDocument();
    const row = screen.getByText('ПД_том1.pdf').closest('tr')!;
    expect(within(row).getByText('ПД')).toBeInTheDocument();
    expect(within(row).getByText('Обрабатывается')).toBeInTheDocument();
    const rej = screen.getByText('notes.txt').closest('tr')!;
    expect(within(rej).getByText('Отклонён')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Открыть протокол' })).toBeNull();
  });
});

const LIMITS = { max_file_bytes: 52428800, max_package_bytes: 209715200, max_files: 500, extensions: ['.pdf', '.docx', '.xml', '.zip', '.7z', '.rar'] };
const uploadRoutes = () => ({
  '/api/v1/processes': () => ({ body: { items: [], total: 0 } }),
  '/api/v1/documents/upload/limits': () => ({ body: LIMITS }),
  'POST /api/v1/documents/upload': () => ({
    status: 202,
    body: { process_id: '01a0ebb5-b715-7ef5-a425-28907de7f69f', status: 'PENDING', object_id: 'OBJ-UPLOAD-7de7f69f', queue: 'rabbitmq', accepted: [{ name: 'a.pdf', size_bytes: 8, sha256: 'x' }], rejected: [] },
  }),
});

describe('Мастер загрузки', () => {
  it('shows the limits up front and blocks unsupported files with a Russian reason', async () => {
    mockApi(uploadRoutes());
    const user = userEvent.setup();
    renderAt('/processes');
    await user.click(await screen.findByRole('button', { name: /Загрузить комплект/ }));
    expect(await screen.findByText(/на файл и .* на весь пакет/)).toBeInTheDocument();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [new File(['x'], 'notes.txt', { type: 'text/plain' })]);
    expect(await screen.findByText(/Формат .txt не поддерживается/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled();
  }, 20_000);

  it('posts multipart to /documents/upload and shows the result', async () => {
    const { calls } = mockApi(uploadRoutes());
    const user = userEvent.setup();
    renderAt('/processes');
    await user.click(await screen.findByRole('button', { name: /Загрузить комплект/ }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [new File(['%PDF-1.4'], 'a.pdf', { type: 'application/pdf' })]);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Далее' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    await user.type(screen.getByRole('textbox', { name: /Наименование объекта/ }), 'Дом 7');
    await user.click(screen.getByRole('button', { name: 'Загрузить и проверить' }));
    expect(await screen.findByText('Комплект принят, проверка поставлена в очередь')).toBeInTheDocument();
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.url).toBe('/api/v1/documents/upload');
    const form = post?.body as unknown as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get('object_name')).toBe('Дом 7');
    expect((form.getAll('files')[0] as File).name).toBe('a.pdf');
  }, 20_000);

  it('takes a whole folder: keeps the paths (stage from ПД/РД folders) and leaves out non-documents', async () => {
    const { calls } = mockApi(uploadRoutes());
    const user = userEvent.setup();
    renderAt('/processes');
    await user.click(await screen.findByRole('button', { name: /Загрузить комплект/ }));
    const inFolder = (body: string, rel: string) => {
      const f = new File([body], rel.split('/').pop()!, { type: 'application/pdf' });
      Object.defineProperty(f, 'webkitRelativePath', { value: rel });
      return f;
    };
    const folderInput = [...document.querySelectorAll('input[type="file"]')].at(-1) as HTMLInputElement;
    expect(folderInput).toHaveAttribute('webkitdirectory');
    await user.upload(folderInput, [
      inFolder('%PDF-1.4', 'Полярная/ПД/АР.pdf'),
      inFolder('%PDF-1.4', 'Полярная/РД/АР.pdf'),
      inFolder('x', 'Полярная/РД/план.dwg'),
      inFolder('x', 'Полярная/.DS_Store'),
    ]);
    expect(await screen.findByText('Полярная/ПД/АР.pdf')).toBeInTheDocument();
    expect(screen.getByText('Полярная/РД/АР.pdf')).toBeInTheDocument();
    expect(screen.getByText(/Из папки не взято 2 файла/)).toBeInTheDocument();
    expect(screen.getByText(/\.dwg — 1/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Далее' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    await user.click(screen.getByRole('button', { name: 'Загрузить и проверить' }));
    expect(await screen.findByText('Комплект принят, проверка поставлена в очередь')).toBeInTheDocument();
    const form = calls.find((c) => c.method === 'POST')?.body as unknown as FormData;
    expect(form.getAll('files').map((f) => (f as File).name)).toEqual(['Полярная/ПД/АР.pdf', 'Полярная/РД/АР.pdf']);
  }, 20_000);
});
