/** Module 8 «Нормативная база» client (apps/api/src/modules/normative). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch, toQuery } from '../../api/client';

export interface NormRef {
  kind: 'sp' | 'gost' | 'fz' | 'other';
  designation: string;
  clause: string | null;
  edition: string | null;
  status: string | null;
  confidence: string | null;
}

export interface NormParam {
  code: string;
  name: string;
  section: string;
  criticality_level: string;
  criticality: string;
  unit: string | null;
  min_value: number | null;
  max_value: number | null;
  is_active: boolean;
  base_min_value: number | null;
  base_max_value: number | null;
  base_is_active: boolean;
  overridden: boolean;
  threshold_source: string | null;
  threshold_note: string | null;
  refs: NormRef[];
}

export interface ParamsResponse {
  matrix_version: string;
  base_version: string;
  total: number;
  overrides: number;
  sections: string[];
  items: NormParam[];
}

export interface NormDocument {
  designation: string;
  kind: string;
  edition: string | null;
  status: string | null;
  params_count: number;
}

export interface MatrixVersion {
  version: number;
  matrix_version: string;
  reason: string | null;
  created_by_login: string | null;
  created_at: string;
  changes: Array<{ param_code: string; fields: Record<string, { from: unknown; to: unknown }> }>;
}

export const nKeys = { params: ['normative', 'params'] as const, docs: ['normative', 'documents'] as const, versions: ['normative', 'versions'] as const };

export function useNormParams(filters: { q?: string; section?: string; criticality?: string; active?: string }) {
  return useQuery({ queryKey: [...nKeys.params, filters], queryFn: () => apiFetch<ParamsResponse>(`/normative/params${toQuery(filters)}`), placeholderData: (prev) => prev });
}

export function useNormDocuments() {
  return useQuery({ queryKey: nKeys.docs, queryFn: () => apiFetch<{ total: number; items: NormDocument[] }>('/normative/documents') });
}

export function useMatrixVersions() {
  return useQuery({ queryKey: nKeys.versions, queryFn: () => apiFetch<{ base_version: string; items: MatrixVersion[] }>('/normative/versions') });
}

export interface ParamPatch {
  min_value?: number | null;
  max_value?: number | null;
  is_active?: boolean;
  reason?: string | null;
}

export function useUpdateParam(csrf: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { code: string; patch: ParamPatch }) =>
      apiFetch<{ unchanged: boolean; matrix_version: string }>(`/normative/params/${encodeURIComponent(v.code)}`, {
        method: 'PUT',
        body: JSON.stringify(v.patch),
        headers: csrf ? { 'X-CSRF-Token': csrf } : {},
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['normative'] }),
  });
}
