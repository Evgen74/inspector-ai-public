/**
 * Matrix sections from packages/contracts/codes.yaml (prefix ↔ id ranges, 97 §2.9): ПЗ … СМ, ИОС1–ИОС5.
 * Used by the dashboard section filter; order = the matrix order.
 */
import { parse } from 'yaml';
import codesYaml from '@inspector/contracts/codes.yaml?raw';

interface Prefix {
  latin: string;
  cyrillic: string;
  first: number;
  last: number;
  section: string;
}

const parsed = parse(codesYaml) as { prefixes: Prefix[] };

export interface MatrixSection {
  /** Short Russian section as printed in the protocol (section_ru), e.g. «ИОС4». */
  code: string;
  latin: string;
  /** «Раздел 5. ИОС4» */
  title: string;
  params: number;
}

export const MATRIX_SECTIONS: MatrixSection[] = parsed.prefixes.map((p) => ({
  code: p.cyrillic,
  latin: p.latin,
  title: p.section,
  params: p.last - p.first + 1,
}));

export function sectionOrder(code: string): number {
  const i = MATRIX_SECTIONS.findIndex((s) => s.code === code);
  return i === -1 ? MATRIX_SECTIONS.length : i;
}
