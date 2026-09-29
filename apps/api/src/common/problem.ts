/**
 * RFC 9457 problems backed by the error catalogue `packages/contracts/errors.yaml`.
 *
 * Mirrors inspector_common.errors (Python): the same `type` slug, `instance` = "<path>#<request_id>",
 * Russian title/detail rendered from the catalogue, `{name}` placeholders filled from `details`.
 */
import path from 'node:path';
import { readYaml } from '../contracts/contracts';

export interface CatalogEntry {
  code: string;
  http: number | null;
  domain: string;
  severity: 'error' | 'warning' | 'info';
  title_ru: string;
  detail_ru: string;
  hint_ru?: string;
  retryable?: boolean;
  details?: Record<string, string>;
  [attr: string]: unknown;
}

/** Per-item problem (10 §3.2): used in `errors[]` / `warnings[]` and in successful bodies. */
export interface ProblemItem {
  code: string;
  title: string;
  detail: string;
  details?: Record<string, unknown>;
  pointer?: string;
  file_name?: string;
  field?: string;
}

export interface ProblemBody {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  code: string;
  request_id: string;
  timestamp: string;
  retryable: boolean;
  details?: Record<string, unknown>;
  errors?: ProblemItem[];
  warnings?: ProblemItem[];
}

const PLACEHOLDER = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

/** Fill `{name}` placeholders; unknown placeholders stay visible (same as the Python renderer). */
export function renderTemplate(template: string, details: Record<string, unknown>): string {
  return template.replace(PLACEHOLDER, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(details, name) ? String(details[name]) : whole,
  );
}

export class ErrorCatalog {
  private readonly entries: Map<string, CatalogEntry>;

  constructor(entries: CatalogEntry[]) {
    this.entries = new Map(entries.map((e) => [e.code, e]));
  }

  static load(contractsDir: string): ErrorCatalog {
    const raw = readYaml<{ defaults?: Partial<CatalogEntry>; errors: CatalogEntry[] }>(
      path.join(contractsDir, 'errors.yaml'),
    );
    const defaults = raw.defaults ?? {};
    return new ErrorCatalog(raw.errors.map((e) => ({ ...defaults, ...e }) as CatalogEntry));
  }

  has(code: string): boolean {
    return this.entries.has(code);
  }

  /** Unknown codes are a programming error: every code must be in errors.yaml. */
  get(code: string): CatalogEntry {
    const entry = this.entries.get(code);
    if (!entry) throw new Error(`error code ${code} is not in packages/contracts/errors.yaml`);
    return entry;
  }

  item(code: string, details: Record<string, unknown> = {}, extra: Partial<ProblemItem> = {}): ProblemItem {
    const entry = this.get(code);
    const item: ProblemItem = {
      code,
      title: entry.title_ru,
      detail: renderTemplate(entry.detail_ru, details),
      ...extra,
    };
    if (Object.keys(details).length > 0) item.details = details;
    return item;
  }

  problem(args: {
    code: string;
    details?: Record<string, unknown>;
    status?: number;
    instancePath: string;
    requestId: string;
    errors?: ProblemItem[];
    warnings?: ProblemItem[];
  }): ProblemBody {
    const entry = this.get(args.code);
    const details = args.details ?? {};
    const body: ProblemBody = {
      type: `/problems/${args.code.toLowerCase().replaceAll('_', '-')}`,
      title: entry.title_ru,
      status: args.status ?? entry.http ?? 500,
      detail: renderTemplate(entry.detail_ru, details),
      instance: `${args.instancePath}#${args.requestId}`,
      code: args.code,
      request_id: args.requestId,
      timestamp: new Date().toISOString(),
      retryable: Boolean(entry.retryable),
    };
    if (Object.keys(details).length > 0) body.details = details;
    if (args.errors?.length) body.errors = args.errors;
    if (args.warnings?.length) body.warnings = args.warnings;
    return body;
  }
}

/**
 * Throw from services/controllers; the exception filter renders it as application/problem+json.
 * `status` is needed only for catalogue codes without an HTTP status (e.g. CONTRACT_VALIDATION_FAILED → 422).
 */
export class ApiProblem extends Error {
  constructor(
    readonly code: string,
    readonly details: Record<string, unknown> = {},
    readonly options: { status?: number; errors?: ProblemItem[]; warnings?: ProblemItem[] } = {},
  ) {
    super(code);
    this.name = 'ApiProblem';
  }
}
