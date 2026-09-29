/** Read-only view of the 132-parameter matrix seed (packages/contracts/seed/params.json; owner AG-03). */
import { readFileSync } from 'node:fs';
import path from 'node:path';

type Json = Record<string, unknown>;

export interface NormRef {
  kind: 'sp' | 'gost' | 'fz' | 'other';
  designation: string;
  clause: string | null;
  edition: string | null;
  status: string | null;
  confidence: string | null;
}

export interface CatalogParam {
  code: string;
  param_id: number;
  name: string;
  section: string;
  criticality_level: string;
  criticality: string;
  unit: string | null;
  min_value: number | null;
  max_value: number | null;
  threshold_source: string | null;
  threshold_note: string | null;
  is_active: boolean;
  refs: NormRef[];
}

export interface Catalog {
  matrixVersion: string;
  params: CatalogParam[];
}

const KINDS = ['sp', 'gost', 'fz', 'other'] as const;

function str(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

export function parseCatalog(raw: Json): Catalog {
  const params = ((raw.params as Json[] | undefined) ?? []).map((p): CatalogParam => {
    const refs: NormRef[] = [];
    const byKind = (p.references as Record<string, Json[]> | undefined) ?? {};
    for (const kind of KINDS) {
      for (const r of byKind[kind] ?? []) {
        refs.push({
          kind,
          designation: str(r.designation) ?? str(r.ref) ?? '—',
          clause: str(r.clause),
          edition: str(r.edition),
          status: str(r.status),
          confidence: str(r.confidence),
        });
      }
    }
    return {
      code: String(p.code),
      param_id: Number(p.param_id),
      name: String(p.short_name ?? p.parameter_name ?? p.code),
      section: String(p.section ?? ''),
      criticality_level: String(p.criticality_level ?? ''),
      criticality: String(p.criticality ?? ''),
      unit: str(p.unit_canonical) ?? str(p.unit),
      min_value: num(p.min_value),
      max_value: num(p.max_value),
      threshold_source: str(p.threshold_source),
      threshold_note: str(p.threshold_note),
      is_active: p.is_active !== false,
      refs,
    };
  });
  return { matrixVersion: String(raw.matrix_version ?? '0'), params };
}

export function loadCatalog(contractsDir: string): Catalog {
  return parseCatalog(JSON.parse(readFileSync(path.join(contractsDir, 'seed', 'params.json'), 'utf8')) as Json);
}
