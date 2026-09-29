import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTimeSec } from '../format';
import { completenessBasisLabel, confidenceLabel, protocolStatusColor, protocolStatusText, runStatusLabel, withoutScenarioCode } from './labels';

describe('Russian labels for codes without label_ru', () => {
  it('translates completeness basis, confidence and run status, never echoing the code', () => {
    expect(completenessBasisLabel('MANDATORY_SOURCE_MISSING')).toBe('Не загружен обязательный источник');
    expect(completenessBasisLabel('SOMETHING_NEW')).toBe('Иное основание');
    expect(confidenceLabel('MEDIUM')).toBe('Средняя');
    expect(runStatusLabel('SUCCEEDED')).toBe('Успешно');
  });

  it('states protocol status with the version and a green finalized badge', () => {
    expect(protocolStatusText('PROTOCOL_FINALIZED', 2)).toBe('Финализирован · v2');
    expect(protocolStatusText('VERIFICATION_COMPLETED', 1)).toBe('Верификация завершена · v1');
    expect(protocolStatusText('IN_VERIFICATION', 1)).toBe('На верификации · v1');
    expect(protocolStatusColor('PROTOCOL_FINALIZED')).toBe('green');
  });

  it('drops the raw scenario code from server lines', () => {
    expect(withoutScenarioCode('Тип проверки: FULL — Полный комплект (ПД, РД, ИД)')).toBe('Тип проверки: Полный комплект (ПД, РД, ИД)');
  });

  it('formats dates as dd.mm.yyyy in Moscow time', () => {
    expect(formatDate('2026-09-22')).toBe('22.09.2026');
    expect(formatDate('2026-09-28T22:30:00.000Z')).toBe('29.09.2026');
    expect(formatDateTimeSec('2026-09-29T08:08:05.000Z')).toBe('29.09.2026 11:08:05');
  });
});
