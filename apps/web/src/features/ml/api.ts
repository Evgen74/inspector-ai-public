/** Module 10 client: weekly ML report. */
import { useQuery } from '@tanstack/react-query';
import { apiFetch, toQuery } from '../../api/client';

export interface Bucket {
  confirmed: number;
  rejected: number;
  total: number;
  precision: number | null;
}

export interface MlReport {
  period: { from: string; to: string };
  generated_at: string;
  totals: { decided: number; confirmed: number; rejected: number; clarification: number; precision: number | null; disputes: number };
  by_param: Array<Bucket & { param_code: string; name: string; section: string }>;
  by_section: Array<Bucket & { section: string }>;
  by_reason: Array<{ reason_code: string; label: string; family: string | null; count: number; share: number | null }>;
  trend: Array<{ week_start: string; confirmed: number; rejected: number; precision: number | null }>;
  recommendations: Array<{ severity: 'info' | 'warning'; text: string }>;
}

export function useMlReport(from?: string, to?: string) {
  return useQuery({ queryKey: ['ml-report', from, to], queryFn: () => apiFetch<MlReport>(`/ml/reports/weekly${toQuery({ from, to })}`) });
}

export function reportUrls(from?: string, to?: string): { html: string; json: string } {
  const q = toQuery({ from, to });
  return { html: `/api/v1/ml/reports/weekly.html${q}`, json: `/api/v1/ml/reports/weekly${q}` };
}
