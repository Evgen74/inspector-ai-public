import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import type { components } from '../../api/schema.gen';

export type MonitoringOverview = components['schemas']['MonitoringOverview'];

export function useMonitoringOverview(logLines: number, refetchMs: number | false) {
  return useQuery({
    queryKey: ['monitoring', logLines],
    queryFn: () => apiFetch<MonitoringOverview>(`/admin/monitoring/overview?log_lines=${logLines}`),
    refetchInterval: refetchMs,
    retry: false,
  });
}
