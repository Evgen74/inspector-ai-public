/** Upload vertical (ТЗ модуль 1): upload, list and status of processes. Types mirror apps/api/openapi/pending/upload.openapi.yaml. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';

export type ProcessState = 'PENDING' | 'PARSING' | 'READY' | 'FAILED';
export type StepState = 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED';
export type FileState = 'RECEIVED' | 'PREPARED' | 'PROCESSING' | 'DONE' | 'REJECTED';

export interface ProcessSummary {
  process_id: string;
  status: ProcessState;
  stage: string | null;
  object_id: string;
  object_name: string;
  address: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  queue: string | null;
  progress: {
    steps_done: number;
    steps_total: number;
    percent: number;
    stage?: { step: string; done: number; total: number; pages_per_min?: number | null } | null;
  };
  error: string | null;
  files_total: number;
  files_rejected: number;
  pages_total: number;
  verification_process_id: string | null;
  protocol: { object_id: string; run_id: string } | null;
  /** Set when the process was archived («Архивировать»). */
  archived_at?: string | null;
}

export interface ProcessFileItem {
  file_id: string | null;
  name: string;
  size_bytes: number;
  sha256: string;
  status: FileState;
  stage: string | null;
  stage_source: string | null;
  pages: number | null;
  problems: string[];
  from_archive: string | null;
}

export interface ProcessDetail extends ProcessSummary {
  steps: Array<{ step: string; status: StepState; started_at: string | null; finished_at: string | null }>;
  files: ProcessFileItem[];
  log: Array<{ ts: string; level: 'info' | 'warn' | 'error'; message: string }>;
}

export interface UploadLimits {
  max_file_bytes: number;
  max_package_bytes: number;
  max_files: number;
  extensions: string[];
}

export interface UploadResult {
  process_id: string;
  status: 'PENDING';
  object_id: string;
  queue: string;
  accepted: Array<{ name: string; size_bytes: number; sha256: string }>;
  rejected: Array<{ name: string; code: string; detail: string }>;
}

/** Fallback used until GET /documents/upload/limits answers (500 МБ per document, 5 ГБ per package). */
export const DEFAULT_LIMITS: UploadLimits = {
  max_file_bytes: 500 * 1024 * 1024,
  max_package_bytes: 5 * 1024 * 1024 * 1024,
  max_files: 500,
  extensions: ['.pdf', '.docx', '.xml', '.zip', '.7z', '.rar'],
};

export const isActive = (s: ProcessState) => s === 'PENDING' || s === 'PARSING';

export function useProcesses(includeArchived = false) {
  return useQuery({
    queryKey: ['processes', includeArchived],
    queryFn: () =>
      apiFetch<{ items: ProcessSummary[]; total: number }>(`/processes${includeArchived ? '?include_archived=true' : ''}`),
    // Poll while something is being processed.
    refetchInterval: (q) => (q.state.data?.items.some((p) => isActive(p.status)) ? 3000 : 20_000),
  });
}

export function useProcess(id: string) {
  return useQuery({
    queryKey: ['process', id],
    queryFn: () => apiFetch<ProcessDetail>(`/processes/${encodeURIComponent(id)}`),
    refetchInterval: (q) => (q.state.data && !isActive(q.state.data.status) ? false : 2000),
  });
}

export function useUploadLimits(enabled = true) {
  return useQuery({
    enabled,
    queryKey: ['upload-limits'],
    queryFn: () => apiFetch<UploadLimits>('/documents/upload/limits'),
    staleTime: 3_600_000,
  });
}

export interface UploadInput {
  files: File[];
  registry?: File | null;
  objectName?: string;
  address?: string;
}

export function useUploadDocuments() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: UploadInput) => {
      const form = new FormData();
      if (input.objectName?.trim()) form.append('object_name', input.objectName.trim());
      if (input.address?.trim()) form.append('address', input.address.trim());
      // The relative path (folder uploads) is kept in the file name.
      for (const f of input.files) form.append('files', f, (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
      if (input.registry) form.append('registry', input.registry, input.registry.name);
      return apiFetch<UploadResult>('/documents/upload', { method: 'POST', body: form });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['processes'] });
      void client.invalidateQueries({ queryKey: ['objects'] });
    },
  });
}

/** «500 МБ», «5 ГБ». */
const sizeLabel = (bytes: number) =>
  bytes >= 1024 ** 3 ? `${Number((bytes / 1024 ** 3).toFixed(1))} ГБ` : `${Math.round(bytes / 1048576)} МБ`;

/** Client-side check of the upload limits and formats: Russian message per file (server checks again).
 * An archive is a container: only the package limit applies to it (its documents are checked on the server). */
export function validateClientFiles(
  files: Array<{ name: string; size: number }>,
  limits: UploadLimits = DEFAULT_LIMITS,
): { errors: Map<string, string>; totalBytes: number; packageError: string | null } {
  const errors = new Map<string, string>();
  let total = 0;
  for (const f of files) {
    total += f.size;
    const dot = f.name.lastIndexOf('.');
    const ext = dot < 0 ? '' : f.name.slice(dot).toLowerCase();
    if (!limits.extensions.includes(ext)) {
      errors.set(f.name, `Формат ${ext || 'без расширения'} не поддерживается. Допустимо: PDF, DOCX, XML и архивы ZIP, 7z, RAR.`);
    } else if (f.size === 0) {
      errors.set(f.name, 'Файл пустой (0 байт).');
    } else if (!['.zip', '.7z', '.rar'].includes(ext) && f.size > limits.max_file_bytes) {
      errors.set(f.name, `Файл больше ${sizeLabel(limits.max_file_bytes)} (${(f.size / 1048576).toFixed(1)} МБ). Разделите документ на части.`);
    }
  }
  let packageError: string | null = null;
  if (total > limits.max_package_bytes) {
    packageError = `Общий размер пакета ${(total / 1048576).toFixed(1)} МБ превышает лимит ${sizeLabel(limits.max_package_bytes)}. Загрузите файлы несколькими пакетами.`;
  } else if (files.length > limits.max_files) {
    packageError = `В пакете ${files.length} файлов — максимум ${limits.max_files}. Разделите пакет на части.`;
  }
  return { errors, totalBytes: total, packageError };
}

export interface ArchiveInput {
  kind: 'process' | 'object' | 'batch-run';
  id: string;
  /** false = return from the archive */
  archived?: boolean;
}

/** «Архивировать» (permission batch.import): hides a process, object or imported run from the lists. */
export function useArchive() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id, archived = true }: ArchiveInput) => {
      const path =
        kind === 'process'
          ? `/processes/${encodeURIComponent(id)}/archive`
          : kind === 'object'
            ? `/admin/objects/${encodeURIComponent(id)}/archive`
            : `/admin/batch-runs/${encodeURIComponent(id)}/archive`;
      return apiFetch<{ kind: string; id: string; archived: boolean; archived_at: string | null }>(path, {
        method: 'POST',
        body: JSON.stringify({ archived }),
      });
    },
    onSuccess: () => {
      for (const key of ['processes', 'process', 'objects', 'object', 'dashboard', 'batchRuns']) {
        void client.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}
