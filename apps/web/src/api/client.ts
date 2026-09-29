/**
 * Thin fetch client for /api/v1. Every call carries an X-Request-Id; errors become ApiError with the
 * server's RFC 9457 problem (Russian title/detail) so the UI can show «Код обращения».
 */
import type { Problem } from './types';

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem | null,
    readonly requestId: string,
  ) {
    super(problem?.detail ?? `HTTP ${status}`);
    this.name = 'ApiError';
  }

  get title(): string {
    if (this.status === 0) return 'Сервер недоступен';
    return this.problem?.title ?? `Ошибка ${this.status}`;
  }

  get detail(): string {
    if (this.status === 0) return 'Не удалось связаться с API. Проверьте, что сервер запущен (make api-dev).';
    return this.problem?.detail ?? 'Сервер вернул неожиданный ответ.';
  }
}

/** Same-origin absolute URL (relative in the browser would be equivalent; Node's fetch in tests needs a base). */
export function apiUrl(path: string): string {
  const origin = typeof window !== 'undefined' ? window.location?.origin : undefined;
  return origin && origin !== 'null' ? new URL(`${API_BASE}${path}`, origin).toString() : `${API_BASE}${path}`;
}

function newRequestId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `web-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const requestId = newRequestId();
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json, application/problem+json');
  headers.set('X-Request-Id', requestId);
  // FormData: the browser sets multipart/form-data with its boundary.
  if (init.body !== undefined && !headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  let res: Response;
  try {
    res = await fetch(apiUrl(path), { ...init, headers });
  } catch {
    throw new ApiError(0, null, requestId);
  }
  const returnedId = res.headers.get('X-Request-Id') ?? requestId;
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const problem = body && typeof body === 'object' && 'code' in body ? (body as Problem) : null;
    throw new ApiError(res.status, problem, problem?.request_id ?? returnedId);
  }
  return body as T;
}

export function toQuery(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}
