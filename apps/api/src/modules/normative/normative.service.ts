/** Module 8 «Нормативная база»: the 132-parameter matrix with admin overrides of thresholds and activity. */
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { Inject, Injectable } from '@nestjs/common';
import { ApiProblem } from '../../common/problem';
import { validationProblem } from '../shared/tz-validation';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { type Catalog, type CatalogParam, loadCatalog, type NormRef } from './params-catalog';
import { type MatrixVersionRow, NormativeRepository, type OverridePatch, type OverrideRow } from './normative.repository';

export interface ParamsQuery {
  q?: string;
  section?: string;
  criticality?: string;
  active?: string;
}

export interface ParamUpdate {
  min_value?: number | null;
  max_value?: number | null;
  is_active?: boolean;
  reason?: string | null;
}

type Json = Record<string, unknown>;

const invalid = (detail: string): ApiProblem => validationProblem('INVALID_VALUE', 'Некорректное значение', detail);

@Injectable()
export class NormativeService {
  private catalogCache: Catalog | null = null;

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly repo: NormativeRepository,
  ) {}

  private get catalog(): Catalog {
    this.catalogCache ??= loadCatalog(this.config.contractsDir);
    return this.catalogCache;
  }

  private effectiveVersion(latest: MatrixVersionRow | undefined): string {
    return latest ? `${this.catalog.matrixVersion}+ovr.${latest.version}` : this.catalog.matrixVersion;
  }

  private merge(p: CatalogParam, o: OverrideRow | undefined): Json {
    return {
      code: p.code,
      name: p.name,
      section: p.section,
      criticality_level: p.criticality_level,
      criticality: p.criticality,
      unit: p.unit,
      min_value: o ? o.min_value : p.min_value,
      max_value: o ? o.max_value : p.max_value,
      is_active: o && o.is_active !== null ? o.is_active : p.is_active,
      base_min_value: p.min_value,
      base_max_value: p.max_value,
      base_is_active: p.is_active,
      overridden: Boolean(o),
      threshold_source: p.threshold_source,
      threshold_note: p.threshold_note,
      refs: p.refs,
    };
  }

  async list(query: ParamsQuery): Promise<Json> {
    const [overrides, versions] = await Promise.all([this.repo.overrides(), this.repo.versions(1)]);
    const byCode = new Map(overrides.map((o) => [o.param_code, o]));
    const q = (query.q ?? '').trim().toLowerCase();
    let items = this.catalog.params.map((p) => this.merge(p, byCode.get(p.code)));
    if (q) items = items.filter((i) => `${i.code} ${i.name} ${(i.refs as NormRef[]).map((r) => r.designation).join(' ')}`.toLowerCase().includes(q));
    if (query.section) items = items.filter((i) => i.section === query.section);
    if (query.criticality) items = items.filter((i) => i.criticality_level === query.criticality);
    if (query.active === 'true' || query.active === 'false') items = items.filter((i) => String(i.is_active) === query.active);
    return {
      matrix_version: this.effectiveVersion(versions[0]),
      base_version: this.catalog.matrixVersion,
      total: this.catalog.params.length,
      overrides: overrides.length,
      sections: [...new Set(this.catalog.params.map((p) => p.section))],
      items,
    };
  }

  async update(code: string, body: ParamUpdate, user: { id: string | null; login: string | null }): Promise<Json> {
    const param = this.catalog.params.find((p) => p.code === code);
    if (!param) throw new ApiProblem('NOT_FOUND');
    const fields = ['min_value', 'max_value', 'is_active'] as const;
    if (!fields.some((f) => body[f] !== undefined)) throw invalid('Не указано ни одного изменяемого поля.');
    for (const f of ['min_value', 'max_value'] as const) {
      const v = body[f];
      if (v !== undefined && v !== null && !Number.isFinite(v)) throw invalid('Порог должен быть числом.');
    }
    if (body.is_active !== undefined && typeof body.is_active !== 'boolean') throw invalid('Признак активности должен быть логическим.');
    const overrides = await this.repo.overrides();
    const prev = overrides.find((o) => o.param_code === code);
    const before = this.merge(param, prev);
    const patch: OverridePatch = {
      min_value: body.min_value !== undefined ? body.min_value : (before.min_value as number | null),
      max_value: body.max_value !== undefined ? body.max_value : (before.max_value as number | null),
      is_active: body.is_active !== undefined ? body.is_active : (before.is_active as boolean),
    };
    if (patch.min_value !== null && patch.max_value !== null && patch.min_value > patch.max_value) {
      throw invalid('Минимум не может быть больше максимума.');
    }
    const changed = fields.filter((f) => patch[f] !== before[f]);
    if (changed.length === 0) {
      const latest = (await this.repo.versions(1))[0];
      return { unchanged: true, matrix_version: this.effectiveVersion(latest), param: before };
    }
    const change = {
      param_code: code,
      fields: Object.fromEntries(changed.map((f) => [f, { from: before[f], to: patch[f] }])),
    };
    const reason = body.reason?.trim() || null;
    const version = await this.repo.save({ code, patch, baseVersion: this.catalog.matrixVersion, reason, change, user });
    await this.exportOverrides();
    const after = this.merge(param, { param_code: code, ...patch, matrix_version: version.version, updated_at: version.created_at });
    return {
      unchanged: false,
      matrix_version: this.effectiveVersion(version),
      version: version.version,
      audit_details: change,
      param: after,
    };
  }

  /** Overrides as a JSON file the pipeline can read (`.cache/matrix_overrides.json`); best effort. */
  async exportOverrides(): Promise<void> {
    try {
      const [overrides, versions] = await Promise.all([this.repo.overrides(), this.repo.versions(1)]);
      mkdirSync(this.config.cacheRoot, { recursive: true });
      writeFileSync(
        path.join(this.config.cacheRoot, 'matrix_overrides.json'),
        JSON.stringify({ matrix_version: this.effectiveVersion(versions[0]), overrides }, null, 2),
      );
    } catch {
      /* the DB is the source of truth */
    }
  }

  async versions(): Promise<Json> {
    const items = await this.repo.versions(50);
    return { base_version: this.catalog.matrixVersion, items: items.map((v) => ({ ...v, matrix_version: `${this.catalog.matrixVersion}+ovr.${v.version}` })) };
  }

  /** Normative documents cited by the matrix (read-only), most cited first. */
  documents(): Json {
    const docs = new Map<string, { designation: string; kind: string; editions: Set<string>; statuses: Map<string, number>; params: Set<string> }>();
    for (const p of this.catalog.params) {
      for (const r of p.refs) {
        const d = docs.get(r.designation) ?? { designation: r.designation, kind: r.kind, editions: new Set(), statuses: new Map(), params: new Set() };
        if (r.edition) d.editions.add(r.edition);
        if (r.status) d.statuses.set(r.status, (d.statuses.get(r.status) ?? 0) + 1);
        d.params.add(p.code);
        docs.set(r.designation, d);
      }
    }
    const items = [...docs.values()]
      .map((d) => ({
        designation: d.designation,
        kind: d.kind,
        edition: [...d.editions][0] ?? null,
        status: [...d.statuses.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null,
        params_count: d.params.size,
      }))
      .sort((a, b) => b.params_count - a.params_count || a.designation.localeCompare(b.designation, 'ru'));
    return { total: items.length, items };
  }
}
