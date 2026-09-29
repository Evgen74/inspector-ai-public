/**
 * Locating and reading artifacts of an imported `inspector-batch` run directory (97 §1.4, run_layout.yaml).
 *
 * Paths come from `<run_dir>/artifacts.json` (schema run_artifacts, rebuilt by the CLI after every command);
 * when a run predates the index, the run_layout.yaml template of the kind is used. Every resolved path must
 * stay inside the runs root (symlinks included). JSON artifacts are validated against their contract schema
 * and cached by (path, mtime, size), so repeated reads of a protocol cost one stat().
 */
import { existsSync, readFileSync, realpathSync, statSync } from 'node:fs';
import path from 'node:path';
import { Inject, Injectable } from '@nestjs/common';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { ContractSchemas, readYaml, summarizeAjvErrors } from '../../contracts/contracts';
import { ApiProblem } from '../../common/problem';
import type { RunRecord } from './lookup.repository';

export type ArtifactKind =
  | 'PROTOCOL_JSON'
  | 'PROTOCOL_DOCX'
  | 'PROTOCOL_PDF'
  | 'FINDING_GROUPS'
  | 'FINDINGS'
  | 'LAYOUT'
  | 'SUBMISSION';

interface IndexEntry {
  kind: string;
  path: string;
  object_id?: string | null;
  file_id?: string | null;
}

interface LayoutTemplate {
  path: string;
  schema: string | null;
}

export interface ArtifactRef {
  kind: ArtifactKind;
  /** Absolute path (inside the runs root). */
  absPath: string;
  /** Path relative to the run directory, as in artifacts.json. */
  relPath: string;
}

interface CacheEntry {
  mtimeMs: number;
  size: number;
  value: unknown;
}

function isInside(root: string, candidate: string): boolean {
  const rel = path.relative(root, candidate);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

@Injectable()
export class RunArtifacts {
  private readonly templates: Record<string, LayoutTemplate>;
  private readonly cache = new Map<string, CacheEntry>();
  private readonly runsRootReal: string | null;

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly schemas: ContractSchemas,
  ) {
    const layout = readYaml<{ artifacts: Record<string, LayoutTemplate> }>(
      path.join(config.contractsDir, 'run_layout.yaml'),
    );
    this.templates = layout.artifacts;
    this.runsRootReal = existsSync(config.runsRoot) ? realpathSync(config.runsRoot) : null;
  }

  /** The run directory of an imported run, or null when it is gone or outside the runs root. */
  runDir(run: RunRecord): string | null {
    const dir = path.dirname(run.manifestRef);
    if (!existsSync(dir) || !this.runsRootReal) return null;
    const real = realpathSync(dir);
    return isInside(this.runsRootReal, real) ? real : null;
  }

  private readIndex(runDir: string): IndexEntry[] | null {
    const file = path.join(runDir, 'artifacts.json');
    if (!existsSync(file)) return null;
    const index = this.readJson(file, 'run_artifacts', 'artifacts.json') as { artifacts: IndexEntry[] };
    return index.artifacts;
  }

  /** The artifact of `kind` for an object (or a file, for LAYOUT) in the run, or null when absent. */
  locate(run: RunRecord, kind: ArtifactKind, key: { objectId?: string; fileId?: string }): ArtifactRef | null {
    const runDir = this.runDir(run);
    if (!runDir) return null;
    let rel: string | undefined;
    const index = this.readIndex(runDir);
    if (index) {
      rel = index.find(
        (a) =>
          a.kind === kind &&
          (key.objectId === undefined || a.object_id === key.objectId) &&
          (key.fileId === undefined || a.file_id === key.fileId),
      )?.path;
    } else {
      const template = this.templates[kind]?.path;
      if (template) {
        rel = template.replace('{object_id}', key.objectId ?? '').replace('{file_id}', key.fileId ?? '');
      }
    }
    if (!rel) return null;
    const abs = path.resolve(runDir, rel);
    if (!existsSync(abs)) return null;
    const real = realpathSync(abs);
    if (!this.runsRootReal || !isInside(this.runsRootReal, real)) return null;
    return { kind, absPath: real, relPath: rel };
  }

  schemaOf(kind: ArtifactKind): string | null {
    return this.templates[kind]?.schema ?? null;
  }

  /** Parse and validate a JSON artifact; a contract violation is a 422 CONTRACT_VALIDATION_FAILED. */
  readJson(absPath: string, schema: string | null, label: string): unknown {
    const st = statSync(absPath);
    const cached = this.cache.get(absPath);
    if (cached && cached.mtimeMs === st.mtimeMs && cached.size === st.size) return cached.value;
    let value: unknown;
    try {
      value = JSON.parse(readFileSync(absPath, 'utf8'));
    } catch (err) {
      throw new ApiProblem(
        'CONTRACT_VALIDATION_FAILED',
        { artifact: label, schema: schema ?? 'json', reason: `некорректный JSON (${(err as Error).message})` },
        { status: 422 },
      );
    }
    if (schema) {
      const result = this.schemas.validate(schema, value);
      if (!result.valid) {
        throw new ApiProblem(
          'CONTRACT_VALIDATION_FAILED',
          { artifact: label, schema: `${schema}.schema.json`, reason: summarizeAjvErrors(result.errors) },
          { status: 422 },
        );
      }
    }
    this.cache.set(absPath, { mtimeMs: st.mtimeMs, size: st.size, value });
    return value;
  }

  /**
   * Parse a JSONL artifact; every line is validated. Invalid lines are skipped and reported (a protocol stays
   * viewable when one group is malformed).
   */
  readJsonl(absPath: string, schema: string | null, label: string): { rows: unknown[]; invalid: string[] } {
    const st = statSync(absPath);
    const cacheKey = `${absPath}#jsonl`;
    const cached = this.cache.get(cacheKey);
    if (cached && cached.mtimeMs === st.mtimeMs && cached.size === st.size) {
      return cached.value as { rows: unknown[]; invalid: string[] };
    }
    const rows: unknown[] = [];
    const invalid: string[] = [];
    readFileSync(absPath, 'utf8')
      .split('\n')
      .forEach((line, i) => {
        if (!line.trim()) return;
        let value: unknown;
        try {
          value = JSON.parse(line);
        } catch {
          invalid.push(`${label}:${i + 1}: некорректный JSON`);
          return;
        }
        if (schema) {
          const result = this.schemas.validate(schema, value);
          if (!result.valid) {
            invalid.push(`${label}:${i + 1}: ${summarizeAjvErrors(result.errors, 2)}`);
            return;
          }
        }
        rows.push(value);
      });
    const value = { rows, invalid };
    this.cache.set(cacheKey, { mtimeMs: st.mtimeMs, size: st.size, value });
    return value;
  }
}
