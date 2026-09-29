/**
 * Enum labels straight from packages/contracts/enums.yaml (bundled at build time; no runtime fetch).
 * The UI never invents codes: unknown codes are shown raw, labels come only from the contract.
 */
import { parse } from 'yaml';
import enumsYaml from '@inspector/contracts/enums.yaml?raw';

interface RawEnumValue {
  code: string;
  label_ru?: string;
  color?: string;
  [attr: string]: unknown;
}

interface RawEnums {
  enums: Record<string, { values: Array<string | RawEnumValue> }>;
}

const parsed = parse(enumsYaml) as RawEnums;

const byEnum = new Map<string, Map<string, RawEnumValue>>(
  Object.entries(parsed.enums).map(([name, def]) => [
    name,
    new Map(def.values.map((v) => (typeof v === 'string' ? [v, { code: v }] : [v.code, v]))),
  ]),
);

/** Codes of an enum in contract order. */
export function enumCodes(enumName: string): string[] {
  return [...(byEnum.get(enumName)?.keys() ?? [])];
}

/** Russian label of a code, or the code itself when the contract has no label (open vocabularies). */
export function enumLabel(enumName: string, code: string | null | undefined): string {
  if (code === null || code === undefined) return '—';
  return byEnum.get(enumName)?.get(code)?.label_ru ?? code;
}

export function enumValue(enumName: string, code: string): RawEnumValue | undefined {
  return byEnum.get(enumName)?.get(code);
}
