/**
 * Runtime configuration from `INSPECTOR_*` environment variables (see the repository `.env.example`).
 *
 * Local-only runtime: the API talks to the local PostgreSQL and reads run directories from disk.
 * Paths default to the monorepo layout, like `inspector_common.settings` on the Python side.
 */
import os from 'node:os';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { z } from 'zod';

export const APP_CONFIG = Symbol('APP_CONFIG');

const REPO_MARKERS = ['packages/contracts/enums.yaml', 'services/ml/pyproject.toml'] as const;

export class ConfigError extends Error {
  constructor(
    readonly field: string,
    readonly reason: string,
  ) {
    super(`Некорректная конфигурация: ${field} — ${reason}.`);
    this.name = 'ConfigError';
  }
}

function looksLikeRepoRoot(dir: string): boolean {
  return REPO_MARKERS.every((marker) => existsSync(path.join(dir, marker)));
}

/** Monorepo root: `INSPECTOR_REPO_ROOT`, else the first parent of `start` or of the cwd with the markers. */
export function findRepoRoot(env: NodeJS.ProcessEnv = process.env, start: string = __dirname): string {
  const fromEnv = env.INSPECTOR_REPO_ROOT;
  if (fromEnv) {
    const root = path.resolve(fromEnv);
    if (!looksLikeRepoRoot(root)) {
      throw new ConfigError('INSPECTOR_REPO_ROOT', `каталог ${root} не похож на корень репозитория`);
    }
    return root;
  }
  for (const origin of [start, process.cwd()]) {
    let dir = path.resolve(origin);
    for (;;) {
      if (looksLikeRepoRoot(dir)) return dir;
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  throw new ConfigError('INSPECTOR_REPO_ROOT', 'не удалось найти корень репозитория; задайте переменную явно');
}

const boolFromEnv = z
  .enum(['true', 'false', '1', '0', 'on', 'off'])
  .transform((v) => v === 'true' || v === '1' || v === 'on');

const EnvSchema = z.object({
  INSPECTOR_APP_ENV: z.enum(['local', 'test', 'demo', 'prod']).default('local'),
  INSPECTOR_API_HOST: z.string().min(1).default('127.0.0.1'),
  INSPECTOR_API_PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  INSPECTOR_DATABASE_URL: z
    .string()
    .regex(/^postgres(ql)?:\/\//, 'ожидается строка подключения postgresql://')
    .default('postgresql://localhost:5432/inspector'),
  INSPECTOR_DATA_ROOT: z.string().min(1).optional(),
  INSPECTOR_RUNS_ROOT: z.string().min(1).optional(),
  INSPECTOR_CONTRACTS_DIR: z.string().min(1).optional(),
  // Same vocabulary as the Python settings (INFO, …) plus pino's lowercase names.
  INSPECTOR_LOG_LEVEL: z
    .string()
    .transform((v) => v.toLowerCase())
    .pipe(z.enum(['debug', 'info', 'warning', 'warn', 'error', 'silent']))
    .default('info'),
  INSPECTOR_LOG_FORMAT: z.enum(['json', 'console']).default('json'),
  INSPECTOR_API_RESPONSE_VALIDATION: boolFromEnv.optional(),
  // Platform services (AG-00): auth, sessions, page rendering.
  INSPECTOR_AUTH_MODE: z.enum(['required', 'optional']).optional(),
  INSPECTOR_REDIS_URL: z
    .string()
    .regex(/^rediss?:\/\//, 'ожидается строка подключения redis://')
    .default('redis://127.0.0.1:6379/0'),
  INSPECTOR_SESSION_IDLE_MIN: z.coerce.number().int().min(1).max(24 * 60).default(30),
  INSPECTOR_SESSION_ABSOLUTE_H: z.coerce.number().int().min(1).max(7 * 24).default(12),
  INSPECTOR_SESSION_MAX_PER_USER: z.coerce.number().int().min(1).max(50).default(3),
  INSPECTOR_COOKIE_SECURE: boolFromEnv.optional(),
  INSPECTOR_CACHE_ROOT: z.string().min(1).optional(),
  INSPECTOR_ML_API_URL: z
    .string()
    .regex(/^https?:\/\//, 'ожидается адрес http://')
    .default('http://127.0.0.1:8090'),
  INSPECTOR_ML_API_TOKEN: z.string().min(1).optional(),
  INSPECTOR_ML_API_TIMEOUT_MS: z.coerce.number().int().min(100).max(300_000).default(30_000),
  // `--workers` of the batch run started for an uploaded package; unset/empty = auto (the resource cap below).
  INSPECTOR_UPLOAD_WORKERS: z.preprocess((v) => (v === '' ? undefined : v), z.coerce.number().int().min(1).max(64).optional()),
  // Share of the machine an analysis may load (CPUs and memory); the Python pipeline applies the same cap.
  INSPECTOR_RESOURCE_CAP: z.coerce.number().min(0.05).max(1).default(0.75),
});

export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'silent';

export interface AppConfig {
  readonly appEnv: 'local' | 'test' | 'demo' | 'prod';
  readonly host: string;
  readonly port: number;
  readonly databaseUrl: string;
  readonly repoRoot: string;
  /** Decoded organizer mirror (data_utf8/). Read-only. */
  readonly dataRoot: string;
  /** inspector-batch run directories (runs/). The import endpoint reads only below this root. */
  readonly runsRoot: string;
  /** packages/contracts */
  readonly contractsDir: string;
  readonly logLevel: LogLevel;
  readonly logFormat: 'json' | 'console';
  /** Validate responses against the OpenAPI document (on by default outside prod). */
  readonly validateResponses: boolean;
  /**
   * `required`: every operation without `security: []` needs a session (default in demo/prod).
   * `optional`: requests without a session pass as anonymous; a session, when present, is enforced as usual
   * (default in local/test, until the web login screen lands). Refused in demo/prod.
   */
  readonly authMode: 'required' | 'optional';
  /** Redis for sessions, reauth tokens and login throttling. */
  readonly redisUrl: string;
  readonly sessionIdleSeconds: number;
  readonly sessionAbsoluteSeconds: number;
  readonly maxSessionsPerUser: number;
  /** `Secure` session cookie (named `__Host-ii_sid`); off for plain-http localhost outside prod. */
  readonly cookieSecure: boolean;
  /** Writable cache root (.cache/): rendered page tiles live in `<cacheRoot>/render`. */
  readonly cacheRoot: string;
  /** Internal ml-api (services/ml/apps/ml_api, FastAPI) that renders PDF pages. */
  readonly mlApiUrl: string;
  readonly mlApiToken: string | null;
  readonly mlApiTimeoutMs: number;
  /** `--workers` for the recognition of an uploaded package (INSPECTOR_UPLOAD_WORKERS, default 8). */
  readonly uploadWorkers: number;
}

/** Organizer package layout (same constants as inspector_common.paths). */
export const PACKAGE_DIR_NAME = 'ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0';
export const DOCUMENTS_DIR_PARTS = ['ХАКАТОН_УЧАСТНИКАМ_ГОТОВО_К_ПЕРЕДАЧЕ', '01_ДОКУМЕНТАЦИЯ'] as const;

export function organizerManifestPath(dataRoot: string): string {
  return path.join(dataRoot, PACKAGE_DIR_NAME, 'data', 'document_manifest.jsonl');
}

export function splitPolicyPath(dataRoot: string): string {
  return path.join(dataRoot, PACKAGE_DIR_NAME, 'data', 'split_policy.json');
}

export function documentsRoot(dataRoot: string): string {
  return path.join(dataRoot, ...DOCUMENTS_DIR_PARTS);
}

function resolveContractsDir(repoRoot: string, override: string | undefined): string {
  if (override) return path.resolve(override);
  try {
    // `@inspector/contracts` is a workspace dependency; its package exports enums.yaml.
    return path.dirname(require.resolve('@inspector/contracts/enums.yaml'));
  } catch {
    return path.join(repoRoot, 'packages', 'contracts');
  }
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env, overrides: Partial<AppConfig> = {}): AppConfig {
  const parsed = EnvSchema.safeParse(env);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    throw new ConfigError(String(issue?.path.join('.') ?? 'env'), issue?.message ?? 'некорректное значение');
  }
  const e = parsed.data;
  const repoRoot = overrides.repoRoot ?? findRepoRoot(env);
  const level = e.INSPECTOR_LOG_LEVEL === 'warning' ? 'warn' : e.INSPECTOR_LOG_LEVEL;
  const strictEnv = e.INSPECTOR_APP_ENV === 'demo' || e.INSPECTOR_APP_ENV === 'prod';
  const authMode = e.INSPECTOR_AUTH_MODE ?? (strictEnv ? 'required' : 'optional');
  if (strictEnv && authMode === 'optional') {
    throw new ConfigError('INSPECTOR_AUTH_MODE', `режим optional запрещён при INSPECTOR_APP_ENV=${e.INSPECTOR_APP_ENV}`);
  }
  const config: AppConfig = {
    appEnv: e.INSPECTOR_APP_ENV,
    host: e.INSPECTOR_API_HOST,
    port: e.INSPECTOR_API_PORT,
    databaseUrl: e.INSPECTOR_DATABASE_URL,
    repoRoot,
    dataRoot: path.resolve(e.INSPECTOR_DATA_ROOT ?? path.join(repoRoot, 'data_utf8')),
    runsRoot: path.resolve(e.INSPECTOR_RUNS_ROOT ?? path.join(repoRoot, 'runs')),
    contractsDir: resolveContractsDir(repoRoot, e.INSPECTOR_CONTRACTS_DIR),
    logLevel: level,
    logFormat: e.INSPECTOR_LOG_FORMAT,
    validateResponses: e.INSPECTOR_API_RESPONSE_VALIDATION ?? e.INSPECTOR_APP_ENV !== 'prod',
    authMode,
    redisUrl: e.INSPECTOR_REDIS_URL,
    sessionIdleSeconds: e.INSPECTOR_SESSION_IDLE_MIN * 60,
    sessionAbsoluteSeconds: e.INSPECTOR_SESSION_ABSOLUTE_H * 3600,
    maxSessionsPerUser: e.INSPECTOR_SESSION_MAX_PER_USER,
    cookieSecure: e.INSPECTOR_COOKIE_SECURE ?? e.INSPECTOR_APP_ENV === 'prod',
    cacheRoot: path.resolve(e.INSPECTOR_CACHE_ROOT ?? path.join(repoRoot, '.cache')),
    mlApiUrl: e.INSPECTOR_ML_API_URL.replace(/\/+$/, ''),
    mlApiToken: e.INSPECTOR_ML_API_TOKEN ?? null,
    mlApiTimeoutMs: e.INSPECTOR_ML_API_TIMEOUT_MS,
    uploadWorkers: e.INSPECTOR_UPLOAD_WORKERS ?? Math.max(1, Math.floor(os.availableParallelism() * e.INSPECTOR_RESOURCE_CAP)),
    ...overrides,
  };
  return Object.freeze(config);
}
