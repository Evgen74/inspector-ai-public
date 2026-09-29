/**
 * Usability instrumentation (ТЗ §9.3, 05 §3.18): the click/key counters that travel with a decision as
 * `client_metrics`, and the batched session-event sender.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatElapsed, useCardMetrics, useUiEvents } from './telemetry';
import * as api from './api';

describe('formatElapsed', () => {
  it('renders m:ss, floored and zero-padded', () => {
    expect(formatElapsed(0)).toBe('0:00');
    expect(formatElapsed(999)).toBe('0:00');
    expect(formatElapsed(1_000)).toBe('0:01');
    expect(formatElapsed(9_000)).toBe('0:09');
    expect(formatElapsed(65_000)).toBe('1:05');
    expect(formatElapsed(602_000)).toBe('10:02');
  });

  it('never goes negative (clock skew)', () => {
    expect(formatElapsed(-500)).toBe('0:00');
  });
});

describe('useCardMetrics', () => {
  beforeEach(() => {
    vi.spyOn(performance, 'now').mockReturnValue(1_000);
  });
  afterEach(() => vi.restoreAllMocks());

  it('counts a click on a control but not inside the document viewer, and classifies input by the mix', () => {
    const root = document.createElement('div');
    document.body.append(root);
    const button = document.createElement('button');
    button.textContent = 'Подтвердить';
    root.append(button);
    const viewerBtn = document.createElement('button');
    const viewer = document.createElement('div');
    viewer.setAttribute('data-viewer', '');
    viewer.append(viewerBtn);
    root.append(viewer);

    const ref = { current: root };
    const { result, rerender } = renderHook(({ fid }: { fid: string | null }) => useCardMetrics(ref, fid), { initialProps: { fid: 'F1' } });

    expect(result.current.snapshot()).toEqual({ time_on_card_ms: 0, clicks: 0, keys: 0, input: 'KEYBOARD' });

    act(() => vi.spyOn(performance, 'now').mockReturnValue(1_500));
    act(() => button.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    act(() => viewerBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }))); // ignored: inside [data-viewer]
    let snap = result.current.snapshot();
    expect(snap.clicks).toBe(1);
    expect(snap.input).toBe('MOUSE'); // clicks > 0, no keys

    act(() => result.current.key());
    snap = result.current.snapshot();
    expect(snap.keys).toBe(1);
    expect(snap.input).toBe('MIXED'); // both clicks and keys

    // A new finding resets the counter and the clock.
    act(() => vi.spyOn(performance, 'now').mockReturnValue(2_000));
    rerender({ fid: 'F2' });
    snap = result.current.snapshot();
    expect(snap).toEqual({ time_on_card_ms: 0, clicks: 0, keys: 0, input: 'KEYBOARD' });

    root.remove();
  });
});

describe('useUiEvents', () => {
  it('flushes on unmount and sends the buffered events for the process/session, skipping without a CSRF token', () => {
    const spy = vi.spyOn(api, 'sendUiEvents').mockResolvedValue(undefined);
    const { result, unmount } = renderHook(() => useUiEvents('proc-1', 'csrf-tok'));
    act(() => result.current.track('CARD_SHOWN', { finding_id: 'F1' }));
    expect(spy).not.toHaveBeenCalled(); // buffered, not flushed yet (SESSION_START was already sent on mount)
    unmount();
    const calls = spy.mock.calls;
    const last = calls[calls.length - 1]!;
    expect(last[0]).toBe('proc-1');
    expect(last[1]).toBe(result.current.sessionId);
    expect(last[3]).toBe('csrf-tok');
    expect(last[2].some((e) => e.type === 'CARD_SHOWN' && e.finding_id === 'F1')).toBe(true);
    spy.mockRestore();
  });
});
