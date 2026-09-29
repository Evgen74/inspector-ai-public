import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { canonicalJson, inputManifestHash, sha256Hex } from '../src/common/hashing';
import { pickRequestId, uuidv7 } from '../src/common/ids';
import { ErrorCatalog, renderTemplate } from '../src/common/problem';
import { ConfigError, loadConfig } from '../src/config/config';
import { contractSchemas, REPO_CONTRACTS } from './helpers';

interface HashVectors {
  sha256_bytes: Array<{ input_utf8: string; sha256: string }>;
  canonical_json: Array<{ input: unknown; canonical: string; sha256: string }>;
  input_manifest_hash: Array<{ rows: Array<Record<string, unknown>>; expected: string }>;
}

describe('hashing (golden vectors shared with inspector_common.hashing)', () => {
  const vectors = JSON.parse(readFileSync(path.join(REPO_CONTRACTS, 'vectors', 'hashing.json'), 'utf8')) as HashVectors;

  it('sha256', () => {
    for (const v of vectors.sha256_bytes) expect(sha256Hex(v.input_utf8)).toBe(v.sha256);
  });

  it('canonical JSON', () => {
    for (const v of vectors.canonical_json) {
      expect(canonicalJson(v.input)).toBe(v.canonical);
      expect(sha256Hex(canonicalJson(v.input))).toBe(v.sha256);
    }
    expect(() => canonicalJson({ x: Number.NaN })).toThrow(TypeError);
  });

  it('input_manifest_hash', () => {
    for (const v of vectors.input_manifest_hash) expect(inputManifestHash(v.rows)).toBe(v.expected);
  });
});

describe('ids', () => {
  it('uuidv7 has version 7, the RFC variant and a millisecond timestamp prefix', () => {
    const now = Date.UTC(2026, 8, 27, 12, 0, 0);
    const id = uuidv7(now);
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(Number.parseInt(id.replace(/-/g, '').slice(0, 12), 16)).toBe(now);
    expect(uuidv7(now + 1) > id).toBe(true);
  });

  it('pickRequestId keeps well-formed ids only', () => {
    expect(pickRequestId('abc-12345')).toBe('abc-12345');
    expect(pickRequestId(['first-1234', 'second'])).toBe('first-1234');
    expect(pickRequestId('short')).not.toBe('short');
    expect(pickRequestId('x'.repeat(200))).toHaveLength(36);
    expect(pickRequestId(undefined)).toHaveLength(36);
  });
});

describe('error catalogue', () => {
  const catalog = ErrorCatalog.load(REPO_CONTRACTS);

  it('renders placeholders and keeps unknown ones visible', () => {
    expect(renderTemplate('Файл {file_id} ({x})', { file_id: 'F1' })).toBe('Файл F1 ({x})');
  });

  it('builds RFC 9457 bodies that satisfy problem.schema.json', () => {
    const body = catalog.problem({
      code: 'FILE_MISSING_ON_DISK',
      details: { file_id: 'F9001', relative_path: 'a/b.pdf' },
      status: 422,
      instancePath: '/api/v1/x',
      requestId: 'req-12345678',
    });
    expect(body).toMatchObject({
      type: '/problems/file-missing-on-disk',
      status: 422,
      code: 'FILE_MISSING_ON_DISK',
      instance: '/api/v1/x#req-12345678',
      retryable: false,
    });
    expect(body.detail).toContain('F9001');
    expect(contractSchemas().validate('problem', body)).toEqual({ valid: true });
  });

  it('uses the catalogue HTTP status and refuses unknown codes', () => {
    expect(catalog.problem({ code: 'NOT_FOUND', instancePath: '/', requestId: 'r-12345678' }).status).toBe(404);
    expect(() => catalog.get('NO_SUCH_CODE')).toThrow(/errors\.yaml/);
  });
});

describe('config', () => {
  it('derives defaults from the repository layout', () => {
    const c = loadConfig({});
    expect(c.port).toBe(3000);
    expect(c.host).toBe('127.0.0.1');
    expect(c.databaseUrl).toBe('postgresql://localhost:5432/inspector');
    expect(c.runsRoot).toBe(path.join(c.repoRoot, 'runs'));
    expect(c.dataRoot).toBe(path.join(c.repoRoot, 'data_utf8'));
    expect(c.validateResponses).toBe(true);
  });

  it('maps the Python log-level vocabulary and turns response validation off in prod', () => {
    expect(loadConfig({ INSPECTOR_LOG_LEVEL: 'WARNING' }).logLevel).toBe('warn');
    expect(loadConfig({ INSPECTOR_APP_ENV: 'prod' }).validateResponses).toBe(false);
    expect(loadConfig({ INSPECTOR_APP_ENV: 'prod', INSPECTOR_API_RESPONSE_VALIDATION: 'on' }).validateResponses).toBe(true);
  });

  it('fails fast with a Russian message on invalid values', () => {
    expect(() => loadConfig({ INSPECTOR_API_PORT: '99999' })).toThrow(ConfigError);
    expect(() => loadConfig({ INSPECTOR_DATABASE_URL: 'mysql://x' })).toThrow(/Некорректная конфигурация/);
  });
});
