/**
 * Usability instrumentation (ТЗ §9.3 «Критерии юзабилити», 05 §3.18, VER-68). Method (05 §6 C9, published in the
 * help): clicks are counted from «card shown» to «decision committed» on the workspace controls; viewer pan/zoom
 * (inside `[data-viewer]`) and typing are not clicks; hotkeys are counted as keys. The numbers travel with the
 * decision (`client_metrics`) and session events go to POST /telemetry/ui-events in batches.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { newKey, sendUiEvents, type UiEvent } from './api';
import type { ClientMetrics } from './types';

interface Counter {
  findingId: string | null;
  startedAt: number;
  clicks: number;
  keys: number;
}

/** Counts clicks on the workspace (capture phase) and hotkeys for the card on screen. */
export function useCardMetrics(root: React.RefObject<HTMLElement | null>, findingId: string | null) {
  const counter = useRef<Counter>({ findingId, startedAt: performance.now(), clicks: 0, keys: 0 });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    counter.current = { findingId, startedAt: performance.now(), clicks: 0, keys: 0 };
    setTick((t) => t + 1);
  }, [findingId]);

  useEffect(() => {
    const el = root.current;
    if (!el) return undefined;
    const onClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target || target.closest('[data-viewer]')) return;
      if (!target.closest('button, [role="button"], [role="tab"], [role="option"], a, input, textarea, .ant-select, .ant-tag, li')) return;
      counter.current.clicks += 1;
      setTick((t) => t + 1);
    };
    el.addEventListener('click', onClick, true);
    return () => el.removeEventListener('click', onClick, true);
  }, [root]);

  const key = useCallback(() => {
    counter.current.keys += 1;
    setTick((t) => t + 1);
  }, []);

  const snapshot = useCallback((): ClientMetrics => {
    const c = counter.current;
    return {
      time_on_card_ms: Math.max(0, Math.round(performance.now() - c.startedAt)),
      clicks: c.clicks,
      keys: c.keys,
      input: c.clicks === 0 ? 'KEYBOARD' : c.keys === 0 ? 'MOUSE' : 'MIXED',
    };
  }, []);

  return { key, snapshot, clicks: counter.current.clicks, keys: counter.current.keys, startedAt: counter.current.startedAt, tick };
}

/** Batches session events (SESSION_START, CARD_SHOWN, …) and flushes on 20 events, on hide and on unmount. */
export function useUiEvents(pid: string, csrf: string | null | undefined) {
  const sessionId = useMemo(() => newKey(), []);
  const buffer = useRef<UiEvent[]>([]);
  const csrfRef = useRef(csrf);
  csrfRef.current = csrf;

  const flush = useCallback(() => {
    const events = buffer.current.splice(0, buffer.current.length);
    void sendUiEvents(pid, sessionId, events, csrfRef.current);
  }, [pid, sessionId]);

  const track = useCallback(
    (type: string, extra: Partial<UiEvent> = {}) => {
      buffer.current.push({ type, ts_client: new Date().toISOString(), ...extra });
      if (buffer.current.length >= 20) flush();
    },
    [flush],
  );

  useEffect(() => {
    track('SESSION_START');
    const onHide = () => {
      if (document.visibilityState === 'hidden') flush();
    };
    document.addEventListener('visibilitychange', onHide);
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      flush();
    };
  }, [track, flush]);

  return { track, flush, sessionId };
}

/** «0:42» */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
