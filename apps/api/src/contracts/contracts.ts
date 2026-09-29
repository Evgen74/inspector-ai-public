/**
 * Read-only access to `packages/contracts` (owner AG-00): enums.yaml, errors.yaml and the JSON Schemas.
 *
 * Contracts are law: the API never defines enum values or error codes of its own. JSON Schemas are
 * resolved from local files only (their `$id`s are identifiers, never fetched).
 */
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import Ajv2020, { type ErrorObject, type ValidateFunction } from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { parse as parseYaml } from 'yaml';

export const SCHEMA_BASE = 'https://contracts.inspector-ai.local/schemas/';

export interface EnumValue {
  code: string;
  label_ru?: string;
  [attr: string]: unknown;
}

export interface EnumDef {
  owner?: string;
  open?: boolean;
  values: EnumValue[];
}

export function readYaml<T>(file: string): T {
  return parseYaml(readFileSync(file, 'utf8')) as T;
}

/** enums.yaml → {EnumName: {values: [{code, label_ru?, …}]}} with bare strings normalized to {code}. */
export function loadEnums(contractsDir: string): Record<string, EnumDef> {
  const raw = readYaml<{ enums: Record<string, { values: Array<string | EnumValue>; open?: boolean; owner?: string }> }>(
    path.join(contractsDir, 'enums.yaml'),
  );
  const out: Record<string, EnumDef> = {};
  for (const [name, def] of Object.entries(raw.enums)) {
    out[name] = {
      owner: def.owner,
      open: def.open,
      values: def.values.map((v) => (typeof v === 'string' ? { code: v } : v)),
    };
  }
  return out;
}

export function enumCodes(enums: Record<string, EnumDef>, name: string): string[] {
  const def = enums[name];
  if (!def) throw new Error(`enum ${name} is not in packages/contracts/enums.yaml`);
  return def.values.map((v) => v.code);
}

/** A Draft 2020-12 validator preloaded with every schema of packages/contracts/schemas. */
export class ContractSchemas {
  private readonly ajv: Ajv2020;
  private readonly cache = new Map<string, ValidateFunction>();

  constructor(readonly contractsDir: string) {
    this.ajv = new Ajv2020({ allErrors: true, strict: false });
    addFormats(this.ajv);
    const dir = path.join(contractsDir, 'schemas');
    for (const file of readdirSync(dir).filter((f) => f.endsWith('.schema.json')).sort()) {
      const schema = JSON.parse(readFileSync(path.join(dir, file), 'utf8')) as { $id?: string };
      this.ajv.addSchema(schema, schema.$id ?? SCHEMA_BASE + file);
    }
  }

  /** Validate `data` against `<name>.schema.json` (e.g. `run_manifest`, `problem`). */
  validate(name: string, data: unknown): { valid: true } | { valid: false; errors: ErrorObject[] } {
    let fn = this.cache.get(name);
    if (!fn) {
      const found = this.ajv.getSchema(`${SCHEMA_BASE}${name}.schema.json`);
      if (!found) throw new Error(`schema ${name}.schema.json is not in packages/contracts/schemas`);
      fn = found;
      this.cache.set(name, fn);
    }
    return fn(data) ? { valid: true } : { valid: false, errors: [...(fn.errors ?? [])] };
  }
}

/** One-line human summary of ajv errors (used in problem details). */
export function summarizeAjvErrors(errors: readonly ErrorObject[], limit = 3): string {
  const parts = errors.slice(0, limit).map((e) => {
    const where = e.instancePath || '/';
    const extra =
      e.keyword === 'additionalProperties'
        ? ` (${String((e.params as { additionalProperty?: string }).additionalProperty)})`
        : e.keyword === 'enum'
          ? ` (${((e.params as { allowedValues?: unknown[] }).allowedValues ?? []).join(', ')})`
          : '';
    return `${where}: ${e.message ?? e.keyword}${extra}`;
  });
  const rest = errors.length > limit ? `; ещё ${errors.length - limit}` : '';
  return parts.join('; ') + rest;
}
