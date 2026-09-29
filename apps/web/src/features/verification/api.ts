/**
 * Verification API client (AG-05): TanStack Query hooks over AG-08's `apiFetch`, plus the write helper that adds
 * `Idempotency-Key` (one UUID per user action, reused on a retry), `If-Match` (row_version from the card or the
 * summary) and `X-CSRF-Token` (from the session of GET /auth/me).
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { apiFetch, ApiError, setCsrfToken } from '../../api/client';
import type {
  AuthSession,
  CompletenessView,
  DecisionCodes,
  DecisionRequest,
  DecisionResult,
  EvidenceCardView,
  FinalizeResult,
  ObjectVerification,
  ProcessTransition,
  UnfinalizeResult,
  UsabilityReport,
  VerificationQueue,
  VerificationSummary,
} from './types';

const enc = encodeURIComponent;

export const vKeys = {
  me: ['auth', 'me'] as const,
  codes: ['verification', 'codes'] as const,
  object: (objectId: string) => ['verification', 'object', objectId] as const,
  process: (pid: string) => ['verification', pid] as const,
  summary: (pid: string) => ['verification', pid, 'summary'] as const,
  queue: (pid: string) => ['verification', pid, 'queue'] as const,
  card: (pid: string, fid: string) => ['verification', pid, 'card', fid] as const,
  completeness: (pid: string) => ['verification', pid, 'completeness'] as const,
  usability: (pid: string) => ['verification', pid, 'usability'] as const,
};

export function newKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  const hex = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-8${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

export interface WriteOptions {
  ifMatch?: number;
  csrf?: string | null;
  /** Reuse the key when retrying the same user action. */
  key?: string;
}

export function postJson<T>(path: string, body: unknown, opts: WriteOptions = {}): Promise<T> {
  const headers: Record<string, string> = { 'Idempotency-Key': opts.key ?? newKey() };
  if (opts.ifMatch !== undefined) headers['If-Match'] = `"${opts.ifMatch}"`;
  if (opts.csrf) headers['X-CSRF-Token'] = opts.csrf;
  // An operation without a requestBody (e.g. verification/claim) must get no body and no JSON Content-Type (415).
  return apiFetch<T>(path, body === undefined ? { method: 'POST', headers } : { method: 'POST', body: JSON.stringify(body), headers });
}

