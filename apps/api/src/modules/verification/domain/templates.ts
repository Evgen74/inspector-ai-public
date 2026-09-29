/**
 * Russian wording of the verification flow (UI prefill, system comments, protocol cells). Sources:
 * - ТЗ §9.4 sample comments (verbatim): SYSTEM_COMMENT_REJECTED, SYSTEM_COMMENT_DISPUTE;
 * - ТЗ §9.4 table rows 2–3 (clarification, confirmation) for the other two system comments;
 * - 05 §3.6 comment templates and suggested fixes;
 * - Приложение 2 §6 «Комментарий ИИ» («🤖 ИИ СОГЛАСЕН (NN%). …», 93 §5.3);
 * - 93 §5.4 status lines and «Решение инспектора» markers.
 */

/** ТЗ §9.4, «Пример системного комментария при отклонении кандидата» (verbatim, reason code substituted). */
export function systemCommentRejected(reasonCode: string): string {
  return (
    `Результат инспектора: NEGATIVE_VERIFIED. Причина: ${reasonCode}. Запись включена в черновик следующей версии ` +
    'набора данных; её использование для обучения допускается только после проверки куратором данных и выпуска ' +
    'dataset_version'
  );
}

/** ТЗ §9.4, «Пример системного комментария при спорном решении» (verbatim). */
export const SYSTEM_COMMENT_DISPUTE =
  'Статус: CLARIFICATION_REQUIRED. Показаны точные страницы и доказательные фрагменты. До повторного решения ' +
  'инспектора запись не включается в GOLD и не передаётся во внешнюю систему';

/** The dispute comment stored in Dispute_Log.ai_comment: sample 2 + the validator's argument (05 §3.7). */
export function disputeComment(argument: string): string {
  return `${SYSTEM_COMMENT_DISPUTE}. Основание: ${argument}`;
}

/** ТЗ §9.4 row 3: «Сохранить как положительный GOLD-кандидат; передача наружу только после финализации протокола». */
export function systemCommentConfirmed(basisCode: string): string {
  return (
    `Результат инспектора: CONFIRMED_VIOLATION. Основание: ${basisCode}. Запись сохранена как положительный ` +
    'GOLD-кандидат; передача наружу только после финализации протокола'
  );
}

/** ТЗ §9.4 row 2: «Показать источники, координаты и конфликт редакций; не включать в GOLD». */
export function systemCommentClarification(clarifyCode: string): string {
  return (
    `Результат инспектора: CLARIFICATION_REQUIRED. Основание: ${clarifyCode}. Показаны источники, координаты и ` +
    'конфликт редакций; запись не включается в GOLD'
  );
}

export const SYSTEM_COMMENT_REVERTED =
  'Решение отменено: карточка возвращена в очередь (PENDING); черновик набора данных по ней отозван';

/** Приложение 2 §6 «Комментарий ИИ» per AiVerdict (93 §5.3; «Отправлено в дообучение» with the v1.1 caveat). */
export function aiComment(verdict: 'AGREE' | 'UNCERTAIN' | 'DISAGREE', confidence: number, argument: string | null, fix: string | null): string {
  const pct = `${Math.round(confidence * 100)}%`;
  if (verdict === 'AGREE') {
    return [`🤖 ИИ СОГЛАСЕН (${pct}). Причина обоснована.`, fix, 'Отправлено в дообучение (черновик набора, после проверки куратором).']
      .filter(Boolean)
      .join(' ');
  }
  if (verdict === 'UNCERTAIN') {
    return [`🤖 ИИ НЕ УВЕРЕН (${pct}).`, argument, 'Запись требует внимательной проверки инспектором.'].filter(Boolean).join(' ');
  }
  return [`🤖 ИИ НЕ СОГЛАСЕН (${pct}).`, argument].filter(Boolean).join(' ');
}

/** Rejection_Log.suggested_fix per DecisionRejectReason (05 §3.6.1, column «suggested_fix»). */
export const SUGGESTED_FIX: Record<string, string> = {
  WRONG_REVISION: 'Проверить выбор актуальной редакции (предшественник/преемник, статус утверждения).',
  APPROVED_CHANGE: 'Добавить распознавание документов согласования изменений.',
  OCR_ERROR: 'Добавить фрагмент в набор для OCR; проверить предобработку страницы.',
  EXTRACTION_ERROR: 'Уточнить шаблон извлечения и семантическую привязку параметра {param}.',
  CV_ERROR: 'Разметить фрагмент для модели распознавания графики.',
  LINKING_ERROR: 'Проверить правила привязки листов, помещений и элементов.',
  WITHIN_TOLERANCE: 'Проверить пороги min/max параметра {param} в нормативной базе.',
  EQUIVALENT_SOLUTION: 'Добавить синонимы и эквиваленты в словарь терминов.',
  METHODOLOGY_DIFFERENCE: 'Учесть методику подсчёта (например, коэффициенты летних помещений).',
  NOT_APPLICABLE_PARAM: 'Уточнить правила применимости параметра {param}.',
  DUPLICATE: 'Улучшить дедупликацию групп доказательств.',
  OTHER: 'Разобрать вручную.',
};

export function suggestedFix(reasonCode: string, paramCode: string): string {
  return (SUGGESTED_FIX[reasonCode] ?? SUGGESTED_FIX.OTHER!).replaceAll('{param}', paramCode);
}

