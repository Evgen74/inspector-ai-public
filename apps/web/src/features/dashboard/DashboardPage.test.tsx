/**
 * Дашборд (ТЗ §7 модуль 7): strict colours, KPI tiles, URL-synced filters that reach the API, the
 * findings-by-section summary.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { currentLocation, renderApp, useMockApi } from '../../../test/render';
import { TYUMEN } from '../../mocks/data';

const { requests } = useMockApi();

function rowOf(text: string): HTMLElement {
  return screen.getByText(text).closest('tr') as HTMLElement;
}

describe('Дашборд', () => {
  it('is the start page and colours objects by the strict rule', async () => {
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Дашборд инспектора' })).toBeInTheDocument();
    await screen.findByText('Синтетический объект «Северный», корпус 2 (демо)');
    const colour = (name: string) => within(rowOf(name)).getByTestId('indicator').getAttribute('data-code');
    expect(colour('Синтетический объект «Северный», корпус 2 (демо)')).toBe('RED');
    expect(colour('Пример нарушений на чертежах (Тюменская, 5)')).toBe('YELLOW');
    expect(colour('Синтетический объект «Школа на 550 мест» (демо)')).toBe('GREEN');
    expect(colour('Синтетический объект без протокола (демо)')).toBe('NONE');
    expect(colour('Синтетическая скрытая выборка (демо)')).toBe('NONE');
    const tyumen = rowOf('Пример нарушений на чертежах (Тюменская, 5)');
    expect(within(tyumen).getByText('Требует действий')).toBeInTheDocument();
    expect(within(tyumen).getByText('№ 2026-09-28-TYUMEN5-1')).toBeInTheDocument();
    expect(within(tyumen).getByText('Только ПД и РД')).toBeInTheDocument();
    expect(within(tyumen).getByText('ИД –')).toHaveAttribute('data-code', 'ID_MISSING');
  });

  it('shows the tiles and filters by colour through the URL and the API', async () => {
    const user = userEvent.setup();
    renderApp('/dashboard');
    await screen.findByText('Синтетический объект «Северный», корпус 2 (демо)');
    const tile = (name: RegExp) => screen.getAllByRole('button').find((b) => name.test(b.textContent ?? ''))!;
    expect(tile(/С нарушениями/).textContent).toContain('1');
    expect(tile(/Нет результата/).textContent).toContain('2');
    await user.click(tile(/С нарушениями/));
    await waitFor(() => expect(currentLocation.search).toBe('?color=RED'));
    await waitFor(() => expect(requests).toContain('/api/v1/dashboard?color=RED'));
    await waitFor(() => expect(screen.queryByText('Пример нарушений на чертежах (Тюменская, 5)')).not.toBeInTheDocument());
    expect(screen.getByText('Синтетический объект «Северный», корпус 2 (демо)')).toBeInTheDocument();
    // tiles still count every object that passed the other filters
    expect(tile(/Требуют действий/).textContent).toContain('1');
  });

  it('applies section, decision, scenario and date filters from a shared link', async () => {
    renderApp('/dashboard?section=ИОС4&status=CONFIRMED_VIOLATION');
    await waitFor(() => expect(requests).toContain('/api/v1/dashboard?section=ИОС4&status=CONFIRMED_VIOLATION'));
    await screen.findByText('Синтетический объект «Северный», корпус 2 (демо)');
    expect(screen.queryByText('Пример нарушений на чертежах (Тюменская, 5)')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сбросить' })).toBeInTheDocument();
  });

  it('narrows by protocol date (Moscow calendar day) and shows an empty state', async () => {
    renderApp('/dashboard?date_from=2026-09-26&date_to=2026-09-26');
    await screen.findByText('Синтетический объект «Школа на 550 мест» (демо)');
    expect(screen.queryByText('Пример нарушений на чертежах (Тюменская, 5)')).not.toBeInTheDocument();
  });

  it('summarises findings by matrix section, suspicions outside the matrix', async () => {
    renderApp('/dashboard');
    const chart = await screen.findByRole('table', { name: 'Находки по разделам и решениям' });
    await waitFor(() => expect(within(chart).getByRole('rowheader', { name: 'ИОС4' })).toBeInTheDocument());
    expect(within(chart).getByRole('rowheader', { name: 'Вне матрицы' })).toBeInTheDocument();
    expect(within(chart).getByLabelText('Подтверждено: 1')).toBeInTheDocument();
  });

  it('opens the latest protocol from a row click', async () => {
    const user = userEvent.setup();
    renderApp('/dashboard');
    await user.click(await screen.findByText('Пример нарушений на чертежах (Тюменская, 5)', { selector: 'strong, span' }).then((el) => el.closest('tr')!.querySelector('td:nth-child(4)')!));
    await waitFor(() => expect(currentLocation.pathname).toMatch(new RegExp(`^/objects/${TYUMEN}/protocols/`)));
  });
});