/** The current session, or null without one (401). */
export function useAuthSession() {
  return useQuery({
    queryKey: vKeys.me,
    queryFn: async () => {
      try {
        const session = await apiFetch<AuthSession>('/auth/me');
        setCsrfToken(session.csrf_token);
        return session;
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          setCsrfToken(null);
          return null;
        }
        throw err;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function hasPermission(session: AuthSession | null | undefined, code: string): boolean {
  return Boolean(session?.permissions.some((p) => p.code === code));
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { login: string; password: string }) => apiFetch<AuthSession>('/auth/login', { method: 'POST', body: JSON.stringify(v) }),
    onSuccess: (session) => {
      setCsrfToken(session.csrf_token);
      client.setQueryData(vKeys.me, session);
      void client.invalidateQueries({ queryKey: ['verification'] });
    },
  });
}

export async function reauthToken(password: string, csrf: string | null | undefined): Promise<string> {
  const headers: Record<string, string> = {};
  if (csrf) headers['X-CSRF-Token'] = csrf;
  const res = await apiFetch<{ reauth_token: string }>('/auth/reauth', { method: 'POST', body: JSON.stringify({ password }), headers });
  return res.reauth_token;
}

export function useObjectVerification(objectId: string) {
  return useQuery({ queryKey: vKeys.object(objectId), queryFn: () => apiFetch<ObjectVerification>(`/objects/${enc(objectId)}/verification`), enabled: Boolean(objectId) });
}

export function useSummary(pid: string) {
  return useQuery({ queryKey: vKeys.summary(pid), queryFn: () => apiFetch<VerificationSummary>(`/processes/${enc(pid)}/verification`), enabled: Boolean(pid) });
}

export function useQueue(pid: string) {
  return useQuery({ queryKey: vKeys.queue(pid), queryFn: () => apiFetch<VerificationQueue>(`/processes/${enc(pid)}/findings`), enabled: Boolean(pid) });
}

export function cardQuery(pid: string, fid: string) {
  return {
    queryKey: vKeys.card(pid, fid),
    queryFn: () => apiFetch<EvidenceCardView>(`/processes/${enc(pid)}/findings/${enc(fid)}`),
    staleTime: 30_000,
  };
}

export function useCard(pid: string, fid: string | null) {
  return useQuery({ ...cardQuery(pid, fid ?? ''), enabled: Boolean(pid && fid) });
}

/** Warm the next card (05 §3.17.2: card switch < 300 ms perceived). */
export function prefetchCard(client: QueryClient, pid: string, fid: string | null | undefined): void {
  if (fid) void client.prefetchQuery(cardQuery(pid, fid));
}

export function useDecisionCodes() {
  return useQuery({ queryKey: vKeys.codes, queryFn: () => apiFetch<DecisionCodes>('/dictionaries/decision-codes'), staleTime: Infinity });
}

export function useCompleteness(pid: string, enabled = true) {
  return useQuery({ queryKey: vKeys.completeness(pid), queryFn: () => apiFetch<CompletenessView>(`/processes/${enc(pid)}/completeness`), enabled: Boolean(pid) && enabled });
}

export function useUsability(pid: string, enabled = true) {
  return useQuery({ queryKey: vKeys.usability(pid), queryFn: () => apiFetch<UsabilityReport>(`/processes/${enc(pid)}/usability`), enabled: Boolean(pid) && enabled });
}

export function postDecision(pid: string, fid: string, body: DecisionRequest, opts: WriteOptions) {
  return postJson<DecisionResult>(`/processes/${enc(pid)}/findings/${enc(fid)}/decisions`, body, opts);
}

export function postDisputeResolution(
  disputeId: number,
  body: { resolution: 'INSPECTOR_UPHELD' | 'AI_UPHELD' | 'KEPT_CLARIFICATION'; comment?: string | null; comment_source?: string | null; seen_fingerprint: string },
  opts: WriteOptions,
) {
  return postJson<DecisionResult>(`/disputes/${disputeId}/resolve`, body, opts);
}

export function postClaim(pid: string, opts: WriteOptions) {
  return postJson<ProcessTransition>(`/processes/${enc(pid)}/verification/claim`, undefined, opts);
}

export function postReopen(pid: string, comment: string | null, opts: WriteOptions) {
  return postJson<ProcessTransition>(`/processes/${enc(pid)}/verification/reopen`, { comment }, opts);
}

export function postFinalize(pid: string, reauth_token: string, opts: WriteOptions) {
  return postJson<FinalizeResult>(`/processes/${enc(pid)}/finalize`, { reauth_token }, opts);
}

export function postUnfinalize(pid: string, body: { reason_code: string; reason_text: string; reauth_token: string }, opts: WriteOptions) {
  return postJson<UnfinalizeResult>(`/processes/${enc(pid)}/unfinalize`, body, opts);
}

export interface UiEvent {
  type: string;
  finding_id?: string | null;
  target?: string | null;
  input?: 'MOUSE' | 'KEYBOARD' | 'MIXED' | null;
  ts_client: string;
  payload?: Record<string, unknown> | null;
}

/** Best-effort telemetry (never blocks or breaks the workspace). */
export async function sendUiEvents(pid: string, sessionId: string, events: UiEvent[], csrf: string | null | undefined): Promise<void> {
  if (!events.length || !csrf) return;
  try {
    await apiFetch('/telemetry/ui-events', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, process_id: pid, events: events.slice(0, 200) }),
      headers: { 'X-CSRF-Token': csrf },
      keepalive: true,
    });
  } catch {
    /* telemetry only */
  }
}

/** Everything of one process is refetched after a write (the server is the source of truth). */
export function invalidateProcess(client: QueryClient, pid: string): Promise<void> {
  return client.invalidateQueries({ queryKey: vKeys.process(pid) });
}
