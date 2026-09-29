/**
 * Russian labels for codes that enums.yaml carries without `label_ru` (the contract stays the source of the
 * codes; this file only supplies the words). Unknown codes fall back to a neutral «—»-free text, never the raw code
 * in prominent UI: callers may pass `fallback`.
 */
import { enumLabel } from './enums';

export const COMPLETENESS_BASIS_RU: Record<string, string> = {
  REGISTRY_MISSING: 'Нет реестра файлов',
  REGISTRY_ROW_INVALID: 'Ошибка в строке реестра',
  REGISTRY_HASH_MISMATCH: 'Хэш файла не совпадает с реестром',
  FILE_NOT_LISTED: 'Файла нет в реестре',
  OBJECT_MISMATCH: 'Файл относится к другому объекту',
  REVISION_UNRESOLVED: 'Редакция документа не определена',
  APPROVAL_MISSING: 'Нет отметки о согласовании',
  SUPERSEDED_ONLY: 'Есть только заменённая редакция',
  MANDATORY_SOURCE_MISSING: 'Не загружен обязательный источник',
  DECLARED_NOT_RECEIVED: 'Заявлен в реестре, но не получен',
  CURRENT_REVISION_NOT_UPLOADED: 'Не загружена актуальная редакция',
  FILE_REJECTED: 'Файл отклонён при проверке',
  SOURCE_UNREADABLE: 'Источник не читается',
  FILE_NOT_PROCESSED: 'Файл ещё не обработан',
  VALUE_ABSTAINED: 'Значение не удалось надёжно извлечь',
  UNIT_INCOMPATIBLE: 'Несовместимые единицы измерения',
  VALUE_UNPARSEABLE: 'Значение не удалось разобрать',
  VALUE_IMPLAUSIBLE: 'Значение неправдоподобно',
  SCOPE_MISMATCH: 'Не совпадает область применения',
  SHEETS_NOT_MATCHED: 'Листы не сопоставлены',
  EVIDENCE_NOT_LOCALIZABLE: 'Место в документе не определено',
  ENGINE_ERROR: 'Ошибка обработки',
  LOW_CONFIDENCE_SEMANTIC: 'Низкая уверенность распознавания',
  STAGE_NOT_APPLICABLE: 'Стадия не применима',
  PARAM_NOT_APPLICABLE_TO_OBJECT: 'Параметр не применим к объекту',
  PARAM_DEACTIVATED: 'Параметр отключён',
};

export const completenessBasisLabel = (code: string | null | undefined) =>
  code ? (COMPLETENESS_BASIS_RU[code] ?? 'Иное основание') : '—';

export const CONFIDENCE_RU: Record<string, string> = { HIGH: 'Высокая', MEDIUM: 'Средняя', LOW: 'Низкая' };
export const confidenceLabel = (code: string | null | undefined) => (code ? (CONFIDENCE_RU[code] ?? code) : '—');

/** Monitoring / batch run statuses. */
export const RUN_STATUS_RU: Record<string, string> = {
  SUCCEEDED: 'Успешно',
  SUCCESS: 'Успешно',
  COMPLETED: 'Завершён',
  FAILED: 'Ошибка',
  RUNNING: 'Выполняется',
  PENDING: 'В очереди',
  QUEUED: 'В очереди',
  CANCELLED: 'Отменён',
  PARTIAL: 'Частично',
  NONE: 'Нет запусков',
};
export const runStatusLabel = (code: string | null | undefined) => (code ? (RUN_STATUS_RU[code] ?? 'Иное состояние') : '—');

/** Protocol status text with the version: «Финализирован · v2», «Верификация завершена · v1». */
export function protocolStatusText(status: string, webVersion?: number | null): string {
  const base =
    status === 'PROTOCOL_FINALIZED'
      ? 'Финализирован'
      : status === 'VERIFICATION_COMPLETED'
        ? 'Верификация завершена'
        : status === 'SUPERSEDED'
          ? 'Заменён новой версией'
          : enumLabel('ProtocolStatus', status);
  return webVersion ? `${base} · v${webVersion}` : base;
}

export function protocolStatusColor(status: string): string {
  return status === 'PROTOCOL_FINALIZED' ? 'green' : status === 'VERIFICATION_COMPLETED' ? 'cyan' : status === 'SUPERSEDED' ? 'default' : 'gold';
}

/** Server text «Тип проверки: FULL — Полный комплект (ПД, РД, ИД)» → without the raw code. */
export function withoutScenarioCode(line: string | null | undefined): string {
  return (line ?? '').replace(/\b(FULL|PD_RD_ONLY|PD_ID_ONLY|RD_ID_ONLY|SINGLE_ONLY|PARTIALLY_LOADED)\s+[—-]\s+/g, '');
}

/** «FREE-HEATING-001» → «вне матрицы: HEATING-001» is not a name: callers pair the code with a name from the catalog. */
export const isFreeParam = (code: string) => code.startsWith('FREE-');
