import { describe, expect, it } from 'vitest';
import { withoutInternalCodes } from './format';
import { enumLabel } from './contracts/enums';

describe('withoutInternalCodes', () => {
  it('drops a bracketed internal code and keeps the readable text', () => {
    expect(withoutInternalCodes('не PDF (.txt): служебный файл разметки (GROUND_TRUTH_INDEX)')).toBe('не PDF (.txt): служебный файл разметки');
    expect(withoutInternalCodes('Отсутствует ИД')).toBe('Отсутствует ИД');
    expect(withoutInternalCodes(null)).toBe('');
  });
  it('shows the manifest section as a word', () => {
    expect(enumLabel('ManifestSection', 'OTHER')).toBe('Прочее');
  });
});
