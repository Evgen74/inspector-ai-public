/**
 * Keyboard map of the verification workspace (05 §3.17.3). Physical keys (`KeyboardEvent.code`), so C / R / U
 * work the same on the Russian layout (С / К / Г). The evidence panes keep their own keys when focused
 * (0, +, −, [, ], O — AG-08's EvidencePane).
 */

export type HotkeyAction =
  | 'CONFIRM'
  | 'CONFIRM_NOW'
  | 'REJECT'
  | 'CLARIFY'
  | 'NEXT'
  | 'PREV'
  | 'NEXT_PENDING'
  | 'SUBMIT'
  | 'ESCAPE'
  | 'UNDO'
  | 'DIGIT'
  | 'HELP'
  | 'METER';

export interface Hotkey {
  action: HotkeyAction;
  digit?: number;
}

function inEditable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.closest !== 'function') return false;
  return Boolean(el.closest('input, textarea, select, [contenteditable="true"], .ant-select'));
}

/** The workspace action of a keydown, or null (typing in a field, a viewer key, an unmapped key). */
export function hotkeyOf(e: Pick<KeyboardEvent, 'code' | 'key' | 'shiftKey' | 'ctrlKey' | 'metaKey' | 'altKey' | 'target'>): Hotkey | null {
  const mod = e.ctrlKey || e.metaKey;
  if (e.code === 'Escape') return { action: 'ESCAPE' };
  if (e.code === 'Enter' || e.code === 'NumpadEnter') {
    // Enter commits the open decision; inside a comment it needs Ctrl/⌘ (Enter is a new line there).
    if (inEditable(e.target) && !mod) return null;
    return { action: 'SUBMIT' };
  }
  if (inEditable(e.target)) return null;
  if (mod && e.code === 'KeyZ') return { action: 'UNDO' };
  if (mod || e.altKey) return null;
  const inViewer = Boolean((e.target as HTMLElement | null)?.closest?.('[data-viewer]'));
  switch (e.code) {
    case 'KeyC':
      return { action: e.shiftKey ? 'CONFIRM_NOW' : 'CONFIRM' };
    case 'KeyR':
      return { action: 'REJECT' };
    case 'KeyU':
      return { action: 'CLARIFY' };
    case 'KeyJ':
    case 'ArrowDown':
      return inViewer && e.code === 'ArrowDown' ? null : { action: 'NEXT' };
    case 'KeyK':
    case 'ArrowUp':
      return inViewer && e.code === 'ArrowUp' ? null : { action: 'PREV' };
    case 'KeyN':
      return { action: 'NEXT_PENDING' };
    case 'KeyT':
      return { action: 'METER' };
    case 'Slash':
      return e.shiftKey ? { action: 'HELP' } : null;
    case 'F1':
      return { action: 'HELP' };
    default:
      break;
  }
  const digit = /^(?:Digit|Numpad)([1-9])$/.exec(e.code);
  if (digit) return { action: 'DIGIT', digit: Number(digit[1]) };
  return null;
}

export const HOTKEY_HELP: Array<[string, string]> = [
  ['C', 'Подтвердить нарушение (открыть решение)'],
  ['Shift + C', 'Подтвердить сразу (основание и комментарий по умолчанию)'],
  ['R', 'Отклонить → 1–9 код причины'],
  ['U', 'Требует уточнения → 1–8 основание'],
  ['Enter', 'Сохранить решение (в комментарии — Ctrl + Enter)'],
  ['Esc', 'Закрыть форму решения'],
  ['J / ↓, K / ↑', 'Следующая / предыдущая карточка'],
  ['N', 'Следующая необработанная'],
  ['Ctrl + Z', 'Отменить последнее решение (10 с)'],
  ['T', 'Секундомер и счётчик кликов'],
  ['?', 'Эта справка'],
  ['0, +, −, [, ], O', 'В панели документа: вся страница, масштаб, фрагменты, разметка'],
];
