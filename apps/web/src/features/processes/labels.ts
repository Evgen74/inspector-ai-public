import type { FileState, ProcessState, StepState } from './api';

export const STATUS_LABEL: Record<ProcessState, string> = {
  PENDING: 'В очереди',
  PARSING: 'Обработка',
  PAUSED: 'На паузе',
  READY: 'Готово',
  FAILED: 'Ошибка',
  CANCELLED: 'Отменено',
};
export const STATUS_COLOR: Record<ProcessState, string> = {
  PENDING: 'default',
  PARSING: 'processing',
  PAUSED: 'warning',
  READY: 'success',
  FAILED: 'error',
  CANCELLED: 'default',
};

export const STEP_LABEL: Record<string, string> = {
  prepare: 'Подготовка реестра комплекта',
  inventory: 'Инвентаризация файлов',
  recognize: 'Распознавание документов',
  layout: 'Разметка листов и штампов',
  tables: 'Таблицы и значения',
  compare: 'Сравнение ПД, РД и ИД',
  export: 'Формирование протокола',
  import: 'Импорт результатов',
};
export const stepLabel = (s: string | null | undefined) => (s ? (STEP_LABEL[s] ?? s) : '—');

export const STEP_STATE_LABEL: Record<StepState, string> = { PENDING: 'ожидает', RUNNING: 'выполняется', DONE: 'готово', FAILED: 'ошибка' };
export const FILE_STATE_LABEL: Record<FileState, string> = {
  RECEIVED: 'Принят',
  PREPARED: 'В реестре',
  PROCESSING: 'Обрабатывается',
  DONE: 'Обработан',
  REJECTED: 'Отклонён',
};
export const STAGE_LABEL: Record<string, string> = { PD: 'ПД', RD: 'РД', ID: 'ИД', UNKNOWN: 'не определена' };

export function durationText(start: string | null, end: string | null): string {
  if (!start) return '—';
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} с` : `${Math.floor(s / 60)} мин ${s % 60} с`;
}

/** «Распознавание: 1 287 из 3 169 страниц · 80 стр/мин · осталось ≈ 24 мин» (null when nothing to show). */
export function recognitionProgressText(stage: { step: string; done: number; total: number; pages_per_min?: number | null } | null | undefined): string | null {
  if (!stage || stage.step !== 'recognize' || stage.total <= 0) return null;
  const n = (v: number) => v.toLocaleString('ru-RU');
  let text = `Распознавание: ${n(stage.done)} из ${n(stage.total)} страниц`;
  const rate = stage.pages_per_min;
  if (rate && rate > 0) {
    text += ` · ${n(Math.round(rate))} стр/мин`;
    const minutes = Math.max(0, Math.ceil((stage.total - stage.done) / rate));
    text += minutes >= 60 ? ` · осталось ≈ ${Math.floor(minutes / 60)} ч ${minutes % 60} мин` : ` · осталось ≈ ${minutes} мин`;
  }
  return text;
}
