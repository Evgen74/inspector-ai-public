/** «Протокол» page: toolbar, version history, downloads through the API, notes, the object card tabs. */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { currentLocation, renderApp, useMockApi } from '../../../test/render';
import { RUN_IDS, TYUMEN } from '../../mocks/data';

useMockApi();

describe('Протокол', () => {
  it('renders the protocol with its status, versions and downloads', async () => {
    renderApp(`/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}`);
    expect(await screen.findByRole('heading', { name: 'Протокол № 2026-09-28-TYUMEN5-1' })).toBeInTheDocument();
    expect(screen.getAllByText('На верификации · v2')[0]).toHaveAttribute('data-code', 'IN_VERIFICATION');
    expect(screen.getByText('предварительная')).toBeInTheDocument();
    expect(screen.getByText('Примечание к протоколу')).toBeInTheDocument();
    const docx = screen.getByRole('link', { name: /DOCX/ });
    expect(docx).toHaveAttribute('href', `/api/v1/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}/export?format=docx`);
    expect(screen.getByRole('link', { name: /PDF/ })).toHaveAttribute('href', expect.stringContaining('format=pdf'));
    const toc = screen.getByRole('navigation', { name: 'Разделы протокола' });
    expect(within(toc).getByText('4. Критические — 3')).toHaveAttribute('href', '#p2-s4');
    expect(within(toc).getByText('Приложение Б — 4')).toBeInTheDocument();
  });

  it('disables downloads the export did not produce and switches versions', async () => {
    const user = userEvent.setup();
    renderApp(`/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV1}`);
    expect((await screen.findAllByText('На верификации · v1'))[0]).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /DOCX/ })).toBeDisabled();
    await user.click(screen.getByRole('combobox', { name: 'Версия протокола' }));
    await user.click(await screen.findByText(/^На верификации · v2 · .* · текущая$/));
    await waitFor(() => expect(currentLocation.pathname).toBe(`/objects/${TYUMEN}/protocols/${RUN_IDS.tyumenV2}`));
    expect((await screen.findAllByText('На верификации · v2'))[0]).toBeInTheDocument();
  });

  it('refuses protocols of the hidden split and unknown runs with Russian results', async () => {
    renderApp(`/objects/OBJ-SYNTH-HIDDEN/protocols/${RUN_IDS.red}`);
    expect(await screen.findByText('Доступ к протоколу закрыт')).toBeInTheDocument();
  });

  it('shows 404 for a run without a protocol of the object', async () => {
    renderApp(`/objects/${TYUMEN}/protocols/${RUN_IDS.red}`);
    expect(await screen.findByText('Протокол не найден')).toBeInTheDocument();
  });
});

describe('Объект — вкладки', () => {
  it('overview shows the indicator reasons and the latest protocol', async () => {
    renderApp(`/objects/${TYUMEN}`);
    expect(await screen.findByText('Ожидают решения инспектора: 3 кандидата (критических: 3)')).toBeInTheDocument();
    expect(screen.getByText('Нет обязательных документов: 1 параметр')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '№ 2026-09-28-TYUMEN5-1' })).toBeInTheDocument();
  });

  it('protocols tab lists the version history, newest first', async () => {
    renderApp(`/objects/${TYUMEN}?tab=protocols`);
    const table = await screen.findByText('2026-09-28-TYUMEN5-1', { selector: 'a' });
    const rows = [...table.closest('tbody')!.querySelectorAll<HTMLElement>('tr.ant-table-row')];
    expect(rows.map((r) => r.querySelector('td')!.textContent)).toEqual(['v2текущая', 'v1']);
    expect(within(rows[0]!).getByText('d1-fixture-tyumen')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('3 · 0 · 1 · 4')).toBeInTheDocument();
  });

  it('runs tab lists the inventory import and the protocol runs', async () => {
    renderApp(`/objects/${TYUMEN}?tab=runs`);
    expect(await screen.findByText('Протокол v2')).toBeInTheDocument();
    expect(screen.getByText('Инвентаризация (последний импорт)')).toBeInTheDocument();
  });

  it('hidden split: protocols are closed', async () => {
    renderApp('/objects/OBJ-SYNTH-HIDDEN?tab=protocols');
    expect(await screen.findByText('Протоколы скрытой выборки не показываются')).toBeInTheDocument();
  });
});
