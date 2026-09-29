/**
 * Reading `runs/<run_id>/artifacts.json` (RunArtifacts contract) and the artifacts it lists.
 *
 * Every entry is checked before it is read: the path must match the run_layout.yaml template of its kind, stay
 * inside the run directory after symlink resolution, and have the declared size; parsed artifacts must also have
 * the declared sha256 and validate record by record against their contract schema (run_layout.yaml `schema`).
 * Nothing is globbed: an artifact that is not in the index does not exist for the importer.
 */
import { readFileSync, realpathSync, statSync } from 'node:fs';
import path from 'node:path';
import type { ErrorObject } from 'ajv';
import { sha256Hex } from '../../common/hashing';
import { ContractSchemas, readYaml, summarizeAjvErrors } from '../../contracts/contracts';

export const ARTIFACTS_INDEX = 'artifacts.json';

export interface RunArtifactEntry {
  kind: string;
  path: string;
  format: string;
  sha256: string;
  size_bytes: number;
  schema_name?: string | null;
  object_id?: string | null;
  file_id?: string | null;
  records?: number | null;
  producer?: { agent?: string; command?: string };
  modified_at?: string;
}

export interface RunArtifactsIndex {
  schema_version: 1;
  layout_version: string;
  run_id: string;
  generated_at: string;
  objects?: string[];
  commands?: string[];
  artifacts: RunArtifactEntry[];
  page_tokens?: unknown[];
}

interface LayoutEntry {
  path: string;
  scope: string;
  format: string;
  schema: string | null;
}

/** One contract problem found while reading artifacts (rendered as CONTRACT_VALIDATION_FAILED items). */
export interface ArtifactIssue {
  artifact: string;
  schema: string;
  reason: string;
  pointer?: string;
}

export class ArtifactContractError extends Error {
  constructor(readonly issues: ArtifactIssue[]) {
    super(issues.map((i) => `${i.artifact}: ${i.reason}`).join('; '));
    this.name = 'ArtifactContractError';
  }
}

const PLACEHOLDERS: Record<string, string> = {
  object_id: '(?<object_id>[^/]+)',
  file_id: '(?<file_id>[^/]+)',
  page05: '\\d{5}',
  command: '[a-z][a-z_-]*',
};

function templateRegex(template: string): RegExp {
  const parts = template.split(/(\{[a-z0-9_]+\})/);
  const body = parts
    .map((part) => {
      const m = /^\{([a-z0-9_]+)\}$/.exec(part);
      if (m) return PLACEHOLDERS[m[1] ?? ''] ?? '[^/]+';
      return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    })
    .join('');
  return new RegExp(`^${body}$`);
}

export class RunLayoutRules {
  private readonly byKind: Map<string, LayoutEntry & { regex: RegExp }>;

  constructor(contractsDir: string) {
    const raw = readYaml<{ artifacts: Record<string, LayoutEntry> }>(path.join(contractsDir, 'run_layout.yaml'));
    this.byKind = new Map(Object.entries(raw.artifacts).map(([kind, e]) => [kind, { ...e, regex: templateRegex(e.path) }]));
  }

  entry(kind: string): (LayoutEntry & { regex: RegExp }) | undefined {
    return this.byKind.get(kind);
  }

  /** Placeholder values of `relPath` for `kind`, or null when it does not match the template. */
  match(kind: string, relPath: string): Record<string, string> | null {
    const e = this.byKind.get(kind);
    const m = e?.regex.exec(relPath);
    return m ? { ...(m.groups ?? {}) } : null;
  }
}

function ajvIssues(artifact: string, schema: string, errors: readonly ErrorObject[], prefix = ''): ArtifactIssue[] {
  return errors.slice(0, 20).map((e) => ({
    artifact,
    schema,
    reason: summarizeAjvErrors([e]),
    pointer: `${prefix}${e.instancePath || '/'}`,
  }));
}

/** Reads and checks artifacts of one run directory. */
export class RunArtifactsReader {
  constructor(
    readonly runDir: string,
    private readonly schemas: ContractSchemas,
    private readonly layout: RunLayoutRules,
  ) {}

