/**
 * Contract-first request/response validation against `packages/contracts/openapi/openapi.yaml` (OAS 3.0.3).
 *
 * openapi-backend (ajv 8) is used purely as a router + validator; Nest controllers stay the handlers.
 * A conformance test checks that every operation has a route and every route has an operation.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { Injectable, type OnModuleInit } from '@nestjs/common';
import type { ErrorObject } from 'ajv';
import addFormats from 'ajv-formats';
import localizeRu from 'ajv-i18n/localize/ru';
import OpenAPIBackend, { type Document, type Operation, type Request as OasRequest } from 'openapi-backend';
import { parse as parseYaml } from 'yaml';

export const API_PREFIX = '/api/v1';
/**
 * The document lives in `packages/contracts/openapi/openapi.yaml` (owner AG-00; contracts are law) and is
 * resolved through the `@inspector/contracts` workspace package export. Fallback (same depth from src/ and
 * dist/): <repo>/apps/api/{src,dist}/openapi/ → <repo>/packages/contracts/openapi/openapi.yaml.
 */
function resolveOpenApiPath(): string {
  try {
    return require.resolve('@inspector/contracts/openapi/openapi.yaml');
  } catch {
    return path.resolve(__dirname, '..', '..', '..', '..', 'packages', 'contracts', 'openapi', 'openapi.yaml');
  }
}

export const OPENAPI_PATH = resolveOpenApiPath();

/**
 * AG-08 additions waiting for AG-00 to merge them into the contracts document (see the header of each file).
 * Same depth from src/ and dist/: apps/api/{src,dist}/openapi/ → apps/api/openapi/pending/.
 */
export const OPENAPI_PENDING_DIR = path.resolve(__dirname, '..', '..', 'openapi', 'pending');

const COMPONENT_KINDS = ['schemas', 'parameters', 'responses', 'headers', 'requestBodies'] as const;

type Json = Record<string, unknown>;

/** Overlay files in name order (empty when the directory is gone, i.e. after AG-00 merged them). */
export function pendingOverlayFiles(dir: string = OPENAPI_PENDING_DIR): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith('.yaml') || f.endsWith('.yml'))
    .sort()
    .map((f) => path.join(dir, f));
}