/** 93 §5.4 status line by process status. */
export const STATUS_LINE: Record<string, string> = {
  PENDING: '⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)',
  PARSING: '⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)',
  READY: '⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)',
  VERIFYING: '🔄 ВЕРИФИКАЦИЯ В ПРОЦЕССЕ (дозагрузка возможна)',
  COMPLETED: '☑️ ВЕРИФИКАЦИЯ ЗАВЕРШЕНА, ПРОТОКОЛ НЕ ФИНАЛИЗИРОВАН (дозагрузка возможна)',
  FINALIZED: '🔒 ПРОТОКОЛ ФИНАЛИЗИРОВАН (дозагрузка невозможна)',
};

export function versionLine(version: number, isFinal: boolean): string {
  return `${version} (${isFinal ? 'окончательная' : 'предварительная'})`;
}

/** «Решение инспектора» cell of Разделы 4–5 (protocol contract enum). */
export const DECISION_MARKER: Record<string, string> = {
  PENDING: '⏳ Ожидает',
  CONFIRMED_VIOLATION: '✅ Подтверждено',
  NEGATIVE_VERIFIED: '❌ Отклонено',
  CLARIFICATION_REQUIRED: '❓ Требует уточнения',
};

const STAGE_RU: Record<string, string> = { PD: 'ПД', RD: 'РД', ID: 'ИД' };

export function stageRu(stage: string | null | undefined): string {
  return (stage && STAGE_RU[stage]) || String(stage ?? '—');
}

export interface SourceRefLike {
  stage: string;
  file_id: string;
  pdf_page_number: number;
  document_sheet_number?: string | number | null;
  sheet_number?: string | number | null;
  document_code?: string | null;
  revision?: string | null;
}

/** «РД АНО-150321-1-РД-ОВ1 ред. 4, л. 5, стр. 18» (document code, else file id). */
export function sourceRef(s: SourceRefLike | null | undefined): string {
  if (!s) return 'источник не указан';
  const sheet = s.document_sheet_number ?? s.sheet_number;
  const doc = s.document_code || s.file_id;
  const rev = s.revision ? ` ред. ${s.revision}` : '';
  return `${stageRu(s.stage)} ${doc}${rev}, л. ${sheet ?? '—'}, стр. ${s.pdf_page_number}`;
}

const LOCATION_WORD: Record<string, string> = {
  ROOM: 'помещение',
  FLOOR: 'этаж',
  BUILDING: 'корпус',
  AXES: 'оси',
  ELEMENT: 'элемент',
};

/** «помещение 012», «оси 1-5/А-Г», «объект в целом». */
export function locationPhrase(locationType: string | null | undefined, location: string): string {
  if (locationType === 'OBJECT' || !location) return 'объект в целом';
  const word = locationType ? LOCATION_WORD[locationType] : undefined;
  return word ? `${word} ${location}` : location;
}

function valueText(v: unknown): string {
  if (v === null || v === undefined || v === '') return 'нет данных';
  return String(v);
}

export interface CardFacts {
  paramCode: string;
  parameterLabel: string;
  location: string;
  locationType: string | null;
  expected: unknown;
  actual: unknown;
  expectedSource: SourceRefLike | null;
  actualSource: SourceRefLike | null;
}

/** 05 §3.6.2 confirm comment template (prefilled, editable; comment_source TEMPLATE). */
export function confirmComment(f: CardFacts): string {
  return (
    `Подтверждаю нарушение по параметру «${f.parameterLabel}», ${locationPhrase(f.locationType, f.location)}: ` +
    `ожидается «${valueText(f.expected)}» (${sourceRef(f.expectedSource)}), ` +
    `фактически «${valueText(f.actual)}» (${sourceRef(f.actualSource)}). Согласованное изменение не представлено.`
  );
}

/** 05 §3.6.1 reject comment templates; OTHER has none (a hand-written comment ≥ 30 characters is required). */
export function rejectComment(reasonCode: string, f: CardFacts): string {
  const actualRef = sourceRef(f.actualSource);
  const loc = locationPhrase(f.locationType, f.location);
  switch (reasonCode) {
    case 'WRONG_REVISION':
      return `Отклонено: сравнение выполнено с неактуальной редакцией (${actualRef}).`;
    case 'APPROVED_CHANGE':
      return 'Отклонено: изменение согласовано (документ согласования указан в решении).';
    case 'OCR_ERROR':
      return `Отклонено: ошибка распознавания значения (${actualRef}).`;
    case 'EXTRACTION_ERROR':
      return `Отклонено: значение извлечено неверно (${actualRef}).`;
    case 'CV_ERROR':
      return `Отклонено: графический элемент распознан неверно (${actualRef}).`;
    case 'LINKING_ERROR':
      return `Отклонено: сопоставлены несопоставимые фрагменты (${loc}).`;
    case 'WITHIN_TOLERANCE':
      return 'Отклонено: отклонение в пределах допуска.';
    case 'EQUIVALENT_SOLUTION':
      return 'Отклонено: решения ПД и РД равнозначны (иное обозначение или формулировка).';
    case 'METHODOLOGY_DIFFERENCE':
      return 'Отклонено: различие обусловлено методикой подсчёта, проектное решение не изменено.';
    case 'NOT_APPLICABLE_PARAM':
      return `Отклонено: параметр ${f.paramCode} неприменим к объекту.`;
    case 'DUPLICATE':
      return 'Отклонено: дублирует другую находку.';
    default:
      return '';
  }
}

function lowerFirst(s: string): string {
  return s ? s[0]!.toLowerCase() + s.slice(1) : s;
}

/** Clarification comment: «Требует уточнения: конфликт редакций (РД …, л. 5, стр. 18).» */
export function clarifyComment(label: string, f: CardFacts): string {
  return `Требует уточнения: ${lowerFirst(label)} (${sourceRef(f.actualSource)}).`;
}
