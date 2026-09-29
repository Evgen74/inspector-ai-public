/** Module 6 «РиН» client: delivery status of a process and the manual send. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';

export interface RinAttempt {
  attempt_no: number;
  started_at: string;
  outcome: string;
  http_status: number | null;
  detail: string | null;
  duration_ms: number | null;
}

export interface RinDelivery {
  process_id: string;
  status: 'PENDING_SYNC' | 'SYNCED' | 'SYNC_FAILED' | null;
  status_label: string;
  trigger?: 'AUTO' | 'MANUAL';
  attempts: number;
  max_attempts?: number;
  next_attempt_at?: string | null;
  last_error?: string | null;
  violations?: number;
  external_id?: string | null;
  synced_at?: string | null;
  attempts_log?: RinAttempt[];
}

export const rinKey = (processId: string) => ['rin', processId] as const;

export function useRinStatus(processId: string | undefined) {
  return useQuery({
    queryKey: rinKey(processId ?? ''),
    queryFn: () => apiFetch<RinDelivery>(`/processes/${encodeURIComponent(processId ?? '')}/rin`),
    enabled: Boolean(processId),
    // While a delivery is retrying, poll: retries are compressed to seconds in dev.
    refetchInterval: (q) => (q.state.data?.status === 'PENDING_SYNC' ? 2000 : false),
  });
}

export function useSendToRin(processId: string, csrf: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (opts: { simulate_failures?: number; force?: boolean }) =>
      apiFetch<RinDelivery>(`/processes/${encodeURIComponent(processId)}/rin/send`, {
        method: 'POST',
        body: JSON.stringify(opts),
        headers: csrf ? { 'X-CSRF-Token': csrf } : {},
      }),
    onSuccess: (data) => client.setQueryData(rinKey(processId), data),
  });
}