function sameJson(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Adds the overlay's tags, paths and components to `base`. An overlay only adds: an entry the base already
 * has is skipped when identical (the overlay was adopted by AG-00) and otherwise the base wins and the entry
 * is reported in `conflicts` (the conformance test fails on any conflict; the API still starts).
 */
export function mergeOpenApiOverlay(
  base: Json,
  overlay: Json,
  label = 'overlay',
  conflicts: string[] = [],
): Json {
  const out = structuredClone(base) as Json & { paths?: Json; components?: Record<string, Json>; tags?: Json[] };
  const paths = (overlay.paths ?? {}) as Json;
  out.paths ??= {};
  for (const [p, item] of Object.entries(paths)) {
    if (p in out.paths) {
      if (!sameJson(out.paths[p], item)) conflicts.push(`${label}: paths.${p}`);
      continue;
    }
    out.paths[p] = item;
  }
  const components = (overlay.components ?? {}) as Record<string, Json>;
  out.components ??= {};
  for (const kind of COMPONENT_KINDS) {
    const add = components[kind];
    if (!add) continue;
    const target = (out.components[kind] ??= {});
    for (const [name, def] of Object.entries(add)) {
      if (name in target) {
        if (!sameJson(target[name], def)) conflicts.push(`${label}: components.${kind}.${name}`);
        continue;
      }
      target[name] = def;
    }
  }
  for (const kind of Object.keys(components)) {
    if (!(COMPONENT_KINDS as readonly string[]).includes(kind)) conflicts.push(`${label}: components.${kind} (unsupported)`);
  }
  const tags = (overlay.tags ?? []) as Array<{ name: string }>;
  out.tags ??= [];
  for (const tag of tags) {
    const existing = (out.tags as Array<{ name: string }>).find((t) => t.name === tag.name);
    if (existing) {
      if (!sameJson(existing, tag)) conflicts.push(`${label}: tags.${tag.name}`);
      continue;
    }
    out.tags.push(tag);
  }
  return out;
}

/** Conflicts found while merging the pending overlays into the contracts document (see mergeOpenApiOverlay). */
export const OPENAPI_OVERLAY_CONFLICTS: string[] = [];

/** The contracts document plus the pending AG-08 overlays: the document the API actually serves. */
export function loadOpenApiDocument(
  file: string = OPENAPI_PATH,
  overlays: string[] = pendingOverlayFiles(),
): Document {
  let doc = parseYaml(readFileSync(file, 'utf8')) as Json;
  const conflicts: string[] = [];
  for (const overlay of overlays) {
    doc = mergeOpenApiOverlay(doc, parseYaml(readFileSync(overlay, 'utf8')) as Json, path.basename(overlay), conflicts);
  }
  OPENAPI_OVERLAY_CONFLICTS.splice(0, OPENAPI_OVERLAY_CONFLICTS.length, ...conflicts);
  return doc as unknown as Document;
}

export interface OasValidationError {
  /** e.g. /query/page_size, /requestBody/run_dir, /path/object_id */
  pointer: string;
  field: string | undefined;
  /** Russian message (ajv-i18n) */
  message: string;
}

function toValidationErrors(errors: readonly ErrorObject[] | null | undefined): OasValidationError[] {
  if (!errors?.length) return [];
  const copy = errors.map((e) => ({ ...e }));
  localizeRu(copy);
  return copy.map((e) => {
    let pointer = e.instancePath || '';
    let field = pointer.split('/').filter(Boolean).at(-1);
    if (e.keyword === 'required') {
      const missing = (e.params as { missingProperty?: string }).missingProperty;
      if (missing) {
        pointer = `${pointer}/${missing}`;
        field = missing;
      }
    } else if (e.keyword === 'additionalProperties') {
      const extra = (e.params as { additionalProperty?: string }).additionalProperty;
      if (extra) {
        pointer = `${pointer}/${extra}`;
        field = extra;
      }
    }
    let message = e.message ?? e.keyword;
    if (e.keyword === 'enum') {
      const allowed = (e.params as { allowedValues?: unknown[] }).allowedValues ?? [];
      message = `${message}: ${allowed.map(String).join(', ')}`;
    }
    return { pointer: pointer || '/', field, message };
  });
}

@Injectable()
export class OpenApiService implements OnModuleInit {
  readonly document: Document;
  private readonly backend: OpenAPIBackend;
  private initialized = false;

  constructor() {
    this.document = loadOpenApiDocument();
    this.backend = new OpenAPIBackend({
      definition: structuredClone(this.document),
      apiRoot: API_PREFIX,
      strict: true,
      validate: true,
      coerceTypes: true,
      ajvOpts: { allErrors: true, strict: false },
      customizeAjv: (ajv) => {
        addFormats(ajv);
        return ajv;
      },
    });
  }

  async onModuleInit(): Promise<void> {
    await this.init();
  }

  async init(): Promise<void> {
    if (!this.initialized) {
      await this.backend.init();
      this.initialized = true;
    }
  }

  match(req: OasRequest): Operation | undefined {
    return this.backend.matchOperation(req);
  }

  validateRequest(req: OasRequest, operation: Operation): OasValidationError[] {
    const result = this.backend.validateRequest(req, operation);
    return result.valid ? [] : toValidationErrors(result.errors as ErrorObject[] | null);
  }

  validateResponse(body: unknown, operation: Operation, statusCode: number): OasValidationError[] {
    const result = this.backend.validateResponse(body, operation, statusCode);
    return result.valid ? [] : toValidationErrors(result.errors as ErrorObject[] | null);
  }

  /** [method, "/api/v1/objects/{object_id}"] for every operation of the document. */
  operations(): Array<{ method: string; path: string; operationId: string }> {
    const out: Array<{ method: string; path: string; operationId: string }> = [];
    for (const [p, item] of Object.entries(this.document.paths ?? {})) {
      for (const method of ['get', 'put', 'post', 'delete', 'patch', 'head', 'options'] as const) {
        const op = (item as Record<string, { operationId?: string } | undefined>)[method];
        if (op?.operationId) out.push({ method: method.toUpperCase(), path: API_PREFIX + p, operationId: op.operationId });
      }
    }
    return out;
  }
}
