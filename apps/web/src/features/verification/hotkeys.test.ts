/**
 * Keyboard map of the verification workspace (05 §3.17.3): physical-key mapping (independent of layout), the
 * editable-field guard, the Enter/Ctrl+Enter distinction inside a comment, and the viewer's own arrow keys.
 */
import { describe, expect, it } from 'vitest';
import { hotkeyOf, HOTKEY_HELP } from './hotkeys';

function evt(over: Partial<KeyboardEvent> & { code: string }): Pick<KeyboardEvent, 'code' | 'key' | 'shiftKey' | 'ctrlKey' | 'metaKey' | 'altKey' | 'target'> {
  return { key: over.code, shiftKey: false, ctrlKey: false, metaKey: false, altKey: false, target: null, ...over };
}

describe('hotkeyOf', () => {
  it('maps the three decision actions and Shift+C to the immediate-confirm variant', () => {
    expect(hotkeyOf(evt({ code: 'KeyC' }))).toEqual({ action: 'CONFIRM' });
    expect(hotkeyOf(evt({ code: 'KeyC', shiftKey: true }))).toEqual({ action: 'CONFIRM_NOW' });
    expect(hotkeyOf(evt({ code: 'KeyR' }))).toEqual({ action: 'REJECT' });
    expect(hotkeyOf(evt({ code: 'KeyU' }))).toEqual({ action: 'CLARIFY' });
  });

  it('maps navigation: J/K and arrows, N for next pending', () => {
    expect(hotkeyOf(evt({ code: 'KeyJ' }))).toEqual({ action: 'NEXT' });
    expect(hotkeyOf(evt({ code: 'ArrowDown' }))).toEqual({ action: 'NEXT' });
    expect(hotkeyOf(evt({ code: 'KeyK' }))).toEqual({ action: 'PREV' });
    expect(hotkeyOf(evt({ code: 'ArrowUp' }))).toEqual({ action: 'PREV' });
    expect(hotkeyOf(evt({ code: 'KeyN' }))).toEqual({ action: 'NEXT_PENDING' });
  });

  it('reads 1–9 as DIGIT for the reason/basis chip pick', () => {
    expect(hotkeyOf(evt({ code: 'Digit1' }))).toEqual({ action: 'DIGIT', digit: 1 });
    expect(hotkeyOf(evt({ code: 'Digit9' }))).toEqual({ action: 'DIGIT', digit: 9 });
    expect(hotkeyOf(evt({ code: 'Numpad3' }))).toEqual({ action: 'DIGIT', digit: 3 });
    expect(hotkeyOf(evt({ code: 'Digit0' }))).toBeNull(); // reserved for the viewer (full page)
  });

  it('Enter submits outside a field; Ctrl/⌘+Enter submits inside one, plain Enter there is a newline', () => {
    expect(hotkeyOf(evt({ code: 'Enter' }))).toEqual({ action: 'SUBMIT' });
    expect(hotkeyOf(evt({ code: 'NumpadEnter' }))).toEqual({ action: 'SUBMIT' });
    const textarea = document.createElement('textarea');
    document.body.append(textarea);
    expect(hotkeyOf(evt({ code: 'Enter', target: textarea }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'Enter', target: textarea, ctrlKey: true }))).toEqual({ action: 'SUBMIT' });
    expect(hotkeyOf(evt({ code: 'Enter', target: textarea, metaKey: true }))).toEqual({ action: 'SUBMIT' });
    textarea.remove();
  });

  it('Escape always fires, even while typing', () => {
    const input = document.createElement('input');
    document.body.append(input);
    expect(hotkeyOf(evt({ code: 'Escape', target: input }))).toEqual({ action: 'ESCAPE' });
    input.remove();
  });

  it('ignores every other key while a field, select or contenteditable is focused', () => {
    for (const el of [document.createElement('input'), document.createElement('select'), (() => {
      const d = document.createElement('div');
      d.setAttribute('contenteditable', 'true'); // jsdom does not reflect the .contentEditable IDL property to the attribute
      return d;
    })()]) {
      document.body.append(el);
      expect(hotkeyOf(evt({ code: 'KeyC', target: el }))).toBeNull();
      expect(hotkeyOf(evt({ code: 'KeyR', target: el }))).toBeNull();
      expect(hotkeyOf(evt({ code: 'Digit1', target: el }))).toBeNull();
      el.remove();
    }
  });

  it('ignores keys with a modifier, except Ctrl/⌘+Z (undo) and the Enter cases above', () => {
    expect(hotkeyOf(evt({ code: 'KeyC', ctrlKey: true }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'KeyJ', metaKey: true }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'KeyR', altKey: true }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'KeyZ', ctrlKey: true }))).toEqual({ action: 'UNDO' });
    expect(hotkeyOf(evt({ code: 'KeyZ', metaKey: true }))).toEqual({ action: 'UNDO' });
  });

  it('? (Shift+/) and F1 open help; Slash alone does nothing; T toggles the meter', () => {
    expect(hotkeyOf(evt({ code: 'Slash', shiftKey: true }))).toEqual({ action: 'HELP' });
    expect(hotkeyOf(evt({ code: 'Slash' }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'F1' }))).toEqual({ action: 'HELP' });
    expect(hotkeyOf(evt({ code: 'KeyT' }))).toEqual({ action: 'METER' });
  });

  it("ArrowUp/ArrowDown inside the document viewer pane (ML zoom/pan) are not NEXT/PREV, but J/K still are", () => {
    const viewer = document.createElement('div');
    viewer.setAttribute('data-viewer', '');
    const inner = document.createElement('div');
    viewer.append(inner);
    document.body.append(viewer);
    expect(hotkeyOf(evt({ code: 'ArrowDown', target: inner }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'ArrowUp', target: inner }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'KeyJ', target: inner }))).toEqual({ action: 'NEXT' });
    expect(hotkeyOf(evt({ code: 'KeyK', target: inner }))).toEqual({ action: 'PREV' });
    viewer.remove();
  });

  it('an unmapped key returns null', () => {
    expect(hotkeyOf(evt({ code: 'KeyQ' }))).toBeNull();
    expect(hotkeyOf(evt({ code: 'F5' }))).toBeNull();
  });

  it('the help table documents every action key without duplicates', () => {
    expect(HOTKEY_HELP.length).toBeGreaterThan(5);
    const keys = HOTKEY_HELP.map(([k]) => k);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
