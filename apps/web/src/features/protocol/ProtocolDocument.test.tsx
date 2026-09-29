/**
 * Приложение 2 verbatim (93 §5.1): titles, header labels, column sets, the rendered cells (emoji markers,
 * percent text) and the appendices, from the contract-valid D1 fixture.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import fixture from '../../../../api/fixtures/d1/OBJ-TYUMENSKAYA-5-GOLD-SEED.protocol.json';
import type { Protocol } from '../../contracts/protocol';
import { ProtocolDocument } from './ProtocolDocument';

const protocol = fixture as unknown as Protocol;

function headers(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole('columnheader')
    .map((th) => th.textContent ?? '');
}

describe('ProtocolDocument — Приложение 2', () => {
  it('prints the seven sections and the appendices in order with their counts', () => {
    render(<ProtocolDocument protocol={protocol} />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № 2026-09-28-TYUMEN5-1');
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'РАЗДЕЛ 1. СТАТУС ЗАГРУЗКИ ДОКУМЕНТОВ',
      'РАЗДЕЛ 2. СВОДНАЯ СТАТИСТИКА (С ПРОЦЕНТАМИ)',
      'РАЗДЕЛ 3. ПАРАМЕТРЫ, НЕ ПРОВЕРЕННЫЕ ИЗ-ЗА ОТСУТСТВИЯ ИД — 1',
      'РАЗДЕЛ 4. КРИТИЧЕСКИЕ НАРУШЕНИЯ — 3',
      'РАЗДЕЛ 5. СУЩЕСТВЕННЫЕ НАРУШЕНИЯ — 0',
      'РАЗДЕЛ 6. ПОДОЗРЕНИЯ ИИ — 1',
      'РАЗДЕЛ 7. РЕЗОЛЮТИВНАЯ ЧАСТЬ',
      'ПРИЛОЖЕНИЕ А. РАЗДЕЛЬНЫЕ ТАБЛИЦЫ (п. 9.2 ТЗ)',
      'ПРИЛОЖЕНИЕ Б. КАРТОЧКИ ДОКАЗАТЕЛЬСТВ',
      'ПРИЛОЖЕНИЕ В. РЕЕСТР ВХОДНЫХ ФАЙЛОВ И ВЕРСИИ',
    ]);
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      '7.1. По критическим нарушениям',
      '7.2. По существенным нарушениям',
      'А.1. Комплектность и сопоставимость',
      'А.2. Предварительные кандидаты',
      'А.3. Подтверждённые инспектором нарушения',
      'А.4. Проверенные отрицательные результаты',
      'А.5. Гипотезы свободного поиска',
    ]);
  });

  it('prints the header block with the Приложение 2 labels, the status line and the added «Тип проверки»', () => {
    render(<ProtocolDocument protocol={protocol} />);
    const header = screen.getByRole('region', { name: 'Заголовок протокола' });
    const text = header.textContent ?? '';
    for (const label of ['Объект:', 'Адрес:', 'Номер надзорного дела:', 'Застройщик:', 'Подрядчик:', 'Дата формирования:', 'Версия протокола:', 'Статус:', 'Тип проверки:']) {
      expect(text).toContain(label);
    }
    expect(text).toContain('Статус: ⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)');
    expect(text).toContain('Версия протокола: 1 (предварительная)');
    expect(text).toContain('Дата формирования: 28 сентября 2026 г.');
    expect(text).toContain('Тип проверки: PD_RD_ONLY (Только ПД и РД)');
    expect(text).toContain('Адрес: г. Москва, ул. Тюменская, д. 5');
    expect(text).toContain('Застройщик: —');
  });

  it('uses the exact column sets of every table', () => {
    const { container } = render(<ProtocolDocument protocol={protocol} />);
    const tables = [...container.querySelectorAll('table.p2-table')] as HTMLElement[];
    expect(headers(tables[0]!)).toEqual(['Тип документа', 'Статус', 'Загружено файлов', 'Ожидается', 'Комментарий']);
    expect(headers(tables[1]!)).toEqual(['Показатель', 'Количество', '% от общего']);
    expect(headers(tables[2]!)).toEqual(['№', 'Код', 'Раздел', 'Параметр', 'Отсутствующий файл']);
    const violation = ['№', 'Раздел', 'Параметр (код)', 'ПД', 'РД', 'ИД', 'Отклонение', 'Решение инспектора'];
    expect(headers(tables[3]!)).toEqual(violation);
    expect(headers(tables[4]!)).toEqual(violation);
    expect(headers(tables[5]!)).toEqual(['№', 'Метод', 'Описание', 'ПД', 'РД', 'ИД', 'Решение инспектора', 'Причина отклонения', 'Комментарий ИИ']);
    expect(headers(tables[6]!)).toEqual(['№', 'Вид работ', 'Конкретная рекомендация']);
    expect(headers(tables[7]!)).toEqual(['№', 'Вид нарушения', 'Конкретная рекомендация']);
  });

  it('prints the statistics rows verbatim with the «─» indents and the percent text of the contract', () => {
    const { container } = render(<ProtocolDocument protocol={protocol} />);
    const rows = [...container.querySelectorAll('#p2-s2 tbody tr')].map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent));
    expect(rows).toEqual([
      ['Всего параметров в Матрице', '132', '100%'],
      ['Проверено успешно (есть ПД, РД, ИД)', '20', '15,1%'],
      ['Не проверено (отсутствует ИД)', '64', '48,5%'],
      ['Не загружены документы (технические ошибки)', '0', '0%'],
      ['Не проверено (отсутствует ПД/РД)', '48', '36,4%'],
      ['Выявлено нарушений (всего)', '3', '2,3%'],
      ['─ Критических (приостановка)', '3', '2,3%'],
      ['─ Существенных (предписание)', '0', '0%'],
      ['Подозрений ИИ (свободный поиск)', '1', '0,8%'],
    ]);
    expect(container.querySelector('#p2-s2')!.textContent).toContain(
      'До подтверждения инспектором расхождения являются кандидатами и не являются основанием для приостановки работ или выдачи предписания (п. 9.2 ТЗ)',
    );
  });

  it('prints the violation rows with the deviation markers and the ⏳ decision, and opens the card', async () => {
    const onOpenCard = vi.fn();
    const { container } = render(<ProtocolDocument protocol={protocol} onOpenCard={onOpenCard} />);
    const rows = [...container.querySelectorAll('#p2-s4 tbody tr')] as HTMLElement[];
    expect(rows).toHaveLength(3);
    expect(rows[0]!.textContent).toContain('Характеристики вентиляторов (IOS4-079), пом. 012');
    expect(rows[0]!.textContent).toContain('🔄 Изменена конфигурация');
    expect(rows[1]!.textContent).toContain('❌ Полное отсутствие');
    expect(rows[2]!.textContent).toContain('пом. 147, 198, 314');
    for (const r of rows) expect(within(r).getByText('⏳ Ожидает')).toHaveAttribute('data-code', 'PENDING');
    const user = userEvent.setup();
    await user.click(within(rows[1]!).getByRole('button', { name: 'Открыть карточку Б.3' }));
    expect(onOpenCard).toHaveBeenLastCalledWith('Б.3');
    await user.click(within(rows[2]!).getByText('Конфигурация вентиляции изменена'));
    expect(onOpenCard).toHaveBeenLastCalledWith('Б.4');
    expect(container.querySelector('#p2-s5 tbody')!.textContent).toBe('Не выявлено');
  });

  it('prints the suspicion and the резолютивная часть with the draft prefix', () => {
    const { container } = render(<ProtocolDocument protocol={protocol} />);
    const s6 = container.querySelector('#p2-s6 tbody tr')!;
    expect(s6.textContent).toContain('Графическое сравнение');
    expect(s6.textContent).toContain('267, 270, 271, 272');
    const s7 = [...container.querySelectorAll('#p2-s7 table')] as HTMLElement[];
    const critical = [...s7[0]!.querySelectorAll('tbody tr')].map((tr) => tr.textContent ?? '');
    expect(critical).toHaveLength(3);
    for (const r of critical) expect(r).toContain('Проект рекомендации (до подтверждения инспектором): ');
    expect(critical[0]).toContain('Монтаж вентиляционного оборудования (IOS4-079)');
    expect(s7[1]!.textContent).toContain('Не требуется');
  });

  it('prints Приложения А/Б/В: the banner, four evidence cards with every mandatory field, the registry with hashes', () => {
    const { container } = render(<ProtocolDocument protocol={protocol} />);
    const a = container.querySelector('#p2-app-a')!;
    expect(within(a as HTMLElement).getAllByText('Не являются нарушениями до решения инспектора')).toHaveLength(2);
    expect(a.textContent).toContain('IOS2-071');
    const cards = screen.getAllByRole('article');
    expect(cards.map((c) => c.getAttribute('aria-label'))).toEqual(['Карточка Б.1', 'Карточка Б.2', 'Карточка Б.3', 'Карточка Б.4']);
    const b4 = cards[3]!.textContent ?? '';
    for (const field of ['ID находки', 'Код параметра / правило', 'Ожидаемое значение (эталон)', 'Фактическое значение', 'Обоснование', 'Уровень риска', 'Решение инспектора', 'Причина решения', 'SHA-256', 'Шифр', 'Ред.', 'Статус утверждения', 'Лист / стр.', 'bbox (норм.)']) {
      expect(b4).toContain(field);
    }
    expect(b4).toContain('л. 7 / стр. 20'); // room 314 drawn on РД p20
    expect(b4).toContain('л. 5 / стр. 18');
    expect(b4).toContain('0c398d7b…84fd');
    const v = container.querySelector('#p2-app-v')!;
    expect(v.textContent).toContain('a9070055b75adeea0d47651cf9dca3ca818ca5f54ac7ce9ddcd86efc817db7dc');
    expect(v.textContent).toContain('input_manifest_hash');
  });

  it('continues numbering into Раздел 5 and prints 7.2 when there are substantial violations', () => {
    const p = JSON.parse(JSON.stringify(protocol)) as Protocol;
    const row = { ...p.appendix2.section4_critical.rows[2]!, no: 4, card_ref: 'Б.5', parameter_label: 'Площадь асфальтобетонного покрытия (SPZU-025) [карточка Б.5]', deviation: { direction: 'DECREASE', text: '⬇️ Уменьшение на 16%' } };
    p.appendix2.section5_substantial = { count: 1, rows: [row] };
    p.appendix2.section7_resolution.substantial = [
      { no: 1, violation_kind: 'Уменьшение площади асфальтобетонного покрытия на 16% (SPZU-025)', recommendation: 'Представить корректировку проекта благоустройства.' },
    ];
    const { container } = render(<ProtocolDocument protocol={p} />);
    expect(screen.getByRole('heading', { name: 'РАЗДЕЛ 5. СУЩЕСТВЕННЫЕ НАРУШЕНИЯ — 1' })).toBeInTheDocument();
    const r = container.querySelector('#p2-s5 tbody tr')!;
    expect(r.querySelector('td')!.textContent).toBe('4');
    expect(r.textContent).toContain('⬇️ Уменьшение на 16%');
    expect(container.querySelectorAll('#p2-s7 table')[1]!.textContent).toContain('Уменьшение площади асфальтобетонного покрытия на 16% (SPZU-025)');
  });

  it('shows the finalisation stamp only on a final protocol', () => {
    const p = JSON.parse(JSON.stringify(protocol)) as Protocol;
    render(<ProtocolDocument protocol={p} />);
    expect(screen.getByText('Протокол не финализирован: данные предварительные.')).toBeInTheDocument();
  });
});
