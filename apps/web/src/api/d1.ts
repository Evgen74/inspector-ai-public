/**
 * D1 endpoints (dashboard, protocols, page annotations): response types come from the generated OpenAPI types
 * (schema.gen.ts); the protocol and finding groups inside ProtocolView follow the contract JSON Schemas
 * (src/contracts/protocol.ts). Query keys follow 08 §3.7.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import type { FindingGroup, Protocol } from '../contracts/protocol';
import { withPartialDecisions, type GroupProgress } from '../features/protocol/partialDecisions';
import { API_BASE, apiFetch, toQuery } from './client';
import type { components } from './schema.gen';

type S = components['schemas'];
export type Dashboard = S['Dashboard'];
export type DashboardObject = S['DashboardObject'];
export type DashboardTiles = S['DashboardTiles'];
export type SectionSummary = S['SectionSummary'];
export type Indicator = S['Indicator'];
export type IndicatorColor = S['IndicatorColor'];
export type FindingCounters = S['FindingCounters'];
export type ProtocolVersion = S['ProtocolVersion'];
export type ProtocolVersionList = S['ProtocolVersionList'];
export type ProtocolFileFormat = S['ProtocolFileFormat'];
export type PageAnnotations = S['PageAnnotations'];

export interface ProtocolView extends Omit<S['ProtocolView'], 'protocol' | 'finding_groups'> {
  protocol: Protocol;
  finding_groups: FindingGroup[];
}

export interface DashboardFilter {
  q?: string;
  color?: string[];
  section?: string[];
  status?: string[];
  scenario?: string;
  dateFrom?: string;
  dateTo?: string;
}

const csv = (v?: string[]) => (v && v.length ? v.join(',') : undefined);

export function dashboardQuery(f: DashboardFilter): string {
  return toQuery({
    q: f.q,
    color: csv(f.color),
    section: csv(f.section),
    status: csv(f.status),
    scenario: f.scenario,
    date_from: f.dateFrom,
    date_to: f.dateTo,
  });
}

export function useDashboard(filter: DashboardFilter) {
  return useQuery({
    queryKey: ['dashboard', filter],
    queryFn: () => apiFetch<Dashboard>(`/dashboard${dashboardQuery(filter)}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}

export function useProtocolVersions(objectId: string, enabled = true) {
  return useQuery({
    queryKey: ['protocols', objectId],
    queryFn: () => apiFetch<ProtocolVersionList>(`/objects/${encodeURIComponent(objectId)}/protocols`),
    enabled: enabled && objectId.length > 0,
  });
}

export function useProtocol(objectId: string, runId: string) {
  return useQuery({
    queryKey: ['protocol', objectId, runId],
    queryFn: () =>
      apiFetch<ProtocolView>(`/objects/${encodeURIComponent(objectId)}/protocols/${encodeURIComponent(runId)}`),
    enabled: objectId.length > 0 && runId.length > 0,
    staleTime: 60_000,
    select: (v) => ({ ...v, protocol: withPartialDecisions(v.protocol, v.protocol.ext?.decision_progress as Record<string, GroupProgress> | undefined) }),
  });
}

export function usePageAnnotations(fileId: string, page: number, enabled = true) {
  return useQuery({
    queryKey: ['annotations', fileId, page],
    queryFn: () => apiFetch<PageAnnotations>(`/files/${encodeURIComponent(fileId)}/annotations${toQuery({ page })}`),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

/** Direct download link (browser handles Content-Disposition; the API streams AG-04's file). */
export function exportUrl(objectId: string, runId: string, format: ProtocolFileFormat): string {
  return `${API_BASE}/objects/${encodeURIComponent(objectId)}/protocols/${encodeURIComponent(runId)}/export?format=${format}`;
}