  /** artifacts.json, validated against run_artifacts.schema.json; null when the run has no index. */
  readIndex(): RunArtifactsIndex | null {
    const file = path.join(this.runDir, ARTIFACTS_INDEX);
    let text: string;
    try {
      text = readFileSync(file, 'utf8');
    } catch {
      return null;
    }
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch (err) {
      throw new ArtifactContractError([
        { artifact: ARTIFACTS_INDEX, schema: 'run_artifacts.schema.json', reason: `некорректный JSON (${(err as Error).message})` },
      ]);
    }
    const result = this.schemas.validate('run_artifacts', data);
    if (!result.valid) throw new ArtifactContractError(ajvIssues(ARTIFACTS_INDEX, 'run_artifacts.schema.json', result.errors));
    const index = data as RunArtifactsIndex;
    const issues: ArtifactIssue[] = [];
    const seen = new Set<string>();
    for (const a of index.artifacts) {
      if (seen.has(a.path)) issues.push({ artifact: ARTIFACTS_INDEX, schema: 'run_layout.yaml', reason: `путь ${a.path} указан дважды` });
      seen.add(a.path);
      if (!this.layout.match(a.kind, a.path)) {
        issues.push({
          artifact: ARTIFACTS_INDEX,
          schema: 'run_layout.yaml',
          reason: `путь ${a.path} не соответствует шаблону ${this.layout.entry(a.kind)?.path ?? '?'} вида ${a.kind}`,
        });
      }
    }
    if (issues.length) throw new ArtifactContractError(issues);
    return index;
  }

  /** Absolute path of an entry, strictly inside the run directory (symlinks resolved). */
  resolve(entry: RunArtifactEntry): string {
    const root = realpathSync(this.runDir);
    let real: string;
    try {
      real = realpathSync(path.join(root, ...entry.path.split('/')));
    } catch {
      throw new ArtifactContractError([{ artifact: entry.path, schema: 'run_artifacts.schema.json', reason: 'файл из artifacts.json отсутствует' }]);
    }
    if (!real.startsWith(root + path.sep)) {
      throw new ArtifactContractError([{ artifact: entry.path, schema: 'run_artifacts.schema.json', reason: 'путь выходит за пределы каталога запуска' }]);
    }
    return real;
  }

  /** Size check only (reference artifacts: layout, tables, … are not parsed by the import). */
  checkSize(entry: RunArtifactEntry): string {
    const file = this.resolve(entry);
    const size = statSync(file).size;
    if (size !== entry.size_bytes) {
      throw new ArtifactContractError([
        { artifact: entry.path, schema: 'run_artifacts.schema.json', reason: `размер ${size} байт, в artifacts.json ${entry.size_bytes}` },
      ]);
    }
    return file;
  }

  /** Bytes of an entry with size and sha256 verified against the index. */
  readBytes(entry: RunArtifactEntry): { bytes: Buffer; file: string } {
    const file = this.checkSize(entry);
    const bytes = readFileSync(file);
    const digest = sha256Hex(bytes);
    if (digest !== entry.sha256) {
      throw new ArtifactContractError([
        {
          artifact: entry.path,
          schema: 'run_artifacts.schema.json',
          reason: `sha256 ${digest.slice(0, 12)}… не совпадает с artifacts.json (${entry.sha256.slice(0, 12)}…)`,
        },
      ]);
    }
    return { bytes, file };
  }

  /** A JSON artifact validated against `schema`. */
  readJson<T>(entry: RunArtifactEntry, schema: string): { value: T; bytes: Buffer; file: string } {
    const { bytes, file } = this.readBytes(entry);
    let value: unknown;
    try {
      value = JSON.parse(bytes.toString('utf8'));
    } catch (err) {
      throw new ArtifactContractError([{ artifact: entry.path, schema: `${schema}.schema.json`, reason: `некорректный JSON (${(err as Error).message})` }]);
    }
    const result = this.schemas.validate(schema, value);
    if (!result.valid) throw new ArtifactContractError(ajvIssues(entry.path, `${schema}.schema.json`, result.errors));
    return { value: value as T, bytes, file };
  }

  /** A JSONL artifact; every line validated against `schema` (errors point at /line/<n>). */
  readJsonl<T>(entry: RunArtifactEntry, schema: string): { values: T[]; bytes: Buffer; file: string } {
    const { bytes, file } = this.readBytes(entry);
    const values: T[] = [];
    const issues: ArtifactIssue[] = [];
    bytes
      .toString('utf8')
      .split('\n')
      .forEach((line, i) => {
        if (!line.trim() || issues.length >= 20) return;
        let value: unknown;
        try {
          value = JSON.parse(line);
        } catch (err) {
          issues.push({ artifact: entry.path, schema: `${schema}.schema.json`, reason: `строка ${i + 1}: некорректный JSON (${(err as Error).message})` });
          return;
        }
        const result = this.schemas.validate(schema, value);
        if (!result.valid) issues.push(...ajvIssues(entry.path, `${schema}.schema.json`, result.errors, `/line/${i + 1}`));
        else values.push(value as T);
      });
    if (issues.length) throw new ArtifactContractError(issues);
    return { values, bytes, file };
  }
}
