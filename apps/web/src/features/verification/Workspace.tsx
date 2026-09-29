/**
 * Verification workspace (ТЗ §9.3; 05 §3.17): a keyboard-first queue on the left, AG-08's EvidenceViewer (ПД blue /
 * РД red panes zoomed to the fragments) in the centre, the evidence card with the three actions on the right.
 * After a decision the next unprocessed card opens by itself; completeness lives on its own tab; finalization and
 * un-finalization are dialogs; a stopwatch with the click counter (T) proves the ≤ 3 clicks / ≤ 30 min criteria.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Badge, Breadcrumb, Button, Dropdown, Empty, Flex, Progress, Result, Segmented, Skeleton, Space, Tag, Tooltip, Typography } from 'antd';
import { EllipsisOutlined, FieldTimeOutlined, KeyOutlined, ReloadOutlined, UnlockOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { ApiError } from '../../api/client';
import { ProblemAlert } from '../../components/ProblemAlert';
import { enumLabel } from '../../contracts/enums';
import { compareSummary } from './compareSummary';
import { EvidenceViewer } from '../evidence/EvidenceViewer';
import {
  cardQuery,
  hasPermission,
  invalidateProcess,
  newKey,
  postDecision,
  postDisputeResolution,
  postReopen,
  prefetchCard,
  useAuthSession,
  useCard,
  useDecisionCodes,
  useQueue,
  useSummary,
  vKeys,
} from './api';
import { CardPanel, DisputeBanner, STATUS_MARK, StatusTag } from './CardPanel';
import { type DecisionDraft, DecisionPanel, type DecisionPanelHandle, type Panel } from './DecisionPanel';
import { FinalizeDialog, FinalizedBanner, HelpModal, LoginPanel, UnfinalizeDialog } from './Dialogs';
import { hotkeyOf } from './hotkeys';
import { CompletenessPanel, UsabilityPanel } from './Panels';
import { formatElapsed, useCardMetrics, useUiEvents } from './telemetry';
import type { DecisionResult, EvidenceCardView, QueueItem, QueueTab } from './types';

const FILTERS: Array<{ value: QueueTab; label: string }> = [
  { value: 'ALL', label: 'Все' },
  { value: 'PENDING', label: 'Ожидают' },
  { value: 'CLARIFICATION', label: 'Уточнение' },
  { value: 'CONFIRMED', label: 'Подтверждено' },
  { value: 'NEGATIVE', label: 'Отклонено' },
  { value: 'DISPUTES', label: 'Споры' },
];

const MATCH: Record<QueueTab, (q: QueueItem) => boolean> = {
  ALL: () => true,
  PENDING: (q) => q.inspector_status === 'PENDING',
  CLARIFICATION: (q) => q.inspector_status === 'CLARIFICATION_REQUIRED',
  CONFIRMED: (q) => q.inspector_status === 'CONFIRMED_VIOLATION',
  NEGATIVE: (q) => q.inspector_status === 'NEGATIVE_VERIFIED',
  DISPUTES: (q) => q.has_open_dispute,
};

function QueueList({ items, selected, onSelect }: { items: QueueItem[]; selected: string | null; onSelect(fid: string): void }) {
  const active = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    // Newer browsers return a Promise from scrollIntoView; an effect must return nothing or a cleanup function.
    void active.current?.scrollIntoView?.({ block: 'nearest' });
  }, [selected]);
  if (!items.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Нет карточек" />;
  return (
    <ul role="listbox" aria-label="Очередь находок" style={{ listStyle: 'none', margin: 0, padding: 0, overflowY: 'auto' }} data-testid="queue">
      {items.map((q) => {
        const on = q.finding_id === selected;
        const mark = q.has_open_dispute ? '⚖️' : (STATUS_MARK[q.inspector_status ?? '']?.text.split(' ')[0] ?? '·');
        return (
          <li
            key={q.finding_id}
            ref={on ? active : undefined}
            role="option"
            aria-selected={on}
            data-finding={q.finding_id}
            data-status={q.inspector_status ?? ''}
            onClick={() => onSelect(q.finding_id)}
            style={{
              cursor: 'pointer',
              padding: '7px 10px',
              borderLeft: `3px solid ${on ? '#1F4E8C' : 'transparent'}`,
              background: on ? '#eef3fa' : undefined,
              borderBottom: '1px solid #f0f0f0',
            }}
          >
            <Flex justify="space-between" gap={6}>
              <Typography.Text strong style={{ fontSize: 12.5 }}>
                {mark} {q.card_no ?? ''} · {q.param_code}
              </Typography.Text>
              {q.criticality_level === 'CRITICAL_SUSPEND' ? <Tag color="volcano" style={{ marginInlineEnd: 0, fontSize: 11 }}>крит.</Tag> : <Tag style={{ marginInlineEnd: 0, fontSize: 11 }}>сущ.</Tag>}
            </Flex>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {q.location_type === 'OBJECT' || q.location === 'OBJECT' ? 'объект в целом' : `${q.location_type === 'ROOM' ? 'пом. ' : ''}${q.location}`} · {q.parameter_label.replace(/\s*\([^)]*\)\s*$/, '')}
            </Typography.Text>
          </li>
        );
      })}
    </ul>
  );
}

function Meter({ startedAt, clicks, keys }: { startedAt: number; clicks: number; keys: number }) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(performance.now()), 500);
    return () => window.clearInterval(t);
  }, []);
  return (
    <Tag color={clicks > 3 ? 'red' : 'blue'} icon={<FieldTimeOutlined />} data-testid="meter" style={{ marginInlineEnd: 0 }}>
      {formatElapsed(now - startedAt)} · клики: {clicks} · клавиши: {keys}
    </Tag>
  );
}

export interface WorkspaceProps {
  pid: string;
  findingId: string | null;
  onSelect(fid: string | null, replace?: boolean): void;
}

export function Workspace({ pid, findingId, onSelect }: WorkspaceProps) {
  const client = useQueryClient();
  const { message, modal } = App.useApp();
  const session = useAuthSession();
  const summary = useSummary(pid);
  const queue = useQueue(pid);
  const codes = useDecisionCodes();
  const [view, setView] = useState<'queue' | 'completeness' | 'usability'>('queue');
  const [filter, setFilter] = useState<QueueTab>('ALL');
  const [panel, setPanel] = useState<Panel>(null);
  const [busy, setBusy] = useState(false);
  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [unfinalizeOpen, setUnfinalizeOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [meter, setMeter] = useState(false);
  const [writeError, setWriteError] = useState<unknown>(null);
  const lastDecision = useRef<{ fid: string; at: number } | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const decisionRef = useRef<DecisionPanelHandle>(null);

  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);
  const selected = findingId ?? summary.data?.next_finding_id ?? items[0]?.finding_id ?? null;
  const card = useCard(pid, selected);
  const csrf = session.data?.csrf_token ?? null;
  const ui = useUiEvents(pid, csrf);
  const metrics = useCardMetrics(root, card.data?.finding_id ?? null);
  const s = summary.data;

  useEffect(() => {
    setPanel(null);
    setWriteError(null);
  }, [selected]);

  useEffect(() => {
    const c = card.data;
    if (!c) return;
    ui.track('CARD_SHOWN', { finding_id: c.finding_id });
    prefetchCard(client, pid, c.navigation.next_finding_id);
    prefetchCard(client, pid, c.navigation.next_pending_finding_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.data?.finding_id]);

  const reviewable = Boolean(card.data && card.data.statuses.inspector_status !== null && card.data.statuses.lifecycle_state === 'ACTIVE');
  const mayDecide = hasPermission(session.data, 'finding.decide');
  const disabledReason = !session.data
    ? 'Войдите, чтобы принимать решения'
    : !mayDecide
      ? 'У вас нет права принимать решения по находкам'
      : s?.status === 'FINALIZED'
        ? 'Протокол финализирован — изменения невозможны'
        : s?.status === 'COMPLETED'
          ? 'Верификация завершена: чтобы изменить решение, нажмите «Возобновить верификацию»'
          : !reviewable
            ? 'Эта строка не требует решения инспектора'
            : null;
  const canDecide = disabledReason === null && (s?.status === 'READY' || s?.status === 'VERIFYING');

  const refresh = useCallback(() => invalidateProcess(client, pid), [client, pid]);

  const goNext = useCallback(
    (fid: string | null | undefined) => {
      if (fid) onSelect(fid);
    },
    [onSelect],
  );

  const afterDecision = useCallback(
    (res: DecisionResult, label: string) => {
      lastDecision.current = { fid: res.finding.finding_id, at: Date.now() };
      ui.track('DECISION_COMMITTED', { finding_id: res.finding.finding_id, payload: { decision: res.decision.decision, effective_status: res.decision.effective_status } });
      client.setQueryData(vKeys.queue(pid), (old: typeof queue.data) =>
        old ? { ...old, items: old.items.map((q) => (q.finding_id === res.finding.finding_id ? { ...res.finding, position: q.position } : q)) } : old,
      );
      void refresh();
      if (res.ai?.verdict === 'DISAGREE') {
        message.warning({ content: `${res.ai.comment} Запись переведена в «Требует уточнения» до повторного решения.`, duration: 8 });
        return;
      }
      message.success({
        content: (
          <span>
            {label} · {res.finding.location}
            {res.ai ? ` · ${res.ai.comment.split('.')[0]}` : ''}{' '}
            <Typography.Text type="secondary">(Ctrl+Z — отменить)</Typography.Text>
          </span>
        ),
        duration: 3,
      });
      if (res.process.status === 'COMPLETED') {
        message.info('Все кандидаты обработаны — можно завершить верификацию.');
      }
      goNext(res.next_finding_id);
    },
    [client, pid, refresh, message, goNext, ui],
  );

  const handleWriteError = useCallback(
    async (err: unknown, retry: (overrideOf: string | null) => void) => {
      if (err instanceof ApiError && err.problem?.code === 'VERSION_CONFLICT') {
        const details = (err.problem.details ?? {}) as { decision_id?: string | null };
        await refresh();
        modal.confirm({
          title: 'Решение по карточке уже принято',
          content: err.problem.detail,
          okText: 'Заменить своим решением',
          cancelText: 'Принять и перейти далее',
          onOk: () => retry(details.decision_id ?? null),
          onCancel: () => goNext(card.data?.navigation.next_pending_finding_id),
        });
        return;
      }
      if (err instanceof ApiError && err.problem?.code === 'EVIDENCE_CHANGED') {
        await refresh();
        message.warning(err.problem.detail);
        return;
      }
      if (err instanceof ApiError && err.status === 401) void client.invalidateQueries({ queryKey: vKeys.me });
      setWriteError(err);
    },
    [refresh, modal, goNext, card.data, message, client],
  );

  const submitDecision = useCallback(
    async (draft: DecisionDraft, overrideOf: string | null = null, target: EvidenceCardView | undefined = card.data) => {
      if (!target || busy) return;
      setBusy(true);
      setWriteError(null);
      const key = newKey();
      try {
        const res = await postDecision(
          pid,
          target.finding_id,
          { ...draft, seen_fingerprint: target.evidence_fingerprint, client_metrics: metrics.snapshot(), ...(overrideOf ? { override_of_decision_id: overrideOf } : {}) },
          { ifMatch: target.row_version, csrf, key },
        );
        const label = draft.decision === 'CONFIRMED_VIOLATION' ? '✅ Подтверждено' : draft.decision === 'NEGATIVE_VERIFIED' ? '❌ Отклонено' : draft.decision === 'CLARIFICATION_REQUIRED' ? '❓ Требует уточнения' : '↩ Решение отменено';
        setPanel(null);
        afterDecision(res, label);
      } catch (err) {
        // «Заменить своим решением»: the fresh card (new row_version) + override_of_decision_id → DECISION_OVERRIDE.
        await handleWriteError(err, (id) => {
          void client.fetchQuery({ ...cardQuery(pid, target.finding_id), staleTime: 0 }).then((again) => submitDecisionRef.current(draft, id, again));
        });
      } finally {
        setBusy(false);
      }
    },
    [card.data, busy, client, pid, metrics, csrf, afterDecision, handleWriteError],
  );
  const submitDecisionRef = useRef(submitDecision);
  submitDecisionRef.current = submitDecision;

  const resolveDispute = useCallback(
    async (resolution: 'INSPECTOR_UPHELD' | 'AI_UPHELD' | 'KEPT_CLARIFICATION', comment: string | null) => {
      const c = card.data;
      if (!c?.open_dispute) return;
      setBusy(true);
      setWriteError(null);
      try {
        const res = await postDisputeResolution(
          c.open_dispute.dispute_id,
          { resolution, comment, comment_source: comment ? 'MANUAL' : null, seen_fingerprint: c.evidence_fingerprint },
          { ifMatch: c.row_version, csrf, key: newKey() },
        );
        afterDecision(res, resolution === 'AI_UPHELD' ? '✅ Подтверждено' : resolution === 'INSPECTOR_UPHELD' ? '❌ Отклонено' : '❓ Требует уточнения');
      } catch (err) {
        await handleWriteError(err, () => undefined);
      } finally {
        setBusy(false);
      }
    },
    [card.data, csrf, afterDecision, handleWriteError],
  );

  const undo = useCallback(async () => {
    const last = lastDecision.current;
    if (!last || Date.now() - last.at > (codes.data?.limits.undo_window_ms ?? 10_000)) {
      message.info('Отменить можно только последнее решение в течение 10 секунд.');
      return;
    }
    lastDecision.current = null;
    const target = await client.fetchQuery({ ...cardQuery(pid, last.fid), staleTime: 0 });
    onSelect(last.fid);
    ui.track('DECISION_REVERTED', { finding_id: last.fid });
    await submitDecision({ decision: 'REVERT_TO_PENDING' }, null, target);
  }, [codes.data, client, pid, onSelect, submitDecision, message, ui]);

  const move = useCallback(
    (delta: 1 | -1) => {
      const visible = items.filter(MATCH[filter]);
      const i = visible.findIndex((q) => q.finding_id === selected);
      const next = visible[Math.min(visible.length - 1, Math.max(0, (i < 0 ? -1 : i) + delta))];
      if (next) onSelect(next.finding_id);
    },
    [items, filter, selected, onSelect],
  );

  // Keyboard-first (05 §3.17.3).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (finalizeOpen || unfinalizeOpen) return;
      const hk = hotkeyOf(e);
      if (!hk) return;
      if (helpOpen && hk.action !== 'ESCAPE' && hk.action !== 'HELP') return;
      const count = () => metrics.key();
      switch (hk.action) {
        case 'CONFIRM':
          if (canDecide) {
            count();
            setPanel('confirm');
            e.preventDefault();
          }
          break;
        case 'CONFIRM_NOW':
          if (canDecide && card.data) {
            count();
            e.preventDefault();
            void submitDecision({ decision: 'CONFIRMED_VIOLATION', basis_code: card.data.prefill.confirm_basis_code, comment: card.data.prefill.confirm_comment, comment_source: 'TEMPLATE' });
          }
          break;
        case 'REJECT':
          if (canDecide) {
            count();
            setPanel('reject');
            e.preventDefault();
          }
          break;
        case 'CLARIFY':
          if (canDecide) {
            count();
            setPanel('clarify');
            e.preventDefault();
          }
          break;
        case 'DIGIT':
          if (panel === 'reject' || panel === 'clarify') {
            count();
            decisionRef.current?.pickDigit(hk.digit!);
            e.preventDefault();
          }
          break;
        case 'SUBMIT':
          if (panel) {
            count();
            decisionRef.current?.submit();
            e.preventDefault();
          }
          break;
        case 'ESCAPE':
          if (helpOpen) setHelpOpen(false);
          else setPanel(null);
          break;
        case 'NEXT':
          e.preventDefault();
          move(1);
          break;
        case 'PREV':
          e.preventDefault();
          move(-1);
          break;
        case 'NEXT_PENDING':
          goNext(card.data?.navigation.next_pending_finding_id);
          break;
        case 'UNDO':
          e.preventDefault();
          void undo();
          break;
        case 'HELP':
          e.preventDefault();
          setHelpOpen((v) => !v);
          ui.track('HOTKEY_HELP_OPENED');
          break;
        case 'METER':
          setMeter((v) => !v);
          break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [canDecide, card.data, panel, move, goNext, undo, submitDecision, metrics, helpOpen, finalizeOpen, unfinalizeOpen, ui]);

  const processAction = async (kind: 'reopen') => {
    if (!s) return;
    setBusy(true);
    try {
      if (kind === 'reopen') await postReopen(pid, 'Возобновление верификации для изменения решения', { ifMatch: s.row_version, csrf });
      await refresh();
    } catch (err) {
      setWriteError(err);
    } finally {
      setBusy(false);
    }
  };

  if (summary.isPending || queue.isPending || codes.isPending) return <Skeleton active style={{ padding: 24 }} />;
  if (summary.error) {
    return (
      <Flex vertical gap={12} style={{ padding: 24 }}>
        <ProblemAlert error={summary.error} />
        {summary.error instanceof ApiError && summary.error.status === 401 && <LoginPanel />}
      </Flex>
    );
  }
  if (queue.error || codes.error) return <ProblemAlert error={queue.error ?? codes.error} />;
  if (!s || !codes.data) return null;

  const uploadLabel = (k: 'pd' | 'rd' | 'id') => {
    const code = s.upload_status?.[k];
    return code ? enumLabel('StageUploadStatus', code) : `${k === 'pd' ? 'ПД' : k === 'rd' ? 'РД' : 'ИД'}: —`;
  };
  const decided = s.counts.reviewable - s.counts.pending;
  const visible = items.filter(MATCH[filter]);
  const counts = queue.data?.counts;

  return (
    <div ref={root} style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px)', minHeight: 560 }} data-testid="verification-workspace">
      <Flex vertical gap={8} style={{ padding: '10px 16px', background: '#fff', borderBottom: '1px solid #eef0f3' }}>
        <Flex justify="space-between" align="center" wrap gap={8}>
          <Flex vertical gap={2}>
            <Breadcrumb
              items={[
                { title: <Link to="/verification">Верификация</Link> },
                { title: <Link to={`/objects/${encodeURIComponent(s.object.object_id)}`}>{s.object.name ?? s.object.object_id}</Link> },
                { title: `Протокол ${s.protocol?.protocol_no ?? ''} · версия ${s.protocol?.version ?? '—'}` },
              ]}
            />
            <Space size={8} wrap>
              <Tag color={s.status === 'FINALIZED' ? 'green' : s.status === 'COMPLETED' ? 'cyan' : 'orange'} data-testid="status-line">
                {s.status_line}
              </Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Тип проверки: {s.scenario ? enumLabel('LoadScenario', s.scenario) : (s.scenario_ru ?? '—')} · {uploadLabel('pd')} · {uploadLabel('rd')} · {uploadLabel('id')} · матрица {s.versions.matrix_version ?? '—'}
              </Typography.Text>
            </Space>
          </Flex>
          <Space wrap>
            <Tooltip title="Обработано кандидатов (подтверждено, отклонено или переведено в уточнение)">
              <Progress type="line" size="small" style={{ width: 170, margin: 0 }} percent={s.counts.reviewable ? Math.round((decided / s.counts.reviewable) * 100) : 100} format={() => `${decided} / ${s.counts.reviewable}`} />
            </Tooltip>
            {s.counts.disputes_open > 0 && <Badge count={s.counts.disputes_open} title="Открытые споры с ИИ"><Tag color="gold">споры</Tag></Badge>}
            {/* Status machine: READY/VERIFYING → «Завершить»; COMPLETED → «Финализировать» (reopen is a secondary action). */}
            {s.status === 'COMPLETED' && s.capabilities.can_reopen && (
              <Dropdown
                trigger={['click']}
                menu={{ items: [{ key: 'reopen', icon: <ReloadOutlined />, label: 'Возобновить верификацию', onClick: () => void processAction('reopen') }] }}
              >
                <Button size="small" icon={<EllipsisOutlined />} aria-label="Ещё" loading={busy} />
              </Dropdown>
            )}
            {s.status !== 'FINALIZED' && hasPermission(session.data, 'protocol.finalize') && (
              <Button type="primary" size="small" onClick={() => { setFinalizeOpen(true); ui.track('FINALIZE_OPENED'); }} data-testid="open-finalize">
                {s.status === 'COMPLETED' ? 'Финализировать протокол' : 'Завершить'}
              </Button>
            )}
            {s.capabilities.can_unfinalize && (
              <Button size="small" danger icon={<UnlockOutlined />} onClick={() => setUnfinalizeOpen(true)}>
                Отменить финализацию
              </Button>
            )}
            {meter && card.data && <Meter startedAt={metrics.startedAt} clicks={metrics.clicks} keys={metrics.keys} />}
            <Tooltip title="Клавиши (?)">
              <Button size="small" icon={<KeyOutlined />} onClick={() => setHelpOpen(true)} aria-label="Клавиши" />
            </Tooltip>
          </Space>
        </Flex>
        {!session.data && !session.isPending && <LoginPanel />}
        {s.status === 'FINALIZED' && <FinalizedBanner summary={s} />}
        {writeError ? <ProblemAlert error={writeError} /> : null}
      </Flex>
      <Flex style={{ flex: 1, minHeight: 0 }}>
        <Flex vertical style={{ width: 340, borderRight: '1px solid #eef0f3', background: '#fff', minHeight: 0 }}>
          <Segmented
            size="small"
            value={view}
            onChange={(v) => setView(v as typeof view)}
            options={[
              { value: 'queue', label: `Кандидаты · ${s.counts.reviewable}` },
              { value: 'completeness', label: 'Комплектность' },
              { value: 'usability', label: 'Замеры' },
            ]}
            style={{ margin: 8, alignSelf: 'flex-start', maxWidth: 'calc(100% - 16px)', whiteSpace: 'nowrap' }}
          />
          {view === 'queue' ? (
            <>
              <Flex wrap gap={4} style={{ padding: '0 8px 8px' }}>
                {FILTERS.map((f) => (
                  <Tag.CheckableTag key={f.value} checked={filter === f.value} onChange={() => setFilter(f.value)} style={{ marginInlineEnd: 0, fontSize: 12 }}>
                    {f.label} {counts?.[f.value] ?? 0}
                  </Tag.CheckableTag>
                ))}
              </Flex>
              <QueueList items={visible} selected={selected} onSelect={(fid) => onSelect(fid)} />
            </>
          ) : (
            <Typography.Text type="secondary" style={{ padding: 12, fontSize: 12 }}>
              {view === 'completeness'
                ? 'Статусы комплектности отделены от кандидатов и не требуют решения инспектора.'
                : 'Время на протокол и клики на решение — по данным этой проверки.'}
            </Typography.Text>
          )}
        </Flex>
        {view === 'queue' ? (
          <>
            <div data-viewer style={{ flex: 1, minWidth: 0, padding: 8, display: 'flex', flexDirection: 'column' }}>
              {card.data ? (
                <EvidenceViewer key={card.data.finding_id} card={card.data.evidence_card} group={card.data.finding_group} summary={compareSummary(card.data)} />
              ) : card.error ? (
                <ProblemAlert error={card.error} />
              ) : selected ? (
                <Skeleton active />
              ) : (
                <Result status="success" title="Кандидатов нет" subTitle="В этом протоколе нет строк, требующих решения инспектора." />
              )}
            </div>
            <Flex vertical gap={10} style={{ width: 430, borderLeft: '1px solid #eef0f3', background: '#fff', padding: 12, overflowY: 'auto' }}>
              {card.data ? (
                <>
                  {card.data.open_dispute && (
                    <DisputeBanner dispute={card.data.open_dispute} canDecide={canDecide} busy={busy} onResolve={(r, c) => void resolveDispute(r, c)} />
                  )}
                  <DecisionPanel
                    ref={decisionRef}
                    card={card.data}
                    codes={codes.data}
                    queue={items}
                    panel={panel}
                    setPanel={setPanel}
                    canDecide={canDecide}
                    disabledReason={disabledReason}
                    busy={busy}
                    onSubmit={(d) => void submitDecision(d)}
                  />
                  <CardPanel card={card.data} />
                  <Typography.Text type="secondary" style={{ fontSize: 11.5 }}>
                    Карточка {card.data.navigation.position} из {card.data.navigation.total} · J/K — соседние, N — следующая необработанная
                  </Typography.Text>
                </>
              ) : card.error ? (
                <ProblemAlert error={card.error} />
              ) : !selected ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={s.status === 'FINALIZED' ? 'Протокол финализирован, кандидатов на проверку нет' : 'Нет кандидатов на проверку'}
                  data-testid="no-candidates"
                />
              ) : (
                <Skeleton active />
              )}
            </Flex>
          </>
        ) : (
          <div style={{ flex: 1, padding: 16, overflowY: 'auto', background: '#fff' }}>
            {view === 'completeness' ? <CompletenessPanel pid={pid} /> : <UsabilityPanel pid={pid} />}
          </div>
        )}
      </Flex>
      <FinalizeDialog
        open={finalizeOpen}
        summary={s}
        csrf={csrf}
        onClose={() => setFinalizeOpen(false)}
        onJump={(fid) => {
          setFinalizeOpen(false);
          setFilter('ALL');
          onSelect(fid);
        }}
        onDone={(r) => {
          setFinalizeOpen(false);
          ui.track('FINALIZE_COMMITTED', { payload: { version: r.protocol.version } });
          message.success(`Протокол финализирован: версия ${r.protocol.version}, в «РиН» — ${r.rin.violations} нарушений, черновиков набора данных — ${r.dataset_items}.`);
          void refresh();
        }}
      />
      <UnfinalizeDialog
        open={unfinalizeOpen}
        summary={s}
        codes={codes.data}
        csrf={csrf}
        onClose={() => setUnfinalizeOpen(false)}
        onDone={(r) => {
          setUnfinalizeOpen(false);
          message.success(`Финализация отменена: рабочая версия ${r.protocol.version}, приостановлено черновиков — ${r.suspended_dataset_items}.`);
          void refresh();
        }}
      />
      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}

export { StatusTag };
