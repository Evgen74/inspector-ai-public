/**
 * Usability report (ТЗ §9.3 «Критерии юзабилити», §11 #15; 05 §3.18, VER-65/66/68). Method (05 §6 C9):
 * clicks are counted from «card shown» to «decision committed» (navigation is automatic, typing is not a
 * click, hotkeys are counted separately as keys); protocol time runs from the first card shown (or the first
 * decision) to finalization (or the last decision while the protocol is open).
 */

export const TARGET_PROTOCOL_MINUTES = 30;
export const TARGET_CLICKS_PER_DECISION = 3;

export interface MetricDecision {
  decidedAt: Date;
  userId: string;
  decision: string;
  metrics: { time_on_card_ms?: number; clicks?: number; keys?: number; input?: string } | null;
}

export interface MetricEvent {
  type: string;
  tsClient: Date;
  userId: string;
}

export interface Distribution {
  n: number;
  mean: number | null;
  median: number | null;
  p90: number | null;
  max: number | null;
}

export interface UsabilityReport {
  decisions: number;
  measured_decisions: number;
  clicks: Distribution & { share_within_target: number | null };
  keys: Distribution;
  keyboard_only_share: number | null;
  time_on_card_ms: Distribution;
  protocol_time_ms: number | null;
  active_time_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
  inspectors: number;
  targets: { protocol_minutes: number; clicks_per_decision: number };
  met: { protocol_time: boolean | null; clicks: boolean | null };
}

function quantile(sorted: number[], q: number): number | null {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return Math.round((sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (pos - lo)) * 100) / 100;
}

export function distribution(values: number[]): Distribution {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return { n: 0, mean: null, median: null, p90: null, max: null };
  const mean = Math.round((v.reduce((s, x) => s + x, 0) / v.length) * 100) / 100;
  return { n: v.length, mean, median: quantile(v, 0.5), p90: quantile(v, 0.9), max: v.at(-1)! };
}

export function usabilityReport(decisions: MetricDecision[], events: MetricEvent[], finalizedAt: Date | null): UsabilityReport {
  const measured = decisions.filter((d) => d.metrics && (d.metrics.clicks !== undefined || d.metrics.time_on_card_ms !== undefined));
  const clicks = measured.map((d) => d.metrics!.clicks ?? 0);
  const keys = measured.map((d) => d.metrics!.keys ?? 0);
  const times = measured.map((d) => d.metrics!.time_on_card_ms).filter((t): t is number => typeof t === 'number');
  const starts = [
    ...events.filter((e) => e.type === 'SESSION_START' || e.type === 'CARD_SHOWN').map((e) => e.tsClient.getTime()),
    ...decisions.map((d) => d.decidedAt.getTime() - (d.metrics?.time_on_card_ms ?? 0)),
  ];
  const start = starts.length ? Math.min(...starts) : null;
  const end = finalizedAt ? finalizedAt.getTime() : decisions.length ? Math.max(...decisions.map((d) => d.decidedAt.getTime())) : null;
  const protocolTime = start !== null && end !== null && end >= start ? end - start : null;
  const clickDist = distribution(clicks);
  const within = clicks.length ? Math.round((clicks.filter((c) => c <= TARGET_CLICKS_PER_DECISION).length / clicks.length) * 1000) / 1000 : null;
  const keyboardOnly = measured.length ? Math.round((measured.filter((d) => (d.metrics!.clicks ?? 0) === 0).length / measured.length) * 1000) / 1000 : null;
  return {
    decisions: decisions.length,
    measured_decisions: measured.length,
    clicks: { ...clickDist, share_within_target: within },
    keys: distribution(keys),
    keyboard_only_share: keyboardOnly,
    time_on_card_ms: distribution(times),
    protocol_time_ms: protocolTime,
    active_time_ms: times.length ? times.reduce((s, t) => s + t, 0) : null,
    started_at: start !== null ? new Date(start).toISOString() : null,
    finished_at: end !== null ? new Date(end).toISOString() : null,
    inspectors: new Set(decisions.map((d) => d.userId)).size,
    targets: { protocol_minutes: TARGET_PROTOCOL_MINUTES, clicks_per_decision: TARGET_CLICKS_PER_DECISION },
    met: {
      protocol_time: protocolTime === null ? null : protocolTime <= TARGET_PROTOCOL_MINUTES * 60_000,
      clicks: clickDist.max === null ? null : clickDist.max <= TARGET_CLICKS_PER_DECISION,
    },
  };
}
