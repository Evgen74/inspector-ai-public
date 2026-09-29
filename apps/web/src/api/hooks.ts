/** TanStack Query hooks. Query keys follow 08 §3.7. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch, toQuery } from './client';
import type { BatchRun, FileItem, Health, ImportResult, ManifestStage, ObjectDetail, ObjectSummary, Page } from './types';

export interface ObjectsFilter {
  page: number;
  pageSize: number;
  q?: string;
}

export function useObjects(filter: ObjectsFilter) {
  return useQuery({
    queryKey: ['objects', filter],
    queryFn: () =>
      apiFetch<Page<ObjectSummary>>(`/objects${toQuery({ page: filter.page, page_size: filter.pageSize, q: filter.q })}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}

export function useObject(objectId: string) {
  return useQuery({
    queryKey: ['object', objectId],
    queryFn: () => apiFetch<ObjectDetail>(`/objects/${encodeURIComponent(objectId)}`),
  });
}

export interface FilesFilter {
  page: number;
  pageSize: number;
  stage?: ManifestStage;
  localStatus?: string;
  q?: string;
}

export function useObjectFiles(objectId: string, filter: FilesFilter) {
  return useQuery({
    queryKey: ['objectFiles', objectId, filter],
    queryFn: () =>
      apiFetch<Page<FileItem>>(
        `/objects/${encodeURIComponent(objectId)}/files${toQuery({
          page: filter.page,
          page_size: filter.pageSize,
          stage: filter.stage,
          local_status: filter.localStatus,
          q: filter.q,
        })}`,
      ),
    placeholderData: keepPreviousData,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    // 503 still carries a Health body: read it instead of failing the query.
    queryFn: async () => {
      const res = await fetch('/api/v1/health', { headers: { Accept: 'application/json' } });
      return (await res.json()) as Health;
    },
    refetchInterval: 15_000,
    retry: false,
  });
}

export function useBatchRuns(page: number, pageSize: number) {
  return useQuery({
    queryKey: ['batchRuns', page, pageSize],
    queryFn: () => apiFetch<Page<BatchRun>>(`/admin/batch-runs${toQuery({ page, page_size: pageSize })}`),
    placeholderData: keepPreviousData,
  });
}

export function useImportBatchRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runDir: string) =>
      apiFetch<ImportResult>('/admin/batch-runs/import', { method: 'POST', body: JSON.stringify({ run_dir: runDir }) }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['objects'] }),
        client.invalidateQueries({ queryKey: ['object'] }),
        client.invalidateQueries({ queryKey: ['objectFiles'] }),
        client.invalidateQueries({ queryKey: ['batchRuns'] }),
      ]);
    },
  });
}
