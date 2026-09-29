/**
 * In-process request metrics (module 11): counters, a latency histogram, a sliding window for rate/p95/5xx and a
 * ring buffer of recent JSON log lines. Rendered in the Prometheus text format by `renderPrometheus()`.
 * No dependency on prom-client: the exposition format is plain text and the process is single-node.
 */
import { Writable } from 'node:stream';

export const LATENCY_BUCKETS_MS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000] as const;
const WINDOW_MS = 5 * 60_000;
const MAX_SAMPLES = 20_000;
const MAX_LOG_LINES = 500;

export interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  event: string | null;
  request_id: string | null;
  raw: Record<string, unknown>;
}

interface Sample {
  t: number;
  ms: number;
  status: number;
}

function escapeLabel(v: string): string {
  return v.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
}

export class MetricsRegistry {
  private readonly startedAt = Date.now();
  private samples: Sample[] = [];
  private readonly byRouteStatus = new Map<string, number>();
  private readonly bucketCounts = new Array<number>(LATENCY_BUCKETS_MS.length + 1).fill(0);
  private durationSumMs = 0;
  private total = 0;
  private logs: LogEntry[] = [];
  /** True when a log stream feeds `pushLogLine` (then the request hook must not duplicate the lines). */
  logTapActive = false;

  recordRequest(method: string, route: string, status: number, ms: number): void {
    const key = `${method}\u0000${route}\u0000${status}`;
    this.byRouteStatus.set(key, (this.byRouteStatus.get(key) ?? 0) + 1);
    let i = LATENCY_BUCKETS_MS.findIndex((b) => ms <= b);
    if (i === -1) i = LATENCY_BUCKETS_MS.length;
    this.bucketCounts[i] = (this.bucketCounts[i] ?? 0) + 1;
    this.durationSumMs += ms;
    this.total += 1;
    const now = Date.now();
    this.samples.push({ t: now, ms, status });
    if (this.samples.length > MAX_SAMPLES) this.samples = this.samples.slice(-MAX_SAMPLES / 2);
  }

  /** Window statistics over the last `windowMs` (default 5 minutes). */
  window(windowMs = WINDOW_MS): { requests: number; rate_per_min: number; p95_ms: number | null; p50_ms: number | null; errors_5xx: number; errors_4xx: number } {
    const since = Date.now() - windowMs;
    const inWindow = this.samples.filter((s) => s.t >= since);
    const sorted = inWindow.map((s) => s.ms).sort((a, b) => a - b);
    const q = (p: number) => (sorted.length ? (sorted[Math.min(sorted.length - 1, Math.ceil(p * sorted.length) - 1)] ?? null) : null);
    const minutes = Math.min(windowMs, Date.now() - this.startedAt) / 60_000;
    return {
      requests: inWindow.length,
      rate_per_min: minutes > 0 ? Math.round((inWindow.length / minutes) * 10) / 10 : 0,
      p95_ms: q(0.95) === null ? null : Math.round(q(0.95)!),
      p50_ms: q(0.5) === null ? null : Math.round(q(0.5)!),
      errors_5xx: inWindow.filter((s) => s.status >= 500).length,
      errors_4xx: inWindow.filter((s) => s.status >= 400 && s.status < 500).length,
    };
  }

  totals(): { requests: number; errors_5xx: number; uptime_s: number } {
    let e5 = 0;
    for (const [k, v] of this.byRouteStatus) if (Number(k.split('\u0000')[2]) >= 500) e5 += v;
    return { requests: this.total, errors_5xx: e5, uptime_s: Math.round((Date.now() - this.startedAt) / 1000) };
  }

  pushLogLine(line: string): void {
    let raw: Record<string, unknown>;
    try {
      raw = JSON.parse(line) as Record<string, unknown>;
    } catch {
      return;
    }
    const str = (v: unknown) => (typeof v === 'string' ? v : null);
    this.logs.push({
      timestamp: str(raw.timestamp) ?? new Date().toISOString(),
      level: str(raw.level) ?? 'info',
      message: str(raw.message) ?? str(raw.msg) ?? '',
      event: str(raw.event),
      request_id: str(raw.request_id),
      raw,
    });
    if (this.logs.length > MAX_LOG_LINES) this.logs = this.logs.slice(-MAX_LOG_LINES);
  }

  recentLogs(limit: number): LogEntry[] {
    return this.logs.slice(-Math.max(1, Math.min(limit, MAX_LOG_LINES))).reverse();
  }

  /** Writable that tees newline-delimited JSON into the ring buffer (no output of its own). */
  logTap(): Writable {
    this.logTapActive = true;
    let pending = '';
    return new Writable({
      write: (chunk: Buffer | string, _enc, cb) => {
        pending += chunk.toString();
        let nl = pending.indexOf('\n');
        while (nl !== -1) {
          this.pushLogLine(pending.slice(0, nl));
          pending = pending.slice(nl + 1);
          nl = pending.indexOf('\n');
        }
        if (pending.length > 1_000_000) pending = '';
        cb();
      },
    });
  }

  renderPrometheus(extra: Array<{ name: string; help: string; type: 'gauge' | 'counter'; value: number; labels?: Record<string, string> }> = []): string {
    const out: string[] = [];
    out.push('# HELP inspector_http_requests_total Число HTTP-запросов API.');
    out.push('# TYPE inspector_http_requests_total counter');
    for (const [k, v] of [...this.byRouteStatus].sort()) {
      const [method, route, status] = k.split('\u0000');
      out.push(`inspector_http_requests_total{method="${method}",route="${escapeLabel(route ?? '')}",status="${status}"} ${v}`);
    }
    out.push('# HELP inspector_http_request_duration_ms Длительность HTTP-запросов, мс.');
    out.push('# TYPE inspector_http_request_duration_ms histogram');
    let cumulative = 0;
    LATENCY_BUCKETS_MS.forEach((b, i) => {
      cumulative += this.bucketCounts[i] ?? 0;
      out.push(`inspector_http_request_duration_ms_bucket{le="${b}"} ${cumulative}`);
    });
    cumulative += this.bucketCounts[LATENCY_BUCKETS_MS.length] ?? 0;
    out.push(`inspector_http_request_duration_ms_bucket{le="+Inf"} ${cumulative}`);
    out.push(`inspector_http_request_duration_ms_sum ${Math.round(this.durationSumMs * 1000) / 1000}`);
    out.push(`inspector_http_request_duration_ms_count ${this.total}`);
    out.push('# HELP inspector_uptime_seconds Время работы процесса API.');
    out.push('# TYPE inspector_uptime_seconds gauge');
    out.push(`inspector_uptime_seconds ${this.totals().uptime_s}`);
    const seen = new Set<string>();
    for (const m of extra) {
      if (!seen.has(m.name)) {
        out.push(`# HELP ${m.name} ${m.help}`);
        out.push(`# TYPE ${m.name} ${m.type}`);
        seen.add(m.name);
      }
      const labels = m.labels
        ? `{${Object.entries(m.labels)
            .map(([k, v]) => `${k}="${escapeLabel(v)}"`)
            .join(',')}}`
        : '';
      out.push(`${m.name}${labels} ${m.value}`);
    }
    return `${out.join('\n')}\n`;
  }
}

/** One registry per process (the Fastify hooks and the service share it). */
export const metricsRegistry = new MetricsRegistry();
